"""Film and TV requests through Seerr (v3.4.1, `/api/v1`), on the member's behalf.

Status: proposed, not deployed. Standard library only. Design: docs/design/UNIVERSAL-SEARCH-AND-REQUESTS.md (Seerr)
and REQUEST-FORKS-PLAN.md (why the global key is accepted for now, and the fork that replaces it).

Credential: Seerr's ONE global API key. It is full Seerr admin, so the rules here are strict and settings.py accepts
it in real mode only with verified identity (`HOME_IDENTITY_MODE=jwt_required`):

  * A fixed allow-list (`ROUTES`): `GET /api/v1/search`, `GET /api/v1/user` (paged, to map members),
    `POST /api/v1/request`, and for "My requests" `GET /api/v1/request` (the member's own, `requestedBy`),
    `GET /api/v1/movie/<id>` / `GET /api/v1/tv/<id>` (titles only) and `DELETE /api/v1/request/<id>`. Nothing under
    `/settings`, no approvals or status changes, no user edits.
  * A cancel is allowed only for a request in the member's OWN list that is still waiting for approval: Seerr lets
    any non-manager delete any PENDING request, so Home checks the owner itself before sending the delete.
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
import re
import threading
import unicodedata
from collections import OrderedDict
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
MAP_DEADLINE = 6.0                              # a user-map refresh that takes longer is abandoned (never partial)
# Seerr permission bits that make a user an administrator of some kind (server/lib/permissions.ts).
ADMIN_BITS = 2 | 4 | 8 | 16                     # ADMIN, MANAGE_SETTINGS, MANAGE_USERS, MANAGE_REQUESTS
ROUTES = {("GET", "/api/v1/search"): frozenset({"query", "page"}),
          ("GET", "/api/v1/user"): frozenset({"take", "skip"}),
          ("POST", "/api/v1/request"): frozenset(),
          ("GET", "/api/v1/request"): frozenset({"take", "skip", "sort", "requestedBy"}),
          ("GET", "/api/v1/movie/<id>"): frozenset(),
          ("GET", "/api/v1/tv/<id>"): frozenset(),
          ("DELETE", "/api/v1/request/<id>"): frozenset(),
          ("POST", "/api/v1/user/import-from-jellyfin"): frozenset()}
ID_PATH = re.compile(r"/api/v1/(movie|tv|request)/([0-9]{1,9})")
MEDIA_TYPES = ("movie", "tv")
MINE_LIMIT = 30                                 # the member's newest requests shown
TITLE_TTL, TITLE_SIZE = 86400.0, 2000           # titles change rarely; bounded per process
TITLE_BUDGET = 3.0                              # seconds spent looking titles up per page; the rest wait a reload


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


MAX_SEASONS = 60                                # seasons listed for one show, at most


@dataclass(frozen=True)
class Season:
    number: int
    episodes: int
    state: MediaState              # NONE (may be asked for) | ASKED | PARTIAL | AVAILABLE | BLOCKED


@dataclass(frozen=True)
class ShowDetail:
    tmdb_id: int
    title: str
    year: Optional[int]
    seasons: Tuple[Season, ...]


class RequestState(enum.Enum):
    """A member's own request, reduced to what they are told (request status plus the media's library status)."""
    AWAITING = "awaiting"          # request 1 PENDING: waits for an administrator's approval
    COMING = "coming"              # approved, not in the library yet
    PARTIAL = "partial"            # some of a show is in the library
    ARRIVED = "arrived"            # in the library (or request 5 COMPLETED)
    DECLINED = "declined"          # request 3
    FAILED = "failed"              # request 4: Seerr could not hand it on; the owner sees it


@dataclass(frozen=True)
class WatchRequest:
    request_id: int
    media_type: str
    tmdb_id: int
    title: str                     # "" when the title could not be looked up in time
    year: Optional[int]
    state: RequestState
    asked_on: str                  # "2026-10-28" or ""
    jellyfin_id: Optional[str]
    cancellable: bool              # the member's own, still waiting for approval


class CancelOutcome(enum.Enum):
    CANCELLED = "cancelled"
    NOT_ALLOWED = "not_allowed"    # not the member's, gone, or no longer waiting for approval
    UNAVAILABLE = "unavailable"


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


def _state(request_status: Any, media_status: Any) -> Optional[RequestState]:
    if request_status == 1:
        return RequestState.AWAITING
    if request_status == 3:
        return RequestState.DECLINED
    if request_status == 4:
        return RequestState.FAILED
    if request_status not in (2, 5):
        return None
    if media_status == 5 or request_status == 5:
        return RequestState.ARRIVED
    return RequestState.PARTIAL if media_status == 4 else RequestState.COMING


def _mine_row(item: Any, seerr_id: int) -> Optional[tuple]:
    """(request id, media type, tmdb id, state, asked on, jellyfin id) for a request OF THIS MEMBER, else None."""
    if not isinstance(item, dict):
        return None
    by, media = item.get("requestedBy"), item.get("media")
    rid = item.get("id")
    if (not isinstance(by, dict) or by.get("id") != seerr_id or not isinstance(media, dict)
            or not isinstance(rid, int) or isinstance(rid, bool) or not 0 < rid < 10**9):
        return None
    mtype, tmdb = media.get("mediaType") or item.get("type"), media.get("tmdbId")
    if mtype not in MEDIA_TYPES or not isinstance(tmdb, int) or isinstance(tmdb, bool) or not 0 < tmdb < 10**9:
        return None
    state = _state(item.get("status"), media.get("status"))
    if state is None:
        return None
    created = item.get("createdAt")
    asked_on = created[:10] if isinstance(created, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", created[:10]) else ""
    return rid, mtype, tmdb, state, asked_on, _hex32(media.get("jellyfinMediaId"))


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
        self._titles_lock = threading.Lock()
        self._titles: "OrderedDict[tuple, tuple]" = OrderedDict()   # (type, tmdb) -> (at, title, year)

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
        started = self._clock.now()
        for page in range(USER_PAGES):
            if page and self._clock.now() - started > MAP_DEADLINE:
                self._fail("map_deadline")
                return None
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

    def show(self, seerr_id: Any, tmdb_id: Any) -> Tuple[str, Optional[ShowDetail]]:
        """("ok", detail) | ("unavailable", None): one show's seasons and what Seerr knows of each, read AS the member
        (specials, season 0, are left out, as Seerr's own "all seasons" does)."""
        if (not isinstance(seerr_id, int) or isinstance(seerr_id, bool) or seerr_id <= 1
                or not isinstance(tmdb_id, int) or isinstance(tmdb_id, bool) or not 0 < tmdb_id < 10**9):
            return "unavailable", None
        body = self._call("GET", f"/api/v1/tv/{tmdb_id}", None, act_as=seerr_id)
        if not isinstance(body, dict):
            return "unavailable", None
        title = _text(body.get("name"), MAX_TITLE)
        raw = body.get("seasons")
        if not title or not isinstance(raw, list):
            self._fail("malformed")
            return "unavailable", None
        info = body.get("mediaInfo") if isinstance(body.get("mediaInfo"), dict) else {}
        known = {}
        for s in info.get("seasons") or ():
            if isinstance(s, dict) and isinstance(s.get("seasonNumber"), int) and isinstance(s.get("status"), int):
                known[s["seasonNumber"]] = s["status"]
        seasons = []
        for s in raw[:MAX_SEASONS + 1]:
            number = s.get("seasonNumber") if isinstance(s, dict) else None
            if not isinstance(number, int) or isinstance(number, bool) or not 0 < number <= MAX_SEASONS:
                continue
            episodes = s.get("episodeCount")
            episodes = episodes if isinstance(episodes, int) and not isinstance(episodes, bool) and episodes >= 0 else 0
            status = known.get(number)
            state = _STATUS.get(status, MediaState.BLOCKED if isinstance(status, int) and status > 5 else MediaState.NONE)
            seasons.append(Season(number, episodes, state))
        date = body.get("firstAirDate")
        year = int(date[:4]) if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit() else None
        seasons.sort(key=lambda s: s.number)
        with self._titles_lock:
            self._titles[("tv", tmdb_id)] = (self._clock.now(), title, year)
        return "ok", ShowDetail(tmdb_id, title, year, tuple(seasons))

    def create(self, seerr_id: Any, media_type: Any, tmdb_id: Any, seasons: Optional[Tuple[int, ...]] = None) -> Outcome:
        """One request, as the member. A show asks for every season, or for `seasons` when the member chose them.
        Never retried: a timeout is UNAVAILABLE, and a second attempt is answered by Seerr's own duplicate check
        (DUPLICATE)."""
        if (not isinstance(seerr_id, int) or isinstance(seerr_id, bool) or seerr_id <= 1
                or media_type not in MEDIA_TYPES or not isinstance(tmdb_id, int) or not 0 < tmdb_id < 10**9):
            return Outcome.REFUSED
        if seasons is not None and (media_type != "tv" or not seasons or len(seasons) > MAX_SEASONS or not all(
                isinstance(n, int) and not isinstance(n, bool) and 0 < n <= MAX_SEASONS for n in seasons)):
            return Outcome.REFUSED
        payload: Dict[str, Any] = {"mediaType": media_type, "mediaId": tmdb_id, "is4k": False}
        if media_type == "tv":
            payload["seasons"] = sorted(set(seasons)) if seasons else "all"
        try:
            self._send("POST", "/api/v1/request", None, json.dumps(payload).encode("ascii"), seerr_id)
        except _Answered as answer:
            if answer.outcome is _Raw.OK:
                approved = isinstance(answer.body, dict) and answer.body.get("status") != 1
                return Outcome.CREATED if approved else Outcome.AWAITING
            return {_Raw.CONFLICT: Outcome.DUPLICATE, _Raw.REFUSED: Outcome.REFUSED,
                    _Raw.NOTHING: Outcome.REFUSED}.get(answer.outcome, Outcome.UNAVAILABLE)
        return Outcome.UNAVAILABLE

    # ---- accounts --------------------------------------------------------------------------
    def link(self, jellyfin_user_id: Any) -> Tuple[str, Optional[int]]:
        """Create the member's Seerr user from their Jellyfin account (HOME_SEERR_PROVISION=on), Seerr's own
        "Import Jellyfin users", then map them again. ("ok", seerr id) | ("not_linked", None) | ("unavailable",
        None). Seerr gives an imported user its default permissions; one that comes out an administrator is still
        refused by the map, as always. Called only after `user_for` said not_linked."""
        key = _hex32(jellyfin_user_id)
        if key is None:
            return "not_linked", None
        body = json.dumps({"jellyfinUserIds": [key]}).encode("ascii")
        try:
            self._send("POST", "/api/v1/user/import-from-jellyfin", None, body, None)
        except _Answered as answer:
            if answer.outcome is not _Raw.OK:
                return ("not_linked", None) if answer.outcome in (_Raw.REFUSED, _Raw.CONFLICT) else \
                    ("unavailable", None)
        else:
            return "unavailable", None
        with self._map_lock:
            self._map_at = float("-inf")                      # read the map again: the new user is in it
        return self.user_for(key)

    # ---- My requests -----------------------------------------------------------------------
    def mine(self, seerr_id: Any) -> Tuple[str, Tuple[WatchRequest, ...]]:
        """("ok", rows) | ("empty", ()) | ("unavailable", ()): the member's own requests, newest first, read AS the
        member and filtered to `requestedBy` = the member (rows of anyone else are dropped). Titles come from a
        per-process cache; at most TITLE_BUDGET seconds are spent looking up the rest."""
        if not isinstance(seerr_id, int) or isinstance(seerr_id, bool) or seerr_id <= 1:
            return "unavailable", ()
        body = self._call("GET", "/api/v1/request", {"take": str(MINE_LIMIT), "skip": "0", "sort": "added",
                                                     "requestedBy": str(seerr_id)}, act_as=seerr_id)
        if body is None:
            return "unavailable", ()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            self._fail("malformed")
            return "unavailable", ()
        rows = [r for r in (_mine_row(item, seerr_id) for item in results[:MINE_LIMIT]) if r is not None]
        started, out = self._clock.now(), []
        for rid, mtype, tmdb, state, asked_on, jf in rows:
            named = self._title(mtype, tmdb)
            if named is None and self._clock.now() - started < TITLE_BUDGET:
                named = self._look_up(seerr_id, mtype, tmdb)
            title, year = named or ("", None)
            out.append(WatchRequest(rid, mtype, tmdb, title, year, state, asked_on, jf, state is RequestState.AWAITING))
        return ("ok" if out else "empty"), tuple(out)

    def cancel(self, seerr_id: Any, request_id: Any) -> CancelOutcome:
        """Withdraw one of the member's own requests while it still waits for approval. The member's own list is
        read first (Seerr itself would let any member delete any pending request); never retried."""
        if (not isinstance(seerr_id, int) or isinstance(seerr_id, bool) or seerr_id <= 1
                or not isinstance(request_id, int) or isinstance(request_id, bool) or not 0 < request_id < 10**9):
            return CancelOutcome.NOT_ALLOWED
        state, rows = self.mine(seerr_id)
        if state == "unavailable":
            return CancelOutcome.UNAVAILABLE
        if not any(r.request_id == request_id and r.cancellable for r in rows):
            return CancelOutcome.NOT_ALLOWED
        try:
            self._send("DELETE", f"/api/v1/request/{request_id}", None, None, seerr_id)
        except _Answered as answer:
            if answer.outcome is _Raw.OK:
                return CancelOutcome.CANCELLED
            if answer.outcome is _Raw.REFUSED:
                return CancelOutcome.NOT_ALLOWED
        return CancelOutcome.UNAVAILABLE

    def _title(self, mtype: str, tmdb: int) -> Optional[tuple]:
        with self._titles_lock:
            hit = self._titles.get((mtype, tmdb))
            if hit is None or self._clock.now() - hit[0] > TITLE_TTL:
                return None
            return hit[1], hit[2]

    def _look_up(self, seerr_id: int, mtype: str, tmdb: int) -> Optional[tuple]:
        body = self._call("GET", f"/api/v1/{mtype}/{tmdb}", None, act_as=seerr_id)
        if not isinstance(body, dict):
            return None
        movie = mtype == "movie"
        title = _text(body.get("title" if movie else "name"), MAX_TITLE)
        if not title:
            return None
        date = body.get("releaseDate" if movie else "firstAirDate")
        year = int(date[:4]) if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit() else None
        with self._titles_lock:
            self._titles[(mtype, tmdb)] = (self._clock.now(), title, year)
            self._titles.move_to_end((mtype, tmdb))
            while len(self._titles) > TITLE_SIZE:
                self._titles.popitem(last=False)
        return title, year

    # ---- internals -------------------------------------------------------------------------
    def _call(self, method: str, path: str, query, act_as: Optional[int] = None) -> Optional[Any]:
        try:
            self._send(method, path, query, None, act_as)
        except _Answered as answer:
            return answer.body if answer.outcome is _Raw.OK else None
        return None

    def _send(self, method, path, query, json_body: Optional[bytes], act_as: Optional[int]) -> None:
        m = ID_PATH.fullmatch(path)
        template = f"/api/v1/{m.group(1)}/<id>" if m else path
        allowed = ROUTES.get((method, template))
        if allowed is None or not set(query or {}) <= allowed:
            raise ForbiddenCall(f"{method} {template}")
        if json_body is not None and len(json_body) > MAX_REQUEST_BODY:
            raise ForbiddenCall("body")
        if path not in ("/api/v1/user", "/api/v1/user/import-from-jellyfin") and \
                (not isinstance(act_as, int) or act_as <= 1):
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
            if m:                                 # one request or title that is gone: an answer, not route drift
                self.breaker.neutral(token)
                raise _Answered(_Raw.REFUSED if method == "DELETE" else _Raw.FAILED) from None
            log_failure(SERVICE, exc)
            self.breaker.failure("route", token)
            raise _Answered(_Raw.FAILED) from None
        except UpstreamAuthError as exc:
            # 403 on a request (or 401/403 on a delete) is Seerr's answer for the MEMBER; elsewhere it is the key.
            if (method == "POST" and exc.status == 403) or method == "DELETE":
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
        if method == "DELETE" and status == 204:
            self.breaker.success(token)
            raise _Answered(_Raw.OK, {})
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
