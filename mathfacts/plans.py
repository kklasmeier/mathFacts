"""Account plan copies, the child's current stage, and advancement.

A child never shares a plan row. Choosing a system plan or another plan copies
it first. Next sheet opens the builder and does not save a sheet. A stage keeps
the student until they have finished its minimum number of sheets. The last
finished sheet then decides whether they move on.
"""

import uuid

from . import badges, clock
from .catalog import CHAMPION_KEYS
from .pools import constrained_pool
from .specs import OPERAND_LIMIT, parse_spec

OPERATIONS = ("add", "sub", "mul", "div")
SNOOZE_SECONDS = 7 * 24 * 60 * 60


def system_plans(db):
    return db.execute(
        "SELECT * FROM plans WHERE is_system = 1 ORDER BY id"
    ).fetchall()


def system_plan(db, operation):
    return db.execute(
        "SELECT * FROM plans WHERE is_system = 1 AND operation = ?", (operation,)
    ).fetchone()


def account_plans(db, account_id):
    return db.execute(
        "SELECT * FROM plans WHERE account_id = ? ORDER BY created_at, id",
        (account_id,),
    ).fetchall()


def get_plan(db, account_id, plan_id):
    """An account's own plan. System plans are not returned here."""
    return db.execute(
        "SELECT * FROM plans WHERE id = ? AND account_id = ?",
        (plan_id, account_id),
    ).fetchone()


def stages(db, plan_id):
    return db.execute(
        "SELECT * FROM plan_stages WHERE plan_id = ? ORDER BY position, id",
        (plan_id,),
    ).fetchall()


def child_plans(db, account_id, child_id):
    return db.execute(
        """
        SELECT g.*, p.name AS plan_name, p.operation, p.source_template_id,
               s.name AS stage_name, s.position, s.a_spec, s.b_spec,
               s.adv_x, s.adv_y, s.adv_min_performance
        FROM child_plan_progress g
        JOIN plans p ON p.id = g.plan_id
        JOIN plan_stages s ON s.id = g.current_stage_id
        WHERE g.child_id = ? AND p.account_id = ?
        ORDER BY p.operation
        """,
        (child_id, account_id),
    ).fetchall()


def copy_plan(db, account_id, source_id, name):
    """Deep-copy a plan and its stages. The source can be a system plan."""
    source = db.execute("SELECT * FROM plans WHERE id = ?", (source_id,)).fetchone()
    if source is None:
        return None
    if source["account_id"] not in (None, account_id):
        return None
    now = clock.now()
    cursor = db.execute(
        """
        INSERT INTO plans (
            account_id, source_template_id, operation, name, is_system, created_at,
            default_cols, default_rows, spacing, default_orientation
        ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
        """,
        (
            account_id, source["id"], source["operation"], name, now,
            source["default_cols"], source["default_rows"], source["spacing"],
            source["default_orientation"],
        ),
    )
    plan_id = cursor.lastrowid
    for stage in stages(db, source["id"]):
        db.execute(
            """
            INSERT INTO plan_stages (
                plan_id, position, stage_key, name, operation, a_spec, b_spec, include_reverse,
                pair_rule, pair_rule_limit, default_orientation, default_page_direction,
                default_cols, default_rows, review_mix_pct, mixed,
                adv_x, adv_y, adv_min_performance, adv_min_pace, adv_min_support, min_sheets
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id, stage["position"], stage["stage_key"], stage["name"],
                _operation(stage, source["operation"]),
                stage["a_spec"], stage["b_spec"], stage["include_reverse"],
                stage["pair_rule"], stage["pair_rule_limit"], stage["default_orientation"],
                stage["default_page_direction"], stage["default_cols"], stage["default_rows"],
                stage["review_mix_pct"], stage["mixed"], stage["adv_x"], stage["adv_y"],
                stage["adv_min_performance"], stage["adv_min_pace"], stage["adv_min_support"],
                stage["min_sheets"],
            ),
        )
    return plan_id


def _link(db, child_id, plan_id, stage_id):
    now = clock.now()
    db.execute(
        """
        INSERT INTO child_plan_progress (
            child_id, plan_id, current_stage_id, stage_started_at, ready_to_advance, finished
        ) VALUES (?, ?, ?, ?, 0, 0)
        """,
        (child_id, plan_id, stage_id, now),
    )
    db.execute(
        """
        INSERT INTO stage_history (child_id, plan_id, stage_id, entered_at)
        VALUES (?, ?, ?, ?)
        """,
        (child_id, plan_id, stage_id, now),
    )


def assign_copy(db, account_id, child_id, source_id, position, name, advancement):
    """Copy a plan, apply advancement to every stage, and start the child on one stage."""
    plan_id = copy_plan(db, account_id, source_id, name)
    if plan_id is None:
        return None
    _apply_advancement(db, plan_id, advancement)
    stage = _stage_at(db, plan_id, position)
    _link(db, child_id, plan_id, stage["id"])
    return plan_id, stage["id"]


def create_scratch(db, account_id, child_id, operation, name, advancement):
    now = clock.now()
    cursor = db.execute(
        """
        INSERT INTO plans (account_id, operation, name, is_system, created_at)
        VALUES (?, ?, ?, 0, ?)
        """,
        (account_id, operation, name, now),
    )
    plan_id = cursor.lastrowid
    stage_id = add_stage(db, account_id, plan_id, "Stage 1", "", "")
    _apply_advancement(db, plan_id, advancement)
    _link(db, child_id, plan_id, stage_id)
    return plan_id, stage_id


def add_stage(db, account_id, plan_id, name, a_spec, b_spec, operation=None):
    """Append a stage and give it an account-owned completion badge."""
    plan = db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    previous = db.execute(
        "SELECT * FROM plan_stages WHERE plan_id = ? ORDER BY position DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    position = (previous["position"] + 1) if previous else 1
    operation = operation or (_operation(previous, plan["operation"]) if previous else plan["operation"])
    min_sheets = previous["min_sheets"] if previous else 3
    performance = previous["adv_min_performance"] if previous else 3
    label = name.strip() or f"Stage {position}"
    key = f"custom-{uuid.uuid4().hex[:8]}"
    cursor = db.execute(
        """
        INSERT INTO plan_stages (
            plan_id, position, stage_key, name, operation, a_spec, b_spec, include_reverse,
            pair_rule, default_orientation, default_page_direction,
            default_cols, default_rows, review_mix_pct, mixed,
            adv_x, adv_y, adv_min_performance, min_sheets
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'any', ?, 'portrait', ?, ?, 20, 0, 2, ?, ?, ?)
        """,
        (
            plan_id, position, key, label, operation, a_spec, b_spec,
            plan["default_orientation"] or "horizontal",
            plan["default_cols"], plan["default_rows"], min_sheets, performance, min_sheets,
        ),
    )
    from .catalog import _stage_badge
    _stage_badge(db, account_id, key, label, clock.now())
    return cursor.lastrowid


def _apply_advancement(db, plan_id, advancement):
    db.execute(
        """
        UPDATE plan_stages
        SET adv_x = ?, adv_y = ?, adv_min_performance = ?, adv_min_pace = ?,
            adv_min_support = ?, min_sheets = ?
        WHERE plan_id = ?
        """,
        (
            advancement["x"], advancement["y"], advancement["performance"],
            advancement["pace"], advancement["support"], advancement["y"], plan_id,
        ),
    )


def _stage_at(db, plan_id, position):
    row = db.execute(
        "SELECT * FROM plan_stages WHERE plan_id = ? AND position = ?",
        (plan_id, position),
    ).fetchone()
    if row is None:
        row = db.execute(
            "SELECT * FROM plan_stages WHERE plan_id = ? ORDER BY position LIMIT 1",
            (plan_id,),
        ).fetchone()
    return row


def builder_values(db, account_id, child_id, stage_id):
    """Form defaults for Next sheet. None when this account does not have that stage."""
    stage = _owned_stage(db, account_id, child_id, stage_id)
    if stage is None or not stage["a_spec"].strip() or not stage["b_spec"].strip():
        return None
    return {
        "child": str(child_id),
        "operation": stage["operation"],
        "a_spec": stage["a_spec"],
        "b_spec": stage["b_spec"],
        "include_reverse": bool(stage["include_reverse"]),
        "allow_negatives": False,
        "orientation": stage["default_orientation"],
        "page_direction": stage["default_page_direction"],
        "cols": str(stage["default_cols"]),
        "rows": str(stage["default_rows"]),
        "order": "shuffled",
        "title": "",
        "spacing": stage["spacing"] or "normal",
        "name_line": True,
        "date_line": True,
        "answer_key": False,
        "badges_on": True,
        "plan_stage_id": str(stage["id"]),
    }


def lock_stage(db, account_id, cfg):
    """Keep the fact set on the stage. Layout fields stay as the parent set them.

    Returns the stage row, or None when this is a free sheet.
    """
    if not cfg.plan_stage_id:
        return None
    stage = _owned_stage(db, account_id, cfg.child_id, cfg.plan_stage_id)
    if stage is None:
        cfg.plan_stage_id = None
        cfg.review_facts = ()
        cfg.review_pct = 0
        return None
    cfg.operation = stage["operation"]
    cfg.a_spec = stage["a_spec"]
    cfg.b_spec = stage["b_spec"]
    cfg.include_reverse = bool(stage["include_reverse"])
    cfg.pair_rule = stage["pair_rule"]
    cfg.pair_rule_limit = stage["pair_rule_limit"]
    cfg.review_pct = stage["review_mix_pct"] or 0
    cfg.review_facts = tuple(_review_facts(db, stage))
    cfg.stage_name = stage["name"]
    return stage


def _owned_stage(db, account_id, child_id, stage_id):
    return db.execute(
        """
        SELECT s.*, p.account_id, p.spacing,
               COALESCE(s.operation, p.operation) AS operation
        FROM plan_stages s
        JOIN plans p ON p.id = s.plan_id
        JOIN child_plan_progress g ON g.plan_id = p.id AND g.child_id = ?
        WHERE s.id = ? AND p.account_id = ?
        """,
        (child_id, stage_id, account_id),
    ).fetchone()


def _review_facts(db, stage):
    earlier = db.execute(
        """
        SELECT * FROM plan_stages
        WHERE plan_id = ? AND position < ?
        ORDER BY position
        """,
        (stage["plan_id"], stage["position"]),
    ).fetchall()
    facts = []
    seen = set()
    operation = _operation(stage, stage["operation"])
    for row in earlier:
        for fact in _stage_facts(row, _operation(row, operation)):
            if fact not in seen:
                seen.add(fact)
                facts.append(fact)
    return facts


def _stage_facts(stage, operation):
    if not str(stage["a_spec"]).strip() or not str(stage["b_spec"]).strip():
        return []
    limit = OPERAND_LIMIT[operation]
    try:
        a_values = parse_spec(stage["a_spec"], limit)
        b_values = parse_spec(stage["b_spec"], limit)
    except Exception:
        return []
    pool = constrained_pool(
        operation, a_values, b_values,
        bool(stage["include_reverse"]), False,
        stage["pair_rule"], stage["pair_rule_limit"],
    )
    return pool.facts


def assignees(db, account_id, plan_id):
    return db.execute(
        """
        SELECT c.id, c.name, g.finished
        FROM child_plan_progress g
        JOIN children c ON c.id = g.child_id
        WHERE g.plan_id = ? AND c.account_id = ? AND c.archived = 0
        ORDER BY c.name
        """,
        (plan_id, account_id),
    ).fetchall()


def assign_plan(db, account_id, child_id, plan_id):
    """Link a child to this account's plan and start them on stage 1.

    Returns the first stage id, or None when the plan is missing or already assigned.
    """
    plan = get_plan(db, account_id, plan_id)
    if plan is None:
        return None
    already = db.execute(
        "SELECT 1 FROM child_plan_progress WHERE child_id = ? AND plan_id = ?",
        (child_id, plan_id),
    ).fetchone()
    if already:
        return None
    stage = _stage_at(db, plan_id, 1)
    if stage is None:
        return None
    _link(db, child_id, plan_id, stage["id"])
    return stage["id"]


def delete_plan(db, account_id, plan_id):
    plan = get_plan(db, account_id, plan_id)
    if plan is None:
        return False
    db.execute(
        "DELETE FROM plans WHERE id = ? AND account_id = ?",
        (plan_id, account_id),
    )
    return True


def open_sheet(db, child_id, stage_id, started_at):
    """The issued sheet waiting on this stage, if one is already prepared."""
    return db.execute(
        """
        SELECT * FROM worksheets
        WHERE child_id = ? AND plan_stage_id = ? AND status = 'issued'
          AND created_at >= ?
        ORDER BY number DESC LIMIT 1
        """,
        (child_id, stage_id, started_at),
    ).fetchone()


def issue_stage_sheet(db, account_id, child_id, stage_id):
    """Save the next sheet for this stage. Facts and layout come from the plan."""
    values = builder_values(db, account_id, child_id, stage_id)
    if values is None:
        return None
    from . import badges, builder, sheets
    values["seed"] = str(builder.new_seed())
    cfg, errors = builder.parse(values, {child_id})
    if errors:
        return None
    lock_stage(db, account_id, cfg)
    badges.apply_pending(cfg, db)
    built = builder.build_sheet(cfg)
    return sheets.save_sheet(db, account_id, cfg, built)


def ensure_open_sheet(db, account_id, child_id, plan_id):
    """Prepare a sheet for the current stage when one is not already waiting."""
    progress = _progress(db, account_id, child_id, plan_id)
    if progress is None or progress["finished"] or progress["current_stage_id"] is None:
        return None
    waiting = open_sheet(
        db, child_id, progress["current_stage_id"], progress["stage_started_at"]
    )
    if waiting:
        return waiting["id"], waiting["number"]
    return issue_stage_sheet(db, account_id, child_id, progress["current_stage_id"])


def show_ready(progress, now=None):
    if not progress or progress["finished"] or not progress["ready_to_advance"]:
        return False
    snoozed = progress["snoozed_until"]
    if snoozed and snoozed > (now if now is not None else clock.now()):
        return False
    return True


def refresh_child(db, child_id, clear_snooze=False):
    """Recompute ready-to-advance from the sheets made on the current stage."""
    rows = db.execute(
        "SELECT * FROM child_plan_progress WHERE child_id = ?", (child_id,)
    ).fetchall()
    for progress in rows:
        if progress["finished"] or progress["current_stage_id"] is None:
            continue
        stage = db.execute(
            "SELECT * FROM plan_stages WHERE id = ?", (progress["current_stage_id"],)
        ).fetchone()
        ready = _stage_ready(db, child_id, stage, progress["stage_started_at"])
        snoozed = None if clear_snooze else progress["snoozed_until"]
        db.execute(
            """
            UPDATE child_plan_progress
            SET ready_to_advance = ?, snoozed_until = ?
            WHERE child_id = ? AND plan_id = ?
            """,
            (1 if ready else 0, snoozed, child_id, progress["plan_id"]),
        )


def _operation(stage, fallback):
    """The stage's operation, or the plan's when the stage has none yet."""
    if stage is not None and stage["operation"] in OPERATIONS:
        return stage["operation"]
    return fallback


def _stage_sheets(db, child_id, stage_id, started_at):
    return db.execute(
        """
        SELECT r.performance, r.support, r.pace
        FROM worksheets w
        JOIN ratings r ON r.worksheet_id = w.id
        WHERE w.child_id = ? AND w.plan_stage_id = ? AND w.status = 'completed'
          AND w.created_at >= ?
        ORDER BY r.completed_at, w.id
        """,
        (child_id, stage_id, started_at),
    ).fetchall()


def _meets(row, stage):
    if row["performance"] < stage["adv_min_performance"]:
        return False
    if stage["adv_min_pace"] is not None and (
        row["pace"] is None or row["pace"] < stage["adv_min_pace"]
    ):
        return False
    if stage["adv_min_support"] is not None and row["support"] < stage["adv_min_support"]:
        return False
    return True


def _stage_ready(db, child_id, stage, started_at):
    """True once the minimum is met and the last finished sheet clears the bar."""
    rows = _stage_sheets(db, child_id, stage["id"], started_at)
    if len(rows) < stage["min_sheets"]:
        return False
    return _meets(rows[-1], stage)


def graduate_ready(db, account_id, child_id):
    """Move each plan whose current stage has just cleared its bar."""
    moved = []
    for row in child_plans(db, account_id, child_id):
        if not show_ready(row):
            continue
        result = advance(db, account_id, child_id, row["plan_id"])
        if result:
            moved.append(result)
    return moved


def renumber(db, plan_id):
    """Keep stage positions as 1, 2, 3 after a stage is removed."""
    rows = db.execute(
        "SELECT id FROM plan_stages WHERE plan_id = ? ORDER BY position, id",
        (plan_id,),
    ).fetchall()
    for index, row in enumerate(rows, start=1):
        db.execute(
            "UPDATE plan_stages SET position = ? WHERE id = ?", (index, row["id"])
        )


def _progress(db, account_id, child_id, plan_id):
    return db.execute(
        """
        SELECT g.*, p.account_id, p.operation, p.name AS plan_name
        FROM child_plan_progress g
        JOIN plans p ON p.id = g.plan_id
        WHERE g.child_id = ? AND g.plan_id = ? AND p.account_id = ?
        """,
        (child_id, plan_id, account_id),
    ).fetchone()


def _close(db, child_id, plan_id, reason):
    db.execute(
        """
        UPDATE stage_history SET exited_at = ?, exit_reason = ?
        WHERE child_id = ? AND plan_id = ? AND exited_at IS NULL
        """,
        (clock.now(), reason, child_id, plan_id),
    )


def _open(db, child_id, plan_id, stage_id):
    db.execute(
        """
        INSERT INTO stage_history (child_id, plan_id, stage_id, entered_at)
        VALUES (?, ?, ?, ?)
        """,
        (child_id, plan_id, stage_id, clock.now()),
    )


def advance(db, account_id, child_id, plan_id):
    """Move to the next stage, or finish the plan on the last stage."""
    progress = _progress(db, account_id, child_id, plan_id)
    if progress is None or progress["finished"]:
        return None
    current = db.execute(
        "SELECT * FROM plan_stages WHERE id = ?", (progress["current_stage_id"],)
    ).fetchone()
    badges.award_key(
        db, child_id, f"stage_complete:{current['stage_key']}", account_id
    )
    nxt = db.execute(
        """
        SELECT * FROM plan_stages
        WHERE plan_id = ? AND position > ?
        ORDER BY position LIMIT 1
        """,
        (current["plan_id"], current["position"]),
    ).fetchone()
    _close(db, child_id, plan_id, "advanced")
    now = clock.now()
    if nxt is None:
        db.execute(
            """
            UPDATE child_plan_progress
            SET ready_to_advance = 0, snoozed_until = NULL, finished = 1, stage_started_at = ?
            WHERE child_id = ? AND plan_id = ?
            """,
            (now, child_id, plan_id),
        )
        badges.award_key(db, child_id, CHAMPION_KEYS[progress["operation"]], account_id)
        return "finished"
    db.execute(
        """
        UPDATE child_plan_progress
        SET current_stage_id = ?, stage_started_at = ?, ready_to_advance = 0,
            snoozed_until = NULL, finished = 0
        WHERE child_id = ? AND plan_id = ?
        """,
        (nxt["id"], now, child_id, plan_id),
    )
    _open(db, child_id, plan_id, nxt["id"])
    return nxt["name"]


def repeat_stage(db, account_id, child_id, plan_id):
    """Stay on this stage and start the count over."""
    progress = _progress(db, account_id, child_id, plan_id)
    if progress is None:
        return None
    now = clock.now()
    _close(db, child_id, plan_id, "repeat")
    _open(db, child_id, plan_id, progress["current_stage_id"])
    db.execute(
        """
        UPDATE child_plan_progress
        SET stage_started_at = ?, ready_to_advance = 0, snoozed_until = NULL
        WHERE child_id = ? AND plan_id = ?
        """,
        (now, child_id, plan_id),
    )
    return progress["current_stage_id"]


def snooze(db, account_id, child_id, plan_id):
    progress = _progress(db, account_id, child_id, plan_id)
    if progress is None:
        return None
    until = clock.now() + SNOOZE_SECONDS
    db.execute(
        """
        UPDATE child_plan_progress SET snoozed_until = ?
        WHERE child_id = ? AND plan_id = ?
        """,
        (until, child_id, plan_id),
    )
    return until


def move_to(db, account_id, child_id, plan_id, stage_id):
    progress = _progress(db, account_id, child_id, plan_id)
    if progress is None:
        return None
    stage = db.execute(
        "SELECT * FROM plan_stages WHERE id = ? AND plan_id = ?",
        (stage_id, plan_id),
    ).fetchone()
    if stage is None:
        return None
    now = clock.now()
    _close(db, child_id, plan_id, "manual")
    _open(db, child_id, plan_id, stage["id"])
    db.execute(
        """
        UPDATE child_plan_progress
        SET current_stage_id = ?, stage_started_at = ?, ready_to_advance = 0,
            snoozed_until = NULL, finished = 0
        WHERE child_id = ? AND plan_id = ?
        """,
        (stage["id"], now, child_id, plan_id),
    )
    return stage["name"]


def unlink(db, account_id, child_id, plan_id):
    progress = _progress(db, account_id, child_id, plan_id)
    if progress is None:
        return False
    db.execute(
        "DELETE FROM child_plan_progress WHERE child_id = ? AND plan_id = ?",
        (child_id, plan_id),
    )
    db.execute(
        "DELETE FROM stage_history WHERE child_id = ? AND plan_id = ?",
        (child_id, plan_id),
    )
    return True


def stage_tally(db, child_id, stage_id, started_at):
    """Finished sheets on this stage, and whether the last one clears the bar."""
    stage = db.execute("SELECT * FROM plan_stages WHERE id = ?", (stage_id,)).fetchone()
    rows = _stage_sheets(db, child_id, stage_id, started_at)
    return {
        "done": len(rows),
        "minimum": stage["min_sheets"],
        "last_ok": bool(rows) and _meets(rows[-1], stage),
    }
