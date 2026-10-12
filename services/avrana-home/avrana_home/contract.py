"""Adapter contract: types, states and the base class every service adapter implements.

Status: proposed, not deployed. Standard library only. See docs/design/ADAPTER-CONTRACT.md.

The base class is a template: the public methods (`continue_items`, `recent_items`, `item`,
`fetch_artwork`, `search`) are final in spirit and do the checks that must never be skipped, in
this order:

  1. the argument is a real `MemberPrincipal` (a raw string is a programming error);
  2. the member holds the adapter's required Authentik group, else NOT_PERMITTED with ZERO upstream
     calls and without touching the cache;
  3. the per-service circuit is closed, else UNAVAILABLE with zero upstream calls;
  4. member-scoped cache lookup (keyed by member, never shared);
  5. the upstream mapping (`resolve_user`): unmapped -> NOT_LINKED, ambiguous -> NOT_LINKED
     (refused), never a fallback to an admin or service view;
  6. only then the subclass hook, which may talk to the upstream.

Subclasses implement the `_hook` methods only.
"""
from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from .cache import MemberCache
from .principal import MemberPrincipal
from .resilience import (CircuitBreaker, UpstreamError, SystemClock, log_failure)

DEFAULT_LIMIT = 12
MAX_LIMIT = 50
MAX_TITLE_LEN = 200

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
        if self.progress_fraction is not None:
            progress = {"fraction": round(self.progress_fraction, 4),
                        "percent": int(round(self.progress_fraction * 100)),
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


class MediaAdapter:
    """Base class. Subclasses set `service`, pass a breaker and cache, and implement hooks."""

    service: Service

    def __init__(self, breaker: Optional[CircuitBreaker] = None,
                 cache: Optional[MemberCache] = None, clock=None):
        self.clock = clock or SystemClock()
        self.breaker = breaker or CircuitBreaker(self.clock)
        self.cache = cache or MemberCache(self.clock)

    @property
    def required_group(self) -> str:
        return REQUIRED_GROUP[self.service]

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
        """Explicit mapping. None means unmapped OR ambiguous (refused); never a fallback."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return None
        if not self.breaker.allow():
            return None
        try:
            user = self._mapped(principal)
        except (MappingFailed, AmbiguousMappingError):
            return None
        except UpstreamError as exc:
            self._failed(exc)
            return None
        return user

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
            return SectionResult(self.service, "item", SectionState.EMPTY, reason="invalid_id") \
                if principal.has_group(self.required_group) else self._not_permitted("item")
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
        if not self.breaker.allow():
            return ArtworkResult(SectionState.UNAVAILABLE)
        try:
            user = self._mapped(principal)
            result = self._fetch_artwork(user, ref)
            self.breaker.record_success()
            if result.state is SectionState.OK:
                scope.set(self.service.value, "art:" + ref, result, ttl=600.0)
            return result
        except (MappingFailed, AmbiguousMappingError):
            return ArtworkResult(SectionState.NOT_LINKED)
        except UpstreamError as exc:
            self._failed(exc)
            return ArtworkResult(SectionState.UNAVAILABLE)

    def health(self):
        return self.breaker.snapshot(self.service.value)

    # ---- internals ------------------------------------------------------------------------
    @staticmethod
    def _require_principal(principal: Any) -> None:
        if not isinstance(principal, MemberPrincipal):
            raise TypeError("adapters take a MemberPrincipal, never a raw identity")

    def _not_permitted(self, section: str) -> SectionResult:
        return SectionResult(self.service, section, SectionState.NOT_PERMITTED)

    def _failed(self, exc: Exception) -> None:
        self.breaker.record_failure(type(exc).__name__)
        log_failure(self.service.value, exc)

    def _mapped(self, principal: MemberPrincipal) -> UpstreamUser:
        """Mapping with member-scoped caching of the outcome (positive and negative)."""
        scope = self.cache.for_member(principal)
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
            self.breaker.record_success()       # the upstream answered; the member just is not linked
            scope.set(self.service.value, "mapping", ("absent", exc.reason), ttl=60.0)
            raise
        except AmbiguousMappingError:
            self.breaker.record_success()
            scope.set(self.service.value, "mapping", ("ambiguous", None), ttl=60.0)
            raise
        self.breaker.record_success()
        scope.set(self.service.value, "mapping", ("user", user), ttl=300.0)
        return user

    def _section(self, principal: MemberPrincipal, section: str, cache_name: str,
                 fetch: Callable[[UpstreamUser], SectionResult]) -> SectionResult:
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return self._not_permitted(section)            # no upstream call, no cache read
        scope = self.cache.for_member(principal)
        cached = scope.get(self.service.value, cache_name)
        if cached is not None:
            return cached
        if not self.breaker.allow():
            return SectionResult(self.service, section, SectionState.UNAVAILABLE, reason="cooling_off")
        try:
            user = self._mapped(principal)
        except MappingFailed as exc:
            return SectionResult(self.service, section, SectionState.NOT_LINKED, reason=exc.reason)
        except AmbiguousMappingError:
            return SectionResult(self.service, section, SectionState.NOT_LINKED, reason="ambiguous")
        except UpstreamError as exc:
            self._failed(exc)
            return SectionResult(self.service, section, SectionState.UNAVAILABLE, reason=type(exc).__name__)
        try:
            result = fetch(user)
        except UpstreamError as exc:
            self._failed(exc)
            return SectionResult(self.service, section, SectionState.UNAVAILABLE, reason=type(exc).__name__)
        self.breaker.record_success()
        if result.state in (SectionState.OK, SectionState.EMPTY):
            scope.set(self.service.value, cache_name, result, ttl=self.cache_ttl(section))
        return result

    def cache_ttl(self, section: str) -> float:
        return {"continue": 30.0, "recent": 120.0, "item": 120.0}.get(section, 30.0)


def _limit(limit: Any) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)
