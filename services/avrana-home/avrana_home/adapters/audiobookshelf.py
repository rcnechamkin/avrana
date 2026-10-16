"""Audiobookshelf read-only member adapter: "Continue listening", covers and search.

Status: proposed, not deployed. Standard library only. Proven only against HAND-WRITTEN fixtures that
are unverified against the deployed Audiobookshelf; a recorded, read-only contract check is a separate,
owner-approved step that must happen before any real member data is read (ADAPTER-CONTRACT.md,
"Audiobookshelf").

How it stays member-scoped with an ADMIN-capable token (Audiobookshelf has no impersonation):

  * The token lives only inside the transport. Every request goes through `GuardedTransport`: GET
    only, an explicit route list, and the member's upstream user id carried in the PATH of every
    user route, which the guard compares with the bound id (never a different member's, never none).
  * The only request that is not bound to a member is the user list used for mapping. Item, cover,
    library-list and library-search requests need a bound member but cannot carry one; everything they
    return is re-checked against that member's own permissions before it is shown.
  * The member's own user record is read from `/api/users/{id}`; its id must equal the bound id, and
    every progress entry in it must name that same user (an entry that names another user, or names
    nobody, is `UpstreamMisbehaved` and the whole section is discarded).
  * Item metadata is fetched with the admin token, so it is NOT member-scoped by the upstream. An item
    is shown only after it is checked against THAT user's own permissions from the user record:
    library access, the tag allow or deny list and the explicit-content flag. Any missing or wrongly
    typed permission field fails closed: a malformed permission record makes the section unavailable
    (never an unfiltered list) and a malformed item is left out.
  * Covers: the cover route cannot carry the member, so its scoping rests on the adapter. A cover
    (`audiobookshelf/cover/<item id>`) is fetched only after the SAME checks as the section: group
    first (no upstream call without it, nor for a malformed ref), then the member's own user record
    (active, permissions parsed fail closed), then the item itself through `_visible` (library, tags,
    explicit flag, a book, not missing or invalid; a different id answered is `UpstreamMisbehaved`).
    An item the member may not see, an unknown item and an item without a cover are all the same
    neutral EMPTY. The bytes go through the shared image check (allowed raster type, magic number,
    MAX_IMAGE_BYTES) and are cached per member only.
  * Search: group first (the base class, before the term is read), then the term is cleaned by the
    contract's `clean_query` (wildcards neutralised) and sent ONLY as the `q` query parameter. The
    member's own record is read and its permissions parsed BEFORE any library is searched. The
    libraries searched are the member's own `librariesAccessible`, or, only when that record grants
    every library, the upstream's library list (book libraries). Each library is searched with
    `GET /api/libraries/{id}/search?q=&limit=` and EVERY hit goes through `_visible` (library, tags,
    explicit, book, not missing or invalid), exactly as the section does. A hit from a library that
    was not searched, or more hits than asked for, is `UpstreamMisbehaved`; a non-object body or a
    missing hit list is `UpstreamMalformed` (UNAVAILABLE, never an empty or unfiltered list). Results
    are never cached (base class). UNVERIFIED response shape, recalled from the public API docs:
    `{"book": [{"libraryItem": {expanded library item}, "matchKey": ..., "matchText": ...}], "tags":
    [...], "authors": [...], "series": [...], "narrators": [...]}` for a book library (`podcast` in
    place of `book` for a podcast library); `GET /api/libraries` as `{"libraries": [{"id", "name",
    "mediaType"}, ...]}`.

Route and field names are recalled from Audiobookshelf's public API documentation and are UNVERIFIED.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, DEFAULT_LIMIT, Kind, MappingFailed, MediaItem,
                        SectionResult, SectionState, Service, UpstreamUser, build_handoff_url, clean_text,
                        valid_upstream_id)
from ..principal import MemberPrincipal
from ..resilience import (DEFAULT_TIMEOUT, FanOutSpent, ItemGone, RouteMissing, Transport, UpstreamMalformed,
                          UpstreamMisbehaved, UpstreamTimeout, UserGone)
from ._base import GuardedAdapter, Route, bounded_int, lookup_username, match_exactly_one, member_override
from ._base import GuardedTransport as _Guard

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_BOUND_ID = re.compile(_UUID)
_ITEM_PATH = r"(?:li_[a-z0-9]{6,40}|" + _UUID + r")"   # old "li_" ids and current UUID ids (contract.py)
_ARTWORK_REF = re.compile(r"audiobookshelf/cover/(" + _ITEM_PATH + r")")
COVER_QUERY = {"width": "400", "format": "jpeg"}    # same size as Jellyfin's maxWidth; format UNVERIFIED
MAX_LOOKUPS = 24                # item lookups per request, however long the progress list is
# Continue needs one item lookup per progress entry, one after another, inside the one request budget. A lookup
# is started only while at least this much of the budget is left; once the budget is short, Continue answers
# with the items it already has. A slow-but-answering service must never look like an outage (AVR-503 F1).
LOOKUP_RESERVE = 0.4            # seconds
_LIBRARY_PATH = r"(?:lib_[a-z0-9]{3,40}|" + _UUID + r")"   # old "lib_" ids and current UUID ids (UNVERIFIED)
_LIBRARY_ID = re.compile(_LIBRARY_PATH)
MAX_LIBRARIES = 6               # libraries searched per request (each is one upstream call)
MAX_SEARCH_PAGE = 50            # hits asked for per library, whatever the limit

ALLOWED_ROUTES = (
    Route("users", r"/api/users", (), user_scoped=False, needs_user=False, not_found=RouteMissing),
    Route("user", r"/api/users/(?P<user>" + _UUID + r")", (), user_scoped=True, bind_in="path",
          not_found=UserGone),
    Route("item", r"/api/items/" + _ITEM_PATH, ("expanded",), user_scoped=False, not_found=ItemGone),
    # The cover route cannot carry the member: ITS scoping rests on `_fetch_artwork` running `_visible`
    # for the same item, with that member's own permissions, first.
    Route("cover", r"/api/items/" + _ITEM_PATH + r"/cover", ("width", "format"), user_scoped=False,
          not_found=ItemGone),
    # Search. Neither route can carry the member: the library list is read only for a member whose OWN
    # record grants every library, and every hit goes through `_visible` with that member's permissions.
    # The term travels only as the `q` query parameter, already cleaned by the contract's `clean_query`.
    Route("libraries", r"/api/libraries", (), user_scoped=False, not_found=RouteMissing),
    Route("search", r"/api/libraries/" + _LIBRARY_PATH + r"/search", ("q", "limit"), user_scoped=False,
          not_found=ItemGone),
)


class GuardedTransport(_Guard):
    """The Audiobookshelf allow-list around an inner Transport."""

    def __init__(self, inner, bound_user_id: Optional[str] = None):
        super().__init__(inner, ALLOWED_ROUTES, _BOUND_ID, bound_user_id)

    def _clone(self, user_id):
        return GuardedTransport(self._inner, user_id)


class _Access:
    """What one user may see, read from that user's own record (fail closed on anything odd)."""

    def __init__(self, libraries: Optional[frozenset], tags: Optional[Tuple[bool, frozenset]],
                 explicit: bool):
        self.libraries = libraries        # None: every library
        self.tags = tags                  # None: every tag; else (is_deny_list, selected tags)
        self.explicit = explicit

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "_Access":
        perms = record.get("permissions")
        if not isinstance(perms, dict):
            raise UpstreamMalformed()
        for flag in ("accessAllLibraries", "accessAllTags", "accessExplicitContent"):
            if not isinstance(perms.get(flag), bool):
                raise UpstreamMalformed()
        libraries = None
        if not perms["accessAllLibraries"]:
            libs = record.get("librariesAccessible")
            if not isinstance(libs, list) or not all(isinstance(x, str) for x in libs):
                raise UpstreamMalformed()
            libraries = frozenset(libs)
        tags = None
        if not perms["accessAllTags"]:
            selected = record.get("itemTagsSelected")
            deny = perms.get("selectedTagsNotAccessible")
            if (not isinstance(selected, list) or not all(isinstance(x, str) for x in selected)
                    or not isinstance(deny, bool)):
                raise UpstreamMalformed()
            tags = (deny, frozenset(selected))
        return cls(libraries, tags, perms["accessExplicitContent"])

    def allows(self, library_id: str, item_tags: List[str], explicit: bool) -> bool:
        if self.libraries is not None and library_id not in self.libraries:
            return False
        if explicit and not self.explicit:
            return False
        if self.tags is not None:
            deny, selected = self.tags
            hit = any(t in selected for t in item_tags)
            if deny and hit:
                return False
            if not deny and not hit:
                return False
        return True


def _require_active(record: Dict[str, Any]) -> None:
    active = record.get("isActive")
    if not isinstance(active, bool):
        raise UpstreamMalformed()                         # a required field is missing or mistyped
    if not active:
        raise MappingFailed("disabled")


def _left(budget) -> float:
    try:
        return budget.remaining()
    except UpstreamTimeout:
        return 0.0


class AudiobookshelfAdapter(GuardedAdapter):
    service = Service.AUDIOBOOKSHELF
    not_offered = frozenset({"recent", "item"})

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT, *,
                 member_username: Optional[Tuple[str, str]] = None, **kw):
        # member_username: (principal username, upstream username), owner preview only (settings.py);
        # None keeps the default rule (the principal's username, exactly).
        self._member_username = member_override(member_username)
        super().__init__(GuardedTransport(transport), timeout, **kw)

    def __repr__(self) -> str:
        return "AudiobookshelfAdapter(<redacted>)"

    # -- what this adapter does not offer: no upstream call, nothing cached ----------------
    def recent_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        return self._not_offered(principal, "recent")

    def item(self, principal: MemberPrincipal, item_id: str) -> SectionResult:
        return self._not_offered(principal, "item")

    def fetch_artwork(self, principal: MemberPrincipal, ref: str) -> ArtworkResult:
        # Group first, then the ref's exact shape, both before any upstream call or cache read.
        self._require_principal(principal)
        if not principal.has_group(self.required_group):
            return ArtworkResult(SectionState.NOT_PERMITTED)
        if not isinstance(ref, str) or _ARTWORK_REF.fullmatch(ref) is None:
            return ArtworkResult(SectionState.EMPTY)
        return super().fetch_artwork(principal, ref)

    # -- mapping: the verified USERNAME, exactly; the e-mail is never used -------------------
    def _resolve_user(self, principal) -> UpstreamUser:
        guard = self._guard.bind(None)
        body = self._get_json(guard, self._budget(), "/api/users", None)
        users = body.get("users") if isinstance(body, dict) else None
        if not isinstance(users, list):
            raise UpstreamMalformed()

        def extract(raw):
            if not isinstance(raw, dict):
                return None
            name, uid = raw.get("username"), raw.get("id")
            if isinstance(name, str) and isinstance(uid, str) and _BOUND_ID.fullmatch(uid):
                return name, uid
            return None
        uid, raw = match_exactly_one(lookup_username(principal, self._member_username), users, extract)
        _require_active(raw)
        return UpstreamUser(Service.AUDIOBOOKSHELF, uid)

    def _member_access(self, guard, budget, uid: str) -> Tuple[Dict[str, Any], _Access]:
        """The member's own record (its id must be the bound id; active) and the permissions in it."""
        record = self._get_json(guard, budget, f"/api/users/{uid}", None)
        if not isinstance(record, dict) or record.get("id") != uid:
            raise UpstreamMisbehaved()                    # another user's record, or none
        _require_active(record)
        return record, _Access.from_record(record)

    def _fetch_artwork(self, user: UpstreamUser, ref: str) -> ArtworkResult:
        m = _ARTWORK_REF.fullmatch(ref)
        if m is None:
            return ArtworkResult(SectionState.EMPTY)
        item_id = m.group(1)
        uid = user.upstream_id
        guard = self._guard.bind(uid)
        budget = self._budget()
        _record, access = self._member_access(guard, budget, uid)   # BEFORE the item is fetched
        try:
            raw = self._get_json(guard, budget, f"/api/items/{item_id}", {"expanded": "1"})
        except ItemGone:
            return ArtworkResult(SectionState.EMPTY)
        visible, _status = self._visible(raw, item_id, access, 0.0, None, None)
        if visible is None or visible.artwork is None:
            return ArtworkResult(SectionState.EMPTY)      # not visible to THIS member, or no cover: neutral
        return self._fetch_image(guard, budget, f"/api/items/{item_id}/cover", COVER_QUERY)

    # -- search: library by library, every hit re-checked for THIS member ------------------
    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        uid = user.upstream_id
        guard = self._guard.bind(uid)
        budget = self._budget()
        _record, access = self._member_access(guard, budget, uid)   # BEFORE any library is searched
        page = min(MAX_SEARCH_PAGE, limit * 3)
        shown: List[MediaItem] = []
        bad = 0
        for library_id in self._libraries(guard, budget, access)[:MAX_LIBRARIES]:
            if len(shown) >= limit:
                break
            try:
                body = self._get_json(guard, budget, f"/api/libraries/{library_id}/search",
                                      {"q": query, "limit": str(page)})
            except ItemGone:
                continue                                  # the library is gone: neutral
            if not isinstance(body, dict):
                raise UpstreamMalformed()
            hits = body.get("book")
            if hits is None and isinstance(body.get("podcast"), list):
                continue                                  # a podcast library: no books to show
            if not isinstance(hits, list):
                raise UpstreamMalformed()
            if len(hits) > page:
                raise UpstreamMisbehaved()                # the limit was ignored
            for hit in hits:
                raw = hit.get("libraryItem") if isinstance(hit, dict) else None
                item_id = raw.get("id") if isinstance(raw, dict) else None
                if not valid_upstream_id(Service.AUDIOBOOKSHELF, item_id):
                    bad += 1
                    continue
                if isinstance(raw.get("libraryId"), str) and raw["libraryId"] != library_id:
                    raise UpstreamMisbehaved()            # a hit from a library that was not searched
                media, status = self._visible(raw, item_id, access, None, None, None)
                bad += status == "bad"
                if media is not None and len(shown) < limit and all(m.id != media.id for m in shown):
                    shown.append(media)
        if not shown and bad:
            raise UpstreamMalformed()                     # nothing usable and some drift: never "empty"
        return SectionResult.of(Service.AUDIOBOOKSHELF, "search", tuple(shown))

    def _libraries(self, guard, budget, access: _Access) -> List[str]:
        """The library ids to search: the member's own list, or (only when the member's record grants every
        library) the upstream's library list, book libraries only. Ids of an unexpected shape are skipped."""
        if access.libraries is not None:
            return sorted(x for x in access.libraries if _LIBRARY_ID.fullmatch(x))
        body = self._get_json(guard, budget, "/api/libraries", None)
        raws = body.get("libraries") if isinstance(body, dict) else body
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        out, parsed = [], 0
        for raw in raws:
            lid = raw.get("id") if isinstance(raw, dict) else None
            if not isinstance(lid, str) or not _LIBRARY_ID.fullmatch(lid):
                continue
            parsed += 1
            kind = raw.get("mediaType")
            if isinstance(kind, str) and kind != "book":
                continue                                  # a podcast library
            if lid not in out:
                out.append(lid)
        if raws and not parsed:
            raise UpstreamMalformed()
        return out

    # -- the one section ---------------------------------------------------------------------
    def _continue_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        uid = user.upstream_id
        guard = self._guard.bind(uid)
        budget = self._budget()
        record, access = self._member_access(guard, budget, uid)   # BEFORE any item is fetched
        entries = self._candidates(record.get("mediaProgress"), uid)

        shown: List[MediaItem] = []
        unusable = looked_up = 0
        for last_update, item_id, fraction, position, duration in entries[:MAX_LOOKUPS]:
            if len(shown) >= limit:
                break
            if _left(budget) < LOOKUP_RESERVE:
                # Our own fan-out has used the budget; the service answered every call so far.
                if shown:
                    break                                 # what is already checked is accurate: show it
                raise FanOutSpent()                       # nothing to show yet: unavailable, never "empty"
            try:
                raw = self._get_json(guard, budget, f"/api/items/{item_id}", {"expanded": "1"})
            except ItemGone:
                looked_up += 1
                continue                                  # vanished upstream: omitted, neutral
            except UpstreamTimeout:
                if shown:
                    break                                 # a late lookup ran out of budget: keep the rest
                if looked_up:
                    raise FanOutSpent() from None         # the service answered earlier lookups: ours
                raise                                     # nothing answered in time: real evidence
            looked_up += 1
            media, status = self._visible(raw, item_id, access, fraction, position, duration)
            unusable += status == "bad"
            if media is not None:
                shown.append(media)
        if not shown and unusable:
            raise UpstreamMalformed()                     # nothing could be shown safely: drift, not "empty"
        return SectionResult.of(Service.AUDIOBOOKSHELF, "continue", tuple(shown))

    @staticmethod
    def _candidates(progress: Any, uid: str):
        """In-progress entries of THIS user, newest first. Identity is mandatory on every entry."""
        if not isinstance(progress, list):
            raise UpstreamMalformed()
        out, seen, bad = [], set(), 0
        for e in progress:
            if not isinstance(e, dict):
                bad += 1
                continue
            if e.get("userId") != uid:                    # another user's entry, or no identity at all
                raise UpstreamMisbehaved()
            item_id = e.get("libraryItemId")
            if not valid_upstream_id(Service.AUDIOBOOKSHELF, item_id):
                bad += 1
                continue
            if e.get("episodeId") is not None or e.get("isFinished") is True \
                    or e.get("hideFromContinueListening") is True:
                continue                                  # a podcast episode, finished, or hidden by the member
            frac, cur, dur = e.get("progress"), e.get("currentTime"), e.get("duration")
            if isinstance(frac, bool) or not isinstance(frac, (int, float)) or frac != frac:
                bad += 1
                continue
            if frac <= 0:
                continue                                  # not started
            if frac >= 1:
                continue                                  # finished by its own numbers, even if the flag lags
            last = bounded_int(e.get("lastUpdate")) or 0
            position = bounded_int(cur)
            duration = bounded_int(dur)
            if item_id in seen:
                continue
            seen.add(item_id)
            # Seconds (ABS floats, truncated). A zero or negative duration is "unknown", so the item's own
            # duration is used instead (`_visible`), never a remaining time computed from nothing.
            out.append((last, item_id, min(1.0, float(frac)), None if position is None else max(0, position),
                        None if duration is None or duration <= 0 else duration))
        if progress and bad == len(progress):
            raise UpstreamMalformed()
        out.sort(key=lambda t: t[0], reverse=True)
        return out

    @staticmethod
    def _visible(raw: Any, item_id: str, access: _Access, fraction: Optional[float], position: Optional[int],
                 duration: Optional[int]) -> Tuple[Optional[MediaItem], str]:
        """(item, status): "ok", "filtered" (a legitimate drop) or "bad" (unusable: fail closed)."""
        if not isinstance(raw, dict):
            return None, "bad"
        if raw.get("id") != item_id:
            raise UpstreamMisbehaved()                    # the lookup answered with a different item
        library_id, media = raw.get("libraryId"), raw.get("media")
        meta = media.get("metadata") if isinstance(media, dict) else None
        tags = media.get("tags") if isinstance(media, dict) else None
        if (not isinstance(library_id, str) or not isinstance(meta, dict) or not isinstance(tags, list)
                or not all(isinstance(t, str) for t in tags) or not isinstance(meta.get("explicit"), bool)):
            return None, "bad"                            # a required permission field is missing: omit
        if raw.get("mediaType") != "book" or raw.get("isMissing") is True or raw.get("isInvalid") is True:
            return None, "filtered"
        if not access.allows(library_id, tags, meta["explicit"]):
            return None, "filtered"
        title = clean_text(meta.get("title")) or "Untitled"
        # A cover is offered unless the item says it has none (`coverPath` present and null; UNVERIFIED
        # field). The path itself is never read or exposed. A missing cover upstream is a neutral 404.
        no_cover = isinstance(media, dict) and "coverPath" in media and media["coverPath"] is None
        artwork = None if no_cover else ArtworkRef(f"audiobookshelf/cover/{item_id}", f"Cover of {title}")
        if duration is None:
            duration = bounded_int(media.get("duration"))
        return MediaItem(id=f"audiobookshelf:{item_id}", service=Service.AUDIOBOOKSHELF,
                         kind=Kind.AUDIOBOOK, title=title,
                         handoff_url=build_handoff_url(Service.AUDIOBOOKSHELF, item_id),
                         subtitle=clean_text(meta.get("authorName")), series=clean_text(meta.get("seriesName")),
                         progress_fraction=fraction, position_seconds=position,
                         duration_seconds=duration, artwork=artwork), "ok"
