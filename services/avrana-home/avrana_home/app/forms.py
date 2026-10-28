"""Home's form posts (first one: "Sign in on a TV", Quick Connect; owner decision 2026-10-27). No member data at import.

This is the ONLY module that reads a request body, as `identity.py` is the only one that reads headers (the route-layer
guard, webtests/test_route_layer_source.py, pins both). A post is accepted only when every lock holds:

  * the path is in FORM_ROUTES and the shell is on (otherwise the method gate answers 501, as for every other path);
  * identity.py says it is a same-origin `application/x-www-form-urlencoded` post (Sec-Fetch-Site, or Origin = Host);
  * the body is at most MAX_FORM_BYTES and holds only the allow-listed fields, each at most once;
  * the form token is an HMAC over form, expiry and the verified member's username, under a per-process random key,
    issued by the page the member just loaded (so a restart simply makes the member reload the page);
  * the page itself carries CSP `form-action 'self'` (middleware.py).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
from typing import Awaitable, Callable, Dict, FrozenSet, Optional, Tuple
from urllib.parse import parse_qsl

TV_ROUTE = "/me/tv"
FORM_ROUTES = frozenset({TV_ROUTE})
MAX_FORM_BYTES = 1024
TOKEN_TTL = 30 * 60
_TOKEN = re.compile(r"([0-9]{1,12})\.([A-Za-z0-9_-]{1,40})\Z")


async def read_form(request, fields: FrozenSet[str]) -> Optional[Dict[str, str]]:
    """The posted fields, or None for an oversized, non-ASCII, malformed or unexpected body. Never logged."""
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FORM_BYTES:
            return None
        chunks.append(chunk)
    try:
        text = b"".join(chunks).decode("ascii")
        pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=bool(text), max_num_fields=len(fields))
    except (UnicodeDecodeError, ValueError):
        return None
    out: Dict[str, str] = {}
    for key, value in pairs:
        if key not in fields or key in out:
            return None
        out[key] = value
    return out


class FormTokens:
    def __init__(self, clock: Callable[[], float] = time.time, key: Optional[bytes] = None):
        self._key = key or secrets.token_bytes(32)
        self._clock = clock

    def _sig(self, form: str, exp: int, username: str) -> str:
        mac = hmac.new(self._key, f"{form}|{exp}|{username}".encode("utf-8"), hashlib.sha256).digest()[:18]
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")

    def issue(self, form: str, username: str) -> str:
        exp = int(self._clock()) + TOKEN_TTL
        return f"{exp}.{self._sig(form, exp, username)}"

    def check(self, token: Optional[str], form: str, username: str) -> bool:
        # The exact ASCII shape issue() writes: a percent-encoded "²" passes str.isdigit() but not int(), and
        # compare_digest raises on non-ASCII text, so anything looser turned a crafted token into a 500.
        match = _TOKEN.fullmatch(token) if isinstance(token, str) and len(token) <= 64 else None
        if match is None or int(match.group(1)) < self._clock():
            return False
        return hmac.compare_digest(match.group(2), self._sig(form, int(match.group(1)), username))


class Replays:
    """One upstream write per submitted form. A double-click or a resent page arrives as a second post with the same
    token and fields; it waits for the first one's answer instead of sending again, and an approval is remembered for
    the token's life, so a repeat reads "approved" rather than Jellyfin's "already used". Keyed by an HMAC of member,
    token and fields under a per-process random key, in memory only: the code itself is never kept. Single event
    loop (one worker), so no lock is needed."""

    def __init__(self, keep: FrozenSet[str], clock: Callable[[], float] = time.monotonic, limit: int = 1024):
        self._key = secrets.token_bytes(32)
        self._keep, self._clock, self._limit = keep, clock, limit
        self._pending: Dict[bytes, "asyncio.Future"] = {}
        self._done: Dict[bytes, Tuple[float, str]] = {}

    def _digest(self, parts) -> bytes:
        return hmac.new(self._key, "\x00".join(parts).encode("utf-8"), hashlib.sha256).digest()

    async def once(self, parts, run: Callable[[], Awaitable[str]]) -> str:
        key, now = self._digest(parts), self._clock()
        done = self._done.get(key)
        if done is not None and done[0] > now:
            return done[1]
        pending = self._pending.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        try:
            outcome = await run()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()             # retrieved: a lone failure never logs "exception was never retrieved"
            raise
        else:
            future.set_result(outcome)
            if outcome in self._keep:
                if len(self._done) >= self._limit:
                    self._done = {k: v for k, v in self._done.items() if v[0] > now}
                    if len(self._done) >= self._limit:
                        self._done.clear()
                self._done[key] = (now + TOKEN_TTL, outcome)
            return outcome
        finally:
            self._pending.pop(key, None)


def result_headers(outcome: str, allowed) -> Dict[str, str]:
    """The 303 back to the page after a post (post/redirect/get). `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    return {"Location": f"{TV_ROUTE}?r={outcome}"}
