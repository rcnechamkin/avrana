"""One-time mode, end to end (owner decision, 2026-10-15): loading a page never changes state;
finishing a one-time import (revoking the Audible authorization) happens only in the CSRF-protected
Refresh or the background scheduler; an empty choice can never finish an import."""
import asyncio

from helpers import connect, csrf, hdr, refresh

PROGRESS = "/contribute/audible/progress"


def _db(app):
    from app.db import connect as dbc
    return dbc(app.state.settings.db_path)


def _snapshot(app):
    db = _db(app)
    try:
        return ({t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY 1,2")]
                 for t in ("connection", "book", "job")},
                db.execute("SELECT COUNT(*) FROM audit").fetchone()[0])
    finally:
        db.close()


def _state(app, sub):
    db = _db(app)
    try:
        row = db.execute("SELECT state FROM connection WHERE authentik_sub=? ORDER BY created_at DESC LIMIT 1",
                         (sub,)).fetchone()
        return row["state"] if row else None
    finally:
        db.close()


def _choose(client, app, sub, asins=("B000000AA1",)):
    for a in asins:
        client.post("/contribute/audible/select", data={"asin": a, "csrf_token": csrf(app, sub)},
                    headers=hdr(sub), follow_redirects=False)
    return client.post("/contribute/audible/mode", data={"mode": "once", "csrf_token": csrf(app, sub)},
                       headers=hdr(sub), follow_redirects=False)


def test_loading_the_progress_page_never_finishes_a_one_time_import(client, app):
    connect(client, app, "alice")
    _choose(client, app, "alice")
    before = _snapshot(app)
    for _ in range(3):
        assert client.get(PROGRESS, headers=hdr("alice")).status_code == 200
    assert _snapshot(app) == before, "a GET changed stored state"
    assert app.state.companion.revoked == []
    assert _state(app, "alice") == "connected"


def test_refresh_finishes_it_once_with_a_token_and_says_so(client, app):
    connect(client, app, "alice")
    _choose(client, app, "alice")
    # without a token nothing happens
    r = client.post("/contribute/audible/progress/refresh", data={}, headers=hdr("alice"), follow_redirects=False)
    assert r.status_code in (400, 403)
    assert app.state.companion.revoked == []
    r = refresh(client, app, "alice")
    assert r.status_code == 200 and "disconnected and nothing was kept" in r.text
    assert len(app.state.companion.revoked) == 1 and _state(app, "alice") == "disconnected"
    # afterwards the page no longer exists for this connection, and a second Refresh does nothing more
    assert client.get(PROGRESS, headers=hdr("alice"), follow_redirects=False).status_code == 302
    assert refresh(client, app, "alice").status_code == 303
    assert len(app.state.companion.revoked) == 1


def test_an_empty_choice_is_refused_and_never_finishes_anything(client, app):
    connect(client, app, "alice")
    before = _snapshot(app)
    r = client.post("/contribute/audible/select", data={"csrf_token": csrf(app, "alice")},
                    headers=hdr("alice"), follow_redirects=False)
    assert r.status_code == 200 and "Choose at least one book" in r.text
    r = client.post("/contribute/audible/mode", data={"mode": "once", "csrf_token": csrf(app, "alice")},
                    headers=hdr("alice"), follow_redirects=False)
    assert r.status_code == 200 and "Choose at least one book" in r.text
    assert _snapshot(app) == before, "a refused empty choice changed stored state"
    refresh(client, app, "alice")
    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))
    assert app.state.companion.revoked == [] and _state(app, "alice") == "connected"


def test_books_already_in_avrana_alone_never_finish_a_one_time_import(client, app):
    """The bug the owner named: a scan marks books already in Avrana 'already'. With one-time mode
    set and nothing chosen, they used to count as done, and the next page load revoked."""
    connect(client, app, "alice")
    db = _db(app)
    cid = db.execute("SELECT id FROM connection WHERE authentik_sub='alice'").fetchone()["id"]
    db.execute("UPDATE book SET status='already' WHERE connection_id=? AND eligibility='purchased'", (cid,))
    db.execute("UPDATE connection SET sync_mode='once' WHERE id=?", (cid,))
    db.close()
    from app import jobs
    db = _db(app)
    assert jobs.all_selected_done(db, cid) is False
    db.close()
    client.get(PROGRESS, headers=hdr("alice"))
    refresh(client, app, "alice")
    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))
    assert app.state.companion.revoked == [] and _state(app, "alice") == "connected"


def test_a_chosen_book_found_already_in_avrana_still_finishes(client, app):
    """The other side: a book the member chose that turns out to be present is done, so the
    one-time promise (authorization removed afterwards) still holds."""
    connect(client, app, "alice")
    client.post("/contribute/audible/select", data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    app.state.companion.present_asins = {"B000000AA1"}
    client.post("/contribute/audible/mode", data={"mode": "once", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    assert refresh(client, app, "alice").status_code == 200
    assert len(app.state.companion.revoked) == 1


def test_refresh_only_touches_the_members_own_connection(client, app):
    connect(client, app, "alice")
    connect(client, app, "bob")
    _choose(client, app, "alice")
    _choose(client, app, "bob")
    refresh(client, app, "bob")
    assert _state(app, "bob") == "disconnected"
    assert _state(app, "alice") == "connected", "bob's Refresh finished alice's import"
    # alice's token does not work for bob
    r = client.post("/contribute/audible/progress/refresh", data={"csrf_token": csrf(app, "alice")},
                    headers=hdr("bob"), follow_redirects=False)
    assert r.status_code in (400, 403)


def test_the_scheduler_still_finishes_without_a_browser(client, app):
    connect(client, app, "alice")
    _choose(client, app, "alice")
    from app.sync import scheduler_tick
    asyncio.run(scheduler_tick(app.state))
    asyncio.run(scheduler_tick(app.state))
    assert len(app.state.companion.revoked) == 1 and _state(app, "alice") == "disconnected"
