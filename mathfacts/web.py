"""Public health check and the signed-in home page."""

from flask import Blueprint, g, jsonify, render_template, request

from . import badges, children, clock, plans, ratings, sheets
from .pools import OPERATIONS, SYMBOL
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
        for row in plans.child_plans(db, account_id, child_id):
            plans.ensure_open_sheet(db, account_id, child_id, row["plan_id"])
        rows, _total = sheets.list_sheets(db, account_id, child_id=child_id)
        recent = [row for row in rows if row["plan_stage_id"] is None][:5]
        unfinished = sheets.unfinished_count(db, account_id, child_id)
    plan_cards = []
    pending_badges = 0
    if child:
        for row in plans.child_plans(db, account_id, child["id"]):
            waiting = None
            if row["current_stage_id"]:
                waiting = plans.open_sheet(
                    db, child["id"], row["current_stage_id"], row["stage_started_at"]
                )
            tally = plans.stage_tally(
                db, child["id"], row["current_stage_id"], row["stage_started_at"]
            )
            plan_cards.append({
                "row": row,
                "ready": plans.show_ready(row),
                "stages": plans.stages(db, row["plan_id"]),
                "waiting": waiting,
                "done": tally["done"],
                "minimum": tally["minimum"],
            })
        pending_badges = badges.pending_count(db, child["id"])
    return render_template(
        "home.html",
        kids=kids,
        child=child,
        recent=recent,
        unfinished=unfinished,
        plan_cards=plan_cards,
        pending_badges=pending_badges,
        operations=OPERATIONS,
        symbols=SYMBOL,
        performance_label=ratings.performance_label,
        support_label=ratings.support_label,
        format_day=clock.format_day,
        local_date=clock.local_date,
        parse_date=clock.parse_date,
    )
