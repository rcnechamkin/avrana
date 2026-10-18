"""DEVELOPMENT identity shim. The most dangerous code in this directory: read this first.

Locally there is no Authentik outpost, so nothing sets `X-authentik-*`. This ASGI middleware
stands in for it by injecting those headers for a chosen SYNTHETIC member. In a real deployment
it would be an identity-forging hole, so it is built to be impossible to enable by accident:

  1. It lives here, outside the `avrana_home` package that a deployment would ship, and
     `create_app` neither imports nor knows about it. `Settings` has no switch for it.
  2. It needs an explicit opt-in (`--dev-identity` or HOME_DEV_IDENTITY=on on run_dev.py) AND
     `check_startup` must pass: the bind address is a loopback literal (127.0.0.1 or ::1), the
     upstream mode is mock, the upstream URL is loopback and the upstream key is the fixed fake.
     Any failure raises `DevIdentityRefused` and nothing starts.
  3. The middleware refuses to be constructed without the sealed token `check_startup` returns.
  4. Headers are stripped, then set, in ONE place (`_rewrite_headers`): every client-supplied
     header that looks like an outpost identity header (any case, `_` or `-`, any `x-authentik*`
     name, `x-forwarded-user`, `remote-user`, `x-dev-identity`) is removed before the chosen
     synthetic identity is added. A client therefore cannot reach the application with an
     identity of its own choosing, even in dev mode; it can only pick among the fixed synthetic
     members below.
  5. Every HTML page rendered under it carries a visible "DEVELOPMENT IDENTITY" banner.
"""
from __future__ import annotations

import html
from typing import Mapping, Optional

from avrana_home.app.middleware import with_hygiene
from avrana_home.app.settings import MOCK_API_KEY, is_loopback_host, url_host

COOKIE = "avrana_dev_identity"
SELECT_HEADER = "x-dev-identity"
LOOPBACK_LITERALS = ("127.0.0.1", "::1")

# Invented members. Each exists in the mock Jellyfin fixtures (or deliberately does not).
DEV_IDENTITIES: Mapping[str, dict] = {
    "member-a": {"name": "Member A", "email": "member-a@example.test",
                 "groups": "avrana-users|avrana-videos|avrana-audiobooks",
                 "note": "Movies and TV plus Audiobooks; items in progress in both"},
    "member-b": {"name": "Member B", "email": "member-b@example.test",
                 "groups": "avrana-users|avrana-videos|avrana-audiobooks|avrana-books|avrana-comics",
                 "note": "Movies and TV (different items), books, comics"},
    "member-c": {"name": "Member C", "email": "member-c@example.test",
                 "groups": "avrana-users|avrana-videos",
                 "note": "Movies and TV, but the Jellyfin account is disabled (not set up yet)"},
    "member-d": {"name": "Member D", "email": "member-d@example.test",
                 "groups": "avrana-users|avrana-videos",
                 "note": "Movies and TV, but no Jellyfin account of that name (not set up yet)"},
    "member-nolib": {"name": "Member NoLib", "email": "member-nolib@example.test",
                     "groups": "avrana-users|avrana-comics",
                     "note": "No Movies and TV permission: that section is absent"},
    # Komga links a member only when the Authentik username equals the Komga login exactly
    # (ADAPTER-CONTRACT 12.2, open owner decision), so these usernames are the fixtures' logins.
    "member-a@synthetic.invalid": {"name": "Comics A", "email": "comics-a@example.test",
                                   "groups": "avrana-users|avrana-comics",
                                   "note": "Comics: sees the unrestricted recent books"},
    "member-b@synthetic.invalid": {"name": "Comics B", "email": "comics-b@example.test",
                                   "groups": "avrana-users|avrana-comics",
                                   "note": "Comics, age restricted (12 and under, no 'adult' label)"},
    "synthetic-admin": {"name": "Synthetic Admin", "email": "admin@example.test",
                        "groups": "authentik Admins",
                        "note": "Operations tile only; no library permission"},
}


class DevIdentityRefused(RuntimeError):
    """The development identity shim will not start in this configuration."""


class _Checked:
    __slots__ = ()


_SEAL = _Checked()


def check_startup(*, enabled: bool, host: str, settings) -> _Checked:
    """Return the sealed token the middleware needs, or raise DevIdentityRefused."""
    if enabled is not True:
        raise DevIdentityRefused("the development identity is not enabled (pass --dev-identity)")
    if host not in LOOPBACK_LITERALS:
        raise DevIdentityRefused("the development identity needs a loopback bind (127.0.0.1 or ::1)")
    if getattr(settings, "uses_real_upstream", True):
        raise DevIdentityRefused("the development identity refuses a real upstream configuration")
    if getattr(settings, "identity_mode", None) != "headers":
        # The shim forges plain headers; a JWT mode ignores them. It never mints tokens (AVR-498).
        raise DevIdentityRefused("the development identity is headers-only: HOME_IDENTITY_MODE must be headers")
    if not is_loopback_host(url_host(settings.jellyfin_base_url) or ""):
        raise DevIdentityRefused("the development identity needs a loopback mock upstream URL")
    if settings.audiobookshelf_base_url and not is_loopback_host(
            url_host(settings.audiobookshelf_base_url) or ""):
        raise DevIdentityRefused("the development identity needs a loopback mock upstream URL")
    if settings.komga_base_url and not is_loopback_host(url_host(settings.komga_base_url) or ""):
        raise DevIdentityRefused("the development identity needs a loopback mock upstream URL")
    if settings.calibre_web_base_url and not is_loopback_host(url_host(settings.calibre_web_base_url) or ""):
        raise DevIdentityRefused("the development identity needs a loopback mock upstream URL")
    if settings.calibre_web_credential not in ("", "viewer:" + MOCK_API_KEY):
        raise DevIdentityRefused("the development identity refuses a non-mock upstream key")
    if settings.komga_token not in ("", MOCK_API_KEY):
        raise DevIdentityRefused("the development identity refuses a non-mock upstream key")
    if settings.audiobookshelf_token not in ("", MOCK_API_KEY):
        raise DevIdentityRefused("the development identity refuses a non-mock upstream key")
    if settings.jellyfin_api_key != MOCK_API_KEY:
        raise DevIdentityRefused("the development identity refuses a non-mock upstream key")
    return _SEAL


def _norm(name: bytes) -> str:
    return name.decode("latin-1").lower().replace("_", "-")


def _forbidden_inbound(name: str) -> bool:
    return (name.startswith("x-authentik") or name.startswith("x-forwarded-user")
            or name in ("remote-user", "x-remote-user", SELECT_HEADER))


def _selected(headers) -> Optional[str]:
    for raw_name, raw_value in headers:
        if _norm(raw_name) == SELECT_HEADER:
            pick = raw_value.decode("latin-1").strip()
            return pick if pick in DEV_IDENTITIES else None
    for raw_name, raw_value in headers:
        if _norm(raw_name) == "cookie":
            for part in raw_value.decode("latin-1").split(";"):
                key, _, value = part.strip().partition("=")
                if key == COOKIE and value in DEV_IDENTITIES:
                    return value
    return None


def _rewrite_headers(headers, pick: Optional[str]) -> list:
    """The ONE place identity headers are stripped and set."""
    kept = [(k, v) for k, v in headers if not _forbidden_inbound(_norm(k))]
    if pick is not None:
        who = DEV_IDENTITIES[pick]
        kept += [(b"x-authentik-username", pick.encode()),
                 (b"x-authentik-groups", who["groups"].encode()),
                 (b"x-authentik-email", who["email"].encode()),
                 (b"x-authentik-name", who["name"].encode())]
    return kept


def banner(pick: Optional[str]) -> bytes:
    who = html.escape(pick) if pick else "none (anonymous)"
    return (f'<div role="note" style="background:#ffd600;color:#000;padding:8px 12px;'
            f'font:14px/1.4 sans-serif;text-align:center">DEVELOPMENT IDENTITY: {who}. '
            f'Synthetic members only, not a deployment. '
            f'<a href="/_dev/identity" style="color:#000">Switch</a></div>').encode("utf-8")


def _page(pick: Optional[str]) -> bytes:
    rows = "\n".join(
        f'<li><a href="/_dev/identity/{html.escape(n)}">{html.escape(n)}</a>: {html.escape(d["note"])}</li>'
        for n, d in DEV_IDENTITIES.items())
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Development identity</title>'
            f'</head><body><h1>Development identity</h1>\n<p>Pick a synthetic member.</p>\n<ul>\n{rows}\n'
            f'<li><a href="/_dev/identity/none">none</a>: no identity headers (anonymous)</li></ul>\n'
            f'<p><a href="/">Home</a></p></body></html>').encode("utf-8")


class DevIdentityMiddleware:
    def __init__(self, app, *, checked):
        if checked is not _SEAL:
            raise DevIdentityRefused("construct only after check_startup")
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        pick = _selected(scope.get("headers", ()))
        path = scope.get("raw_path", b"").decode("latin-1").split("?", 1)[0]
        if path == "/_dev/identity" or path.startswith("/_dev/identity/"):
            return await self._switcher(scope, send, path, pick)
        scope = dict(scope, headers=_rewrite_headers(scope.get("headers", ()), pick))
        await self.app(scope, receive, self._with_banner(send, pick, scope.get("method") == "HEAD"))

    def _with_banner(self, send, pick, head):
        if head:                         # no body to carry a banner; headers pass through untouched
            return send
        held = {}

        async def wrapped(message):
            if message["type"] == "http.response.start":
                ctype = dict((k.lower(), v) for k, v in message.get("headers", ())).get(b"content-type", b"")
                if ctype.startswith(b"text/html"):
                    held["start"] = message
                    held["body"] = bytearray()
                    return
                await send(message)
            elif message["type"] == "http.response.body" and "start" in held:
                held["body"] += message.get("body", b"")
                if message.get("more_body"):
                    return
                body = bytes(held["body"])
                marker = body.find(b"<body>")
                if marker >= 0:
                    cut = marker + len(b"<body>")
                    body = body[:cut] + banner(pick) + body[cut:]
                start = dict(held.pop("start"))
                start["headers"] = [(k, v) for k, v in start["headers"]
                                    if k.lower() != b"content-length"]
                start["headers"].append((b"content-length", str(len(body)).encode()))
                await send(start)
                await send({"type": "http.response.body", "body": body})
            else:
                await send(message)

        return wrapped

    async def _switcher(self, scope, send, path, pick):
        if scope.get("method") not in ("GET", "HEAD"):
            body, status, extra = b"", 501, []
        elif path == "/_dev/identity":
            body, status, extra = _page(pick), 200, []
        else:
            choice = path[len("/_dev/identity/"):]
            if choice == "none":
                cookie = f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
            elif choice in DEV_IDENTITIES:
                cookie = f"{COOKIE}={choice}; Path=/; HttpOnly; SameSite=Strict"
            else:
                cookie = None
            if cookie is None:
                body, status, extra = _page(pick), 404, []
            else:
                body, status, extra = b"", 303, [(b"location", b"/"), (b"set-cookie", cookie.encode())]
        if status == 200 or status == 404:
            body = body.replace(b"<body>", b"<body>" + banner(pick), 1)
        headers = with_hygiene([(b"content-type", b"text/html; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())] + extra)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if scope.get("method") == "HEAD" else body})
