"""Jellyfin read-only member adapter.

Status: proposed, not deployed. Standard library only. Proven only against SYNTHETIC fixtures.

Read-only by construction: every request goes through `GuardedTransport`, which allows only GET
on a fixed list of path templates and query keys, requires the mapped user id on every
user-scoped route, and raises `ForbiddenRequest` BEFORE the inner transport is touched. The API
key lives inside the inner transport; nothing in this module holds or formats it.

Route and field names follow Jellyfin's public OpenAPI schema as remembered (10.10/10.11) and are
UNVERIFIED against a real server. Where the schema has changed between versions the allow-list
below is the one place to change.
"""
from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, Kind, MappingFailed, MediaItem, SectionResult,
                        SectionState, Service, UpstreamUser, build_handoff_url, clean_names, clean_summary, clean_text,
                        credits_of)
from ..resilience import (DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamMalformed,
                          UpstreamMisbehaved, UserGone)
from .. import media_ids
from . import _base
from ._base import (GuardedAdapter, Route, bounded_int, image_magic_ok, iso_instant, lookup_username,
                    match_exactly_one, member_override)

TICKS_PER_SECOND = 10_000_000
_GUID = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")
_HEX32 = r"[0-9a-f]{32}"
_BOUND_ID = re.compile(_HEX32)
MAX_INT = _base.MAX_INT
_ARTWORK_REF = re.compile(r"jellyfin/(primary|backdrop|logo)/(" + _HEX32 + r")")
# Backdrop: the wide image for Home's hero (an episode uses its series'). Logo: the title-treatment image Home's hero
# shows in place of typed text (a transparent PNG; an episode uses its series', ParentLogo*). Asking for Logo also
# makes Jellyfin (DtoService.AddInheritedImages, 10.11) send ParentBackdrop* for an episode.
_IMAGE_TYPES = "Primary,Backdrop,Logo"
_ITEM_FIELDS = "PrimaryImageAspectRatio,ProviderIds"   # ProviderIds: media_ids.from_jellyfin
_TITLE_FIELDS = _ITEM_FIELDS + ",Overview,People,Genres,Tags"   # the title page alone asks for the synopsis (R2-C)
                                                              # and who made it (richer Details, 2026-10-28)
# BaseItemPerson.Type (PersonKind) -> MediaItem.credits role. Every other kind (producer, composer, guest star) is left out.
_PERSON_ROLE = {"Actor": "cast", "Director": "directors", "Writer": "writers"}
# New for You (owner request 2026-10-28): what arrived in the last FOR_YOU_DAYS that is the next thing for this member.
FOR_YOU_DAYS = 30
FOR_YOU_ASK = 50              # Up next entries and newly added films looked at; most are older and are dropped
PLAYED_ASK = 200              # the member's newest watched films (their collections) and episodes (their series)
_FOR_YOU_FIELDS = _ITEM_FIELDS + ",DateCreated"
_COLLECTION_ID = re.compile(r"[0-9]{1,12}")
_int = bounded_int                    # names kept for the tests and for older importers
_image_magic_ok = image_magic_ok


def normalise_guid(value: Any) -> Optional[str]:
    """Jellyfin ids arrive dashed or undashed. Return 32 lowercase hex, or None if not a GUID."""
    if isinstance(value, str) and _GUID.fullmatch(value):
        return value.replace("-", "").lower()
    return None


# ---- the read-only allow-list -------------------------------------------------------------
# The user id travels in the QUERY (`userId`) on every user-scoped Jellyfin route. What a 404 means is
# declared per route: the user routes say "that user is gone", the image route "that item is gone",
# the user list "that route is gone" (drift).
ALLOWED_ROUTES = (
    Route("users", r"/Users", (), user_scoped=False, needs_user=False, not_found=RouteMissing),
    Route("resume", r"/UserItems/Resume",
          ("userId", "limit", "mediaTypes", "fields", "enableUserData", "enableImageTypes",
           "enableTotalRecordCount"), user_scoped=True, not_found=UserGone),
    Route("latest", r"/Items/Latest",
          ("userId", "limit", "includeItemTypes", "groupItems", "fields", "enableImageTypes",
           "enableUserData"), user_scoped=True, not_found=UserGone),
    # Up next (owner decision 2026-10-27, Home's Watch filter): the next unwatched episode of each series the member
    # is watching, user-scoped through the `userId` QUERY parameter like the others.
    Route("next_up", r"/Shows/NextUp",
          ("userId", "limit", "fields", "enableUserData", "enableImageTypes", "enableTotalRecordCount"),
          user_scoped=True, not_found=UserGone),
    # One route for the item lookup (`ids`) and search (`searchTerm`): both are user-scoped through the
    # `userId` QUERY parameter. Search moved here from the legacy `/Users/{id}/Items`, which Jellyfin 10.9+
    # keeps only as an obsolete, hidden alias (doc-verified against the 10.11 ItemsController source,
    # 2026-10-16; not live-verified). The term travels only as `searchTerm`.
    # New releases (owner decision 2026-10-28) is the same user-scoped listing sorted by premiere date, never later
    # than today, without the placeholders of unaired episodes. `isPlayed` (owner request 2026-10-28): THIS member's
    # watched episodes by DatePlayed (when each series was last watched, for Continue's order) and watched or unwatched
    # films (New for You's collections).
    Route("items", r"/Items", ("userId", "ids", "fields", "enableUserData", "enableImageTypes",
                               "searchTerm", "includeItemTypes", "recursive", "limit", "sortBy", "sortOrder",
                               "maxPremiereDate", "isMissing", "isPlayed"),
          user_scoped=True, not_found=UserGone),
    # The image route cannot carry a userId, so ITS member scoping is not enforced here: it rests on
    # the adapter calling `_visible_item` (a userId-scoped lookup) for the same item first.
    Route("image", r"/Items/" + _HEX32 + r"/Images/(?:Primary|Backdrop|Logo)", ("maxWidth", "quality"),
          user_scoped=False, not_found=ItemGone),
)


def check_request(method: Any, path: Any, query: Optional[Mapping[str, str]],
                  bound_user_id: Optional[str]) -> Route:
    """Raise ForbiddenRequest unless this is an allow-listed read-only request for the bound user."""
    return _base.check_request(ALLOWED_ROUTES, _BOUND_ID, method, path, query, bound_user_id)


class GuardedTransport(_base.GuardedTransport):
    """The Jellyfin allow-list around an inner Transport."""

    def __init__(self, inner, bound_user_id: Optional[str] = None):
        super().__init__(inner, ALLOWED_ROUTES, _BOUND_ID, bound_user_id)

    def _clone(self, user_id):
        return GuardedTransport(self._inner, user_id)


def _details(raw: dict) -> dict:
    """The title page's credits, genres and tags (MediaItem fields), only what the item itself lists. `People` is a list
    of {Name, Type, Role}; only actors, directors and writers are kept, in Jellyfin's own order (billing order)."""
    people = raw.get("People") if isinstance(raw.get("People"), list) else []
    by_role: dict = {}
    for person in people[:200]:
        if isinstance(person, dict) and person.get("Type") in _PERSON_ROLE:
            by_role.setdefault(_PERSON_ROLE[person["Type"]], []).append(person.get("Name"))
    return {"credits": credits_of(by_role.items()), "genres": clean_names(raw.get("Genres")),
            "tags": clean_names(raw.get("Tags"))}


# ---- adapter ------------------------------------------------------------------------------
def _arrived(raw: Any) -> Optional[str]:
    """When the item was added to the library (`DateCreated`), as MediaItem.active, or None."""
    return iso_instant(raw.get("DateCreated")) if isinstance(raw, dict) else None


def _collection(raw: Any) -> Optional[str]:
    """The film's TMDb collection id (ProviderIds `TmdbCollection`, set by Jellyfin's TMDb provider; UNVERIFIED
    live), or None. It links the films of one series (a trilogy) without another call."""
    ids = raw.get("ProviderIds") if isinstance(raw, dict) else None
    value = ids.get("TmdbCollection") if isinstance(ids, dict) else None
    return value if isinstance(value, str) and _COLLECTION_ID.fullmatch(value) else None


class JellyfinAdapter(GuardedAdapter):
    service = Service.JELLYFIN
    artwork_rechecks_visibility = True     # visibility is per member: re-checked before any cached cover
    extra_sections = frozenset({"next_up", "released", "for_you"})
    RELEASED_ASK = 4          # episodes ask for more, because only the newest of each series is kept

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT, *,
                 member_username: Optional[Tuple[str, str]] = None, **kw):
        # member_username: (principal username, upstream username), owner preview only (settings.py);
        # None keeps the default rule (the principal's username, exactly).
        self._member_username = member_override(member_username)
        super().__init__(GuardedTransport(transport), timeout, **kw)

    def __repr__(self) -> str:
        return "JellyfinAdapter(<redacted>)"

    # -- mapping -------------------------------------------------------------------------
    def _resolve_user(self, principal) -> UpstreamUser:
        guard = self._guard.bind(None)
        users = self._get_json(guard, self._budget(), "/Users", None)
        if not isinstance(users, list):
            raise UpstreamMalformed()

        def extract(raw):
            if not isinstance(raw, dict):
                return None
            name, uid = raw.get("Name"), normalise_guid(raw.get("Id"))
            return (name, uid) if isinstance(name, str) and uid is not None else None
        uid, raw = match_exactly_one(lookup_username(principal, self._member_username), users, extract)
        policy = raw.get("Policy")
        if isinstance(policy, dict) and policy.get("IsDisabled") is True:
            raise MappingFailed("disabled")
        return UpstreamUser(Service.JELLYFIN, uid)

    # -- item parsing --------------------------------------------------------------------
    def _parse_item(self, raw: Any, user_id: str, kinds: Tuple[str, ...],
                    want_progress: bool, require_progress: bool,
                    want_summary: bool = False, want_backdrop: bool = True,
                    series_poster: bool = False) -> Tuple[Optional[MediaItem], str]:
        """Returns (item, status). status: "ok", "filtered" (a legitimate drop: another type, not
        in progress) or "bad" (unparsable: wrong shape or invalid id). Only "bad" counts as drift.
        `series_poster` (Continue, Up next and New releases): an episode shows its series' poster instead of its own
        still, so it stands as tall as the films and covers beside it; without one it keeps its still."""
        if not isinstance(raw, dict):
            return None, "bad"
        item_id = normalise_guid(raw.get("Id"))
        if item_id is None:
            return None, "bad"
        data = raw.get("UserData")
        data = data if isinstance(data, dict) else {}
        # Scope tripwire: a response that names another user, or another item, is hostile or broken.
        # UserData.UserId may well be absent from real responses (UNVERIFIED); checked only if present.
        if "UserId" in data and normalise_guid(data["UserId"]) != user_id:
            raise UpstreamMisbehaved()
        if "ItemId" in data and normalise_guid(data["ItemId"]) != item_id:
            raise UpstreamMisbehaved()
        jf_type = raw.get("Type")
        if not isinstance(jf_type, str):
            return None, "bad"
        if jf_type not in kinds:
            return None, "filtered"
        kind = {"Movie": Kind.MOVIE, "Episode": Kind.EPISODE, "Series": Kind.SERIES}[jf_type]

        fraction = position = duration = None
        ticks = _int(data.get("PlaybackPositionTicks"))
        run = _int(raw.get("RunTimeTicks"))
        if want_progress and ticks is not None and ticks > 0:
            position = ticks // TICKS_PER_SECOND
            if run is not None and run > 0:
                duration = run // TICKS_PER_SECOND
                fraction = min(1.0, ticks / run)
            else:
                pct = data.get("PlayedPercentage")
                if isinstance(pct, (int, float)) and not isinstance(pct, bool) and 0 < pct <= 100:
                    fraction = pct / 100.0
        if require_progress and position is None:
            # a missing or non-numeric position is drift; zero means "not in progress"
            return None, ("filtered" if ticks is not None else "bad")
        if require_progress and data.get("Played") is True:
            # Watched to the end (Jellyfin keeps a position on some played items): never in Continue.
            return None, "filtered"

        title = clean_text(raw.get("Name")) or "Untitled"
        series = clean_text(raw.get("SeriesName")) if kind is Kind.EPISODE else None
        subtitle = None
        if kind is Kind.EPISODE:
            s, e = _int(raw.get("ParentIndexNumber")), _int(raw.get("IndexNumber"))
            if s is not None and e is not None and 0 <= s < 10000 and 0 <= e < 10000:
                subtitle = f"S{s} E{e}"
        year = _int(raw.get("ProductionYear"))
        year = year if year is not None and 1800 <= year <= 2200 else None
        if kind is not Kind.EPISODE and year is not None:
            subtitle = str(year)

        artwork = None
        tags = raw.get("ImageTags")
        if isinstance(tags, dict) and isinstance(tags.get("Primary"), str) and tags["Primary"]:
            alt = (f"Still from {series}, {title}" if series else
                   f"Poster for {title}")
            artwork = ArtworkRef(f"jellyfin/primary/{item_id}", alt)
        series_id, series_tag = normalise_guid(raw.get("SeriesId")), raw.get("SeriesPrimaryImageTag")
        if (series_poster and kind is Kind.EPISODE and series_id is not None and isinstance(series_tag, str)
                and series_tag):
            # The ref names the series, as a borrowed backdrop does: the gateway checks THAT item is visible to the member.
            artwork = ArtworkRef(f"jellyfin/primary/{series_id}", f"Poster for {series or title}", shape="poster")
        backdrop = None
        own = raw.get("BackdropImageTags")
        parent = normalise_guid(raw.get("ParentBackdropItemId"))
        theirs = raw.get("ParentBackdropImageTags")
        if not want_backdrop:
            pass                                                     # search results carry no backdrop
        elif isinstance(own, list) and own and isinstance(own[0], str) and own[0]:
            backdrop = ArtworkRef(f"jellyfin/backdrop/{item_id}", "")
        elif (kind is Kind.EPISODE and parent is not None and isinstance(theirs, list) and theirs
              and isinstance(theirs[0], str) and theirs[0]):
            backdrop = ArtworkRef(f"jellyfin/backdrop/{parent}", "")   # the series' backdrop
        logo = None
        logo_parent, logo_tag = normalise_guid(raw.get("ParentLogoItemId")), raw.get("ParentLogoImageTag")
        logo_name = series or title
        if not want_backdrop:
            pass                                                     # only the hero shows a logo, as with backdrops
        elif isinstance(tags, dict) and isinstance(tags.get("Logo"), str) and tags["Logo"]:
            logo = ArtworkRef(f"jellyfin/logo/{item_id}", logo_name)
        elif kind is Kind.EPISODE and logo_parent is not None and isinstance(logo_tag, str) and logo_tag:
            logo = ArtworkRef(f"jellyfin/logo/{logo_parent}", logo_name)   # the series' logo
        return MediaItem(id=f"jellyfin:{item_id}", service=Service.JELLYFIN, kind=kind, title=title,
                         handoff_url=build_handoff_url(Service.JELLYFIN, item_id),
                         subtitle=subtitle, series=series, progress_fraction=fraction,
                         position_seconds=position, duration_seconds=duration,
                         artwork=artwork, year=year, active=iso_instant(data.get("LastPlayedDate")),
                         external_ids=media_ids.from_jellyfin(raw.get("ProviderIds")),
                         summary=clean_summary(raw.get("Overview")) if want_summary else None,
                         backdrop=backdrop, logo=logo, released=_base.iso_day(raw.get("PremiereDate")),
                         **(_details(raw) if want_summary else {})), "ok"

    def _parse_list(self, raws: Any, user_id: str, limit: int, kinds, want_progress,
                    require_progress, want_summary: bool = False,
                    want_backdrop: bool = True, series_poster: bool = False) -> Tuple[MediaItem, ...]:
        return self._parse_many(raws, limit, lambda raw: self._parse_item(
            raw, user_id, kinds, want_progress, require_progress, want_summary, want_backdrop, series_poster))

    # -- hooks ---------------------------------------------------------------------------
    def _continue_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        body = self._get_json(guard, self._budget(), "/UserItems/Resume", {
            "userId": user.upstream_id, "limit": str(limit), "mediaTypes": "Video",
            "fields": _ITEM_FIELDS, "enableUserData": "true", "enableImageTypes": _IMAGE_TYPES,
            "enableTotalRecordCount": "false"})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        items = self._parse_list(body.get("Items"), user.upstream_id, limit,
                                 ("Movie", "Episode"), want_progress=True, require_progress=True,
                                 series_poster=True)
        return SectionResult.of(Service.JELLYFIN, "continue", items)

    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        body = self._get_json(guard, self._budget(), "/Items/Latest", {
            "userId": user.upstream_id, "limit": str(limit),
            "includeItemTypes": "Movie,Series,Episode", "groupItems": "true",
            "fields": _ITEM_FIELDS, "enableImageTypes": _IMAGE_TYPES, "enableUserData": "true"})
        # user data is requested only so the scope tripwire can run; it is never exposed here
        items = self._parse_list(body, user.upstream_id, limit, ("Movie", "Series", "Episode"),
                                 want_progress=False, require_progress=False)
        return SectionResult.of(Service.JELLYFIN, "recent", items)

    def _next_up_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        body = self._get_json(guard, self._budget(), "/Shows/NextUp", {
            "userId": user.upstream_id, "limit": str(limit), "fields": _ITEM_FIELDS, "enableUserData": "true",
            "enableImageTypes": _IMAGE_TYPES, "enableTotalRecordCount": "false"})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        # user data is requested only so the scope tripwire can run; an episode's own progress belongs to Continue.
        # The series poster, as in Continue (#138): All's Continue shows Up next among films and covers (2026-10-28).
        items = self._parse_list(body.get("Items"), user.upstream_id, limit, ("Episode",),
                                 want_progress=False, require_progress=False, series_poster=True)
        # An Up next episode was never played, so it carries when its SERIES was last watched: Home orders Continue by
        # it across libraries (owner request 2026-10-28), so a show left months ago no longer leads the rail.
        series_of = self._series_ids(body.get("Items"))
        last = self._series_last_played(guard, user)
        items = tuple(dataclasses.replace(i, active=last.get(series_of.get(i.id))) for i in items)
        return SectionResult.of(Service.JELLYFIN, "next_up", items)

    @staticmethod
    def _series_ids(raws: Any) -> dict:
        """{"jellyfin:<episode id>": series id} for the episodes of a listing that name a valid series."""
        out = {}
        for raw in raws if isinstance(raws, list) else ():
            if isinstance(raw, dict):
                item_id, series_id = normalise_guid(raw.get("Id")), normalise_guid(raw.get("SeriesId"))
                if item_id and series_id:
                    out[f"jellyfin:{item_id}"] = series_id
        return out

    def _series_last_played(self, guard, user: UpstreamUser) -> dict:
        """{series id: when THIS member last watched an episode of it}, from their watched episodes, newest first."""
        body = self._get_json(guard, self._budget(), "/Items", {
            "userId": user.upstream_id, "includeItemTypes": "Episode", "recursive": "true", "isPlayed": "true",
            "sortBy": "DatePlayed", "sortOrder": "Descending", "limit": str(PLAYED_ASK), "enableUserData": "true",
            "enableImageTypes": "Primary"})
        raws = body.get("Items") if isinstance(body, dict) else None
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > PLAYED_ASK:
            raise UpstreamMisbehaved()
        out: dict = {}
        for raw in raws:
            data = raw.get("UserData") if isinstance(raw, dict) else None
            if not isinstance(data, dict):
                continue
            if "UserId" in data and normalise_guid(data["UserId"]) != user.upstream_id:
                raise UpstreamMisbehaved()                  # the same scope tripwire as `_parse_item`
            series_id, when = normalise_guid(raw.get("SeriesId")), iso_instant(data.get("LastPlayedDate"))
            if series_id and when and when > out.get(series_id, ""):
                out[series_id] = when
        return out

    def _for_you_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        """New for You (owner request 2026-10-28), newest arrival first, each item's `active` when it arrived:
          * the member's Up next episode of a show, when THAT episode arrived in the last FOR_YOU_DAYS: Jellyfin's Up
            next is the episode after the last one watched, so it is new only when the member was caught up (behind on
            a show, Up next is an older episode and is left out);
          * an unwatched film added in the last FOR_YOU_DAYS from a TMDb collection the member has watched a film of
            (the next film of a series). Collections come from ProviderIds; UNVERIFIED that the library has them."""
        guard = self._guard.bind(user.upstream_id)
        since = iso_instant((datetime.now(timezone.utc) - timedelta(days=FOR_YOU_DAYS)).isoformat())
        body = self._get_json(guard, self._budget(), "/Shows/NextUp", {
            "userId": user.upstream_id, "limit": str(FOR_YOU_ASK), "fields": _FOR_YOU_FIELDS, "enableUserData": "true",
            "enableImageTypes": _IMAGE_TYPES, "enableTotalRecordCount": "false"})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        arrived = {f"jellyfin:{normalise_guid(r.get('Id'))}": _arrived(r)
                   for r in body.get("Items") or () if isinstance(r, dict) and normalise_guid(r.get("Id"))}
        episodes = self._parse_list(body.get("Items"), user.upstream_id, FOR_YOU_ASK, ("Episode",),
                                    want_progress=True, require_progress=False, series_poster=True)
        found = [dataclasses.replace(i, active=arrived[i.id]) for i in episodes
                 if (arrived.get(i.id) or "") >= since and i.position_seconds is None]   # started: Continue's

        def films(played: bool, ask: int, sort: str):
            raws = self._get_json(guard, self._budget(), "/Items", {
                "userId": user.upstream_id, "includeItemTypes": "Movie", "recursive": "true",
                "isPlayed": "true" if played else "false", "sortBy": sort, "sortOrder": "Descending",
                "limit": str(ask), "fields": _FOR_YOU_FIELDS, "enableUserData": "true",
                "enableImageTypes": _IMAGE_TYPES})
            raws = raws.get("Items") if isinstance(raws, dict) else None
            if not isinstance(raws, list):
                raise UpstreamMalformed()
            return raws
        added = [r for r in films(False, FOR_YOU_ASK, "DateCreated") if (_arrived(r) or "") >= since and _collection(r)]
        if added:
            seen = {_collection(r) for r in films(True, PLAYED_ASK, "DatePlayed")} - {None}
            fresh = [r for r in added if _collection(r) in seen]
            when = {f"jellyfin:{normalise_guid(r.get('Id'))}": _arrived(r) for r in fresh}
            found += [dataclasses.replace(i, active=when.get(i.id)) for i in
                      self._parse_list(fresh, user.upstream_id, FOR_YOU_ASK, ("Movie",), want_progress=True,
                                       require_progress=False) if i.position_seconds is None]
        found.sort(key=lambda i: i.active or "", reverse=True)
        return SectionResult.of(Service.JELLYFIN, "for_you", tuple(found[:limit]))

    def _released_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        """Films and episodes by premiere date, newest first, none later than today; one episode per series (its
        newest), so a show that drops a season is one card. An episode shows its series' poster, as Continue and Up
        next do (owner request 2026-10-28), so the rail stands as tall as the films beside it; a show without a poster
        keeps the episode's still."""
        guard = self._guard.bind(user.upstream_id)
        today = datetime.now(timezone.utc).date().isoformat()
        body = self._get_json(guard, self._budget(), "/Items", {
            "userId": user.upstream_id, "includeItemTypes": "Movie,Episode", "recursive": "true",
            "sortBy": "PremiereDate,SortName", "sortOrder": "Descending", "maxPremiereDate": today + "T23:59:59Z",
            "isMissing": "false", "limit": str(min(50, limit * self.RELEASED_ASK)), "fields": _ITEM_FIELDS,
            "enableImageTypes": _IMAGE_TYPES, "enableUserData": "true"})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        # user data is requested only so the scope tripwire can run; it is never exposed here
        found = self._parse_list(body.get("Items"), user.upstream_id, min(50, limit * self.RELEASED_ASK),
                                 ("Movie", "Episode"), want_progress=False, require_progress=False,
                                 series_poster=True)
        shown, series = [], set()
        for item in found:
            if item.released is None or item.released > today:
                continue
            if item.kind is Kind.EPISODE:
                if item.series in series:
                    continue
                series.add(item.series)
            shown.append(item)
        return SectionResult.of(Service.JELLYFIN, "released", tuple(shown[:limit]))

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        body = self._get_json(guard, self._budget(), "/Items", {
            "userId": user.upstream_id, "searchTerm": query, "includeItemTypes": "Movie,Series,Episode", "recursive": "true",
            "limit": str(limit), "fields": _ITEM_FIELDS, "enableImageTypes": "Primary",
            "enableUserData": "true"})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        items = self._parse_list(body.get("Items"), user.upstream_id, limit, ("Movie", "Series", "Episode"),
                                 want_progress=False, require_progress=False, want_backdrop=False)
        return SectionResult.of(Service.JELLYFIN, "search", items)

    def _visible_item(self, guard, budget, user: UpstreamUser, item_id: str,
                      fields: str = _ITEM_FIELDS) -> Optional[MediaItem]:
        body = self._get_json(guard, budget, "/Items", {
            "userId": user.upstream_id, "ids": item_id, "fields": fields,
            "enableUserData": "true", "enableImageTypes": _IMAGE_TYPES})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        items = self._parse_list(body.get("Items"), user.upstream_id, 1,
                                 ("Movie", "Series", "Episode"), want_progress=True,
                                 require_progress=False, want_summary=fields == _TITLE_FIELDS)
        return next((i for i in items if i.id == f"jellyfin:{item_id}"), None)

    def _item(self, user: UpstreamUser, item_id: str) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        found = self._visible_item(guard, self._budget(), user, item_id, fields=_TITLE_FIELDS)
        return SectionResult.of(Service.JELLYFIN, "item", (found,) if found else ())

    def _fetch_artwork(self, user: UpstreamUser, ref: str, cached=None) -> ArtworkResult:
        m = _ARTWORK_REF.fullmatch(ref)
        if m is None:
            return ArtworkResult(SectionState.EMPTY)
        image, item_id = m.group(1), m.group(2)
        guard = self._guard.bind(user.upstream_id)
        budget = self._budget()
        # Member-scoped permission check. A backdrop ref names the item that owns the image: the movie or series
        # itself (an episode's ref names its series), so that item must be visible to this member and have one.
        visible = self._visible_item(guard, budget, user, item_id)
        owned = (None if visible is None else
                 {"backdrop": visible.backdrop, "logo": visible.logo}.get(image, visible.artwork))
        if owned is None or owned.ref != ref:
            return ArtworkResult(SectionState.EMPTY)
        hit = cached() if cached is not None else None      # only AFTER this member's visibility check
        if hit is not None:
            return hit
        if image == "backdrop":
            return self._fetch_image(guard, budget, f"/Items/{item_id}/Images/Backdrop",
                                     {"maxWidth": "1280", "quality": "80"})
        if image == "logo":
            return self._fetch_image(guard, budget, f"/Items/{item_id}/Images/Logo",
                                     {"maxWidth": "800", "quality": "90"})
        return self._fetch_image(guard, budget, f"/Items/{item_id}/Images/Primary",
                                 {"maxWidth": "400", "quality": "80"})
