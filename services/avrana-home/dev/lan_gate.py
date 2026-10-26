"""The passphrase gate in front of the fixture-only LAN preview (run_lan_preview.py, AVR-585 B1). Standard library.

preview/gate.py is not reused: its sealed token comes only from the REAL owner-preview settings path, and HTTP Basic
would resend the secret on every request. This gate is the outermost ASGI layer:

  * Host check first: only `<bind ip>:<port>` (and the optional `<name>.local:<port>`) are answered; any other Host
    gets 421, so a DNS-rebinding page on another origin reaches nothing.
  * One random passphrase per run (made by the launcher with `secrets`, printed to the console only). Only its
    SHA-256 digest is kept; the comparison is `hmac.compare_digest`. It is never logged, never echoed.
  * `POST /_lan/unlock` (form body, at most MAX_BODY bytes) with the right passphrase sets
    `__Host-avrana_lan=<random token>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=<seconds left>` and
    redirects to /. Tokens live in this process's memory only, so a cookie from an earlier run is worthless.
  * Every other request without a valid cookie gets the same minimal page (the passphrase form, no fixture data,
    status 403); the application, the identity shim and the mocks are never reached.
  * Wrong passphrases: MAX_FAILURES per address within WINDOW seconds locks that address out for LOCKOUT seconds
    (429); MAX_TOTAL_FAILURES in all seals the gate for the rest of the run (restart to get a new passphrase).
  * The gate's cookie is removed from the Cookie header before the request goes further in.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import secrets
import threading
import time
from collections import deque
from typing import Callable, Dict, Iterable
from urllib.parse import parse_qs

from avrana_home.app.logsafe import app_log, log_event
from avrana_home.app.middleware import with_hygiene

COOKIE = "__Host-avrana_lan"
UNLOCK_PATH = "/_lan/unlock"
MIN_PASSPHRASE = 16
MAX_BODY = 2048
MAX_FAILURES = 5
WINDOW = 300.0
LOCKOUT = 300.0
MAX_TOTAL_FAILURES = 25
MAX_SESSIONS = 8
MAX_TRACKED = 1024


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _norm(name: bytes) -> str:
    return bytes(name).decode("latin-1").lower()


def _page(message: str = "") -> bytes:
    note = f'<p role="alert">{html.escape(message)}</p>' if message else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Preview locked</title></head><body style="font:16px/1.5 sans-serif;margin:24px">'
            '<h1>Temporary preview</h1><p>Enter the passphrase shown in the console that started it.</p>'
            f'{note}<form method="post" action="{UNLOCK_PATH}">'
            '<label for="p">Passphrase</label><br>'
            '<input id="p" name="passphrase" type="password" autocomplete="off" autocapitalize="off" '
            'spellcheck="false" required style="font-size:18px;width:100%;max-width:24em"><br><br>'
            '<button type="submit" style="font-size:18px">Unlock</button></form></body></html>').encode("utf-8")


class LanGate:
    def __init__(self, app, *, passphrase: str, allowed_hosts: Iterable[str], expires_at: float,
                 clock: Callable[[], float] = time.monotonic):
        if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE:
            raise ValueError(f"the passphrase must be at least {MIN_PASSPHRASE} characters")
        hosts = frozenset(h.lower().encode("ascii") for h in allowed_hosts)
        if not hosts:
            raise ValueError("at least one allowed Host is required")
        self.app = app
        self._want = _digest(passphrase.encode("utf-8"))     # only the digest is kept
        self._hosts = hosts
        self._expires_at = expires_at
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: Dict[bytes, None] = {}               # digests of live session tokens, oldest first
        self._failures: Dict[str, deque] = {}
        self._locked: Dict[str, float] = {}
        self._total_failures = 0
        self.sealed = False

    def __repr__(self) -> str:
        return "LanGate(<redacted>)"

    # ---- throttle ----
    def _is_locked(self, addr: str, now: float) -> bool:
        with self._lock:
            if self.sealed:
                return True
            until = self._locked.get(addr)
            if until is None:
                return False
            if now >= until:
                del self._locked[addr]
                self._failures.pop(addr, None)
                return False
            return True

    def _fail(self, addr: str, now: float) -> None:
        with self._lock:
            self._total_failures += 1
            if self._total_failures >= MAX_TOTAL_FAILURES and not self.sealed:
                self.sealed = True
                log_event(app_log, logging.WARNING, "lan_gate_sealed")
            q = self._failures.pop(addr, None) or deque()
            self._failures[addr] = q
            while q and now - q[0] > WINDOW:
                q.popleft()
            q.append(now)
            while len(self._failures) > MAX_TRACKED:
                self._failures.pop(next(iter(self._failures)))
            if len(q) >= MAX_FAILURES:
                self._locked[addr] = now + LOCKOUT
                log_event(app_log, logging.WARNING, "lan_gate_throttled")
                while len(self._locked) > MAX_TRACKED:
                    self._locked.pop(next(iter(self._locked)))

    # ---- sessions ----
    def _new_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[_digest(token.encode("ascii"))] = None
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.pop(next(iter(self._sessions)))
        return token

    def _has_session(self, headers) -> bool:
        if self._clock() >= self._expires_at:
            return False
        for name, value in headers:
            if _norm(name) != "cookie":
                continue
            for part in bytes(value).decode("latin-1").split(";"):
                key, _, token = part.strip().partition("=")
                if key == COOKIE and token:
                    with self._lock:
                        if _digest(token.encode("latin-1")) in self._sessions:
                            return True
        return False

    @staticmethod
    def _without_gate_cookie(headers) -> list:
        out = []
        for name, value in headers:
            if _norm(name) == "cookie":
                parts = [p for p in bytes(value).decode("latin-1").split(";")
                         if p.strip().partition("=")[0] != COOKIE]
                kept = ";".join(parts).strip().strip(";").strip()
                if kept:
                    out.append((name, kept.encode("latin-1")))
                continue
            out.append((name, value))
        return out

    # ---- responses ----
    @staticmethod
    async def _send(send, status: int, body: bytes, head: bool, extra=(), ctype=b"text/html; charset=utf-8"):
        headers = with_hygiene([(b"content-type", ctype), (b"content-length", str(len(body)).encode())]
                               + list(extra), form_self=True)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if head else body})

    async def _read_body(self, receive) -> bytes:
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return b""
            body += message.get("body", b"")
            if len(body) > MAX_BODY:
                raise ValueError("body too large")
            if not message.get("more_body"):
                return bytes(body)

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind == "lifespan":
            return await self.app(scope, receive, send)
        if kind != "http":
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        method = scope.get("method")
        head = method == "HEAD"
        headers = scope.get("headers", ())
        hosts = [bytes(v).lower() for k, v in headers if _norm(k) == "host"]
        if len(hosts) != 1 or hosts[0] not in self._hosts:
            return await self._send(send, 421, b"Misdirected request.\n", head, ctype=b"text/plain; charset=utf-8")
        path = scope.get("path", "")
        if path == UNLOCK_PATH and method == "POST":
            return await self._unlock(scope, receive, send)
        if self._has_session(headers):
            if path == UNLOCK_PATH:
                return await self._send(send, 303, b"", head, [(b"location", b"/")])
            inner = dict(scope, headers=self._without_gate_cookie(headers))
            return await self.app(inner, receive, send)
        await self._send(send, 403, _page(), head)          # any method, any path: the form, nothing else

    async def _unlock(self, scope, receive, send):
        client = scope.get("client") or ("", 0)
        addr = str(client[0]) if client else ""
        now = self._clock()
        if self._is_locked(addr, now) or now >= self._expires_at:
            return await self._send(send, 429, _page("Too many wrong attempts. Try again later."), False,
                                    [(b"retry-after", str(int(LOCKOUT)).encode())])
        ctype = b""
        for k, v in scope.get("headers", ()):
            if _norm(k) == "content-type":
                ctype = bytes(v).split(b";", 1)[0].strip().lower()
        try:
            raw = await self._read_body(receive)
        except ValueError:
            return await self._send(send, 413, _page("That was too long."), False)
        given = b""
        if ctype == b"application/x-www-form-urlencoded":
            try:
                values = parse_qs(raw.decode("utf-8"), keep_blank_values=True,
                                  max_num_fields=4).get("passphrase", [])
            except (UnicodeDecodeError, ValueError):
                values = []
            if len(values) == 1:
                given = values[0].strip().encode("utf-8")
        if given and hmac.compare_digest(_digest(given), self._want):
            token = self._new_session()
            left = max(1, int(self._expires_at - now))
            cookie = f"{COOKIE}={token}; Path=/; Max-Age={left}; HttpOnly; Secure; SameSite=Strict"
            log_event(app_log, logging.INFO, "lan_gate_unlocked")
            return await self._send(send, 303, b"", False, [(b"location", b"/"), (b"set-cookie", cookie.encode())])
        self._fail(addr, now)
        await self._send(send, 403, _page("That passphrase is not right."), False)
