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
    An On Deck book carries `shelf="next"` (UP_NEXT) and no progress, so Home can say "Up next" instead of
    passing it off as started. Every Continue book carries `active` (owner request 2026-10-28: Home orders Continue by
    it across libraries): an in-progress book its own `readProgress.readDate`, an On Deck book the newest read date in
    its series, from one more own-key call (the member's read books, newest first).
  * New for You (owner request 2026-10-28), also with the member's own key only: their On Deck books that Komga first
    scanned (`created`) in the last FOR_YOU_DAYS, newest first. On Deck is the book after the last one read in a series
    with nothing in progress, so a new issue shows only when the member was caught up (behind, On Deck is an older
    book). A member without a key: not offered, as Continue.
  * A book with no metadata has its file name as `metadata.title`; `_title` shows "<series> #<number>" instead.
  * A reflowable EPUB (`media.mediaProfile` EPUB, not DiViNa-compatible) is an EBOOK: its own title, the author as
    subtitle, no "#<number>", and no series when the series is only its Calibre "Title (id)" folder.
  * The credential lives only inside the transport (a header, never a URL). Every request goes through
    `GuardedTransport`: GET only, an explicit four-route list (books, book, series, thumbnail), no query keys
    beyond the list. The series route is read only for a title page, and only for the series of a book the shared
    account was just allowed to read (its genres and tags live on the series).
  * Recently added (owner decision 2026-10-28) is the book list sorted by `created` (when Komga first
    scanned the file), one book per series (its newest), with no date window (owner request 2026-10-28). It is NOT
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
                        SectionState, Service, UpstreamUser, _limit, build_handoff_url, clean_names, clean_summary,
                        clean_text, credits_of, valid_upstream_id)
from .. import media_ids
from ..principal import MemberPrincipal
from ..resilience import (DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamAuthError, UpstreamError,
                          UpstreamMalformed, UpstreamMisbehaved)
from ._base import GuardedAdapter, Route, bounded_int, iso_day, iso_instant, year_from
from ._base import GuardedTransport as _Guard
from ..member_keys import MemberKeyStore, member_key_id  # noqa: F401  (member_key_id is re-exported)

SHARED_VIEWER = "shared"                      # the fixed, non-member upstream "user": a shared view, by design
_BOUND_ID = re.compile(SHARED_VIEWER)
_ID = r"[A-Za-z0-9]{6,32}"
_ARTWORK_REF = re.compile(r"komga/book/(" + _ID + r")")
MAX_PAGE = 100                   # books asked for in one page, whatever the limit
# Comics carry cover dates about two months ahead of sale; a release date further out than this is not "new".
RELEASE_AHEAD_DAYS = 92
ADDED_SORT, RELEASED_SORT = "created,desc", "metadata.releaseDate,desc"     # fixed values, never member input
READING_SORT, IN_PROGRESS = "readProgress.readDate,desc", "IN_PROGRESS"      # likewise
READ = "READ"
# New for You (owner request 2026-10-28): an On Deck book (the next unread book of a series the member is caught up on)
# that Komga first scanned in the last FOR_YOU_DAYS.
FOR_YOU_DAYS = 30
NO_MEMBER_KEY = "no_member_key"               # the provisioning trigger (provision.py)
# Two or more trailing "(...)" groups: the year, "(Digital)", the scanner's tag. Komga's `metadata.title` falls back to
# the file name when a book has no metadata, and that is how file names end ("Saga 055 (2021) (Digital) (Group)").
_FILE_TAGS = re.compile(r"(?:\s*\([^()]{0,60}\)){2,}\s*$")
UP_NEXT = "next"                 # MediaItem.shelf for an On Deck book in Continue (fixed, never upstream text)

ALLOWED_ROUTES = (
    Route("books", r"/api/v1/books", ("search", "sort", "page", "size"), user_scoped=False, not_found=RouteMissing),
    Route("book", r"/api/v1/books/(?!(?:latest|updated|ondeck)$)" + _ID, (), user_scoped=False, not_found=ItemGone),
    Route("thumbnail", r"/api/v1/books/(?!(?:latest|updated|ondeck)/)" + _ID + r"/thumbnail", (), user_scoped=False,
          not_found=ItemGone),
    # One series, for a title page's genres and tags (richer Details, 2026-10-28): only the series of a book the shared
    # account could read a moment before. "latest" and "updated" are Komga list routes that look like ids.
    Route("series", r"/api/v1/series/(?!(?:latest|updated)$)" + _ID, (), user_scoped=False, not_found=ItemGone),
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


# Komga author roles -> MediaItem.credits. Comics: writers and artists (pencils, inks, colours, covers); an EPUB novel:
# its writers. Letterers, editors and translators are left out.
_ARTIST_ROLES = frozenset({"penciller", "inker", "colorist", "cover", "artist"})


def _credits(authors: Any, ebook: bool):
    """MediaItem.credits from `metadata.authors` ({name, role}), in the book's own order."""
    named = [a for a in authors[:200] if isinstance(a, dict)] if isinstance(authors, list) else []
    writers = [a.get("name") for a in named if a.get("role") == "writer"]
    if ebook:
        return credits_of((("writers", writers or [a.get("name") for a in named]),))
    return credits_of((("writers", writers),
                       ("artists", [a.get("name") for a in named if a.get("role") in _ARTIST_ROLES])))


def _words(value: Any) -> list:
    """The strings of an upstream list of genres or tags (clean_names bounds and cleans them); else []."""
    return [x for x in value[:200] if isinstance(x, str)] if isinstance(value, list) else []


def _creator(authors: Any) -> Optional[str]:
    """`metadata.authors` is a list of {name, role} (Komga BookMetadataDto, recalled from the public API, not
    live-verified). The first writer is the creator; failing that, the first named author. Anything else: None."""
    if not isinstance(authors, list):
        return None
    named = [a for a in authors[:50] if isinstance(a, dict) and clean_text(a.get("name"))]
    pick = next((a for a in named if a.get("role") == "writer"), named[0] if named else None)
    return clean_text(pick.get("name")) if pick else None


def _title(title: Optional[str], name: Optional[str], series: Optional[str], number: Optional[str]) -> str:
    """The book's display title. A title that is really the file name (ending in scanner tags, or Komga's `name` that is
    just the series and the padded number, "Saga 055") becomes "<series> #<number>" when Komga knows both, else the
    title without its trailing tags. A file name that reads as a title is kept. Nothing is made up: every word comes
    from the book's own fields."""
    title = title or name
    if not title:
        return "Untitled"
    tagged = _FILE_TAGS.search(title)
    bare = (title == name and series and number
            and re.fullmatch(re.escape(series) + r"\s*[-#:]?\s*0*" + re.escape(number.lstrip("0") or "0"),
                             title, re.IGNORECASE))
    if not tagged and not bare:
        return title
    if series and number:
        return clean_text(f"{series} #{number}") or title
    if tagged:
        return title[:tagged.start()].strip() or title
    return title


# Calibre names each book's folder "<title> (<calibre id>)"; Komga turns that folder into a one-book series.
_CALIBRE_FOLDER = re.compile(r".+ \(\d+\)")


def _is_ebook(media: Any) -> bool:
    """A reflowable EPUB (a novel). A fixed-layout EPUB that Komga can page like images is a comic."""
    return (isinstance(media, dict) and media.get("mediaProfile") == "EPUB"
            and media.get("epubDivinaCompatible") is not True)


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
        if member_keys is not None:                    # Continue and New for You are offered (to the members with a key)
            self.not_offered = frozenset()
            self.extra_sections = self.extra_sections | {"for_you"}

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

    def for_you_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        """New for You, with the member's own key only; without one (or without member keys at all), not offered."""
        self._require_principal(principal)
        guard = self._member_guard(principal.email) if "for_you" in self.extra_sections else None
        if guard is None:
            return self._not_offered(principal, "for_you")
        limit = _limit(limit)
        return self._section(principal, "for_you", f"for_you:{limit}", lambda user: self._for_you(guard, limit))

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
        number, series = clean_text(info.get("number"), 20), clean_text(raw.get("seriesTitle"))
        creator = _creator(info.get("authors"))
        if _is_ebook(media):
            # A reflowable EPUB is a book, not an issue: its own title, the author under it, and a series only
            # when it names a real one (a Calibre folder gives each book a "Title (id)" series of its own).
            title = clean_text(info.get("title")) or clean_text(raw.get("name")) or "Untitled"
            if creator and title.endswith(f" - {creator}") and len(title) > len(creator) + 3:
                title = title[:-len(creator) - 3].strip()     # Calibre's "<title> - <author>" file name as a title
            kind, subtitle = Kind.EBOOK, creator
            if series and (series == title or _CALIBRE_FOLDER.fullmatch(series)):
                series = None
        else:
            title = _title(clean_text(info.get("title")), clean_text(raw.get("name")), series, number)
            kind, subtitle = Kind.COMIC, (f"#{number}" if number else None)
        return MediaItem(creator=creator, year=year_from(info.get("releaseDate")),
                         released=iso_day(info.get("releaseDate")),
                         id=f"komga:{book_id}", service=Service.KOMGA, kind=kind, title=title,
                         handoff_url=build_handoff_url(Service.KOMGA, book_id),
                         subtitle=subtitle, series=series,
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
            genres, tags = self._series_words(guard, budget, raw.get("seriesId"))
            item = dataclasses.replace(item, summary=clean_summary(info.get("summary")),
                                       credits=_credits(info.get("authors"), item.kind is Kind.EBOOK),
                                       genres=clean_names(genres), tags=clean_names(_words(info.get("tags")) + tags))
        return item

    def _series_words(self, guard, budget, series_id: Any) -> Tuple[list, list]:
        """(genres, tags) of a visible book's series (SeriesDto.metadata), or two empty lists when the series cannot be
        read or says nothing usable. It never fails the title page: the book itself was already allowed."""
        if not _item_id(series_id):
            return [], []
        try:
            raw = self._get_json(guard, budget, f"/api/v1/series/{series_id}", None)
        except ItemGone:
            return [], []
        except UpstreamAuthError as exc:
            if exc.status == 403:
                return [], []
            raise
        if not isinstance(raw, dict) or raw.get("id") != series_id or not isinstance(raw.get("metadata"), dict):
            return [], []
        return _words(raw["metadata"].get("genres")), _words(raw["metadata"].get("tags"))

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

    def _own_page(self, guard, budget, path: str, params: Dict[str, str], size: int) -> list:
        """One page of books read with the member's own key: the raw list (UpstreamAuthError passes to the caller)."""
        body = self._get_json(guard, budget, path, dict(params, page="0", size=str(size)))
        raws = body.get("content") if isinstance(body, dict) else None
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > size:
            raise UpstreamMisbehaved()                         # the page size was ignored
        return raws

    def _series_last_read(self, guard, budget) -> Dict[str, str]:
        """{series id: the member's newest read date in it}, from their read books, newest first (own key)."""
        out: Dict[str, str] = {}
        for raw in self._own_page(guard, budget, "/api/v1/books", {"read_status": READ, "sort": READING_SORT},
                                  MAX_PAGE):
            series_id = raw.get("seriesId") if isinstance(raw, dict) else None
            prog = raw.get("readProgress") if isinstance(raw, dict) else None
            when = iso_instant(prog.get("readDate")) if isinstance(prog, dict) else None
            if _item_id(series_id) and when and when > out.get(series_id, ""):
                out[series_id] = when
        return out

    def _for_you(self, member_guard: MemberGuardedTransport, limit: int) -> SectionResult:
        """The member's On Deck books first scanned in the last FOR_YOU_DAYS, newest first, `active` = when scanned."""
        guard, budget = member_guard.bind(SHARED_VIEWER), self._budget()
        since = datetime.now(timezone.utc) - timedelta(days=FOR_YOU_DAYS)
        try:
            raws = self._own_page(guard, budget, "/api/v1/books/ondeck", {}, MAX_PAGE)
        except UpstreamAuthError:
            return SectionResult(Service.KOMGA, "for_you", SectionState.EMPTY, reason="member_key_refused")
        shown, bad = [], 0
        for raw in raws:
            item, status = self._book(raw)
            bad += status == "bad"
            when = _created(raw) if item is not None else None
            if when is not None and when >= since and all(item.id != s.id for s in shown):
                shown.append(dataclasses.replace(item, shelf=UP_NEXT, active=iso_instant(when.isoformat())))
        if not shown and bad:
            raise UpstreamMalformed()
        shown.sort(key=lambda i: i.active or "", reverse=True)
        return SectionResult.of(Service.KOMGA, "for_you", tuple(shown[:limit]))

    def _reading(self, member_guard: MemberGuardedTransport, limit: int) -> SectionResult:
        """In-progress books (most recently read first), then On Deck, as one list. Every call uses the member's own
        key. A refused key (401/403) is the member's, not the service's: an empty row, never counted."""
        guard, budget = member_guard.bind(SHARED_VIEWER), self._budget()
        shown, bad, seen = [], 0, set()
        last_read: Optional[Dict[str, str]] = None
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
                    prog = raw.get("readProgress")
                    item = dataclasses.replace(item, progress_fraction=self._progress(raw),
                                               active=iso_instant(prog.get("readDate")) if isinstance(prog, dict)
                                               else None)
                else:                                          # On Deck: the next unread book, nothing read yet
                    if last_read is None:
                        try:
                            last_read = self._series_last_read(guard, budget)
                        except UpstreamError:                  # only the order suffers: the row still shows
                            last_read = {}
                    item = dataclasses.replace(item, shelf=UP_NEXT, active=last_read.get(raw.get("seriesId")))
                shown.append(item)
        if not shown and bad:
            raise UpstreamMalformed()                          # nothing usable and some drift: never "empty"
        return SectionResult.of(Service.KOMGA, "continue", tuple(shown))

    # -- hooks -----------------------------------------------------------------------------
    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        def keep(raw):                                         # no date window (owner request 2026-10-28)
            return _created(raw) is not None
        return self._listing(user, limit, "/api/v1/books", {"sort": ADDED_SORT}, "recent", keep=keep,
                             per_series=True, size=MAX_PAGE)

    def _shelves_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        """One shelf, New releases: the newest release dates, one book per series. Shown as Recently released when
        Recently added is empty."""
        latest = _today() + timedelta(days=RELEASE_AHEAD_DAYS)

        def keep(raw):
            day = _released(raw)
            return day is not None and day <= latest
        return self._listing(user, limit, "/api/v1/books", {"sort": RELEASED_SORT}, "shelves", keep=keep,
                             per_series=True, size=MAX_PAGE, shelf="new")

    def _released_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        """Home's New releases (owner decision 2026-10-28): the newest release dates, one book per series, as its own
        section. Cover dates run ahead of sale, so Home sorts a future date as today.

        Up to `limit` of EACH kind (owner request 2026-10-28, the Books chip): the newest releases are nearly all
        issues, so one `limit`-long list would never hold a novel. A novel's release date is usually years old, so
        the newest page still may hold fewer than `limit` of them; then the library's newest ADDITIONS (the Recently
        added order) are read once more for novels that have a release day, and fill the rest. Komga's book list has
        no filter by kind (GET, and no `media_profile` key in the allow-list), so this is a second page, not a query."""
        latest = _today() + timedelta(days=RELEASE_AHEAD_DAYS)

        def keep(raw):
            day = _released(raw)
            return day is not None and day <= latest
        out = self._listing(user, limit, "/api/v1/books", {"sort": RELEASED_SORT}, "released", keep=keep,
                            per_series=True, size=MAX_PAGE, per_kind=True)
        novels = [it for it in out.items if it.kind is Kind.EBOOK]
        if len(novels) >= limit:
            return out
        added = self._listing(user, limit - len(novels), "/api/v1/books", {"sort": ADDED_SORT}, "released",
                              keep=keep, per_series=True, size=MAX_PAGE, kinds=(Kind.EBOOK,))
        have = {it.id for it in out.items}
        return SectionResult.of(Service.KOMGA, "released",
                                out.items + tuple(it for it in added.items if it.id not in have))

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        """Search is the SAME shared-account listing as recent (contract 12.2): Komga applies the one regular
        account's library sharing to the answer; there is no per-member filter. The term is a query parameter only."""
        return self._listing(user, limit, "/api/v1/books", {"search": query}, "search")

    def _listing(self, user: UpstreamUser, limit: int, path: str, params: Dict[str, str], section: str, *,
                 keep=None, per_series: bool = False, size: Optional[int] = None,
                 shelf: Optional[str] = None, per_kind: bool = False,
                 kinds: Optional[Tuple[Kind, ...]] = None) -> SectionResult:
        """One page of books, in the upstream's order. `keep` drops a book legitimately (not drift); `per_series`
        keeps only the first (newest) book of each series; `per_kind` counts `limit` for each kind apart (issues and
        novels), so a long run of one cannot crowd the other out of the page; `kinds` keeps only those kinds."""
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
            if len(shown) >= limit and not per_kind:
                break
            item, status = self._book(raw)
            bad += status == "bad"
            if item is None or (keep is not None and not keep(raw)) or any(item.id == s.id for s in shown):
                continue
            if kinds is not None and item.kind not in kinds:
                continue
            if per_kind and sum(1 for s in shown if s.kind is item.kind) >= limit:
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
