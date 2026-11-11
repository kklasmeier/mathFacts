from mathfacts.db import SCHEMA_VERSION, connect, init_db


def test_init_creates_database_file_and_schema_table(tmp_path):
    path = tmp_path / "nested" / "mathfacts.db"
    init_db(path)

    assert path.exists()
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT value FROM schema_info WHERE key = 'version'"
        ).fetchone()
        assert row["value"] == str(SCHEMA_VERSION)
    finally:
        conn.close()


def test_init_uses_wal_journal_mode(tmp_path):
    path = tmp_path / "mathfacts.db"
    init_db(path)

    conn = connect(path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
    finally:
        conn.close()


def test_init_is_idempotent(tmp_path):
    path = tmp_path / "mathfacts.db"
    init_db(path)
    init_db(path)

    conn = connect(path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_app_creates_database_at_configured_path(tmp_path):
    from mathfacts import create_app

    path = tmp_path / "configured.db"
    create_app(
        {"TESTING": True, "SECRET_KEY": "x", "DATABASE": str(path)}
    )
    assert path.exists()
