"""Recovery when the Audible handshake fails at the paste step.

Regression for a live-observed dead end: a completion failure deleted the connector's
one-time session and then re-rendered the paste page still bound to it, so the user's natural
retry hit "Session not found" — the login handshake is single-shot, so that page could never
succeed again. The honest recovery is to send the user back to a clean start.
"""
from __future__ import annotations

from helpers import csrf, hdr

SESSION_RE = __import__("helpers").SESSION_RE


def _start(client, app, sub="alice"):
    r = client.post(
        "/contribute/audible/start",
        data={"email": f"{sub}@audible.example", "marketplace": "us", "csrf_token": csrf(app, sub)},
        headers=hdr(sub), follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    return SESSION_RE.search(r.text).group(1)


def _complete(client, app, session_id, sub="alice", url="https://amazon.example/maplanding?code=abc"):
    return client.post(
        "/contribute/audible/complete",
        data={"session_id": session_id, "response_url": url, "csrf_token": csrf(app, sub)},
        headers=hdr(sub), follow_redirects=False,
    )


def test_failed_complete_sends_user_to_a_clean_restart_not_a_dead_session(client, app):
    app.state.companion.fail_complete = True
    sid = _start(client, app)
    r = _complete(client, app, sid)

    # The failure page must be the connect page (which can start a fresh handshake), not the
    # paste page bound to the now-consumed session.
    assert r.status_code == 200, r.text
    assert 'action="/contribute/audible/start"' in r.text
    assert 'name="session_id"' not in r.text
    assert "start again" in r.text.lower()


def test_retrying_the_same_paste_page_no_longer_yields_session_not_found(client, app):
    """Reproduces the exact user symptom: the second submit of a consumed session used to
    404 'Session not found'. Now the user is on the connect page and can simply start over."""
    app.state.companion.fail_complete = True
    sid = _start(client, app)
    _complete(client, app, sid)  # first attempt fails

    # Whatever the user does, the dead session is gone; resubmitting it is a clean 404, and
    # the recovery path (a fresh start) works end to end.
    stale = _complete(client, app, sid)
    assert stale.status_code == 404  # session truly consumed — no phantom reuse

    app.state.companion.fail_complete = False
    sid2 = _start(client, app)  # fresh start = fresh session + fresh login process
    ok = _complete(client, app, sid2)
    assert ok.status_code in (302, 303), ok.text


def test_a_transient_failure_does_not_wedge_the_connection(client, app):
    """After a failed attempt the connection must be re-startable, not stuck 'connected'."""
    app.state.companion.fail_complete = True
    _complete(client, app, _start(client, app))

    app.state.companion.fail_complete = False
    ok = _complete(client, app, _start(client, app))
    assert ok.status_code in (302, 303)

    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    state = conn.execute("SELECT state FROM connection WHERE authentik_sub='alice'").fetchone()["state"]
    conn.close()
    assert state == "connected"
