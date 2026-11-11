from mathfacts import children


def add_child(client, name="Sam", grade="2", color="blue"):
    return client.post("/children/new", data={"name": name, "grade": grade, "color": color})


def child_id(db, name):
    row = db.execute(
        "SELECT id FROM children WHERE name = ? ORDER BY id DESC", (name,)
    ).fetchone()
    return row["id"]


def test_add_child_shows_in_the_list(signed_in_client, db):
    response = add_child(signed_in_client, "Sam")
    assert response.status_code == 302
    page = signed_in_client.get("/children").get_data(as_text=True)
    assert "Sam" in page
    assert child_id(db, "Sam")


def test_name_is_required(signed_in_client, db):
    response = add_child(signed_in_client, name="   ")
    assert response.status_code == 400
    assert "Enter a first name or nickname." in response.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0


def test_unknown_color_is_refused(signed_in_client, db):
    response = add_child(signed_in_client, color="plaid")
    assert response.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0


def test_grade_and_color_are_optional(signed_in_client, db):
    response = signed_in_client.post("/children/new", data={"name": "Lee"})
    assert response.status_code == 302
    row = db.execute("SELECT grade, color FROM children WHERE name = 'Lee'").fetchone()
    assert row["grade"] is None and row["color"] is None


def test_edit_changes_name_and_color(signed_in_client, db):
    add_child(signed_in_client, "Sam", color="blue")
    cid = child_id(db, "Sam")
    response = signed_in_client.post(
        f"/children/{cid}/edit", data={"name": "Samuel", "grade": "3", "color": "green"}
    )
    assert response.status_code == 302
    row = db.execute("SELECT name, color FROM children WHERE id = ?", (cid,)).fetchone()
    assert row["name"] == "Samuel" and row["color"] == "green"


def test_limit_is_ten_children(signed_in_client, db):
    for i in range(children.MAX_CHILDREN):
        add_child(signed_in_client, f"Child {i}")
    assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 10

    response = signed_in_client.get("/children/new")
    assert response.status_code == 302
    add_child(signed_in_client, "One too many")
    assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 10


def test_archive_hides_a_child_from_the_builder_and_restore_brings_back(
    signed_in_client, db
):
    add_child(signed_in_client, "Sam")
    cid = child_id(db, "Sam")

    signed_in_client.post(f"/children/{cid}/archive")
    assert signed_in_client.get("/builder").status_code == 302  # no active children
    page = signed_in_client.get("/children").get_data(as_text=True)
    assert "Archived" in page

    signed_in_client.post(f"/children/{cid}/restore")
    assert signed_in_client.get("/builder").status_code == 200


def test_delete_needs_the_name_typed_out(signed_in_client, db):
    add_child(signed_in_client, "Sam")
    cid = child_id(db, "Sam")

    signed_in_client.post(f"/children/{cid}/delete", data={"confirm_name": "Sa"})
    assert db.execute("SELECT COUNT(*) FROM children WHERE id = ?", (cid,)).fetchone()[0] == 1

    # Matching ignores case and surrounding spaces.
    signed_in_client.post(f"/children/{cid}/delete", data={"confirm_name": "  sam "})
    assert db.execute("SELECT COUNT(*) FROM children WHERE id = ?", (cid,)).fetchone()[0] == 0


def test_deleting_a_child_deletes_their_sheets(signed_in_client, db):
    add_child(signed_in_client, "Sam")
    cid = child_id(db, "Sam")
    signed_in_client.post(
        "/builder",
        data={
            "child": str(cid), "operation": "add", "a_spec": "1-3", "b_spec": "2",
            "orientation": "horizontal", "page_direction": "portrait", "cols": "3",
            "rows": "2", "order": "sequential", "spacing": "normal", "seed": "5",
            "action": "save",
        },
    )
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM worksheet_problems").fetchone()[0] == 6

    signed_in_client.post(f"/children/{cid}/delete", data={"confirm_name": "Sam"})
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM worksheet_problems").fetchone()[0] == 0


def test_children_pages_render(signed_in_client, db):
    assert signed_in_client.get("/children").status_code == 200
    assert signed_in_client.get("/children/new").status_code == 200
    add_child(signed_in_client, "Sam", color="red")
    cid = child_id(db, "Sam")
    edit = signed_in_client.get(f"/children/{cid}/edit").get_data(as_text=True)
    assert "Archive" in edit and "Delete Sam permanently" in edit
    assert 'value="red" checked' in edit
    assert signed_in_client.get("/children/9999/edit").status_code == 404
