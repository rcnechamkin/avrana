"""Ebook and audiobook requests through Shelfarr (2026.10.19.1, `/api/v1`), on the member's behalf.

Status: proposed, not deployed. Standard library only.

Credential: ONE Shelfarr token held by Home, minted from an admin profile with exactly the scopes
`search:read requests:write requests:admin` (`requests:admin` is what lets a token name another user; Shelfarr
2026.10.19.1 `requests_controller.rb` `find_user`). It cannot change settings or create users. Members never mint
tokens (Media 2.0: no manual member keys).

Rules this module keeps:

  * Exactly two upstream calls exist, on a fixed allow-list (`ROUTES`): `GET /api/v1/search` and
    `POST /api/v1/requests`. Nothing else can be sent: no request listing (an admin-scoped token would see
    everyone's), no cancel, retry, grab, users or settings.
  * The member is named by `username` only, taken from the verified principal by the caller and checked here
    against Shelfarr's username shape (lower case, as Shelfarr compares). A username Shelfarr does not know is a
    404 ("User not found"): the member has never signed in to Shelfarr, which is `NOT_LINKED`, never an error.
  * Search results are parsed strictly: a `work_id` of the shape `provider:id`, bounded text, booleans for the
    formats. Upstream URLs (covers, source pages) are dropped: the browser never loads anything from elsewhere.
  * Failures map to a few fixed outcomes; nothing upstream sends is shown or logged.
  * One circuit breaker per process, as for the adapters: a failing Shelfarr fails fast for every member.
"""
from __future__ import annotations

import enum
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .owned import KEY as OWNED_KEY, isbn13, title_key
from ..resilience import (MAX_JSON_BYTES, MAX_REQUEST_BODY, CircuitBreaker, Clock, SystemClock, UpstreamAuthError,
                          UpstreamError, UpstreamHTTPError, UpstreamNotFound, coerce, log_failure)

SERVICE = "shelfarr"
# What each format needs from the member: the library group it fills (contract.REQUIRED_GROUP's names).
FORMAT_GROUP = {"ebook": "avrana-books", "audiobook": "avrana-audiobooks"}
FORMAT_ORDER = ("ebook", "audiobook")
SEARCH_LIMIT = 10
MIN_TERM, MAX_TERM = 2, 100
MAX_TITLE, MAX_AUTHOR, MAX_SERIES = 300, 200, 200
MAX_KEYS = 20                      # sources and editions read per result
WORK_ID = re.compile(r"[a-z][a-z_]{1,23}:[A-Za-z0-9][A-Za-z0-9._:-]{0,95}")
USERNAME = re.compile(r"[a-z0-9][a-z0-9._@+-]{0,149}")
ROUTES = {("GET", "/api/v1/search"): frozenset({"q", "limit", "content_kind"}),
          ("POST", "/api/v1/requests"): frozenset()}


class Outcome(enum.Enum):
    CREATED = "created"            # 201: the request exists in Shelfarr
    QUEUED = "queued"              # 202: Shelfarr accepted it and will process it shortly
    REFUSED = "refused"            # 422: Shelfarr would not take it (already asked for, already owned, invalid)
    NOT_LINKED = "not_linked"      # 404: no active Shelfarr user with the member's username
    UNAVAILABLE = "unavailable"    # timeout, unreachable, 5xx, malformed, breaker open, or a credential problem


@dataclass(frozen=True)
class BookOffer:
    work_id: str
    title: str
    author: str
    year: Optional[int]
    series: str
    formats: Tuple[str, ...]       # subset of FORMAT_ORDER the upstream says exist
    keys: Tuple[str, ...] = ()     # exact catalogue keys ("hardcover:123", "isbn:978…") for owned.OwnedIndex
    title_key: Optional[str] = None   # folded title|surname, the LIKELY tier only


class ForbiddenCall(Exception):
    """A call outside ROUTES: a programming error, never sent."""


def clean_term(raw: Any) -> Optional[str]:
    """The search term, or None when unusable: printable text, collapsed spaces, MIN_TERM..MAX_TERM characters."""
    if not isinstance(raw, str):
        return None
    text = " ".join(unicodedata.normalize("NFC", raw).split())
    if not MIN_TERM <= len(text) <= MAX_TERM or not text.isprintable():
        return None
    return text


def member_username(raw: Any) -> Optional[str]:
    """Shelfarr's form of the principal's username (Shelfarr lower-cases on lookup), or None if it cannot be one."""
    if not isinstance(raw, str):
        return None
    name = raw.strip().lower()
    return name if USERNAME.fullmatch(name) else None


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text[:limit] if text.isprintable() else ""


def _offer(item: Any) -> Optional[BookOffer]:
    if not isinstance(item, dict):
        return None
    work_id, title = item.get("work_id"), _text(item.get("title"), MAX_TITLE)
    if not isinstance(work_id, str) or not WORK_ID.fullmatch(work_id) or not title:
        return None
    flags = {"ebook": item.get("has_ebook"), "audiobook": item.get("has_audiobook")}
    formats = tuple(f for f in FORMAT_ORDER if flags[f] is True)
    year = item.get("year")
    year = year if isinstance(year, int) and not isinstance(year, bool) and 0 < year < 3000 else None
    author = _text(item.get("author"), MAX_AUTHOR)
    return BookOffer(work_id, title, author, year, _text(item.get("series_name"), MAX_SERIES), formats,
                     _keys(work_id, item), title_key(title, author))


def _keys(work_id: str, item: dict) -> Tuple[str, ...]:
    """The result's own work id, its other providers' work ids and its editions' ISBN-13s, as index keys. Only the
    shapes the index uses survive (owned.KEY); everything else is ignored."""
    found = [work_id]
    sources = item.get("sources")
    for source in sources[:MAX_KEYS] if isinstance(sources, list) else ():
        if isinstance(source, dict) and isinstance(source.get("work_id"), str):
            found.append(source["work_id"])
    editions = item.get("editions")
    for edition in editions[:MAX_KEYS] if isinstance(editions, list) else ():
        if isinstance(edition, dict):
            for field in ("isbn_13", "isbn_10"):
                number = isbn13(edition.get(field))
                if number:
                    found.append("isbn:" + number)
            asin = edition.get("asin")
            if isinstance(asin, str) and len(asin) == 10 and asin.isalnum():
                found.append("asin:" + asin.upper())
    return tuple(dict.fromkeys(k for k in found if OWNED_KEY.fullmatch(k)))


class ShelfarrRequests:
    """Search Shelfarr's metadata providers and create a request for a named member. Thread-safe like the adapters
    (no per-call state on the instance besides the breaker, which locks itself)."""

    service = SERVICE

    def __init__(self, transport, timeout: float = 2.0, clock: Optional[Clock] = None):
        self._transport = transport
        self._timeout = float(timeout)
        self.breaker = CircuitBreaker(clock or SystemClock())

    def __repr__(self) -> str:
        return "ShelfarrRequests(<redacted>)"

    # ---- the two calls ---------------------------------------------------------------------
    def search(self, term: Any) -> Tuple[str, Tuple[BookOffer, ...]]:
        """("ok", offers) | ("empty", ()) | ("invalid", ()) | ("unavailable", ()). Book content only (Shelfarr's
        `content_kind=book`): graphic novels and comics go to their own request service."""
        text = clean_term(term)
        if text is None:
            return "invalid", ()
        body = self._call("GET", "/api/v1/search", {"q": text, "limit": str(SEARCH_LIMIT), "content_kind": "book"})
        if body is None:
            return "unavailable", ()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            self._fail("malformed")
            return "unavailable", ()
        offers, seen = [], set()
        for item in results[:SEARCH_LIMIT]:
            offer = _offer(item)
            if offer is not None and offer.work_id not in seen:
                seen.add(offer.work_id)
                offers.append(offer)
        return ("ok" if offers else "empty"), tuple(offers)

    def create(self, username: Any, work_id: Any, book_type: Any, title: Any, author: Any) -> Outcome:
        """Ask for one format of one work for the member `username` (already the verified principal's, see
        `member_username`). Never retried: a timeout is UNAVAILABLE even though Shelfarr may have created it, and
        a second attempt is answered by Shelfarr's own duplicate check (REFUSED)."""
        name = member_username(username)
        if (name is None or not isinstance(work_id, str) or not WORK_ID.fullmatch(work_id)
                or book_type not in FORMAT_GROUP or not _text(title, MAX_TITLE)):
            return Outcome.REFUSED
        payload = {"work_id": work_id, "book_type": book_type, "title": _text(title, MAX_TITLE),
                   "author": _text(author, MAX_AUTHOR), "username": name}
        try:
            self._send("POST", "/api/v1/requests", None, json.dumps(payload, ensure_ascii=True).encode("ascii"))
        except _Answered as answer:
            return answer.outcome
        return Outcome.UNAVAILABLE

    # ---- internals -------------------------------------------------------------------------
    def _call(self, method: str, path: str, query) -> Optional[Any]:
        try:
            self._send(method, path, query, None)
        except _Answered as answer:
            return answer.body if answer.outcome is Outcome.CREATED else None
        return None

    def _send(self, method: str, path: str, query, json_body: Optional[bytes]) -> None:
        """Raises _Answered with the outcome (and, for a 2xx, the parsed body). Returns only when the breaker is
        open."""
        allowed = ROUTES.get((method, path))
        if allowed is None or not set(query or {}) <= allowed:
            raise ForbiddenCall(f"{method} {path}")
        if json_body is not None and len(json_body) > MAX_REQUEST_BODY:
            raise ForbiddenCall("body")
        token = self.breaker.acquire()
        if token is None:
            return
        try:
            kw = {"json_body": json_body} if json_body is not None else {}
            resp = self._transport.request(method, path, query, self._timeout, MAX_JSON_BYTES, **kw)
        except UpstreamNotFound:
            self.breaker.neutral(token)
            raise _Answered(Outcome.NOT_LINKED) from None
        except UpstreamAuthError as exc:          # the token is wrong or lost its scope: an operator problem
            log_failure(SERVICE, exc)
            self.breaker.failure("auth", token)
            raise _Answered(Outcome.UNAVAILABLE) from None
        except UpstreamHTTPError as exc:
            if exc.status == 422:
                self.breaker.neutral(token)
                raise _Answered(Outcome.REFUSED) from None
            log_failure(SERVICE, exc)
            self.breaker.failure(type(exc).__name__, token)
            raise _Answered(Outcome.UNAVAILABLE) from None
        except Exception as exc:                  # noqa: BLE001: every transport failure is one outcome
            err = coerce(exc) or UpstreamError()
            log_failure(SERVICE, err)
            self.breaker.failure(type(err).__name__, token)
            raise _Answered(Outcome.UNAVAILABLE) from None
        status = getattr(resp, "status", 0)
        if status not in (200, 201, 202):
            self.breaker.failure("status", token)
            raise _Answered(Outcome.UNAVAILABLE)
        try:
            body = json.loads(resp.body.decode("utf-8")) if resp.body else {}
        except (ValueError, UnicodeDecodeError, RecursionError):
            self.breaker.failure("malformed", token)
            raise _Answered(Outcome.UNAVAILABLE) from None
        self.breaker.success(token)
        raise _Answered(Outcome.QUEUED if status == 202 else Outcome.CREATED, body)

    def _fail(self, error_class: str) -> None:
        token = self.breaker.acquire(trial=False)
        if token is not None:
            self.breaker.failure(error_class, token)


class _Answered(Exception):
    def __init__(self, outcome: Outcome, body: Any = None):
        super().__init__(outcome.value)
        self.outcome = outcome
        self.body = body
