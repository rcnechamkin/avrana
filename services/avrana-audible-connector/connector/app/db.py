"""SQLite access with a tiny forward-only migration runner.

WAL mode + a short busy timeout make the single-writer/many-reader pattern safe for a
low-traffic onboarding app. All access goes through short-lived connections.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(db_path: str) -> list[str]:
    """Apply any unapplied .sql files in migrations/ in lexical order. Idempotent."""
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        applied = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
        ran: list[str] = []
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (path.name,))
            ran.append(path.name)
        return ran
    finally:
        conn.close()


def q(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))


def one(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
    cur = conn.execute(sql, tuple(params))
    return cur.fetchone()
