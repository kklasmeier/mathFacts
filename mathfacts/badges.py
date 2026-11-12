"""Badge awarding and the print banner (spec 5.7).

Each badge is earned once per child. Awarding again does nothing. A badge
stays earned if a sheet is edited or deleted. Pending means earned and not
yet printed. Shown means it was attached to a sheet.
"""

import datetime

from . import clock
from .catalog import CHAMPION_KEYS, OWN_KEYS

BANNER_CAP = 5


def peek(db, child_id):
    """Badges the next sheet would show, without writing anything.

    Returns (items, more, ids). More than five pending shows the four oldest
    and a "+N more" count. The rest stay pending.
    """
    rows = db.execute(
        """
        SELECT cb.id, b.name, b.icon
        FROM child_badges cb
        JOIN badges b ON b.id = cb.badge_id
        WHERE cb.child_id = ? AND cb.shown_at IS NULL
        ORDER BY cb.earned_at, cb.id
        """,
        (child_id,),
    ).fetchall()
    if len(rows) > BANNER_CAP:
        shown = rows[: BANNER_CAP - 1]
        more = len(rows) - len(shown)
    else:
        shown = rows
        more = 0
    items = [{"name": row["name"], "icon": row["icon"]} for row in shown]
    return items, more, [row["id"] for row in shown]


def use_saved_banner(cfg, options):
    """Reprint and regenerate keep the badges already stored with the sheet."""
    cfg.banner_items = tuple(options.get("banner") or [])
    cfg.banner_more = int(options.get("banner_more") or 0)
    cfg.banner_ids = ()


def apply_pending(cfg, db):
    """Attach the preview of pending badges onto a config. Writes nothing."""
    if not cfg.badges_on:
        cfg.banner_items = ()
        cfg.banner_more = 0
        cfg.banner_ids = ()
        return
    items, more, ids = peek(db, cfg.child_id)
    cfg.banner_items = tuple(items)
    cfg.banner_more = more
    cfg.banner_ids = tuple(ids)


def mark_shown(db, cfg, worksheet_id):
    """Record that these pending badges printed on this sheet."""
    if not cfg.banner_ids:
        return
    now = clock.now()
    marks = ",".join("?" for _ in cfg.banner_ids)
    db.execute(
        f"""
        UPDATE child_badges
        SET shown_on_worksheet_id = ?, shown_at = ?
        WHERE id IN ({marks}) AND shown_at IS NULL
        """,
        (worksheet_id, now, *cfg.banner_ids),
    )


def release_for_sheet(db, worksheet_id, completed):
    """Issued sheets return their badges to pending. Finished sheets do not."""
    if completed:
        db.execute(
            "UPDATE child_badges SET shown_on_worksheet_id = NULL WHERE shown_on_worksheet_id = ?",
            (worksheet_id,),
        )
    else:
        db.execute(
            """
            UPDATE child_badges
            SET shown_on_worksheet_id = NULL, shown_at = NULL
            WHERE shown_on_worksheet_id = ?
            """,
            (worksheet_id,),
        )


def pending_count(db, child_id):
    return db.execute(
        "SELECT COUNT(*) FROM child_badges WHERE child_id = ? AND shown_at IS NULL",
        (child_id,),
    ).fetchone()[0]


def award(db, child_id, badge_id, source_worksheet_id=None):
    """Insert one earned badge. Returns True only the first time."""
    try:
        db.execute(
            """
            INSERT INTO child_badges (child_id, badge_id, earned_at, source_worksheet_id)
            VALUES (?, ?, ?, ?)
            """,
            (child_id, badge_id, clock.now(), source_worksheet_id),
        )
    except Exception as error:
        if "UNIQUE" in str(error).upper():
            return False
        raise
    return True


def award_key(db, child_id, key, account_id, source_worksheet_id=None):
    """Award the system badge, or this account's own badge with the same key."""
    row = db.execute(
        """
        SELECT id FROM badges
        WHERE key = ? AND (account_id IS NULL OR account_id = ?)
        ORDER BY account_id IS NULL DESC
        LIMIT 1
        """,
        (key, account_id),
    ).fetchone()
    if row is None:
        return None
    if award(db, child_id, row["id"], source_worksheet_id):
        name = db.execute("SELECT name FROM badges WHERE id = ?", (row["id"],)).fetchone()
        return name["name"]
    return None


def evaluate(db, child_id, account_id):
    """Award any newly earned catalog badges. Returns the new names."""
    rows = _completed(db, child_id)
    earned = []

    def give(key, source=None):
        name = award_key(db, child_id, key, account_id, source)
        if name:
            earned.append(name)

    count = len(rows)
    excellent = sum(1 for row in rows if row["performance"] == 4)
    for key, _name, _desc, _icon, _cat, rule, tier in _catalog(db):
        if rule == "count" and count >= tier:
            give(key, rows[-1]["id"] if rows else None)
        elif rule == "excellent" and excellent >= tier:
            give(key, rows[-1]["id"] if rows else None)
        elif rule == "busy_week" and _busy(rows, tier):
            give(key)
        elif rule == "streak" and _longest_streak(rows) >= tier:
            give(key)
        elif rule == "solid" and _solid_run(rows, tier):
            give(key)
        elif rule == "mix" and _mix(rows, tier):
            give(key)
        elif rule == "comeback" and _comeback(rows):
            give(key, rows[-1]["id"])
        elif rule == "best" and _personal_best(rows):
            give(key, rows[-1]["id"])
        elif rule == "less_help" and _less_help(rows):
            give(key)
        elif rule == "pace" and _quicker(rows):
            give(key)

    for operation, key in OWN_KEYS.items():
        if any(row["operation"] == operation and row["support"] == 3 for row in rows):
            give(key)

    return earned


def _catalog(db):
    from .catalog import BADGES
    return BADGES


def _completed(db, child_id):
    return db.execute(
        """
        SELECT w.id, w.operation, w.plan_stage_id, w.created_at,
               r.performance, r.support, r.pace, r.completed_at,
               s.mixed
        FROM worksheets w
        JOIN ratings r ON r.worksheet_id = w.id
        LEFT JOIN plan_stages s ON s.id = w.plan_stage_id
        WHERE w.child_id = ? AND w.status = 'completed'
        ORDER BY r.completed_at, w.created_at, w.id
        """,
        (child_id,),
    ).fetchall()


def _week(iso):
    day = datetime.date.fromisoformat(iso)
    return day - datetime.timedelta(days=(day.weekday() + 1) % 7)


def _busy(rows, need):
    counts = {}
    for row in rows:
        counts[_week(row["completed_at"])] = counts.get(_week(row["completed_at"]), 0) + 1
    return any(count >= need for count in counts.values())


def _longest_streak(rows):
    weeks = sorted({_week(row["completed_at"]) for row in rows})
    if not weeks:
        return 0
    best = run = 1
    for prev, cur in zip(weeks, weeks[1:]):
        if (cur - prev).days == 7:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def _solid_run(rows, need):
    run = 0
    for row in rows:
        if row["performance"] >= 3:
            run += 1
            if run >= need:
                return True
        else:
            run = 0
    return False


def _mix(rows, minimum):
    return any(row["mixed"] and row["performance"] >= minimum for row in rows)


def _comeback(rows):
    previous = None
    for row in rows:
        if previous is not None and row["performance"] >= previous + 1:
            return True
        previous = row["performance"]
    return False


def _personal_best(rows):
    scores = [row["performance"] for row in rows]
    best = None
    improved = False
    for index in range(4, len(scores)):
        average = sum(scores[index - 4:index + 1]) / 5
        if best is None or average > best + 1e-9:
            if best is not None:
                improved = True
            best = max(average, best or average)
    return improved


def _less_help(rows):
    previous = {}
    for row in rows:
        stage = row["plan_stage_id"]
        if stage is None:
            continue
        if stage in previous and row["support"] > previous[stage]:
            return True
        previous[stage] = row["support"]
    return False


def _quicker(rows):
    previous = {}
    for row in rows:
        if row["pace"] is None:
            continue
        operation = row["operation"]
        if operation in previous and row["pace"] >= previous[operation] + 1:
            return True
        previous[operation] = row["pace"]
    return False


def collection(db, child_id, account_id):
    """Every badge this child can see: earned first, then the ones still ahead."""
    return db.execute(
        """
        SELECT b.id, b.name, b.description, b.icon, b.category, b.key,
               cb.earned_at, cb.shown_at
        FROM badges b
        LEFT JOIN child_badges cb ON cb.badge_id = b.id AND cb.child_id = ?
        WHERE b.account_id IS NULL OR b.account_id = ?
        ORDER BY cb.earned_at IS NULL, cb.earned_at DESC, b.category, b.name
        """,
        (child_id, account_id),
    ).fetchall()
