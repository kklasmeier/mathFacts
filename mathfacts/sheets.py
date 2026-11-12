"""Saved sheets: numbering, saving, and loading (spec 5.3, 6).

Every query takes the account ID. A sheet from another account is simply not
found, so the route returns 404.
"""

import json

from . import clock
from .pools import Problem


LAYOUT_FIELDS = ("orientation", "page_direction", "cols", "rows", "order")


def remembered_layout(db, account_id):
    """Last problem layout, page, across, down, and order for this account."""
    row = db.execute(
        "SELECT builder_prefs FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None or not row["builder_prefs"]:
        return {}
    try:
        data = json.loads(row["builder_prefs"])
    except json.JSONDecodeError:
        return {}
    return {
        key: str(data[key])
        for key in LAYOUT_FIELDS
        if key in data and str(data[key]).strip()
    }


def remember_layout(db, account_id, cfg):
    """Keep the layout fields so the next new sheet starts from this setup."""
    prefs = {
        "orientation": cfg.orientation,
        "page_direction": cfg.page_direction,
        "cols": str(cfg.cols),
        "rows": str(cfg.rows),
        "order": cfg.order,
    }
    db.execute(
        "UPDATE accounts SET builder_prefs = ? WHERE id = ?",
        (json.dumps(prefs), account_id),
    )


def next_number(db, account_id):
    """Take the next sheet number for this account. Numbers are never reused."""
    db.execute(
        "UPDATE accounts SET next_sheet_number = next_sheet_number + 1 WHERE id = ?",
        (account_id,),
    )
    return db.execute(
        "SELECT next_sheet_number - 1 FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()[0]


def save_sheet(db, account_id, cfg, plan):
    """Store the config, the options that fix the layout, and every printed problem."""
    number = next_number(db, account_id)
    cursor = db.execute(
        """
        INSERT INTO worksheets (
            account_id, number, child_id, created_at, title, operation, a_spec, b_spec,
            include_reverse, orientation, cols, rows, order_mode, seed, options_json,
            plan_stage_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id, number, cfg.child_id, clock.now(), plan.title, cfg.operation,
            cfg.a_spec, cfg.b_spec, 1 if cfg.include_reverse else 0, cfg.orientation,
            cfg.cols, cfg.rows, cfg.order, cfg.seed, json.dumps(_options(cfg, plan)),
            cfg.plan_stage_id,
        ),
    )
    sheet_id = cursor.lastrowid
    _write_problems(db, sheet_id, plan.problems)
    return sheet_id, number


PAGE_SIZE = 50
UNFINISHED_DAYS = 14


def form_values(row, options):
    """Builder form values for a saved sheet, including the seed that printed it."""
    return {
        "child": str(row["child_id"]),
        "operation": row["operation"],
        "a_spec": row["a_spec"],
        "b_spec": row["b_spec"],
        "include_reverse": bool(row["include_reverse"]),
        "allow_negatives": bool(options.get("allow_negatives")),
        "orientation": row["orientation"],
        "page_direction": options.get("page_direction", "portrait"),
        "cols": str(row["cols"]),
        "rows": str(row["rows"]),
        "order": row["order_mode"],
        "title": row["title"],
        "spacing": options.get("spacing", "normal"),
        "seed": str(row["seed"]),
        "name_line": bool(options.get("name_line", True)),
        "date_line": bool(options.get("date_line", True)),
        "answer_key": bool(options.get("answer_key")),
        "badges_on": bool(options.get("banner") or options.get("banner_more")),
        "plan_stage_id": "" if row["plan_stage_id"] is None else str(row["plan_stage_id"]),
    }


def _options(cfg, plan):
    return {
        "name_line": cfg.name_line,
        "date_line": cfg.date_line,
        "answer_key": cfg.answer_key,
        "spacing": cfg.spacing,
        "page_direction": cfg.page_direction,
        "allow_negatives": cfg.allow_negatives,
        "font_pt": plan.fit.font_pt,
        "cell_w_in": plan.fit.cell_w_in,
        "cell_h_in": plan.fit.cell_h_in,
        "legible": plan.fit.legible,
        "tight": plan.fit.tight,
        "fits": plan.fit.fits,
        "notices": plan.notices,
        "banner": list(cfg.banner_items),
        "banner_more": cfg.banner_more,
        "stage_name": cfg.stage_name,
    }


def _write_problems(db, sheet_id, problems):
    db.execute("DELETE FROM worksheet_problems WHERE worksheet_id = ?", (sheet_id,))
    db.executemany(
        """
        INSERT INTO worksheet_problems (worksheet_id, position, op, a, b, answer, dividend)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (sheet_id, position, p.op, p.a, p.b, p.answer, p.dividend)
            for position, p in enumerate(problems)
        ],
    )


def replace_sheet(db, account_id, sheet_id, cfg, plan):
    """Replace an issued sheet's problems and settings. The number stays.

    Returns the sheet number, "completed" when the sheet is finished, or None
    when this account has no such sheet.
    """
    row = db.execute(
        "SELECT status, number FROM worksheets WHERE id = ? AND account_id = ?",
        (sheet_id, account_id),
    ).fetchone()
    if row is None:
        return None
    if row["status"] != "issued":
        return "completed"
    db.execute(
        """
        UPDATE worksheets SET
            child_id = ?, title = ?, operation = ?, a_spec = ?, b_spec = ?,
            include_reverse = ?, orientation = ?, cols = ?, rows = ?, order_mode = ?,
            seed = ?, revision = revision + 1, options_json = ?, plan_stage_id = ?
        WHERE id = ? AND account_id = ?
        """,
        (
            cfg.child_id, plan.title, cfg.operation, cfg.a_spec, cfg.b_spec,
            1 if cfg.include_reverse else 0, cfg.orientation, cfg.cols, cfg.rows,
            cfg.order, cfg.seed, json.dumps(_options(cfg, plan)), cfg.plan_stage_id,
            sheet_id, account_id,
        ),
    )
    _write_problems(db, sheet_id, plan.problems)
    return row["number"]


def owned_sheets(db, account_id, sheet_ids):
    """The given ids that belong to this account, newest number first."""
    ids = [int(i) for i in sheet_ids]
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    return db.execute(
        f"""
        SELECT id, number, title, status, child_id FROM worksheets
        WHERE account_id = ? AND id IN ({marks})
        ORDER BY number DESC
        """,
        (account_id, *ids),
    ).fetchall()


def delete_sheets(db, account_id, sheet_ids):
    """Permanently delete these sheets. Ratings and problems go with them.

    Sheet numbers are not returned to the account. Returns the rows deleted.
    """
    rows = owned_sheets(db, account_id, sheet_ids)
    if not rows:
        return []
    from . import badges, plans
    child_ids = set()
    for row in rows:
        badges.release_for_sheet(db, row["id"], completed=row["status"] == "completed")
        child_ids.add(row["child_id"])
    marks = ",".join("?" for _ in rows)
    db.execute(
        f"DELETE FROM worksheets WHERE account_id = ? AND id IN ({marks})",
        (account_id, *[row["id"] for row in rows]),
    )
    for child_id in child_ids:
        plans.refresh_child(db, child_id)
    return rows


def list_sheets(db, account_id, *, child_id=None, operation=None, status=None,
                support=None, search="", date_from=None, date_to=None,
                issued_before=None, page=1):
    """One page of this account's sheets, newest first, plus the total count."""
    where = ["w.account_id = ?"]
    args = [account_id]
    if child_id:
        where.append("w.child_id = ?")
        args.append(child_id)
    if operation:
        where.append("w.operation = ?")
        args.append(operation)
    if status:
        where.append("w.status = ?")
        args.append(status)
    if support:
        where.append("r.support = ?")
        args.append(support)
    if issued_before is not None:
        where.append("w.status = 'issued' AND w.created_at <= ?")
        args.append(issued_before)
    if date_from or date_to:
        # Issued sheets are filtered by the day they were made. Completed sheets
        # are filtered by the day they were finished. Placeholders follow that
        # same order: the issued bounds, then the completed bounds.
        start = clock.start_of_day(date_from) if date_from else None
        end = clock.start_of_day(date_to) + 86400 if date_to else None
        issued = ["w.status = 'issued'"]
        done = ["w.status = 'completed'"]
        issued_args = []
        done_args = []
        if start is not None:
            issued.append("w.created_at >= ?")
            issued_args.append(start)
            done.append("r.completed_at >= ?")
            done_args.append(date_from.isoformat())
        if end is not None:
            issued.append("w.created_at < ?")
            issued_args.append(end)
            done.append("r.completed_at <= ?")
            done_args.append(date_to.isoformat())
        where.append(f"(({' AND '.join(issued)}) OR ({' AND '.join(done)}))")
        args.extend(issued_args)
        args.extend(done_args)
    term = (search or "").strip().lstrip("#")
    if term:
        if term.isdigit():
            where.append("(w.number = ? OR w.title LIKE ?)")
            args.extend([int(term), f"%{term}%"])
        else:
            where.append("w.title LIKE ?")
            args.append(f"%{term}%")

    sql_where = " AND ".join(where)
    total = db.execute(
        f"""
        SELECT COUNT(*) FROM worksheets w
        LEFT JOIN ratings r ON r.worksheet_id = w.id
        WHERE {sql_where}
        """,
        args,
    ).fetchone()[0]
    offset = max(0, page - 1) * PAGE_SIZE
    rows = db.execute(
        f"""
        SELECT w.*, c.name AS child_name,
               r.performance, r.support, r.pace, r.completed_at, r.aid_type, r.notes
        FROM worksheets w
        JOIN children c ON c.id = w.child_id
        LEFT JOIN ratings r ON r.worksheet_id = w.id
        WHERE {sql_where}
        ORDER BY w.number DESC
        LIMIT ? OFFSET ?
        """,
        (*args, PAGE_SIZE, offset),
    ).fetchall()
    return rows, total


def unfinished_count(db, account_id, child_id):
    return db.execute(
        "SELECT COUNT(*) FROM worksheets WHERE account_id = ? AND child_id = ? AND status = 'issued'",
        (account_id, child_id),
    ).fetchone()[0]


def get_pref(db, account_id, key):
    row = db.execute(
        "SELECT value FROM account_settings WHERE account_id = ? AND key = ?",
        (account_id, key),
    ).fetchone()
    return row["value"] if row else None


def set_pref(db, account_id, key, value):
    db.execute(
        """
        INSERT INTO account_settings (account_id, key, value) VALUES (?, ?, ?)
        ON CONFLICT (account_id, key) DO UPDATE SET value = excluded.value
        """,
        (account_id, key, value),
    )


def load_sheet(db, account_id, sheet_id):
    """Return (row, options, problems) for this account's sheet, or None."""
    row = db.execute(
        "SELECT * FROM worksheets WHERE id = ? AND account_id = ?", (sheet_id, account_id)
    ).fetchone()
    if row is None:
        return None
    rows = db.execute(
        "SELECT op, a, b FROM worksheet_problems WHERE worksheet_id = ? ORDER BY position",
        (sheet_id,),
    ).fetchall()
    problems = [Problem(r["op"], r["a"], r["b"]) for r in rows]
    return row, json.loads(row["options_json"]), problems
