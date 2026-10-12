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

import json
import re
import unicodedata
from typing import Any, List, Mapping, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, AmbiguousMappingError, ForbiddenRequest, Kind,
                        MappingFailed, MediaAdapter, MediaItem, SectionResult, SectionState,
                        Service, UpstreamUser, build_handoff_url, clean_text)
from ..resilience import (MAX_IMAGE_BYTES, MAX_JSON_BYTES, CallBudget, DEFAULT_TIMEOUT, ItemGone,
                          RouteMissing, Transport, TransportResponse, UpstreamError,
                          UpstreamMalformed, UpstreamMisbehaved, UpstreamNotFound, UpstreamTooLarge,
                          UpstreamUnreachable, UserGone)

TICKS_PER_SECOND = 10_000_000
_GUID = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")
_HEX32 = r"[0-9a-f]{32}"
_BOUND_ID = re.compile(_HEX32)
MAX_INT = 2 ** 63
_ARTWORK_REF = re.compile(r"jellyfin/primary/(" + _HEX32 + r")")
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


def _image_magic_ok(ctype: str, body: bytes) -> bool:
    """The bytes must really be the image type claimed (the serving app must still send
    X-Content-Type-Options: nosniff, see ADAPTER-CONTRACT.md)."""
    if ctype == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if ctype == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if ctype == "image/webp":
        return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    return False
_ITEM_FIELDS = "PrimaryImageAspectRatio"


def normalise_guid(value: Any) -> Optional[str]:
    """Jellyfin ids arrive dashed or undashed. Return 32 lowercase hex, or None if not a GUID."""
    if isinstance(value, str) and _GUID.fullmatch(value):
        return value.replace("-", "").lower()
    return None


# ---- the read-only allow-list -------------------------------------------------------------
class Route:
    def __init__(self, name: str, pattern: str, query_keys: Tuple[str, ...], user_scoped: bool,
                 needs_user: bool = True, not_found: type = UserGone):
        self.name = name
        self.pattern = re.compile(pattern)
        self.query_keys = frozenset(query_keys)
        self.user_scoped = user_scoped      # the userId query value must equal the bound user
        self.needs_user = needs_user        # a mapped user must exist before this route is used
        # What a 404 on THIS route means, declared here and nowhere else: UserGone (the route is
        # addressed by the bound user), ItemGone (by one item), RouteMissing (a fixed route).
        self.not_found = not_found


ALLOWED_ROUTES = (
    Route("users", r"/Users", (), user_scoped=False, needs_user=False, not_found=RouteMissing),
    Route("resume", r"/UserItems/Resume",
          ("userId", "limit", "mediaTypes", "fields", "enableUserData", "enableImageTypes",
           "enableTotalRecordCount"), user_scoped=True),
    Route("latest", r"/Items/Latest",
          ("userId", "limit", "includeItemTypes", "groupItems", "fields", "enableImageTypes",
           "enableUserData"), user_scoped=True),
    Route("items", r"/Items", ("userId", "ids", "fields", "enableUserData", "enableImageTypes"),
          user_scoped=True),
    # The image route cannot carry a userId, so ITS member scoping is not enforced here: it rests on
    # the adapter calling `_visible_item` (a userId-scoped lookup) for the same item first.
    Route("image", r"/Items/" + _HEX32 + r"/Images/Primary", ("maxWidth", "quality"),
          user_scoped=False, not_found=ItemGone),
)


def check_request(method: Any, path: Any, query: Optional[Mapping[str, str]],
                  bound_user_id: Optional[str]) -> Route:
    """Raise ForbiddenRequest unless this is an allow-listed read-only request for the bound user."""
    if method != "GET":
        raise ForbiddenRequest("method")
    if not isinstance(path, str):
        raise ForbiddenRequest("path")
    route = next((r for r in ALLOWED_ROUTES if r.pattern.fullmatch(path)), None)
    if route is None:
        raise ForbiddenRequest("path")
    if bound_user_id is not None and (not isinstance(bound_user_id, str)
                                      or _BOUND_ID.fullmatch(bound_user_id) is None):
        raise ForbiddenRequest("bound user id")
    query = dict(query or {})
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in query.items()):
        raise ForbiddenRequest("query")
    if not set(query) <= route.query_keys:
        raise ForbiddenRequest("query")
    if route.needs_user and bound_user_id is None:
        raise ForbiddenRequest("no mapped user")
    if route.user_scoped and query.get("userId") != bound_user_id:
        raise ForbiddenRequest("user scope")
    if not route.user_scoped and "userId" in query:
        raise ForbiddenRequest("user scope")
    return route


class GuardedTransport:
    """Wraps an inner Transport. Same `request` signature; checks first, then delegates."""

    def __init__(self, inner: Transport, bound_user_id: Optional[str] = None):
        if bound_user_id is not None and (not isinstance(bound_user_id, str)
                                          or _BOUND_ID.fullmatch(bound_user_id) is None):
            raise ForbiddenRequest("bound user id")        # defence in depth: never bind a non-GUID
        self._inner = inner
        self._bound = bound_user_id

    def bind(self, user_id: Optional[str]) -> "GuardedTransport":
        return GuardedTransport(self._inner, user_id)

    def request(self, method, path, query, timeout, max_bytes) -> TransportResponse:
        route = check_request(method, path, query, self._bound)
        try:
            return self._inner.request(method, path, query, timeout, max_bytes)
        except UpstreamNotFound as exc:
            if type(exc) is UpstreamNotFound:             # a bare 404: the ROUTE says what it means
                raise route.not_found(exc.status) from None
            raise

    def __repr__(self) -> str:
        return "GuardedTransport(<redacted>)"


# ---- adapter ------------------------------------------------------------------------------
def _norm_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


class JellyfinAdapter(MediaAdapter):
    service = Service.JELLYFIN

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT, **kw):
        kw.setdefault("request_timeout", timeout)
        super().__init__(**kw)
        self._guard = GuardedTransport(transport)
        self._timeout = timeout

    def __repr__(self) -> str:
        return "JellyfinAdapter(<redacted>)"

    # -- low level -----------------------------------------------------------------------
    def _get(self, guard: GuardedTransport, budget: CallBudget, path: str,
             query: Optional[Mapping[str, str]], max_bytes: int = MAX_JSON_BYTES) -> TransportResponse:
        timeout = min(budget.remaining(), self._timeout)
        try:
            resp = guard.request("GET", path, query, timeout, max_bytes)
        except (UpstreamError, ForbiddenRequest):
            raise                      # classified already, or a bug in OUR allow-list use: stay visible
        except Exception:
            # Anything else a transport raises is upstream-side by definition (a surprise exception
            # class from a client library). It is one failed call, logged by class downstream,
            # never an escaping exception and never a reason to force-open the circuit.
            raise UpstreamUnreachable() from None
        budget.remaining()                      # a response that arrives past the budget is too late
        if len(resp.body) > max_bytes:
            raise UpstreamTooLarge()
        return resp

    def _get_json(self, guard, budget, path, query) -> Any:
        resp = self._get(guard, budget, path, query)
        try:
            return json.loads(resp.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError, MemoryError):
            raise UpstreamMalformed() from None

    def _budget(self) -> CallBudget:
        return self.current_budget()

    # -- mapping -------------------------------------------------------------------------
    def _resolve_user(self, principal) -> UpstreamUser:
        guard = self._guard.bind(None)
        users = self._get_json(guard, self._budget(), "/Users", None)
        if not isinstance(users, list):
            raise UpstreamMalformed()
        if users and not any(isinstance(u, dict) and isinstance(u.get("Name"), str)
                             and normalise_guid(u.get("Id")) is not None for u in users):
            raise UpstreamMalformed()      # a non-empty list nobody can be matched in is drift, not "unlinked"
        wanted_exact = principal.username
        wanted_loose = _norm_name(principal.username)
        exact, loose = {}, {}
        for raw in users:
            if not isinstance(raw, dict):
                continue
            name, uid = raw.get("Name"), normalise_guid(raw.get("Id"))
            if not isinstance(name, str) or uid is None:
                continue
            if _norm_name(name) == wanted_loose:
                loose[uid] = raw
                if name == wanted_exact:
                    exact[uid] = raw
        if len(exact) > 1 or (len(exact) == 1 and len(loose) > 1):
            raise AmbiguousMappingError()
        if not exact:
            raise MappingFailed("case_or_unicode_mismatch" if loose else "unmapped")
        (uid, raw), = exact.items()
        policy = raw.get("Policy")
        if isinstance(policy, dict) and policy.get("IsDisabled") is True:
            raise MappingFailed("disabled")
        return UpstreamUser(Service.JELLYFIN, uid)

    # -- item parsing --------------------------------------------------------------------
    def _parse_item(self, raw: Any, user_id: str, kinds: Tuple[str, ...],
                    want_progress: bool, require_progress: bool) -> Tuple[Optional[MediaItem], str]:
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

        title = clean_text(raw.get("Name")) or "Untitled"
        series = clean_text(raw.get("SeriesName")) if kind is Kind.EPISODE else None
        subtitle = None
        if kind is Kind.EPISODE:
            s, e = _int(raw.get("ParentIndexNumber")), _int(raw.get("IndexNumber"))
            if s is not None and e is not None and 0 <= s < 10000 and 0 <= e < 10000:
                subtitle = f"S{s} E{e}"
        else:
            year = _int(raw.get("ProductionYear"))
            if year is not None and 1800 <= year <= 2200:
                subtitle = str(year)

        artwork = None
        tags = raw.get("ImageTags")
        if isinstance(tags, dict) and isinstance(tags.get("Primary"), str) and tags["Primary"]:
            alt = (f"Still from {series}, {title}" if series else
                   f"Poster for {title}")
            artwork = ArtworkRef(f"jellyfin/primary/{item_id}", alt)
        return MediaItem(id=f"jellyfin:{item_id}", service=Service.JELLYFIN, kind=kind, title=title,
                         handoff_url=build_handoff_url(Service.JELLYFIN, item_id),
                         subtitle=subtitle, series=series, progress_fraction=fraction,
                         position_seconds=position, duration_seconds=duration,
                         artwork=artwork), "ok"

    def _parse_list(self, raws: Any, user_id: str, limit: int, kinds, want_progress,
                    require_progress) -> Tuple[MediaItem, ...]:
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > limit:
            raise UpstreamMisbehaved()            # limit ignored: possibly an unscoped listing
        out: List[MediaItem] = []
        seen = set()
        bad = 0
        for raw in raws:
            item, status = self._parse_item(raw, user_id, kinds, want_progress, require_progress)
            bad += status == "bad"
            if item is not None and item.id not in seen:
                seen.add(item.id)
                out.append(item)
        if raws and bad == len(raws):
            raise UpstreamMalformed()             # total schema drift: never cache it as "empty"
        return tuple(out)

    # -- hooks ---------------------------------------------------------------------------
    def _continue_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        body = self._get_json(guard, self._budget(), "/UserItems/Resume", {
            "userId": user.upstream_id, "limit": str(limit), "mediaTypes": "Video",
            "fields": _ITEM_FIELDS, "enableUserData": "true", "enableImageTypes": "Primary",
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
            "fields": _ITEM_FIELDS, "enableImageTypes": "Primary", "enableUserData": "true"})
        # user data is requested only so the scope tripwire can run; it is never exposed here
        items = self._parse_list(body, user.upstream_id, limit, ("Movie", "Series", "Episode"),
                                 want_progress=False, require_progress=False)
        return SectionResult.of(Service.JELLYFIN, "recent", items)

    def _visible_item(self, guard, budget, user: UpstreamUser, item_id: str) -> Optional[MediaItem]:
        body = self._get_json(guard, budget, "/Items", {
            "userId": user.upstream_id, "ids": item_id, "fields": _ITEM_FIELDS,
            "enableUserData": "true", "enableImageTypes": "Primary"})
        if not isinstance(body, dict):
            raise UpstreamMalformed()
        items = self._parse_list(body.get("Items"), user.upstream_id, 1,
                                 ("Movie", "Series", "Episode"), want_progress=True,
                                 require_progress=False)
        return next((i for i in items if i.id == f"jellyfin:{item_id}"), None)

    def _item(self, user: UpstreamUser, item_id: str) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        found = self._visible_item(guard, self._budget(), user, item_id)
        return SectionResult.of(Service.JELLYFIN, "item", (found,) if found else ())

    def _fetch_artwork(self, user: UpstreamUser, ref: str) -> ArtworkResult:
        m = _ARTWORK_REF.fullmatch(ref)
        if m is None:
            return ArtworkResult(SectionState.EMPTY)
        item_id = m.group(1)
        guard = self._guard.bind(user.upstream_id)
        budget = self._budget()
        visible = self._visible_item(guard, budget, user, item_id)   # member-scoped permission check
        if visible is None or visible.artwork is None:
            return ArtworkResult(SectionState.EMPTY)
        try:
            resp = self._get(guard, budget, f"/Items/{item_id}/Images/Primary",
                             {"maxWidth": "400", "quality": "80"}, MAX_IMAGE_BYTES)
        except ItemGone:
            return ArtworkResult(SectionState.EMPTY)
        ctype = resp.content_type.split(";")[0].strip().lower()
        if ctype not in _IMAGE_TYPES or not _image_magic_ok(ctype, resp.body):
            raise UpstreamMalformed()
        return ArtworkResult(SectionState.OK, ctype, resp.body)


def _int(value: Any) -> Optional[int]:
    """A bounded integer from upstream JSON, or None. Hostile magnitudes are rejected here so
    later arithmetic can neither overflow nor divide by something absurd."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = int(value)
    except (OverflowError, ValueError):
        return None
    return number if -MAX_INT < number < MAX_INT else None
