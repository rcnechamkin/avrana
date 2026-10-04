"""End-to-end flow, catalog isolation, eligibility, and selection."""
from helpers import connect, csrf, hdr


def test_connect_populates_library(client, app):
    connect(client, app, "alice")
    r = client.get("/contribute/audible/library", headers=hdr("alice"))
    assert r.status_code == 200
    assert "Owned One" in r.text and "Owned Two" in r.text


def test_purchased_vs_plus_classification(client, app):
    connect(client, app, "alice")
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    rows = {r["asin"]: r["eligibility"] for r in conn.execute("SELECT asin, eligibility FROM book")}
    conn.close()
    assert rows["B000000AA1"] == "purchased"
    assert rows["B000000AA2"] == "purchased"
    assert rows["B000000PL1"] == "plus"  # Audible Plus never purchased


def test_catalog_isolation_between_users(client, app):
    connect(client, app, "alice", email="alice@audible.example")
    connect(client, app, "bob", email="bob@audible.example")
    # Give bob a distinct extra book, then confirm alice never sees it.
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    bob_conn = conn.execute("SELECT id, profile_id FROM connection WHERE authentik_sub='bob'").fetchone()
    conn.execute("INSERT INTO book(connection_id, asin, title, eligibility, status) "
                 "VALUES (?,?,?,?,?)", (bob_conn["id"], "B000000BOB", "Bob Secret", "purchased", "available"))
    conn.close()
    r = client.get("/contribute/audible/library", headers=hdr("alice"))
    assert "Bob Secret" not in r.text
    assert "B000000BOB" not in r.text


def test_user_cannot_use_another_users_session(client, app):
    # alice starts an auth session; bob tries to complete it.
    r = client.post("/contribute/audible/start",
                    data={"email": "a@b.co", "marketplace": "us", "csrf_token": csrf(app, "alice")},
                    headers=hdr("alice"), follow_redirects=False)
    import re
    sid = re.search(r'name="session_id" value="([^"]+)"', r.text).group(1)
    r2 = client.post("/contribute/audible/complete",
                     data={"session_id": sid, "response_url": "https://amazon.example/x",
                           "csrf_token": csrf(app, "bob")},
                     headers=hdr("bob"), follow_redirects=False)
    assert r2.status_code == 404  # not bob's session


def test_select_individual_and_all_new(client, app):
    connect(client, app, "alice")
    # Select one specific book.
    client.post("/contribute/audible/select",
                data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    got = conn.execute("SELECT status FROM book WHERE asin='B000000AA1'").fetchone()["status"]
    assert got == "selected"
    # Plus title cannot be selected.
    client.post("/contribute/audible/select",
                data={"asin": "B000000PL1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    plus = conn.execute("SELECT status FROM book WHERE asin='B000000PL1'").fetchone()["status"]
    assert plus != "selected"
    # Select all new selects both purchased-available titles.
    client.post("/contribute/audible/select",
                data={"select_all": "1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    sel = conn.execute("SELECT COUNT(*) c FROM book WHERE status='selected'").fetchone()["c"]
    conn.close()
    assert sel == 2


def test_disconnect_and_reconnect(client, app):
    connect(client, app, "alice")
    client.post("/contribute/audible/disconnect",
                data={"csrf_token": csrf(app, "alice")}, headers=hdr("alice"), follow_redirects=False)
    assert "alice" in [p for p in app.state.companion.revoked] or app.state.companion.revoked
    # After disconnect, connect page is shown again and a fresh connect works.
    r = client.get("/contribute/audible", headers=hdr("alice"), follow_redirects=False)
    assert r.status_code == 200
    connect(client, app, "alice")
    r2 = client.get("/contribute/audible/library", headers=hdr("alice"))
    assert r2.status_code == 200
