"""Registration, sign-in, sign-out, password change, and public pages (spec 5.11)."""

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from . import auth, security
from .sessions import cookie_options, get_db, queue_cookie, queue_delete

bp = Blueprint("auth", __name__)

THEMES = ("light", "dark", "auto")

# Wording chosen so that unknown usernames and wrong passwords look the same.
GENERIC_SIGNIN_ERROR = "That username or password is not right."
LOCKED_ERROR = "Sign-in is paused after several failed attempts. Try again in about 15 minutes."
INACTIVE_ERROR = "This account is inactive. Contact your administrator."
REGISTER_LIMIT_ERROR = "Too many sign-up attempts from this network. Try again later."


def safe_next(value, default):
    """Allow only a path on this site, so sign-in cannot redirect elsewhere."""
    if value and value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    return default


def _client():
    return request.remote_addr or "", request.headers.get("User-Agent", "")


def _signed_in_redirect():
    return redirect(url_for("web.index"))


def _queue_session_cookies(signed_in):
    queue_cookie("sid", signed_in.token, **cookie_options())
    queue_cookie(
        "rt", signed_in.remembered_cookie,
        **cookie_options(max_age=current_app.config["REMEMBER_SECONDS"]),
    )


# --- Public pages -----------------------------------------------------------


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.account is not None:
        return _signed_in_redirect()

    db = get_db()
    ip, ua = _client()
    first_run = auth.account_count(db) == 0

    if request.method == "GET":
        return render_template(
            "register.html", first_run=first_run, values={}, errors={}
        )

    values = {
        "email": request.form.get("email", "").strip(),
        "username": request.form.get("username", "").strip(),
    }
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    if auth.register_attempt_limited(db, ip):
        return render_template(
            "register.html", first_run=first_run, values=values,
            errors={"form": REGISTER_LIMIT_ERROR},
        ), 429

    if request.form.get("website"):
        # Honeypot: real people never see this field.
        return render_template(
            "register.html", first_run=first_run, values=values,
            errors={"form": "Registration could not be completed."},
        ), 400

    errors = {}
    if not security.valid_email(values["email"]):
        errors["email"] = "Enter a valid email address."
    if not security.valid_username(values["username"]):
        errors["username"] = (
            "Use 3 to 30 letters, numbers, underscores, dashes, or periods."
        )
    problems = security.password_problems(password, values["username"], values["email"])
    if problems:
        errors["password"] = " ".join(problems)
    if password != confirm:
        errors["confirm"] = "The passwords do not match."
    if not request.form.get("guardian"):
        errors["guardian"] = (
            "Confirm that you are a parent or legal guardian and accept the terms."
        )
    if errors:
        return render_template(
            "register.html", first_run=first_run, values=values, errors=errors
        ), 400

    try:
        account_id, _role = auth.register_account(
            db, values["email"], values["username"], security.hash_password(password)
        )
    except auth.DuplicateAccount as duplicate:
        if duplicate.field == "email":
            message = "That email is already registered."
        else:
            message = "That username is already taken."
        errors[duplicate.field] = message
        return render_template(
            "register.html", first_run=first_run, values=values, errors=errors
        ), 400

    account = auth.get_account(db, account_id)
    signed_in = auth.start_login(db, account, g.device_id, ip, ua, "registration")
    _queue_session_cookies(signed_in)
    return redirect(url_for("auth.welcome"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.account is not None:
        return _signed_in_redirect()

    db = get_db()
    ip, ua = _client()
    next_url = safe_next(request.values.get("next"), url_for("web.index"))

    if request.method == "GET":
        return render_template("login.html", errors={}, values={}, next_url=next_url)

    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "")
    values = {"identifier": identifier}

    if auth.signin_locked(db, identifier, ip):
        auth.record_event(
            db, "lockout", False, identifier=identifier, device_id=g.device_id,
            ip=ip, ua=ua, reason="too many failed attempts",
        )
        return render_template(
            "login.html", errors={"form": LOCKED_ERROR}, values=values, next_url=next_url
        ), 429

    account = auth.find_account(db, identifier)
    if account is None:
        security.burn_time(password)
        auth.record_event(
            db, "failed_login", False, identifier=identifier, device_id=g.device_id,
            ip=ip, ua=ua, reason="unknown account",
        )
        return render_template(
            "login.html", errors={"form": GENERIC_SIGNIN_ERROR}, values=values,
            next_url=next_url,
        ), 401

    matches, needs_rehash = security.verify_password(account["password_hash"], password)
    if not matches:
        auth.record_event(
            db, "failed_login", False, account_id=account["id"], identifier=identifier,
            device_id=g.device_id, ip=ip, ua=ua, reason="wrong password",
        )
        return render_template(
            "login.html", errors={"form": GENERIC_SIGNIN_ERROR}, values=values,
            next_url=next_url,
        ), 401

    if account["status"] != "active":
        auth.record_event(
            db, "failed_login", False, account_id=account["id"], identifier=identifier,
            device_id=g.device_id, ip=ip, ua=ua, reason="inactive account",
        )
        return render_template(
            "login.html", errors={"form": INACTIVE_ERROR}, values=values,
            next_url=next_url,
        ), 403

    if needs_rehash:
        auth.update_password_hash(db, account["id"], security.hash_password(password))

    signed_in = auth.start_login(db, account, g.device_id, ip, ua, "hard_login")
    _queue_session_cookies(signed_in)
    if account["must_change_password"]:
        return redirect(url_for("auth.change_password"))
    return redirect(next_url)


@bp.post("/logout")
def logout():
    ip, ua = _client()
    if g.account is not None:
        auth.sign_out(
            get_db(), g.account["id"], g.session_id, request.cookies.get("rt"),
            g.device_id, ip, ua,
        )
    queue_delete("sid")
    queue_delete("rt")
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@bp.route("/terms")
def terms():
    return render_template("terms.html")


@bp.post("/appearance")
def appearance():
    theme = request.form.get("theme", "auto")
    if theme not in THEMES:
        abort(400)
    queue_cookie(
        "theme", theme,
        **cookie_options(max_age=current_app.config["THEME_COOKIE_SECONDS"]),
    )
    return redirect(safe_next(request.form.get("next"), "/"))


# --- Signed-in pages --------------------------------------------------------


@bp.route("/welcome")
def welcome():
    return render_template("welcome.html")


@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    account = g.account
    forced = bool(account["must_change_password"])

    if request.method == "GET":
        return render_template("change_password.html", forced=forced, errors={})

    db = get_db()
    ip, ua = _client()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm", "")
    errors = {}

    if not forced:
        ok, _ = security.verify_password(account["password_hash"], current)
        if not ok:
            errors["current"] = "That is not your current password."

    problems = security.password_problems(new, account["username"], account["email"])
    if problems:
        errors["new"] = " ".join(problems)
    elif security.verify_password(account["password_hash"], new)[0]:
        errors["new"] = "Choose a password that is different from the current one."
    if new != confirm:
        errors["confirm"] = "The passwords do not match."
    if errors:
        return render_template("change_password.html", forced=forced, errors=errors), 400

    auth.set_new_password(db, account["id"], security.hash_password(new))
    auth.revoke_other_access(
        db,
        account["id"],
        keep_session_id=g.session_id,
        keep_remembered_id=auth.remembered_id_from_cookie(request.cookies.get("rt")),
        reason="password changed",
    )
    auth.record_event(
        db, "password_changed", True, account_id=account["id"], device_id=g.device_id,
        session_id=g.session_id, ip=ip, ua=ua,
    )
    flash("Your password has been changed. Other devices were signed out.")
    return redirect(url_for("web.index"))
