"""Authentik identity/authorization enforcement and CSRF protection."""
from helpers import csrf, hdr


def test_unauthenticated_is_401_json(client):
    # No identity headers, JSON accept => 401 (not a redirect).
    r = client.get("/contribute/audible", headers={"accept": "application/json"}, follow_redirects=False)
    assert r.status_code == 401


def test_wrong_group_is_forbidden(client):
    r = client.get("/contribute/audible", headers=hdr("u1", groups="some-other-group"),
                   follow_redirects=False)
    assert r.status_code == 403


def test_member_allowed(client):
    r = client.get("/contribute/audible", headers=hdr("u1"), follow_redirects=False)
    assert r.status_code == 200
    assert "Connect your Audible account" in r.text


def test_healthz_is_public(client):
    assert client.get("/healthz").status_code == 200


def test_post_without_csrf_rejected(client, app):
    r = client.post(
        "/contribute/audible/start",
        data={"email": "a@b.co", "marketplace": "us"},  # no csrf_token
        headers=hdr("u1"), follow_redirects=False,
    )
    assert r.status_code == 403


def test_post_with_csrf_ok(client, app):
    r = client.post(
        "/contribute/audible/start",
        data={"email": "a@b.co", "marketplace": "us", "csrf_token": csrf(app, "u1")},
        headers=hdr("u1"), follow_redirects=False,
    )
    assert r.status_code == 200


def test_csrf_bound_to_subject(app):
    # A token issued for u1 must not validate for u2.
    token = app.state.csrf.issue("u1")
    assert app.state.csrf.verify(token, "u1")
    assert not app.state.csrf.verify(token, "u2")


def test_status_summary_is_public_and_nonsensitive(client, app):
    """The Homepage widget endpoint: unauthenticated, counts only, no titles/emails/ASINs."""
    from helpers import connect as do_connect
    do_connect(client, app, "alice")  # creates a connected profile + a library of books
    r = client.get("/status/summary")  # no auth headers on purpose
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"profiles", "pending", "downloading", "imported", "failed", "state"}
    assert body["profiles"] == 1
    assert all(isinstance(body[k], int) for k in ("profiles", "pending", "downloading", "imported", "failed"))
    # Must never leak identifying detail.
    blob = r.text.lower()
    assert "alice" not in blob and "@" not in blob and "b0000" not in blob


def test_status_summary_counts_books_still_to_download(client, app):
    from helpers import connect as do_connect, csrf, hdr
    do_connect(client, app, "alice")
    client.post("/contribute/audible/select",
                data={"asin": "B000000AA1", "csrf_token": csrf(app, "alice")},
                headers=hdr("alice"), follow_redirects=False)
    body = client.get("/status/summary").json()
    assert body["pending"] >= 1
    assert body["state"] in ("queued", "importing")
