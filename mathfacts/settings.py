"""Site settings, the audit log, and administrator actions (spec 5.13).

The temporary reset password is encrypted with the app secret so the
administrator can read it back and hand it to someone. It is never hashed,
and it is never written to the sign-in log or the audit log.
"""

import base64
import hashlib
import hmac
import os
from pathlib import Path

from flask import current_app

from . import auth, clock

DEFAULTS = {
    "max_children": 10,
    "login_log_days": 365,
    "idle_hours": 12,
    "remember_days": 365,
    "reset_hours": 72,
}
LIMITS = {
    "max_children": (1, 100),
    "login_log_days": (1, 3650),
    "idle_hours": (1, 168),
    "remember_days": (1, 3650),
    "reset_hours": (1, 720),
}
TERMS_MAX = 20000
PAGE_SIZE = 50
BACKUP_DIR = Path("/home/pi/backups")

# Config names that a saved setting replaces, and the multiplier to seconds.
RUNTIME = {
    "SESSION_IDLE_SECONDS": ("idle_hours", 3600),
    "REMEMBER_SECONDS": ("remember_days", 86400),
}

EVENT_LABELS = {
    "registration": "Registered",
    "hard_login": "Password sign-in",
    "soft_login": "Automatic sign-in",
    "logout": "Signed out",
    "logout_all": "Signed out of all devices",
    "failed_login": "Sign-in failed",
    "lockout": "Locked out",
    "suspicious_cookie": "Suspicious cookie",
    "device_revoked": "Device revoked",
    "password_changed": "Password changed",
    "password_reset_by_admin": "Password reset by administrator",
    "account_inactivated": "Account inactivated",
    "account_reactivated": "Account reactivated",
}
AUDIT_LABELS = {
    "inactivate": "Inactivate",
    "reactivate": "Reactivate",
    "password_reset": "Password reset",
    "settings_change": "Settings change",
    "command_line_reset": "Command-line password reset",
}
LOGIN_LABELS = {"hard": "Password", "soft": "Automatic"}


def get_setting(db, key):
    row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(db, key, value):
    db.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _int_setting(db, key):
    raw = get_setting(db, key)
    if raw and str(raw).isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULTS[key]


def max_children(db):
    return _int_setting(db, "max_children")


def runtime_override(db, name):
    """Seconds for a timeout the administrator changed, or None to use config."""
    spec = RUNTIME.get(name)
    if spec is None:
        return None
    key, factor = spec
    raw = get_setting(db, key)
    if not raw or not str(raw).isdigit() or int(raw) <= 0:
        return None
    return int(raw) * factor


def terms_text(db):
    return get_setting(db, "terms_text") or ""


def _secret_key():
    key = current_app.config.get("SECRET_KEY") or ""
    return hashlib.sha256(key.encode("utf-8")).digest()


def encrypt_text(plain):
    """Encrypt a short secret. The result is text safe to store in SQLite."""
    key = _secret_key()
    nonce = os.urandom(16)
    data = plain.encode("utf-8")
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + cipher).decode("ascii")


def decrypt_text(stored):
    """Return the original text, or None when the value is missing or damaged."""
    if not stored:
        return None
    try:
        raw = base64.urlsafe_b64decode(stored.encode("ascii"))
    except (ValueError, TypeError):
        return None
    if len(raw) < 16 + 32:
        return None
    nonce, mac, cipher = raw[:16], raw[16:48], raw[48:]
    key = _secret_key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        return None
    stream = _keystream(key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")


def _keystream(key, nonce, length):
    out = b""
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        out += block
        counter += 1
    return out[:length]


def temporary_password(db):
    return decrypt_text(get_setting(db, "reset_password"))


def validate_settings(form):
    """Return (clean values, errors). A blank temporary password leaves it as it is."""
    errors = {}
    clean = {}
    for key, (low, high) in LIMITS.items():
        raw = str(form.get(key, "")).strip()
        if not raw.isdigit() or not low <= int(raw) <= high:
            errors[key] = f"Use a whole number from {low} to {high}."
        else:
            clean[key] = int(raw)
    terms = str(form.get("terms_text", "")).strip()
    if len(terms) > TERMS_MAX:
        errors["terms_text"] = f"Use {TERMS_MAX} characters or fewer."
    clean["terms_text"] = terms
    password = str(form.get("temporary_password", ""))
    if password:
        from . import security

        problems = security.password_problems(password)
        if problems:
            errors["temporary_password"] = " ".join(problems)
        else:
            clean["temporary_password"] = password
    return clean, errors


def save_settings(db, admin_id, clean):
    """Store the settings. The temporary password is encrypted and kept out of the audit log."""
    changed = []
    for key in LIMITS:
        set_setting(db, key, str(clean[key]))
        changed.append(key.replace("_", " "))
    set_setting(db, "terms_text", clean["terms_text"])
    changed.append("terms")
    if "temporary_password" in clean:
        set_setting(db, "reset_password", encrypt_text(clean["temporary_password"]))
        changed.append("temporary password")
    record_audit(
        db, admin_id, "settings_change", None,
        "Updated " + ", ".join(changed) + ".",
    )


def record_audit(db, admin_id, event, target_id, detail):
    db.execute(
        """
        INSERT INTO audit_log (at, admin_account_id, event, target_account_id, detail)
        VALUES (?, ?, ?, ?, ?)
        """,
        (clock.now(), admin_id, event, target_id, detail or ""),
    )


def list_accounts(db):
    """Every account with counts only. Names of children are not selected."""
    return db.execute(
        """
        SELECT a.id, a.username, a.email, a.role, a.status, a.created_at,
               a.last_login_at, a.last_login_type,
               (SELECT COUNT(*) FROM children c WHERE c.account_id = a.id) AS child_count,
               (SELECT COUNT(*) FROM worksheets w WHERE w.account_id = a.id) AS sheet_count,
               (SELECT COUNT(DISTINCT r.device_id) FROM remembered_logins r
                 WHERE r.account_id = a.id AND r.revoked_at IS NULL) AS device_count
        FROM accounts a
        ORDER BY a.created_at, a.id
        """
    ).fetchall()


def get_account_row(db, account_id):
    return db.execute(
        "SELECT id, username, email, role, status FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()


def _revoke_all(db, account_id, reason):
    now = clock.now()
    db.execute(
        "UPDATE sessions SET ended_at = ? WHERE account_id = ? AND ended_at IS NULL",
        (now, account_id),
    )
    db.execute(
        "UPDATE remembered_logins SET revoked_at = ?, revoked_reason = ? "
        "WHERE account_id = ? AND revoked_at IS NULL",
        (now, reason, account_id),
    )


def inactivate(db, admin_id, target_id):
    """Return 'self', 'missing', or 'ok'. Data is kept. Sign-ins stop immediately."""
    if admin_id == target_id:
        return "self"
    row = get_account_row(db, target_id)
    if row is None:
        return "missing"
    if row["status"] != "inactive":
        db.execute("UPDATE accounts SET status = 'inactive' WHERE id = ?", (target_id,))
        _revoke_all(db, target_id, "account inactivated")
        auth.record_event(
            db, "account_inactivated", True, account_id=target_id,
            reason="inactivated by administrator",
        )
        record_audit(db, admin_id, "inactivate", target_id, f"Inactivated {row['username']}.")
    return "ok"


def reactivate(db, admin_id, target_id):
    row = get_account_row(db, target_id)
    if row is None:
        return "missing"
    if row["status"] != "active":
        db.execute("UPDATE accounts SET status = 'active' WHERE id = ?", (target_id,))
        auth.record_event(
            db, "account_reactivated", True, account_id=target_id,
            reason="reactivated by administrator",
        )
        record_audit(db, admin_id, "reactivate", target_id, f"Reactivated {row['username']}.")
    return "ok"


def reset_password(db, admin_id, target_id, password):
    """Set a temporary password, force a change, and sign the account out everywhere.

    Returns the account row. The password itself is not stored in either log.
    """
    row = get_account_row(db, target_id)
    if row is None:
        return None
    from . import security

    hours = _int_setting(db, "reset_hours")
    expires = clock.now() + hours * 3600
    db.execute(
        """
        UPDATE accounts
        SET password_hash = ?, must_change_password = 1, password_reset_expires_at = ?
        WHERE id = ?
        """,
        (security.hash_password(password), expires, target_id),
    )
    _revoke_all(db, target_id, "password reset by administrator")
    auth.record_event(
        db, "password_reset_by_admin", True, account_id=target_id,
        reason="temporary password set",
    )
    record_audit(
        db, admin_id, "password_reset", target_id,
        f"Temporary password set for {row['username']}. It expires in {hours} hours.",
    )
    return row


def recover_password(db, username, password):
    """Command-line recovery. Clears the forced-change flag so the person can sign in."""
    from . import security

    row = db.execute(
        "SELECT id, username FROM accounts WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    if row is None:
        return None
    db.execute(
        """
        UPDATE accounts
        SET password_hash = ?, must_change_password = 0, password_reset_expires_at = NULL
        WHERE id = ?
        """,
        (security.hash_password(password), row["id"]),
    )
    _revoke_all(db, row["id"], "command line reset")
    auth.record_event(
        db, "password_changed", True, account_id=row["id"], reason="command line reset",
    )
    record_audit(db, None, "command_line_reset", row["id"], f"Reset {row['username']} from the Pi.")
    return row


def list_devices(db, account_id):
    return db.execute(
        """
        SELECT r.id, r.label, r.last_used_at, r.revoked_at, r.expires_at,
               d.id AS device_id, d.user_agent_summary, d.last_ip
        FROM remembered_logins r
        JOIN devices d ON d.id = r.device_id
        WHERE r.account_id = ?
        ORDER BY r.last_used_at DESC
        """,
        (account_id,),
    ).fetchall()


def revoke_device(db, account_id, remembered_id):
    row = db.execute(
        """
        SELECT r.id, r.revoked_at, d.id AS device_id
        FROM remembered_logins r
        JOIN devices d ON d.id = r.device_id
        WHERE r.id = ? AND r.account_id = ?
        """,
        (remembered_id, account_id),
    ).fetchone()
    if row is None:
        return None
    if row["revoked_at"] is None:
        auth.revoke_remembered(db, remembered_id, "revoked by administrator")
        now = clock.now()
        db.execute(
            "UPDATE sessions SET ended_at = ? WHERE account_id = ? AND device_id = ? "
            "AND ended_at IS NULL",
            (now, account_id, row["device_id"]),
        )
        auth.record_event(
            db, "device_revoked", True, account_id=account_id,
            device_id=row["device_id"], remembered_id=remembered_id,
            reason="revoked by administrator",
        )
    return row


def _login_where(account_id, device, event, date_from, date_to):
    where = ["1 = 1"]
    args = []
    if account_id:
        where.append("e.account_id = ?")
        args.append(account_id)
    if device:
        where.append("e.device_id LIKE ?")
        args.append(f"%{device}%")
    if event:
        where.append("e.event_type = ?")
        args.append(event)
    if date_from:
        where.append("e.at >= ?")
        args.append(clock.start_of_day(date_from))
    if date_to:
        where.append("e.at < ?")
        args.append(clock.start_of_day(date_to) + 86400)
    return " AND ".join(where), args


def list_login_events(db, *, account_id=None, device="", event="", date_from=None,
                      date_to=None, page=1, limit=PAGE_SIZE):
    where, args = _login_where(account_id, device.strip(), event, date_from, date_to)
    total = db.execute(
        f"SELECT COUNT(*) FROM login_events e WHERE {where}", args
    ).fetchone()[0]
    offset = max(0, page - 1) * limit
    rows = db.execute(
        f"""
        SELECT e.*, a.username
        FROM login_events e
        LEFT JOIN accounts a ON a.id = e.account_id
        WHERE {where}
        ORDER BY e.at DESC, e.id DESC
        LIMIT ? OFFSET ?
        """,
        (*args, limit, offset),
    ).fetchall()
    return rows, total


def list_audit(db, *, date_from=None, date_to=None, page=1):
    where = ["1 = 1"]
    args = []
    if date_from:
        where.append("g.at >= ?")
        args.append(clock.start_of_day(date_from))
    if date_to:
        where.append("g.at < ?")
        args.append(clock.start_of_day(date_to) + 86400)
    sql_where = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM audit_log g WHERE {sql_where}", args).fetchone()[0]
    offset = max(0, page - 1) * PAGE_SIZE
    rows = db.execute(
        f"""
        SELECT g.*, admin.username AS admin_name, target.username AS target_name
        FROM audit_log g
        LEFT JOIN accounts admin ON admin.id = g.admin_account_id
        LEFT JOIN accounts target ON target.id = g.target_account_id
        WHERE {sql_where}
        ORDER BY g.at DESC, g.id DESC
        LIMIT ? OFFSET ?
        """,
        (*args, PAGE_SIZE, offset),
    ).fetchall()
    return rows, total


def maybe_purge(db):
    """Drop sign-in history older than the retention window, at most once a day."""
    last = get_setting(db, "last_purge_at")
    now = clock.now()
    if last and last.isdigit() and now - int(last) < 86400:
        return
    cutoff = now - _int_setting(db, "login_log_days") * 86400
    db.execute("DELETE FROM login_events WHERE at < ?", (cutoff,))
    db.execute(
        "DELETE FROM sessions WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,)
    )
    db.execute(
        "DELETE FROM remembered_logins WHERE revoked_at IS NOT NULL AND revoked_at < ?",
        (cutoff,),
    )
    db.execute("DELETE FROM remembered_logins WHERE expires_at < ?", (cutoff,))
    set_setting(db, "last_purge_at", str(now))


def site_status(db, database_path):
    path = Path(database_path)
    size = path.stat().st_size if path.exists() else 0
    backup = None
    if BACKUP_DIR.is_dir():
        files = [item for item in BACKUP_DIR.glob("mathfacts*.db") if item.is_file()]
        if files:
            newest = max(files, key=lambda item: item.stat().st_mtime)
            backup = clock.format_stamp(int(newest.stat().st_mtime))
    accounts = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    return {
        "size": _format_size(size),
        "backup": backup,
        "version": current_app.config.get("APP_VERSION", ""),
        "accounts": accounts,
    }


def _format_size(size):
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024)) if size else 0} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def form_values(db):
    values = {key: str(_int_setting(db, key)) for key in LIMITS}
    values["terms_text"] = terms_text(db)
    values["temporary_password"] = temporary_password(db) or ""
    return values
