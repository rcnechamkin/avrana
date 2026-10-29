"""Shared helpers for the web tests. Everything is synthetic; nothing leaves loopback.

Standard library only at import time. FastAPI-dependent helpers import lazily so Tier A modules
can import this file on a machine without the framework.
"""
from __future__ import annotations

import importlib.util
import io
import re
import socket
import threading
import time
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from . import FRAMEWORK_MISSING, SKIP_REASON

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parents[1]
PORTAL_PATH = REPO / "services" / "avrana-portal" / "portal.py"
IDENTITIES_PATH = REPO / "tests" / "fixtures" / "identities.py"


def require_framework():
    if FRAMEWORK_MISSING:
        raise unittest.SkipTest(SKIP_REASON)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


portal = _load("avrana_portal_under_test", PORTAL_PATH)
fixtures = _load("avrana_identity_fixtures", IDENTITIES_PATH)
IDENTITIES = fixtures.IDENTITIES

GROUPS = "X-authentik-groups"
USER = "X-authentik-username"


# ---- the stdlib portal, in memory (same idea as tests/test_portal_authz.py) ------------------
class _FakeSocket:
    def __init__(self, wire):
        self._in, self.sent = io.BytesIO(wire), io.BytesIO()

    def makefile(self, mode, *_a, **_k):
        return self._in if "r" in mode else self.sent

    def sendall(self, data):
        self.sent.write(data)

    def settimeout(self, _t):
        pass

    def close(self):
        pass


@dataclass
class Resp:
    status: int
    headers: list
    body: bytes

    def all(self, name):
        return [v for k, v in self.headers if k.lower() == name.lower()]

    def header(self, name):
        vals = self.all(name)
        return vals[0] if vals else None

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def location(self):
        return self.header("Location")


def parse_http(data: bytes) -> Resp:
    head, _sep, body = data.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    if not lines[0].startswith(b"HTTP/"):
        return Resp(0, [], data)
    status = int(lines[0].split()[1])
    headers = []
    for ln in lines[1:]:
        k, _s, v = ln.partition(b":")
        headers.append((k.decode("latin-1").strip(), v.decode("latin-1").strip()))
    return Resp(status, headers, body)


def wire(target, headers=(), method="GET", host="portal.test"):
    lines = [f"{method} {target} HTTP/1.1".encode("latin-1"), b"Host: " + host.encode("latin-1")]
    for k, v in headers:
        lines.append((k if isinstance(k, bytes) else k.encode("latin-1")) + b": "
                     + (v if isinstance(v, bytes) else v.encode("latin-1")))
    lines.append(b"Connection: close")
    return b"\r\n".join(lines) + b"\r\n\r\n"


def portal_raw(wire_bytes) -> Resp:
    sock = _FakeSocket(wire_bytes)
    portal.Handler(sock, ("127.0.0.1", 0), None)
    return parse_http(sock.sent.getvalue())


def portal_request(target, headers=(), method="GET") -> Resp:
    return portal_raw(wire(target, headers, method))


def ident_headers(name, username=None, extras=True):
    """Headers for a fixture identity: the groups header exactly as the fixtures say (absent for
    None, empty for []), plus a synthetic username, name and e-mail when `username` is given."""
    groups = IDENTITIES[name]
    out = []
    if username:
        out.append((USER, username))
        if extras:
            out += [("X-authentik-name", "Member " + username[-1].upper()),
                    ("X-authentik-email", username + "@example.test")]
    if groups is not None:
        out.append((GROUPS, "|".join(groups)))
    return out


def valid_principal_identity(name) -> bool:
    groups = IDENTITIES[name]
    return bool(groups)         # absent or empty groups header: no principal


_TAG_GAP = re.compile(r">\s+<")
_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Whitespace-only normalisation, plus the two entity SPELLINGS that markupsafe and
    html.escape differ on (equivalent HTML): &#39; = &#x27; and &#34; = &quot;."""
    text = text.replace("&#39;", "&#x27;").replace("&#34;", "&quot;")
    text = _WS.sub(" ", text)
    text = _TAG_GAP.sub("><", text)
    return text.strip()


# ---- app helpers ------------------------------------------------------------------------------
def make_settings(**overrides):
    from avrana_home.app.settings import Settings
    return replace(Settings(), **overrides)


class PeerOverride:
    """Test-only ASGI wrapper: the test client cannot choose the peer address, so set it here."""

    def __init__(self, app, peer):
        self.app, self.peer = app, peer

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=self.peer)
        await self.app(scope, receive, send)


def make_client(settings=None, adapters=None, peer=("203.0.113.7", 50000), wrap=None, quick_connect=None,
                account_reader=None, member_store=None):
    from fastapi.testclient import TestClient
    from avrana_home.app.main import create_app
    app = create_app(settings or make_settings(), adapters=adapters, quick_connect=quick_connect,
                     account_reader=account_reader, member_store=member_store)
    outer = PeerOverride(wrap(app) if wrap else app, peer)
    client = TestClient(outer, base_url="http://portal.test", follow_redirects=False,
                        raise_server_exceptions=False)
    client.fastapi_app = app
    return client


# ---- real uvicorn on an ephemeral loopback port -------------------------------------------------
class RealServer:
    """Context manager: run an ASGI app under uvicorn (h11) on 127.0.0.1, port chosen by the OS.
    Access log and proxy-header rewriting off, exactly like serve.py."""

    def __init__(self, app, access_log=False):
        import uvicorn
        config = uvicorn.Config(app, host="127.0.0.1", port=0, http="h11", log_config=None,
                                access_log=access_log, proxy_headers=False, lifespan="off",
                                server_header=False)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = None

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    def exchange(self, wire_bytes: bytes, timeout=10) -> Resp:
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as s:
            try:
                s.sendall(wire_bytes)
            except OSError:
                pass
            chunks = []
            while True:
                try:
                    data = s.recv(65536)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
        raw = b"".join(chunks)
        if not raw:
            return Resp(-1, [], b"")
        return parse_http(raw)

    def get(self, target, headers=(), method="GET") -> Resp:
        return self.exchange(wire(target, headers, method, host="127.0.0.1"))


# ---- adapters for tests ------------------------------------------------------------------------
from avrana_home.contract import (Kind, MappingFailed, MediaAdapter, MediaItem, SectionResult,  # noqa: E402
                                  Service, UpstreamUser, build_handoff_url)


class StubAdapter(MediaAdapter):
    """A Jellyfin-shaped adapter over in-memory data: username -> [(hex id, title, progress)].
    Counts every call that would have reached an upstream (`calls`)."""
    service = Service.JELLYFIN

    def __init__(self, data, **kw):
        super().__init__(**kw)
        self.data = data
        self.calls = 0

    def _resolve_user(self, principal):
        self.calls += 1
        if principal.username not in self.data:
            raise MappingFailed("unmapped")
        return UpstreamUser(self.service, principal.username)

    def _items(self, user, section):
        self.calls += 1
        out = []
        for item_id, title, fraction in self.data[user.upstream_id]:
            out.append(MediaItem(id=f"jellyfin:{item_id}", service=self.service, kind=Kind.MOVIE,
                                 title=title, handoff_url=build_handoff_url(self.service, item_id),
                                 progress_fraction=fraction if section == "continue" else None,
                                 position_seconds=int(fraction * 7200) if fraction and section == "continue" else None,
                                 duration_seconds=7200 if fraction and section == "continue" else None))
        return SectionResult.of(self.service, section, tuple(out))

    def _continue_items(self, user, limit):
        return self._items(user, "continue")

    def _recent_items(self, user, limit):
        return self._items(user, "recent")
