"""Reconnecting an Audible account after a `once`-mode sync auto-revoked it must work.

Regression (500 on the connect form, reported from contribute.avrana.net):
the two disconnect paths disagree. A manual disconnect deletes the connection row
(routes/flow.py -> delete_connection_cascade), but a `once`-mode sync auto-revokes by
setting state='disconnected' and KEEPING the row (sync.py) so import history survives.

get_connection_for_sub() filters `state != 'disconnected'`, so on a reconnect the retained
row is invisible and start_connect falls through to create_connection() -- whose INSERT then
collided with that row on UNIQUE(authentik_sub, audible_email) and raised
sqlite3.IntegrityError. Net effect: completing a `once` sync permanently locked you out of
reconnecting that account.
"""
from __future__ import annotations

from helpers import connect, csrf, hdr


def _db(app):
    from app.db import connect as dbc
    return dbc(app.state.settings.db_path)


def _rows(app, sub, email):
    conn = _db(app)
    rows = [dict(r) for r in conn.execute(
        "SELECT id, profile_id, state, baselined FROM connection "
        "WHERE authentik_sub=? AND audible_email=?", (sub, email))]
    conn.close()
    return rows


def test_reconnect_after_once_mode_revoke(client, app):
    sub, email = "sub-once", "reconnect@audible.example"
    connect(client, app, sub, email=email)

    before = _rows(app, sub, email)
    assert len(before) == 1
    old_profile = before[0]["profile_id"]

    # Exactly what sync.py does when a `once` sync finishes: revoke, keep the row.
    conn = _db(app)
    conn.execute("UPDATE connection SET state='disconnected', baselined=1 WHERE id=?",
                 (before[0]["id"],))
    conn.close()

    # The reconnect that used to 500.
    r = client.post(
        "/contribute/audible/start",
        data={"email": email, "marketplace": "us", "csrf_token": csrf(app, sub)},
        headers=hdr(sub), follow_redirects=False,
    )
    assert r.status_code == 200, r.text

    after = _rows(app, sub, email)
    assert len(after) == 1, "reconnect must not leave a duplicate row"
    assert after[0]["state"] != "disconnected"
    assert after[0]["profile_id"] != old_profile, "must get a fresh Libation profile"
    assert after[0]["baselined"] == 0, "first scan must be a baseline again, so Auto cannot dump the back catalogue"


def test_reconnect_does_not_disturb_another_subject(client, app):
    """The cleanup is scoped to (sub, email) -- a different user with the same Audible
    address keeps their connection."""
    email = "shared@audible.example"
    connect(client, app, "sub-a", email=email)
    connect(client, app, "sub-b", email=email)

    conn = _db(app)
    conn.execute("UPDATE connection SET state='disconnected' WHERE authentik_sub='sub-a'")
    conn.close()

    r = client.post(
        "/contribute/audible/start",
        data={"email": email, "marketplace": "us", "csrf_token": csrf(app, "sub-a")},
        headers=hdr("sub-a"), follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    assert len(_rows(app, "sub-a", email)) == 1
    b = _rows(app, "sub-b", email)
    assert len(b) == 1 and b[0]["state"] != "disconnected", "sub-b must be untouched"
