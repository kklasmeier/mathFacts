"""Administrator console (spec 5.13).

The first account is the administrator. These tests check that an inactive
account cannot sign in, a reset forces a new password, the administrator
cannot open another family's sheet, and the administrator cannot inactivate
their own account.
"""

from helpers import make_child, sheet_values

from mathfacts.reset_password import main
from mathfacts import settings

PASSWORD = "correct horse battery"
TEMPORARY = "temporary horse battery"
REPLACEMENT = "a different longer phrase"


def _settings(**overrides):
    values = {
        "max_children": "10",
        "login_log_days": "365",
        "idle_hours": "12",
        "remember_days": "365",
        "reset_hours": "72",
        "terms_text": "",
        "temporary_password": "",
    }
    values.update(overrides)
    return values


def _parent(app, register):
    other = app.test_client()
    response = register(
        email="lee@example.com", username="lee", name="Lee", test_client=other
    )
    assert response.status_code == 302
    return other


def test_parent_cannot_open_admin_and_admin_cannot_open_their_sheet(
    app, register, signed_in_client, db
):
    other = _parent(app, register)
    cid = make_child(other, db, "Lee child")
    saved = other.post("/builder", data={**sheet_values(cid, title="Lee sheet"), "action": "save"})
    sheet_id = int(saved.headers["Location"].rsplit("/", 1)[1])

    assert other.get("/admin").status_code == 404
    assert other.get("/admin/accounts").status_code == 404
    assert other.get("/admin/logins").status_code == 404
    assert other.get(f"/admin/accounts/{1}/reset").status_code == 404

    assert signed_in_client.get(f"/worksheets/{sheet_id}").status_code == 404
    assert signed_in_client.get(f"/worksheets/{sheet_id}/print").status_code == 404

    page = signed_in_client.get("/admin/accounts").get_data(as_text=True)
    assert "lee" in page
    assert "Lee child" not in page
    assert "Lee sheet" not in page
    assert "1 child" in page
    assert "1 sheet" in page
    assert 'href="/admin"' in signed_in_client.get("/").get_data(as_text=True)
    assert 'href="/admin"' not in other.get("/").get_data(as_text=True)


def test_admin_cannot_inactivate_their_own_account(signed_in_client, db):
    admin_id = db.execute("SELECT id FROM accounts WHERE username = 'kim'").fetchone()["id"]
    response = signed_in_client.post(
        f"/admin/accounts/{admin_id}/inactivate", data={"confirm": "yes"}
    )
    assert response.status_code == 302
    assert db.execute("SELECT status FROM accounts WHERE id = ?", (admin_id,)).fetchone()[0] == "active"


def test_inactivate_blocks_sign_in_and_keeps_the_data(app, register, signed_in_client, db):
    other = _parent(app, register)
    cid = make_child(other, db, "Lee child")
    lee_id = db.execute("SELECT id FROM accounts WHERE username = 'lee'").fetchone()["id"]

    preview = signed_in_client.post(f"/admin/accounts/{lee_id}/inactivate")
    assert preview.status_code == 200
    assert b"Inactivate" in preview.data
    assert db.execute("SELECT status FROM accounts WHERE id = ?", (lee_id,)).fetchone()[0] == "active"

    signed_in_client.post(f"/admin/accounts/{lee_id}/inactivate", data={"confirm": "yes"})
    assert db.execute("SELECT status FROM accounts WHERE id = ?", (lee_id,)).fetchone()[0] == "inactive"
    assert db.execute("SELECT name FROM children WHERE id = ?", (cid,)).fetchone()["name"] == "Lee child"
    assert other.get("/").status_code == 302

    refused = app.test_client().post("/login", data={"identifier": "lee", "password": PASSWORD})
    assert refused.status_code == 403
    assert b"inactive" in refused.data

    signed_in_client.post(f"/admin/accounts/{lee_id}/reactivate", data={"confirm": "yes"})
    allowed = app.test_client().post("/login", data={"identifier": "lee", "password": PASSWORD})
    assert allowed.status_code == 302
    assert allowed.headers["Location"] == "/"


def test_reset_forces_a_new_password_and_hides_it_from_the_logs(
    app, register, signed_in_client, db
):
    other = _parent(app, register)
    lee_id = db.execute("SELECT id FROM accounts WHERE username = 'lee'").fetchone()["id"]
    assert signed_in_client.get(f"/admin/accounts/{lee_id}/reset").status_code == 302

    saved = signed_in_client.post("/admin", data=_settings(temporary_password=TEMPORARY))
    assert saved.status_code == 302

    done = signed_in_client.post(
        f"/admin/accounts/{lee_id}/reset", data={"choice": "site"}
    )
    assert done.status_code == 200
    assert TEMPORARY.encode() in done.data
    assert other.get("/").status_code == 302

    old = app.test_client().post("/login", data={"identifier": "lee", "password": PASSWORD})
    assert old.status_code == 401

    forced = app.test_client().post("/login", data={"identifier": "lee", "password": TEMPORARY})
    assert forced.headers["Location"].endswith("/change-password")
    client = app.test_client()
    client.post("/login", data={"identifier": "lee", "password": TEMPORARY})
    refused = client.post(
        "/change-password", data={"new_password": TEMPORARY, "confirm": TEMPORARY}
    )
    assert refused.status_code == 400
    changed = client.post(
        "/change-password", data={"new_password": REPLACEMENT, "confirm": REPLACEMENT}
    )
    assert changed.status_code == 302
    assert client.get("/").status_code == 200

    logged = " ".join(
        (row["detail"] or "") + " " + (row["reason"] or "")
        for row in db.execute(
            "SELECT detail, NULL AS reason FROM audit_log "
            "UNION ALL SELECT NULL, reason FROM login_events"
        )
    )
    assert TEMPORARY not in logged
    assert "Password reset" in signed_in_client.get("/admin/audit").get_data(as_text=True)


def test_expired_temporary_password_stops_working(app, register, signed_in_client, db, clock):
    _parent(app, register)
    lee_id = db.execute("SELECT id FROM accounts WHERE username = 'lee'").fetchone()["id"]
    signed_in_client.post("/admin", data=_settings(temporary_password=TEMPORARY, reset_hours="72"))
    signed_in_client.post(f"/admin/accounts/{lee_id}/reset", data={"choice": "site"})
    clock.advance(73 * 3600)

    refused = app.test_client().post("/login", data={"identifier": "lee", "password": TEMPORARY})
    assert refused.status_code == 403
    assert b"expired" in refused.data


def test_sign_in_log_filters_and_csv_have_no_child_data(app, register, signed_in_client, db):
    other = _parent(app, register)
    make_child(other, db, "Lee child")
    csv_response = signed_in_client.get("/admin/logins.csv")
    assert csv_response.mimetype == "text/csv"
    text = csv_response.get_data(as_text=True)
    assert text.startswith("time,event,account,attempted,device,ip,browser,success,reason")
    assert "Registered" in text
    assert "Lee child" not in text

    filtered = signed_in_client.get("/admin/logins.csv?account=2&event=registration")
    narrowed = filtered.get_data(as_text=True)
    assert "lee" in narrowed
    assert "kim" not in narrowed
    assert "Lee child" not in narrowed
    page = signed_in_client.get("/admin/logins?account=2&event=registration").get_data(as_text=True)
    assert "Lee child" not in page


def test_terms_and_child_limit_follow_site_settings(signed_in_client, db):
    signed_in_client.post(
        "/admin", data=_settings(max_children="1", terms_text="Families keep their own sheets.")
    )
    assert b"Families keep their own sheets." in signed_in_client.get("/terms").data
    make_child(signed_in_client, db, "Sam")
    again = signed_in_client.post(
        "/children/new", data={"name": "Alex", "grade": "", "color": ""}
    )
    assert again.status_code == 302
    assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 1


def test_revoke_device_ends_that_sign_in(app, register, signed_in_client, db):
    other = _parent(app, register)
    lee_id = db.execute("SELECT id FROM accounts WHERE username = 'lee'").fetchone()["id"]
    remembered = db.execute(
        "SELECT id FROM remembered_logins WHERE account_id = ? AND revoked_at IS NULL",
        (lee_id,),
    ).fetchone()["id"]
    signed_in_client.post(
        f"/admin/accounts/{lee_id}/revoke", data={"remembered_id": remembered}
    )
    assert other.get("/").status_code == 302
    assert db.execute(
        "SELECT revoked_at FROM remembered_logins WHERE id = ?", (remembered,)
    ).fetchone()["revoked_at"] is not None


def test_temporary_password_round_trip_and_command_line_reset(app, register, monkeypatch):
    register()
    with app.app_context():
        stored = settings.encrypt_text(TEMPORARY)
        assert settings.decrypt_text(stored) == TEMPORARY
        assert TEMPORARY not in stored

    monkeypatch.setattr("mathfacts.create_app", lambda test_config=None: app)
    assert main(["reset_password"]) == 2
    assert main(["reset_password", "kim", "--password", REPLACEMENT]) == 0
    client = app.test_client()
    response = client.post("/login", data={"identifier": "kim", "password": REPLACEMENT})
    assert response.status_code == 302
