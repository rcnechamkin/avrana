"""Embedded Jellyfin Quick Connect approval (Media 2.0 ME-05; owner decision 2026-10-27, option C2). Standard library only.

A member types the 6-digit code their TV shows; Home approves it AS THAT MEMBER through Jellyfin's
`POST /QuickConnect/Authorize?code=<code>&userId=<member's Jellyfin id>`, using the server's API key (Jellyfin gives
every API key the Administrator role, which is what lets `userId` name another user: 10.11 QuickConnectController and
RequestHelpers.GetUserId). It is an upstream WRITE (as are the request brokers in requests/), so it lives here,
apart from the read-only adapters and their GET-only allow-list, with its own allow-list of exactly three requests:

  GET  /QuickConnect/Enabled                       is Quick Connect switched on (no auth needed upstream)
  GET  /Users                                      the member's account, matched by exact username, and its Policy
  POST /QuickConnect/Authorize  code, userId       the approval

Guardrails (docs/design/ME-PREFERENCES-PROFILE-QUICKCONNECT.md section 4):
  * the member comes only from the verified principal (real mode needs jwt_required: settings.py); the Jellyfin id
    comes only from the exact-username match (adapters/_base.match_exactly_one), never from the request;
  * never for a Jellyfin administrator or a disabled account (Policy), never for a missing or ambiguous match;
  * only when Quick Connect is on; only a code of exactly six digits;
  * rate limits per member and overall, counted before any upstream call;
  * no retry: approving is not idempotent, so a timeout is reported as "unknown", never repeated;
  * the code is never logged, cached, stored or returned.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from typing import Callable, Dict, Optional, Tuple

from .adapters._base import lookup_username, match_exactly_one, member_override
from .adapters.jellyfin import normalise_guid
from .contract import REQUIRED_GROUP, AmbiguousMappingError, MappingFailed, Service
from .principal import is_minted_principal
from .resilience import (DEFAULT_TIMEOUT, MAX_JSON_BYTES, UpstreamAuthError, UpstreamError, UpstreamHTTPError,
                         UpstreamNotFound, UpstreamTimeout)

CODE = re.compile(r"[0-9]{6}\Z")
SMALL = 4096
STATUS_TTL = 30.0                  # the page's status is reused this long per member (the approval re-checks everything)
STATUS_TTL_UNAVAILABLE = 5.0       # a failed look is retried sooner, but not on every reload
STATUS_ENTRIES = 512

# Outcomes, each a fixed id the page turns into words (never upstream text).
APPROVED = "approved"              # Jellyfin answered true: the approval is acknowledged (not a verified TV sign-in)
BAD_CODE = "bad_code"              # not six digits
NOT_FOUND = "not_found"            # Jellyfin knows no waiting request with that code (wrong or expired)
NOT_ACCEPTED = "not_accepted"      # Jellyfin refused it otherwise (for example, already approved)
OFF = "off"                        # Quick Connect is switched off on the server
NOT_ELIGIBLE = "not_eligible"      # no TV and Movies access, admin, disabled, unmatched or ambiguous account
BUSY = "busy"                      # rate limit
UNKNOWN = "unknown"                # timed out after sending: it may or may not have gone through
UNAVAILABLE = "unavailable"        # Jellyfin could not be reached or answered nonsense before the approval was sent
OUTCOMES = (APPROVED, BAD_CODE, NOT_FOUND, NOT_ACCEPTED, OFF, NOT_ELIGIBLE, BUSY, UNKNOWN, UNAVAILABLE)

READY = "ready"                    # status(): the form can be offered

_ALLOWED = {("GET", "/QuickConnect/Enabled"): frozenset(), ("GET", "/Users"): frozenset(),
            ("POST", "/QuickConnect/Authorize"): frozenset({"code", "userId"})}


class ForbiddenQuickConnectRequest(Exception):
    pass


def check_request(method: str, path: str, query: Optional[Dict[str, str]]) -> None:
    allowed = _ALLOWED.get((method, path))
    if allowed is None or set(query or {}) != allowed:
        raise ForbiddenQuickConnectRequest()
    if allowed:
        if not CODE.fullmatch(query["code"]) or normalise_guid(query["userId"]) != query["userId"]:
            raise ForbiddenQuickConnectRequest()


class RateLimit:
    """At most `per_member` attempts per member and `overall` in all, in any `window` seconds. In memory, per
    process (one worker); a restart forgets, which only ever allows more tries after a restart, never fewer."""

    def __init__(self, per_member: int = 5, overall: int = 30, window: float = 600.0,
                 clock: Callable[[], float] = time.monotonic):
        self._per, self._all, self._window, self._clock = per_member, overall, window, clock
        self._members: Dict[str, deque] = {}
        self._every: deque = deque()
        self._lock = threading.Lock()

    def take(self, member: str) -> bool:
        now = self._clock()
        with self._lock:
            for q in (self._every, *self._members.values()):
                while q and q[0] <= now - self._window:
                    q.popleft()
            self._members = {k: q for k, q in self._members.items() if q}
            mine = self._members.setdefault(member, deque())
            if len(mine) >= self._per or len(self._every) >= self._all:
                return False
            mine.append(now)
            self._every.append(now)
            return True


class QuickConnect:
    def __init__(self, transport, *, timeout: float = DEFAULT_TIMEOUT, limit: Optional[RateLimit] = None,
                 member_username: Optional[Tuple[str, str]] = None, clock: Callable[[], float] = time.monotonic):
        self._transport = transport
        self._timeout = timeout
        self._limit = limit or RateLimit(clock=clock)
        self._member_username = member_override(member_username)
        self._clock = clock
        self._status: Dict[str, Tuple[float, str]] = {}      # username -> (expires, status); never a code
        self._status_lock = threading.Lock()

    def __repr__(self) -> str:
        return "QuickConnect(<redacted>)"

    def _call(self, method: str, path: str, query=None, max_bytes: int = SMALL):
        check_request(method, path, query)
        resp = self._transport.request(method, path, query, self._timeout, max_bytes)
        if resp.status != 200:
            raise UpstreamHTTPError(resp.status)
        return resp

    def _enabled(self) -> bool:
        return self._call("GET", "/QuickConnect/Enabled").body.strip() == b"true"

    def _member_id(self, principal) -> Optional[str]:
        """The member's Jellyfin id (32 hex), or None when they must not be approved for: unmatched, ambiguous,
        disabled or a Jellyfin administrator."""
        users = json.loads(self._call("GET", "/Users", None, MAX_JSON_BYTES).body)
        if not isinstance(users, list):
            raise ValueError("users")

        def extract(raw):
            if not isinstance(raw, dict):
                return None
            name, uid = raw.get("Name"), normalise_guid(raw.get("Id"))
            return (name, uid) if isinstance(name, str) and uid is not None else None
        try:
            uid, raw = match_exactly_one(lookup_username(principal, self._member_username), users, extract)
        except (MappingFailed, AmbiguousMappingError):
            return None
        policy = raw.get("Policy")
        if not isinstance(policy, dict) or policy.get("IsDisabled") is not False \
                or policy.get("IsAdministrator") is not False:
            return None                     # missing Policy fails closed too
        return uid

    def _eligible_principal(self, principal) -> bool:
        return is_minted_principal(principal) and REQUIRED_GROUP[Service.JELLYFIN] in principal.groups

    def status(self, principal) -> str:
        """READY, OFF, NOT_ELIGIBLE or UNAVAILABLE, for the page. Read-only, and the approval checks everything again, so
        the answer is reused for STATUS_TTL per member: reloading /me/tv costs no upstream calls, and a slow Jellyfin
        holds the page up at most once per member and window."""
        if not self._eligible_principal(principal):
            return NOT_ELIGIBLE
        now = self._clock()
        with self._status_lock:
            hit = self._status.get(principal.username)
        if hit is not None and hit[0] > now:
            return hit[1]
        result = self._look(principal)
        ttl = STATUS_TTL_UNAVAILABLE if result == UNAVAILABLE else STATUS_TTL
        with self._status_lock:
            if len(self._status) >= STATUS_ENTRIES:
                self._status = {k: v for k, v in self._status.items() if v[0] > now}
                if len(self._status) >= STATUS_ENTRIES:
                    self._status.clear()
            self._status[principal.username] = (now + ttl, result)
        return result

    def _forget(self, principal) -> None:
        with self._status_lock:
            self._status.pop(principal.username, None)

    def _look(self, principal) -> str:
        try:
            if not self._enabled():
                return OFF
            return READY if self._member_id(principal) else NOT_ELIGIBLE
        except (UpstreamError, ValueError, ForbiddenQuickConnectRequest):
            return UNAVAILABLE

    def approve(self, principal, code: str) -> str:
        outcome = self._approve(principal, code)
        if outcome in (OFF, NOT_ELIGIBLE, UNAVAILABLE):
            self._forget(principal)         # the page after the redirect looks again rather than offer a stale form
        return outcome

    def _approve(self, principal, code: str) -> str:
        if not self._eligible_principal(principal):
            return NOT_ELIGIBLE
        if not isinstance(code, str) or not CODE.fullmatch(code):
            return BAD_CODE
        if not self._limit.take(principal.username):
            return BUSY
        try:
            if not self._enabled():
                return OFF
            uid = self._member_id(principal)
        except (UpstreamError, ValueError, ForbiddenQuickConnectRequest):
            return UNAVAILABLE
        if uid is None:
            return NOT_ELIGIBLE
        try:
            resp = self._call("POST", "/QuickConnect/Authorize", {"code": code, "userId": uid})
        except UpstreamTimeout:
            return UNKNOWN                  # sent, outcome unknown: never retried
        except UpstreamNotFound:
            return NOT_FOUND
        except UpstreamAuthError as exc:
            # 401: switched off between the check and the approval (10.11 answers a disabled Quick Connect with an
            # authentication error). 403: the key lacks the rights, which no retry fixes.
            return OFF if exc.status == 401 else UNAVAILABLE
        except UpstreamHTTPError:
            return NOT_ACCEPTED             # e.g. Jellyfin's "already authorized" (an unhandled 500 upstream)
        except UpstreamError:
            return UNKNOWN                  # the connection broke after sending: can't tell
        return APPROVED if resp.body.strip() == b"true" else NOT_ACCEPTED
