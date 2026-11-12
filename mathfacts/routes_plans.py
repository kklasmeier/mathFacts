"""Plan setup, a child's plans, and the account plan library (spec 5.6, 5.12.2)."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import children, plans
from .builder import SPACING_CHOICES
from .pools import OPERATIONS, SYMBOL
from .sessions import get_db

bp = Blueprint("plans", __name__)

OP_ORDER = ("add", "sub", "mul", "div")
BAR_LABEL = {
    4: "Excellent",
    3: "Good or better",
    2: "OK or better",
    1: "Needs improvement or better",
}
SPACING_LABEL = dict(SPACING_CHOICES)


def _child_or_404(db, child_id):
    child = children.get_child(db, g.account["id"], child_id)
    if child is None:
        abort(404)
    return child


def _plan_or_404(db, plan_id):
    plan = plans.get_plan(db, g.account["id"], plan_id)
    if plan is None:
        abort(404)
    return plan


def _advancement(source):
    def whole(name, low, high, default):
        raw = str(source.get(name, "")).strip()
        if raw.isdigit() and low <= int(raw) <= high:
            return int(raw)
        return default

    pace = str(source.get("pace", "")).strip()
    support = str(source.get("support_min", "")).strip()
    return {
        "x": whole("x", 1, 10, 2),
        "y": whole("y", 1, 10, 3),
        "performance": whole("performance", 2, 4, 3),
        "pace": int(pace) if pace in ("2", "3", "4") else None,
        "support": int(support) if support in ("2", "3") else None,
    }


def _selected_ops(source):
    if hasattr(source, "getlist"):
        raw = source.getlist("ops")
    else:
        raw = source.get("ops", [])
    if isinstance(raw, str):
        raw = [raw]
    return [op for op in OP_ORDER if op in raw]


@bp.get("/children/<int:child_id>/plans")
def child_plans(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    plans.refresh_child(db, child_id)
    rows = plans.child_plans(db, g.account["id"], child_id)
    if not rows:
        return render_template(
            "child_plans.html", child=child, cards=[], operations=OPERATIONS,
            symbols=SYMBOL, bars=BAR_LABEL,
        )
    cards = []
    for row in rows:
        tally = plans.stage_tally(
            db, child_id, row["current_stage_id"], row["stage_started_at"]
        )
        cards.append({
            "row": row,
            "ready": plans.show_ready(row),
            "done": tally["done"],
            "minimum": tally["minimum"],
            "last_ok": tally["last_ok"],
            "stages": plans.stages(db, row["plan_id"]),
        })
    return render_template(
        "child_plans.html",
        child=child,
        cards=cards,
        operations=OPERATIONS,
        symbols=SYMBOL,
        bars=BAR_LABEL,
    )


@bp.route("/children/<int:child_id>/plans/setup", methods=["GET", "POST"])
def setup(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    source = request.form if request.method == "POST" else request.args
    step = str(source.get("step", "1") or "1")
    existing = {row["operation"] for row in plans.child_plans(db, g.account["id"], child_id)}
    ops = _selected_ops(source)
    if request.method == "POST" and step == "5" and source.get("action") in ("generate", "done"):
        return _confirm(db, child, ops, existing, source)
    if request.method == "POST" and step in ("1", "2", "3", "4"):
        step = str(int(step) + 1)
    return render_template(
        "plan_setup.html",
        child=child,
        step=step,
        ops=ops,
        existing=existing,
        operations=OPERATIONS,
        sources=_sources(db, ops),
        stages=_stage_choices(db, ops, source),
        advancement=_advancement(source),
        bars=BAR_LABEL,
        error=_setup_error(step, ops, existing),
    )


def _setup_error(step, ops, existing):
    if step != "1" and not [op for op in ops if op not in existing]:
        return "Choose at least one operation."
    return ""


def _sources(db, ops):
    account = plans.account_plans(db, g.account["id"])
    out = {}
    for op in ops:
        out[op] = [row for row in account if row["operation"] == op]
    return out


def _stage_choices(db, ops, source):
    choices = {}
    for op in ops:
        kind = source.get(f"src_{op}", "system")
        if kind == "scratch":
            choices[op] = []
            continue
        if str(kind).startswith("plan-"):
            plan_id = kind.split("-", 1)[1]
            plan = plans.get_plan(db, g.account["id"], int(plan_id)) if plan_id.isdigit() else None
            choices[op] = plans.stages(db, plan["id"]) if plan else []
        else:
            system = plans.system_plan(db, op)
            choices[op] = plans.stages(db, system["id"]) if system else []
    return choices


def _confirm(db, child, ops, existing, source):
    fresh = [op for op in ops if op not in existing]
    if not fresh:
        flash("Choose at least one operation.")
        return redirect(url_for("plans.setup", child_id=child["id"]))
    advancement = _advancement(source)
    first_stage = None
    for op in fresh:
        kind = source.get(f"src_{op}", "system")
        position = source.get(f"stage_{op}", "1")
        position = int(position) if str(position).isdigit() else 1
        name = f"{OPERATIONS[op]} for {child['name']}"
        if kind == "scratch":
            _plan_id, stage_id = plans.create_scratch(
                db, g.account["id"], child["id"], op, name, advancement
            )
        else:
            if str(kind).startswith("plan-") and kind.split("-", 1)[1].isdigit():
                source_id = int(kind.split("-", 1)[1])
                if plans.get_plan(db, g.account["id"], source_id) is None:
                    abort(404)
            else:
                system = plans.system_plan(db, op)
                source_id = system["id"]
            result = plans.assign_copy(
                db, g.account["id"], child["id"], source_id, position, name, advancement
            )
            if result is None:
                abort(404)
            _plan_id, stage_id = result
        if first_stage is None:
            first_stage = stage_id
    flash(f"Plans are ready for {child['name']}.")
    if source.get("action") == "generate" and first_stage:
        stage = db_stage_specs(db, first_stage)
        if stage and stage["a_spec"].strip():
            return redirect(url_for(
                "sheets.new_sheet", child=child["id"], stage=first_stage
            ))
        flash("Add facts to the first stage before generating a sheet.")
    return redirect(url_for("plans.child_plans", child_id=child["id"]))


def db_stage_specs(db, stage_id):
    return db.execute("SELECT a_spec FROM plan_stages WHERE id = ?", (stage_id,)).fetchone()


@bp.post("/children/<int:child_id>/plans/<int:plan_id>/<action>")
def plan_action(child_id, plan_id, action):
    db = get_db()
    _child_or_404(db, child_id)
    account_id = g.account["id"]
    if action == "advance":
        result = plans.advance(db, account_id, child_id, plan_id)
        if result is None:
            abort(404)
        earned = badges_after(db, child_id, account_id)
        if result == "finished":
            flash("That was the last stage. The plan is complete.")
        else:
            flash(f"Advanced to {result}.")
        if earned:
            flash("New badge earned! " + ", ".join(earned) + ".")
    elif action == "repeat":
        if plans.repeat_stage(db, account_id, child_id, plan_id) is None:
            abort(404)
        flash("Staying on this stage. The count starts over.")
    elif action == "snooze":
        if plans.snooze(db, account_id, child_id, plan_id) is None:
            abort(404)
        flash("Hidden for 7 days. A new rating can bring it back.")
    elif action == "move":
        stage_id = request.form.get("stage_id", "")
        if not stage_id.isdigit():
            abort(400)
        name = plans.move_to(db, account_id, child_id, plan_id, int(stage_id))
        if name is None:
            abort(404)
        flash(f"Moved to {name}.")
    elif action == "remove":
        if request.form.get("confirm") != "yes":
            row = plans.child_plans(db, account_id, child_id)
            match = next((item for item in row if item["plan_id"] == plan_id), None)
            if match is None:
                abort(404)
            return render_template(
                "plan_confirm.html",
                child_id=child_id,
                title=f"Remove {match['plan_name']}?",
                body="The child leaves this plan. Sheets already made stay. The plan copy stays in the library.",
                action=url_for("plans.plan_action", child_id=child_id, plan_id=plan_id, action="remove"),
            )
        if not plans.unlink(db, account_id, child_id, plan_id):
            abort(404)
        flash("Removed the plan from this child.")
    else:
        abort(404)
    return redirect(url_for("plans.child_plans", child_id=child_id))


def badges_after(db, child_id, account_id):
    from . import badges
    return badges.evaluate(db, child_id, account_id)


@bp.get("/plans")
def library():
    db = get_db()
    account_id = g.account["id"]
    cards = []
    for plan in plans.account_plans(db, account_id):
        stage_rows = plans.stages(db, plan["id"])
        first = stage_rows[0] if stage_rows else None
        cards.append({
            "plan": plan,
            "count": len(stage_rows),
            "minimum": first["min_sheets"] if first else 3,
            "bar": first["adv_min_performance"] if first else 3,
            "kids": plans.assignees(db, account_id, plan["id"]),
        })
    return render_template(
        "plan_library.html",
        cards=cards,
        systems=plans.system_plans(db),
        operations=OPERATIONS,
        symbols=SYMBOL,
        bars=BAR_LABEL,
    )


@bp.route("/plans/<int:plan_id>/assign", methods=["GET", "POST"])
def assign(plan_id):
    db = get_db()
    plan = _plan_or_404(db, plan_id)
    kids = children.list_children(db, g.account["id"])
    linked = {row["id"] for row in plans.assignees(db, g.account["id"], plan_id)}
    if request.method == "POST":
        chosen = request.form.getlist("child")
        started = []
        for kid in kids:
            if str(kid["id"]) not in chosen or kid["id"] in linked:
                continue
            stage_id = plans.assign_plan(db, g.account["id"], kid["id"], plan_id)
            if stage_id is None:
                continue
            made = plans.issue_stage_sheet(db, g.account["id"], kid["id"], stage_id)
            started.append(kid["name"])
            if made is None:
                flash(f"{kid['name']} is assigned. Add numbers to the first stage, then the sheet can be prepared.")
        if started:
            flash("Assigned to " + ", ".join(started) + ".")
        return redirect(url_for("plans.library"))
    return render_template(
        "plan_assign.html", plan=plan, kids=kids, linked=linked,
    )


@bp.route("/plans/<int:plan_id>/delete", methods=["GET", "POST"])
def delete(plan_id):
    db = get_db()
    plan = _plan_or_404(db, plan_id)
    if request.method == "POST":
        if not plans.delete_plan(db, g.account["id"], plan_id):
            abort(404)
        flash(f"Deleted {plan['name']}.")
        return redirect(url_for("plans.library"))
    return render_template("plan_delete.html", plan=plan)


@bp.get("/plans/system/<operation>")
def system_view(operation):
    if operation not in OPERATIONS:
        abort(404)
    db = get_db()
    plan = plans.system_plan(db, operation)
    if plan is None:
        abort(404)
    return render_template(
        "plan_editor.html",
        plan=plan,
        stages=plans.stages(db, plan["id"]),
        operations=OPERATIONS,
        symbols=SYMBOL,
        bars=BAR_LABEL,
        spacings=SPACING_LABEL,
        readonly=True,
    )


@bp.post("/plans/system/<operation>/copy")
def copy_system(operation):
    if operation not in OPERATIONS:
        abort(404)
    db = get_db()
    plan = plans.system_plan(db, operation)
    if plan is None:
        abort(404)
    new_id = plans.copy_plan(db, g.account["id"], plan["id"], f"{plan['name']} copy")
    flash("Saved a copy for this account. The standard plan is unchanged.")
    return redirect(url_for("plans.editor", plan_id=new_id))


@bp.route("/plans/new", methods=["GET", "POST"])
def new_plan():
    if request.method == "GET":
        return render_template("plan_new.html", operations=OPERATIONS, errors={})
    name = request.form.get("name", "").strip()
    operation = request.form.get("operation", "")
    errors = {}
    if not name or len(name) > 80:
        errors["name"] = "Enter a name up to 80 characters."
    if operation not in OPERATIONS:
        errors["operation"] = "Choose an operation."
    if errors:
        return render_template("plan_new.html", operations=OPERATIONS, errors=errors), 400
    db = get_db()
    from . import clock
    cursor = db.execute(
        """
        INSERT INTO plans (account_id, operation, name, is_system, created_at)
        VALUES (?, ?, ?, 0, ?)
        """,
        (g.account["id"], operation, name, clock.now()),
    )
    plans.add_stage(db, g.account["id"], cursor.lastrowid, "Stage 1", "0-9", "0")
    flash("Add the facts for the first stage.")
    return redirect(url_for("plans.editor", plan_id=cursor.lastrowid))


@bp.route("/plans/<int:plan_id>", methods=["GET", "POST"])
def editor(plan_id):
    db = get_db()
    plan = _plan_or_404(db, plan_id)
    if request.method == "POST":
        target = _edit(db, plan) or {}
        params = {"plan_id": plan_id, "_anchor": target.get("anchor")}
        if target.get("open"):
            params["open"] = target["open"]
        return redirect(url_for("plans.editor", **params))
    return render_template(
        "plan_editor.html",
        plan=plan,
        stages=plans.stages(db, plan_id),
        operations=OPERATIONS,
        symbols=SYMBOL,
        bars=BAR_LABEL,
        spacings=SPACING_LABEL,
        readonly=False,
    )


def _edit(db, plan):
    action = request.form.get("action", "")
    if action == "rename":
        name = request.form.get("name", "").strip()
        if name and len(name) <= 80:
            db.execute(
                "UPDATE plans SET name = ? WHERE id = ? AND account_id = ?",
                (name, plan["id"], g.account["id"]),
            )
        return {"anchor": "plan-name"}
    if action == "options":
        _save_options(db, plan)
        return {"anchor": "plan-options"}
    if action == "add":
        stage_id = plans.add_stage(db, g.account["id"], plan["id"], "", "", "")
        return {"anchor": f"stage-{stage_id}", "open": stage_id}
    stage_id = request.form.get("stage_id", "")
    if not stage_id.isdigit():
        abort(400)
    stage = db.execute(
        "SELECT * FROM plan_stages WHERE id = ? AND plan_id = ?",
        (int(stage_id), plan["id"]),
    ).fetchone()
    if stage is None:
        abort(404)
    if action == "remove":
        count = db.execute(
            "SELECT COUNT(*) FROM plan_stages WHERE plan_id = ?", (plan["id"],)
        ).fetchone()[0]
        if count > 1:
            used = db.execute(
                "SELECT COUNT(*) FROM child_plan_progress WHERE current_stage_id = ?",
                (stage["id"],),
            ).fetchone()[0]
            if used:
                flash("Move the child to another stage before removing this one.")
            else:
                position = stage["position"]
                db.execute("DELETE FROM plan_stages WHERE id = ?", (stage["id"],))
                plans.renumber(db, plan["id"])
                neighbor = db.execute(
                    """
                    SELECT id FROM plan_stages
                    WHERE plan_id = ? AND position >= ?
                    ORDER BY position LIMIT 1
                    """,
                    (plan["id"], position),
                ).fetchone()
                if neighbor is None:
                    neighbor = db.execute(
                        """
                        SELECT id FROM plan_stages
                        WHERE plan_id = ? ORDER BY position DESC LIMIT 1
                        """,
                        (plan["id"],),
                    ).fetchone()
                if neighbor:
                    return {"anchor": f"stage-{neighbor['id']}"}
                return {"anchor": "add-stage"}
        return {"anchor": f"stage-{stage['id']}"}
    if action == "up":
        _swap(db, plan["id"], stage, -1)
        return {"anchor": f"stage-{stage['id']}"}
    if action == "down":
        _swap(db, plan["id"], stage, 1)
        return {"anchor": f"stage-{stage['id']}"}
    if action == "save":
        name = request.form.get("stage_name", "").strip() or stage["name"]
        a_spec = request.form.get("a_spec", "").strip()
        b_spec = request.form.get("b_spec", "").strip()
        rule = request.form.get("pair_rule", "any")
        if rule not in ("any", "sum_max", "operands_equal"):
            rule = "any"
        limit = request.form.get("pair_rule_limit", "").strip()
        pair_limit = int(limit) if limit.isdigit() else None
        review = request.form.get("review_mix_pct", "20").strip()
        review_pct = int(review) if review.isdigit() and 0 <= int(review) <= 50 else 20
        operation = request.form.get("operation", plan["operation"])
        if operation not in OPERATIONS:
            operation = plan["operation"]
        minimum = request.form.get("min_sheets", "3").strip()
        min_sheets = int(minimum) if minimum.isdigit() and 1 <= int(minimum) <= 20 else 3
        performance = request.form.get("performance", "3").strip()
        bar = int(performance) if performance in ("1", "2", "3", "4") else 3
        both = 1 if request.form.get("include_reverse") and operation in ("add", "mul") else 0
        db.execute(
            """
            UPDATE plan_stages
            SET name = ?, operation = ?, a_spec = ?, b_spec = ?, include_reverse = ?,
                pair_rule = ?, pair_rule_limit = ?, review_mix_pct = ?,
                min_sheets = ?, adv_min_performance = ?, mixed = ?
            WHERE id = ?
            """,
            (
                name[:80], operation, a_spec[:40], b_spec[:40], both, rule, pair_limit,
                review_pct, min_sheets, bar,
                1 if request.form.get("mixed") else 0,
                stage["id"],
            ),
        )
        if stage["stage_key"].startswith("custom-"):
            db.execute(
                """
                UPDATE badges SET name = ?, description = ?
                WHERE account_id = ? AND key = ?
                """,
                (f"{name[:80]} Complete", f"Move past {name[:80]}.",
                 g.account["id"], f"stage_complete:{stage['stage_key']}"),
            )
        return {"anchor": f"stage-{stage['id']}", "open": stage["id"]}


def _save_options(db, plan):
    def count(name, low, high, default):
        raw = request.form.get(name, "").strip()
        if raw.isdigit() and low <= int(raw) <= high:
            return int(raw)
        return default

    cols = count("cols", 1, 10, plan["default_cols"] or 5)
    rows = count("rows", 1, 20, plan["default_rows"] or 4)
    spacing = request.form.get("spacing", "normal")
    if spacing not in SPACING_LABEL:
        spacing = "normal"
    orientation = request.form.get("orientation") or plan["default_orientation"] or "horizontal"
    if orientation not in ("horizontal", "vertical"):
        orientation = "horizontal"
    db.execute(
        """
        UPDATE plans
        SET default_cols = ?, default_rows = ?, spacing = ?, default_orientation = ?
        WHERE id = ? AND account_id = ?
        """,
        (cols, rows, spacing, orientation, plan["id"], g.account["id"]),
    )
    db.execute(
        """
        UPDATE plan_stages
        SET default_cols = ?, default_rows = ?, default_orientation = ?
        WHERE plan_id = ?
        """,
        (cols, rows, orientation, plan["id"]),
    )
    if "min_sheets" in request.form:
        minimum = count("min_sheets", 1, 20, 3)
        performance = request.form.get("performance", "3").strip()
        bar = int(performance) if performance in ("1", "2", "3", "4") else 3
        db.execute(
            """
            UPDATE plan_stages
            SET min_sheets = ?, adv_min_performance = ?
            WHERE plan_id = ?
            """,
            (minimum, bar, plan["id"]),
        )


def _swap(db, plan_id, stage, direction):
    other = db.execute(
        """
        SELECT * FROM plan_stages
        WHERE plan_id = ? AND position = ?
        """,
        (plan_id, stage["position"] + direction),
    ).fetchone()
    if other is None:
        return
    db.execute("UPDATE plan_stages SET position = ? WHERE id = ?", (other["position"], stage["id"]))
    db.execute("UPDATE plan_stages SET position = ? WHERE id = ?", (stage["position"], other["id"]))
