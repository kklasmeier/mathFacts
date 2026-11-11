import pytest

from mathfacts import clock as clock_module
from mathfacts import create_app
from mathfacts.db import connect

PASSWORD = "correct horse battery"


class FakeClock:
    """Stands in for mathfacts.clock.now so tests can move time forward."""

    def __init__(self, start=1_800_000_000):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(clock_module, "now", fake)
    return fake


def _config(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "SECRET_KEY": "test-secret-not-for-production",
        "DATABASE": str(tmp_path / "test.db"),
        "WTF_CSRF_ENABLED": False,
        # Cheap hashing keeps the suite fast. Production values are in config.py.
        "ARGON2_TIME_COST": 1,
        "ARGON2_MEMORY_COST": 8192,
        "ARGON2_PARALLELISM": 1,
    }
    config.update(overrides)
    return config


@pytest.fixture
def app(tmp_path, clock):
    return create_app(_config(tmp_path))


@pytest.fixture
def csrf_app(tmp_path, clock):
    """The same app with CSRF checks turned on, for the CSRF tests only."""
    return create_app(_config(tmp_path, WTF_CSRF_ENABLED=True))


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def new_client(app):
    """Make another client, which behaves like a second device or browser."""
    return app.test_client


@pytest.fixture
def db(app):
    conn = connect(app.config["DATABASE"])
    yield conn
    conn.close()


@pytest.fixture
def register(client):
    """Create an account through the sign-up form. Returns the response."""

    def _register(
        email="kim@example.com",
        username="kim",
        name="Kim",
        password=PASSWORD,
        guardian="yes",
        test_client=None,
    ):
        target = test_client or client
        data = {
            "name": name,
            "email": email,
            "username": username,
            "password": password,
            "confirm": password,
        }
        if guardian:
            data["guardian"] = guardian
        return target.post("/register", data=data)

    return _register


@pytest.fixture
def signed_in_client(client, register):
    """A client already signed in as the first (administrator) account."""
    response = register()
    assert response.status_code == 302
    return client
