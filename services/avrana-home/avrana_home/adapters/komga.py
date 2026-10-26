"""Komga read-only catalogue adapter: one section, "Recently added" (comics). A SHARED REGULAR-ACCOUNT VIEW.

Status: proposed, not deployed. Standard library only. Proven only against HAND-WRITTEN fixtures that
are unverified against the deployed Komga; a recorded, read-only contract check is a separate,
owner-approved step that must happen before any real member data is read (ADAPTER-CONTRACT.md, section 12.5).

OWNER DECISION, 2026-10-15 (contract section 12.2): Komga is a SHARED view, the same pattern as Calibre-Web
(section 13.2). The home holds ONE dedicated regular (non-admin) Komga account and NO admin key. Nobody will
ever have Komga restrictions, so there is nothing per member to enforce. What this module does:

  * The Authentik group `avrana-comics` is checked before any upstream call (and before any cache read).
  * There is no user listing (`/api/v2/users` is admin-only and is not in the route table) and no per-member
    mapping: every member who holds the group is mapped to the same fixed, non-member "shared viewer"
    (`SHARED_VIEWER`). `resolve_user` never names a real Komga account.
  * No per-member restriction filter exists. Every member sees what the one regular account sees; Komga
    itself applies that account's library sharing to the answers. The invariant that no member is restricted
    is the owner's, and the constructor refuses unless `owner_confirms_no_member_restrictions` is True.
  * Read progress in a book response belongs to the shared account, not the member: it is never read, so it
    can never be shown as a member's own. "Continue" is not offered. The `ondeck`, read-list, collection and
    per-user routes are not in the route table.
  * The credential lives only inside the transport (a header, never a URL). Every request goes through
    `GuardedTransport`: GET only, an explicit four-route list (latest, book, search, thumbnail), no query
    keys beyond the list.
  * Hand-off and artwork never use an upstream URL: the contract builder makes the hand-off URL from the
    validated book id.

If any member ever has a Komga restriction, the shared view would show that member more than Komga does.
The earlier admin-key, per-member design (user listing, restriction filter, link-table linker) was REMOVED,
not kept behind a flag: it needed an admin key that reaches everything, and the owner will not issue one.

Route and field names are recalled from Komga's public API documentation and are UNVERIFIED.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, DEFAULT_LIMIT, Kind, MediaItem, SectionResult,
                        SectionState, Service, UpstreamUser, build_handoff_url, clean_text,
                        valid_upstream_id)
from .. import media_ids
from ..principal import MemberPrincipal
from ..resilience import (DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamAuthError,
                          UpstreamMalformed, UpstreamMisbehaved)
from ._base import GuardedAdapter, Route, year_from
from ._base import GuardedTransport as _Guard

SHARED_VIEWER = "shared"                      # the fixed, non-member upstream "user": a shared view, by design
_BOUND_ID = re.compile(SHARED_VIEWER)
_ID = r"[A-Za-z0-9]{6,32}"
_ARTWORK_REF = re.compile(r"komga/book/(" + _ID + r")")
MAX_PAGE = 100                   # books asked for in one page, whatever the limit

ALLOWED_ROUTES = (
    Route("latest", r"/api/v1/books/latest", ("page", "size"), user_scoped=False, not_found=RouteMissing),
    Route("book", r"/api/v1/books/(?!(?:latest|updated|ondeck)$)" + _ID, (), user_scoped=False, not_found=ItemGone),
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


_RESERVED = frozenset({"latest", "updated", "ondeck"})     # Komga sub-routes that look like ids (UNVERIFIED list)


def _item_id(value: Any) -> bool:
    return valid_upstream_id(Service.KOMGA, value) and value not in _RESERVED


def _creator(authors: Any) -> Optional[str]:
    """`metadata.authors` is a list of {name, role} (Komga BookMetadataDto, recalled from the public API, not
    live-verified). The first writer is the creator; failing that, the first named author. Anything else: None."""
    if not isinstance(authors, list):
        return None
    named = [a for a in authors[:50] if isinstance(a, dict) and clean_text(a.get("name"))]
    pick = next((a for a in named if a.get("role") == "writer"), named[0] if named else None)
    return clean_text(pick.get("name")) if pick else None


class KomgaAdapter(GuardedAdapter):
    service = Service.KOMGA
    not_offered = frozenset({"continue"})

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT, *,
                 owner_confirms_no_member_restrictions: bool = False, **kw):
        # A shared view (contract 12.2, owner decision 2026-10-15): every member sees what the regular
        # account sees, so Komga's own per-member restrictions are NOT applied. The owner must opt in on
        # purpose, and only while no member has a Komga restriction.
        if owner_confirms_no_member_restrictions is not True:
            raise ValueError("Komga adapter is a shared view; the owner must confirm no member is restricted")
        super().__init__(GuardedTransport(transport), timeout, **kw)

    def __repr__(self) -> str:
        return "KomgaAdapter(<redacted>)"

    # -- what this adapter does not offer: no upstream call, nothing cached ----------------
    def continue_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        """Read progress belongs to the shared account, not the member: not offered."""
        return self._not_offered(principal, "continue")

    # -- mapping: none. A shared view (OWNER DECISION, contract 12.2) ------------------------
    def _resolve_user(self, principal) -> UpstreamUser:
        return UpstreamUser(Service.KOMGA, SHARED_VIEWER)

    # -- books -----------------------------------------------------------------------------
    @staticmethod
    def _book(raw: Any) -> Tuple[Optional[MediaItem], str]:
        """(item, status): "ok", "filtered" (a legitimate drop) or "bad" (unusable). Only explicit fields are
        read: `readProgress` (the shared account's) is never touched."""
        if not isinstance(raw, dict):
            return None, "bad"
        book_id = raw.get("id")
        if not _item_id(book_id):
            return None, "bad"
        media = raw.get("media")
        if raw.get("deleted") is True or (isinstance(media, dict) and media.get("status") not in (None, "READY")):
            return None, "filtered"
        info = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        title = clean_text(info.get("title")) or clean_text(raw.get("name")) or "Untitled"
        number = clean_text(info.get("number"), 20)
        return MediaItem(creator=_creator(info.get("authors")), year=year_from(info.get("releaseDate")),
                         id=f"komga:{book_id}", service=Service.KOMGA, kind=Kind.COMIC, title=title,
                         handoff_url=build_handoff_url(Service.KOMGA, book_id),
                         subtitle=f"#{number}" if number else None, series=clean_text(raw.get("seriesTitle")),
                         artwork=ArtworkRef(f"komga/book/{book_id}", f"Cover of {title}"),
                         external_ids=media_ids.from_book_metadata(info)), "ok"

    def _visible_book(self, guard, budget, book_id: str) -> Optional[MediaItem]:
        """The book if the shared account can see it, else None. Komga answers 404 for an unknown book and 403
        for a book in a library or behind a content restriction the account may not use (BookController, from
        the source; UNVERIFIED live). Both are the same "hidden" here, so a title page cannot tell them apart
        (no existence oracle). The 403 is handled inside the hook, so it never reaches the shared circuit; a
        refused credential (401) still does."""
        if not _item_id(book_id):
            return None
        try:
            raw = self._get_json(guard, budget, f"/api/v1/books/{book_id}", None)
        except ItemGone:
            return None
        except UpstreamAuthError as exc:
            if exc.status == 403:
                return None
            raise
        if isinstance(raw, dict) and raw.get("id") != book_id:
            raise UpstreamMisbehaved()
        item, status = self._book(raw)
        if item is None and status == "bad":
            raise UpstreamMalformed()
        return item

    # -- hooks -----------------------------------------------------------------------------
    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        return self._listing(user, limit, "/api/v1/books/latest", {}, "recent")

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        """Search is the SAME shared-account listing as recent (contract 12.2): Komga applies the one regular
        account's library sharing to the answer; there is no per-member filter. The term is a query parameter only."""
        return self._listing(user, limit, "/api/v1/books", {"search": query}, "search")

    def _listing(self, user: UpstreamUser, limit: int, path: str, params: Dict[str, str],
                 section: str) -> SectionResult:
        guard, budget = self._guard.bind(user.upstream_id), self._budget()
        size = min(MAX_PAGE, limit * 3)
        body = self._get_json(guard, budget, path, dict(params, page="0", size=str(size)))
        raws = body.get("content") if isinstance(body, dict) else None
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > size:
            raise UpstreamMisbehaved()                         # the page size was ignored
        shown = []
        bad = 0
        for raw in raws:
            if len(shown) >= limit:
                break
            item, status = self._book(raw)
            bad += status == "bad"
            if item is not None and all(item.id != s.id for s in shown):
                shown.append(item)
        if not shown and bad:
            raise UpstreamMalformed()                          # nothing usable and some drift: never "empty"
        return SectionResult.of(Service.KOMGA, section, tuple(shown))

    def _item(self, user: UpstreamUser, item_id: str) -> SectionResult:
        found = self._visible_book(self._guard.bind(user.upstream_id), self._budget(), item_id)
        return SectionResult.of(Service.KOMGA, "item", (found,) if found else ())

    def _fetch_artwork(self, user: UpstreamUser, ref: str) -> ArtworkResult:
        m = _ARTWORK_REF.fullmatch(ref)
        if m is None:
            return ArtworkResult(SectionState.EMPTY)
        book_id = m.group(1)
        if book_id in _RESERVED:
            return ArtworkResult(SectionState.EMPTY)
        # The shared account's own rights decide whether this cover exists (404 = EMPTY); there is no
        # per-member visibility to check (contract 12.2).
        return self._fetch_image(self._guard.bind(user.upstream_id), self._budget(),
                                 f"/api/v1/books/{book_id}/thumbnail", None)
