"""Badge awarding and the print banner (spec 5.7)."""

import json

from helpers import make_child, sheet_values

from mathfacts import badges


def _award(db, child_id, count):
    rows = db.execute(
        "SELECT id FROM badges WHERE account_id IS NULL ORDER BY id LIMIT ?", (count,)
    ).fetchall()
    for row in rows:
        assert badges.award(db, child_id, row["id"])
        assert badges.award(db, child_id, row["id"]) is False
    db.commit()


def _save(client, child, **extra):
    response = client.post("/builder", data={**sheet_values(child), "action": "save", **extra})
    assert response.status_code == 302
    return int(response.headers["Location"].rsplit("/", 1)[1])


def test_banner_shows_four_and_keeps_the_rest_pending(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    _award(db, child, 7)
    sheet_id = _save(signed_in_client, child, badges_on="on")
    options = json.loads(db.execute(
        "SELECT options_json FROM worksheets WHERE id = ?", (sheet_id,)
    ).fetchone()["options_json"])
    assert len(options["banner"]) == 4
    assert options["banner_more"] == 3
    assert badges.pending_count(db, child) == 3
    page = signed_in_client.get(f"/worksheets/{sheet_id}").get_data(as_text=True)
    assert "+3 more" in page

    signed_in_client.post(
        "/worksheets/delete", data={"sheet_id": sheet_id, "confirm": "yes"}
    )
    assert badges.pending_count(db, child) == 7
    assert db.execute(
        "SELECT COUNT(*) FROM child_badges WHERE child_id = ? AND shown_at IS NULL",
        (child,),
    ).fetchone()[0] == 7


def test_deleting_a_finished_sheet_keeps_badges_shown(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    _award(db, child, 2)
    sheet_id = _save(signed_in_client, child, badges_on="on")
    signed_in_client.post(
        f"/worksheets/{sheet_id}/rate",
        data={"performance": "3", "support": "3"},
    )
    pending = badges.pending_count(db, child)
    signed_in_client.post(
        "/worksheets/delete", data={"sheet_id": sheet_id, "confirm": "yes"}
    )
    assert badges.pending_count(db, child) == pending
    assert db.execute(
        "SELECT COUNT(*) FROM child_badges WHERE child_id = ? AND shown_at IS NOT NULL",
        (child,),
    ).fetchone()[0] == 2


def test_a_badge_is_awarded_once(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    first = _save(signed_in_client, child)
    signed_in_client.post(
        f"/worksheets/{first}/rate", data={"performance": "4", "support": "3"}
    )
    signed_in_client.post(
        f"/worksheets/{first}/rate", data={"performance": "3", "support": "3"}
    )
    second = _save(signed_in_client, child)
    signed_in_client.post(
        f"/worksheets/{second}/rate", data={"performance": "4", "support": "3"}
    )
    count = db.execute(
        """
        SELECT COUNT(*) FROM child_badges cb
        JOIN badges b ON b.id = cb.badge_id
        WHERE cb.child_id = ? AND b.key = 'first_sheet'
        """,
        (child,),
    ).fetchone()[0]
    assert count == 1
    page = signed_in_client.get(f"/children/{child}/badges").get_data(as_text=True)
    assert "First Sheet" in page
    assert "Earned" in page
