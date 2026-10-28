"""Stateless protection for the request broker's one form: a signed token, a double-tap guard, a per-member rate.

Status: proposed, not deployed. Standard library only.

Home keeps no session store, so the confirmation form carries everything it will submit plus an HMAC over
(principal username, those exact fields, expiry). The key is derived from a secret Home already holds
(`form_key`: the JWT client secret in a JWT identity mode), so open forms survive a restart; without one it is
`os.urandom` at start and a restart simply expires every open form. The POST is accepted only when the MAC matches for the SAME
verified principal and the SAME fields, so:

  * another site cannot forge a request (it cannot compute the MAC), and the route also checks the browser's own
    `Origin` / `Sec-Fetch-Site` (main.py);
  * a member cannot replay a token minted for someone else, or edit the title or format a token was minted for
    (the fields Home rendered from Shelfarr's own search are the only fields it will send);
  * a token is good for TOKEN_TTL seconds.

The guards are in memory and per process, like the adapters' cache: good enough to stop a double tap and a runaway
loop; Shelfarr's own duplicate check is the real idempotency.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque
from typing import Callable, Dict, Mapping, Optional, Tuple

TOKEN_TTL = 15 * 60             # long enough to read the page, short enough that an old tab expires
DOUBLE_TAP_WINDOW = 60.0        # the same member asking for the same format of the same work again
RATE_WINDOW, RATE_MAX = 3600.0, 10
SEARCH_WINDOW, SEARCH_MAX = 600.0, 40   # searches per member per ten minutes (the providers' caps are shared)
FLASH_TTL = 120.0               # how long an outcome waits for the redirected page to show it


def form_key(secret: str) -> Optional[bytes]:
    """A form-signing key derived from a secret Home already holds, or None (then FormSigner draws a random one).
    A separate, labelled derivation: the form key reveals nothing about the secret and cannot sign anything else."""
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), b"avrana-home/request-forms/v1", hashlib.sha256).digest()


class FormSigner:
    def __init__(self, key: Optional[bytes] = None, now: Callable[[], float] = time.time):
        self._key = key if key is not None else os.urandom(32)
        self._now = now

    def __repr__(self) -> str:
        return "FormSigner(<redacted>)"

    def _mac(self, username: str, fields: Mapping[str, str], expires: int) -> str:
        message = json.dumps([username, sorted(fields.items()), expires], ensure_ascii=True,
                             separators=(",", ":")).encode("ascii")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def sign(self, username: str, fields: Mapping[str, str]) -> str:
        expires = int(self._now()) + TOKEN_TTL
        return f"{expires}.{self._mac(username, fields, expires)}"

    def verify(self, token: object, username: str, fields: Mapping[str, str]) -> bool:
        if not isinstance(token, str) or len(token) > 100 or token.count(".") != 1:
            return False
        raw_expires, mac = token.split(".")
        if not raw_expires.isdigit() or len(raw_expires) > 12:
            return False
        expires = int(raw_expires)
        if expires < self._now() or expires > self._now() + TOKEN_TTL:
            return False
        return hmac.compare_digest(mac, self._mac(username, fields, expires))


class RequestGuard:
    """`check(username, key)` -> None when the attempt may go ahead (and records it), else "repeat" or "rate"."""

    def __init__(self, now: Callable[[], float] = time.monotonic):
        self._now = now
        self._lock = threading.Lock()
        self._recent: Dict[Tuple[str, str], float] = {}
        self._attempts: Dict[str, deque] = {}

    def check(self, username: str, key: str) -> Optional[str]:
        now = self._now()
        with self._lock:
            self._recent = {k: t for k, t in self._recent.items() if now - t < DOUBLE_TAP_WINDOW}
            if (username, key) in self._recent:
                return "repeat"
            attempts = self._attempts.setdefault(username, deque())
            while attempts and now - attempts[0] >= RATE_WINDOW:
                attempts.popleft()
            if len(attempts) >= RATE_MAX:
                return "rate"
            attempts.append(now)
            self._recent[(username, key)] = now
            return None


class SearchLimiter:
    """`allow(username)` -> False once a member has searched SEARCH_MAX times in SEARCH_WINDOW (a runaway tab or a
    script must not spend the shared Hardcover or TMDB budget for everyone)."""

    def __init__(self, now: Callable[[], float] = time.monotonic, window: float = SEARCH_WINDOW,
                 limit: int = SEARCH_MAX):
        self._now, self._window, self._limit = now, window, limit
        self._lock = threading.Lock()
        self._seen: Dict[str, deque] = {}

    def allow(self, username: str) -> bool:
        now = self._now()
        with self._lock:
            if len(self._seen) > 10_000:                 # bounded memory: forget idle members
                self._seen = {u: q for u, q in self._seen.items() if q and now - q[-1] < self._window}
            seen = self._seen.setdefault(username, deque())
            while seen and now - seen[0] >= self._window:
                seen.popleft()
            if len(seen) >= self._limit:
                return False
            seen.append(now)
            return True


class SearchCache:
    """A small TTL cache of upstream search answers. Keys must already say whose view they are: a shared service
    account search is keyed by the term alone, a search made AS a member by (member, term). Only successful answers
    ("ok", "empty") are kept; `drop` forgets one key after the member asked for something, so the next view is fresh."""

    def __init__(self, ttl: float, size: int = 256, now: Callable[[], float] = time.monotonic):
        self._ttl, self._size, self._now = ttl, size, now
        self._lock = threading.Lock()
        self._data: Dict[object, Tuple[float, object]] = {}

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit is None or self._now() - hit[0] > self._ttl:
                self._data.pop(key, None)
                return None
            return hit[1]

    def put(self, key, value) -> None:
        with self._lock:
            if len(self._data) >= self._size:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (self._now(), value)

    def drop(self, key) -> None:
        with self._lock:
            self._data.pop(key, None)


class Flash:
    """One outcome per member, shown once by the page the POST redirects to (post-redirect-get: a reload never
    re-sends the form). In memory, per process, FLASH_TTL seconds."""

    def __init__(self, now: Callable[[], float] = time.monotonic):
        self._now = now
        self._lock = threading.Lock()
        self._data: Dict[Tuple[str, str], Tuple[float, object]] = {}

    def put(self, username: str, page: str, value) -> None:
        with self._lock:
            now = self._now()
            self._data = {k: v for k, v in self._data.items() if now - v[0] < FLASH_TTL}
            self._data[(username, page)] = (now, value)

    def take(self, username: str, page: str):
        with self._lock:
            hit = self._data.pop((username, page), None)
        return hit[1] if hit is not None and self._now() - hit[0] < FLASH_TTL else None

