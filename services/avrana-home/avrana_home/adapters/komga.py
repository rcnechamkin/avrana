"""Komga read-only catalogue adapter: "Recently added" and one shelf, New releases (comics). A SHARED REGULAR-ACCOUNT VIEW.

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
    can never be shown as a member's own. The shared account's route table has no `ondeck`, read-list,
    collection or per-user route.
  * Continue reading (owner decision 2026-10-28) is offered ONLY to a member whose OWN Komga API key Home holds
    (`member_keys`, a live MemberKeyStore filed by the member's signed email; docs/runbooks/komga-member-keys.md).
    It is that member's in-progress books, then their On Deck (the next unread book of a series they have
    started), read with their key through a separate two-route allow-list. The shared account is never used for
    it. A member without a key gets an empty row, never cached: reason `no_member_key` when Home may make their
    key (provision.py, "Home does it", 2026-10-28), else `not_offered`. A refused member key is that member's
    problem: an empty row, never a count against the circuit every member shares.
  * The credential lives only inside the transport (a header, never a URL). Every request goes through
    `GuardedTransport`: GET only, an explicit three-route list (books, book, thumbnail), no query keys
    beyond the list.
  * Recently added (owner decision 2026-10-28) is the book list sorted by `created` (when Komga first
    scanned the file), only books added in the last RECENT_DAYS, one book per series (its newest). It is NOT
    `/api/v1/books/latest`: live, that route orders by last modification, so one new issue lifted its whole
    series, and a 2025 bulk scan shares one `created` second. The New releases shelf is the same list sorted
    by `metadata.releaseDate`, one book per series; Home shows it as Recently released when nothing is new.
  * Hand-off and artwork never use an upstream URL: the contract builder makes the hand-off URL from the
    validated book id.

If any member ever has a Komga restriction, the shared view would show that member more than Komga does.
The earlier admin-key, per-member design (user listing, restriction filter, link-table linker) was REMOVED,
not kept behind a flag: it needed an admin key that reaches everything, and the owner will not issue one.

Route and field names are recalled from Komga's public API documentation and are UNVERIFIED.
"""
from __future__ import annotations

import dataclasses
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, DEFAULT_LIMIT, Kind, MediaItem, SectionResult,
                        SectionState, Service, UpstreamUser, _limit, build_handoff_url, clean_summary, clean_text,
                        valid_upstream_id)
from .. import media_ids
from ..principal import MemberPrincipal
from ..resilience import (DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamAuthError,
                          UpstreamMalformed, UpstreamMisbehaved)
from ._base import GuardedAdapter, Route, bounded_int, iso_day, year_from
from ._base import GuardedTransport as _Guard
from ..member_keys import MemberKeyStore, member_key_id  # noqa: F401  (member_key_id is re-exported)

SHARED_VIEWER = "shared"                      # the fixed, non-member upstream "user": a shared view, by design
_BOUND_ID = re.compile(SHARED_VIEWER)
_ID = r"[A-Za-z0-9]{6,32}"
_ARTWORK_REF = re.compile(r"komga/book/(" + _ID + r")")
MAX_PAGE = 100                   # books asked for in one page, whatever the limit
# Recently added means added in the last two months (owner decision 2026-10-28, as Audiobookshelf's of 2026-10-27).
RECENT_DAYS = 60
# Comics carry cover dates about two months ahead of sale; a release date further out than this is not "new".
RELEASE_AHEAD_DAYS = 92
ADDED_SORT, RELEASED_SORT = "created,desc", "metadata.releaseDate,desc"     # fixed values, never member input
READING_SORT, IN_PROGRESS = "readProgress.readDate,desc", "IN_PROGRESS"      # likewise
NO_MEMBER_KEY = "no_member_key"               # the provisioning trigger (provision.py)

ALLOWED_ROUTES = (
    Route("books", r"/api/v1/books", ("search", "sort", "page", "size"), user_scoped=False, not_found=RouteMissing),
    Route("book", r"/api/v1/books/(?!(?:latest|updated|ondeck)$)" + _ID, (), user_scoped=False, not_found=ItemGone),
    Route("thumbnail", r"/api/v1/books/(?!(?:latest|updated|ondeck)/)" + _ID + r"/thumbnail", (), user_scoped=False,
          not_found=ItemGone),
)


class GuardedTransport(_Guard):
    """The Komga allow-list around an inner Transport."""

    def __init__(self, inner, bound_user_id: Optional[str] = None):
        super().__init__(inner, ALLOWED_ROUTES, _BOUND_ID, bound_user_id)

    def _clone(self, user_id):
        return GuardedTransport(self._inner, user_id)


# One member's OWN key (never the shared account's): their in-progress books and their On Deck, nothing else.
MEMBER_ROUTES = (
    Route("reading", r"/api/v1/books", ("read_status", "sort", "page", "size"), user_scoped=False,
          not_found=RouteMissing),
    Route("ondeck", r"/api/v1/books/ondeck", ("page", "size"), user_scoped=False, not_found=RouteMissing),
)


class MemberGuardedTransport(_Guard):
    """The allow-list around ONE member's own-key transport."""

    def __init__(self, inner, bound_user_id: Optional[str] = None):
        super().__init__(inner, MEMBER_ROUTES, _BOUND_ID, bound_user_id)

    def _clone(self, user_id):
        return MemberGuardedTransport(self._inner, user_id)



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


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _created(raw: dict) -> Optional[datetime]:
    """When Komga first scanned the book (`created`, ISO 8601), or None: a book without one is never "recent"."""
    value = raw.get("created")
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _released(raw: dict) -> Optional[date]:
    info = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = info.get("releaseDate")
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


class KomgaAdapter(GuardedAdapter):
    service = Service.KOMGA
    not_offered = frozenset({"continue"})
    extra_sections = frozenset({"shelves", "released"})

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT, *,
                 owner_confirms_no_member_restrictions: bool = False,
                 member_keys: Optional[MemberKeyStore] = None,
                 member_transport: Optional[Callable[[str], Transport]] = None,
                 provisioning: bool = False, **kw):
        # A shared view (contract 12.2, owner decision 2026-10-15): every member sees what the regular
        # account sees, so Komga's own per-member restrictions are NOT applied. The owner must opt in on
        # purpose, and only while no member has a Komga restriction.
        if owner_confirms_no_member_restrictions is not True:
            raise ValueError("Komga adapter is a shared view; the owner must confirm no member is restricted")
        super().__init__(GuardedTransport(transport), timeout, **kw)
        if (member_keys is None) != (member_transport is None):
            raise ValueError("member_keys and member_transport go together")
        self._keys = member_keys
        self._member_transport = member_transport     # one member's key -> an inner Transport carrying it
        self._guards: Dict[str, MemberGuardedTransport] = {}
        self._provisioning = bool(provisioning) and member_keys is not None
        if member_keys is not None:                    # Continue is offered (to the members with a key)
            self.not_offered = frozenset()

    def __repr__(self) -> str:
        return "KomgaAdapter(<redacted>)"

    @property
    def member_keys(self) -> Optional[MemberKeyStore]:
        """The live keys store (provision.py files new keys in it), or None."""
        return self._keys

    # -- what this adapter does not offer: no upstream call, nothing cached ----------------
    def continue_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        """The member's own reading, with their own key; without one, not offered (the shared account's progress
        is never anyone's). The group is checked first (in `_not_offered` or `_section`), before any cache read."""
        self._require_principal(principal)
        guard = self._member_guard(principal.email)
        if guard is None:
            out = self._not_offered(principal, "continue")
            if self._provisioning and out.reason == "not_offered" and member_key_id(principal.email):
                out = SectionResult(self.service, "continue", SectionState.EMPTY, reason=NO_MEMBER_KEY)
            return out
        limit = _limit(limit)
        return self._section(principal, "continue", f"continue:{limit}",
                             lambda user: self._reading(guard, limit))

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
                         released=iso_day(info.get("releaseDate")),
                         id=f"komga:{book_id}", service=Service.KOMGA, kind=Kind.COMIC, title=title,
                         handoff_url=build_handoff_url(Service.KOMGA, book_id),
                         subtitle=f"#{number}" if number else None, series=clean_text(raw.get("seriesTitle")),
                         artwork=ArtworkRef(f"komga/book/{book_id}", f"Cover of {title}"),
                         external_ids=media_ids.from_book_metadata(info)), "ok"

    def _visible_book(self, guard, budget, book_id: str, summary: bool = False) -> Optional[MediaItem]:
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
        if item is not None and summary:                   # title page only (R2-C); `metadata` is a dict or absent
            info = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            item = dataclasses.replace(item, summary=clean_summary(info.get("summary")))
        return item

    def _member_guard(self, email: Any) -> Optional[MemberGuardedTransport]:
        """The allow-listed transport for this member's CURRENT key (the store follows the file), or None."""
        if self._keys is None:
            return None
        key = self._keys.get(email)
        if key is None:
            return None
        guard = self._guards.get(key)
        if guard is None:
            if len(self._guards) > 2 * 500:                # replaced keys: start over rather than grow
                self._guards.clear()
            guard = self._guards[key] = MemberGuardedTransport(self._member_transport(key))
        return guard

    @staticmethod
    def _progress(raw: dict) -> Optional[float]:
        """The member's OWN progress (their key's `readProgress`), as a fraction, or None."""
        prog, media = raw.get("readProgress"), raw.get("media")
        if not isinstance(prog, dict) or not isinstance(media, dict) or prog.get("completed") is True:
            return None
        page, pages = bounded_int(prog.get("page")), bounded_int(media.get("pagesCount"))
        if page is None or pages is None or pages <= 0 or not 0 < page < pages:
            return None
        return page / pages

    def _reading(self, member_guard: MemberGuardedTransport, limit: int) -> SectionResult:
        """In-progress books (most recently read first), then On Deck, as one list. Both calls use the member's own
        key. A refused key (401/403) is the member's, not the service's: an empty row, never counted."""
        guard, budget = member_guard.bind(SHARED_VIEWER), self._budget()
        shown, bad, seen = [], 0, set()
        pages = (("/api/v1/books", {"read_status": IN_PROGRESS, "sort": READING_SORT}, True),
                 ("/api/v1/books/ondeck", {}, False))
        for path, params, in_progress in pages:
            if len(shown) >= limit:
                break
            size = limit - len(shown)
            try:
                body = self._get_json(guard, budget, path, dict(params, page="0", size=str(size)))
            except UpstreamAuthError:
                return SectionResult(Service.KOMGA, "continue", SectionState.EMPTY, reason="member_key_refused")
            raws = body.get("content") if isinstance(body, dict) else None
            if not isinstance(raws, list):
                raise UpstreamMalformed()
            if len(raws) > size:
                raise UpstreamMisbehaved()                     # the page size was ignored
            for raw in raws:
                item, status = self._book(raw)
                bad += status == "bad"
                if item is None or item.id in seen:
                    continue
                seen.add(item.id)
                if in_progress:
                    item = dataclasses.replace(item, progress_fraction=self._progress(raw))
                shown.append(item)
        if not shown and bad:
            raise UpstreamMalformed()                          # nothing usable and some drift: never "empty"
        return SectionResult.of(Service.KOMGA, "continue", tuple(shown))

    # -- hooks -----------------------------------------------------------------------------
    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)

        def keep(raw):
            when = _created(raw)
            return when is not None and when >= since
        return self._listing(user, limit, "/api/v1/books", {"sort": ADDED_SORT}, "recent", keep=keep,
                             per_series=True, size=MAX_PAGE)

    def _shelves_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        """One shelf, New releases: the newest release dates, one book per series. Shown as Recently released when
        nothing was added in the last RECENT_DAYS."""
        latest = _today() + timedelta(days=RELEASE_AHEAD_DAYS)

        def keep(raw):
            day = _released(raw)
            return day is not None and day <= latest
        return self._listing(user, limit, "/api/v1/books", {"sort": RELEASED_SORT}, "shelves", keep=keep,
                             per_series=True, size=MAX_PAGE, shelf="new")

    def _released_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        """Home's New releases (owner decision 2026-10-28): the same listing as the New releases shelf, as its own
        section. Cover dates run ahead of sale, so Home sorts a future date as today."""
        latest = _today() + timedelta(days=RELEASE_AHEAD_DAYS)

        def keep(raw):
            day = _released(raw)
            return day is not None and day <= latest
        return self._listing(user, limit, "/api/v1/books", {"sort": RELEASED_SORT}, "released", keep=keep,
                             per_series=True, size=MAX_PAGE)

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        """Search is the SAME shared-account listing as recent (contract 12.2): Komga applies the one regular
        account's library sharing to the answer; there is no per-member filter. The term is a query parameter only."""
        return self._listing(user, limit, "/api/v1/books", {"search": query}, "search")

    def _listing(self, user: UpstreamUser, limit: int, path: str, params: Dict[str, str], section: str, *,
                 keep=None, per_series: bool = False, size: Optional[int] = None,
                 shelf: Optional[str] = None) -> SectionResult:
        """One page of books, in the upstream's order. `keep` drops a book legitimately (not drift); `per_series`
        keeps only the first (newest) book of each series."""
        guard, budget = self._guard.bind(user.upstream_id), self._budget()
        size = min(MAX_PAGE, size or limit * 3)
        body = self._get_json(guard, budget, path, dict(params, page="0", size=str(size)))
        raws = body.get("content") if isinstance(body, dict) else None
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > size:
            raise UpstreamMisbehaved()                         # the page size was ignored
        shown, series = [], set()
        bad = 0
        for raw in raws:
            if len(shown) >= limit:
                break
            item, status = self._book(raw)
            bad += status == "bad"
            if item is None or (keep is not None and not keep(raw)) or any(item.id == s.id for s in shown):
                continue
            if per_series:
                key = raw.get("seriesId") if isinstance(raw.get("seriesId"), str) else item.id
                if key in series:
                    continue
                series.add(key)
            shown.append(dataclasses.replace(item, shelf=shelf) if shelf else item)
        if not shown and bad:
            raise UpstreamMalformed()                          # nothing usable and some drift: never "empty"
        return SectionResult.of(Service.KOMGA, section, tuple(shown))

    def _item(self, user: UpstreamUser, item_id: str) -> SectionResult:
        found = self._visible_book(self._guard.bind(user.upstream_id), self._budget(), item_id, summary=True)
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
