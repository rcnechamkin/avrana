"""Comic requests through Omnibus (the Avrana fork, `avrana/v1.4.4`), on the member's behalf.

Status: proposed, not deployed. Standard library only. Design: docs/design/REQUEST-FORKS-PLAN.md (Omnibus) and
HOME-APP.md section 5e.

Credential: ONE Omnibus API key that an administrator minted and switched to "on behalf" (the fork's
`ApiKey.allowOnBehalf`). With it, and only together with `X-Omnibus-User: <member>`, the fork accepts exactly
`GET /api/search` and `GET`/`POST /api/request`; everything else still needs a session. The fork refuses to act as an
administrator and applies the member's own Request permission and auto-approve; each use is in Omnibus's audit log.

Rules this module keeps:

  * A fixed allow-list (`ROUTES`), and every call names the member (`act_as_name`); a call without one is refused
    here before anything is sent.
  * Only whole series are asked for (`type: volume`, ComicVine ids only), with the fields Omnibus's own search
    returned: name, year, publisher. Upstream URLs, covers and descriptions are dropped.
  * "My requests": Omnibus creates one request per issue, so the member's list is grouped by series here and said
    as counts ("12 of 20 issues arrived"). The fork's key cannot cancel; nothing here deletes.
  * Failures map to a few fixed outcomes; nothing upstream sends is shown or logged.
"""
from __future__ import annotations

import enum
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..resilience import (MAX_JSON_BYTES, MAX_REQUEST_BODY, CircuitBreaker, Clock, SystemClock, UpstreamAuthError,
                          UpstreamError, UpstreamHTTPError, UpstreamNotFound, coerce, log_failure)

SERVICE = "omnibus"
SEARCH_LIMIT = 12
MIN_TERM, MAX_TERM = 2, 100
MAX_NAME, MAX_PUBLISHER = 300, 120
MINE_LIMIT = 30                                  # series shown on My requests
MINE_ROWS = 2000                                 # issue requests read, at most
USERNAME = re.compile(r"[A-Za-z0-9._@+-]{1,150}")
ROUTES = {("GET", "/api/search"): frozenset({"q", "page"}),
          ("GET", "/api/request"): frozenset(),
          ("POST", "/api/request"): frozenset()}
# Omnibus's own words for a successful volume request that waits for an administrator (api/request/route.ts).
AWAITING_MESSAGE = "Sent for Admin approval."


class Outcome(enum.Enum):
    CREATED = "created"            # queued: Omnibus is looking for the issues
    AWAITING = "awaiting"          # waits for an administrator's approval
    REFUSED = "refused"            # 400 or 403: no Request permission, manga switched off, unresolvable series
    NOT_LINKED = "not_linked"      # 401: no Omnibus account for this member (or the key is not on-behalf)
    UNAVAILABLE = "unavailable"


class SeriesState(enum.Enum):
    AWAITING = "awaiting"          # any issue waits for approval
    COMING = "coming"              # being looked for or downloaded
    WAITING_RELEASE = "waiting_release"   # nothing left but issues not out yet
    STUCK = "stuck"                # stalled or needs a manual download; the owner sees it
    ARRIVED = "arrived"            # every issue imported


_COMING = {"PENDING", "DOWNLOADING", "QUEUED", "SEARCHING"}
_RELEASE = {"UNRELEASED", "AWAITING_RELEASE"}
_STUCK = {"STALLED", "MANUAL_DDL", "FAILED", "ERROR"}


@dataclass(frozen=True)
class ComicOffer:
    cv_id: int
    name: str
    year: Optional[int]
    publisher: str
    issues: int


@dataclass(frozen=True)
class ComicSeriesRequest:
    volume_id: str
    name: str
    state: SeriesState
    arrived: int                   # issues imported
    total: int                     # issues asked for
    asked_on: str                  # the first ask, "2026-10-28" or ""
    changed_on: str = ""           # the latest issue that arrived


class ForbiddenCall(Exception):
    """A call outside ROUTES, or without a member: a programming error, never sent."""


def clean_term(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    text = " ".join(unicodedata.normalize("NFC", raw).split())
    if not MIN_TERM <= len(text) <= MAX_TERM or not text.isprintable():
        return None
    return text


def member_name(raw: Any) -> Optional[str]:
    """The principal's username as Omnibus compares it (exact), or None if it cannot be one."""
    return raw if isinstance(raw, str) and USERNAME.fullmatch(raw) else None


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:limit] if text.isprintable() else ""


def _int(value: Any, top: int) -> Optional[int]:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value < top else None


def _offer(item: Any) -> Optional[ComicOffer]:
    if not isinstance(item, dict) or item.get("metadataSource", "COMICVINE") != "COMICVINE":
        return None
    cv, name = _int(item.get("id"), 10**10), _text(item.get("name"), MAX_NAME)
    if cv is None or not name:
        return None
    count = _int(item.get("count"), 100000) or 0
    return ComicOffer(cv, name, _int(item.get("year"), 3000), _text(item.get("publisher"), MAX_PUBLISHER), count)


_ISSUE_TAIL = re.compile(r"\s*(?:#|issue\s*#?)\s*-?\d[\d.]*.*$", re.I)


def _series(rows) -> Tuple[ComicSeriesRequest, ...]:
    groups: Dict[str, dict] = {}
    for item in rows[:MINE_ROWS]:
        if not isinstance(item, dict) or item.get("metadataSource", "COMICVINE") != "COMICVINE":
            continue
        vol, status = item.get("volumeId"), item.get("status")
        if not isinstance(vol, str) or not vol.isdigit() or len(vol) > 10 or not isinstance(status, str):
            continue
        name = _ISSUE_TAIL.sub("", _text(item.get("seriesName"), MAX_NAME)).strip()
        name = re.sub(r"\s*\(\d{4}\)$", "", name).strip()
        created = item.get("createdAt")
        day = created[:10] if isinstance(created, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", created[:10]) else ""
        g = groups.setdefault(vol, {"name": "", "statuses": [], "first": day, "arrived": ""})
        g["name"] = g["name"] or name
        g["statuses"].append(status)
        updated = item.get("updatedAt")
        if status == "IMPORTED" and isinstance(updated, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated[:10]):
            g["arrived"] = max(g["arrived"], updated[:10])
        if day and (not g["first"] or day < g["first"]):
            g["first"] = day
    out = []
    for vol, g in groups.items():
        statuses = g["statuses"]
        arrived = sum(1 for s in statuses if s == "IMPORTED")
        if "PENDING_APPROVAL" in statuses:
            state = SeriesState.AWAITING
        elif any(s in _STUCK for s in statuses):
            state = SeriesState.STUCK
        elif any(s in _COMING for s in statuses):
            state = SeriesState.COMING
        elif arrived == len(statuses):
            state = SeriesState.ARRIVED
        else:
            state = SeriesState.WAITING_RELEASE
        out.append(ComicSeriesRequest(vol, g["name"] or "A comic series", state, arrived, len(statuses), g["first"],
                                      g["arrived"]))
    out.sort(key=lambda r: r.asked_on, reverse=True)
    return tuple(out[:MINE_LIMIT])


class OmnibusRequests:
    """Search Omnibus's metadata as a member, ask for a series as that member, and list their requests."""

    service = SERVICE

    def __init__(self, transport, timeout: float = 4.0, clock: Optional[Clock] = None):
        self._transport = transport
        self._timeout = float(timeout)
        self.breaker = CircuitBreaker(clock or SystemClock())

    def __repr__(self) -> str:
        return "OmnibusRequests(<redacted>)"

    def search(self, username: Any, term: Any) -> Tuple[str, Tuple[ComicOffer, ...]]:
        """("ok", offers) | ("empty", ()) | ("invalid", ()) | ("not_linked", ()) | ("unavailable", ())."""
        name, text = member_name(username), clean_term(term)
        if text is None:
            return "invalid", ()
        if name is None:
            return "not_linked", ()
        outcome, body = self._exchange("GET", "/api/search", {"q": text, "page": "1"}, None, name)
        if outcome is not Outcome.CREATED:
            return ("not_linked" if outcome is Outcome.NOT_LINKED else "unavailable"), ()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            self._fail("malformed")
            return "unavailable", ()
        offers, seen = [], set()
        for item in results[:SEARCH_LIMIT * 3]:
            offer = _offer(item)
            if offer is not None and offer.cv_id not in seen:
                seen.add(offer.cv_id)
                offers.append(offer)
        offers = offers[:SEARCH_LIMIT]
        return ("ok" if offers else "empty"), tuple(offers)

    def create(self, username: Any, cv_id: Any, name: Any, year: Any, publisher: Any) -> Outcome:
        """Ask for a whole series as the member. Never retried (Omnibus does not create a second request for an issue
        already asked for, so a resend is harmless, but a timeout is still UNAVAILABLE)."""
        who, cv = member_name(username), _int(cv_id, 10**10)
        title = _text(name, MAX_NAME)
        if who is None or cv is None or not title:
            return Outcome.REFUSED
        payload: Dict[str, Any] = {"type": "volume", "cvId": cv, "name": title, "metadataSource": "COMICVINE"}
        if _int(year, 3000):
            payload["year"] = str(_int(year, 3000))
        if _text(publisher, MAX_PUBLISHER):
            payload["publisher"] = _text(publisher, MAX_PUBLISHER)
        outcome, body = self._exchange("POST", "/api/request", None,
                                       json.dumps(payload, ensure_ascii=True).encode("ascii"), who)
        if outcome is Outcome.CREATED:
            message = body.get("message") if isinstance(body, dict) else None
            if not (isinstance(body, dict) and body.get("success") is True):
                return Outcome.UNAVAILABLE
            return Outcome.AWAITING if message == AWAITING_MESSAGE else Outcome.CREATED
        return outcome

    def mine(self, username: Any) -> Tuple[str, Tuple[ComicSeriesRequest, ...]]:
        """("ok", series) | ("empty", ()) | ("not_linked", ()) | ("unavailable", ()): the member's own requests
        (the fork lists only the named member's), grouped by series."""
        who = member_name(username)
        if who is None:
            return "not_linked", ()
        outcome, body = self._exchange("GET", "/api/request", None, None, who)
        if outcome is not Outcome.CREATED:
            return ("not_linked" if outcome is Outcome.NOT_LINKED else "unavailable"), ()
        if not isinstance(body, list):
            self._fail("malformed")
            return "unavailable", ()
        rows = _series(body)
        return ("ok" if rows else "empty"), rows

    # ---- internals -------------------------------------------------------------------------
    def _exchange(self, method: str, path: str, query, json_body: Optional[bytes], who: str):
        """(Outcome, body): CREATED carries the parsed 2xx body."""
        allowed = ROUTES.get((method, path))
        if allowed is None or not set(query or {}) <= allowed:
            raise ForbiddenCall(f"{method} {path}")
        if member_name(who) is None:
            raise ForbiddenCall("as whom")
        if json_body is not None and len(json_body) > MAX_REQUEST_BODY:
            raise ForbiddenCall("body")
        token = self.breaker.acquire()
        if token is None:
            return Outcome.UNAVAILABLE, None
        kw: Dict[str, Any] = {"act_as_name": who}
        if json_body is not None:
            kw["json_body"] = json_body
        try:
            resp = self._transport.request(method, path, query, self._timeout, MAX_JSON_BYTES, **kw)
        except UpstreamAuthError as exc:
            if exc.status == 401:                  # the fork: no such member, an admin, or a key not on-behalf
                log_failure(SERVICE, exc)
                self.breaker.neutral(token)
                return Outcome.NOT_LINKED, None
            self.breaker.neutral(token)            # 403: the member's own permission (Request, manga switch)
            return Outcome.REFUSED, None
        except UpstreamNotFound as exc:
            log_failure(SERVICE, exc)
            self.breaker.failure("route", token)
            return Outcome.UNAVAILABLE, None
        except UpstreamHTTPError as exc:
            if method == "POST" and exc.status == 400:
                self.breaker.neutral(token)
                return Outcome.REFUSED, None
            log_failure(SERVICE, exc)
            self.breaker.failure(type(exc).__name__, token)
            return Outcome.UNAVAILABLE, None
        except Exception as exc:                  # noqa: BLE001: every transport failure is one outcome
            err = coerce(exc) or UpstreamError()
            log_failure(SERVICE, err)
            self.breaker.failure(type(err).__name__, token)
            return Outcome.UNAVAILABLE, None
        if getattr(resp, "status", 0) != 200:
            self.breaker.failure("status", token)
            return Outcome.UNAVAILABLE, None
        try:
            body = json.loads(resp.body.decode("utf-8")) if resp.body else {}
        except (ValueError, UnicodeDecodeError, RecursionError):
            self.breaker.failure("malformed", token)
            return Outcome.UNAVAILABLE, None
        self.breaker.success(token)
        return Outcome.CREATED, body

    def _fail(self, error_class: str) -> None:
        token = self.breaker.acquire(trial=False)
        if token is not None:
            self.breaker.failure(error_class, token)
