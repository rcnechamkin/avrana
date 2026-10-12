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
  4. the in-flight cap (`busy`) and the shared circuit (`cooling_off`), both returning UNAVAILABLE
     with zero upstream calls;
  5. the upstream mapping (`resolve_user`): unmapped -> NOT_LINKED, ambiguous -> NOT_LINKED
     (refused), never a fallback to an admin or service view;
  6. only then the subclass hook, which may talk to the upstream.

Subclasses implement the `_hook` methods only. Anything the upstream (or a transport) can
provoke is converted to an `UpstreamError` at this boundary (`resilience.coerce`), so a public
method returns a state and never raises for upstream-controlled input. Which errors count toward
the circuit shared by all members is `resilience.counts_toward_breaker`.
"""
from __future__ import annotations

import enum
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from .cache import MemberCache
from .principal import MemberPrincipal, is_minted_principal
from .resilience import (CircuitBreaker, SystemClock, UpstreamNotFound, coerce,
                         counts_toward_breaker, log_failure)

DEFAULT_LIMIT = 12
MAX_LIMIT = 50
MAX_TITLE_LEN = 200
ARTWORK_TTL = 300.0   # longest an item hidden from a member can still be served from cache
DEFAULT_MAX_IN_FLIGHT = 4

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
# Strict, ASCII-only id patterns (fullmatch). Path templates are UNVERIFIED against live apps.
_ID_PATTERN = {
    Service.JELLYFIN: re.compile(r"[0-9a-f]{32}"),
    Service.AUDIOBOOKSHELF: re.compile(r"li_[a-z0-9]{6,40}"),
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


class AmbiguousMappingError(Exception):
    """More than one upstream account could be this member. Refuse; never pick one."""


class MappingFailed(Exception):
    """Internal: carries a NOT_LINKED reason code out of the hook layer."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ForbiddenRequest(Exception):
    """An adapter tried a request outside its read-only allow-list. Raised BEFORE any I/O."""


@dataclass(frozen=True)
class _Outcome:
    kind: str                       # "ok" | "unavailable" | "not_linked"
    value: Any = None
    reason: Optional[str] = None
    fresh: bool = False             # False when a hung call finished after the circuit moved on


class MediaAdapter:
    """Base class. Subclasses set `service`, pass a breaker and cache, and implement hooks."""

    service: Service

    def __init__(self, breaker: Optional[CircuitBreaker] = None,
                 cache: Optional[MemberCache] = None, clock=None,
                 max_in_flight: int = DEFAULT_MAX_IN_FLIGHT):
        self.clock = clock or SystemClock()
        self.breaker = breaker or CircuitBreaker(self.clock)
        self.cache = cache or MemberCache(self.clock)
        self._max_in_flight = max_in_flight
        self._in_flight = 0
        self._flight_lock = threading.Lock()

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
        raise NotImplementedError("search is defined by the contract but not implemented yet")

    # ---- public contract ------------------------------------------------------------------
    def resolve_user(self, principal: MemberPrincipal) -> Optional[UpstreamUser]:
        """Explicit mapping. None means unmapped OR ambiguous (refused) or unavailable; never a
        fallback account."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return None
        out = self._call(principal, lambda user: user)
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
        self._require_principal(principal)
        raise NotImplementedError("search is defined by the contract but not implemented yet")

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
        result = out.value
        if result.state is SectionState.OK and out.fresh:
            scope.set(self.service.value, "art:" + ref, result, ttl=ARTWORK_TTL,
                      size=len(result.data) + 256)
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

    def _acquire_slot(self) -> bool:
        with self._flight_lock:
            if self._in_flight >= self._max_in_flight:
                return False
            self._in_flight += 1
            return True

    def _release_slot(self) -> None:
        with self._flight_lock:
            self._in_flight -= 1

    def _account(self, err: Exception, token: Optional[int]) -> None:
        log_failure(self.service.value, err)
        if counts_toward_breaker(err):
            self.breaker.failure(type(err).__name__, token)
        else:
            self.breaker.neutral(token)          # a per-request problem: the shared circuit is untouched

    def _mapped(self, scope, principal: MemberPrincipal, token: int) -> UpstreamUser:
        """Mapping with member-scoped caching of the outcome (positive and negative)."""
        hit = scope.get(self.service.value, "mapping")
        if hit is not None:
            kind, payload = hit
            if kind == "user":
                return payload
            if kind == "ambiguous":
                raise AmbiguousMappingError()
            raise MappingFailed(payload)
        try:
            user = self._resolve_user(principal)
        except MappingFailed as exc:
            if self.breaker.valid(token):
                scope.set(self.service.value, "mapping", ("absent", exc.reason), ttl=60.0, size=128)
            raise
        except AmbiguousMappingError:
            if self.breaker.valid(token):
                scope.set(self.service.value, "mapping", ("ambiguous", None), ttl=60.0, size=128)
            raise
        if self.breaker.valid(token):
            scope.set(self.service.value, "mapping", ("user", user), ttl=300.0, size=128)
        return user

    def _call(self, principal: MemberPrincipal, work: Callable[[UpstreamUser], Any]) -> _Outcome:
        """The one place that touches the upstream: in-flight cap, shared circuit, mapping, then
        `work`. Every upstream-provoked failure becomes an outcome; nothing raises for it."""
        scope = self.cache.for_member(principal)
        if not self._acquire_slot():
            return _Outcome("unavailable", reason="busy")
        try:
            token = self.breaker.acquire()
            if token is None:
                return _Outcome("unavailable", reason="cooling_off")
            stage = "mapping"
            try:
                user = self._mapped(scope, principal, token)
                stage = "work"
                value = work(user)
            except MappingFailed as exc:
                self.breaker.success(token)           # the upstream answered; the member is not linked
                return _Outcome("not_linked", reason=exc.reason)
            except AmbiguousMappingError:
                self.breaker.success(token)
                return _Outcome("not_linked", reason="ambiguous")
            except Exception as exc:
                err = coerce(exc)
                if err is None:                       # a programming error, not upstream input
                    self.breaker.neutral(token)
                    raise
                if isinstance(err, UpstreamNotFound) and stage == "work":
                    # The mapped upstream user (or item) is gone: specific to this member. Forget the
                    # mapping so it is re-resolved, and do not touch the shared circuit.
                    scope.delete(self.service.value, "mapping")
                    log_failure(self.service.value, err)
                    self.breaker.neutral(token)
                    return _Outcome("not_linked", reason="upstream_user_not_found")
                self._account(err, token)
                return _Outcome("unavailable", reason=type(err).__name__)
            fresh = self.breaker.success(token)
            return _Outcome("ok", value, fresh=fresh)
        finally:
            self._release_slot()

    def _section(self, principal: MemberPrincipal, section: str, cache_name: str,
                 fetch: Callable[[UpstreamUser], SectionResult]) -> SectionResult:
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return self._not_permitted(section)            # no upstream call, no cache read
        scope = self.cache.for_member(principal)
        cached = scope.get(self.service.value, cache_name)
        if cached is not None:
            return cached
        out = self._call(principal, fetch)
        if out.kind == "unavailable":
            return SectionResult(self.service, section, SectionState.UNAVAILABLE, reason=out.reason)
        if out.kind == "not_linked":
            return SectionResult(self.service, section, SectionState.NOT_LINKED, reason=out.reason)
        result = out.value
        if result.state in (SectionState.OK, SectionState.EMPTY) and out.fresh:
            scope.set(self.service.value, cache_name, result, ttl=self.cache_ttl(section),
                      size=256 + 512 * len(result.items))
        return result

    def cache_ttl(self, section: str) -> float:
        return {"continue": 30.0, "recent": 120.0, "item": 120.0}.get(section, 30.0)


def _limit(limit: Any) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)
