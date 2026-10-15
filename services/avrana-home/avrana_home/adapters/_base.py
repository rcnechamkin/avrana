"""Service-neutral pieces shared by every read-only adapter.

Status: proposed, not deployed. Standard library only.

What lives here is what must be identical for every service, so that a new adapter cannot get the
isolation rules subtly different:

  * `Route` / `check_request` / `GuardedTransport`: the read-only allow-list and the choke point.
    Each route declares WHERE the bound upstream user id travels (a query parameter or a path
    segment) and what a 404 on that route means; the id pattern is per service.
  * `GuardedAdapter`: the budgeted JSON/binary fetch helpers, the list drift accounting, the
    image flow (magic-number check) and the 404 classes, built on `MediaAdapter`.
  * `bounded_int`, `image_magic_ok`, `match_exactly_one`: small pure helpers.

Nothing here knows a service's routes, field names or id format; those are passed in.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Iterable, List, Mapping, Optional, Pattern, Sequence, Tuple

from ..contract import (AmbiguousMappingError, ArtworkResult, ForbiddenRequest, MappingFailed,
                        MediaAdapter, SectionState)
from ..resilience import (DEFAULT_TIMEOUT, MAX_IMAGE_BYTES, MAX_JSON_BYTES, CallBudget, ItemGone,
                          Transport, TransportResponse, UpstreamError, UpstreamMalformed,
                          UpstreamMisbehaved, UpstreamNotFound, UpstreamTooLarge,
                          UpstreamUnreachable, UserGone)

MAX_INT = 2 ** 63
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


# ---- the read-only allow-list --------------------------------------------------------------
class Route:
    """One allowed request shape.

    `user_scoped` routes carry the bound upstream user id, and the guard checks it:
      * `bind_in="query"`: the query parameter `bind_param` must equal the bound id;
      * `bind_in="path"`: the regex group `path_group` of `pattern` must equal the bound id.
    A route that is not user scoped must not carry the identity at all (query form).
    `not_found` declares what a 404 on this route means: `UserGone` (addressed by the bound user),
    `ItemGone` (addressed by one item) or `RouteMissing` (a fixed route).
    """

    def __init__(self, name: str, pattern: str, query_keys: Tuple[str, ...], user_scoped: bool,
                 needs_user: bool = True, not_found: type = UserGone, bind_in: str = "query",
                 bind_param: str = "userId", path_group: str = "user"):
        if bind_in not in ("query", "path"):
            raise ValueError("bind_in")
        self.name = name
        self.pattern = re.compile(pattern)
        self.query_keys = frozenset(query_keys)
        self.user_scoped = user_scoped
        self.needs_user = needs_user        # a mapped user must exist before this route is used
        self.not_found = not_found
        self.bind_in = bind_in
        self.bind_param = bind_param
        self.path_group = path_group
        if user_scoped and bind_in == "path" and path_group not in self.pattern.groupindex:
            raise ValueError("a path-bound route needs a named group for the user id")


def check_request(routes: Sequence[Route], id_pattern: Pattern[str], method: Any, path: Any,
                  query: Optional[Mapping[str, str]], bound_user_id: Optional[str]) -> Route:
    """Raise ForbiddenRequest unless this is an allow-listed read-only request for the bound user."""
    if method != "GET":
        raise ForbiddenRequest("method")
    if not isinstance(path, str):
        raise ForbiddenRequest("path")
    hit = None
    for r in routes:
        m = r.pattern.fullmatch(path)
        if m is not None:
            hit = (r, m)
            break
    if hit is None:
        raise ForbiddenRequest("path")
    route, match = hit
    if bound_user_id is not None and (not isinstance(bound_user_id, str)
                                      or id_pattern.fullmatch(bound_user_id) is None):
        raise ForbiddenRequest("bound user id")
    query = dict(query or {})
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in query.items()):
        raise ForbiddenRequest("query")
    if not set(query) <= route.query_keys:
        raise ForbiddenRequest("query")
    if route.needs_user and bound_user_id is None:
        raise ForbiddenRequest("no mapped user")
    if route.user_scoped:
        carried = query.get(route.bind_param) if route.bind_in == "query" else match.group(route.path_group)
        if carried != bound_user_id:
            raise ForbiddenRequest("user scope")
    elif route.bind_param in query:
        raise ForbiddenRequest("user scope")
    return route


class GuardedTransport:
    """Wraps an inner Transport. Same `request` signature; checks first, then delegates. A bare 404
    from the inner transport is re-raised as the class the matched ROUTE declares."""

    def __init__(self, inner: Transport, routes: Sequence[Route], id_pattern: Pattern[str],
                 bound_user_id: Optional[str] = None):
        if bound_user_id is not None and (not isinstance(bound_user_id, str)
                                          or id_pattern.fullmatch(bound_user_id) is None):
            raise ForbiddenRequest("bound user id")        # defence in depth: never bind a malformed id
        self._inner = inner
        self._routes = tuple(routes)
        self._pattern = id_pattern
        self._bound = bound_user_id

    def _clone(self, user_id: Optional[str]) -> "GuardedTransport":
        return GuardedTransport(self._inner, self._routes, self._pattern, user_id)

    def bind(self, user_id: Optional[str]) -> "GuardedTransport":
        return self._clone(user_id)

    def request(self, method, path, query, timeout, max_bytes) -> TransportResponse:
        route = check_request(self._routes, self._pattern, method, path, query, self._bound)
        try:
            return self._inner.request(method, path, query, timeout, max_bytes)
        except UpstreamNotFound as exc:
            if type(exc) is UpstreamNotFound:             # a bare 404: the ROUTE says what it means
                raise route.not_found(exc.status) from None
            raise

    def __repr__(self) -> str:
        return "GuardedTransport(<redacted>)"


# ---- small pure helpers --------------------------------------------------------------------
def bounded_int(value: Any) -> Optional[int]:
    """A bounded integer from upstream JSON, or None. Hostile magnitudes are rejected here so
    later arithmetic can neither overflow nor divide by something absurd."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = int(value)
    except (OverflowError, ValueError):
        return None
    return number if -MAX_INT < number < MAX_INT else None


def image_magic_ok(ctype: str, body: bytes) -> bool:
    """The bytes must really be the image type claimed (the serving app must still send
    X-Content-Type-Options: nosniff, see ADAPTER-CONTRACT.md)."""
    if ctype == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if ctype == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if ctype == "image/webp":
        return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    return False


def norm_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def match_exactly_one(wanted: str, entries: Sequence[Any],
                      extract: Callable[[Any], Optional[Tuple[str, str]]]) -> Tuple[str, Any]:
    """Pick the one upstream account whose name equals `wanted` EXACTLY (case-sensitive, no
    normalisation). `extract(entry)` returns `(name, upstream_id)` or None for an unparsable entry.

    * a non-empty list in which nothing is parsable is schema drift: `UpstreamMalformed`;
    * no exact match: `MappingFailed("case_or_unicode_mismatch")` if some entry matches loosely
      (NFKC, case folding, trimming), else `MappingFailed("unmapped")`: loose matches never link;
    * two exact matches, or one exact match that also collides loosely with another: ambiguous,
      `AmbiguousMappingError`: refused, never picked.
    Returns `(upstream_id, entry)`."""
    loose_wanted = norm_name(wanted)
    exact, loose = {}, {}
    parsed = 0
    for entry in entries:
        got = extract(entry)
        if got is None:
            continue
        parsed += 1
        name, uid = got
        if norm_name(name) == loose_wanted:
            loose[uid] = entry
            if name == wanted:
                exact[uid] = entry
    if entries and parsed == 0:
        raise UpstreamMalformed()
    if len(exact) > 1 or (len(exact) == 1 and len(loose) > 1):
        raise AmbiguousMappingError()
    if not exact:
        raise MappingFailed("case_or_unicode_mismatch" if loose else "unmapped")
    (uid, entry), = exact.items()
    return uid, entry


# ---- the adapter base ----------------------------------------------------------------------
class GuardedAdapter(MediaAdapter):
    """A `MediaAdapter` whose every request goes through a `GuardedTransport`."""

    def __init__(self, guard: GuardedTransport, timeout: float = DEFAULT_TIMEOUT, **kw):
        kw.setdefault("request_timeout", timeout)       # one number drives the budget AND each call
        super().__init__(**kw)
        self._guard = guard
        self._timeout = timeout

    def _budget(self) -> CallBudget:
        return self.current_budget()

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

    def _get_json(self, guard: GuardedTransport, budget: CallBudget, path: str,
                  query: Optional[Mapping[str, str]]) -> Any:
        resp = self._get(guard, budget, path, query)
        try:
            return json.loads(resp.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError, MemoryError):
            raise UpstreamMalformed() from None

    def _fetch_image(self, guard: GuardedTransport, budget: CallBudget, path: str,
                     query: Optional[Mapping[str, str]]) -> ArtworkResult:
        """An image route. A 404 (ItemGone, declared by the route) is simply "no artwork"; a body
        whose content type is not an allowed image type or whose bytes do not match is drift."""
        try:
            resp = self._get(guard, budget, path, query, MAX_IMAGE_BYTES)
        except ItemGone:
            return ArtworkResult(SectionState.EMPTY)
        ctype = resp.content_type.split(";")[0].strip().lower()
        if ctype not in IMAGE_TYPES or not image_magic_ok(ctype, resp.body):
            raise UpstreamMalformed()
        return ArtworkResult(SectionState.OK, ctype, resp.body)

    @staticmethod
    def _parse_many(raws: Any, limit: int, parse_one: Callable[[Any], Tuple[Any, str]]) -> Tuple[Any, ...]:
        """Parse a listing. `parse_one(raw)` returns `(item_or_None, status)` where status is "ok",
        "filtered" (a legitimate drop) or "bad" (unparsable: counts as drift). More entries than the
        limit is hostile (limit ignored: possibly an unscoped listing); if EVERY raw entry is bad the
        whole listing is `UpstreamMalformed` and is never cached as an empty success."""
        if not isinstance(raws, list):
            raise UpstreamMalformed()
        if len(raws) > limit:
            raise UpstreamMisbehaved()
        out: List[Any] = []
        seen = set()
        bad = 0
        for raw in raws:
            item, status = parse_one(raw)
            bad += status == "bad"
            if item is not None and item.id not in seen:
                seen.add(item.id)
                out.append(item)
        if raws and bad == len(raws):
            raise UpstreamMalformed()
        return tuple(out)
