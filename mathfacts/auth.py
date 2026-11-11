"""Accounts, sessions, remembered devices, and the sign-in log (spec 5.11).

Only hashes of passwords and remembered-sign-in secrets are stored. Raw
session tokens and remembered secrets exist only in the browser's cookies.
Every function takes an open database connection and never commits; the
request wrapper commits once per request.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Optional

from flask import current_app

from . import clock
from .security import new_token, sha256_hex

DEVICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class DuplicateAccount(Exception):
    def __init__(self, field):
        super().__init__(field)
        self.field = field


def _cfg(name):
    """Config value, unless the administrator saved an override for it."""
    from flask import g

    db = g.get("db")
    if db is not None:
        from . import settings

        override = settings.runtime_override(db, name)
        if override is not None:
            return override
    return current_app.config[name]


# --- Browser / device -------------------------------------------------------


def user_agent_summary(ua: str) -> str:
    ua = ua or ""
    if "Edg/" in ua:
        browser = "Edge"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "Browser"

    if "iPhone" in ua or "iPad" in ua:
        system = "iOS"
    elif "Android" in ua:
        system = "Android"
    elif "Windows" in ua:
        system = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        system = "macOS"
    elif "Linux" in ua:
        system = "Linux"
    else:
        system = "unknown system"
    return f"{browser} on {system}"


def ensure_device(db, cookie_value, ip, ua):
    """Return (device_id, is_new). Creates or refreshes the devices row."""
    now = clock.now()
    is_new = not (cookie_value and DEVICE_ID_RE.match(cookie_value))
    device_id = uuid.uuid4().hex if is_new else cookie_value
    db.execute(
        """
        INSERT INTO devices (id, first_seen_at, last_seen_at, last_ip, user_agent_summary)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            last_ip = excluded.last_ip,
            user_agent_summary = excluded.user_agent_summary
        """,
        (device_id, now, now, ip, user_agent_summary(ua)),
    )
    return device_id, is_new


# --- Sign-in log ------------------------------------------------------------


def record_event(
    db,
    event_type,
    success,
    *,
    account_id=None,
    identifier=None,
    device_id=None,
    remembered_id=None,
    session_id=None,
    ip="",
    ua="",
    reason=None,
):
    """Append one row to the sign-in log. Never pass a password or raw token."""
    from . import settings

    settings.maybe_purge(db)
    db.execute(
        """
        INSERT INTO login_events (
            at, event_type, success, account_id, attempted_identifier, device_id,
            remembered_login_id, session_id, ip, user_agent, user_agent_summary, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clock.now(),
            event_type,
            1 if success else 0,
            account_id,
            identifier.lower() if identifier else None,
            device_id,
            remembered_id,
            session_id,
            ip,
            ua,
            user_agent_summary(ua),
            reason,
        ),
    )


# --- Accounts ---------------------------------------------------------------


def account_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]


def get_account(db, account_id):
    return db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def find_account(db, identifier):
    """Match a username or email, ignoring case. Returns None if no match."""
    if not identifier:
        return None
    return db.execute(
        "SELECT * FROM accounts WHERE email = ? COLLATE NOCASE "
        "OR username = ? COLLATE NOCASE",
        (identifier, identifier),
    ).fetchone()


def register_account(db, email, username, password_hash, display_name):
    """Create an account. The first account becomes the Administrator.

    Uses BEGIN IMMEDIATE so two simultaneous first registrations cannot both
    become the Administrator. Commit first, because earlier writes in this
    request (the rate-limit row, the device row) opened an implicit transaction.
    """
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute(
            "SELECT 1 FROM accounts WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone():
            raise DuplicateAccount("email")
        if db.execute(
            "SELECT 1 FROM accounts WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone():
            raise DuplicateAccount("username")
        role = "admin" if account_count(db) == 0 else "parent"
        cursor = db.execute(
            "INSERT INTO accounts (email, username, display_name, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (email, username, display_name, password_hash, role, clock.now()),
        )
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return cursor.lastrowid, role


def update_display_name(db, account_id, display_name):
    db.execute(
        "UPDATE accounts SET display_name = ? WHERE id = ?", (display_name, account_id)
    )


def update_password_hash(db, account_id, password_hash):
    db.execute(
        "UPDATE accounts SET password_hash = ? WHERE id = ?", (password_hash, account_id)
    )


def set_new_password(db, account_id, password_hash):
    db.execute(
        "UPDATE accounts SET password_hash = ?, must_change_password = 0, "
        "password_reset_expires_at = NULL WHERE id = ?",
        (password_hash, account_id),
    )


def mark_last_login(db, account_id, login_type):
    db.execute(
        "UPDATE accounts SET last_login_at = ?, last_login_type = ? WHERE id = ?",
        (clock.now(), login_type, account_id),
    )


# --- Sign-in limits ---------------------------------------------------------


def _failures_since(db, *, identifier=None, ip=None):
    since = clock.now() - _cfg("SIGNIN_WINDOW_SECONDS")
    if identifier is not None:
        return db.execute(
            "SELECT COUNT(*) FROM login_events WHERE event_type = 'failed_login' "
            "AND attempted_identifier = ? AND at >= ?",
            (identifier.lower(), since),
        ).fetchone()[0]
    return db.execute(
        "SELECT COUNT(*) FROM login_events WHERE event_type = 'failed_login' "
        "AND ip = ? AND at >= ?",
        (ip, since),
    ).fetchone()[0]


def signin_locked(db, identifier, ip) -> bool:
    """True when this identifier or this network has too many recent failures.

    Counts apply whether or not the account exists, so the lock does not reveal
    which usernames are real. The network limit is higher, because a whole
    family often shares one home IP address.
    """
    return (
        _failures_since(db, identifier=identifier) >= _cfg("SIGNIN_FAILURE_LIMIT")
        or _failures_since(db, ip=ip) >= _cfg("SIGNIN_IP_FAILURE_LIMIT")
    )


def register_attempt_limited(db, ip) -> bool:
    now = clock.now()
    bucket = f"register:{ip}"
    db.execute("DELETE FROM rate_events WHERE at < ?", (now - _cfg("REGISTER_WINDOW_SECONDS"),))
    count = db.execute(
        "SELECT COUNT(*) FROM rate_events WHERE bucket = ?", (bucket,)
    ).fetchone()[0]
    db.execute("INSERT INTO rate_events (bucket, at) VALUES (?, ?)", (bucket, now))
    return count >= _cfg("REGISTER_LIMIT")


# --- Sessions ---------------------------------------------------------------


def create_session(db, account_id, device_id, login_type, remembered_id):
    """Return (token, session_id). The token goes in the cookie; only its hash is stored."""
    token = new_token()
    session_id = sha256_hex(token)
    now = clock.now()
    db.execute(
        "INSERT INTO sessions (id, account_id, device_id, login_type, remembered_login_id, "
        "created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            account_id,
            device_id,
            login_type,
            remembered_id,
            now,
            now,
            now + _cfg("SESSION_IDLE_SECONDS"),
        ),
    )
    return token, session_id


def end_session(db, session_id):
    db.execute(
        "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
        (clock.now(), session_id),
    )


def load_session(db, token):
    """Return (account, session_id) for a live session, else (None, None).

    Slides the idle timeout forward on every use.
    """
    if not token:
        return None, None
    session_id = sha256_hex(token)
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    now = clock.now()
    if row is None or row["ended_at"] is not None or row["expires_at"] <= now:
        return None, None
    account = get_account(db, row["account_id"])
    if account is None or account["status"] != "active":
        end_session(db, session_id)
        return None, None
    db.execute(
        "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
        (now, now + _cfg("SESSION_IDLE_SECONDS"), session_id),
    )
    return account, session_id


# --- Remembered devices -----------------------------------------------------


def remembered_id_from_cookie(value) -> Optional[str]:
    if value and "." in value:
        return value.split(".", 1)[0]
    return None


def issue_remembered(db, account_id, device_id):
    """Replace any remembered sign-in on this device. Return (cookie_value, id)."""
    now = clock.now()
    rl_id = new_token(16)
    secret = new_token()
    db.execute(
        "UPDATE remembered_logins SET revoked_at = ?, revoked_reason = 'replaced' "
        "WHERE device_id = ? AND revoked_at IS NULL",
        (now, device_id),
    )
    db.execute(
        "INSERT INTO remembered_logins (id, account_id, device_id, secret_hash, created_at, "
        "last_used_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rl_id, account_id, device_id, sha256_hex(secret), now, now, now + _cfg("REMEMBER_SECONDS")),
    )
    return f"{rl_id}.{secret}", rl_id


def revoke_remembered(db, rl_id, reason):
    db.execute(
        "UPDATE remembered_logins SET revoked_at = ?, revoked_reason = ? "
        "WHERE id = ? AND revoked_at IS NULL",
        (clock.now(), reason, rl_id),
    )


def revoke_other_access(db, account_id, keep_session_id, keep_remembered_id, reason):
    """End every other session and remembered sign-in for this account."""
    now = clock.now()
    db.execute(
        "UPDATE sessions SET ended_at = ? WHERE account_id = ? AND ended_at IS NULL "
        "AND id IS NOT ?",
        (now, account_id, keep_session_id),
    )
    db.execute(
        "UPDATE remembered_logins SET revoked_at = ?, revoked_reason = ? "
        "WHERE account_id = ? AND revoked_at IS NULL AND id IS NOT ?",
        (now, reason, account_id, keep_remembered_id),
    )


# --- Sign-in flows ----------------------------------------------------------


@dataclass
class SignedIn:
    token: str
    session_id: str
    remembered_cookie: str


def start_login(db, account, device_id, ip, ua, event_type) -> SignedIn:
    """Hard login or registration: new session plus a fresh remembered sign-in."""
    remembered_cookie, rl_id = issue_remembered(db, account["id"], device_id)
    token, session_id = create_session(db, account["id"], device_id, "hard", rl_id)
    record_event(
        db,
        event_type,
        True,
        account_id=account["id"],
        device_id=device_id,
        remembered_id=rl_id,
        session_id=session_id,
        ip=ip,
        ua=ua,
    )
    mark_last_login(db, account["id"], "hard")
    return SignedIn(token=token, session_id=session_id, remembered_cookie=remembered_cookie)


@dataclass
class SoftLogin:
    account: object = None
    session_token: Optional[str] = None
    session_id: Optional[str] = None
    remembered_cookie: Optional[str] = None  # set only when the secret rotated
    clear_cookie: bool = False


def soft_login(db, cookie_value, device_id, ip, ua) -> SoftLogin:
    """Sign in from the remembered-device cookie without a password (5.11.3)."""
    result = SoftLogin()
    parts = cookie_value.split(".", 1) if cookie_value else []
    if len(parts) != 2 or not parts[0] or not parts[1]:
        result.clear_cookie = True
        return result

    rl_id, secret = parts
    now = clock.now()
    row = db.execute("SELECT * FROM remembered_logins WHERE id = ?", (rl_id,)).fetchone()
    if row is None or row["revoked_at"] is not None or row["expires_at"] <= now:
        result.clear_cookie = True
        return result

    account = get_account(db, row["account_id"])
    if account is None or account["status"] != "active":
        revoke_remembered(db, rl_id, "account inactive")
        result.clear_cookie = True
        return result

    presented = sha256_hex(secret)
    grace = _cfg("ROTATION_GRACE_SECONDS")
    if presented == row["secret_hash"]:
        rotate = True
    elif (
        row["prev_secret_hash"] is not None
        and presented == row["prev_secret_hash"]
        and row["prev_valid_until"] is not None
        and row["prev_valid_until"] >= now
    ):
        # A second tab used the old secret just after rotation. Allow it,
        # but do not rotate again, so the browser's newest cookie stays valid.
        rotate = False
    else:
        revoke_remembered(db, rl_id, "suspicious cookie")
        record_event(
            db,
            "suspicious_cookie",
            False,
            account_id=account["id"],
            device_id=device_id,
            remembered_id=rl_id,
            ip=ip,
            ua=ua,
            reason="remembered secret did not match",
        )
        result.clear_cookie = True
        return result

    if rotate:
        new_secret = new_token()
        db.execute(
            "UPDATE remembered_logins SET prev_secret_hash = secret_hash, "
            "prev_valid_until = ?, secret_hash = ?, last_used_at = ?, expires_at = ? "
            "WHERE id = ?",
            (now + grace, sha256_hex(new_secret), now, now + _cfg("REMEMBER_SECONDS"), rl_id),
        )
        result.remembered_cookie = f"{rl_id}.{new_secret}"
    else:
        db.execute(
            "UPDATE remembered_logins SET last_used_at = ?, expires_at = ? WHERE id = ?",
            (now, now + _cfg("REMEMBER_SECONDS"), rl_id),
        )

    token, session_id = create_session(db, account["id"], device_id, "soft", rl_id)
    record_event(
        db,
        "soft_login",
        True,
        account_id=account["id"],
        device_id=device_id,
        remembered_id=rl_id,
        session_id=session_id,
        ip=ip,
        ua=ua,
    )
    mark_last_login(db, account["id"], "soft")
    result.account = account
    result.session_token = token
    result.session_id = session_id
    return result


def sign_out(db, account_id, session_id, rt_cookie, device_id, ip, ua):
    """End this session and this device's remembered sign-in (spec 5.11.3)."""
    if session_id:
        end_session(db, session_id)
    rl_id = remembered_id_from_cookie(rt_cookie)
    if rl_id:
        revoke_remembered(db, rl_id, "logout")
    record_event(
        db,
        "logout",
        True,
        account_id=account_id,
        device_id=device_id,
        remembered_id=rl_id,
        session_id=session_id,
        ip=ip,
        ua=ua,
    )
