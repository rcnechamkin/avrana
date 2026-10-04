"""A connection's first scan is a baseline: it records the existing catalogue but never
imports it. Auto/ask only act on purchases that appear in a LATER scan.

Regression: auto-mode's safety used to rely entirely on the connect-time scan having already
inserted every book, so a later scan would see nothing "new". That breaks if the first
*successful* scan lands while mode='auto' (the connect-time scan failed, or a reconnect) —
the whole back catalogue looks brand-new and gets queued. The explicit `baselined` flag fixes
it regardless of which scan is first.
"""
from __future__ import annotations

import asyncio

from helpers import connect, csrf, hdr


def _db(app):
    from app.db import connect as dbc
    return dbc(app.state.settings.db_path)


def _books(app):
    conn = _db(app)
    rows = {r["asin"]: r["status"] for r in conn.execute("SELECT asin, status FROM book")}
    conn.close()
    return rows


def _job_count(app):
    conn = _db(app)
    n = conn.execute("SELECT COUNT(*) c FROM job").fetchone()["c"]
    conn.close()
    return n


def _profile(app, sub):
    conn = _db(app)
    pid = conn.execute("SELECT profile_id FROM connection WHERE authentik_sub=?", (sub,)).fetchone()["profile_id"]
    conn.close()
    return pid


def _simulate_first_scan_never_ran(app, sub, mode):
    """Put the connection in the state where its baseline scan has NOT happened yet but the
    account is connected in `mode` — i.e. the connect-time scan failed."""
    conn = _db(app)
    cid = conn.execute("SELECT id FROM connection WHERE authentik_sub=?", (sub,)).fetchone()["id"]
    conn.execute("DELETE FROM book WHERE connection_id=?", (cid,))
    conn.execute("UPDATE connection SET baselined=0, last_scan_at=NULL, sync_mode=? WHERE id=?", (mode, cid))
    conn.close()


def test_baseline_scan_in_auto_mode_does_not_queue_the_existing_catalog(client, app):
    connect(client, app, "alice")            # connect-time baseline scan happens here
    _simulate_first_scan_never_ran(app, "alice", "auto")

    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))   # first *successful* scan, in auto mode

    books = _books(app)
    assert books, "the catalogue should be recorded"
    assert set(books.values()) <= {"available", "already", "excluded"}, \
        f"nothing should be queued/importing on a baseline scan, got {books}"
    assert _job_count(app) == 0, "a baseline scan must not create any download jobs"


def test_baseline_scan_in_ask_mode_does_not_flood_pending(client, app):
    connect(client, app, "alice")
    _simulate_first_scan_never_ran(app, "alice", "ask")

    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))

    assert "pending" not in _books(app).values(), \
        "a baseline scan must not turn the whole owned library into pending approvals"


def test_new_purchase_after_baseline_still_auto_queues(client, app):
    """The baseline must not disable auto mode — a purchase appearing in a later scan queues."""
    connect(client, app, "alice")
    client.post("/contribute/audible/mode",
                data={"mode": "auto", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    assert _job_count(app) == 0, "the existing catalogue must not have been queued at connect"

    # Make the connection due for a scheduled scan, then a new purchase appears.
    conn = _db(app)
    conn.execute("UPDATE connection SET last_scan_at=datetime('now','-2 days') WHERE authentik_sub='alice'")
    conn.close()
    app.state.companion.add_new_purchase(_profile(app, "alice"), "B0NEWBUY01", title="Brand New Buy")

    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))

    assert _books(app).get("B0NEWBUY01") in ("importing", "imported"), "the new purchase should auto-queue"
