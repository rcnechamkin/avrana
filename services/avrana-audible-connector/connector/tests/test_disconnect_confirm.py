"""Disconnect asks on its own page, without script (AVR-502, owner decision 2026-10-15).

The Disconnect controls on the mode and progress pages are links to `GET /contribute/audible/disconnect`,
a read-only confirmation page. Only its CSRF-protected POST (unchanged) revokes and forgets the account.
Fixtures only: a temporary SQLite file, the in-memory fake companion and header identities.
"""
import pathlib
import re

import pytest

from helpers import connect, csrf, hdr

CONFIRM = "/contribute/audible/disconnect"
TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "app" / "templates"


def _snapshot(app):
    from app.db import connect as dbc
    db = dbc(app.state.settings.db_path)
    try:
        tables = {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY 1")]
                  for t in ("connection", "book", "job", "auth_session", "audit")}
        return tables
    finally:
        db.close()


def _state(app, sub):
    from app.db import connect as dbc
    db = dbc(app.state.settings.db_path)
    try:
        row = db.execute("SELECT state FROM connection WHERE authentik_sub=?", (sub,)).fetchone()
        return row["state"] if row else None
    finally:
        db.close()


def test_get_renders_the_confirmation_and_changes_nothing(client, app, fake):
    connect(client, app, "alice")
    before = _snapshot(app)
    for _ in range(2):
        r = client.get(CONFIRM + "?from=progress", headers=hdr("alice"), follow_redirects=False)
        assert r.status_code == 200
        assert "Disconnect your Audible account?" in r.text
    assert _snapshot(app) == before, "loading the confirmation page changed stored state"
    assert fake.revoked == [], "loading the confirmation page revoked the authorization"
    assert _state(app, "alice") == "connected"
    # the page offers exactly one form: the CSRF-protected POST to the same path
    forms = re.findall(r'<form method="post" action="([^"]+)"', r.text)
    assert forms == [CONFIRM]
    token = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
    assert app.state.csrf.verify(token, "alice")


def test_the_page_says_what_is_and_is_not_removed(client, app):
    connect(client, app, "alice")
    text = client.get(CONFIRM, headers=hdr("alice")).text
    assert "Remove the Audible authorization" in text
    assert "Forget your Audible book list" in text
    assert "Remove books already imported. They stay in Avrana." in text
    assert "Change your Audible or Amazon account" in text


@pytest.mark.parametrize("src,target", [
    ("mode", "/contribute/audible/mode"), ("progress", "/contribute/audible/progress"),
    ("", "/contribute/audible/progress"), ("https://evil.example/", "/contribute/audible/progress"),
    ("//evil.example", "/contribute/audible/progress")])
def test_cancel_goes_back_to_the_page_that_offered_disconnect(src, target, client, app):
    connect(client, app, "alice")
    r = client.get(CONFIRM, params={"from": src} if src else None, headers=hdr("alice"))
    cancel = re.search(r'<a href="([^"]+)" class="ghost as-button">Cancel</a>', r.text)
    assert cancel and cancel.group(1) == target


def test_without_a_connection_the_page_redirects_like_the_post(client, app):
    r = client.get(CONFIRM, headers=hdr("nobody"), follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/contribute/audible")


def test_unauthenticated_and_wrong_group_get_the_usual_denial(client, app):
    connect(client, app, "alice")
    assert client.get(CONFIRM, headers={"accept": "application/json"}).status_code == 401
    assert client.get(CONFIRM, headers=hdr("alice", groups="some-other-group")).status_code == 403
    assert _state(app, "alice") == "connected"


def test_post_without_or_with_a_bad_token_is_refused_and_changes_nothing(client, app, fake):
    connect(client, app, "alice")
    before = _snapshot(app)
    assert client.post(CONFIRM, data={}, headers=hdr("alice"), follow_redirects=False).status_code == 403
    for bad in ("not-a-token", csrf(app, "mallory")):
        r = client.post(CONFIRM, data={"csrf_token": bad}, headers=hdr("alice"), follow_redirects=False)
        assert r.status_code == 403
    assert _snapshot(app) == before and fake.revoked == []


def test_post_with_a_valid_token_disconnects_as_before(client, app, fake):
    connect(client, app, "alice")
    r = client.post(CONFIRM, data={"csrf_token": csrf(app, "alice")}, headers=hdr("alice"),
                    follow_redirects=False)
    assert r.status_code == 200 and "<h1>Disconnected</h1>" in r.text
    assert len(fake.revoked) == 1 and _state(app, "alice") is None
    from app.db import connect as dbc
    db = dbc(app.state.settings.db_path)
    try:
        assert db.execute("SELECT COUNT(*) FROM book").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit WHERE event='account_disconnected'").fetchone()[0] == 1
    finally:
        db.close()


def test_a_member_can_only_confirm_their_own_disconnect(client, app, fake):
    connect(client, app, "alice")
    connect(client, app, "bob")
    alice_page = client.get(CONFIRM, headers=hdr("alice")).text
    alice_token = re.search(r'name="csrf_token" value="([^"]+)"', alice_page).group(1)
    # bob replaying alice's confirmation token is refused; alice stays connected
    r = client.post(CONFIRM, data={"csrf_token": alice_token}, headers=hdr("bob"), follow_redirects=False)
    assert r.status_code == 403
    assert _state(app, "alice") == "connected" and _state(app, "bob") == "connected"
    # bob confirming his own disconnect leaves alice untouched
    client.post(CONFIRM, data={"csrf_token": csrf(app, "bob")}, headers=hdr("bob"), follow_redirects=False)
    assert _state(app, "bob") is None and _state(app, "alice") == "connected"
    assert len(fake.revoked) == 1


def test_mode_and_progress_link_to_the_confirmation_instead_of_posting(client, app):
    connect(client, app, "alice")
    client.post("/contribute/audible/select", data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    mode = client.get("/contribute/audible/mode", headers=hdr("alice")).text
    assert 'href="/contribute/audible/disconnect?from=mode"' in mode
    client.post("/contribute/audible/mode", data={"mode": "ask", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    progress = client.get("/contribute/audible/progress", headers=hdr("alice")).text
    assert 'href="/contribute/audible/disconnect?from=progress"' in progress
    for page in (mode, progress):
        assert f'action="{CONFIRM}"' not in page


def test_no_template_carries_an_inline_event_handler_or_script():
    for p in TEMPLATES.glob("*.html"):
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=", text, re.I), f"{p.name}: inline event handler"
        assert "<script" not in text.lower(), f"{p.name}: script"
        assert "javascript:" not in text.lower(), f"{p.name}: javascript: URL"
