"""Home's form posts ("Sign in on a TV", Quick Connect, owner decision 2026-10-27; the request brokers' ask pages,
bookrequests.py and watchrequests.py). No member data at import.

This is the ONLY module that reads a request body, as `identity.py` is the only one that reads headers (the route-layer
guard, webtests/test_route_layer_source.py, pins both). A post is accepted only when every lock holds:

  * main.py has that form switched on, so the middleware lets a POST to its exact path through (otherwise 501, as for
    every other path), with a Content-Length of at most middleware.MAX_FORM_BODY;
  * identity.py says it is a same-origin `application/x-www-form-urlencoded` post (Sec-Fetch-Site, or Origin = Host);
  * the body is at most the form's limit (MAX_FORM_BYTES unless the form needs more) and holds only the allow-listed
    fields, each at most once (and, for an `exact` form, every one of them);
  * the form token is an HMAC over the form's fields, expiry and the verified member's username (FormTokens here for
    the TV form; requests/forms.FormSigner for the brokers), issued by the page the member just loaded;
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
MAX_FORM_BYTES = 1024
TOKEN_TTL = 30 * 60
_TOKEN = re.compile(r"([0-9]{1,12})\.([A-Za-z0-9_-]{1,40})\Z")


async def read_form(request, fields: FrozenSet[str], limit: int = MAX_FORM_BYTES,
                    exact: bool = False) -> Optional[Dict[str, str]]:
    """The posted fields, or None for an oversized, non-ASCII, malformed or unexpected body (or, with `exact`, one
    missing a field). Values are percent-decoded as strict UTF-8. Never logged."""
    raw = await read_body(request, limit)
    if raw is None:
        return None
    try:
        text = raw.decode("ascii")
        pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=bool(text), max_num_fields=len(fields),
                          encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    out: Dict[str, str] = {}
    for key, value in pairs:
        if key not in fields or key in out:
            return None
        out[key] = value
    if exact and set(out) != fields:
        return None
    return out


async def read_body(request, limit: int) -> Optional[bytes]:
    """The raw body, or None when it is larger than `limit`: the one bounded read behind read_form and Me → My
    profile's photo upload (avatar.py parses that). Never logged."""
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


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
