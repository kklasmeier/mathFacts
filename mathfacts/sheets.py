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
    options = {
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
    }
    cursor = db.execute(
        """
        INSERT INTO worksheets (
            account_id, number, child_id, created_at, title, operation, a_spec, b_spec,
            include_reverse, orientation, cols, rows, order_mode, seed, options_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id, number, cfg.child_id, clock.now(), plan.title, cfg.operation,
            cfg.a_spec, cfg.b_spec, 1 if cfg.include_reverse else 0, cfg.orientation,
            cfg.cols, cfg.rows, cfg.order, cfg.seed, json.dumps(options),
        ),
    )
    sheet_id = cursor.lastrowid
    db.executemany(
        """
        INSERT INTO worksheet_problems (worksheet_id, position, op, a, b, answer, dividend)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (sheet_id, position, p.op, p.a, p.b, p.answer, p.dividend)
            for position, p in enumerate(plan.problems)
        ],
    )
    return sheet_id, number


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
