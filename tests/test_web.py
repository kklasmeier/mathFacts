import pytest

from mathfacts import create_app


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_index_serves_holding_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Math Facts" in response.get_data(as_text=True)


def test_security_headers_present(client):
    response = client.get("/health")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_production_refuses_to_start_without_secret(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(
            {
                "TESTING": False,
                "SECRET_KEY": "",
                "DATABASE": str(tmp_path / "prod.db"),
            }
        )
