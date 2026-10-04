"""Job dedup/idempotency, retry, sync modes, one-time revocation, scheduler."""
import asyncio

from helpers import connect, csrf, hdr


def _select_and_start(client, app, sub, mode, asins=None):
    connect(client, app, sub)
    if asins is None:
        client.post("/contribute/audible/select",
                    data={"select_all": "1", "csrf_token": csrf(app, sub)},
                    headers=hdr(sub), follow_redirects=False)
    else:
        for a in asins:
            client.post("/contribute/audible/select",
                        data={"asin": a, "csrf_token": csrf(app, sub)},
                        headers=hdr(sub), follow_redirects=False)
    client.post("/contribute/audible/mode",
                data={"mode": mode, "csrf_token": csrf(app, sub)},
                headers=hdr(sub), follow_redirects=False)


def _books(app):
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    rows = {r["asin"]: r["status"] for r in conn.execute("SELECT asin, status FROM book")}
    conn.close()
    return rows


def test_job_dedup_is_refresh_safe(client, app):
    connect(client, app, "alice")
    from app.db import connect as dbc
    from app import jobs
    conn = dbc(app.state.settings.db_path)
    cid = conn.execute("SELECT id FROM connection WHERE authentik_sub='alice'").fetchone()["id"]
    j1, c1 = jobs.queue_book(conn, cid, "alice", "B000000AA1")
    j2, c2 = jobs.queue_book(conn, cid, "alice", "B000000AA1")  # simulate refresh
    n = conn.execute("SELECT COUNT(*) c FROM job WHERE connection_id=? AND asin='B000000AA1' "
                     "AND status IN ('queued','running')", (cid,)).fetchone()["c"]
    conn.close()
    assert c1 is True and c2 is False
    assert j1["id"] == j2["id"]
    assert n == 1  # exactly one active job despite two queue calls


def test_once_mode_revokes_after_success(client, app):
    _select_and_start(client, app, "alice", "once")
    # Progress page polls + dispatches + finalizes.
    client.get("/contribute/audible/progress", headers=hdr("alice"))
    # All succeeded (fake succeeds) => revoke called, connection disconnected.
    assert len(app.state.companion.revoked) == 1
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    state = conn.execute("SELECT state FROM connection WHERE authentik_sub='alice'").fetchone()["state"]
    conn.close()
    assert state == "disconnected"


def test_once_mode_retains_on_failure(client, app):
    app.state.companion.fail_backup_all = True
    _select_and_start(client, app, "alice", "once")
    client.get("/contribute/audible/progress", headers=hdr("alice"))
    assert app.state.companion.revoked == []  # not revoked while failures remain
    books = _books(app)
    assert "failed" in books.values()


def test_retry_failed(client, app):
    app.state.companion.fail_backup_asins = {"B000000AA1"}
    _select_and_start(client, app, "alice", "once", asins=["B000000AA1"])
    client.get("/contribute/audible/progress", headers=hdr("alice"))
    assert _books(app)["B000000AA1"] == "failed"
    # Fix the fault and retry.
    app.state.companion.fail_backup_asins = set()
    client.post("/contribute/audible/retry",
                data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    client.get("/contribute/audible/progress", headers=hdr("alice"))
    assert _books(app)["B000000AA1"] == "imported"


def test_ask_mode_surfaces_pending(client, app):
    connect(client, app, "alice")
    client.post("/contribute/audible/mode", data={"mode": "ask", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    # Mark connection connected + a new purchase appears, then run the scheduler.
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    row = conn.execute("SELECT id, profile_id FROM connection WHERE authentik_sub='alice'").fetchone()
    conn.execute("UPDATE connection SET last_scan_at=datetime('now','-2 days') WHERE id=?", (row["id"],))
    conn.close()
    app.state.companion.add_new_purchase(row["profile_id"], "B000000NEW", "Just Bought")
    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))
    assert _books(app).get("B000000NEW") == "pending"
    assert app.state.companion.revoked == []  # ask never auto-downloads


def test_auto_mode_queues_new_purchase_only(client, app):
    connect(client, app, "alice")
    client.post("/contribute/audible/mode", data={"mode": "auto", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    row = conn.execute("SELECT id, profile_id FROM connection WHERE authentik_sub='alice'").fetchone()
    conn.execute("UPDATE connection SET last_scan_at=datetime('now','-2 days') WHERE id=?", (row["id"],))
    conn.close()
    app.state.companion.add_new_purchase(row["profile_id"], "B000000NEW", "Just Bought")
    # Also add a Plus title that must NOT be queued.
    app.state.companion.profiles[row["profile_id"]]["library"].append(
        {"asin": "B000000PL9", "title": "Plus", "isPlus": True, "purchaseStatus": "plus"})
    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))
    books = _books(app)
    assert books.get("B000000NEW") in ("importing", "imported", "queued")
    assert books.get("B000000PL9") == "excluded"  # Plus never queued


def test_auto_mode_no_duplicate_on_repeat_scan(client, app):
    connect(client, app, "alice")
    client.post("/contribute/audible/mode", data={"mode": "auto", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    from app.db import connect as dbc
    from app.sync import scheduler_tick
    conn = dbc(app.state.settings.db_path)
    row = conn.execute("SELECT id, profile_id FROM connection WHERE authentik_sub='alice'").fetchone()
    conn.execute("UPDATE connection SET last_scan_at=datetime('now','-2 days') WHERE id=?", (row["id"],))
    conn.close()
    app.state.companion.add_new_purchase(row["profile_id"], "B000000NEW", "Just Bought")
    asyncio.run(scheduler_tick(app.state))
    # Second scan (reset due time) must not create a second job for the same ASIN.
    conn = dbc(app.state.settings.db_path)
    conn.execute("UPDATE connection SET last_scan_at=datetime('now','-2 days') WHERE id=?", (row["id"],))
    n_before = conn.execute("SELECT COUNT(*) c FROM job WHERE asin='B000000NEW'").fetchone()["c"]
    conn.close()
    asyncio.run(scheduler_tick(app.state))
    conn = dbc(app.state.settings.db_path)
    n_after = conn.execute("SELECT COUNT(*) c FROM job WHERE asin='B000000NEW'").fetchone()["c"]
    conn.close()
    assert n_after == n_before


def test_scheduler_advances_jobs_without_a_browser(client, app):
    """Downloads finish in the companion on their own. If only progress-page loads polled,
    a user who closed the tab would leave jobs stuck 'importing' forever."""
    import asyncio

    from app.sync import scheduler_tick

    _select_and_start(client, app, "alice", "auto", asins=["B000000AA1"])
    assert _books(app)["B000000AA1"] == "importing"

    asyncio.run(scheduler_tick(app.state))
    assert _books(app)["B000000AA1"] == "imported"


def test_scheduler_finalizes_once_mode_without_a_browser(client, app):
    """The one-time promise — auth is revoked after the import — must not depend on the
    user keeping a tab open until the last byte lands."""
    import asyncio

    from app.sync import scheduler_tick

    _select_and_start(client, app, "alice", "once", asins=["B000000AA1"])
    assert app.state.companion.revoked == []

    asyncio.run(scheduler_tick(app.state))
    assert len(app.state.companion.revoked) == 1
