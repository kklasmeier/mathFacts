"""One account cannot reach another account's children or sheets (spec 6).

Every query filters by the signed-in account. These tests use two accounts and
check that the other one gets 404 (or a refusal), and that nothing changes.
"""

from helpers import make_child, sheet_values


def _second_account(app, register):
    other = app.test_client()
    response = register(
        email="lee@example.com", username="lee", name="Lee", test_client=other
    )
    assert response.status_code == 302
    return other


def test_other_account_cannot_open_edit_archive_or_delete(app, register, signed_in_client, db):
    cid = make_child(signed_in_client, db, "Sam")
    other = _second_account(app, register)

    assert other.get(f"/children/{cid}/edit").status_code == 404
    assert other.post(f"/children/{cid}/edit", data={"name": "Hacked"}).status_code == 404
    assert other.post(f"/children/{cid}/archive").status_code == 404
    assert other.post(f"/children/{cid}/delete", data={"confirm_name": "Sam"}).status_code == 404

    row = db.execute("SELECT name, archived FROM children WHERE id = ?", (cid,)).fetchone()
    assert row["name"] == "Sam" and row["archived"] == 0


def test_other_account_cannot_open_or_print_a_sheet(app, register, signed_in_client, db):
    cid = make_child(signed_in_client, db, "Sam")
    saved = signed_in_client.post("/builder", data={**sheet_values(cid), "action": "save"})
    sheet_id = int(saved.headers["Location"].rsplit("/", 1)[1])
    other = _second_account(app, register)

    assert other.get(f"/worksheets/{sheet_id}").status_code == 404
    assert other.get(f"/worksheets/{sheet_id}/print").status_code == 404
    assert other.get(f"/worksheets/{sheet_id}/print?answers=1").status_code == 404


def test_other_account_cannot_build_a_sheet_for_someone_elses_child(
    app, register, signed_in_client, db
):
    cid = make_child(signed_in_client, db, "Sam")
    other = _second_account(app, register)

    preview = other.post("/api/worksheets/preview", data=sheet_values(cid))
    assert preview.status_code == 400
    assert "child" in preview.get_json()["errors"]

    saved = other.post("/builder", data={**sheet_values(cid), "action": "save"})
    assert saved.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0


def test_builder_ignores_another_accounts_child_in_the_url(app, register, signed_in_client, db):
    cid = make_child(signed_in_client, db, "Sam")
    other = _second_account(app, register)
    make_child(other, db, "Lee's child")

    page = other.get(f"/builder?child={cid}").get_data(as_text=True)
    assert "Sam" not in page
    assert "Lee&#39;s child" in page or "Lee's child" in page


def test_other_account_cannot_rate_regenerate_duplicate_or_delete_a_sheet(
    app, register, signed_in_client, db
):
    cid = make_child(signed_in_client, db, "Sam")
    saved = signed_in_client.post(
        "/builder", data={**sheet_values(cid, title="Sam secret sheet"), "action": "save"}
    )
    sheet_id = int(saved.headers["Location"].rsplit("/", 1)[1])
    other = _second_account(app, register)

    assert other.get(f"/worksheets/{sheet_id}/rate").status_code == 404
    assert other.post(
        f"/worksheets/{sheet_id}/rate", data={"performance": "4", "support": "3"}
    ).status_code == 404
    assert other.post(f"/worksheets/{sheet_id}/regenerate").status_code == 404
    assert other.post(f"/worksheets/{sheet_id}/duplicate").status_code == 404
    assert other.get(f"/builder?replace={sheet_id}").status_code == 404

    other.post("/worksheets/delete", data={"sheet_id": str(sheet_id), "confirm": "yes"})
    assert db.execute("SELECT title FROM worksheets WHERE id = ?", (sheet_id,)).fetchone()["title"] == "Sam secret sheet"
    assert "Sam secret sheet" not in other.get("/worksheets").get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 0
