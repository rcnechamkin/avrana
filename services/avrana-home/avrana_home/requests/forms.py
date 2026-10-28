"""Stateless protection for the request broker's one form: a signed token, a double-tap guard, a per-member rate.

Status: proposed, not deployed. Standard library only.

Home keeps no session store, so the confirmation form carries everything it will submit plus an HMAC over
(principal username, those exact fields, expiry) with a key that exists only in this process (`os.urandom` at
start; a restart simply expires every open form). The POST is accepted only when the MAC matches for the SAME
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
