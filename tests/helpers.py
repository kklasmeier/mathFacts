"""Small helpers shared by the route tests."""


def make_child(client, db, name="Sam"):
    client.post("/children/new", data={"name": name, "grade": "2", "color": "blue"})
    return db.execute(
        "SELECT id FROM children WHERE name = ? ORDER BY id DESC", (name,)
    ).fetchone()["id"]


def sheet_values(child_id, **overrides):
    """Form values the way the builder posts them. Checkboxes are present when on."""
    values = {
        "child": str(child_id),
        "operation": "mul",
        "a_spec": "1-9",
        "b_spec": "2",
        "orientation": "horizontal",
        "page_direction": "portrait",
        "cols": "5",
        "rows": "8",
        "order": "shuffled",
        "title": "",
        "spacing": "normal",
        "seed": "12345",
        "name_line": "on",
        "date_line": "on",
    }
    values.update(overrides)
    return values
