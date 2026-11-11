"""Administrator pages (spec 5.13). A parent who opens these gets 404.

The accounts list has counts only. Nothing here loads another family's
children, sheets, ratings, or notes.
"""

import csv
import io

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask import Response

from . import clock, security, settings
from .sessions import get_db

bp = Blueprint("admin", __name__)


def _admin():
    if g.account is None or g.account["role"] != "admin":
        abort(404)
    return g.account


def _account_or_404(db, account_id):
    row = settings.get_account_row(db, account_id)
    if row is None:
        abort(404)
    return row


def _page():
    raw = request.args.get("page", "1")
    return int(raw) if raw.isdigit() and int(raw) > 0 else 1


@bp.route("/admin", methods=["GET", "POST"])
def index():
    admin = _admin()
    db = get_db()
    status = settings.site_status(db, _database_path())
    if request.method == "GET":
        return render_template(
            "admin_status.html",
            values=settings.form_values(db),
            errors={},
            status=status,
        )

    clean, errors = settings.validate_settings(request.form)
    if errors:
        posted = {
            key: request.form.get(key, "")
            for key in (*settings.LIMITS, "terms_text", "temporary_password")
        }
        return render_template(
            "admin_status.html", values=posted, errors=errors, status=status,
        ), 400

    settings.save_settings(db, admin["id"], clean)
    flash("Site settings saved.")
    return redirect(url_for("admin.index"))


def _database_path():
    from flask import current_app

    return current_app.config["DATABASE"]


@bp.get("/admin/accounts")
def accounts():
    _admin()
    db = get_db()
    return render_template(
        "admin_accounts.html",
        rows=settings.list_accounts(db),
        has_temporary=bool(settings.temporary_password(db)),
        format_stamp=clock.format_stamp,
        format_day=clock.format_day,
        local_date=clock.local_date,
        login_labels=settings.LOGIN_LABELS,
    )


@bp.post("/admin/accounts/<int:account_id>/inactivate")
def inactivate(account_id):
    admin = _admin()
    db = get_db()
    row = _account_or_404(db, account_id)
    if account_id == admin["id"]:
        flash("You cannot inactivate your own account.")
        return redirect(url_for("admin.accounts"))
    if request.form.get("confirm") != "yes":
        return render_template(
            "admin_confirm.html",
            title=f"Inactivate {row['username']}?",
            body="They cannot sign in until you reactivate the account. Their children, sheets, and ratings stay.",
            action=url_for("admin.inactivate", account_id=account_id),
            label="Inactivate",
        )
    outcome = settings.inactivate(db, admin["id"], account_id)
    if outcome == "self":
        flash("You cannot inactivate your own account.")
        return redirect(url_for("admin.accounts"))
    flash(f"Inactivated {row['username']}.")
    return redirect(url_for("admin.accounts"))


@bp.post("/admin/accounts/<int:account_id>/reactivate")
def reactivate(account_id):
    admin = _admin()
    db = get_db()
    row = _account_or_404(db, account_id)
    if request.form.get("confirm") != "yes":
        return render_template(
            "admin_confirm.html",
            title=f"Reactivate {row['username']}?",
            body="They can sign in with their password. Remembered sign-ins stay revoked, so the next sign-in uses a password.",
            action=url_for("admin.reactivate", account_id=account_id),
            label="Reactivate",
        )
    settings.reactivate(db, admin["id"], account_id)
    flash(f"Reactivated {row['username']}.")
    return redirect(url_for("admin.accounts"))


@bp.route("/admin/accounts/<int:account_id>/reset", methods=["GET", "POST"])
def reset(account_id):
    admin = _admin()
    db = get_db()
    row = _account_or_404(db, account_id)
    current = settings.temporary_password(db)
    if not current:
        flash("Set a temporary password in site settings before resetting an account.")
        return redirect(url_for("admin.index"))

    if request.method == "GET":
        return render_template(
            "admin_reset.html", account=row, errors={}, use_site=True,
        )

    use_site = request.form.get("choice", "site") != "once"
    password = current if use_site else request.form.get("once_password", "")
    errors = {}
    if not use_site:
        problems = security.password_problems(password, row["username"], row["email"])
        if problems:
            errors["once_password"] = " ".join(problems)
    if errors:
        return render_template(
            "admin_reset.html", account=row, errors=errors, use_site=False,
        ), 400

    settings.reset_password(db, admin["id"], account_id, password)
    return render_template(
        "admin_reset_done.html", account=row, password=password,
    )


@bp.get("/admin/accounts/<int:account_id>/devices")
def devices(account_id):
    _admin()
    db = get_db()
    row = _account_or_404(db, account_id)
    return render_template(
        "admin_devices.html",
        account=row,
        devices=settings.list_devices(db, account_id),
        format_stamp=clock.format_stamp,
    )


@bp.post("/admin/accounts/<int:account_id>/revoke")
def revoke(account_id):
    _admin()
    db = get_db()
    _account_or_404(db, account_id)
    remembered_id = request.form.get("remembered_id", "")
    if settings.revoke_device(db, account_id, remembered_id) is None:
        abort(404)
    flash("That device must sign in with a password next time.")
    return redirect(url_for("admin.devices", account_id=account_id))


def _log_filters():
    account = request.args.get("account", "")
    account_id = int(account) if account.isdigit() else None
    event = request.args.get("event", "")
    if event not in settings.EVENT_LABELS:
        event = ""
    return {
        "account_id": account_id,
        "account": account if account_id else "",
        "device": request.args.get("device", "").strip(),
        "event": event,
        "date_from": clock.parse_date(request.args.get("date_from", "")),
        "date_to": clock.parse_date(request.args.get("date_to", "")),
    }


@bp.get("/admin/logins")
def logins():
    _admin()
    db = get_db()
    filters = _log_filters()
    page = _page()
    rows, total = settings.list_login_events(db, page=page, **{
        "account_id": filters["account_id"],
        "device": filters["device"],
        "event": filters["event"],
        "date_from": filters["date_from"],
        "date_to": filters["date_to"],
    })
    pages = max(1, (total + settings.PAGE_SIZE - 1) // settings.PAGE_SIZE)
    return render_template(
        "admin_logins.html",
        rows=rows,
        accounts=settings.list_accounts(db),
        filters={
            "account": filters["account"],
            "device": filters["device"],
            "event": filters["event"],
            "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
            "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
        },
        events=settings.EVENT_LABELS,
        page=page,
        pages=pages,
        previous=_page_url(page - 1) if page > 1 else None,
        next_url=_page_url(page + 1) if page < pages else None,
        format_stamp=clock.format_stamp,
    )


@bp.get("/admin/logins.csv")
def logins_csv():
    _admin()
    db = get_db()
    filters = _log_filters()
    rows, _total = settings.list_login_events(
        db,
        account_id=filters["account_id"],
        device=filters["device"],
        event=filters["event"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
        page=1,
        limit=5000,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["time", "event", "account", "attempted", "device", "ip", "browser", "success", "reason"])
    for row in rows:
        writer.writerow([
            clock.format_stamp(row["at"]),
            settings.EVENT_LABELS.get(row["event_type"], row["event_type"]),
            row["username"] or "",
            row["attempted_identifier"] or "",
            row["device_id"] or "",
            row["ip"] or "",
            row["user_agent_summary"] or "",
            "yes" if row["success"] else "no",
            row["reason"] or "",
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sign-in-log.csv"},
    )


@bp.get("/admin/audit")
def audit():
    _admin()
    db = get_db()
    date_from = clock.parse_date(request.args.get("date_from", ""))
    date_to = clock.parse_date(request.args.get("date_to", ""))
    page = _page()
    rows, total = settings.list_audit(db, date_from=date_from, date_to=date_to, page=page)
    pages = max(1, (total + settings.PAGE_SIZE - 1) // settings.PAGE_SIZE)
    return render_template(
        "admin_audit.html",
        rows=rows,
        filters={
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
        labels=settings.AUDIT_LABELS,
        page=page,
        pages=pages,
        previous=_page_url(page - 1) if page > 1 else None,
        next_url=_page_url(page + 1) if page < pages else None,
        format_stamp=clock.format_stamp,
    )


def _page_url(number):
    args = request.args.to_dict()
    args["page"] = number
    return url_for(request.endpoint, **args)
