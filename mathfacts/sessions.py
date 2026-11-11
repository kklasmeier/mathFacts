"""Per-request sign-in state: device cookie, session, soft sign-in, and page guards.

Order for every request (spec section 8, step 13):
1. Ensure a device cookie and devices row.
2. If a live session cookie exists, use it.
3. Otherwise, if a remembered-sign-in cookie exists, try a soft sign-in.
4. Otherwise a protected page redirects to Sign in.
5. A forced password change redirects everything except the change page.
"""

from flask import current_app, g, redirect, request, url_for

from . import auth
from .db import connect

# Pages that anyone can open.
PUBLIC_ENDPOINTS = {
    "web.health",
    "static",
    "auth.register",
    "auth.login",
    "auth.forgot_password",
    "auth.terms",
    "auth.appearance",
}
# Pages that work whether or not someone is signed in.
ANY_STATE_ENDPOINTS = {"auth.logout"}
# Pages allowed while a forced password change is pending.
FORCED_CHANGE_ENDPOINTS = {"auth.change_password", "auth.logout", "web.health", "static"}


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def cookie_options(max_age=None, httponly=True):
    return {
        "path": "/",
        "max_age": max_age,
        "httponly": httponly,
        "samesite": "Lax",
        "secure": current_app.config["COOKIE_SECURE"],
    }


def queue_cookie(name, value, **options):
    g.setdefault("cookies", []).append((name, value, options))


def queue_delete(name):
    g.setdefault("cookies", []).append((name, None, {}))


def _next_path():
    query = request.query_string.decode("utf-8")
    return request.path + (f"?{query}" if query else "")


def _load_request_state():
    g.account = None
    g.session_id = None
    g.device_id = None

    if request.endpoint == "static":
        return None

    db = get_db()
    ip = request.remote_addr or ""
    ua = request.headers.get("User-Agent", "")

    device_id, is_new = auth.ensure_device(db, request.cookies.get("did"), ip, ua)
    g.device_id = device_id
    if is_new:
        queue_cookie(
            "did", device_id,
            **cookie_options(max_age=current_app.config["DEVICE_COOKIE_SECONDS"]),
        )

    session_cookie = request.cookies.get("sid")
    account, session_id = auth.load_session(db, session_cookie)
    if account is not None:
        g.account, g.session_id = account, session_id
    elif session_cookie:
        queue_delete("sid")

    if g.account is None and request.cookies.get("rt"):
        result = auth.soft_login(db, request.cookies["rt"], device_id, ip, ua)
        if result.account is not None:
            g.account, g.session_id = result.account, result.session_id
            queue_cookie("sid", result.session_token, **cookie_options())
            if result.remembered_cookie:
                queue_cookie(
                    "rt", result.remembered_cookie,
                    **cookie_options(max_age=current_app.config["REMEMBER_SECONDS"]),
                )
        elif result.clear_cookie:
            queue_delete("rt")

    endpoint = request.endpoint
    if endpoint is None or endpoint in PUBLIC_ENDPOINTS or endpoint in ANY_STATE_ENDPOINTS:
        return None
    if g.account is None:
        return redirect(url_for("auth.login", next=_next_path()))
    if g.account["must_change_password"] and endpoint not in FORCED_CHANGE_ENDPOINTS:
        return redirect(url_for("auth.change_password"))
    return None


def _finish_request(response):
    for name, value, options in g.pop("cookies", []):
        if value is None:
            response.delete_cookie(name, path="/")
        else:
            response.set_cookie(name, value, **options)
    db = g.get("db")
    if db is not None:
        db.commit()
    return response


def install(app):
    app.before_request(_load_request_state)
    app.after_request(_finish_request)
    app.teardown_appcontext(close_db)
