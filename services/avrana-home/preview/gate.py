"""The owner preview's two outer ASGI layers. Standard library plus avrana_home only.

Outermost to innermost:

  1. `PasswordGate`: HTTP Basic auth against ONE password read from a file at startup. The username part
     is ignored. The comparison is constant time (`hmac.compare_digest` over SHA-256 digests, so the length
     of the stored password does not leak either). Without the right password the answer is 401 with
     `WWW-Authenticate: Basic realm="Avrana preview"`, and NOTHING inside runs: not the identity layer, not
     the application, not /healthz. The one exception is `GET|HEAD /healthz` with no query from a LOOPBACK
     peer (127.0.0.1 or ::1, the real TCP peer: uvicorn runs with proxy_headers off): the container's own
     HEALTHCHECK runs inside the container's network namespace, and no LAN client can appear as loopback
     there (published ports arrive from the bridge gateway or the client's own address). The alternative,
     a healthcheck that reads the password file, would put the secret in a second process for no gain.
     A simple in-memory throttle: after MAX_FAILURES wrong passwords within WINDOW seconds from one client
     address, that address gets 429 for LOCKOUT seconds, right password or not. A request without any
     Authorization header (a browser's first try) is not counted. The password and the Authorization
     header are never logged; the header is removed before the request goes further in.
  2. `OwnerIdentity`: strips EVERY inbound header that could carry identity (`x-authentik-*`,
     `x-forwarded-*`, `forwarded`, `remote-user`, `x-remote-user`, `x-real-ip`, `x-dev-identity`, any case,
     `_` or `-`) and then adds the owner's fixed identity headers. A client can never choose the identity.

Both refuse to be built without the sealed token `check_preview_startup` returns (the dev_identity pattern).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

from avrana_home.app.logsafe import app_log, log_event
from avrana_home.app.middleware import with_hygiene
from avrana_home.contract import REQUIRED_GROUP
from avrana_home.principal import PrincipalError, principal_from_raw_headers

REALM = b'Basic realm="Avrana preview"'
MIN_PASSWORD = 16
MAX_PASSWORD = 1024
MAX_FAILURES = 10
WINDOW = 60.0
LOCKOUT = 60.0
MAX_TRACKED = 4096                   # client addresses remembered by the throttle, oldest dropped first
LOOPBACK = ("127.0.0.1", "::1")
# The groups the preview may inject: the portal's member group and the library groups the adapters check
# (contract.REQUIRED_GROUP). Nothing administrative, so the preview never shows the Operations tile.
ALLOWED_GROUPS = frozenset({"avrana-users", *REQUIRED_GROUP.values()})
_STRIPPED_EXACT = frozenset({"forwarded", "remote-user", "x-remote-user", "x-real-ip", "x-dev-identity",
                             "authorization"})


class PreviewRefused(RuntimeError):
    """The owner preview will not start in this configuration. Messages never carry a secret."""


class _Checked:
    __slots__ = ()


_SEAL = _Checked()


# ---- startup checks ----------------------------------------------------------------------------
def read_password(path: Optional[str]) -> bytes:
    """The password from PREVIEW_PASSWORD_FILE: surrounding whitespace (the trailing newline) is dropped;
    at least MIN_PASSWORD characters. Raises PreviewRefused, naming the variable, never the value."""
    if not path:
        raise PreviewRefused("PREVIEW_PASSWORD_FILE is required")
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise PreviewRefused("PREVIEW_PASSWORD_FILE cannot be read") from None
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise PreviewRefused("PREVIEW_PASSWORD_FILE is not UTF-8 text") from None
    if len(text) < MIN_PASSWORD:
        raise PreviewRefused(f"the preview password must be at least {MIN_PASSWORD} characters")
    if len(text) > MAX_PASSWORD or not text.isprintable():
        raise PreviewRefused("the preview password must be one line of printable text")
    return text.encode("utf-8")


def check_bind(host: str, in_container: bool) -> None:
    """Loopback literals always; 0.0.0.0 only inside the preview container (PREVIEW_IN_CONTAINER=yes, set by
    Dockerfile.preview), where the compose file publishes ONE LAN address. Anything else is refused: a
    host-level bind to a public or LAN address, a name, or `::` (all IPv6 interfaces)."""
    if host in LOOPBACK:
        return
    if host == "0.0.0.0" and in_container:
        return
    raise PreviewRefused("the preview binds 127.0.0.1 or ::1, or 0.0.0.0 inside its container only")


def owner_headers(username: str, groups: Iterable[str]) -> list:
    """The fixed identity headers, validated by the same parser the application uses."""
    groups = [g for g in groups]
    if not username or any(c.isspace() for c in username):
        raise PreviewRefused("PREVIEW_OWNER_USERNAME is not a usable username")
    if not groups:
        raise PreviewRefused("PREVIEW_OWNER_GROUPS is required")
    unknown = [g for g in groups if g not in ALLOWED_GROUPS]
    if unknown:
        raise PreviewRefused("PREVIEW_OWNER_GROUPS may name only avrana-users and the library groups")
    try:
        pairs = [(b"x-authentik-username", username.encode("ascii")),
                 (b"x-authentik-groups", "|".join(groups).encode("ascii"))]
        principal_from_raw_headers(pairs)
    except (PrincipalError, UnicodeEncodeError):
        raise PreviewRefused("PREVIEW_OWNER_USERNAME and PREVIEW_OWNER_GROUPS do not form a valid identity") from None
    return pairs


def check_preview_startup(*, password: bytes, settings, host: str, in_container: bool) -> _Checked:
    """Return the sealed token the two layers need, or raise PreviewRefused."""
    if not isinstance(password, bytes) or len(password) < MIN_PASSWORD:
        raise PreviewRefused(f"the preview password must be at least {MIN_PASSWORD} characters")
    if getattr(settings, "owner_preview", False) is not True:
        raise PreviewRefused("the settings were not built for the owner preview")
    if not settings.home_sections:
        raise PreviewRefused("the owner preview needs HOME_SECTIONS=on")
    check_bind(host, in_container)
    return _SEAL


# ---- helpers -------------------------------------------------------------------------------------
def _norm(name: bytes) -> str:
    return bytes(name).decode("latin-1").lower().replace("_", "-")


def _identity_like(name: str) -> bool:
    return name.startswith("x-authentik") or name.startswith("x-forwarded") or name in _STRIPPED_EXACT


async def _plain(send, status: int, body: bytes, extra=(), head: bool = False) -> None:
    headers = with_hygiene([(b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())] + list(extra))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b"" if head else body})


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


# ---- 1. the password gate --------------------------------------------------------------------------
class PasswordGate:
    def __init__(self, app, *, password: bytes, checked, clock: Callable[[], float] = time.monotonic):
        if checked is not _SEAL:
            raise PreviewRefused("construct only after check_preview_startup")
        if not isinstance(password, bytes) or len(password) < MIN_PASSWORD:
            raise PreviewRefused(f"the preview password must be at least {MIN_PASSWORD} characters")
        self.app = app
        self._want = _digest(password)        # only the digest is kept on the object
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: Dict[str, deque] = {}
        self._locked: Dict[str, float] = {}

    def __repr__(self) -> str:
        return "PasswordGate(<redacted>)"

    # -- throttle --
    def _is_locked(self, addr: str, now: float) -> bool:
        with self._lock:
            until = self._locked.get(addr)
            if until is None:
                return False
            if now >= until:
                del self._locked[addr]
                self._failures.pop(addr, None)
                return False
            return True

    def _fail(self, addr: str, now: float) -> bool:
        """Record one wrong password; True when this address is now locked out."""
        with self._lock:
            q = self._failures.pop(addr, None) or deque()
            self._failures[addr] = q                     # re-inserted: most recent last
            while q and now - q[0] > WINDOW:
                q.popleft()
            q.append(now)
            while len(self._failures) > MAX_TRACKED:
                self._failures.pop(next(iter(self._failures)))
            if len(q) >= MAX_FAILURES:
                self._locked[addr] = now + LOCKOUT
                while len(self._locked) > MAX_TRACKED:
                    self._locked.pop(next(iter(self._locked)))
                return True
            return False

    def _ok(self, addr: str) -> None:
        with self._lock:
            self._failures.pop(addr, None)

    # -- credentials --
    def _check(self, values) -> Optional[bool]:
        """None: no Authorization header at all. True/False: the password is / is not the one."""
        if not values:
            return None
        if len(values) != 1:
            return False
        scheme, _, token = bytes(values[0]).strip().partition(b" ")
        if scheme.lower() != b"basic" or not token or len(token) > 4 * MAX_PASSWORD:
            return False
        try:
            decoded = base64.b64decode(token.strip(), validate=True)
        except (binascii.Error, ValueError):
            return False
        _user, sep, given = decoded.partition(b":")      # the username part is ignored
        if not sep:
            return False
        return hmac.compare_digest(_digest(given), self._want)

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind == "lifespan":
            return await self.app(scope, receive, send)
        if kind != "http":                               # no websockets in this application
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        client = scope.get("client") or ("", 0)
        addr = str(client[0]) if client else ""
        head = scope.get("method") == "HEAD"
        if self._loopback_health(scope, addr):
            return await self.app(scope, receive, send)
        now = self._clock()
        if self._is_locked(addr, now):
            return await _plain(send, 429, b"Too many attempts. Try again in a minute.\n",
                                [(b"retry-after", str(int(LOCKOUT)).encode())], head)
        values = [v for k, v in scope.get("headers", ()) if _norm(k) == "authorization"]
        verdict = self._check(values)
        if verdict is True:
            self._ok(addr)
            inner = dict(scope, headers=[(k, v) for k, v in scope.get("headers", ())
                                         if _norm(k) != "authorization"])
            return await self.app(inner, receive, send)
        if verdict is False and self._fail(addr, now):
            log_event(app_log, logging.WARNING, "preview_auth_throttled")
            return await _plain(send, 429, b"Too many attempts. Try again in a minute.\n",
                                [(b"retry-after", str(int(LOCKOUT)).encode())], head)
        await _plain(send, 401, b"Password required.\n", [(b"www-authenticate", REALM)], head)

    @staticmethod
    def _loopback_health(scope, addr: str) -> bool:
        if scope.get("method") not in ("GET", "HEAD") or scope.get("path") != "/healthz":
            return False
        if scope.get("query_string") or scope.get("raw_path", b"/healthz") != b"/healthz":
            return False
        return addr in LOOPBACK


# ---- 2. the fixed owner identity ---------------------------------------------------------------------
class OwnerIdentity:
    def __init__(self, app, *, headers: list, checked):
        if checked is not _SEAL:
            raise PreviewRefused("construct only after check_preview_startup")
        self.app = app
        self._headers: Tuple[Tuple[bytes, bytes], ...] = tuple((bytes(k), bytes(v)) for k, v in headers)

    def __repr__(self) -> str:
        return "OwnerIdentity(<fixed>)"

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        kept = [(k, v) for k, v in scope.get("headers", ()) if not _identity_like(_norm(k))]
        await self.app(dict(scope, headers=kept + list(self._headers)), receive, send)
