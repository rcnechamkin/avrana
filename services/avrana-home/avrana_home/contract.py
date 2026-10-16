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

import copy
import enum
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
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
MAPPING_TTL_FOUND = 60.0              # bounds how long a renamed or swapped upstream account can linger
MAPPING_TTL_ABSENT = 60.0

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
                "creator": self.creator, "year": self.year,
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
    """A follower saw the failure its single-flight leader already reported and counted."""

    def __init__(self, err: Exception):
        super().__init__(type(err).__name__)
        self.err = err


class _Flight:
    """One in-progress mapping lookup that concurrent sections of the same member share."""
    __slots__ = ("event", "result", "exc", "started", "finished")

    def __init__(self, started: float):
        self.event = threading.Event()
        self.result = None
        self.exc = None
        self.started = started            # when the leader began: an old flight is abandoned
        self.finished = None              # when the leader reported: a stale answer is not shared


def _fresh_copy(err: Exception) -> Exception:
    """A new exception instance for each follower (a shared instance would share its traceback)."""
    try:
        return copy.copy(err)
    except Exception:
        return UpstreamUnreachable()


class _Ctx:
    """Per-call facts the breaker accounting needs."""
    __slots__ = ("upstream", "fresh_mapping")

    def __init__(self):
        self.upstream = False         # did any request actually reach the upstream?
        self.fresh_mapping = False    # was the mapping confirmed against the upstream in this call?


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

    def _fetch_artwork(self, user: UpstreamUser, ref: str) -> ArtworkResult:
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

    def item(self, principal: MemberPrincipal, item_id: str) -> SectionResult:
        if not valid_upstream_id(self.service, item_id):
            self._require_principal(principal)
            if not principal.has_group(self.required_group):
                return self._not_permitted("item")
            return SectionResult(self.service, "item", SectionState.EMPTY, reason="invalid_id")
        return self._section(principal, "item", f"item:{item_id}",
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
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return ArtworkResult(SectionState.NOT_PERMITTED)
        if not isinstance(ref, str) or not 0 < len(ref) <= 100:
            return ArtworkResult(SectionState.EMPTY)
        scope = self.cache.for_member(principal)
        cached = scope.get(self.service.value, "art:" + ref)
        if cached is not None:
            return cached
        out = self._call(principal, lambda user: self._fetch_artwork(user, ref))
        if out.kind == "unavailable":
            return ArtworkResult(SectionState.UNAVAILABLE)
        if out.kind == "not_linked":
            return ArtworkResult(SectionState.NOT_LINKED)
        if out.kind == "gone":
            return ArtworkResult(SectionState.EMPTY)
        result = out.value
        if result.state is SectionState.OK and out.fresh:
            scope.set(self.service.value, "art:" + ref, result, ttl=ARTWORK_TTL, data_class="artwork")
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

    def _acquire_slot(self, member: str) -> Optional[str]:
        """None when admitted, else the refusal reason. Service cap first, then the per-member cap
        (so one member cannot take every slot)."""
        with self._flight_lock:
            if self._in_flight >= self._max_in_flight:
                return "busy"
            if self._by_member.get(member, 0) >= self._max_per_member:
                return "member_busy"
            self._in_flight += 1
            self._by_member[member] = self._by_member.get(member, 0) + 1
            return None

    def _release_slot(self, member: str) -> None:
        with self._flight_lock:
            self._in_flight -= 1
            left = self._by_member.get(member, 0) - 1
            if left > 0:
                self._by_member[member] = left
            else:
                self._by_member.pop(member, None)

    def _account(self, err: Exception, token: Optional[int], member_scoped: bool,
                 force_count: bool = False) -> None:
        log_failure(self.service.value, err)
        if force_count or counts_toward_breaker(err, member_scoped=member_scoped):
            self.breaker.failure(type(err).__name__, token)
        else:
            self.breaker.neutral(token)          # a per-request problem: the shared circuit is untouched

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
        with self._flight_lock:
            flight = self._flights.get(member)
            if flight is not None and self.clock.now() - flight.started > self._request_timeout:
                flight = None                # older than one request budget: its leader is hung or gone
            leader = flight is None
            if leader:
                flight = self._flights[member] = _Flight(self.clock.now())
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
                raise _SharedFailure(_fresh_copy(coerce(flight.exc) or UpstreamUnreachable()))
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
            with self._flight_lock:
                if self._flights.get(member) is flight:
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
              reaches_upstream: bool = True) -> _Outcome:
        """The one place that touches the upstream: in-flight caps, shared circuit, mapping, then
        `work`. Every upstream-provoked failure becomes an outcome; nothing raises for it.

        The breaker hears only about calls that really reached the upstream: a mapping served from
        the cache (found, absent or ambiguous) is neutral, so it can neither reset a failure run nor
        keep a failing service circuit closed."""
        scope = self.cache.for_member(principal)
        member = principal.username
        refused = self._acquire_slot(member)
        if refused is not None:
            return _Outcome("unavailable", reason=refused)
        try:
            # inside the try: whatever the clock does, the slot is released below
            self._local.budget = CallBudget(self.clock, self._request_timeout)
            token = self.breaker.acquire()
            if token is None:
                return _Outcome("unavailable", reason="cooling_off")
            ctx = _Ctx()
            stage = "mapping"
            try:
                user = self._mapped(scope, principal, token, ctx)
                stage = "work"
                ctx.upstream = ctx.upstream or reaches_upstream
                value = work(user)
            except _SharedFailure as shared:
                # The leader of this mapping lookup already counted the failure: not twice.
                self.breaker.neutral(token)
                return _Outcome("unavailable", reason=type(shared.err).__name__)
            except (MappingFailed, AmbiguousMappingError) as exc:
                self._report_ok(token, ctx)
                reason = exc.reason if isinstance(exc, MappingFailed) else "ambiguous"
                return _Outcome("not_linked", reason=reason)
            except Exception as exc:
                err = coerce(exc)
                if err is None:                       # a programming error in OUR code: stay visible
                    self.breaker.neutral(token)
                    raise
                if isinstance(err, ItemGone):
                    # The route is addressed by one item and that item is absent or hidden: an empty
                    # result for that item. Says nothing about the service; never counted.
                    self.breaker.neutral(token)
                    return _Outcome("gone", reason="item_not_found")
                if isinstance(err, UserGone):
                    if stage == "work" and not ctx.fresh_mapping:
                        # A cached mapping points at a user the upstream no longer knows: specific to
                        # this member. Forget the mapping (re-resolved next time); circuit untouched.
                        scope.delete(self.service.value, "mapping")
                        log_failure(self.service.value, err)
                        self.breaker.neutral(token)
                        return _Outcome("not_linked", reason="upstream_user_not_found")
                    # The user was confirmed against the upstream a moment ago (by this call or by the
                    # single-flight leader it followed) and is now "gone": contradictory, so it is
                    # drift and counts. The mapping is NOT dropped on that contradiction.
                    self._account(err, token, member_scoped=False, force_count=True)
                elif isinstance(err, UpstreamNotFound):
                    # A fixed route (or one nobody classified) is missing: service-wide drift.
                    self._account(err, token, member_scoped=False, force_count=True)
                else:
                    self._account(err, token, member_scoped=(stage == "work"))
                return _Outcome("unavailable", reason=type(err).__name__)
            return _Outcome("ok", value, fresh=self._report_ok(token, ctx))
        finally:
            self._local.budget = None
            self._release_slot(member)

    def _report_ok(self, token: int, ctx: "_Ctx") -> bool:
        """Success only if the upstream really answered; returns whether the result is still fresh."""
        if ctx.upstream:
            return self.breaker.success(token)
        self.breaker.neutral(token)
        return self.breaker.valid(token)

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
            scope.set(self.service.value, cache_name, result, ttl=self.cache_ttl(section),
                      data_class="member_progress")
        return result

    def cache_ttl(self, section: str) -> float:
        return {"continue": 30.0, "recent": 120.0, "item": 120.0}.get(section, 30.0)


def _limit(limit: Any) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)
