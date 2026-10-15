"""Sync-mode behaviour and the background scheduler.

Modes:
  once  -> import selected; when all selected succeed, revoke auth (delete profile).
  ask   -> daily metadata scan; newly-seen purchased ASINs become 'pending' for approval.
  auto  -> daily metadata scan; newly-seen purchased ASINs are auto-queued (never Plus,
           never already present/active/completed/excluded).
"""
from __future__ import annotations

import asyncio
import sqlite3

from . import audit, catalog, jobs
from .companion_client import CompanionClient, CompanionError
from .db import one, q
from .security import redact


def existing_asins_in_avrana(conn: sqlite3.Connection) -> set[str]:
    """ASINs already imported into the shared Avrana library (library-wide fact, not
    user-private). Used to flag books as 'already' rather than re-import them.

    Connector-DB half only: this sees imports the connector itself performed. The library
    also contains books that predate the connector, which only the companion can see; callers
    should union `await client.present()` on top (see run_scan).
    """
    rows = q(conn, "SELECT DISTINCT asin FROM book WHERE status='imported'")
    return {r["asin"] for r in rows}


async def run_scan(
    conn: sqlite3.Connection,
    client: CompanionClient,
    connection_row: sqlite3.Row,
    sub: str,
    *,
    poll_seconds: float = 20.0,
) -> dict:
    """Metadata-only scan: trigger a companion scan, wait briefly, normalize the library."""
    cid = connection_row["id"]
    profile = connection_row["profile_id"]
    result = await client.scan(profile)
    scan_job = result.get("id") or result.get("jobId")
    # Poll the scan job to completion (bounded) so the fresh snapshot is ready.
    waited = 0.0
    while scan_job and waited < poll_seconds:
        try:
            state = await client.job(profile, scan_job)
        except CompanionError:
            break
        if str(state.get("status", "")).lower() in ("succeeded", "success", "completed", "failed", "error"):
            break
        await asyncio.sleep(1.0)
        waited += 1.0
    # Is this the connection's FIRST-ever scan? Captured before we mark it baselined below.
    # The whole catalogue is "newly seen" on this scan, but it is the pre-existing library,
    # not a batch of new purchases, so ask/auto must not act on it (see apply_mode_after_scan).
    is_baseline = not bool(connection_row["baselined"])

    snapshot = await client.library(profile)
    # Union both halves of "already in Avrana": what this connector imported, and what is
    # physically on the library filesystem (the 193 pre-connector books the admin Libation
    # instance wrote, which no connector DB has ever recorded).
    on_disk = await client.present()  # None = companion could not answer
    existing = existing_asins_in_avrana(conn) | (on_disk or set())
    outcome = catalog.normalize_and_upsert(conn, cid, snapshot, existing, on_disk=on_disk)
    from .repo import mark_baselined, mark_scanned

    mark_scanned(conn, cid)
    mark_baselined(conn, cid)
    outcome["is_baseline"] = is_baseline
    audit.record(conn, audit.SCAN_RAN, sub=sub, connection_id=cid,
                 detail=f"seen={outcome['seen']} new={len(outcome['newly_seen'])} baseline={is_baseline}")
    return outcome


async def apply_mode_after_scan(
    conn: sqlite3.Connection,
    client: CompanionClient,
    connection_row: sqlite3.Row,
    sub: str,
    newly_seen: list[str],
    *,
    is_baseline: bool = False,
) -> None:
    """Mode-specific handling of newly-seen ASINs from a scan.

    On the BASELINE scan (a connection's first), `newly_seen` is the entire pre-existing
    catalogue, not new purchases, so ask/auto do nothing: no auto-download, no flood of
    pending approvals. The user still selects what they want from the library page. Only
    purchases that appear in a subsequent scan are treated as new.
    """
    cid = connection_row["id"]
    mode = connection_row["sync_mode"]
    if is_baseline:
        return
    if mode == "ask":
        # Surface new purchased titles as 'pending' for the user to approve.
        for asin in newly_seen:
            conn.execute(
                "UPDATE book SET status='pending', updated_at=datetime('now') "
                "WHERE connection_id=? AND asin=? AND eligibility='purchased' AND status='available'",
                (cid, asin),
            )
    elif mode == "auto":
        for asin in newly_seen:
            book = one(conn, "SELECT * FROM book WHERE connection_id=? AND asin=?", (cid, asin))
            if book is None:
                continue
            # Only auto-queue genuinely new purchased titles; never Plus/borrowed, and never
            # anything already present/active/completed/excluded.
            if book["eligibility"] == "purchased" and book["status"] == "available":
                try:
                    jobs.queue_book(conn, cid, sub, asin)
                except ValueError:
                    continue
        await jobs.dispatch_queued(conn, client, connection_row["profile_id"], cid)


async def finalize_once_mode(
    conn: sqlite3.Connection, client: CompanionClient, connection_row: sqlite3.Row, sub: str
) -> bool:
    """For 'once' mode: if every chosen book is in (none failed or pending), revoke auth.
    Returns True only for the one caller that revoked.

    Concurrent callers (two Refreshes, or Refresh and the scheduler) are safe: the connection is
    claimed with a single conditional UPDATE ('connected' -> 'finishing') before revoking, so
    exactly one caller revokes and audits; the others see rowcount 0 and do nothing."""
    cid = connection_row["id"]
    if connection_row["sync_mode"] != "once":
        return False
    if not jobs.all_selected_done(conn, cid):
        return False
    claimed = conn.execute(
        "UPDATE connection SET state='finishing' WHERE id=? AND state='connected' AND sync_mode='once'",
        (cid,),
    ).rowcount
    if claimed != 1:
        return False
    try:
        await client.revoke(connection_row["profile_id"])
    except CompanionError as exc:
        # Release the claim so the user (or the next tick) can retry; record sanitized failure.
        conn.execute(
            "UPDATE connection SET state='connected', failure=? WHERE id=? AND state='finishing'",
            (redact(exc.user_message), cid),
        )
        return False
    except BaseException:
        conn.execute("UPDATE connection SET state='connected' WHERE id=? AND state='finishing'", (cid,))
        raise
    from .repo import set_connection_state

    set_connection_state(conn, cid, "disconnected")
    audit.record(conn, audit.ACCOUNT_DISCONNECTED, sub=sub, connection_id=cid,
                 detail="one-time import complete; auth revoked")
    return True


async def scheduler_tick(app_state) -> None:
    """One pass over all connected accounts due for a scheduled scan. Called by the loop
    and directly by tests. Uses a fresh DB connection."""
    from .db import connect

    settings = app_state.settings
    client: CompanionClient = app_state.companion
    conn = connect(settings.db_path)
    try:
        # Advance in-flight work for every connected account, independent of the scan
        # schedule. Downloads run in the companion and finish on their own; until something
        # polls, the connector's view stays frozen. Progress-page loads used to be the only
        # thing that polled, so closing the browser stranded jobs as 'importing' forever and
        # worse still, a 'once' connection would never finalize, leaving the Audible
        # authorization in place that one-time mode exists to remove.
        active = conn.execute("SELECT * FROM connection WHERE state='connected'").fetchall()
        for connection_row in active:
            sub = connection_row["authentik_sub"]
            cid = connection_row["id"]
            profile = connection_row["profile_id"]
            try:
                await jobs.poll_jobs(conn, client, profile, cid, sub)
                await jobs.dispatch_queued(conn, client, profile, cid)
                await finalize_once_mode(conn, client, connection_row, sub)
            except CompanionError as exc:
                conn.execute(
                    "UPDATE connection SET failure=? WHERE id=?", (redact(exc.user_message), cid)
                )

        due = conn.execute(
            "SELECT * FROM connection WHERE state='connected' AND sync_mode IN ('ask','auto') "
            "AND (last_scan_at IS NULL OR last_scan_at <= datetime('now', ?))",
            (f"-{settings.scan_interval_hours} hours",),
        ).fetchall()
        for connection_row in due:
            sub = connection_row["authentik_sub"]
            try:
                outcome = await run_scan(conn, client, connection_row, sub)
                await apply_mode_after_scan(
                    conn, client, connection_row, sub, outcome["newly_seen"],
                    is_baseline=outcome.get("is_baseline", False),
                )
            except CompanionError as exc:
                conn.execute(
                    "UPDATE connection SET failure=? WHERE id=?",
                    (redact(exc.user_message), connection_row["id"]),
                )
    finally:
        conn.close()


async def scheduler_loop(app_state, interval_seconds: int = 300) -> None:
    """Tick every 5 minutes. The expensive work (a library scan) is still rate-limited to
    `scan_interval_hours` per connection; the frequent part is just polling in-flight jobs so
    a user who closes the browser still sees their import finish and one-time auth revoked.
    """
    while True:
        try:
            await scheduler_tick(app_state)
        except Exception:  # never let the loop die
            pass
        await asyncio.sleep(interval_seconds)
