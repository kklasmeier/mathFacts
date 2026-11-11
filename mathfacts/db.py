"""SQLite connection, schema migrations, and startup setup.

Each migration is a list of SQL statements keyed by its version. Startup
applies every migration newer than the version stored in schema_info, inside
one transaction per migration. Later slices add a new key; old keys never change.
"""

import sqlite3
from pathlib import Path

MIGRATIONS = {
    # Slice 1: accounts, devices, sessions, remembered sign-ins, sign-in log,
    # and rate-limit counters. Shapes follow spec section 6.
    1: [
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'parent')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            must_change_password INTEGER NOT NULL DEFAULT 0,
            password_reset_expires_at INTEGER,
            created_at INTEGER NOT NULL,
            last_login_at INTEGER,
            last_login_type TEXT
        )
        """,
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            first_seen_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            last_ip TEXT,
            user_agent_summary TEXT
        )
        """,
        """
        CREATE TABLE remembered_logins (
            id TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            device_id TEXT NOT NULL REFERENCES devices(id),
            secret_hash TEXT NOT NULL,
            prev_secret_hash TEXT,
            prev_valid_until INTEGER,
            label TEXT,
            created_at INTEGER NOT NULL,
            last_used_at INTEGER,
            expires_at INTEGER NOT NULL,
            revoked_at INTEGER,
            revoked_reason TEXT
        )
        """,
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            device_id TEXT NOT NULL REFERENCES devices(id),
            login_type TEXT NOT NULL CHECK (login_type IN ('hard', 'soft')),
            remembered_login_id TEXT REFERENCES remembered_logins(id) ON DELETE SET NULL,
            created_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            ended_at INTEGER
        )
        """,
        """
        CREATE TABLE login_events (
            id INTEGER PRIMARY KEY,
            at INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            success INTEGER NOT NULL,
            account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            attempted_identifier TEXT,
            device_id TEXT,
            remembered_login_id TEXT,
            session_id TEXT,
            ip TEXT,
            user_agent TEXT,
            user_agent_summary TEXT,
            reason TEXT
        )
        """,
        "CREATE INDEX login_events_identifier ON login_events(attempted_identifier, event_type, at)",
        "CREATE INDEX login_events_ip ON login_events(ip, event_type, at)",
        """
        CREATE TABLE rate_events (
            id INTEGER PRIMARY KEY,
            bucket TEXT NOT NULL,
            at INTEGER NOT NULL
        )
        """,
        "CREATE INDEX rate_events_bucket ON rate_events(bucket, at)",
    ],
}

SCHEMA_VERSION = max(MIGRATIONS)


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_version(conn):
    return int(
        conn.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()[0]
    )


def apply_migrations(conn):
    current = current_version(conn)
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(
                "UPDATE schema_info SET value = ? WHERE key = 'version'",
                (str(version),),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = version


def init_db(path):
    """Create the database file, bring the schema up to date, and close it."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_info ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_info (key, value) VALUES ('version', '0')"
        )
        conn.commit()
        apply_migrations(conn)
    finally:
        conn.close()
