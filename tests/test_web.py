import pytest

from mathfacts import create_app


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_home_redirects_to_sign_in_when_signed_out(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_home_shows_name_when_signed_in(signed_in_client):
    response = signed_in_client.get("/")
    assert response.status_code == 200
    assert b"Welcome, Kim" in response.data


def test_header_groups_account_items_in_the_name_menu(signed_in_client, db):
    signed_in_client.post("/children/new", data={"name": "Alex", "grade": "2", "color": "blue"})
    page = signed_in_client.get("/").get_data(as_text=True)
    header = page.split("<main", 1)[0]
    primary = header.split('class="primary-nav"', 1)[1].split("</nav>", 1)[0]
    assert "Home" in primary and "Sheets" in primary and "New sheet" in primary
    assert "Password" not in primary and "Light" not in primary
    account = header.split('class="dropdown account-menu"', 1)[1].split("</details>", 1)[0]
    for item in ("Profile", "Change password", "Plans", "Admin", "Match device", "Sign out"):
        assert item in account
    child = header.split('class="dropdown child-menu"', 1)[1].split("</details>", 1)[0]
    assert "Alex" in child and "Manage children" in child


def test_security_headers_present(client):
    response = client.get("/health")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_pages_are_not_cached(client):
    response = client.get("/login")
    assert response.headers["Cache-Control"] == "no-store"


def test_static_css_is_served(client):
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert b"--bg" in response.data


def test_production_refuses_to_start_without_secret(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
        create_app({"DATABASE": str(tmp_path / "x.db"), "SECRET_KEY": ""})
