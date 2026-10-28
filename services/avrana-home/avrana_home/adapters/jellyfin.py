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

import re
from typing import Any, Mapping, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, Kind, MappingFailed, MediaItem, SectionResult,
                        SectionState, Service, UpstreamUser, build_handoff_url, clean_summary, clean_text)
from ..resilience import (DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamMalformed,
                          UpstreamMisbehaved, UserGone)
from .. import media_ids
from . import _base
from ._base import (GuardedAdapter, Route, bounded_int, image_magic_ok, lookup_username, match_exactly_one,
                    member_override)

TICKS_PER_SECOND = 10_000_000
_GUID = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")
_HEX32 = r"[0-9a-f]{32}"
_BOUND_ID = re.compile(_HEX32)
MAX_INT = _base.MAX_INT
_ARTWORK_REF = re.compile(r"jellyfin/(primary|backdrop)/(" + _HEX32 + r")")
_IMAGE_TYPES = "Primary,Backdrop"   # Backdrop: the wide image for Home's hero (an episode uses its series')
_ITEM_FIELDS = "PrimaryImageAspectRatio,ProviderIds"   # ProviderIds: media_ids.from_jellyfin
_TITLE_FIELDS = _ITEM_FIELDS + ",Overview"    # the title page alone asks for the synopsis (R2-C)
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
    Route("items", r"/Items", ("userId", "ids", "fields", "enableUserData", "enableImageTypes",
                               "searchTerm", "includeItemTypes", "recursive", "limit"),
          user_scoped=True, not_found=UserGone),
    # The image route cannot carry a userId, so ITS member scoping is not enforced here: it rests on
    # the adapter calling `_visible_item` (a userId-scoped lookup) for the same item first.
    Route("image", r"/Items/" + _HEX32 + r"/Images/(?:Primary|Backdrop)", ("maxWidth", "quality"),
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


# ---- adapter ------------------------------------------------------------------------------
class JellyfinAdapter(GuardedAdapter):
    service = Service.JELLYFIN
    artwork_rechecks_visibility = True     # visibility is per member: re-checked before any cached cover
    extra_sections = frozenset({"next_up"})

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
                    want_summary: bool = False, want_backdrop: bool = True) -> Tuple[Optional[MediaItem], str]:
        """Returns (item, status). status: "ok", "filtered" (a legitimate drop: another type, not
        in progress) or "bad" (unparsable: wrong shape or invalid id). Only "bad" counts as drift."""
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
        return MediaItem(id=f"jellyfin:{item_id}", service=Service.JELLYFIN, kind=kind, title=title,
                         handoff_url=build_handoff_url(Service.JELLYFIN, item_id),
                         subtitle=subtitle, series=series, progress_fraction=fraction,
                         position_seconds=position, duration_seconds=duration,
                         artwork=artwork, year=year,
                         external_ids=media_ids.from_jellyfin(raw.get("ProviderIds")),
                         summary=clean_summary(raw.get("Overview")) if want_summary else None,
                         backdrop=backdrop), "ok"

    def _parse_list(self, raws: Any, user_id: str, limit: int, kinds, want_progress,
                    require_progress, want_summary: bool = False,
                    want_backdrop: bool = True) -> Tuple[MediaItem, ...]:
        return self._parse_many(raws, limit, lambda raw: self._parse_item(
            raw, user_id, kinds, want_progress, require_progress, want_summary, want_backdrop))

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
                                 ("Movie", "Episode"), want_progress=True, require_progress=True)
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
        # user data is requested only so the scope tripwire can run; an episode's own progress belongs to Continue
        items = self._parse_list(body.get("Items"), user.upstream_id, limit, ("Episode",),
                                 want_progress=False, require_progress=False)
        return SectionResult.of(Service.JELLYFIN, "next_up", items)

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
        owned = None if visible is None else (visible.backdrop if image == "backdrop" else visible.artwork)
        if owned is None or owned.ref != ref:
            return ArtworkResult(SectionState.EMPTY)
        hit = cached() if cached is not None else None      # only AFTER this member's visibility check
        if hit is not None:
            return hit
        if image == "backdrop":
            return self._fetch_image(guard, budget, f"/Items/{item_id}/Images/Backdrop",
                                     {"maxWidth": "1280", "quality": "80"})
        return self._fetch_image(guard, budget, f"/Items/{item_id}/Images/Primary",
                                 {"maxWidth": "400", "quality": "80"})
