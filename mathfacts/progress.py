"""Progress figures for one child (spec 5.5).

Charts are numbers and SVG coordinates. The template draws them with the
page's text color, so light and dark themes both stay readable.
"""

import datetime

from . import clock
from .pools import OPERATIONS

RANGES = ("30", "90", "school", "all")
RANGE_LABELS = {
    "30": "Last 30 days",
    "90": "3 months",
    "school": "School year",
    "all": "All time",
}
TABS = ("overview", "performance", "independence", "pace", "journey", "coverage")


def bounds(today, key, start_month=8):
    """Inclusive start date, or None for all time."""
    if key == "30":
        return today - datetime.timedelta(days=29)
    if key == "90":
        return today - datetime.timedelta(days=89)
    if key == "school":
        year = today.year if today.month >= start_month else today.year - 1
        return datetime.date(year, start_month, 1)
    return None


def filter_rows(rows, today, range_key, operation):
    start = bounds(today, range_key)
    kept = []
    for row in rows:
        day = datetime.date.fromisoformat(row["completed_at"])
        if start and day < start:
            continue
        if day > today:
            continue
        if operation and row["operation"] != operation:
            continue
        kept.append(row)
    return kept


def overview(rows, today):
    week = _week(today)
    month = today.strftime("%Y-%m")
    week_rows = [row for row in rows if _week(_day(row)) == week]
    month_rows = [row for row in rows if row["completed_at"][:7] == month]
    average = None
    if rows:
        average = sum(row["performance"] for row in rows) / len(rows)
    practiced = sorted({_week(_day(row)) for row in rows})
    streak = _trailing(practiced, week)
    days = {_day(row).isoformat() for row in week_rows}
    return {
        "week": len(week_rows),
        "month": len(month_rows),
        "total": len(rows),
        "average": None if average is None else round(average, 1),
        "streak": streak,
        "week_days": [(week + datetime.timedelta(days=offset)).isoformat() for offset in range(7)],
        "practiced_days": days,
    }


def performance_chart(rows):
    """Points for each sheet, oldest on the left. Aided sheets use a square."""
    width, height, left, bottom = 320, 120, 16, 16
    if not rows:
        return {"width": width, "height": height, "points": [], "line": ""}
    span = max(1, len(rows) - 1)
    points = []
    for index, row in enumerate(rows):
        x = left + (width - 28) * index / span
        y = bottom + (height - 28) * (4 - row["performance"]) / 3
        y = height - y
        points.append({
            "x": round(x, 1), "y": round(y, 1),
            "aided": row["support"] < 3,
            "label": row["completed_at"],
        })
    line = " ".join(f"{p['x']},{p['y']}" for p in points)
    return {"width": width, "height": height, "points": points, "line": line}


def stacks(rows, field):
    """Weekly stacks. `field` is performance or support."""
    buckets = {}
    for row in rows:
        key = _week(_day(row))
        buckets.setdefault(key, []).append(row)
    out = []
    for key in sorted(buckets):
        group = buckets[key]
        if field == "performance":
            parts = {
                "excellent": sum(1 for row in group if row["performance"] == 4),
                "good": sum(1 for row in group if row["performance"] == 3),
                "ok": sum(1 for row in group if row["performance"] == 2),
                "low": sum(1 for row in group if row["performance"] == 1),
            }
        else:
            parts = {
                "own": sum(1 for row in group if row["support"] == 3),
                "some": sum(1 for row in group if row["support"] == 2),
                "aid": sum(1 for row in group if row["support"] == 1),
            }
        out.append({"label": clock.format_day(key), "total": len(group), **parts})
    return out


def by_operation(rows):
    totals = {key: [] for key in OPERATIONS}
    for row in rows:
        totals[row["operation"]].append(row["performance"])
    return [
        {
            "operation": key,
            "label": OPERATIONS[key],
            "average": round(sum(scores) / len(scores), 1) if scores else None,
            "count": len(scores),
        }
        for key, scores in totals.items()
    ]


def independence_note(rows):
    own = [row for row in rows if row["support"] == 3]
    if len(rows) < 2:
        return ""
    half = len(rows) // 2
    early = rows[:half]
    late = rows[half:]
    early_share = sum(1 for row in early if row["support"] == 3) / len(early)
    late_share = sum(1 for row in late if row["support"] == 3) / len(late)
    if late_share > early_share:
        return "More recent sheets were done on their own."
    if own:
        return f"{len(own)} of {len(rows)} sheets in this range were done on their own."
    return "Support on these sheets is part of the record. It does not hold the child back."


def pace_points(rows):
    paced = [row for row in rows if row["pace"] is not None]
    width, height, left = 320, 120, 16
    if not paced:
        return {"width": width, "height": height, "points": [], "line": ""}
    span = max(1, len(paced) - 1)
    points = []
    for index, row in enumerate(paced):
        x = left + (width - 28) * index / span
        y = 16 + (height - 28) * (4 - row["pace"]) / 3
        points.append({"x": round(x, 1), "y": round(height - y, 1)})
    line = " ".join(f"{p['x']},{p['y']}" for p in points)
    return {"width": width, "height": height, "points": points, "line": line}


def calendar(rows, today):
    """The current month, with a count of finished sheets on each day."""
    start = today.replace(day=1)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    counts = {}
    for row in rows:
        day = _day(row)
        if start <= day < nxt:
            counts[day.isoformat()] = counts.get(day.isoformat(), 0) + 1
    # Sunday-first padding.
    pad = (start.weekday() + 1) % 7
    days = []
    for _ in range(pad):
        days.append(None)
    day = start
    while day < nxt:
        iso = day.isoformat()
        count = counts.get(iso, 0)
        days.append({"iso": iso, "n": day.day, "count": count, "level": min(count, 3)})
        day += datetime.timedelta(days=1)
    return {"label": start.strftime("%B %Y"), "days": days}


def sheets_per_week(rows):
    return stacks(rows, "performance")


def coverage(problems_by_fact, operation):
    """Average of up to 3 recent sheet scores for each fact. Blank when never seen."""
    limit = 12 if operation in ("mul", "div") else 12
    cells = []
    for a in range(limit + 1):
        row = []
        for b in range(limit + 1):
            sheets = problems_by_fact.get((a, b), [])
            if not sheets:
                row.append({"a": a, "b": b, "level": 0, "dot": False})
                continue
            recent = sheets[:3]
            average = sum(item["performance"] for item in recent) / len(recent)
            dot = any(item["support"] < 3 for item in recent)
            row.append({"a": a, "b": b, "level": int(round(average)), "dot": dot})
        cells.append(row)
    return cells


def _day(row):
    return datetime.date.fromisoformat(row["completed_at"])


def _week(day):
    return day - datetime.timedelta(days=(day.weekday() + 1) % 7)


def _trailing(weeks, current):
    if not weeks:
        return 0
    have = set(weeks)
    end = current if current in have else current - datetime.timedelta(days=7)
    if end not in have:
        return 0
    count = 0
    while end in have:
        count += 1
        end -= datetime.timedelta(days=7)
    return count
