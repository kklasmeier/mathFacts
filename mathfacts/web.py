"""Public health check and the signed-in home page."""

from flask import Blueprint, g, jsonify, render_template, request

from . import children, clock, ratings, sheets
from .sessions import get_db

bp = Blueprint("web", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/")
def index():
    db = get_db()
    account_id = g.account["id"]
    kids = children.list_children(db, account_id)
    child = None
    recent = []
    unfinished = 0
    if kids:
        chosen = request.args.get("child", "")
        active_ids = {k["id"] for k in kids}
        if chosen.isdigit() and int(chosen) in active_ids:
            child_id = int(chosen)
            sheets.set_pref(db, account_id, "last_child_id", str(child_id))
        else:
            saved = sheets.get_pref(db, account_id, "last_child_id")
            if saved and saved.isdigit() and int(saved) in active_ids:
                child_id = int(saved)
            else:
                child_id = kids[0]["id"]
                sheets.set_pref(db, account_id, "last_child_id", str(child_id))
        child = next(k for k in kids if k["id"] == child_id)
        rows, _total = sheets.list_sheets(db, account_id, child_id=child_id)
        recent = rows[:5]
        unfinished = sheets.unfinished_count(db, account_id, child_id)
    return render_template(
        "home.html",
        kids=kids,
        child=child,
        recent=recent,
        unfinished=unfinished,
        performance_label=ratings.performance_label,
        support_label=ratings.support_label,
        format_day=clock.format_day,
        local_date=clock.local_date,
        parse_date=clock.parse_date,
    )
