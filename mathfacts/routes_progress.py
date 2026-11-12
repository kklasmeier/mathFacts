"""Progress pages and the badge collection (spec 5.5, 5.7.5)."""

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from . import badges, children, clock, plans, progress
from .pools import OPERATIONS, SYMBOL
from .sessions import get_db

bp = Blueprint("progress", __name__)


def _child_or_404(db, child_id):
    child = children.get_child(db, g.account["id"], child_id)
    if child is None:
        abort(404)
    return child


def _rows(db, child_id):
    return db.execute(
        """
        SELECT w.id, w.operation, w.plan_stage_id, w.created_at, w.title,
               r.performance, r.support, r.pace, r.completed_at
        FROM worksheets w
        JOIN ratings r ON r.worksheet_id = w.id
        WHERE w.child_id = ? AND w.status = 'completed'
        ORDER BY r.completed_at, w.created_at, w.id
        """,
        (child_id,),
    ).fetchall()


@bp.get("/children/<int:child_id>/progress")
def show(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    range_key = request.args.get("range", "30")
    if range_key not in progress.RANGES:
        range_key = "30"
    operation = request.args.get("op", "")
    if operation not in OPERATIONS:
        operation = ""
    tab = request.args.get("tab", "overview")
    if tab not in progress.TABS:
        tab = "overview"
    today = clock.local_date()
    rows = progress.filter_rows(_rows(db, child_id), today, range_key, operation)
    journey = _journey(db, child_id)
    return render_template(
        "progress.html",
        child=child,
        tab=tab,
        range_key=range_key,
        operation=operation,
        ranges=progress.RANGE_LABELS,
        operations=OPERATIONS,
        symbols=SYMBOL,
        tabs=progress.TABS,
        overview=progress.overview(rows, today),
        series=progress.performance_chart(rows),
        rating_stacks=progress.stacks(rows, "performance"),
        support_stacks=progress.stacks(rows, "support"),
        by_operation=progress.by_operation(rows),
        note=progress.independence_note(rows),
        pace=progress.pace_points(rows),
        calendar=progress.calendar(rows, today),
        weeks=progress.sheets_per_week(rows),
        journey=journey,
        coverage=progress.coverage(_coverage(db, child_id, operation or "mul"), operation or "mul"),
        milestones=_milestones(db, child_id),
        badge_count=_badge_count(db, child_id),
    )


def _badge_count(db, child_id):
    return db.execute(
        "SELECT COUNT(*) FROM child_badges WHERE child_id = ?", (child_id,)
    ).fetchone()[0]


def _journey(db, child_id):
    cards = []
    for row in plans.child_plans(db, g.account["id"], child_id):
        history = db.execute(
            """
            SELECT stage_id, exit_reason, exited_at FROM stage_history
            WHERE child_id = ? AND plan_id = ? AND exit_reason = 'advanced'
            """,
            (child_id, row["plan_id"]),
        ).fetchall()
        done = {item["stage_id"] for item in history}
        tally = plans.stage_tally(
            db, child_id, row["current_stage_id"], row["stage_started_at"]
        )
        cards.append({
            "name": row["plan_name"],
            "operation": OPERATIONS[row["operation"]],
            "stages": plans.stages(db, row["plan_id"]),
            "current": row["current_stage_id"],
            "done_ids": done,
            "finished": row["finished"],
            "sheets_done": tally["done"],
            "minimum": tally["minimum"],
        })
    return cards


def _milestones(db, child_id):
    events = []
    for row in db.execute(
        """
        SELECT h.exited_at AS at, s.name
        FROM stage_history h
        LEFT JOIN plan_stages s ON s.id = h.stage_id
        WHERE h.child_id = ? AND h.exit_reason = 'advanced' AND h.exited_at IS NOT NULL
        """,
        (child_id,),
    ):
        events.append({"at": row["at"], "text": f"Passed {row['name'] or 'a stage'}"})
    for row in db.execute(
        """
        SELECT cb.earned_at AS at, b.name
        FROM child_badges cb
        JOIN badges b ON b.id = cb.badge_id
        WHERE cb.child_id = ?
        """,
        (child_id,),
    ):
        events.append({"at": row["at"], "text": f"Badge: {row['name']}"})
    events.sort(key=lambda item: item["at"], reverse=True)
    return events


def _coverage(db, child_id, operation):
    rows = db.execute(
        """
        SELECT p.a, p.b, r.performance, r.support, w.created_at
        FROM worksheet_problems p
        JOIN worksheets w ON w.id = p.worksheet_id
        JOIN ratings r ON r.worksheet_id = w.id
        WHERE w.child_id = ? AND w.operation = ? AND w.status = 'completed'
        ORDER BY w.created_at DESC, w.id DESC
        """,
        (child_id, operation),
    ).fetchall()
    grouped = {}
    for row in rows:
        key = (row["a"], row["b"])
        grouped.setdefault(key, [])
        if len(grouped[key]) < 3:
            grouped[key].append({"performance": row["performance"], "support": row["support"]})
    return grouped


@bp.get("/children/<int:child_id>/badges")
def badges_page(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    category = request.args.get("category", "")
    rows = badges.collection(db, child_id, g.account["id"])
    if category:
        rows = [row for row in rows if row["category"] == category]
    return render_template(
        "badges.html",
        child=child,
        rows=rows,
        category=category,
        format_stamp=clock.format_stamp,
    )


@bp.get("/admin/library")
def admin_library():
    if g.account is None or g.account["role"] != "admin":
        abort(404)
    db = get_db()
    return render_template(
        "admin_library.html",
        plans=plans.system_plans(db),
        stages={plan["id"]: plans.stages(db, plan["id"]) for plan in plans.system_plans(db)},
        badges=db.execute(
            "SELECT name, description, category FROM badges WHERE account_id IS NULL ORDER BY category, name"
        ).fetchall(),
        operations=OPERATIONS,
    )
