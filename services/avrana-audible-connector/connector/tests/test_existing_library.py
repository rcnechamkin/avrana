"""Books the shared Avrana library already holds must never be re-downloaded over.

The connector's own DB only knows imports the connector performed. The library it writes
into predates the connector (193 `[ASIN]`-tagged folders written by the admin Libation
instance as of 2026-08-14), and every connected account gets a *fresh* Libation profile DB
that has no record of them — so `liberate` would happily write to the same
`<Author>/<Title [ASIN]>` path and clobber existing media.

The companion is the only tier that can see the library filesystem, so it is the authority:
it reports present ASINs (`/v1/present`) and refuses a backup for one ("skipped"). These
tests cover the connector's side of that contract.
"""
from __future__ import annotations

from helpers import connect, csrf, hdr


def _books(app):
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    rows = {r["asin"]: r["status"] for r in conn.execute("SELECT asin, status FROM book")}
    conn.close()
    return rows


def _jobs(app):
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    rows = [dict(r) for r in conn.execute("SELECT asin, status FROM job")]
    conn.close()
    return rows


def test_book_already_in_library_is_flagged_not_offered(client, app):
    app.state.companion.present_asins = {"B000000AA1"}
    connect(client, app, "alice")
    assert _books(app)["B000000AA1"] == "already"


def test_selecting_an_existing_book_cannot_queue_it(client, app):
    """`select` only promotes books that are still 'available'."""
    app.state.companion.present_asins = {"B000000AA1"}
    connect(client, app, "alice")
    client.post("/contribute/audible/select",
                data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    assert _books(app)["B000000AA1"] == "already"
    assert not [j for j in _jobs(app) if j["asin"] == "B000000AA1"]


def test_select_all_skips_books_already_in_the_library(client, app):
    app.state.companion.present_asins = {"B000000AA1"}
    connect(client, app, "alice")
    client.post("/contribute/audible/select",
                data={"select_all": "1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    books = _books(app)
    assert books["B000000AA1"] == "already"
    assert books["B000000AA2"] == "selected"


def test_companion_skip_resolves_the_job_instead_of_hanging(client, app):
    """Defence in depth: if a book becomes present between selection and download, the
    companion skips it. That must settle the job, not leave it 'running' forever."""
    connect(client, app, "alice")
    client.post("/contribute/audible/select",
                data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    # Book lands in the library after selection but before dispatch.
    app.state.companion.present_asins = {"B000000AA1"}
    client.post("/contribute/audible/mode",
                data={"mode": "once", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    client.get("/contribute/audible/progress", headers=hdr("alice"))

    assert _books(app)["B000000AA1"] == "already"
    job = [j for j in _jobs(app) if j["asin"] == "B000000AA1"][0]
    assert job["status"] == "succeeded", "a skip is not a failure the user should retry"


def test_once_mode_still_revokes_when_every_pick_was_already_present(client, app):
    """Otherwise a once-mode run that downloaded nothing would leave the stored Audible
    authorization in place forever — the opposite of what one-time mode promises."""
    connect(client, app, "alice")
    client.post("/contribute/audible/select",
                data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    app.state.companion.present_asins = {"B000000AA1"}
    client.post("/contribute/audible/mode",
                data={"mode": "once", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    client.get("/contribute/audible/progress", headers=hdr("alice"))

    assert len(app.state.companion.revoked) == 1


def test_present_lookup_failure_does_not_break_a_scan(client, app):
    """The presence check is an optimisation for the picker; the companion refuses an
    overwriting download regardless. A companion hiccup must not abort onboarding."""
    async def boom():
        raise RuntimeError("companion down")

    connect(client, app, "alice")  # succeeds normally first
    app.state.companion.present = boom
    r = client.get("/contribute/audible", headers=hdr("alice"))
    assert r.status_code == 200


def test_import_that_produced_no_file_is_reset_to_retryable(client, app):
    """Observed live: LibationCli exited 0 having written nothing. 'imported' is terminal,
    so without reconciliation the book would be a permanent phantom no rescan revisits."""
    from app import catalog
    from app.db import connect as dbc

    connect(client, app, "alice")
    conn = dbc(app.state.settings.db_path)
    cid = conn.execute("SELECT id FROM connection WHERE authentik_sub='alice'").fetchone()["id"]
    conn.execute("UPDATE book SET status='imported' WHERE asin='B000000AA1'")
    conn.commit()

    snapshot = {"items": [{"asin": "B000000AA1", "title": "Owned One", "isPurchased": True,
                           "purchaseStatus": "purchased"}]}
    catalog.normalize_and_upsert(conn, cid, snapshot, set(), on_disk=set())
    conn.commit()
    status = conn.execute("SELECT status FROM book WHERE asin='B000000AA1'").fetchone()["status"]
    conn.close()
    assert status == "available", "a phantom import must become retryable"


def test_unknown_disk_state_never_resets_imported_books(client, app):
    """The dangerous inverse: if the companion cannot answer, `present()` returns None, and
    an unknown filesystem must NOT be read as an empty one — that would reset every imported
    book and re-download the whole library."""
    from app import catalog
    from app.db import connect as dbc

    connect(client, app, "alice")
    conn = dbc(app.state.settings.db_path)
    cid = conn.execute("SELECT id FROM connection WHERE authentik_sub='alice'").fetchone()["id"]
    conn.execute("UPDATE book SET status='imported' WHERE asin='B000000AA1'")
    conn.commit()

    snapshot = {"items": [{"asin": "B000000AA1", "title": "Owned One", "isPurchased": True,
                           "purchaseStatus": "purchased"}]}
    catalog.normalize_and_upsert(conn, cid, snapshot, set(), on_disk=None)
    conn.commit()
    status = conn.execute("SELECT status FROM book WHERE asin='B000000AA1'").fetchone()["status"]
    conn.close()
    assert status == "imported", "unknown disk state must leave imported books alone"


def test_client_returns_none_when_companion_cannot_answer():
    """Pins the None-vs-empty-set contract at the client boundary."""
    import asyncio

    from app.companion_client import CompanionClient

    client_ = CompanionClient("http://127.0.0.1:1", token="t", timeout=0.5)
    assert asyncio.run(client_.present()) is None
