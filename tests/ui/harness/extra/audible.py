"""Audible connector: the import progress page in its progress, failure and success states (AVR-359).

AVR-359's acceptance asks for browser proof of these states at 390 and 1280 with axe clean. They are
rendered offline from the connector's own FastAPI app (fastapi.testclient, a temporary SQLite file, the
connector tests' in-memory FakeCompanion and header identities), exactly as test_a11y.py builds them.
Nothing leaves the process. The stylesheet is inlined so the browser layer sees the real styles.

Needs fastapi, jinja2, httpx and pytest (the connector's test dependencies); without them the pages are
listed as unavailable, never as failures.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from harness.pages import REPO_ROOT, Identity, Page, Rendered, Unavailable

CONNECTOR = REPO_ROOT / "services/avrana-audible-connector/connector"
STYLE = CONNECTOR / "app/static/style.css"
PROGRESS = "/contribute/audible/progress"

CONTRIBUTOR = Identity(id="contributors", klass="member", groups=("library-contributors",),
                       username="member-a", name="Member A", email="a@example.test",
                       label="library contributor")

STATES = (
    ("progress-running", "imports still in progress"),
    ("progress-failed", "every chosen book failed; Retry offered"),
    ("progress-succeeded", "every chosen book imported"),
    ("progress-finished-once", "one-time import finished; authorization removed"),
)

_built: dict | None = None


def _build():
    """Render every state once (they share one app and database)."""
    global _built
    if _built is not None:
        return _built
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
        import jinja2  # noqa: F401
        import pytest  # noqa: F401  (the connector's conftest imports it)
    except ImportError as e:
        raise Unavailable(f"{e.name} is not installed; the Audible pages need the connector's test dependencies")
    for p in (str(CONNECTOR / "tests"), str(CONNECTOR)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from conftest import FakeCompanion
    from helpers import connect, csrf, hdr, refresh

    tmp = tempfile.mkdtemp(prefix="ui-audible-")
    settings = Settings(
        companion_base_url="http://companion", companion_token="t", companion_timeout_seconds=5,
        required_group="library-contributors", auth_mode="header",
        oidc_issuer="", oidc_client_id="", oidc_client_secret="", public_base_url="",
        hdr_sub="x-authentik-uid", hdr_username="x-authentik-username",
        hdr_email="x-authentik-email", hdr_groups="x-authentik-groups",
        dev_identity="", db_path=str(Path(tmp) / "t.db"),
        secret_key="ui-harness-fixture-key", cookie_secure=False, session_ttl_seconds=1800,
        rate_limit_window_seconds=300, rate_limit_max=10000, scan_interval_hours=24, brand_name="Avrana")
    fake = FakeCompanion()
    app = create_app(settings)
    app.state.companion = fake
    client = TestClient(app)

    def start(sub, mode="ask", fresh=True):
        if fresh:
            connect(client, app, sub)
        for a in ("B000000AA1", "B000000AA2"):
            client.post("/contribute/audible/select", data={"asin": a, "csrf_token": csrf(app, sub)},
                        headers=hdr(sub), follow_redirects=False)
        client.post("/contribute/audible/mode", data={"mode": mode, "csrf_token": csrf(app, sub)},
                    headers=hdr(sub), follow_redirects=False)

    def page(sub):
        return client.get(PROGRESS, headers=hdr(sub), follow_redirects=False)

    out = {}
    start("run")
    for j in fake.jobs.values():
        if "asin" in j:
            j["status"] = "running"
    refresh(client, app, "run")
    out["progress-running"] = page("run")

    fake.fail_backup_all = True
    start("bad")
    fake.fail_backup_all = False
    refresh(client, app, "bad")
    out["progress-failed"] = page("bad")

    start("ok")
    refresh(client, app, "ok")
    out["progress-succeeded"] = page("ok")

    from app.db import connect as dbc
    # Earlier members imported these books, so the scan marks them already in Avrana; make this
    # member's books choosable again (one-time mode refuses an empty choice).
    connect(client, app, "once")
    db = dbc(settings.db_path)
    db.execute("UPDATE book SET status='available' WHERE status='already' AND connection_id="
               "(SELECT id FROM connection WHERE authentik_sub='once')")
    db.close()
    # connecting again would rescan and mark the books already in Avrana again
    start("once", mode="once", fresh=False)
    out["progress-finished-once"] = refresh(client, app, "once")

    css = STYLE.read_text(encoding="utf-8")
    _built = {}
    for name, r in out.items():
        body = re.sub(r'<link rel="stylesheet" href="/static/style\.css[^"]*">',
                      lambda _m: f"<style>{css}</style>", r.text, count=1)
        _built[name] = Rendered(r.status_code, body, css=[css],
                                notes=["audible connector app via TestClient; fake companion; stylesheet inlined"])
    return _built


def _render(name):
    return lambda: _build()[name]


def register(registry):
    for name, note in STATES:
        registry.add(Page(service="audible", page=name, identity=CONTRIBUTOR, visibility="authorized",
                          render=_render(name), tags=("audible", "progress"), note=note))
