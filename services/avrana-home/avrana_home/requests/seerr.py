"""Film and TV requests through Seerr (v3.4.1, `/api/v1`), on the member's behalf.

Status: proposed, not deployed. Standard library only. Design: docs/design/UNIVERSAL-SEARCH-AND-REQUESTS.md (Seerr)
and REQUEST-FORKS-PLAN.md (why the global key is accepted for now, and the fork that replaces it).

Credential: Seerr's ONE global API key. It is full Seerr admin, so the rules here are strict and settings.py accepts
it in real mode only with verified identity (`HOME_IDENTITY_MODE=jwt_required`):

  * Exactly three upstream calls exist, on a fixed allow-list (`ROUTES`): `GET /api/v1/search`, `GET /api/v1/user`
    (paged, to map members) and `POST /api/v1/request`. Nothing under `/settings`, no request status changes, no
    user edits, no deletes.
  * Every search and every request is sent AS a member (`X-API-User`), never as the key's own user 1, so Seerr's
    own per-user permissions, quotas and auto-approve apply.
  * The member is found by the Jellyfin user id Home already maps them to (the Jellyfin adapter), matched against
    Seerr's `jellyfinUserId`. A Seerr user holding ADMIN or any MANAGE_* permission, or user 1, is refused: Home never
    acts as an administrator. No match: `NOT_LINKED` (open the request website once to sign in).
  * Results are parsed strictly; people, poster paths and overviews are dropped. Only the member's own outcome is
    shown; another member's request is at most "already asked for", never who.
"""
from __future__ import annotations

import enum
import json
import threading
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..resilience import (MAX_JSON_BYTES, MAX_REQUEST_BODY, CircuitBreaker, Clock, SystemClock, UpstreamAuthError,
                          UpstreamError, UpstreamHTTPError, UpstreamNotFound, coerce, log_failure)

SERVICE = "seerr"
SEARCH_LIMIT = 10
MIN_TERM, MAX_TERM = 2, 100
MAX_TITLE = 300
USER_PAGE, USER_PAGES = 100, 20                 # at most 2,000 Seerr users are read to map members
MAP_TTL, MISS_TTL = 600.0, 60.0                 # seconds a user map is trusted; how soon a miss may re-read it
# Seerr permission bits that make a user an administrator of some kind (server/lib/permissions.ts).
ADMIN_BITS = 2 | 4 | 8 | 16                     # ADMIN, MANAGE_SETTINGS, MANAGE_USERS, MANAGE_REQUESTS
ROUTES = {("GET", "/api/v1/search"): frozenset({"query", "page"}),
          ("GET", "/api/v1/user"): frozenset({"take", "skip"}),
          ("POST", "/api/v1/request"): frozenset()}
MEDIA_TYPES = ("movie", "tv")


class MediaState(enum.Enum):
    """Seerr's `mediaInfo.status`, reduced to what a member is told."""
    NONE = "none"                  # unknown to Seerr, or 1 UNKNOWN: may be asked for
    ASKED = "asked"                # 2 PENDING, 3 PROCESSING: someone has asked; not who
    PARTIAL = "partial"            # 4 PARTIALLY_AVAILABLE (a show with some seasons in the library)
    AVAILABLE = "available"        # 5 AVAILABLE
    BLOCKED = "blocked"            # 6+ (blocklisted, deleted): not offered


_STATUS = {1: MediaState.NONE, 2: MediaState.ASKED, 3: MediaState.ASKED, 4: MediaState.PARTIAL,
           5: MediaState.AVAILABLE}


class Outcome(enum.Enum):
    CREATED = "created"            # 201, approved (or auto-approved)
    AWAITING = "awaiting"          # 201, waiting for an administrator's approval
    DUPLICATE = "duplicate"        # 409: already asked for
    REFUSED = "refused"            # 403 (quota or permission) or 202 (nothing left to ask for)
    NOT_LINKED = "not_linked"      # no Seerr user for this member, or an administrator account (never acted as)
    UNAVAILABLE = "unavailable"    # timeout, unreachable, 5xx, malformed, breaker open, or a key problem


@dataclass(frozen=True)
class WatchOffer:
    media_type: str                # "movie" | "tv"
    tmdb_id: int
    title: str
    year: Optional[int]
    state: MediaState
    jellyfin_id: Optional[str]     # the library item when Seerr knows it (32 hex)


class ForbiddenCall(Exception):
    """A call outside ROUTES: a programming error, never sent."""


def clean_term(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    text = " ".join(unicodedata.normalize("NFC", raw).split())
    if not MIN_TERM <= len(text) <= MAX_TERM or not text.isprintable():
        return None
    return text


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:limit] if text.isprintable() else ""


def _hex32(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.replace("-", "").lower()
    return v if len(v) == 32 and all(c in "0123456789abcdef" for c in v) else None


def _offer(item: Any) -> Optional[WatchOffer]:
    if not isinstance(item, dict) or item.get("mediaType") not in MEDIA_TYPES:
        return None                                   # people and anything else are dropped
    tmdb = item.get("id")
    if not isinstance(tmdb, int) or isinstance(tmdb, bool) or not 0 < tmdb < 10**9:
        return None
    movie = item["mediaType"] == "movie"
    title = _text(item.get("title" if movie else "name"), MAX_TITLE)
    if not title:
        return None
    date = item.get("releaseDate" if movie else "firstAirDate")
    year = int(date[:4]) if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit() else None
    info = item.get("mediaInfo") if isinstance(item.get("mediaInfo"), dict) else {}
    status = info.get("status")
    state = _STATUS.get(status, MediaState.BLOCKED if isinstance(status, int) and status > 5 else MediaState.NONE)
    return WatchOffer(item["mediaType"], tmdb, title, year, state, _hex32(info.get("jellyfinMediaId")))


class SeerrRequests:
    """Search Seerr as a member and create a request for that member. Thread-safe (the user map has its own lock)."""

    service = SERVICE

    def __init__(self, transport, timeout: float = 2.0, clock: Optional[Clock] = None):
        self._transport = transport
        self._timeout = float(timeout)
        self._clock = clock or SystemClock()
        self.breaker = CircuitBreaker(self._clock)
        self._map_lock = threading.Lock()
        self._map: Dict[str, Optional[int]] = {}       # jellyfin user id -> Seerr id (None: refused admin)
        self._map_at = float("-inf")

    def __repr__(self) -> str:
        return "SeerrRequests(<redacted>)"

    # ---- members ---------------------------------------------------------------------------
    def user_for(self, jellyfin_user_id: Any) -> Tuple[str, Optional[int]]:
        """("ok", seerr id) | ("not_linked", None) | ("unavailable", None) for a member's Jellyfin user id."""
        key = _hex32(jellyfin_user_id)
        if key is None:
            return "not_linked", None
        with self._map_lock:
            age = self._clock.now() - self._map_at
            if age > MAP_TTL or (key not in self._map and age > MISS_TTL):
                fresh = self._read_users()
                if fresh is None:
                    if age > MAP_TTL:
                        return "unavailable", None
                else:
                    self._map, self._map_at = fresh, self._clock.now()
            found = self._map.get(key)
        return ("ok", found) if found is not None else ("not_linked", None)

    def _read_users(self) -> Optional[Dict[str, Optional[int]]]:
        out: Dict[str, Optional[int]] = {}
        for page in range(USER_PAGES):
            body = self._call("GET", "/api/v1/user", {"take": str(USER_PAGE), "skip": str(page * USER_PAGE)})
            results = body.get("results") if isinstance(body, dict) else None
            if not isinstance(results, list):
                if body is not None:
                    self._fail("malformed")
                return None
            for user in results:
                if not isinstance(user, dict):
                    continue
                uid, perms, jf = user.get("id"), user.get("permissions"), _hex32(user.get("jellyfinUserId"))
                if jf is None or not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
                    continue
                admin = uid == 1 or not isinstance(perms, int) or bool(perms & ADMIN_BITS)
                out[jf] = None if admin or jf in out else uid     # a duplicate Jellyfin id is refused too
            if len(results) < USER_PAGE:
                return out
        return out

    # ---- the calls -------------------------------------------------------------------------
    def search(self, seerr_id: int, term: Any) -> Tuple[str, Tuple[WatchOffer, ...]]:
        text = clean_term(term)
        if text is None:
            return "invalid", ()
        body = self._call("GET", "/api/v1/search", {"query": text, "page": "1"}, act_as=seerr_id)
        if body is None:
            return "unavailable", ()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            self._fail("malformed")
            return "unavailable", ()
        offers, seen = [], set()
        for item in results[:SEARCH_LIMIT * 2]:
            offer = _offer(item)
            if offer is not None and (offer.media_type, offer.tmdb_id) not in seen:
                seen.add((offer.media_type, offer.tmdb_id))
                offers.append(offer)
        offers = offers[:SEARCH_LIMIT]
        return ("ok" if offers else "empty"), tuple(offers)

    def create(self, seerr_id: Any, media_type: Any, tmdb_id: Any) -> Outcome:
        """One request, as the member. A show asks for every season. Never retried: a timeout is UNAVAILABLE, and a
        second attempt is answered by Seerr's own duplicate check (DUPLICATE)."""
        if (not isinstance(seerr_id, int) or isinstance(seerr_id, bool) or seerr_id <= 1
                or media_type not in MEDIA_TYPES or not isinstance(tmdb_id, int) or not 0 < tmdb_id < 10**9):
            return Outcome.REFUSED
        payload: Dict[str, Any] = {"mediaType": media_type, "mediaId": tmdb_id, "is4k": False}
        if media_type == "tv":
            payload["seasons"] = "all"
        try:
            self._send("POST", "/api/v1/request", None, json.dumps(payload).encode("ascii"), seerr_id)
        except _Answered as answer:
            if answer.outcome is _Raw.OK:
                approved = isinstance(answer.body, dict) and answer.body.get("status") != 1
                return Outcome.CREATED if approved else Outcome.AWAITING
            return {_Raw.CONFLICT: Outcome.DUPLICATE, _Raw.REFUSED: Outcome.REFUSED,
                    _Raw.NOTHING: Outcome.REFUSED}.get(answer.outcome, Outcome.UNAVAILABLE)
        return Outcome.UNAVAILABLE

    # ---- internals -------------------------------------------------------------------------
    def _call(self, method: str, path: str, query, act_as: Optional[int] = None) -> Optional[Any]:
        try:
            self._send(method, path, query, None, act_as)
        except _Answered as answer:
            return answer.body if answer.outcome is _Raw.OK else None
        return None

    def _send(self, method, path, query, json_body: Optional[bytes], act_as: Optional[int]) -> None:
        allowed = ROUTES.get((method, path))
        if allowed is None or not set(query or {}) <= allowed:
            raise ForbiddenCall(f"{method} {path}")
        if json_body is not None and len(json_body) > MAX_REQUEST_BODY:
            raise ForbiddenCall("body")
        if path != "/api/v1/user" and (not isinstance(act_as, int) or act_as <= 1):
            raise ForbiddenCall("as whom")              # search and request are ALWAYS sent as a member
        token = self.breaker.acquire()
        if token is None:
            return
        kw: Dict[str, Any] = {}
        if json_body is not None:
            kw["json_body"] = json_body
        if act_as is not None:
            kw["act_as"] = str(act_as)
        try:
            resp = self._transport.request(method, path, query, self._timeout, MAX_JSON_BYTES, **kw)
        except UpstreamNotFound as exc:
            log_failure(SERVICE, exc)
            self.breaker.failure("route", token)
            raise _Answered(_Raw.FAILED) from None
        except UpstreamAuthError as exc:
            # 403 on a request is Seerr's quota or permission answer for the MEMBER; elsewhere it is the key.
            if method == "POST" and exc.status == 403:
                self.breaker.neutral(token)
                raise _Answered(_Raw.REFUSED) from None
            log_failure(SERVICE, exc)
            self.breaker.failure("auth", token)
            raise _Answered(_Raw.FAILED) from None
        except UpstreamHTTPError as exc:
            if method == "POST" and exc.status == 409:
                self.breaker.neutral(token)
                raise _Answered(_Raw.CONFLICT) from None
            log_failure(SERVICE, exc)
            self.breaker.failure(type(exc).__name__, token)
            raise _Answered(_Raw.FAILED) from None
        except Exception as exc:                  # noqa: BLE001: every transport failure is one outcome
            err = coerce(exc) or UpstreamError()
            log_failure(SERVICE, err)
            self.breaker.failure(type(err).__name__, token)
            raise _Answered(_Raw.FAILED) from None
        status = getattr(resp, "status", 0)
        if method == "POST" and status == 202:
            self.breaker.success(token)
            raise _Answered(_Raw.NOTHING)
        if status not in (200, 201):
            self.breaker.failure("status", token)
            raise _Answered(_Raw.FAILED)
        try:
            body = json.loads(resp.body.decode("utf-8")) if resp.body else {}
        except (ValueError, UnicodeDecodeError, RecursionError):
            self.breaker.failure("malformed", token)
            raise _Answered(_Raw.FAILED) from None
        self.breaker.success(token)
        raise _Answered(_Raw.OK, body)

    def _fail(self, error_class: str) -> None:
        token = self.breaker.acquire(trial=False)
        if token is not None:
            self.breaker.failure(error_class, token)


class _Raw(enum.Enum):
    OK = 1
    CONFLICT = 2
    REFUSED = 3
    NOTHING = 4
    FAILED = 5


class _Answered(Exception):
    def __init__(self, outcome: _Raw, body: Any = None):
        super().__init__(outcome.name)
        self.outcome = outcome
        self.body = body
