"""Builder, live preview, saving, and print (spec 5.1 to 5.3).

The main promise: the saved sheet's problems match the preview the parent saw.
Preview and save both come from the same config and seed, so these tests check
that they agree, cell by cell.
"""

import re

from helpers import make_child, sheet_values

from mathfacts import builder


def horizontal_cells(html):
    """The text of each horizontal problem, in page order."""
    return re.findall(r'<div class="horiz">(.*?)</div>', html, flags=re.S)


def saved_problems(db, sheet_id):
    rows = db.execute(
        "SELECT op, a, b FROM worksheet_problems WHERE worksheet_id = ? ORDER BY position",
        (sheet_id,),
    ).fetchall()
    return [(r["op"], r["a"], r["b"]) for r in rows]


def test_builder_shows_one_cell_per_space(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    page = signed_in_client.get(f"/builder?child={cid}").get_data(as_text=True)
    assert page.count('<div class="cell">') == 5 * 8
    assert "sheet-title" in page


def test_builder_without_children_sends_you_to_add_one(signed_in_client):
    response = signed_in_client.get("/builder")
    assert response.status_code == 302
    assert "/children/new" in response.headers["Location"]


def test_saved_sheet_matches_the_preview(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    values = sheet_values(
        cid, a_spec="1-9", b_spec="2,3", include_reverse="on", cols="6", rows="7",
        order="random", seed="4242",
    )

    preview = signed_in_client.post("/api/worksheets/preview", data=values)
    assert preview.status_code == 200
    preview_cells = horizontal_cells(preview.get_json()["html"])
    assert len(preview_cells) == 6 * 7

    response = signed_in_client.post("/builder", data={**values, "action": "save"})
    assert response.status_code == 302
    sheet_id = int(response.headers["Location"].rsplit("/", 1)[1])

    # Stored problems equal what build_sheet gives for the same config.
    cfg, errors = builder.parse(values, {cid})
    assert errors == {}
    expected = builder.build_sheet(cfg)
    assert saved_problems(db, sheet_id) == [(p.op, p.a, p.b) for p in expected.problems]

    # The printed page shows the same problems, in the same order, as the preview.
    printed = signed_in_client.get(f"/worksheets/{sheet_id}/print").get_data(as_text=True)
    assert horizontal_cells(printed) == preview_cells


def test_regenerate_changes_the_seed_and_saves_nothing(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    values = sheet_values(cid, seed="777")
    response = signed_in_client.post("/builder", data={**values, "action": "regenerate"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="seed" value="777"' not in html
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0


def test_save_stores_the_sheet_and_numbers_it_per_account(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    values = sheet_values(cid)
    first = signed_in_client.post("/builder", data={**values, "action": "save"})
    second = signed_in_client.post("/builder", data={**values, "action": "save"})
    assert first.status_code == 302 and second.status_code == 302

    numbers = [
        r["number"] for r in db.execute("SELECT number FROM worksheets ORDER BY number")
    ]
    assert numbers == [1, 2]
    assert db.execute("SELECT next_sheet_number FROM accounts").fetchone()[0] == 3


def test_print_with_answer_key_gives_two_pages(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    values = sheet_values(cid, answer_key="on")
    response = signed_in_client.post("/builder", data={**values, "action": "print"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("?answers=1")
    sheet_id = int(response.headers["Location"].split("/worksheets/")[1].split("/")[0])

    plain = signed_in_client.get(f"/worksheets/{sheet_id}/print").get_data(as_text=True)
    assert plain.count('<article class="sheet') == 1

    with_key = signed_in_client.get(
        f"/worksheets/{sheet_id}/print?answers=1"
    ).get_data(as_text=True)
    assert with_key.count('<article class="sheet') == 2
    assert 'class="sheet portrait pt-' in with_key and " answers" in with_key


def test_preview_rejects_bad_input_with_messages(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    response = signed_in_client.post(
        "/api/worksheets/preview", data=sheet_values(cid, cols="0", a_spec="")
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert "cols" in body["errors"] and "a_spec" in body["errors"]


def test_bad_builder_post_saves_nothing(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    response = signed_in_client.post(
        "/builder", data={**sheet_values(cid, rows="99"), "action": "save"}
    )
    assert response.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0


def test_unknown_action_is_refused(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    response = signed_in_client.post("/builder", data={**sheet_values(cid), "action": "delete"})
    assert response.status_code == 400


def test_detail_page_shows_print_links(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    response = signed_in_client.post(
        "/builder", data={**sheet_values(cid), "action": "save"}
    )
    sheet_id = int(response.headers["Location"].rsplit("/", 1)[1])
    page = signed_in_client.get(f"/worksheets/{sheet_id}").get_data(as_text=True)
    assert "Print with answer key" in page
    assert page.count('<article class="sheet') == 1


def test_landscape_action_switches_the_page_without_saving(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    response = signed_in_client.post(
        "/builder", data={**sheet_values(cid), "action": "landscape"}
    )
    assert response.status_code == 200
    assert 'class="sheet landscape' in response.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == 0


def test_crowded_page_prints_below_10pt_without_a_warning(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    values = sheet_values(cid, a_spec="1-12", b_spec="1-12", cols="10", rows="20",
                          orientation="vertical", seed="9")
    preview = signed_in_client.post("/api/worksheets/preview", data=values).get_json()
    assert not any("Too many problems" in note for note in preview["notices"])
    assert "Auto size:" in preview["auto"]

    saved = signed_in_client.post("/builder", data={**values, "action": "save"})
    sheet_id = int(saved.headers["Location"].rsplit("/", 1)[1])
    printed = signed_in_client.get(f"/worksheets/{sheet_id}/print").get_data(as_text=True)
    match = re.search(r'class="sheet portrait (pt-\d+)', printed)
    assert match
    assert int(match.group(1).split("-")[1]) < 20  # under 10pt
    assert " tight" not in printed


def test_new_sheet_remembers_layout_but_not_the_facts(signed_in_client, db):
    cid = make_child(signed_in_client, db)
    values = sheet_values(
        cid, a_spec="4-6", b_spec="7", orientation="vertical", page_direction="landscape",
        cols="3", rows="4", order="sequential",
    )
    signed_in_client.post("/api/worksheets/preview", data=values)
    page = signed_in_client.get("/builder").get_data(as_text=True)
    assert 'name="orientation" value="vertical" checked' in page
    assert 'name="page_direction" value="landscape" checked' in page
    assert 'name="cols" type="number" min="1" max="10" value="3"' in page
    assert 'name="rows" type="number" min="1" max="20" value="4"' in page
    assert 'value="sequential" selected' in page
    # The fact set goes back to the defaults. Only the layout is remembered.
    assert 'name="a_spec" value="1-9"' in page
    assert 'name="b_spec" value="2"' in page
