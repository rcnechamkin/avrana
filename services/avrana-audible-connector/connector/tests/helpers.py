"""Shared test helpers."""
from __future__ import annotations

import re

SESSION_RE = re.compile(r'name="session_id" value="([^"]+)"')


def hdr(sub: str, groups: str = "library-contributors") -> dict:
    return {
        "x-authentik-uid": sub, "x-authentik-username": sub,
        "x-authentik-email": f"{sub}@example.invalid", "x-authentik-groups": groups,
        "accept": "text/html",
    }


def csrf(app, sub: str) -> str:
    return app.state.csrf.issue(sub)


def connect(client, app, sub, email=None, marketplace="us", response_url="https://amazon.example/maplanding?code=abc"):
    """Drive the full connect handshake for `sub`; leaves them connected with a library."""
    email = email or f"{sub}@audible.example"
    r = client.post(
        "/contribute/audible/start",
        data={"email": email, "marketplace": marketplace, "csrf_token": csrf(app, sub)},
        headers=hdr(sub), follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    m = SESSION_RE.search(r.text)
    assert m, "no session id in paste page"
    session_id = m.group(1)
    r2 = client.post(
        "/contribute/audible/complete",
        data={"session_id": session_id, "response_url": response_url, "csrf_token": csrf(app, sub)},
        headers=hdr(sub), follow_redirects=False,
    )
    assert r2.status_code in (302, 303), r2.text
    return session_id
