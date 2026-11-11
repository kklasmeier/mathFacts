"""Slice 1 behavior: registration, sign-in, remembered devices, sign-out, password change.

Each test describes one rule from spec section 5.11. The `clock` fixture moves
time forward so expiry and lockout rules can be checked without waiting.
"""

from conftest import PASSWORD
from mathfacts.security import sha256_hex

GENERIC_ERROR = b"That username or password is not right."
LOCKED_ERROR = b"Sign-in is paused"
NEW_PASSWORD = "a brand new phrase here"


def _count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _events(db, event_type):
    return db.execute(
        "SELECT * FROM login_events WHERE event_type = ?", (event_type,)
    ).fetchall()


# --- Registration -----------------------------------------------------------


def test_first_account_becomes_administrator_and_later_accounts_are_parents(
    client, register, new_client, db
):
    register()
    register(email="lee@example.com", username="lee", test_client=new_client())
    roles = [row["role"] for row in db.execute("SELECT role FROM accounts ORDER BY id")]
    assert roles == ["admin", "parent"]


def test_registration_signs_the_new_account_in(client, register):
    response = register()
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/welcome")
    assert client.get("/").status_code == 200


def test_registration_rejects_bad_input_and_creates_nothing(app, client, db):
    # Each case is one attempt, so lift the per-hour limit for this test only.
    app.config["REGISTER_LIMIT"] = 100
    cases = [
        {"email": "not-an-email"},
        {"username": "a b"},
        {"password": "short", "confirm": "short"},
        {"password": "password1234", "confirm": "password1234"},
        # Password may not repeat the username.
        {"username": "longusername1", "password": "longusername1", "confirm": "longusername1"},
        {"confirm": "something else entirely"},
    ]
    for overrides in cases:
        data = {
            "email": "kim@example.com",
            "username": "kim",
            "password": PASSWORD,
            "confirm": PASSWORD,
            "guardian": "yes",
        }
        data.update(overrides)
        response = client.post("/register", data=data)
        assert response.status_code == 400, overrides
    assert _count(db, "accounts") == 0


def test_registration_requires_guardian_confirmation(client, register, db):
    response = register(guardian=None)
    assert response.status_code == 400
    assert _count(db, "accounts") == 0


def test_duplicate_email_is_refused_in_any_case(client, register, new_client, db):
    register()
    response = register(email="KIM@example.com", username="other", test_client=new_client())
    assert response.status_code == 400
    assert b"already registered" in response.data
    assert _count(db, "accounts") == 1


def test_honeypot_field_blocks_bots(client, db):
    response = client.post(
        "/register",
        data={
            "email": "bot@example.com", "username": "botty", "password": PASSWORD,
            "confirm": PASSWORD, "guardian": "yes", "website": "http://spam.example",
        },
    )
    assert response.status_code == 400
    assert _count(db, "accounts") == 0


def test_registration_attempts_are_rate_limited(client):
    for _ in range(5):
        client.post("/register", data={})
    assert client.post("/register", data={}).status_code == 429


def test_password_is_stored_as_argon2id_hash(client, register, db):
    register()
    stored = db.execute("SELECT password_hash FROM accounts").fetchone()[0]
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


# --- Sign-in ----------------------------------------------------------------


def test_sign_in_accepts_username_or_email_in_any_case(client, register, new_client):
    register()
    for identifier in ["KIM", "Kim@Example.com"]:
        other = new_client()
        response = other.post(
            "/login", data={"identifier": identifier, "password": PASSWORD}
        )
        assert response.status_code == 302, identifier
        assert other.get("/").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client, register, new_client):
    register()
    wrong = new_client().post(
        "/login", data={"identifier": "kim", "password": "not the password here"}
    )
    unknown = new_client().post(
        "/login", data={"identifier": "nobody", "password": "not the password here"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert GENERIC_ERROR in wrong.data
    assert GENERIC_ERROR in unknown.data


def test_next_must_stay_on_this_site(client, register, new_client):
    register()
    response = new_client().post(
        "/login",
        data={"identifier": "kim", "password": PASSWORD, "next": "https://evil.example"},
    )
    assert response.headers["Location"] == "/"


def test_next_keeps_a_local_page(client, register, new_client):
    register()
    response = new_client().post(
        "/login",
        data={"identifier": "kim", "password": PASSWORD, "next": "/welcome"},
    )
    assert response.headers["Location"] == "/welcome"


def test_signed_out_pages_redirect_to_sign_in_with_return_path(client):
    response = client.get("/?tab=2")
    assert response.status_code == 302
    assert "next=" in response.headers["Location"]


def test_repeated_failures_lock_sign_in_even_with_the_right_password(
    client, register, new_client, clock, db
):
    register()
    for _ in range(5):
        new_client().post("/login", data={"identifier": "kim", "password": "wrong wrong wrong"})
    locked = new_client().post("/login", data={"identifier": "kim", "password": PASSWORD})
    assert locked.status_code == 429
    assert LOCKED_ERROR in locked.data
    assert len(_events(db, "lockout")) == 1

    clock.advance(15 * 60 + 1)
    assert new_client().post(
        "/login", data={"identifier": "kim", "password": PASSWORD}
    ).status_code == 302


def test_lock_applies_to_unknown_names_too(client, new_client):
    for _ in range(5):
        new_client().post("/login", data={"identifier": "ghost", "password": "wrong wrong wrong"})
    assert new_client().post(
        "/login", data={"identifier": "ghost", "password": "wrong wrong wrong"}
    ).status_code == 429


def test_network_address_comes_from_the_proxy_header(register, new_client, db):
    register()
    visitor = new_client()  # signed out, so the sign-in form is reachable
    visitor.post(
        "/login",
        data={"identifier": "kim", "password": "wrong wrong wrong"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    row = _events(db, "failed_login")[0]
    assert row["ip"] == "203.0.113.9"


def test_password_never_appears_in_the_sign_in_log(client, register, new_client, db):
    register()
    client.post("/logout")
    new_client().post("/login", data={"identifier": "kim", "password": "typo typo typo"})
    rows = [dict(row) for row in db.execute("SELECT * FROM login_events")]
    assert rows
    assert PASSWORD not in repr(rows)
    assert "typo typo typo" not in repr(rows)


def test_inactive_account_cannot_sign_in_and_existing_sessions_end(
    client, register, new_client, db
):
    register()
    db.execute("UPDATE accounts SET status = 'inactive'")
    db.commit()
    assert new_client().post(
        "/login", data={"identifier": "kim", "password": PASSWORD}
    ).status_code == 403
    assert client.get("/").status_code == 302


# --- Cookies and storage ----------------------------------------------------


def test_session_cookies_are_http_only_and_lax(client, register):
    response = register()
    cookies = response.headers.getlist("Set-Cookie")
    sid = next(c for c in cookies if c.startswith("sid="))
    rt = next(c for c in cookies if c.startswith("rt="))
    for cookie in (sid, rt):
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie


def test_session_and_remembered_secrets_are_stored_only_as_hashes(client, register, db):
    register()
    sid = client.get_cookie("sid").value
    rl_id, secret = client.get_cookie("rt").value.split(".", 1)

    assert db.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone() is None
    assert db.execute(
        "SELECT 1 FROM sessions WHERE id = ?", (sha256_hex(sid),)
    ).fetchone() is not None

    row = db.execute("SELECT secret_hash FROM remembered_logins WHERE id = ?", (rl_id,)).fetchone()
    assert row["secret_hash"] == sha256_hex(secret)
    assert secret not in row["secret_hash"]


def test_device_cookie_is_set_once_and_reused(client, register, db):
    register()
    did = client.get_cookie("did").value
    client.get("/")
    client.get("/")
    assert client.get_cookie("did").value == did
    assert _count(db, "devices") == 1


# --- Remembered devices -----------------------------------------------------


def test_closing_the_browser_keeps_sign_in_through_the_remembered_device(
    client, register, db
):
    register()
    client.delete_cookie("sid")
    assert client.get("/").status_code == 200
    assert len(_events(db, "soft_login")) == 1


def test_idle_session_ends_and_remembered_device_signs_back_in(
    client, register, clock, db
):
    register()
    clock.advance(13 * 60 * 60)
    assert client.get("/").status_code == 200
    assert len(_events(db, "soft_login")) == 1


def test_remembered_sign_in_expires_after_a_year_without_use(client, register, clock):
    register()
    client.delete_cookie("sid")
    clock.advance(366 * 24 * 60 * 60)
    assert client.get("/").status_code == 302


def test_remembered_cookie_rotates_on_use(client, register):
    register()
    old_rt = client.get_cookie("rt").value
    client.delete_cookie("sid")
    client.get("/")
    assert client.get_cookie("rt").value != old_rt


def test_old_remembered_cookie_works_briefly_for_a_second_tab(
    client, register, new_client
):
    register()
    old_rt = client.get_cookie("rt").value
    client.delete_cookie("sid")
    client.get("/")  # rotates the secret

    second_tab = new_client()
    second_tab.set_cookie("rt", old_rt)
    assert second_tab.get("/").status_code == 200
    # The grace match does not rotate again, so the newest cookie stays valid.
    assert second_tab.get_cookie("rt").value == old_rt


def test_old_remembered_cookie_after_grace_is_treated_as_suspicious(
    client, register, new_client, clock, db
):
    register()
    old_rt = client.get_cookie("rt").value
    client.delete_cookie("sid")
    client.get("/")
    clock.advance(61)

    stale = new_client()
    stale.set_cookie("rt", old_rt)
    assert stale.get("/").status_code == 302
    assert len(_events(db, "suspicious_cookie")) == 1

    # The remembered sign-in is revoked, so the real device must sign in again.
    client.delete_cookie("sid")
    assert client.get("/").status_code == 302


def test_tampered_remembered_cookie_is_rejected(client, register, new_client):
    register()
    rl_id = client.get_cookie("rt").value.split(".", 1)[0]
    attacker = new_client()
    attacker.set_cookie("rt", f"{rl_id}.guessed-secret")
    assert attacker.get("/").status_code == 302


# --- Sign-out ---------------------------------------------------------------


def test_sign_out_ends_the_session_and_remembered_sign_in(client, register, new_client):
    register()
    old_sid = client.get_cookie("sid").value
    old_rt = client.get_cookie("rt").value

    assert client.post("/logout").status_code == 302
    assert client.get("/").status_code == 302

    replay_rt = new_client()
    replay_rt.set_cookie("rt", old_rt)
    assert replay_rt.get("/").status_code == 302

    replay_sid = new_client()
    replay_sid.set_cookie("sid", old_sid)
    assert replay_sid.get("/").status_code == 302


def test_sign_out_needs_a_post(client, register):
    register()
    assert client.get("/logout").status_code == 405


def test_sign_out_on_one_device_leaves_other_devices_signed_in(
    client, register, new_client
):
    register()
    other = new_client()
    other.post("/login", data={"identifier": "kim", "password": PASSWORD})

    client.post("/logout")
    assert other.get("/").status_code == 200


# --- Password change --------------------------------------------------------


def test_forced_change_blocks_other_pages_until_done(client, register, db):
    register()
    db.execute("UPDATE accounts SET must_change_password = 1")
    db.commit()

    assert client.get("/").headers["Location"].endswith("/change-password")
    assert b"Your administrator asked" in client.get("/change-password").data

    same = client.post(
        "/change-password", data={"new_password": PASSWORD, "confirm": PASSWORD}
    )
    assert same.status_code == 400

    done = client.post(
        "/change-password", data={"new_password": NEW_PASSWORD, "confirm": NEW_PASSWORD}
    )
    assert done.status_code == 302
    assert client.get("/").status_code == 200
    flag = db.execute("SELECT must_change_password FROM accounts").fetchone()[0]
    assert flag == 0


def test_change_password_needs_the_current_password(client, register):
    register()
    response = client.post(
        "/change-password",
        data={
            "current_password": "not my password",
            "new_password": NEW_PASSWORD,
            "confirm": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert b"not your current password" in response.data


def test_password_change_signs_out_other_devices_but_not_this_one(
    client, register, new_client
):
    register()
    other = new_client()
    other.post("/login", data={"identifier": "kim", "password": PASSWORD})
    assert other.get("/").status_code == 200

    response = client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm": NEW_PASSWORD,
        },
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 200
    assert other.get("/").status_code == 302


def test_old_password_stops_working_after_change(client, register, new_client):
    register()
    client.post(
        "/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm": NEW_PASSWORD,
        },
    )
    assert new_client().post(
        "/login", data={"identifier": "kim", "password": PASSWORD}
    ).status_code == 401
    assert new_client().post(
        "/login", data={"identifier": "kim", "password": NEW_PASSWORD}
    ).status_code == 302


# --- Appearance -------------------------------------------------------------


def test_theme_choice_is_saved_and_applied(client):
    response = client.post("/appearance", data={"theme": "dark", "next": "/login"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert b'data-theme="dark"' in client.get("/login").data


def test_unknown_theme_is_refused(client):
    assert client.post("/appearance", data={"theme": "neon"}).status_code == 400


# --- CSRF -------------------------------------------------------------------


def test_forms_include_a_csrf_token_and_reject_posts_without_one(csrf_app):
    client = csrf_app.test_client()
    assert b'name="csrf_token"' in client.get("/login").data
    response = client.post("/login", data={"identifier": "x", "password": "y"})
    assert response.status_code == 400
