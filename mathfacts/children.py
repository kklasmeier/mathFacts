"""Children: the people a parent makes worksheets for (spec 4.2, 5.12.1).

Every query takes the account ID, so a child from another account is not found.
"""

from . import clock

MAX_CHILDREN = 10
NAME_MAX = 40
GRADE_MAX = 12
COLORS = {
    "red": "Red",
    "orange": "Orange",
    "yellow": "Yellow",
    "green": "Green",
    "blue": "Blue",
    "purple": "Purple",
    "pink": "Pink",
}


def validate(name, grade, color):
    """Return (clean values, errors). Name is required; grade and color are optional."""
    errors = {}
    name = (name or "").strip()
    grade = (grade or "").strip()
    color = (color or "").strip()
    if not name:
        errors["name"] = "Enter a first name or nickname."
    elif len(name) > NAME_MAX:
        errors["name"] = f"Use {NAME_MAX} characters or fewer."
    if len(grade) > GRADE_MAX:
        errors["grade"] = f"Use {GRADE_MAX} characters or fewer."
    if color and color not in COLORS:
        errors["color"] = "Choose a color from the list, or none."
    return {"name": name, "grade": grade or None, "color": color or None}, errors


def list_children(db, account_id, archived=False):
    return db.execute(
        "SELECT * FROM children WHERE account_id = ? AND archived = ? "
        "ORDER BY name COLLATE NOCASE",
        (account_id, 1 if archived else 0),
    ).fetchall()


def get_child(db, account_id, child_id):
    return db.execute(
        "SELECT * FROM children WHERE id = ? AND account_id = ?", (child_id, account_id)
    ).fetchone()


def count_children(db, account_id):
    return db.execute(
        "SELECT COUNT(*) FROM children WHERE account_id = ?", (account_id,)
    ).fetchone()[0]


def create_child(db, account_id, values):
    cursor = db.execute(
        "INSERT INTO children (account_id, name, grade, color, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (account_id, values["name"], values["grade"], values["color"], clock.now()),
    )
    return cursor.lastrowid


def update_child(db, account_id, child_id, values):
    db.execute(
        "UPDATE children SET name = ?, grade = ?, color = ? WHERE id = ? AND account_id = ?",
        (values["name"], values["grade"], values["color"], child_id, account_id),
    )


def set_archived(db, account_id, child_id, archived):
    db.execute(
        "UPDATE children SET archived = ? WHERE id = ? AND account_id = ?",
        (1 if archived else 0, child_id, account_id),
    )


def delete_child(db, account_id, child_id):
    """Permanently remove the child and, through foreign keys, their sheets."""
    db.execute("DELETE FROM children WHERE id = ? AND account_id = ?", (child_id, account_id))
