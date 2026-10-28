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

import base64
import hashlib
import hmac
import secrets
import time
from typing import Callable, Dict, FrozenSet, Optional
from urllib.parse import parse_qsl

TV_ROUTE = "/me/tv"
FORM_ROUTES = frozenset({TV_ROUTE})
MAX_FORM_BYTES = 1024
TOKEN_TTL = 30 * 60


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
        if not isinstance(token, str) or len(token) > 64:
            return False
        exp_text, _, sig = token.partition(".")
        if not exp_text.isdigit() or not sig or int(exp_text) < self._clock():
            return False
        return hmac.compare_digest(sig, self._sig(form, int(exp_text), username))


def result_headers(outcome: str, allowed) -> Dict[str, str]:
    """The 303 back to the page after a post (post/redirect/get). `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    return {"Location": f"{TV_ROUTE}?r={outcome}"}
