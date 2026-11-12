"""Application factory.

Phase 1 runs as one Flask app behind nginx on the Pi (spec section 8). ProxyFix
makes the client address come from nginx's X-Forwarded-For header, so the
sign-in limits see real clients rather than 127.0.0.1.
"""


from flask import Flask, g, request
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db as database
from .config import Config
from .routes_admin import bp as admin_bp
from .routes_plans import bp as plans_bp
from .routes_progress import bp as progress_bp
from .routes_auth import bp as auth_bp
from .routes_children import bp as children_bp
from .routes_sheets import bp as sheets_bp
from .sessions import install as install_sessions
from .web import bp as web_bp

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    if not app.config["SECRET_KEY"] and not app.testing:
        raise RuntimeError(
            "SECRET_KEY is not set. Put it in instance/mathfacts.env or the environment."
        )

    # One address hop: nginx on the same machine.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    database.init_db(app.config["DATABASE"])
    _seed_library(app)
    csrf.init_app(app)
    install_sessions(app)
    app.register_blueprint(web_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(children_bp)
    app.register_blueprint(sheets_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(progress_bp)

    @app.context_processor
    def inject_common():
        theme = request.cookies.get("theme", "auto")
        if theme not in ("light", "dark", "auto"):
            theme = "auto"
        account = g.get("account")
        nav_kids, nav_child = [], None
        if account is not None and not account["must_change_password"]:
            nav_kids, nav_child = _nav_children(account["id"])
        return {
            "theme": theme,
            "current_account": account,
            "nav_kids": nav_kids,
            "nav_child": nav_child,
        }

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint != "static":
            # Pages hold private data, so browsers must not keep them.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app


def _nav_children(account_id):
    """Active children for the header child menu, and the one last chosen."""
    from . import children, sheets
    from .sessions import get_db

    db = get_db()
    kids = children.list_children(db, account_id)
    if not kids:
        return [], None
    saved = sheets.get_pref(db, account_id, "last_child_id")
    chosen = next((k for k in kids if saved and str(k["id"]) == saved), kids[0])
    return kids, chosen


def _seed_library(app):
    """System plans and badges. Safe to run on every start."""
    from .catalog import seed
    conn = database.connect(app.config["DATABASE"])
    try:
        seed(conn)
        conn.commit()
    finally:
        conn.close()
