"""Rating a finished sheet (spec 5.4).

Performance and support are required. Pace and the aid are optional. Every
completed sheet counts toward advancement, including ones done with an aid.
The progress pages that show this are a later slice. The rule itself is here
so a rating is scored the same way when those pages arrive.
"""

from . import clock

PERFORMANCE = (
    (4, "Excellent"),
    (3, "Good"),
    (2, "OK"),
    (1, "Needs improvement"),
)
SUPPORT = (
    (3, "On their own"),
    (2, "Some help"),
    (1, "Aid throughout"),
)
PACE = (
    (4, "Fast"),
    (3, "Steady"),
    (2, "Slow"),
    (1, "Very slow"),
)
AIDS = (
    ("times_table", "Times table"),
    ("addition_chart", "Addition chart"),
    ("number_line", "Number line or counting"),
    ("fingers", "Fingers or objects"),
    ("other", "Other"),
)

NOTES_MAX = 500
_PERF = dict(PERFORMANCE)
_SUPPORT = dict(SUPPORT)
_PACE = dict(PACE)
_AIDS = dict(AIDS)


def performance_label(value):
    return _PERF.get(value, "")


def support_label(value):
    return _SUPPORT.get(value, "")


def pace_label(value):
    return _PACE.get(value, "")


def aid_label(value):
    return _AIDS.get(value, "")


def summary(performance, support):
    """The short line a completed sheet shows in the list."""
    return f"{performance_label(performance)} · {support_label(support)}"


def ready_to_advance(performances, x=2, y=3, minimum=3):
    """True when at least x of the last y scores meet the minimum.

    `performances` is oldest first. Fewer than y scores uses all of them.
    Support is not an argument: a sheet done with an aid counts the same.
    """
    window = list(performances)[-y:]
    return sum(1 for score in window if score >= minimum) >= x


def _choice(raw, allowed):
    text = str(raw or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value in allowed else None


def validate(form, today=None):
    """Return (clean values, errors). `today` is the default finished date."""
    errors = {}
    today = today or clock.iso_date()

    performance = _choice(form.get("performance"), _PERF)
    if performance is None:
        errors["performance"] = "Choose how it went."
    support = _choice(form.get("support"), _SUPPORT)
    if support is None:
        errors["support"] = "Choose how much support was used."

    pace_raw = str(form.get("pace") or "").strip()
    pace = None
    if pace_raw:
        pace = _choice(pace_raw, _PACE)
        if pace is None:
            errors["pace"] = "Choose a pace, or leave it blank."

    aid = str(form.get("aid_type") or "").strip()
    if support == 3 or not aid:
        aid = None
    elif aid not in _AIDS:
        errors["aid_type"] = "Choose an aid from the list, or leave it blank."

    finished = str(form.get("completed_on") or "").strip() or today
    if clock.parse_date(finished) is None:
        errors["completed_on"] = "Enter a real date."

    notes = str(form.get("notes") or "").strip()
    if len(notes) > NOTES_MAX:
        errors["notes"] = f"Use {NOTES_MAX} characters or fewer."

    clean = {
        "performance": performance,
        "support": support,
        "pace": pace,
        "aid_type": aid,
        "completed_at": finished,
        "notes": notes,
    }
    return clean, errors


def get_rating(db, worksheet_id):
    return db.execute(
        "SELECT * FROM ratings WHERE worksheet_id = ?", (worksheet_id,)
    ).fetchone()


def save_rating(db, worksheet_id, clean):
    """Store the rating and mark the sheet completed. Editing does not add a second row."""
    db.execute(
        "UPDATE worksheets SET status = 'completed' WHERE id = ?", (worksheet_id,)
    )
    existing = get_rating(db, worksheet_id)
    fields = (
        clean["completed_at"], clean["performance"], clean["support"],
        clean["aid_type"], clean["pace"], clean["notes"],
    )
    if existing is None:
        db.execute(
            """
            INSERT INTO ratings (
                worksheet_id, completed_at, performance, support, aid_type, pace, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (worksheet_id, *fields),
        )
    else:
        db.execute(
            """
            UPDATE ratings
            SET completed_at = ?, performance = ?, support = ?, aid_type = ?, pace = ?, notes = ?
            WHERE worksheet_id = ?
            """,
            (*fields, worksheet_id),
        )
