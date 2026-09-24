"""Audit trail. Records meaningful events without ever storing secrets.

Callers must pass already-safe detail strings; this module additionally redacts as a
belt-and-suspenders measure.
"""
from __future__ import annotations

import sqlite3

from .security import redact

# Canonical event names (stable strings for downstream tooling).
CONNECTION_STARTED = "connection_started"
CONNECTION_COMPLETED = "connection_completed"
SYNC_MODE_CHANGED = "sync_mode_changed"
BOOK_QUEUED = "book_queued"
IMPORT_COMPLETED = "import_completed"
IMPORT_FAILED = "import_failed"
ACCOUNT_DISCONNECTED = "account_disconnected"
SCAN_RAN = "scan_ran"


def record(
    conn: sqlite3.Connection,
    event: str,
    *,
    sub: str | None = None,
    connection_id: str | None = None,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO audit(authentik_sub, connection_id, event, detail) VALUES (?,?,?,?)",
        (sub, connection_id, event, redact(detail)[:500]),
    )
