"""Plans, next sheet, and advancement (spec 5.6)."""

import random
from urllib.parse import parse_qs, urlparse

from helpers import make_child, sheet_values

from mathfacts.pools import Problem, constrained_pool
from mathfacts.slots import arrange
from mathfacts.specs import parse_spec


def test_standard_addition_does_not_cap_sums(db):
    row = db.execute(
        """
        SELECT name, pair_rule, pair_rule_limit
        FROM plan_stages WHERE stage_key = 'add-sums-10'
        """
    ).fetchone()
    assert row["name"] == "Facts 0–10"
    assert row["pair_rule"] == "any"
    assert row["pair_rule_limit"] is None


def test_pair_rules_for_sums_and_doubles():
    values = parse_spec("0-10", 20)
    sums = constrained_pool("add", values, values, pair_rule="sum_max", pair_limit=10)
    assert sums.facts
    assert all(fact.a + fact.b <= 10 for fact in sums.facts)
    assert not any(fact.a + fact.b == 11 for fact in sums.facts)

    doubles = constrained_pool(
        "add", parse_spec("1-9", 20), parse_spec("0-12", 20), pair_rule="operands_equal"
    )
    assert [fact.b for fact in doubles.facts] == [fact.a for fact in doubles.facts]
    assert len(doubles.facts) == 9


def test_review_mix_takes_its_share_from_earlier_stages():
    current = [Problem("mul", number, 3) for number in range(13)]
    review = [Problem("mul", number, 2) for number in range(13)]
    page = arrange(current, 4, 5, "shuffled", random.Random(1), review=review, review_pct=20)
    review_facts = set(review)
    assert sum(1 for fact in page.cells if fact in review_facts) == 4
    assert len(page.cells) == 20


def test_wizard_opens_the_builder_and_does_not_save(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    before = db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0]
    response = signed_in_client.post(
        f"/children/{child}/plans/setup",
        data={
            "step": "5", "ops": "mul", "src_mul": "system", "stage_mul": "5",
            "x": "2", "y": "3", "performance": "3", "action": "generate",
        },
    )
    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith("/builder")
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == before

    page = signed_in_client.get(location)
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert "0-12" in text
    assert 'name="b_spec" value="3"' in text
    signed_in_client.get(location)
    assert db.execute("SELECT COUNT(*) FROM worksheets").fetchone()[0] == before

    query = parse_qs(urlparse(location).query)
    stage_id = query["stage"][0]
    saved = signed_in_client.post(
        "/builder",
        data={**sheet_values(child, cols="3", rows="4"), "plan_stage_id": stage_id, "action": "save"},
    )
    assert saved.status_code == 302
    again = signed_in_client.post(
        "/builder",
        data={**sheet_values(child, cols="4", rows="4", seed="99"), "plan_stage_id": stage_id, "action": "save"},
    )
    assert again.status_code == 302
    rows = db.execute(
        "SELECT plan_stage_id, b_spec, cols FROM worksheets ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert {row["plan_stage_id"] for row in rows} == {int(stage_id)}
    assert {row["b_spec"] for row in rows} == {"3"}
    assert db.execute(
        "SELECT default_cols FROM plan_stages WHERE id = ?", (stage_id,)
    ).fetchone()["default_cols"] == 5
    progress = db.execute(
        "SELECT current_stage_id FROM child_plan_progress WHERE child_id = ?", (child,)
    ).fetchone()
    assert progress["current_stage_id"] == int(stage_id)


def test_aids_count_and_a_copy_does_not_change_the_standard_plan(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    signed_in_client.post(
        f"/children/{child}/plans/setup",
        data={
            "step": "5", "ops": "mul", "src_mul": "system", "stage_mul": "5",
            "x": "2", "y": "3", "performance": "3", "action": "done",
        },
    )
    stage = db.execute(
        """
        SELECT s.id, p.id AS plan_id
        FROM plan_stages s
        JOIN plans p ON p.id = s.plan_id
        JOIN child_plan_progress g ON g.plan_id = p.id
        WHERE g.child_id = ? AND s.stage_key = 'mul-3'
        """,
        (child,),
    ).fetchone()
    for performance in (3, 1, 3):
        saved = signed_in_client.post(
            "/builder",
            data={**sheet_values(child), "plan_stage_id": stage["id"], "action": "save"},
        )
        sheet_id = int(saved.headers["Location"].rsplit("/", 1)[1])
        rated = signed_in_client.post(
            f"/worksheets/{sheet_id}/rate",
            data={"performance": str(performance), "support": "1"},
        )
        assert rated.status_code == 302

    page = signed_in_client.get(f"/children/{child}/plans").get_data(as_text=True)
    assert "Current stage: ×4" in page

    signed_in_client.post(
        f"/plans/{stage['plan_id']}",
        data={
            "action": "save", "stage_id": stage["id"], "stage_name": "Renamed times three",
            "a_spec": "0-12", "b_spec": "3", "pair_rule": "any", "review_mix_pct": "20",
            "cols": "5", "rows": "4",
        },
    )
    standard = db.execute(
        """
        SELECT s.name FROM plan_stages s
        JOIN plans p ON p.id = s.plan_id
        WHERE p.is_system = 1 AND s.stage_key = 'mul-3'
        """
    ).fetchone()["name"]
    assert standard == "×3"
    renamed = db.execute(
        "SELECT name FROM plan_stages WHERE id = ?", (stage["id"],)
    ).fetchone()["name"]
    assert renamed == "Renamed times three"


def test_other_accounts_cannot_open_plans(app, register, signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    signed_in_client.post(
        f"/children/{child}/plans/setup",
        data={"step": "5", "ops": "add", "src_add": "system", "stage_add": "1", "action": "done"},
    )
    plan_id = db.execute(
        "SELECT plan_id FROM child_plan_progress WHERE child_id = ?", (child,)
    ).fetchone()["plan_id"]
    other = app.test_client()
    register(email="lee@example.com", username="lee", name="Lee", test_client=other)
    assert other.get(f"/children/{child}/plans").status_code == 404
    assert other.get(f"/children/{child}/progress").status_code == 404
    assert other.get(f"/children/{child}/badges").status_code == 404
    assert other.get(f"/plans/{plan_id}").status_code == 404
    assert signed_in_client.get(f"/children/{child}/progress").status_code == 200


def test_standard_plan_is_an_ordered_path(signed_in_client):
    page = signed_in_client.get("/plans/system/mul").get_data(as_text=True)
    assert 'class="plan-path"' in page
    assert page.index("×0 and ×1") < page.index("×2") < page.index("×5")
    assert "3 sheets before moving on" in page


def test_editor_builds_an_ordered_path(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    signed_in_client.post(
        f"/children/{child}/plans/setup",
        data={"step": "5", "ops": "add", "src_add": "scratch", "action": "done"},
    )
    plan_id = db.execute(
        "SELECT plan_id FROM child_plan_progress WHERE child_id = ?", (child,)
    ).fetchone()["plan_id"]
    signed_in_client.post(f"/plans/{plan_id}", data={"action": "add"})
    page = signed_in_client.get(f"/plans/{plan_id}").get_data(as_text=True)
    assert page.index("Stage 1") < page.index("Stage 2")
    assert page.index('class="plan-marker"') < page.index("Stage 1")
    assert "Add a stage" in page
    assert "Plan options" in page
    assert "Move Up" in page and "Move Down" in page
    assert "Help: Pair rule" in page
    assert "Help: Review %" in page

    stage = db.execute(
        "SELECT id FROM plan_stages WHERE plan_id = ? AND position = 2", (plan_id,)
    ).fetchone()
    saved_response = signed_in_client.post(
        f"/plans/{plan_id}",
        data={
            "action": "save", "stage_id": stage["id"], "stage_name": "Times two",
            "operation": "mul", "a_spec": "0-12", "b_spec": "2", "include_reverse": "on",
            "min_sheets": "4", "performance": "4", "pair_rule": "any", "review_mix_pct": "10",
        },
    )
    assert f"#stage-{stage['id']}" in saved_response.headers["Location"]
    assert f"open={stage['id']}" in saved_response.headers["Location"]
    saved = db.execute("SELECT * FROM plan_stages WHERE id = ?", (stage["id"],)).fetchone()
    assert saved["operation"] == "mul"
    assert saved["include_reverse"] == 1
    assert saved["min_sheets"] == 4
    assert saved["adv_min_performance"] == 4

    signed_in_client.post(
        f"/plans/{plan_id}",
        data={"action": "options", "cols": "6", "rows": "3", "spacing": "compact"},
    )
    # The first stage still has no numbers, so the next sheet uses stage 2.
    builder = signed_in_client.get(f"/builder?child={child}&stage={stage['id']}")
    text = builder.get_data(as_text=True)
    assert 'name="cols" type="number" min="1" max="10" value="6"' in text
    assert 'name="rows" type="number" min="1" max="20" value="3"' in text
    assert 'name="spacing" value="compact" checked' in text
    assert 'name="include_reverse" checked' in text

    shown = signed_in_client.get(f"/children/{child}/plans").get_data(as_text=True)
    assert shown.index("Stage 1") < shown.index("Times two")
    assert "both orders" in shown


def _rate_plan_sheet(client, child, stage_id, performance):
    saved = client.post(
        "/builder",
        data={**sheet_values(child), "plan_stage_id": str(stage_id), "action": "save"},
    )
    sheet_id = int(saved.headers["Location"].rsplit("/", 1)[1])
    rated = client.post(
        f"/worksheets/{sheet_id}/rate",
        data={"performance": str(performance), "support": "1"},
    )
    assert rated.status_code == 302
    return sheet_id


def _current_key(db, child):
    return db.execute(
        """
        SELECT s.stage_key FROM plan_stages s
        JOIN child_plan_progress g ON g.current_stage_id = s.id
        WHERE g.child_id = ?
        """,
        (child,),
    ).fetchone()["stage_key"]


def test_the_last_sheet_moves_on_after_the_minimum(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    signed_in_client.post(
        f"/children/{child}/plans/setup",
        data={
            "step": "5", "ops": "mul", "src_mul": "system", "stage_mul": "1",
            "y": "2", "performance": "3", "action": "done",
        },
    )
    stage_id = db.execute(
        """
        SELECT s.id FROM plan_stages s
        JOIN child_plan_progress g ON g.plan_id = s.plan_id
        WHERE g.child_id = ? AND s.stage_key = 'mul-0-1'
        """,
        (child,),
    ).fetchone()["id"]
    _rate_plan_sheet(signed_in_client, child, stage_id, 4)
    assert _current_key(db, child) == "mul-0-1"
    _rate_plan_sheet(signed_in_client, child, stage_id, 1)
    assert _current_key(db, child) == "mul-0-1"
    _rate_plan_sheet(signed_in_client, child, stage_id, 3)
    assert _current_key(db, child) == "mul-2"


def test_assign_prepares_a_sheet_and_a_stage_can_be_removed(signed_in_client, db):
    child = make_child(signed_in_client, db, "Alex")
    created = signed_in_client.post(
        "/plans/new", data={"name": "Addition facts", "operation": "add"}
    )
    plan_id = int(created.headers["Location"].rsplit("/", 1)[1])
    signed_in_client.post(f"/plans/{plan_id}", data={"action": "add"})
    second = db.execute(
        "SELECT id FROM plan_stages WHERE plan_id = ? AND position = 2", (plan_id,)
    ).fetchone()
    signed_in_client.post(
        f"/plans/{plan_id}", data={"action": "remove", "stage_id": second["id"]}
    )
    left = db.execute(
        "SELECT position FROM plan_stages WHERE plan_id = ? ORDER BY position", (plan_id,)
    ).fetchall()
    assert [row["position"] for row in left] == [1]

    signed_in_client.post(f"/plans/{plan_id}/assign", data={"child": str(child)})
    home = signed_in_client.get(f"/?child={child}").get_data(as_text=True)
    assert "Stage 1 of 1" in home
    assert "Grade" in home
    sheet = db.execute(
        "SELECT id FROM worksheets WHERE child_id = ? AND plan_stage_id IS NOT NULL",
        (child,),
    ).fetchone()
    detail = signed_in_client.get(f"/worksheets/{sheet['id']}").get_data(as_text=True)
    assert "Change and regenerate" not in detail
    assert "Regenerate" in detail
