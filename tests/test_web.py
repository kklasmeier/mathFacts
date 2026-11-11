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
