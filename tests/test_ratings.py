"""Rating a sheet, the history list, and the advancement rule (spec 5.3 and 5.4).

The home banner that says a child is ready to advance is a later slice. These
tests cover the rule itself and the rating form that feeds it.
"""

from helpers import make_child, sheet_values

from mathfacts import ratings, sheets


def _save(client, child_id, **overrides):
    response = client.post(
        "/builder", data={**sheet_values(child_id, **overrides), "action": "save"}
    )
    assert response.status_code == 302
    return int(response.headers["Location"].rsplit("/", 1)[1])


def test_ready_when_two_of_the_last_three_are_good(signed_in_client):
    # Aids are not an input. A Good sheet counts the same however it was done.
    assert ratings.ready_to_advance([1, 3, 3])
    assert ratings.ready_to_advance([3, 1, 4])
    assert not ratings.ready_to_advance([4, 1, 2])
    assert ratings.ready_to_advance([3, 3])
    assert not ratings.ready_to_advance([4])
    assert ratings.ready_to_advance([1, 1, 2, 4, 3])


def test_rating_requires_performance_and_support(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    sheet_id = _save(signed_in_client, cid)
    missing = signed_in_client.post(f"/worksheets/{sheet_id}/rate", data={"support": "3"})
    assert missing.status_code == 400
    assert b"Choose how it went." in missing.data
    assert db.execute("SELECT status FROM worksheets WHERE id = ?", (sheet_id,)).fetchone()[0] == "issued"

    saved = signed_in_client.post(
        f"/worksheets/{sheet_id}/rate",
        data={
            "performance": "4",
            "support": "2",
            "aid_type": "fingers",
            "pace": "3",
            "completed_on": "2026-11-10",
            "notes": "tired",
        },
    )
    assert saved.status_code == 302
    row = db.execute("SELECT * FROM ratings WHERE worksheet_id = ?", (sheet_id,)).fetchone()
    assert row["performance"] == 4 and row["support"] == 2 and row["aid_type"] == "fingers"
    assert row["pace"] == 3 and row["notes"] == "tired" and row["completed_at"] == "2026-11-10"
    assert db.execute("SELECT status FROM worksheets WHERE id = ?", (sheet_id,)).fetchone()[0] == "completed"

    signed_in_client.post(
        f"/worksheets/{sheet_id}/rate",
        data={"performance": "1", "support": "3", "aid_type": "fingers", "completed_on": "2026-11-11"},
    )
    rows = db.execute("SELECT performance, support, aid_type FROM ratings").fetchall()
    assert len(rows) == 1
    assert (rows[0]["performance"], rows[0]["support"], rows[0]["aid_type"]) == (1, 3, None)

    page = signed_in_client.get(f"/worksheets/{sheet_id}").get_data(as_text=True)
    assert "Needs improvement" in page
    assert "On their own" in page
    assert "Edit rating" in page


def test_on_their_own_clears_the_aid_and_long_notes_are_refused():
    clean, errors = ratings.validate(
        {"performance": "4", "support": "3", "aid_type": "fingers", "notes": "ok"}
    )
    assert errors == {}
    assert clean["aid_type"] is None

    _clean, errors = ratings.validate(
        {"performance": "4", "support": "2", "notes": "x" * 501, "completed_on": "nope"}
    )
    assert "notes" in errors and "completed_on" in errors


def test_list_filters_by_search_child_and_support(signed_in_client, db):
    sam = make_child(signed_in_client, db, "Sam")
    alex = make_child(signed_in_client, db, "Alex")
    rockets = _save(signed_in_client, sam, title="Rockets")
    comets = _save(signed_in_client, alex, title="Comets")
    signed_in_client.post(
        f"/worksheets/{comets}/rate",
        data={"performance": "3", "support": "1", "completed_on": "2026-11-10"},
    )

    by_name = signed_in_client.get("/worksheets?q=Rockets&child=all").get_data(as_text=True)
    assert "Rockets" in by_name and "Comets" not in by_name

    by_number = signed_in_client.get("/worksheets?q=1&child=all").get_data(as_text=True)
    assert "Rockets" in by_number and "Comets" not in by_number

    by_child = signed_in_client.get(f"/worksheets?child={alex}").get_data(as_text=True)
    assert "Comets" in by_child and "Rockets" not in by_child

    by_support = signed_in_client.get("/worksheets?support=1&child=all").get_data(as_text=True)
    assert "Comets" in by_support and "Rockets" not in by_support
    assert "Good" in by_support and "Aid throughout" in by_support

    assert db.execute("SELECT id FROM worksheets WHERE id = ?", (rockets,)).fetchone() is not None


def test_list_pages_fifty_at_a_time(signed_in_client, db, monkeypatch):
    cid = make_child(signed_in_client, db)
    monkeypatch.setattr(sheets, "PAGE_SIZE", 1)
    _save(signed_in_client, cid, title="First")
    _save(signed_in_client, cid, title="Second")
    page = signed_in_client.get("/worksheets").get_data(as_text=True)
    assert "Second" in page and "First" not in page
    assert "Page 1 of 2" in page
    older = signed_in_client.get("/worksheets?page=2").get_data(as_text=True)
    assert "First" in older and "Second" not in older


def test_home_shows_the_childs_unfinished_sheets(signed_in_client, db):
    sam = make_child(signed_in_client, db, "Sam")
    alex = make_child(signed_in_client, db, "Alex")
    _save(signed_in_client, sam, title="Sam sheet")
    page = signed_in_client.get(f"/?child={sam}").get_data(as_text=True)
    assert "Welcome, Kim" in page
    assert "1 unfinished sheet" in page
    assert "Sam sheet" in page

    switched = signed_in_client.get(f"/?child={alex}").get_data(as_text=True)
    assert "No unfinished sheets for Alex" in switched
    assert "Sam sheet" not in switched
    assert "No sheets yet for Alex" in switched


def test_deleting_a_completed_sheet_warns_and_removes_the_rating(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    sheet_id = _save(signed_in_client, cid)
    signed_in_client.post(
        f"/worksheets/{sheet_id}/rate",
        data={"performance": "4", "support": "3", "completed_on": "2026-11-10"},
    )
    preview = signed_in_client.get(f"/worksheets/delete?ids={sheet_id}")
    assert b"counts toward progress" in preview.data
    signed_in_client.post(
        "/worksheets/delete", data={"sheet_id": str(sheet_id), "confirm": "yes"}
    )
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 0
    assert db.execute("SELECT next_sheet_number FROM accounts").fetchone()[0] == 2
