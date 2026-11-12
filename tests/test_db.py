import sqlite3

import pytest

from mathfacts import create_app
from mathfacts.db import MIGRATIONS, SCHEMA_VERSION, connect, init_db

TABLES = {
    "accounts",
    "devices",
    "remembered_logins",
    "sessions",
    "login_events",
    "rate_events",
    "children",
    "worksheets",
    "worksheet_problems",
    "ratings",
    "account_settings",
    "app_settings",
    "audit_log",
    "plans",
    "plan_stages",
    "child_plan_progress",
    "stage_history",
    "badges",
    "child_badges",
}


def _tables(path):
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


def _version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0]
    finally:
        conn.close()


def test_init_creates_file_and_schema_version(tmp_path):
    path = tmp_path / "new.db"
    init_db(path)
    assert path.exists()
    assert _version(path) == str(SCHEMA_VERSION)


def test_init_uses_wal_mode(tmp_path):
    path = tmp_path / "wal.db"
    init_db(path)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_init_is_idempotent(tmp_path):
    path = tmp_path / "again.db"
    init_db(path)
    init_db(path)
    assert _version(path) == str(SCHEMA_VERSION)


def test_slice_one_tables_exist(tmp_path):
    path = tmp_path / "tables.db"
    init_db(path)
    assert TABLES <= _tables(path)


def test_upgrade_from_version_zero_database(tmp_path):
    """The Pi already has a slice 0 database (version 0). It must upgrade cleanly."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_info (key, value) VALUES ('version', '0')")
    conn.commit()
    conn.close()

    init_db(path)

    assert _version(path) == str(SCHEMA_VERSION)
    assert TABLES <= _tables(path)


def test_migrations_are_sequential():
    assert sorted(MIGRATIONS) == list(range(1, SCHEMA_VERSION + 1))


def test_foreign_keys_are_enforced(tmp_path):
    path = tmp_path / "fk.db"
    init_db(path)
    conn = connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions (id, account_id, device_id, login_type, created_at, "
                "last_seen_at, expires_at) VALUES ('x', 999, 'nope', 'hard', 0, 0, 0)"
            )
    finally:
        conn.close()


def test_app_creates_database_at_configured_path(tmp_path):
    path = tmp_path / "configured.db"
    create_app({"TESTING": True, "SECRET_KEY": "x", "DATABASE": str(path)})
    assert path.exists()
