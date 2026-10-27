"""Adapter contract: types, states and the base class every service adapter implements.

Status: proposed, not deployed. Standard library only. See docs/design/ADAPTER-CONTRACT.md.

The base class is a template: the public methods (`continue_items`, `recent_items`, `item`,
`fetch_artwork`, `search`) are final in spirit and do the checks that must never be skipped, in
this order:

  1. the argument is a parser-minted `MemberPrincipal` (anything else is a programming error);
  2. the member holds the adapter's required Authentik group, else NOT_PERMITTED with ZERO upstream
     calls and without touching the cache;
  3. member-scoped cache lookup (keyed by member, never shared). A hit is served even while the
     circuit is open: it makes no upstream call and is bounded by a short TTL;
  4. the in-flight caps (`busy` for the service, `member_busy` for one member) and the shared
     circuit (`cooling_off`), all returning UNAVAILABLE with zero upstream calls;
  5. the upstream mapping (`resolve_user`): unmapped -> NOT_LINKED, ambiguous -> NOT_LINKED
     (refused), never a fallback to an admin or service view;
  6. only then the subclass hook, which may talk to the upstream.

Subclasses implement the `_hook` methods only. Anything the upstream (or a transport) can
provoke is converted to an `UpstreamError` at this boundary (`resilience.coerce`), so a public
method returns a state and never raises for upstream-controlled input. Which errors count toward
the circuit shared by all members is `resilience.counts_toward_breaker`.
"""
from __future__ import annotations

import contextvars
import copy
import enum
from html.parser import HTMLParser
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

from .cache import MemberCache, register_cacheable
from .principal import MemberPrincipal, is_minted_principal
from .resilience import (REQUEST_BUDGET, CallBudget, CircuitBreaker, ItemGone, SystemClock,
                         UpstreamNotFound, UpstreamTimeout, UpstreamUnreachable, UserGone, coerce,
                         counts_toward_breaker, log_failure)

DEFAULT_LIMIT = 12
MAX_LIMIT = 50
MAX_TITLE_LEN = 200
ARTWORK_TTL = 300.0   # longest an item hidden from a member can still be served from cache
DEFAULT_MAX_IN_FLIGHT = 8             # upstream calls running at once, per adapter
DEFAULT_MAX_IN_FLIGHT_PER_MEMBER = 2  # ... of which one member may hold at most this many
# Artwork has its OWN allowance (review of #57): a page asks for many covers at once, and since per-member services
# re-check visibility on every cover, covers must neither starve the sections nor be refused under ordinary
# browser parallelism. Unlike sections (refused at once), a cover may wait briefly for a slot, the wait taken from
# its own request deadline. Artwork failures never count toward the service's circuit (they are neutral).
ARTWORK_MAX_IN_FLIGHT = 8
ARTWORK_MAX_IN_FLIGHT_PER_MEMBER = 4
ARTWORK_SLOT_WAIT = 0.4               # seconds, at most, and never more than half the request deadline
# F2 (AVR-503): a section that finds every slot taken waits in a BOUNDED queue instead of failing at once as `busy`,
# so fifteen members opening Home together all get their sections. Bounded three ways: at most SECTION_SLOT_WAIT
# seconds and never more than half of the call's own deadline (the wait is part of that deadline, so the page's hard
# cap holds), at most SECTION_MAX_WAITERS queued per adapter, and only while the circuit is closed (a failing or
# cooling-off service still answers `busy` at once, so a hung upstream adds no queueing on top of its timeouts).
SECTION_SLOT_WAIT = 1.0                # tuned on the burst benchmark: 0.75 s left 7 of 45 sections busy at 200 ms
SECTION_MAX_WAITERS = 24
MAPPING_TTL_FOUND = 60.0              # bounds how long a renamed or swapped upstream account can linger
MAPPING_TTL_ABSENT = 60.0
TRUNCATED = "truncated"               # SectionResult.reason: a list cut short by the request budget
TRUNCATED_TTL = 5.0                   # ... is cached this briefly, so a complete list follows soon

# The page a section job belongs to (AVR-756). `aggregate._run` gives every job of one page the same opaque token, so a
# sibling section that starts only AFTER its single-flight leader failed still shares that one counted failure. Calls
# outside a page (direct adapter calls, artwork) carry None and share only a flight that is still in progress.
_PAGE: "contextvars.ContextVar[Optional[object]]" = contextvars.ContextVar("avrana_page", default=None)


def run_in_page(page: object, fn: Callable[..., Any], *args: Any) -> Any:
    """Run one section job of `page` (on a pool thread); the page token is cleared afterwards."""
    token = _PAGE.set(page)
    try:
        return fn(*args)
    finally:
        _PAGE.reset(token)

log = logging.getLogger("avrana_home")


class Service(str, enum.Enum):
    JELLYFIN = "jellyfin"
    AUDIOBOOKSHELF = "audiobookshelf"
    KOMGA = "komga"
    CALIBRE_WEB = "calibre-web"


class Kind(str, enum.Enum):
    MOVIE = "movie"
    EPISODE = "episode"
    SERIES = "series"
    AUDIOBOOK = "audiobook"
    COMIC = "comic"
    EBOOK = "ebook"


class SectionState(str, enum.Enum):
    OK = "ok"                        # items present
    EMPTY = "empty"                  # reachable, mapped, nothing to show
    UNAVAILABLE = "unavailable"      # upstream down, slow, cooling off or misbehaving
    NOT_LINKED = "not_linked"        # no (or ambiguous) upstream account for this member
    NOT_PERMITTED = "not_permitted"  # lacks the Authentik group: caller renders ABSENCE


# Authentik group that gates each service (docs/services/sso-architecture.md).
REQUIRED_GROUP = {
    Service.JELLYFIN: "avrana-videos",
    Service.AUDIOBOOKSHELF: "avrana-audiobooks",
    Service.KOMGA: "avrana-comics",
    Service.CALIBRE_WEB: "avrana-books",
}

# Fixed per-service hand-off bases. Hand-off URLs are built ONLY from this table plus a validated
# id; an upstream-supplied URL is never used.
HANDOFF_BASE = {
    Service.JELLYFIN: "https://watch.avrana.net",
    Service.AUDIOBOOKSHELF: "https://listen.avrana.net",
    Service.KOMGA: "https://read.avrana.net",
    Service.CALIBRE_WEB: "https://books.avrana.net",
}
# Strict, ASCII-only id patterns (fullmatch). The path templates below were checked against each upstream's
# published web-app source (2026-10-16), not against the deployed apps: docs/design/CONTINUE-AND-HANDOFF.md, section 3.
_ID_PATTERN = {
    Service.JELLYFIN: re.compile(r"[0-9a-f]{32}"),
    # Audiobookshelf before 2.3 used "li_..." ids; current servers use lowercase UUIDs (seen live 2026-10-16).
    Service.AUDIOBOOKSHELF: re.compile(r"(?:li_[a-z0-9]{6,40}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"),
    Service.KOMGA: re.compile(r"[A-Za-z0-9]{6,32}"),
    Service.CALIBRE_WEB: re.compile(r"[0-9]{1,9}"),
}
_HANDOFF_PATH = {
    Service.JELLYFIN: "/web/#/details?id={id}",
    Service.AUDIOBOOKSHELF: "/item/{id}",
    Service.KOMGA: "/book/{id}",
    Service.CALIBRE_WEB: "/book/{id}",
}


class HandoffError(ValueError):
    pass


def valid_upstream_id(service: Service, upstream_id: Any) -> bool:
    return isinstance(upstream_id, str) and _ID_PATTERN[service].fullmatch(upstream_id) is not None


def build_handoff_url(service: Service, upstream_id: str) -> str:
    if not valid_upstream_id(service, upstream_id):
        raise HandoffError("invalid upstream id")
    return HANDOFF_BASE[service] + _HANDOFF_PATH[service].format(id=upstream_id)


MAX_QUERY_RAW = 256        # longer input is refused, not truncated
MAX_QUERY = 100            # after cleaning
MIN_QUERY = 2
# Characters that are wildcards or escapes in one of the upstream query languages (SQL LIKE, glob, regex,
# Lucene-style): they become spaces, so a member cannot widen a search with them.
_QUERY_NEUTRALISED = frozenset("*%_?" + chr(92) + "[]{}()|^~$" + chr(34) + "`")


def clean_query(value: Any) -> Optional[str]:
    """A search term made safe to send as a query PARAMETER, or None if it is unusable.

    Text only; at most MAX_QUERY_RAW characters in; Unicode NFC; control, format, surrogate, private-use and
    unassigned characters and line or paragraph separators removed; wildcards and escapes turned into spaces;
    whitespace collapsed; at most MAX_QUERY characters out; at least MIN_QUERY. It is NOT a path component and
    must never be interpolated into one."""
    if not isinstance(value, str) or len(value) > MAX_QUERY_RAW:
        return None
    out = []
    for ch in unicodedata.normalize("NFC", value):
        cat = unicodedata.category(ch)
        if ch in _QUERY_NEUTRALISED or ch.isspace() or cat in ("Zs", "Zl", "Zp"):
            out.append(" ")
        elif cat[0] == "C":
            continue
        else:
            out.append(ch)
    term = " ".join("".join(out).split())[:MAX_QUERY].strip()
    return term if len(term) >= MIN_QUERY else None


def clean_text(value: Any, limit: int = MAX_TITLE_LEN) -> Optional[str]:
    """Normalise upstream text for display: str only, no control chars, bounded length."""
    if not isinstance(value, str):
        return None
    text = "".join(c for c in value if c.isprintable()).strip()
    return text[:limit] or None


MAX_SUMMARY = 1200          # characters of synopsis shown; longer text is cut at a word with an ellipsis
MAX_SUMMARY_RAW = 20000     # longer upstream input is cut before it is parsed at all


class _TextOnly(HTMLParser):
    """Collects the text of an upstream synopsis. Upstreams store HTML here (Audiobookshelf descriptions, some
    Jellyfin overviews); tags, attributes, comments, scripts and styles are dropped and entities decoded, so only
    plain text remains. The template autoescapes that text: no upstream markup is ever rendered."""
    _BREAKS = frozenset({"br", "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self._BREAKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in self._BREAKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def clean_summary(value: Any) -> Optional[str]:
    """A synopsis as bounded plain text, or None. Never HTML: see `_TextOnly`."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value[:MAX_SUMMARY_RAW]
    if len(value) > MAX_SUMMARY_RAW and raw.rfind("<") > raw.rfind(">"):
        raw = raw[:raw.rfind("<")]          # never show half a tag that the cut-off split
    parser = _TextOnly()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:                       # HTMLParser is lenient; anything it still rejects shows nothing
        return None
    text = " ".join("".join(c if c.isprintable() else " " for c in "".join(parser.parts)).split())
    if len(text) > MAX_SUMMARY:
        text = text[:MAX_SUMMARY].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"
    return text or None


@dataclass(frozen=True)
class UpstreamUser:
    """The mapped upstream account. `upstream_id` is opaque and never shown to the member."""
    service: Service
    upstream_id: str

    def __repr__(self) -> str:
        return f"UpstreamUser({self.service.value}, <redacted>)"


@dataclass(frozen=True)
class ArtworkRef:
    """Opaque artwork reference. The home fetches bytes server-side via `fetch_artwork`; the
    reference never contains an upstream URL, API key or token. `alt` is the text alternative."""
    ref: str
    alt: str

    def to_dict(self) -> dict:
        return {"ref": self.ref, "alt": self.alt}


@dataclass(frozen=True)
class MediaItem:
    id: str                      # "<service>:<upstream id>", stable across calls
    service: Service
    kind: Kind
    title: str
    handoff_url: str
    subtitle: Optional[str] = None       # e.g. "S1 E3: Synthetic Pilot"
    series: Optional[str] = None
    progress_fraction: Optional[float] = None   # 0.0 to 1.0, only for in-progress items
    position_seconds: Optional[int] = None
    duration_seconds: Optional[int] = None
    artwork: Optional[ArtworkRef] = None
    creator: Optional[str] = None        # author, or the person most associated; display text only
    year: Optional[int] = None           # release or publication year, only when the upstream gives one
    # Validated (scheme, value) pairs the upstream itself returned (media_ids.py, MEDIA-IDENTITY.md). Internal:
    # used to link the same title across a member's own results, never displayed and not in to_dict().
    external_ids: Tuple[Tuple[str, str], ...] = field(default=(), repr=False)
    summary: Optional[str] = None        # synopsis, plain text (clean_summary); set on title-page lookups only

    def to_dict(self) -> dict:
        progress = None
        if self.progress_fraction is not None or self.position_seconds is not None:
            frac = self.progress_fraction
            progress = {"fraction": None if frac is None else round(frac, 4),
                        "percent": None if frac is None else int(round(frac * 100)),
                        "position_seconds": self.position_seconds,
                        "duration_seconds": self.duration_seconds}
        return {"id": self.id, "service": self.service.value, "kind": self.kind.value,
                "title": self.title, "subtitle": self.subtitle, "series": self.series,
                "progress": progress,
                "artwork": self.artwork.to_dict() if self.artwork else None,
                "creator": self.creator, "year": self.year, "summary": self.summary,
                "handoff_url": self.handoff_url}


@dataclass(frozen=True)
class SectionResult:
    """One home-page section from one service. Stable data contract for the UI."""
    service: Service
    section: str                  # "continue" | "recent" | "item" | "search"
    state: SectionState
    items: Tuple[MediaItem, ...] = ()
    reason: Optional[str] = None  # fixed diagnostic code for operators; NOT for display

    def to_dict(self) -> dict:
        return {"service": self.service.value, "section": self.section,
                "state": self.state.value, "items": [i.to_dict() for i in self.items]}

    @staticmethod
    def of(service: Service, section: str, items: Tuple[MediaItem, ...]) -> "SectionResult":
        state = SectionState.OK if items else SectionState.EMPTY
        return SectionResult(service, section, state, tuple(items))


@dataclass(frozen=True)
class ArtworkResult:
    state: SectionState
    content_type: Optional[str] = None
    data: bytes = b""


register_cacheable(Service, Kind, SectionState, UpstreamUser, ArtworkRef, MediaItem, SectionResult,
                   ArtworkResult)


class AmbiguousMappingError(Exception):
    """More than one upstream account could be this member. Refuse; never pick one."""


class MappingFailed(Exception):
    """Internal: carries a NOT_LINKED reason code out of the hook layer."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ForbiddenRequest(Exception):
    """An adapter tried a request outside its read-only allow-list. Raised BEFORE any I/O."""


class _SharedFailure(Exception):
    """A follower saw the failure its single-flight leader already reported. `counted` is False when the leader was
    an artwork call (neutral for the circuit): a section follower then counts the failure itself."""

    def __init__(self, err: Exception, flight: "Optional[_Flight]" = None):
        super().__init__(type(err).__name__)
        self.err = err
        self.flight = flight              # set only when the leader may not have counted it (see _call)


class _ArtworkBreaker:
    """The circuit as an artwork call sees it (review of #57): it may only ASK. It never takes the half-open trial
    and its results change nothing, in either direction, so covers can neither open the circuit nor keep it closed
    or close it while the sections fail. Freshness is still the token's validity."""
    __slots__ = ("_inner",)

    def __init__(self, inner):
        self._inner = inner

    def acquire(self):
        return self._inner.acquire(trial=False)

    def valid(self, token):
        return self._inner.valid(token)

    def success(self, token):
        return self._inner.valid(token)

    def failure(self, error_class, token):
        return False

    def neutral(self, token):
        return None


class _Flight:
    """One in-progress mapping lookup that concurrent sections of the same member share."""
    __slots__ = ("event", "result", "exc", "started", "finished", "counted", "page", "closed")

    def __init__(self, started: float, page: Optional[object] = None):
        self.event = threading.Event()
        self.result = None
        self.exc = None
        self.started = started            # when the leader began: an old flight is abandoned
        self.finished = None              # when the leader reported: a stale answer is not shared
        self.counted = True               # False when an artwork call led it (its failure was not counted)
        self.page = page                  # the leader's page token (None outside a page)
        self.closed = False               # the leader has reported (set under the flight lock)


def _fresh_copy(err: Exception) -> Exception:
    """A new exception instance for each follower (a shared instance would share its traceback)."""
    try:
        return copy.copy(err)
    except Exception:
        return UpstreamUnreachable()


class _Ctx:
    """Per-call facts the breaker accounting needs."""
    __slots__ = ("upstream", "fresh_mapping", "artwork")

    def __init__(self, artwork: bool = False):
        self.upstream = False         # did any request actually reach the upstream?
        self.fresh_mapping = False    # was the mapping confirmed against the upstream in this call?
        self.artwork = artwork        # an artwork call: neutral for the circuit


@dataclass(frozen=True)
class _Outcome:
    kind: str                       # "ok" | "unavailable" | "not_linked" | "gone"
    value: Any = None
    reason: Optional[str] = None
    fresh: bool = False             # False when a hung call finished after the circuit moved on


class MediaAdapter:
    """Base class. Subclasses set `service`, pass a breaker and cache, and implement hooks."""

    service: Service
    # Sections ("continue", "recent", ...) this adapter DECLARES it does not offer. `gather` does not
    # request them at all, so the member view carries no empty noise; the methods still answer
    # (EMPTY, reason `not_offered`) for a direct caller.
    not_offered: frozenset = frozenset()
    # True for a service whose upstream decides item visibility PER MEMBER (Jellyfin, Audiobookshelf): the
    # artwork hook then takes `cached=` and re-checks visibility before it may return cached bytes. False for
    # a shared view (Komga, Calibre-Web), where the group is the whole permission. See `fetch_artwork`.
    artwork_rechecks_visibility: bool = False

    def __init__(self, breaker: Optional[CircuitBreaker] = None,
                 cache: Optional[MemberCache] = None, clock=None,
                 max_in_flight: int = DEFAULT_MAX_IN_FLIGHT,
                 max_in_flight_per_member: int = DEFAULT_MAX_IN_FLIGHT_PER_MEMBER,
                 request_timeout: float = REQUEST_BUDGET):
        # `is not None`, never truthiness: an empty cache is falsy (it has __len__) and must not be
        # silently replaced by a private one.
        self.clock = clock if clock is not None else SystemClock()
        self.breaker = breaker if breaker is not None else CircuitBreaker(self.clock)
        self.cache = cache if cache is not None else MemberCache(self.clock)
        self._max_in_flight = max_in_flight
        self._max_per_member = max_in_flight_per_member
        self._request_timeout = request_timeout
        self._in_flight = 0
        self._by_member: dict = {}
        self._flights: dict = {}                      # member -> in-progress mapping lookup
        self._flight_lock = threading.Lock()
        self._slot_freed = threading.Condition(self._flight_lock)
        self._waiting = 0                          # sections queued for a slot (F2), at most SECTION_MAX_WAITERS
        self._art_in_flight = 0
        self._art_by_member: dict = {}
        self._local = threading.local()

    @property
    def request_timeout(self) -> float:
        """The one deadline this adapter gives a whole request (mapping and work together)."""
        return self._request_timeout

    @property
    def required_group(self) -> str:
        return REQUIRED_GROUP[self.service]

    @property
    def in_flight(self) -> int:
        with self._flight_lock:
            return self._in_flight

    # ---- hooks for subclasses -------------------------------------------------------------
    def _resolve_user(self, principal: MemberPrincipal) -> UpstreamUser:
        """Return the mapped user, raise MappingFailed(reason) if none, AmbiguousMappingError
        if several. May call the upstream."""
        raise NotImplementedError

    def _continue_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        raise NotImplementedError

    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        raise NotImplementedError

    def _item(self, user: UpstreamUser, item_id: str) -> SectionResult:
        raise NotImplementedError

    def _fetch_artwork(self, user: UpstreamUser, ref: str, cached=None) -> ArtworkResult:
        """`cached` is passed only when `artwork_rechecks_visibility` is True: a callable returning this
        member's cached OK result or None. Call it ONLY after the member-scoped visibility check passed."""
        raise NotImplementedError

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        """`query` is already cleaned (`clean_query`). Send it ONLY as a query parameter, never in a path."""
        raise NotImplementedError("this adapter does not implement search")

    # ---- public contract ------------------------------------------------------------------
    def resolve_user(self, principal: MemberPrincipal) -> Optional[UpstreamUser]:
        """Explicit mapping. None means unmapped OR ambiguous (refused) or unavailable; never a
        fallback account."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return None
        out = self._call(principal, lambda user: user, reaches_upstream=False)
        return out.value if out.kind == "ok" else None

    def continue_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        limit = _limit(limit)
        return self._section(principal, "continue", f"continue:{limit}",
                             lambda user: self._continue_items(user, limit))

    def recent_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        limit = _limit(limit)
        return self._section(principal, "recent", f"recent:{limit}",
                             lambda user: self._recent_items(user, limit))

    def item(self, principal: MemberPrincipal, item_id: str, fresh: bool = False) -> SectionResult:
        """One item for this member. `fresh=True` (the title page) skips the member cache entirely, no read and no
        write, so a removed upstream permission takes effect on the next view; the group is still checked first."""
        if not valid_upstream_id(self.service, item_id):
            self._require_principal(principal)
            if not principal.has_group(self.required_group):
                return self._not_permitted("item")
            return SectionResult(self.service, "item", SectionState.EMPTY, reason="invalid_id")
        return self._section(principal, "item", None if fresh else f"item:{item_id}",
                             lambda user: self._item(user, item_id))

    def search(self, principal: MemberPrincipal, query: str, limit: int = DEFAULT_LIMIT) -> SectionResult:
        """Search this library as this member. Order: principal, GROUP (before the query is even looked at),
        then the query is validated and bounded (`clean_query`), then mapping and the hook. Search results are
        NEVER cached (no cache read, no cache write): the term is not stored anywhere, and a revoked group or a
        changed restriction takes effect on the next search. The term is never logged."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return self._not_permitted("search")
        term = clean_query(query)
        if term is None:
            return SectionResult(self.service, "search", SectionState.EMPTY, reason="invalid_query")
        limit = _limit(limit)
        return self._section(principal, "search", None, lambda user: self._search(user, term, limit))

    def fetch_artwork(self, principal: MemberPrincipal, ref: str) -> ArtworkResult:
        """Order: principal, GROUP (no cache read, no upstream call without it), ref shape, then:

        * per-member visibility (`artwork_rechecks_visibility`, Jellyfin and Audiobookshelf): the upstream
          is asked, as THIS member, whether the item is visible on EVERY request, and only then may the
          member's own cached bytes be served (the hook calls `cached()` after its check). A hidden item, a
          lost mapping or an unreachable upstream is never served from the cache, and the stale entry is
          dropped. Only the image bytes are cached, never the permission.
        * shared view (Komga, Calibre-Web: one account, no per-member visibility): the member's own cached
          bytes are served for up to ARTWORK_TTL; the group is still checked first on every request.

        Every cache entry lives in the member's own partition (`for_member`), so one member's warm cover is
        never another member's."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return ArtworkResult(SectionState.NOT_PERMITTED)
        if not isinstance(ref, str) or not 0 < len(ref) <= 100:
            return ArtworkResult(SectionState.EMPTY)
        scope = self.cache.for_member(principal)
        key = "art:" + ref
        served_from_cache = []
        if self.artwork_rechecks_visibility:
            def cached() -> Optional[ArtworkResult]:
                value = scope.get(self.service.value, key)
                if isinstance(value, ArtworkResult) and value.state is SectionState.OK:
                    served_from_cache.append(True)
                    return value
                return None
            out = self._call(principal, lambda user: self._fetch_artwork(user, ref, cached=cached), artwork=True)
        else:
            hit = scope.get(self.service.value, key)
            if hit is not None:
                return hit
            out = self._call(principal, lambda user: self._fetch_artwork(user, ref), artwork=True)
        ok = out.kind == "ok" and out.value.state is SectionState.OK
        definitive = out.kind in ("not_linked", "gone") or (
            out.kind == "ok" and out.value.state in (SectionState.EMPTY, SectionState.NOT_PERMITTED,
                                                     SectionState.NOT_LINKED))
        if definitive and self.artwork_rechecks_visibility:
            # A definitive negative (not visible, not linked): forget the bytes. A transient refusal (busy, timeout,
            # unreachable) keeps them: serving still needs a passing check, so keeping them is not a leak.
            scope.delete(self.service.value, key)
        if out.kind == "unavailable":
            return ArtworkResult(SectionState.UNAVAILABLE)
        if out.kind == "not_linked":
            return ArtworkResult(SectionState.NOT_LINKED)
        if out.kind == "gone":
            return ArtworkResult(SectionState.EMPTY)
        result = out.value
        if ok and out.fresh and not served_from_cache:
            scope.set(self.service.value, key, result, ttl=ARTWORK_TTL, data_class="artwork")
        return result

    def health(self):
        return self.breaker.snapshot(self.service.value)

    # ---- internals ------------------------------------------------------------------------
    @staticmethod
    def _require_principal(principal: Any) -> None:
        if not is_minted_principal(principal):
            raise TypeError("adapters take a parser-minted MemberPrincipal, never a raw identity")

    def _not_permitted(self, section: str) -> SectionResult:
        return SectionResult(self.service, section, SectionState.NOT_PERMITTED)

    def current_budget(self) -> CallBudget:
        """The one deadline of the request in progress on this thread: mapping and work share it,
        so a request that respects it can never reach the hard cap in `gather`."""
        budget = getattr(self._local, "budget", None)
        return budget if budget is not None else CallBudget(self.clock, self._request_timeout)

    def _acquire_slot(self, member: str, budget: Optional[CallBudget] = None) -> Optional[str]:
        """None when admitted, else the refusal reason. Service cap first, then the per-member cap
        (so one member cannot take every slot). With a `budget`, a call refused by the SERVICE cap waits in the
        bounded queue (SECTION_SLOT_WAIT, SECTION_MAX_WAITERS, circuit closed only); the per-member cap never waits."""
        with self._slot_freed:
            if self._by_member.get(member, 0) >= self._max_per_member:
                return "member_busy" if self._in_flight < self._max_in_flight else "busy"
            if self._in_flight < self._max_in_flight:
                return self._take_slot(member)
            if (budget is None or self._waiting >= SECTION_MAX_WAITERS or not self.breaker.closed()):
                return "busy"
            try:
                wait = min(SECTION_SLOT_WAIT, budget.remaining() / 2)
            except UpstreamTimeout:
                return "busy"
            end = time.monotonic() + wait
            self._waiting += 1
            try:
                while True:
                    left = end - time.monotonic()
                    if left <= 0:
                        return "busy"
                    self._slot_freed.wait(left)
                    if self._by_member.get(member, 0) >= self._max_per_member:
                        return "member_busy"
                    if self._in_flight < self._max_in_flight:
                        return self._take_slot(member)
            finally:
                self._waiting -= 1

    def _take_slot(self, member: str) -> None:
        """Caller holds `_flight_lock`."""
        self._in_flight += 1
        self._by_member[member] = self._by_member.get(member, 0) + 1
        return None

    def _release_slot(self, member: str) -> None:
        with self._slot_freed:
            self._in_flight -= 1
            left = self._by_member.get(member, 0) - 1
            if left > 0:
                self._by_member[member] = left
            else:
                self._by_member.pop(member, None)
            self._slot_freed.notify_all()          # a queued section (F2) may take the freed slot

    def _acquire_art_slot(self, member: str, budget: CallBudget) -> Optional[str]:
        """The artwork allowance: separate from the section slots, with a short bounded wait (real time, at most
        ARTWORK_SLOT_WAIT and half of what is left of this request's deadline) before refusing."""
        try:
            wait = min(ARTWORK_SLOT_WAIT, budget.remaining() / 2)
        except UpstreamTimeout:
            wait = 0.0
        end = time.monotonic() + wait
        with self._slot_freed:
            while True:
                if (self._art_in_flight < ARTWORK_MAX_IN_FLIGHT
                        and self._art_by_member.get(member, 0) < ARTWORK_MAX_IN_FLIGHT_PER_MEMBER):
                    self._art_in_flight += 1
                    self._art_by_member[member] = self._art_by_member.get(member, 0) + 1
                    return None
                left = end - time.monotonic()
                if left <= 0:
                    return "busy" if self._art_in_flight >= ARTWORK_MAX_IN_FLIGHT else "member_busy"
                self._slot_freed.wait(left)

    def _release_art_slot(self, member: str) -> None:
        with self._slot_freed:
            self._art_in_flight -= 1
            left = self._art_by_member.get(member, 0) - 1
            if left > 0:
                self._art_by_member[member] = left
            else:
                self._art_by_member.pop(member, None)
            self._slot_freed.notify_all()

    def _account(self, err: Exception, token: Optional[int], member_scoped: bool,
                 force_count: bool = False, breaker=None) -> None:
        breaker = breaker if breaker is not None else self.breaker
        log_failure(self.service.value, err)
        if force_count or counts_toward_breaker(err, member_scoped=member_scoped):
            breaker.failure(type(err).__name__, token)
        else:
            breaker.neutral(token)               # a per-request problem: the shared circuit is untouched

    def _mapped(self, scope, principal: MemberPrincipal, token: int, ctx: "_Ctx") -> UpstreamUser:
        """Mapping with member-scoped caching of the outcome (positive and negative)."""
        hit = scope.get(self.service.value, "mapping")
        if hit is not None:
            kind, payload = hit
            if kind == "user":
                return payload
            if kind == "ambiguous":
                raise AmbiguousMappingError()
            raise MappingFailed(payload)
        member = principal.username
        page = _PAGE.get()
        with self._flight_lock:
            flight = self._flights.get(member)
            if flight is not None and self.clock.now() - flight.started > self._request_timeout:
                flight = None                # older than one request budget: its leader is hung or gone
            elif flight is not None and flight.closed and (page is None or flight.page is not page):
                flight = None                # a finished (failed) flight is shared only within its own page
            leader = flight is None
            if leader:
                flight = self._flights[member] = _Flight(self.clock.now(), page)
                flight.counted = not ctx.artwork
        if not leader:
            # Single-flight: a concurrent section of the same page is already asking the upstream
            # for this member; share its answer (and its one counted failure) instead of repeating.
            # The wait is bounded by what is LEFT of this request's own budget, never by the hard cap.
            try:
                left = self.current_budget().remaining()
            except UpstreamTimeout:
                raise _SharedFailure(UpstreamTimeout()) from None
            if not flight.event.wait(left):
                with self._flight_lock:
                    if self._flights.get(member) is flight:
                        del self._flights[member]       # abandon it: the next caller leads afresh
                raise _SharedFailure(UpstreamTimeout())
            if flight.finished is not None and self.clock.now() - flight.finished > MAPPING_TTL_FOUND:
                raise _SharedFailure(UpstreamTimeout())  # an answer older than the mapping TTL is not shared
            if isinstance(flight.exc, MappingFailed):
                raise MappingFailed(flight.exc.reason)
            if isinstance(flight.exc, AmbiguousMappingError):
                raise AmbiguousMappingError()
            if flight.exc is not None:
                raise _SharedFailure(_fresh_copy(coerce(flight.exc) or UpstreamUnreachable()), flight=flight)
            if flight.result is None:
                raise _SharedFailure(UpstreamUnreachable())
            ctx.fresh_mapping = True         # the leader just confirmed it against the upstream
            return flight.result
        try:
            user = self._lead_mapping(scope, principal, token, ctx)
            flight.result = user
            return user
        except BaseException as exc:
            flight.exc = exc
            raise
        finally:
            try:
                flight.finished = self.clock.now()
            except Exception:
                flight.finished = None
            # A failed flight of a page stays visible to that page's sibling sections that start after it ended
            # (AVR-756): they follow it, so one page is still one counted failure. A failure is never cached as
            # data; a later page (another token) or a call outside a page leads afresh. The kept copy carries no
            # traceback, so a retained flight pins no frames.
            retain = page is not None and isinstance(flight.exc, Exception)
            if retain:
                flight.exc = _fresh_copy(flight.exc)
            with self._flight_lock:
                flight.closed = True
                if self._flights.get(member) is flight and not retain:
                    del self._flights[member]
            flight.event.set()

    def _lead_mapping(self, scope, principal: MemberPrincipal, token: int, ctx: "_Ctx") -> UpstreamUser:
        ctx.upstream = ctx.fresh_mapping = True      # from here on the upstream is being asked
        try:
            user = self._resolve_user(principal)
        except MappingFailed as exc:
            if self.breaker.valid(token):
                scope.set(self.service.value, "mapping", ("absent", exc.reason), ttl=MAPPING_TTL_ABSENT,
                          data_class="member_mapping")
            raise
        except AmbiguousMappingError:
            if self.breaker.valid(token):
                scope.set(self.service.value, "mapping", ("ambiguous", None), ttl=MAPPING_TTL_ABSENT,
                          data_class="member_mapping")
            raise
        if self.breaker.valid(token):
            scope.set(self.service.value, "mapping", ("user", user), ttl=MAPPING_TTL_FOUND,
                      data_class="member_mapping")
        return user

    def _call(self, principal: MemberPrincipal, work: Callable[[UpstreamUser], Any],
              reaches_upstream: bool = True, artwork: bool = False) -> _Outcome:
        """The one place that touches the upstream: in-flight caps, shared circuit, mapping, then
        `work`. Every upstream-provoked failure becomes an outcome; nothing raises for it.

        The breaker hears only about calls that really reached the upstream: a mapping served from
        the cache (found, absent or ambiguous) is neutral, so it can neither reset a failure run nor
        keep a failing service circuit closed."""
        scope = self.cache.for_member(principal)
        member = principal.username
        # Both kinds start their deadline BEFORE any wait for a slot, so the wait is part of it (the page's hard cap).
        budget = CallBudget(self.clock, self._request_timeout)
        refused = self._acquire_art_slot(member, budget) if artwork else self._acquire_slot(member, budget)
        if refused is not None:
            return _Outcome("unavailable", reason=refused)
        br = _ArtworkBreaker(self.breaker) if artwork else self.breaker
        try:
            # inside the try: whatever the clock does, the slot is released below. An artwork call's deadline
            # started before its (bounded) wait for a slot, so the wait is part of it.
            self._local.budget = budget
            token = br.acquire()
            if token is None:
                return _Outcome("unavailable", reason="cooling_off")
            ctx = _Ctx(artwork)
            stage = "mapping"
            try:
                user = self._mapped(scope, principal, token, ctx)
                stage = "work"
                ctx.upstream = ctx.upstream or reaches_upstream
                value = work(user)
            except _SharedFailure as shared:
                claim = False
                if not artwork and shared.flight is not None:
                    with self._flight_lock:          # an artwork call led and counted nothing: ONE section counts it
                        if not shared.flight.counted:
                            shared.flight.counted = True
                            claim = True
                if claim:
                    self._account(shared.err, token, member_scoped=False, breaker=br)
                else:
                    br.neutral(token)    # already counted once (or this call may not count at all)
                return _Outcome("unavailable", reason=type(shared.err).__name__)
            except (MappingFailed, AmbiguousMappingError) as exc:
                self._report_ok(token, ctx, br)
                reason = exc.reason if isinstance(exc, MappingFailed) else "ambiguous"
                return _Outcome("not_linked", reason=reason)
            except Exception as exc:
                err = coerce(exc)
                if err is None:                       # a programming error in OUR code: stay visible
                    br.neutral(token)
                    raise
                if isinstance(err, ItemGone):
                    # The route is addressed by one item and that item is absent or hidden: an empty
                    # result for that item. Says nothing about the service; never counted.
                    br.neutral(token)
                    return _Outcome("gone", reason="item_not_found")
                if isinstance(err, UserGone):
                    if stage == "work" and not ctx.fresh_mapping:
                        # A cached mapping points at a user the upstream no longer knows: specific to
                        # this member. Forget the mapping (re-resolved next time); circuit untouched.
                        scope.delete(self.service.value, "mapping")
                        log_failure(self.service.value, err)
                        br.neutral(token)
                        return _Outcome("not_linked", reason="upstream_user_not_found")
                    # The user was confirmed against the upstream a moment ago (by this call or by the
                    # single-flight leader it followed) and is now "gone": contradictory, so it is
                    # drift and counts. The mapping is NOT dropped on that contradiction.
                    self._account(err, token, member_scoped=False, force_count=True, breaker=br)
                elif isinstance(err, UpstreamNotFound):
                    # A fixed route (or one nobody classified) is missing: service-wide drift.
                    self._account(err, token, member_scoped=False, force_count=True, breaker=br)
                else:
                    self._account(err, token, member_scoped=(stage == "work"), breaker=br)
                return _Outcome("unavailable", reason=type(err).__name__)
            if getattr(value, "reason", None) == TRUNCATED:
                # A list cut short by the budget: shown, but no proof of health. The shared failure run is
                # neither reset nor extended, so one such member cannot hold the circuit closed for everyone.
                br.neutral(token)
                return _Outcome("ok", value, fresh=br.valid(token))
            return _Outcome("ok", value, fresh=self._report_ok(token, ctx, br))
        finally:
            self._local.budget = None
            if artwork:
                self._release_art_slot(member)
            else:
                self._release_slot(member)

    def _report_ok(self, token: int, ctx: "_Ctx", breaker=None) -> bool:
        """Success only if the upstream really answered; returns whether the result is still fresh."""
        breaker = breaker if breaker is not None else self.breaker
        if ctx.upstream:
            return breaker.success(token)
        breaker.neutral(token)
        return breaker.valid(token)

    def _section(self, principal: MemberPrincipal, section: str, cache_name: Optional[str],
                 fetch: Callable[[UpstreamUser], SectionResult]) -> SectionResult:
        """`cache_name=None` means this section is NEVER cached (search: the term is not a cache key)."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return self._not_permitted(section)            # no upstream call, no cache read
        scope = self.cache.for_member(principal)
        cached = scope.get(self.service.value, cache_name) if cache_name is not None else None
        if cached is not None:
            return cached
        out = self._call(principal, fetch)
        if out.kind == "unavailable":
            return SectionResult(self.service, section, SectionState.UNAVAILABLE, reason=out.reason)
        if out.kind == "not_linked":
            return SectionResult(self.service, section, SectionState.NOT_LINKED, reason=out.reason)
        if out.kind == "gone":
            return SectionResult(self.service, section, SectionState.EMPTY, reason=out.reason)
        result = out.value
        if cache_name is not None and result.state in (SectionState.OK, SectionState.EMPTY) and out.fresh:
            # permission-dependent library data is member-scoped, never "catalogue"
            ttl = TRUNCATED_TTL if result.reason == TRUNCATED else self.cache_ttl(section)
            scope.set(self.service.value, cache_name, result, ttl=ttl, data_class="member_progress")
        return result

    def cache_ttl(self, section: str) -> float:
        return {"continue": 30.0, "recent": 120.0, "item": 120.0}.get(section, 30.0)


def _limit(limit: Any) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)
