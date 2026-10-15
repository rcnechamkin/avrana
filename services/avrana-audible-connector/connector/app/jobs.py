"""Idempotent import-job creation, polling, and retry.

The dedup lock is the partial unique index `idx_job_active` on (connection_id, asin) for
non-terminal jobs: attempting to queue a book that already has an active job raises an
IntegrityError, which we treat as "already queued" and return the existing job. So a page
refresh or double-click can never create duplicate work.
"""
from __future__ import annotations

import sqlite3
import uuid

from . import audit
from .companion_client import CompanionClient, CompanionError
from .db import one
from .security import redact, valid_asin


def queue_book(conn: sqlite3.Connection, cid: str, sub: str, asin: str) -> tuple[sqlite3.Row, bool]:
    """Create (or return existing) active job for a book. Returns (job_row, created)."""
    if not valid_asin(asin):
        raise ValueError("invalid asin")
    # Must be an eligible purchased book that isn't already imported.
    book = one(
        conn,
        "SELECT * FROM book WHERE connection_id=? AND asin=?",
        (cid, asin),
    )
    if book is None or book["eligibility"] != "purchased":
        raise ValueError("not an importable purchased title")
    if book["status"] == "imported":
        existing = one(
            conn,
            "SELECT * FROM job WHERE connection_id=? AND asin=? ORDER BY created_at DESC LIMIT 1",
            (cid, asin),
        )
        return existing, False

    jid = uuid.uuid4().hex
    try:
        conn.execute(
            "INSERT INTO job(id, connection_id, asin, status) VALUES (?,?,?,'queued')",
            (jid, cid, asin),
        )
    except sqlite3.IntegrityError:
        # Active job already exists (dedup lock). Return it; do not create a duplicate.
        existing = one(
            conn,
            "SELECT * FROM job WHERE connection_id=? AND asin=? AND status IN ('queued','running')",
            (cid, asin),
        )
        return existing, False
    conn.execute(
        "UPDATE book SET status='queued', updated_at=datetime('now') "
        "WHERE connection_id=? AND asin=?",
        (cid, asin),
    )
    audit.record(conn, audit.BOOK_QUEUED, sub=sub, connection_id=cid, detail=asin)
    return one(conn, "SELECT * FROM job WHERE id=?", (jid,)), True


async def dispatch_queued(
    conn: sqlite3.Connection, client: CompanionClient, profile_id: str, cid: str
) -> None:
    """Hand queued jobs to the companion (creates a companion job id). Idempotent per job."""
    pending = conn.execute(
        "SELECT * FROM job WHERE connection_id=? AND status='queued' AND companion_job IS NULL",
        (cid,),
    ).fetchall()
    for job in pending:
        try:
            resp = await client.backup(profile_id, job["asin"])
            comp_id = resp.get("id") or resp.get("jobId")
            conn.execute(
                "UPDATE job SET companion_job=?, status='running', attempts=attempts+1,"
                " updated_at=datetime('now') WHERE id=?",
                (comp_id, job["id"]),
            )
            conn.execute(
                "UPDATE book SET status='importing', updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=?",
                (cid, job["asin"]),
            )
        except CompanionError as exc:
            conn.execute(
                "UPDATE job SET status='failed', failure=?, attempts=attempts+1,"
                " updated_at=datetime('now') WHERE id=?",
                (redact(exc.user_message), job["id"]),
            )
            conn.execute(
                "UPDATE book SET status='failed', updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=?",
                (cid, job["asin"]),
            )


async def poll_jobs(
    conn: sqlite3.Connection, client: CompanionClient, profile_id: str, cid: str, sub: str
) -> None:
    """Refresh running jobs from the companion. Safe to call on every progress page load."""
    running = conn.execute(
        "SELECT * FROM job WHERE connection_id=? AND status='running' AND companion_job IS NOT NULL",
        (cid,),
    ).fetchall()
    for job in running:
        try:
            state = await client.job(profile_id, job["companion_job"])
        except CompanionError:
            continue  # transient; leave as running and try next poll
        status = str(state.get("status", "")).lower()
        if status in ("succeeded", "success", "completed"):
            conn.execute(
                "UPDATE job SET status='succeeded', updated_at=datetime('now') WHERE id=?",
                (job["id"],),
            )
            conn.execute(
                "UPDATE book SET status='imported', updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=?",
                (cid, job["asin"]),
            )
            audit.record(conn, audit.IMPORT_COMPLETED, sub=sub, connection_id=cid, detail=job["asin"])
        elif status == "skipped":
            # The companion refused the download because the shared library already holds
            # this ASIN. That is a success for the user's intent (the book is in Avrana), so
            # it must not surface as a failure or leave the job stuck 'running' forever.
            conn.execute(
                "UPDATE job SET status='succeeded', updated_at=datetime('now') WHERE id=?",
                (job["id"],),
            )
            conn.execute(
                "UPDATE book SET status='already', updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=?",
                (cid, job["asin"]),
            )
        elif status in ("failed", "error"):
            msg = redact(state.get("error") or "Import failed")
            conn.execute(
                "UPDATE job SET status='failed', failure=?, updated_at=datetime('now') WHERE id=?",
                (msg[:200], job["id"]),
            )
            conn.execute(
                "UPDATE book SET status='failed', updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=?",
                (cid, job["asin"]),
            )
            audit.record(conn, audit.IMPORT_FAILED, sub=sub, connection_id=cid, detail=job["asin"])


def retry_failed(conn: sqlite3.Connection, cid: str, asin: str) -> bool:
    """Reset a failed job/book back to queued so dispatch picks it up again."""
    job = one(
        conn,
        "SELECT * FROM job WHERE connection_id=? AND asin=? AND status='failed' "
        "ORDER BY created_at DESC LIMIT 1",
        (cid, asin),
    )
    if job is None:
        return False
    conn.execute(
        "UPDATE job SET status='queued', companion_job=NULL, failure=NULL,"
        " updated_at=datetime('now') WHERE id=?",
        (job["id"],),
    )
    conn.execute(
        "UPDATE book SET status='queued', updated_at=datetime('now') "
        "WHERE connection_id=? AND asin=?",
        (cid, asin),
    )
    return True


def all_selected_done(conn: sqlite3.Connection, cid: str) -> bool:
    """True when the member chose books and every one is in. A failed book counts as unfinished,
    so a one-time import keeps the Audible authorization and the member can still Retry it."""
    row = one(
        conn,
        "SELECT "
        " SUM(CASE WHEN b.status IN ('selected','queued','importing','failed') THEN 1 ELSE 0 END)"
        "   AS pending,"
        # 'already' counts as done: the book is in Avrana, which is what the user asked for.
        # Without it, a once-mode run whose only selection was already present would leave
        # pending=0/done=0 and never revoke the stored Audible authorization. Only books the
        # member chose count (they have a job): a scan also marks books already in the library
        # 'already', and those alone must never finish a one-time import.
        " SUM(CASE WHEN b.status IN ('imported','already') AND EXISTS ("
        "   SELECT 1 FROM job j WHERE j.connection_id=b.connection_id AND j.asin=b.asin)"
        "   THEN 1 ELSE 0 END) AS done "
        "FROM book b WHERE b.connection_id=?",
        (cid,),
    )
    pending = row["pending"] or 0
    done = row["done"] or 0
    return pending == 0 and done > 0
