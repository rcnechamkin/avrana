"""Ownership-scoped data access. Every read/write is bound to an Authentik subject so a
user can never address another user's connection, catalog, or jobs."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from .db import one, q


def _uuid() -> str:
    return uuid.uuid4().hex


def get_connection_for_sub(conn: sqlite3.Connection, sub: str) -> sqlite3.Row | None:
    """The (single) active connection owned by this subject, if any."""
    return one(
        conn,
        "SELECT * FROM connection WHERE authentik_sub=? AND state != 'disconnected' "
        "ORDER BY created_at DESC LIMIT 1",
        (sub,),
    )


def get_connection_owned(conn: sqlite3.Connection, connection_id: str, sub: str) -> sqlite3.Row | None:
    """Fetch a connection only if it belongs to `sub`. Returns None otherwise. This is
    the core cross-user isolation check used by every route that takes a connection id."""
    return one(
        conn,
        "SELECT * FROM connection WHERE id=? AND authentik_sub=?",
        (connection_id, sub),
    )


def create_connection(
    conn: sqlite3.Connection, sub: str, email: str, marketplace: str
) -> sqlite3.Row:
    """Start a fresh connection for `sub` + `email`, replacing a retained disconnected one.

    THERE ARE TWO DISCONNECT PATHS AND THEY DO NOT AGREE:
      - a manual disconnect (routes/flow.py) calls delete_connection_cascade(), so the row
        is gone and this function's INSERT is unproblematic;
      - a `once`-mode sync auto-revokes in sync.py by setting state='disconnected' and
        KEEPING the row, so the import history survives.

    get_connection_for_sub() filters `state != 'disconnected'`, so the retained row is
    invisible to the caller and it falls through to here -- where the INSERT collided with
    that very row on UNIQUE(authentik_sub, audible_email) and raised IntegrityError, i.e. a
    500 on the connect form. The effect was that anyone who completed a `once` sync could
    never reconnect that Audible account again.

    Clearing the stale row (rather than reviving it in place) keeps reconnect semantics
    identical to the manual-disconnect path: a genuinely fresh profile_id, no inherited
    book/job rows, and baselined=0 so the first scan is a baseline and Auto cannot dump the
    back catalogue (migration 002). Audit rows are unaffected -- audit.connection_id carries
    no FK, exactly as for a manual disconnect.
    """
    email = email.strip().lower()
    stale = one(
        conn,
        "SELECT id FROM connection WHERE authentik_sub=? AND audible_email=?",
        (sub, email),
    )
    if stale is not None:
        delete_connection_cascade(conn, stale["id"])
    cid = _uuid()
    profile_id = _uuid()
    conn.execute(
        "INSERT INTO connection(id, authentik_sub, profile_id, audible_email, marketplace) "
        "VALUES (?,?,?,?,?)",
        (cid, sub, profile_id, email.strip().lower(), marketplace),
    )
    return one(conn, "SELECT * FROM connection WHERE id=?", (cid,))


def set_connection_state(conn: sqlite3.Connection, cid: str, state: str, failure: str | None = None) -> None:
    conn.execute(
        "UPDATE connection SET state=?, failure=? WHERE id=?", (state, failure, cid)
    )


def set_sync_mode(conn: sqlite3.Connection, cid: str, mode: str) -> None:
    conn.execute("UPDATE connection SET sync_mode=? WHERE id=?", (mode, cid))


def mark_scanned(conn: sqlite3.Connection, cid: str) -> None:
    conn.execute(
        "UPDATE connection SET last_scan_at=datetime('now') WHERE id=?", (cid,)
    )


def mark_baselined(conn: sqlite3.Connection, cid: str) -> None:
    """Record that this connection has had its first (baseline) scan. Idempotent."""
    conn.execute("UPDATE connection SET baselined=1 WHERE id=?", (cid,))


def create_auth_session(
    conn: sqlite3.Connection, sub: str, cid: str, companion_session: str, ttl_seconds: int
) -> str:
    sid = _uuid()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO auth_session(id, authentik_sub, connection_id, companion_session, expires_at) "
        "VALUES (?,?,?,?,?)",
        (sid, sub, cid, companion_session, expires),
    )
    return sid


def get_auth_session_owned(conn: sqlite3.Connection, sid: str, sub: str) -> sqlite3.Row | None:
    return one(
        conn, "SELECT * FROM auth_session WHERE id=? AND authentik_sub=?", (sid, sub)
    )


def auth_session_expired(row: sqlite3.Row) -> bool:
    try:
        return datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc)
    except Exception:
        return True


def delete_auth_session(conn: sqlite3.Connection, sid: str) -> None:
    conn.execute("DELETE FROM auth_session WHERE id=?", (sid,))


def books_for_connection(conn: sqlite3.Connection, cid: str) -> list[sqlite3.Row]:
    return q(
        conn,
        "SELECT * FROM book WHERE connection_id=? ORDER BY "
        "CASE eligibility WHEN 'purchased' THEN 0 WHEN 'plus' THEN 1 ELSE 2 END, title",
        (cid,),
    )


def delete_connection_cascade(conn: sqlite3.Connection, cid: str) -> None:
    # ON DELETE CASCADE handles book/job/auth_session.
    conn.execute("DELETE FROM connection WHERE id=?", (cid,))
