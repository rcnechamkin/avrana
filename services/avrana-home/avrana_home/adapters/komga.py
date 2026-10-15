"""Komga read-only member adapter: one section, "Recently added" (comics).

Status: proposed, not deployed. Standard library only. Proven only against HAND-WRITTEN fixtures that
are unverified against the deployed Komga; a recorded, read-only contract check is a separate,
owner-approved step that must happen before any real member data is read (ADAPTER-CONTRACT.md, section 12.5).

KEY SCOPE (OWNER DECISION, see the contract, section 12.2). Komga has no impersonation and its per-user
restrictions (library sharing, age restriction, sharing labels) live in the member's user record, which
only an ADMIN credential can list. So enforcing a member's restrictions needs an admin-capable key, and
the read-only property comes from the GET allow-list below, never from the key. The alternative, a
non-admin shared-view account, cannot read restrictions and is correct only while no member is restricted.
This module implements the admin-key design with a fail-closed client-side filter, exactly like the
Audiobookshelf adapter. It must not be wired to a key until the owner has chosen.

How it stays member-scoped:

  * The credential lives only inside the transport. Every request goes through `GuardedTransport`: GET
    only, an explicit route list, and a mapped member must exist before any non-mapping route is used.
    Komga routes cannot carry the member in the path or query, so the guard cannot bind a request to a
    member: the isolation is this module's filter, which is why it is built to fail closed.
  * The member's restrictions are read from that member's own record in `/api/v2/users` (matched by the
    mapped id), BEFORE any book is requested. A malformed restriction field makes the section
    unavailable, never an unfiltered list.
  * Books and series are fetched with the admin key, so they are NOT member-scoped upstream. A book is
    shown only if its library, its series' age rating and its series' sharing labels pass that member's
    restrictions (stricter than Komga's own combination, see `_Access`).
  * Read progress in a book response belongs to the credential's user, not the member: it is never read.
    "Continue" is therefore not offered.
  * Read lists and collections are server-global and are not in the route table.
  * Artwork is fetched only after the same visibility check, per request.

Route and field names are recalled from Komga's public API documentation and are UNVERIFIED.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..contract import (ArtworkRef, ArtworkResult, DEFAULT_LIMIT, Kind, MappingFailed, MediaItem,
                        SectionResult, SectionState, Service, UpstreamUser, build_handoff_url,
                        clean_text, valid_upstream_id)
from ..principal import MemberPrincipal
from ..resilience import (DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamMalformed,
                          UpstreamMisbehaved, UserGone)
from ._base import GuardedAdapter, Route, bounded_int, match_exactly_one
from ._base import GuardedTransport as _Guard

_ID = r"[A-Za-z0-9]{6,32}"
_BOUND_ID = re.compile(_ID)
_ARTWORK_REF = re.compile(r"komga/book/(" + _ID + r")")
MAX_LOOKUPS = 12                 # series lookups per request, however long the book list is
MAX_PAGE = 100                   # books asked for in one page, whatever the limit
MAX_LABELS = 200                 # a list longer than this in a record is hostile

ALLOWED_ROUTES = (
    # the user list: mapping and the member's restrictions (admin-only upstream); not bound to a member
    Route("users", r"/api/v2/users", (), user_scoped=False, needs_user=False, not_found=RouteMissing),
    Route("latest", r"/api/v1/books/latest", ("page", "size"), user_scoped=False, not_found=RouteMissing),
    Route("book", r"/api/v1/books/(?!(?:latest|updated|ondeck)$)" + _ID, (), user_scoped=False, not_found=ItemGone),
    Route("series", r"/api/v1/series/" + _ID, (), user_scoped=False, not_found=ItemGone),
    Route("search", r"/api/v1/books", ("search", "page", "size"), user_scoped=False, not_found=RouteMissing),
    Route("thumbnail", r"/api/v1/books/(?!(?:latest|updated|ondeck)/)" + _ID + r"/thumbnail", (), user_scoped=False,
          not_found=ItemGone),
)


class GuardedTransport(_Guard):
    """The Komga allow-list around an inner Transport."""

    def __init__(self, inner, bound_user_id: Optional[str] = None):
        super().__init__(inner, ALLOWED_ROUTES, _BOUND_ID, bound_user_id)

    def _clone(self, user_id):
        return GuardedTransport(self._inner, user_id)


# ---- member mapping: a SEAM (OWNER DECISION, contract section 11.2 / 12.2) ----------------------
# A linker takes the verified principal and the raw upstream user list and returns the one Komga user id
# for that member, or raises MappingFailed / AmbiguousMappingError. Nothing else in this module decides
# who a member is. The owner has not yet decided between: A) the exact username, B) the e-mail, C) an
# owner-maintained link list. Only A (as far as Komga's records allow) and C exist here; B is NOT implemented.
Linker = Callable[[MemberPrincipal, Sequence[Any]], str]


_RESERVED = frozenset({"latest", "updated", "ondeck"})     # Komga sub-routes that look like ids (UNVERIFIED list)


def _item_id(value: Any) -> bool:
    return valid_upstream_id(Service.KOMGA, value) and value not in _RESERVED


def _komga_user_id(raw: Any) -> Optional[str]:
    if isinstance(raw, dict) and valid_upstream_id(Service.KOMGA, raw.get("id")):
        return raw["id"]
    return None


def exact_name_linker(principal: MemberPrincipal, users: Sequence[Any]) -> str:
    """The contract's current rule (exact, case-sensitive, loose matches never link) applied to the only
    name Komga's user record has: its `email` (the login). A Komga record has no separate username, so
    this links only when the Authentik username equals the Komga login exactly, which will usually NOT be
    the case: the member is then NOT_LINKED (fail safe). The principal's e-mail is never consulted."""
    def extract(raw):
        uid, name = _komga_user_id(raw), raw.get("email") if isinstance(raw, dict) else None
        return (name, uid) if uid is not None and isinstance(name, str) else None
    uid, _ = match_exactly_one(principal.username, users, extract)
    return uid


def link_table_linker(table: Dict[str, str]) -> Linker:
    """Option C: an owner-maintained {Authentik username: Komga user id} table, kept outside Git. The id
    must exist in the upstream list exactly once; an id shared by two usernames is refused up front."""
    frozen = dict(table)
    if len(set(frozen.values())) != len(frozen):
        raise ValueError("two usernames link to one Komga user")
    for uid in frozen.values():
        if not valid_upstream_id(Service.KOMGA, uid):
            raise ValueError("malformed Komga user id in the link table")

    def link(principal: MemberPrincipal, users: Sequence[Any]) -> str:
        uid = frozen.get(principal.username)
        if uid is None:
            raise MappingFailed("unmapped")
        if sum(1 for u in users if _komga_user_id(u) == uid) != 1:
            raise MappingFailed("unmapped")
        return uid
    return link


# ---- what one member may see -----------------------------------------------------------------
def _str_list(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_LABELS or not all(isinstance(x, str) for x in value):
        raise UpstreamMalformed()
    return tuple(value)


class _Access:
    """The restrictions of one member, read from that member's own record (fail closed on anything odd).

    Komga's own combination of allow rules is not verified here; this class is STRICTER on purpose: every
    configured rule must pass (library AND age AND labels), so it can only show less than Komga would."""

    def __init__(self, libraries: Optional[frozenset], age: Optional[Tuple[str, int]],
                 allow: frozenset, exclude: frozenset):
        self.libraries = libraries          # None: every library
        self.age = age                      # None, or ("ALLOW_ONLY" | "EXCLUDE", age)
        self.allow = allow                  # sharing labels, case-folded; empty: no allow rule
        self.exclude = exclude

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "_Access":
        shared_all = record.get("sharedAllLibraries")
        if not isinstance(shared_all, bool):
            raise UpstreamMalformed()
        libraries = None if shared_all else frozenset(_str_list(record.get("sharedLibrariesIds")))
        restriction = record.get("ageRestriction")
        age = None
        if restriction is not None:
            if not isinstance(restriction, dict):
                raise UpstreamMalformed()
            kind, years = restriction.get("restriction"), restriction.get("age")
            if kind not in ("ALLOW_ONLY", "EXCLUDE") or isinstance(years, bool) or not isinstance(years, int):
                raise UpstreamMalformed()
            age = (kind, years)
        allow = frozenset(s.casefold() for s in _str_list(record.get("labelsAllow")))
        exclude = frozenset(s.casefold() for s in _str_list(record.get("labelsExclude")))
        return cls(libraries, age, allow, exclude)

    def allows(self, library_id: str, age_rating: Optional[int], labels: Sequence[str]) -> bool:
        if self.libraries is not None and library_id not in self.libraries:
            return False
        if self.age is not None:
            kind, years = self.age
            if kind == "ALLOW_ONLY" and (age_rating is None or age_rating > years):
                return False                  # unrated content is not "allowed"
            if kind == "EXCLUDE" and age_rating is not None and age_rating >= years:
                return False
        folded = {s.casefold() for s in labels}
        if folded & self.exclude:
            return False
        if self.allow and not folded & self.allow:
            return False
        return True


class KomgaAdapter(GuardedAdapter):
    service = Service.KOMGA

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT,
                 linker: Linker = exact_name_linker, **kw):
        super().__init__(GuardedTransport(transport), timeout, **kw)
        self._linker = linker

    def __repr__(self) -> str:
        return "KomgaAdapter(<redacted>)"

    # -- what this adapter does not offer: no upstream call, nothing cached ----------------
    def continue_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        """Komga read progress belongs to the credential's user, not the member: not offered."""
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return self._not_permitted("continue")
        return SectionResult(self.service, "continue", SectionState.EMPTY, reason="not_offered")

    # -- mapping ---------------------------------------------------------------------------
    def _user_list(self, guard) -> List[Any]:
        users = self._get_json(guard, self._budget(), "/api/v2/users", None)
        if not isinstance(users, list):
            raise UpstreamMalformed()
        return users

    def _resolve_user(self, principal) -> UpstreamUser:
        users = self._user_list(self._guard.bind(None))
        return UpstreamUser(Service.KOMGA, self._linker(principal, users))

    def _access(self, user: UpstreamUser) -> _Access:
        """The member's own restrictions. The list holds every account; only this member's record is read."""
        mine = [u for u in self._user_list(self._guard.bind(None)) if _komga_user_id(u) == user.upstream_id]
        if not mine:
            raise UserGone(404)                   # the mapped account is gone
        if len(mine) > 1:
            raise UpstreamMisbehaved()
        return _Access.from_record(mine[0])

    # -- books -----------------------------------------------------------------------------
    def _series_meta(self, guard, budget, series_id: str) -> Optional[Tuple[str, Optional[int], List[str]]]:
        """(library id, age rating, sharing labels) of a series, or None if it is gone."""
        try:
            raw = self._get_json(guard, budget, f"/api/v1/series/{series_id}", None)
        except ItemGone:
            return None
        if not isinstance(raw, dict):
            raise UpstreamMalformed()
        if raw.get("id") != series_id:
            raise UpstreamMisbehaved()            # the lookup answered with a different series
        meta, library = raw.get("metadata"), raw.get("libraryId")
        if not isinstance(meta, dict) or not isinstance(library, str):
            raise UpstreamMalformed()
        age = meta.get("ageRating")
        if age is not None and (isinstance(age, bool) or not isinstance(age, int)):
            raise UpstreamMalformed()
        return library, age, list(_str_list(meta.get("sharingLabels")))

    def _book(self, raw: Any, access: _Access, series: Dict[str, Any], guard, budget, lookups: List[int]
              ) -> Tuple[Optional[MediaItem], str]:
        """(item, status): "ok", "filtered" (a legitimate drop) or "bad" (unusable: fail closed)."""
        if not isinstance(raw, dict):
            return None, "bad"
        book_id, series_id, library = raw.get("id"), raw.get("seriesId"), raw.get("libraryId")
        if not (_item_id(book_id) and _item_id(series_id) and isinstance(library, str)):
            return None, "bad"
        media = raw.get("media")
        if raw.get("deleted") is True or (isinstance(media, dict) and media.get("status") not in (None, "READY")):
            return None, "filtered"
        if series_id not in series:
            if lookups[0] >= MAX_LOOKUPS:
                return None, "filtered"           # over the lookup bound: left out, never shown unchecked
            lookups[0] += 1
            try:
                series[series_id] = self._series_meta(guard, budget, series_id)
            except UpstreamMalformed:
                series[series_id] = False             # unusable: its books are left out, never shown unchecked
        meta = series[series_id]
        if meta is False:
            return None, "bad"
        if meta is None:
            return None, "filtered"
        series_library, age, labels = meta
        if series_library != library:
            raise UpstreamMisbehaved()            # book and series disagree about the library
        if not access.allows(library, age, labels):
            return None, "filtered"
        info = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        title = clean_text(info.get("title")) or clean_text(raw.get("name")) or "Untitled"
        number = clean_text(info.get("number"), 20)
        return MediaItem(id=f"komga:{book_id}", service=Service.KOMGA, kind=Kind.COMIC, title=title,
                         handoff_url=build_handoff_url(Service.KOMGA, book_id),
                         subtitle=f"#{number}" if number else None, series=clean_text(raw.get("seriesTitle")),
                         artwork=ArtworkRef(f"komga/book/{book_id}", f"Cover of {title}")), "ok"

    def _visible_book(self, guard, budget, access: _Access, book_id: str) -> Optional[MediaItem]:
        if not _item_id(book_id):
            return None
        try:
            raw = self._get_json(guard, budget, f"/api/v1/books/{book_id}", None)
        except ItemGone:
            return None
        if isinstance(raw, dict) and raw.get("id") != book_id:
            raise UpstreamMisbehaved()
        item, status = self._book(raw, access, {}, guard, budget, [0])
        if item is None and status == "bad":
            raise UpstreamMalformed()
        return item

    # -- hooks -----------------------------------------------------------------------------
    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        return self._listing(user, limit, "/api/v1/books/latest", {}, "recent")

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        """Search is the SAME listing as recent, so it passes through the SAME per-member restriction filter
        (library, age rating, sharing labels) and the same fail-closed rules. The term is a query parameter only."""
        return self._listing(user, limit, "/api/v1/books", {"search": query}, "search")

    def _listing(self, user: UpstreamUser, limit: int, path: str, params: Dict[str, str],
                 section: str) -> SectionResult:
        access = self._access(user)                           # BEFORE any book is requested
        guard, budget = self._guard.bind(user.upstream_id), self._budget()
        size = min(MAX_PAGE, limit * 3)
        body = self._get_json(guard, budget, path, dict(params, page="0", size=str(size)))
        raws = body.get("content") if isinstance(body, dict) else None
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > size:
            raise UpstreamMisbehaved()                         # the page size was ignored
        series: Dict[str, Any] = {}
        lookups = [0]
        shown: List[MediaItem] = []
        bad = 0
        for raw in raws:
            if len(shown) >= limit:
                break
            item, status = self._book(raw, access, series, guard, budget, lookups)
            bad += status == "bad"
            if item is not None and all(item.id != s.id for s in shown):
                shown.append(item)
        if not shown and bad:
            raise UpstreamMalformed()                          # nothing usable and some drift: never "empty"
        return SectionResult.of(Service.KOMGA, section, tuple(shown))

    def _item(self, user: UpstreamUser, item_id: str) -> SectionResult:
        access = self._access(user)
        found = self._visible_book(self._guard.bind(user.upstream_id), self._budget(), access, item_id)
        return SectionResult.of(Service.KOMGA, "item", (found,) if found else ())

    def _fetch_artwork(self, user: UpstreamUser, ref: str) -> ArtworkResult:
        m = _ARTWORK_REF.fullmatch(ref)
        if m is None:
            return ArtworkResult(SectionState.EMPTY)
        book_id = m.group(1)
        access = self._access(user)
        guard, budget = self._guard.bind(user.upstream_id), self._budget()
        if self._visible_book(guard, budget, access, book_id) is None:   # member-scoped permission check
            return ArtworkResult(SectionState.EMPTY)
        return self._fetch_image(guard, budget, f"/api/v1/books/{book_id}/thumbnail", None)
