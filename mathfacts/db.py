"""SQLite connection and startup schema setup.

WAL mode lets several gunicorn workers read while one writes. Later slices
add real tables by bumping SCHEMA_VERSION and adding a migration step.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 0


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path):
    """Create the database file and the schema_info table if missing."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_info ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_info (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        conn.close()
