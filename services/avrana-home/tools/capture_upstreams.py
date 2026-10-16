#!/usr/bin/env python3
"""Owner-run, read-only capture of upstream responses for the four Avrana home adapters.

    ADAPTER-CONTRACT.md sections 11.7 (Audiobookshelf), 12.5 (Komga), 13.6 (Calibre-Web) and the
    Jellyfin recorded check. Standard library only.

WHO RUNS IT. The owner, on the owner's own machine, with the owner's own accounts. No agent runs it
against a live server. Nothing in this repository runs it.

WHAT IT DOES. It sends only HTTP GET requests, and only to routes that the adapters themselves allow:
every request is first checked with the adapters' own `ALLOWED_ROUTES` through `check_request`
(`avrana_home/adapters/_base.py`), so a route the adapters do not make cannot be requested from here
either. It never follows a redirect, never uses a proxy, caps every body with the same limits as
`avrana_home/resilience.py`, and keeps request headers (and so every credential) in memory only.

CREDENTIALS. Base URLs and tokens are read from environment variables that the owner sets in their own
shell. They are never accepted as command-line arguments and never printed, logged or written. Names:

    AVRANA_CAPTURE_JELLYFIN_URL            AVRANA_CAPTURE_JELLYFIN_KEY
    AVRANA_CAPTURE_AUDIOBOOKSHELF_URL      AVRANA_CAPTURE_AUDIOBOOKSHELF_TOKEN
    AVRANA_CAPTURE_KOMGA_URL               AVRANA_CAPTURE_KOMGA_TOKEN
    AVRANA_CAPTURE_CALIBRE_WEB_URL         AVRANA_CAPTURE_CALIBRE_WEB_USER   AVRANA_CAPTURE_CALIBRE_WEB_PASSWORD
    AVRANA_CAPTURE_OWN_USERNAME            (optional; not a secret; or use --own-username)

PRIVACY (owner decision): STRICT FIELD ALLOWLISTING FIRST, redaction second. Responses are held in memory.
Before anything else, every response is cut down to the exact fields (JSON) or elements (OPDS/Atom) that the
Home adapters READ, keeping nesting and list shape so the result still works as an adapter fixture. Every
other field is dropped, whatever it holds: tags and labels the adapters do not read, device ids, cover and
other paths, external URLs, provider ids (IMDb, TMDB, ISBN, ASIN), last-login and other timestamps, host and
server names. An unknown or new field is therefore dropped by default. A route with no allowlist is not
written at all. `--show-allowlist` prints the kept fields per service and route and makes no network call.

External URLs are dropped. Provider ids are dropped unless the owner passes `--keep-provider-ids`, which is
only for a specific validation (for example checking that an adapter reads an IMDb id correctly).

REDACTION, applied to what the allowlist kept: tokens, API keys, passwords, session ids and cookies; e-mail
addresses; usernames other than the owner's own; host names and IP addresses; file paths; titles, authors
and descriptions; library, item and user ids (replaced consistently by synthetic ids of the same shape so
shapes and cross references survive). A final scan refuses to write any file that still matches a
secret-like pattern. Redaction is a safety net, not proof: read the output before sharing it.

NOT REDACTED (by design, so the evidence is useful): field names, JSON types, numbers, booleans, the
timestamps an adapter reads (Audiobookshelf lastUpdate), HTTP status codes and content types. Dotted quads
such as a four-part version number look like IP addresses and ARE replaced, so note the server version by
hand. Nothing leaves the owner's machine unless the owner hands the output directory over.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import ipaddress
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

from avrana_home.adapters import audiobookshelf as _abs  # noqa: E402
from avrana_home.adapters import calibre_web as _cw  # noqa: E402
from avrana_home.adapters import jellyfin as _jf  # noqa: E402
from avrana_home.adapters import komga as _kg  # noqa: E402
from avrana_home.adapters._base import check_request  # noqa: E402
from avrana_home.contract import ForbiddenRequest  # noqa: E402
from avrana_home.resilience import DEFAULT_TIMEOUT, MAX_IMAGE_BYTES, MAX_JSON_BYTES, UpstreamMalformed  # noqa: E402

PREFIX = "AVRANA_CAPTURE_"
MAX_TIMEOUT = 30.0
MAX_MEMBERS = 4
MAX_ITEMS = 4
REDACTED = "[REDACTED]"
HOST_PLACEHOLDER = "host.invalid"

# Per service: the adapter's own allow-list and bound-id pattern, and the environment variables.
SERVICES: Dict[str, Dict[str, Any]] = {
    "jellyfin": {"routes": _jf.ALLOWED_ROUTES, "bound": _jf._BOUND_ID, "url": "JELLYFIN_URL",
                 "secrets": ("JELLYFIN_KEY",)},
    "audiobookshelf": {"routes": _abs.ALLOWED_ROUTES, "bound": _abs._BOUND_ID, "url": "AUDIOBOOKSHELF_URL",
                       "secrets": ("AUDIOBOOKSHELF_TOKEN",)},
    "komga": {"routes": _kg.ALLOWED_ROUTES, "bound": _kg._BOUND_ID, "url": "KOMGA_URL",
              "secrets": ("KOMGA_TOKEN",)},
    "calibre-web": {"routes": _cw.ALLOWED_ROUTES, "bound": _cw._BOUND_ID, "url": "CALIBRE_WEB_URL",
                    "secrets": ("CALIBRE_WEB_USER", "CALIBRE_WEB_PASSWORD")},
}


class CaptureError(Exception):
    """A usage or configuration problem. The message never contains a credential or a URL."""


# =====================================================================================================
# Transport: GET only, allow-listed, no redirects, no proxy, bounded
# =====================================================================================================
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                      # a redirect could carry the credential elsewhere


class Response:
    def __init__(self, status: int, body: Optional[bytes], ctype: str = "", error: str = ""):
        self.status, self.body, self.ctype, self.error = status, body, ctype, error

    @property
    def ok(self) -> bool:
        return self.body is not None and 200 <= self.status < 300


def validate_base_url(raw: str, allow_insecure_http: bool = False) -> str:
    try:
        parts = urllib.parse.urlsplit(raw)
        host = parts.hostname
        parts.port
    except ValueError:
        raise CaptureError("a base URL is not valid") from None
    if parts.scheme not in ("http", "https") or not host:
        raise CaptureError("a base URL must start with http:// or https://")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise CaptureError("a base URL must not contain credentials")
    if parts.query or parts.fragment:
        raise CaptureError("a base URL must not have a query or fragment")
    loopback = host == "localhost" or _is_loopback(host)
    if parts.scheme == "http" and not loopback and not allow_insecure_http:
        raise CaptureError("a non-loopback base URL must be https (or pass --allow-insecure-http)")
    return raw.rstrip("/")


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class Client:
    """One service. Every request is checked against the adapters' allow-list first."""

    def __init__(self, name: str, base_url: str, headers: Mapping[str, str], timeout: float,
                 dry_run: bool = False):
        self.name = name
        self._base = base_url
        self._headers = dict(headers)
        self._timeout = timeout
        self.dry = dry_run
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.log: List[str] = []          # request lines (path and query only), for dry-run output

    def __repr__(self) -> str:
        return f"Client({self.name}, <redacted>)"

    def allows(self, path: str, query: Optional[Mapping[str, str]], bound: Optional[str]) -> bool:
        """Whether the adapters in THIS checkout make this request (their own `ALLOWED_ROUTES`). Used only to
        pick between route shapes that differ between adapter versions (search, the Calibre-Web cover route);
        `get` still checks every request itself and refuses anything else."""
        spec = SERVICES[self.name]
        try:
            check_request(spec["routes"], spec["bound"], "GET", path, query, bound)
        except ForbiddenRequest:
            return False
        return True

    def get(self, path: str, query: Optional[Mapping[str, str]], bound: Optional[str],
            max_bytes: int = MAX_JSON_BYTES) -> Response:
        spec = SERVICES[self.name]
        try:
            check_request(spec["routes"], spec["bound"], "GET", path, query, bound)
        except ForbiddenRequest:
            raise CaptureError(f"{self.name}: the adapters do not make this request; refused") from None
        shown = {k: ("<term>" if k in SEARCH_KEYS else v) for k, v in (query or {}).items()}
        self.log.append(path + (("?" + urllib.parse.urlencode(shown)) if shown else ""))
        if self.dry:
            return Response(0, None, error="dry-run")
        url = self._base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        req = urllib.request.Request(url, method="GET", headers=self._headers)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                body = resp.read(max_bytes + 1)
                status = resp.status
                ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
        except urllib.error.HTTPError as exc:
            return Response(exc.code, None, error="redirect_refused" if 300 <= exc.code < 400 else "http_error")
        except TimeoutError:
            return Response(0, None, error="timeout")
        except urllib.error.URLError as exc:
            return Response(0, None, error="timeout" if isinstance(exc.reason, TimeoutError) else "unreachable")
        except (OSError, ValueError):
            return Response(0, None, error="unreachable")
        if len(body) > max_bytes:
            return Response(status, None, ctype, error="too_large")
        return Response(status, body, ctype)


# =====================================================================================================
# Capture steps
# =====================================================================================================
class Capture:
    def __init__(self, service: str, route: str, path: str, resp: Response, kind: str):
        self.service, self.route, self.path = service, route, path
        self.status, self.ctype, self.error = resp.status, resp.ctype, resp.error
        self.body = resp.body if resp.ok else None
        self.kind = kind                 # "json" | "xml" | "image"
        self.summary: Dict[str, Any] = {}
        if kind == "image":
            self.summary = {"bytes": len(resp.body) if resp.body is not None else None,
                            "magic_ok": _image_magic(resp.body) if resp.body is not None else None}
            self.body = None


def _image_magic(body: bytes) -> bool:
    return body.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (body[:4] == b"RIFF" and body[8:12] == b"WEBP")


def _json(resp: Response) -> Any:
    if not resp.ok:
        return None
    try:
        return json.loads(resp.body.decode("utf-8"))
    except (ValueError, RecursionError):
        return None


class Options:
    def __init__(self, members: Sequence[str], max_items: int, images: bool, calibre_probe_id: Optional[int],
                 search_term: Optional[str] = None):
        self.members, self.max_items, self.images, self.probe = tuple(members), max_items, images, calibre_probe_id
        self.term = search_term          # plain letters, digits and spaces only; never printed or written


# The query keys that carry the search term (one per service). Dry-run output shows `<term>` instead.
SEARCH_KEYS = frozenset({"searchTerm", "q", "search", "query"})
_SEARCH_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ]{1,39}")     # stricter than Home's clean_query: a plain word
_ABS_LIBRARY = re.compile(r"(?:lib_[a-z0-9]{3,40}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
SKIPPED_NOTE = "search route not in this checkout's adapters; not requested"


def _skip(c: "Client", route: str) -> "Capture":
    """A planned search that the adapters in this checkout do not make: recorded as skipped, nothing is sent."""
    return Capture(c.name, route, "(skipped)", Response(0, None, error="not_in_adapters"), "json")


_DUMMY_HEX = "0" * 31 + "1"
_DUMMY_UUID = "00000000-0000-4000-8000-000000000001"
_DUMMY_KOMGA = "DUMMYID01"
KOMGA_SHARED = "shared"          # a local label for the route check only (shared regular-account view)


def _pick(users: Any, wanted: Sequence[str], name_keys: Tuple[str, ...], id_key: str = "Id") -> List[Tuple[str, str]]:
    """(name, id) for each wanted username, matched exactly (a Komga/Audiobookshelf/Jellyfin username)."""
    out = []
    if isinstance(users, list):
        for u in users:
            if not isinstance(u, dict):
                continue
            name = next((u[k] for k in name_keys if isinstance(u.get(k), str)), None)
            uid = u.get(id_key)
            if name in wanted and isinstance(uid, str) and all(uid != x[1] for x in out):
                out.append((name, uid))
    return out


def capture_jellyfin(c: Client, o: Options) -> List[Capture]:
    caps: List[Capture] = []
    r = c.get("/Users", None, None)
    caps.append(Capture(c.name, "users", "/Users", r, "json"))
    # Dry run: one distinct dummy id per member, so every member's planned requests are shown.
    users = _json(r) if not c.dry else [{"Name": m, "Id": f"{i + 1:032x}"} for i, m in enumerate(o.members)]
    for _, raw_id in _pick(users, o.members, ("Name",), "Id")[:MAX_MEMBERS]:
        uid = _jf.normalise_guid(raw_id)
        if uid is None:
            continue
        q = {"userId": uid, "limit": "12", "mediaTypes": "Video", "fields": _jf._ITEM_FIELDS,
             "enableUserData": "true", "enableImageTypes": "Primary", "enableTotalRecordCount": "false"}
        caps.append(Capture(c.name, "resume", "/UserItems/Resume", c.get("/UserItems/Resume", q, uid), "json"))
        q = {"userId": uid, "limit": "12", "includeItemTypes": "Movie,Series,Episode", "groupItems": "true",
             "fields": _jf._ITEM_FIELDS, "enableImageTypes": "Primary", "enableUserData": "true"}
        lr = c.get("/Items/Latest", q, uid)
        caps.append(Capture(c.name, "latest", "/Items/Latest", lr, "json"))
        latest = _json(lr) if not c.dry else [{"Id": _DUMMY_HEX}]
        ids = [x["Id"] for x in latest if isinstance(x, dict) and isinstance(x.get("Id"), str)] \
            if isinstance(latest, list) else []
        for raw_item in ids[:o.max_items]:
            item = _jf.normalise_guid(raw_item)
            if item is None:
                continue
            q = {"userId": uid, "ids": item, "fields": _jf._ITEM_FIELDS, "enableUserData": "true",
                 "enableImageTypes": "Primary"}
            caps.append(Capture(c.name, "items", "/Items", c.get("/Items", q, uid), "json"))
            if o.images:
                caps.append(Capture(c.name, "image", "/Items/{id}/Images/Primary",
                                    c.get(f"/Items/{item}/Images/Primary", {"maxWidth": "400", "quality": "80"},
                                          uid, MAX_IMAGE_BYTES), "image"))
        if o.term:
            # Current adapters search through `/Items?userId=&searchTerm=` (Jellyfin 10.9+); older ones used the
            # legacy `/Users/{id}/Items`. Only the shape the adapters in this checkout allow is requested.
            q = {"searchTerm": o.term, "includeItemTypes": "Movie,Series,Episode", "recursive": "true",
                 "limit": "5", "fields": _jf._ITEM_FIELDS, "enableImageTypes": "Primary", "enableUserData": "true"}
            if c.allows("/Items", dict(q, userId=uid), uid):
                caps.append(Capture(c.name, "search", "/Items?searchTerm=", c.get("/Items", dict(q, userId=uid), uid),
                                    "json"))
            elif c.allows(f"/Users/{uid}/Items", q, uid):
                caps.append(Capture(c.name, "search", "/Users/{id}/Items", c.get(f"/Users/{uid}/Items", q, uid), "json"))
            else:
                caps.append(_skip(c, "search"))
    return caps


def capture_audiobookshelf(c: Client, o: Options) -> List[Capture]:
    caps: List[Capture] = []
    r = c.get("/api/users", None, None)
    caps.append(Capture(c.name, "users", "/api/users", r, "json"))
    body = _json(r) if not c.dry else {"users": [{"username": m, "id": f"00000000-0000-4000-8000-{i + 1:012x}"}
                                                 for i, m in enumerate(o.members)]}
    users = body.get("users") if isinstance(body, dict) else None
    seen_items: List[str] = []
    for _, uid in _pick(users, o.members, ("username",), "id")[:MAX_MEMBERS]:
        if _abs._BOUND_ID.fullmatch(uid) is None:
            continue
        rr = c.get(f"/api/users/{uid}", None, uid)
        caps.append(Capture(c.name, "user", "/api/users/{id}", rr, "json"))
        rec = _json(rr) if not c.dry else {"mediaProgress": [{"libraryItemId": "li_dummy01"}]}
        entries = rec.get("mediaProgress") if isinstance(rec, dict) else None
        for e in entries if isinstance(entries, list) else []:
            item = e.get("libraryItemId") if isinstance(e, dict) else None
            if isinstance(item, str) and re.fullmatch(_abs._ITEM_PATH, item) and item not in seen_items:
                seen_items.append(item)
        for item in seen_items[:o.max_items]:
            caps.append(Capture(c.name, "item", "/api/items/{id}",
                                c.get(f"/api/items/{item}", {"expanded": "1"}, uid), "json"))
        seen_items = []
        if o.term:
            caps += _abs_search(c, o, uid, rec)
    return caps


def _abs_search(c: "Client", o: Options, uid: str, rec: Any) -> List["Capture"]:
    """The member's libraries (their own `librariesAccessible`, or the library list when the record grants every
    library), then one library search each, at most `max_items` libraries. Only if the adapters make these."""
    caps: List[Capture] = []
    if not c.allows("/api/libraries", None, uid) or not c.allows(f"/api/libraries/{_DUMMY_UUID}/search",
                                                                  {"q": o.term, "limit": "5"}, uid):
        return [_skip(c, "search")]
    libs = rec.get("librariesAccessible") if isinstance(rec, dict) else None
    perms = rec.get("permissions") if isinstance(rec, dict) else None
    if c.dry or (isinstance(perms, dict) and perms.get("accessAllLibraries") is True):
        lr = c.get("/api/libraries", None, uid)
        caps.append(Capture(c.name, "libraries", "/api/libraries", lr, "json"))
        body = _json(lr) if not c.dry else {"libraries": [{"id": _DUMMY_UUID, "mediaType": "book"}]}
        raws = body.get("libraries") if isinstance(body, dict) else None
        libs = ([x.get("id") for x in raws if isinstance(x, dict) and x.get("mediaType") in (None, "book")]
                if isinstance(raws, list) else [])
    for lib in [x for x in (libs or []) if isinstance(x, str) and _ABS_LIBRARY.fullmatch(x)][:o.max_items]:
        caps.append(Capture(c.name, "search", "/api/libraries/{id}/search",
                            c.get(f"/api/libraries/{lib}/search", {"q": o.term, "limit": "5"}, uid), "json"))
    return caps


def capture_komga(c: Client, o: Options) -> List[Capture]:
    """Komga is a SHARED regular-account view (owner decision): the regular key only. `GET /api/v2/users` is
    admin-only and is never requested. The adapters' route check needs some bound label; it is never sent."""
    caps: List[Capture] = []
    bound = KOMGA_SHARED
    lr = c.get("/api/v1/books/latest", {"page": "0", "size": "5"}, bound)
    caps.append(Capture(c.name, "latest", "/api/v1/books/latest", lr, "json"))
    page = _json(lr) if not c.dry else {"content": [{"id": _DUMMY_KOMGA, "seriesId": _DUMMY_KOMGA}]}
    books = page.get("content") if isinstance(page, dict) else None
    # The shared view reads latest, a book and its thumbnail only (#50); series is not a route it uses.
    for b in (books if isinstance(books, list) else [])[:o.max_items]:
        if not isinstance(b, dict) or not _kg._item_id(b.get("id")):
            continue
        bid = b["id"]
        caps.append(Capture(c.name, "book", "/api/v1/books/{id}", c.get(f"/api/v1/books/{bid}", None, bound), "json"))
        if o.images:
            caps.append(Capture(c.name, "thumbnail", "/api/v1/books/{id}/thumbnail",
                                c.get(f"/api/v1/books/{bid}/thumbnail", None, bound, MAX_IMAGE_BYTES), "image"))
    if o.term:
        q = {"search": o.term, "page": "0", "size": "5"}
        caps.append(Capture(c.name, "search", "/api/v1/books?search=", c.get("/api/v1/books", q, bound), "json")
                    if c.allows("/api/v1/books", q, bound) else _skip(c, "search"))
    return caps


def capture_calibre(c: Client, o: Options) -> List[Capture]:
    caps: List[Capture] = []
    shared = _cw.SHARED_VIEWER
    r = c.get("/opds/new", None, shared)
    caps.append(Capture(c.name, "new", "/opds/new", r, "xml"))
    text = r.body.decode("utf-8", "replace") if r.ok else ""
    ids = [] if not r.ok else list(dict.fromkeys(m.group(1) for m in _cw._COVER_HREF.finditer(text)))
    if c.dry:
        ids = ["1"]
    covers = ids[:1] if o.images else []
    if o.probe is not None:
        covers.append(str(o.probe))
    # The cover route the adapters in this checkout use: `/opds/cover_240_240/{id}` (Calibre-Web Automated v4,
    # seen on the owner preview) or the older `/opds/thumb_cover/{id}`.
    cover = next((t for t in ("/opds/cover_240_240/", "/opds/thumb_cover/") if c.allows(t + "1", None, shared)), None)
    for cid in covers if cover else []:
        caps.append(Capture(c.name, "thumbnail", cover + "{id}",
                            c.get(f"{cover}{cid}", None, shared, MAX_IMAGE_BYTES), "image"))
    if o.term:
        q = {"query": o.term}
        caps.append(Capture(c.name, "search", "/opds/search?query=", c.get("/opds/search", q, shared), "xml")
                    if c.allows("/opds/search", q, shared) else _skip(c, "search"))
    return caps


CAPTURE = {"jellyfin": capture_jellyfin, "audiobookshelf": capture_audiobookshelf,
           "komga": capture_komga, "calibre-web": capture_calibre}


# =====================================================================================================
# Redaction
# =====================================================================================================
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_IPV4 = re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])")
_IPV6 = re.compile(r"(?<![\w:])(?=[0-9A-Fa-f:]*::)(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"
                   r"|(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}(?![\w:])")
_NS_HOSTS = r"(?:www\.w3\.org|opds-spec\.org|purl\.org)(?![\w.\-])"   # XML namespaces and OPDS relation URIs: not hosts
_URL_HOST = re.compile(r"(?i)\b(https?://)(?!" + _NS_HOSTS + r")([^/\s\"'<>?#]+)")
_HEX32 = re.compile(r"(?<![0-9A-Fa-f])[0-9a-f]{32}(?![0-9A-Fa-f])")
_UUID = re.compile(r"(?<![0-9A-Fa-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9A-Fa-f])")
_ABS_ID = re.compile(r"\bli_[a-z0-9]{6,40}\b")
_WIN_PATH = re.compile(r"\\\\[?.]\\[^\s\"'<>]*|[A-Za-z]:\\[^\s\"'<>|]*|\\\\[\w.$\-]+\\[^\s\"'<>]*"
                       # also file:// URLs, forward-slash drive paths (c:/users/...) and //host/share UNC paths
                       r"|(?i:file:/{2,3})[^\s\"'<>]+|(?<![A-Za-z0-9])[A-Za-z]:/[^\s\"'<>|]+"
                       r"|(?<![:/\w])//[\w.$\-]+/[^\s\"'<>]+")
_UNIX_PATH = re.compile(
    r"(?<![\w/.:\-])/(?:home|mnt|media|data|srv|var|usr|opt|tmp|etc|root|config|library|libraries|books|"
    r"audiobooks|comics|manga|movies|tv|music|downloads|volume\d|Users(?=/[^/\s]+/)|Volumes(?=/[^/\s]+/)|app|cache)(?:/[^\s\"'<>?#]*)?")
_AUTH_TEXT = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]{6,}")
_MB_TEXT = re.compile(r"(?i)(Token\s*=\s*\"?)[^\"\s,;]{4,}")
_CRED_PARAM = re.compile(r"(?i)((?:api[_\-]?key|apikey|access[_\-]?token|token|auth|sid|session(?:id)?|"
                         r"connect\.sid|x-emby-token|x-api-key|password|secret)\s*[=:]\s*\"?)[^\s\"'&;,<>]{3,}")
_ISO_TEXT_TITLE = re.compile(r"(?is)<(title|name|summary|content|subtitle|dc:language)(\s[^>]*)?>(.*?)</\1>")

_SENSITIVE_KEY = re.compile(r"(?i)token|secret|passw|apikey|api_key|authorization|cookie|session|credential|"
                            r"^key$|^sid$|^pin$|^hash$|^salt$|accesskey|privatekey")
_TITLE_KEYS = frozenset({
    "title", "name", "sortname", "originaltitle", "subtitle", "authorname", "authors", "author", "narrator",
    "narratorname", "seriesname", "series", "seriestitle", "description", "overview", "summary", "tagline",
    "publisher", "comment", "titlesort", "sorttitle", "forcedsorttitle", "artists", "albumartist", "label"})
_PATH_KEYS = frozenset({"path", "paths", "folder", "folders", "rootfolder", "directory", "file", "filename",
                        "fullpath", "relpath", "libraryfolders", "url", "ffprobecache"})
_PATH_KEY_SUFFIX = re.compile(r"(?i)(?:path|paths|folder|filename)$")     # coverPath, metadataPath, ...
_TAG_KEY = re.compile(r"(?i)(?:tags?|labels?)(?:selected|allow|exclude|accessible)?$")   # member labels: free text
_USER_KEYS = frozenset({"username", "username", "login", "displayname", "user", "owner", "createdby"})
_ID_KEY = re.compile(r"(?i)(?:^|[a-z])ids?$|devices?$|^librariesaccessible$")


def _label(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(97 + r) + s
    return s


def is_synthetic_id(s: str) -> bool:
    return bool(re.fullmatch(r"0{16,}[0-9a-f]{1,16}|00000000-0000-4000-8000-[0-9a-f]{12}|li_[0-9a-f]{8}|ID\d{8}", s))


class Redactor:
    """Consistent pseudonyms for one run. Feed it everything with `learn`, then `redact_*`."""

    def __init__(self, secrets: Sequence[str] = (), hosts: Sequence[str] = (), own_username: str = "",
                 extra_usernames: Sequence[str] = ()):
        self.secrets = sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True)
        self.hosts = [h for h in hosts if h]
        self.own = own_username
        self.users: Dict[str, str] = {}
        self.emails: Dict[str, str] = {}
        self.ids: Dict[str, str] = {}
        self.titles: Dict[str, str] = {}
        self.counts: Counter = Counter()
        for u in extra_usernames:
            self._user(u)

    # ---- maps ----
    def _user(self, name: str) -> Optional[str]:
        if not isinstance(name, str) or not name.strip() or name == self.own:
            return None
        if name not in self.users:
            self.users[name] = f"member-{_label(len(self.users))}"
        return self.users[name]

    def _id(self, value: str) -> str:
        if value in self.ids:
            return self.ids[value]
        n = len(self.ids) + 1
        if _HEX32.fullmatch(value.lower()) and len(value) == 32:
            out = f"{n:032x}"
        elif _UUID.fullmatch(value.lower()):
            out = f"00000000-0000-4000-8000-{n:012x}"
        elif value.startswith("li_"):
            out = f"li_{n:08x}"
        else:
            out = f"ID{n:08d}"
        if is_synthetic_id(value):
            return value
        self.ids[value] = out
        return out

    def _title(self, value: str) -> str:
        if value not in self.titles:
            self.titles[value] = f"Title {len(self.titles) + 1}"
        return self.titles[value]

    def _tag(self, value: str) -> str:
        if value not in self.titles:
            self.titles[value] = f"Tag {len(self.titles) + 1}"
        return self.titles[value]

    # ---- learning (before anything is written) ----
    def learn(self, caps: Sequence[Capture]) -> None:
        for cap in caps:
            if cap.body is None:
                continue
            text = cap.body.decode("utf-8", "replace")
            if cap.kind == "json":
                try:
                    self._learn_json(json.loads(text), cap.route == "users")
                except (ValueError, RecursionError):
                    pass
            for m in _EMAIL.finditer(text):
                self._email(m.group(0))
            for rx in (_HEX32, _UUID, _ABS_ID):
                for m in rx.finditer(text):
                    self._id(m.group(0))

    def _learn_json(self, obj: Any, users_route: bool) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()
                if isinstance(v, str):
                    if kl in _USER_KEYS or (users_route and kl in ("name", "email")):
                        if "@" in v:
                            self._email(v)
                        else:
                            self._user(v)
                    elif _ID_KEY.search(k) and re.fullmatch(r"[A-Za-z0-9_\-]{6,64}", v):
                        self._id(v)
                elif isinstance(v, list) and _ID_KEY.search(k):
                    for x in v:
                        if isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_\-]{6,64}", x):
                            self._id(x)
                if isinstance(v, (dict, list)):
                    self._learn_json(v, users_route)
        elif isinstance(obj, list):
            for x in obj:
                self._learn_json(x, users_route)

    def _email(self, value: str) -> str:
        key = value.lower()
        if key.endswith("@example.invalid"):
            return value                   # already a placeholder
        if key not in self.emails:
            self.emails[key] = f"user{len(self.emails) + 1}@example.invalid"
        return self.emails[key]

    # ---- text ----
    def redact_text(self, s: str) -> str:
        for secret in self.secrets:
            if secret in s:
                self.counts["secret"] += s.count(secret)
                s = s.replace(secret, REDACTED)
        s = _AUTH_TEXT.sub(lambda m: self._count("secret", f"{m.group(1)} {REDACTED}"), s)
        s = _MB_TEXT.sub(lambda m: self._count("secret", m.group(1) + REDACTED), s)
        s = _CRED_PARAM.sub(lambda m: self._count("secret", m.group(1) + REDACTED), s)
        s = _EMAIL.sub(lambda m: self._count("email", self._email(m.group(0))), s)
        s = _URL_HOST.sub(lambda m: self._count("host", m.group(1) + HOST_PLACEHOLDER), s)
        for h in self.hosts:
            s = re.sub(re.escape(h), lambda m: self._count("host", HOST_PLACEHOLDER), s, flags=re.I)
        s = _IPV4.sub(lambda m: self._count("ip", "[ip]"), s)
        s = _IPV6.sub(lambda m: self._count("ip", "[ip]"), s)
        s = _WIN_PATH.sub(lambda m: self._count("path", "[path]"), s)
        s = _UNIX_PATH.sub(lambda m: self._count("path", "[path]"), s)
        for rx in (_UUID, _HEX32, _ABS_ID):
            s = rx.sub(lambda m: self._count("id", self._id(m.group(0))), s)
        for value, repl in sorted(self.ids.items(), key=lambda kv: len(kv[0]), reverse=True):
            if value in s:
                s = re.sub(rf"(?<![A-Za-z0-9_\-]){re.escape(value)}(?![A-Za-z0-9_\-])",
                           lambda m: self._count("id", repl), s)
        for name, repl in sorted(self.users.items(), key=lambda kv: len(kv[0]), reverse=True):
            s = re.sub(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])",
                       lambda m: self._count("username", repl), s, flags=re.I)
        return s

    def _count(self, kind: str, repl: str) -> str:
        self.counts[kind] += 1
        return repl

    # ---- structure ----
    def redact_json(self, obj: Any, key: str = "", users_route: bool = False) -> Any:
        kl = key.lower()
        if isinstance(obj, dict):
            return {self.redact_text(k): self.redact_json(v, k, users_route) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.redact_json(v, key, users_route) for v in obj]
        if not isinstance(obj, str):
            return obj
        if key and _SENSITIVE_KEY.search(key):
            self.counts["secret"] += 1
            return REDACTED
        if (kl in _PATH_KEYS or _PATH_KEY_SUFFIX.search(key)) and not obj.lower().startswith(("http://", "https://")) and (
                "/" in obj or "\\" in obj):
            self.counts["path"] += 1
            return "[path]"
        if "@" in obj and _EMAIL.fullmatch(obj.strip()):
            return self.redact_text(obj)
        if kl in _USER_KEYS or (users_route and kl in ("name", "email")):
            pseudo = self._user(obj)
            if pseudo is not None:
                self.counts["username"] += 1
                return pseudo
            return obj
        if _TAG_KEY.search(key) and obj.strip():
            self.counts["title"] += 1
            return self._tag(obj)
        if kl in _TITLE_KEYS and obj.strip():
            self.counts["title"] += 1
            return self._title(obj)
        if _ID_KEY.search(key) and re.fullmatch(r"[A-Za-z0-9_\-]{6,64}", obj):
            self.counts["id"] += 1
            return self._id(obj)
        return self.redact_text(obj)

    def redact_xml(self, text: str) -> str:
        def title(m):
            inner = m.group(3)
            if not inner.strip():
                return m.group(0)
            self.counts["title"] += 1
            return f"<{m.group(1)}{m.group(2) or ''}>{self._title(inner.strip())}</{m.group(1)}>"
        return self.redact_text(_ISO_TEXT_TITLE.sub(title, text))


# ---- the final scan -------------------------------------------------------------------------------
_SCAN_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@(?!example\.invalid\b)[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")),
    ("ipv4", _IPV4),
    ("ipv6", _IPV6),
    ("bearer-or-basic", re.compile(r"(?i)\b(?:Bearer|Basic)\s+(?!\[REDACTED\])[A-Za-z0-9._~+/=\-]{6,}")),
    ("auth-token", re.compile(r"(?i)token\s*=\s*\"?(?!\[REDACTED\])[^\"\s,;]{4,}")),
    # A JSON literal (true/false/null) is a flag such as Jellyfin's "HasPassword": true, never a credential.
    ("credential-parameter", re.compile(r"(?i)(?:api[_\-]?key|access[_\-]?token|password|secret|x-api-key)"
                                         r"[\"']?\s*[=:]\s*[\"']?(?!\[REDACTED\]|\s|\"|(?:true|false|null)(?![^\s\"'&;,<>\]}]))"
                                         r"[^\s\"'&;,<>\]}]{3,}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("host-in-url", re.compile(r"(?i)\bhttps?://(?!host\.invalid\b|" + _NS_HOSTS + r")[^/\s\"'<>?#]+")),
    ("windows-path", re.compile(r"[A-Za-z]:\\{1,2}[^\s\"'<>|]+|\\\\{1,2}[\w.$\-]+\\{1,2}\w|\\\\{1,2}[?.]\\{1,2}\w")),
    ("unix-path", _UNIX_PATH),
    ("file-url-or-slash-path", re.compile(r"(?i:file:/{2,3})[^\s\"'<>]+|(?<![A-Za-z0-9])[A-Za-z]:/[^\s\"'<>|]+"
                                          r"|(?<![:/\w])//[\w.$\-]+/[^\s\"'<>]+")),
]
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-+/=])[A-Za-z0-9_\-+/=]{28,}(?![A-Za-z0-9_\-+/=])")


def scan_for_secrets(text: str, secrets: Sequence[str] = (), hosts: Sequence[str] = ()) -> List[str]:
    """Names (never matched text) of secret-like patterns still present in `text`."""
    hits: List[str] = []
    for secret in secrets:
        if secret and len(secret) >= 3 and secret in text:
            hits.append("literal-secret")
            break
    for h in hosts:
        if h and re.search(re.escape(h), text, flags=re.I):
            hits.append("configured-host")
            break
    for name, rx in _SCAN_PATTERNS:
        if rx.search(text):
            hits.append(name)
    for m in _LONG_TOKEN.finditer(text):
        tok = m.group(0)
        if is_synthetic_id(tok) or not (re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok)):
            continue
        if "/" in tok and any(re.fullmatch(r"[a-z]{3,}", seg) for seg in tok.split("/")):
            continue                        # a URL path such as /opds/download/42/epub, not base64
        hits.append("long-token")
        break
    return hits


# =====================================================================================================
# Strict field allowlist, applied BEFORE any redaction
# =====================================================================================================
# Each spec is derived from what the Home adapters READ (adapters/jellyfin.py `_parse_item`/`_resolve_user`,
# audiobookshelf.py `_resolve_user`/`_candidates`/`_visible`/`_Access.from_record`, komga.py `_book`/
# `_series_meta`, calibre_web.py `_book`) and from contract.MediaItem. Grammar:
#   True                a scalar (or a list of scalars) is kept; an object or a list of objects is dropped
#   {"key": spec, ...}  only these keys are kept; against a list, applied to each element (list shape kept)
# Everything else, however harmless it looks, is dropped. Not in any spec, on purpose: ExternalUrls,
# metadata.links, ProviderIds, Path, coverPath, Tags, Policy device/folder lists, LastLoginDate, Hostname,
# ServerName, DeviceName, e-mails, member labels, tokens, descriptions, every timestamp the adapters ignore.
_T = True
_DROP = object()

_JF_ITEM = {"Id": _T, "Type": _T, "Name": _T, "SeriesName": _T, "ParentIndexNumber": _T, "IndexNumber": _T,
            "ProductionYear": _T, "RunTimeTicks": _T, "ImageTags": {"Primary": _T},
            "UserData": {"UserId": _T, "ItemId": _T, "PlaybackPositionTicks": _T, "PlayedPercentage": _T}}
_KG_BOOK = {"id": _T, "seriesId": _T, "libraryId": _T, "deleted": _T, "name": _T, "seriesTitle": _T,
            "media": {"status": _T},
            "metadata": {"title": _T, "number": _T, "authors": {"name": _T, "role": _T}, "releaseDate": _T}}
_ABS_ITEM = {"id": _T, "libraryId": _T, "mediaType": _T, "isMissing": _T, "isInvalid": _T,
             "media": {"duration": _T, "tags": _T,
                       "metadata": {"explicit": _T, "title": _T, "authorName": _T, "seriesName": _T,
                                    "publishedYear": _T}}}

# (service, route) -> (request path template, spec)
ALLOWLIST: Dict[Tuple[str, str], Tuple[str, Any]] = {
    ("jellyfin", "users"): ("/Users", {"Name": _T, "Id": _T, "Policy": {"IsDisabled": _T}}),
    ("jellyfin", "resume"): ("/UserItems/Resume", {"Items": _JF_ITEM}),
    ("jellyfin", "latest"): ("/Items/Latest", _JF_ITEM),
    ("jellyfin", "items"): ("/Items", {"Items": _JF_ITEM}),
    ("audiobookshelf", "users"): ("/api/users", {"users": {"id": _T, "username": _T, "isActive": _T}}),
    ("audiobookshelf", "user"): ("/api/users/{id}", {
        "id": _T, "isActive": _T,
        "permissions": {"accessAllLibraries": _T, "accessAllTags": _T, "accessExplicitContent": _T,
                        "selectedTagsNotAccessible": _T},
        "librariesAccessible": _T, "itemTagsSelected": _T,
        "mediaProgress": {"userId": _T, "libraryItemId": _T, "episodeId": _T, "isFinished": _T,
                          "hideFromContinueListening": _T, "progress": _T, "currentTime": _T, "duration": _T,
                          "lastUpdate": _T}}),
    ("audiobookshelf", "item"): ("/api/items/{id}", _ABS_ITEM),
    # Search (AVR-383): the hit list and the fields the adapters read from each hit; creator/year come from
    # authorName/publishedYear (Audiobookshelf), metadata.authors/releaseDate (Komga), ProductionYear (Jellyfin).
    ("audiobookshelf", "libraries"): ("/api/libraries", {"libraries": {"id": _T, "mediaType": _T}}),
    ("audiobookshelf", "search"): ("/api/libraries/{id}/search", {"book": {"libraryItem": _ABS_ITEM}}),
    ("jellyfin", "search"): ("/Items?searchTerm=", {"Items": _JF_ITEM}),
    ("komga", "search"): ("/api/v1/books?search=", {"content": _KG_BOOK}),
    # Komga: shared regular-account view. Only the book and series fields a shared-view adapter shows or
    # checks (identity, library, deleted/ready state, title, number). No users, no restriction records.
    ("komga", "latest"): ("/api/v1/books/latest", {"content": _KG_BOOK}),
    ("komga", "book"): ("/api/v1/books/{id}", _KG_BOOK),
}
# Opt-in extras for --keep-provider-ids (IMDb/TMDB/TVDB, ISBN, ASIN). Off by default.
_JF_PROVIDERS = {"ProviderIds": {"Imdb": _T, "Tmdb": _T, "Tvdb": _T}}
PROVIDER_IDS: Dict[Tuple[str, str], Any] = {
    ("jellyfin", "resume"): {"Items": _JF_PROVIDERS},
    ("jellyfin", "latest"): _JF_PROVIDERS,
    ("jellyfin", "items"): {"Items": _JF_PROVIDERS},
    ("audiobookshelf", "item"): {"media": {"metadata": {"isbn": _T, "asin": _T}}},
    ("komga", "latest"): {"content": {"metadata": {"isbn": _T}}},
    ("komga", "book"): {"metadata": {"isbn": _T}},
    ("jellyfin", "search"): {"Items": _JF_PROVIDERS},
    ("audiobookshelf", "search"): {"book": {"libraryItem": {"media": {"metadata": {"isbn": _T, "asin": _T}}}}},
    ("komga", "search"): {"content": {"metadata": {"isbn": _T}}},
}
# Calibre-Web OPDS (Atom): the elements calibre_web._book reads. A <link> keeps only a RELATIVE cover or
# download href (the numeric book id the adapter extracts); absolute and external links are dropped.
XML_ALLOWLIST = ("entry/title", "entry/author/name", "entry/published (an ISO date only: the year is shown)",
                 "entry/link@href (relative /opds/cover|cover_240_240|thumb_cover/<n> and /opds/download/<n>/<fmt> only)")
XML_PROVIDER_IDS = ("entry/dc:identifier (ISBN and similar)",)
MAX_FEED_ENTRIES = 20
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9:.]{1,18}(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?")
_DC = "http://purl.org/dc/elements/1.1/"
_ATOM_NS = "http://www.w3.org/2005/Atom"


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _merge(a: Any, b: Any) -> Any:
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(a[k], v) if k in a else v
        return out
    return a


def allow_json(spec: Any, obj: Any) -> Any:
    """`obj` cut down to `spec`; _DROP if nothing of the expected shape is there."""
    if spec is True:
        if _scalar(obj):
            return obj
        if isinstance(obj, list) and all(_scalar(x) for x in obj):
            return list(obj)
        return _DROP
    if isinstance(obj, list):
        out = [allow_json(spec, x) for x in obj if isinstance(x, dict)]
        return [x for x in out if x is not _DROP]
    if isinstance(obj, dict) and isinstance(spec, dict):
        out = {}
        for key, sub in spec.items():
            if key in obj:
                kept = allow_json(sub, obj[key])
                if kept is not _DROP:
                    out[key] = kept
        return out
    return _DROP


def allow_xml(body: bytes, keep_provider_ids: bool = False) -> str:
    """Rebuild an OPDS feed holding only the allow-listed elements. Raises UpstreamMalformed."""
    root = _cw.parse_feed(body)               # refuses DOCTYPE/entities and non-Atom documents
    atom = "{" + _ATOM_NS + "}"
    feed = ET.Element(atom + "feed")
    for entry in root.findall(atom + "entry")[:MAX_FEED_ENTRIES]:
        out = ET.SubElement(feed, atom + "entry")
        title = entry.find(atom + "title")
        if title is not None:
            ET.SubElement(out, atom + "title").text = title.text or ""
        name = entry.find(f"{atom}author/{atom}name")
        if name is not None:
            ET.SubElement(ET.SubElement(out, atom + "author"), atom + "name").text = name.text or ""
        published = (entry.findtext(atom + "published") or "").strip()
        if _ISO_DATE.fullmatch(published):
            ET.SubElement(out, atom + "published").text = published      # a date, nothing else
        for link in entry.findall(atom + "link"):
            href = _cw._relative(link.get("href"))
            if href and (_cw._COVER_HREF.fullmatch(href) or _cw._DOWNLOAD_HREF.fullmatch(href)):
                ET.SubElement(out, atom + "link").set("href", href)
        if keep_provider_ids:
            for ident in entry.findall("{" + _DC + "}identifier"):
                ET.SubElement(out, "{" + _DC + "}identifier").text = ident.text or ""
    ET.register_namespace("", _ATOM_NS)
    ET.register_namespace("dc", _DC)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(feed, encoding="unicode") + "\n"


def spec_for(service: str, route: str, keep_provider_ids: bool = False) -> Optional[Any]:
    """The JSON spec for a route, or None if the route has no allowlist (then it is never written)."""
    entry = ALLOWLIST.get((service, route))
    if entry is None:
        return None
    spec = entry[1]
    if keep_provider_ids and (service, route) in PROVIDER_IDS:
        spec = _merge(spec, PROVIDER_IDS[(service, route)])
    return spec


def _paths(spec: Any, prefix: str = "") -> List[str]:
    if spec is True:
        return [prefix]
    out: List[str] = []
    for key, sub in spec.items():
        out += _paths(sub, f"{prefix}.{key}" if prefix else key)
    return out


def show_allowlist(services: Sequence[str], keep_provider_ids: bool, say) -> None:
    """Print, per service and route, the fields that will be kept. Makes no network call."""
    say("ALLOWLIST: only these fields are kept; every other field is dropped before any redaction.")
    say("No network call is made by this mode. Lists are kept element by element; paths are dotted.")
    say("Provider ids (IMDb/TMDB/TVDB, ISBN, ASIN): "
        + ("KEPT (--keep-provider-ids)" if keep_provider_ids else "dropped (default)") + ". External URLs are always dropped.")
    for name in services:
        say(f"[{name}]")
        if name == "komga":
            say("  shared regular-account view: GET /api/v2/users (admin-only) is never requested")
        for (svc, route), (path, _) in ALLOWLIST.items():
            if svc != name:
                continue
            say(f"  {route}  GET {path}")
            for f in _paths(spec_for(name, route, keep_provider_ids)):
                say(f"      {f}")
            extra = PROVIDER_IDS.get((name, route))
            if extra and not keep_provider_ids:
                say("      (only with --keep-provider-ids: " + ", ".join(_paths(extra)) + ")")
        if name == "calibre-web":
            say("  new  GET /opds/new   (and, with --search-term, search  GET /opds/search?query=)")
            for f in XML_ALLOWLIST:
                say(f"      {f}")
            if keep_provider_ids:
                for f in XML_PROVIDER_IDS:
                    say(f"      {f}")
            else:
                say("      (only with --keep-provider-ids: " + ", ".join(XML_PROVIDER_IDS) + ")")
        say("  images: no bytes are stored; only status, content type, size and a magic-byte check")


def apply_allowlist(cap: Capture, keep_provider_ids: bool = False) -> Optional[str]:
    """Replace cap.body by its allow-listed form. Returns an error name if the capture cannot be written."""
    if cap.body is None or cap.kind == "image":
        return None
    try:
        if cap.kind == "json":
            spec = spec_for(cap.service, cap.route, keep_provider_ids)
            if spec is None:
                return "no_allowlist"
            kept = allow_json(spec, json.loads(cap.body.decode("utf-8")))
            if kept is _DROP:
                return "unexpected_shape"
            cap.body = json.dumps(kept, ensure_ascii=False).encode("utf-8")
        elif cap.service == "calibre-web" and cap.route in ("new", "search"):
            cap.body = allow_xml(cap.body, keep_provider_ids).encode("utf-8")
        else:
            return "no_allowlist"
    except (ValueError, RecursionError, UpstreamMalformed):
        return "not_parseable"
    return None


# =====================================================================================================
# Output
# =====================================================================================================
def check_output_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise CaptureError("the output directory is inside a Git work tree; choose a directory outside the repository")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise CaptureError("the output directory exists and is not empty")
    return path


def default_output_dir() -> Path:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "avrana-capture" / stamp


def write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def build_outputs(caps: Sequence[Capture], red: Redactor, keep_provider_ids: bool = False
                  ) -> Tuple[Dict[str, bytes], List[Dict[str, Any]], List[str]]:
    """(files, manifest, refused). Nothing is written here. The allowlist runs first; a file that fails the
    final scan is refused."""
    allow_errors: Dict[int, str] = {}
    for i, cap in enumerate(caps):
        err = apply_allowlist(cap, keep_provider_ids)
        if err is not None:
            allow_errors[i] = err
            cap.body = None                    # nothing unfiltered is ever kept, learned from or written
    red.learn(caps)
    files: Dict[str, bytes] = {}
    manifest: List[Dict[str, Any]] = []
    refused: List[str] = []
    seq: Counter = Counter()
    for i, cap in enumerate(caps):
        seq[(cap.service, cap.route)] += 1
        n = seq[(cap.service, cap.route)]
        base = f"{cap.service}-{cap.route}-{n:02d}"
        entry: Dict[str, Any] = {"service": cap.service, "route": cap.route, "path_template": cap.path,
                                 "status": cap.status, "content_type": cap.ctype.split(";")[0].strip(),
                                 "error": cap.error or allow_errors.get(i), "file": None}
        before = Counter(red.counts)
        if cap.kind == "image":
            name, text = base + ".meta.json", json.dumps(
                {"status": cap.status, "content_type": entry["content_type"], **cap.summary,
                 "note": "image bytes are never stored"}, indent=2) + "\n"
        elif cap.body is not None and cap.kind == "json":
            data = red.redact_json(json.loads(cap.body.decode("utf-8")), users_route=cap.route == "users")
            name, text = base + ".json", red.redact_text(json.dumps(data, indent=2, ensure_ascii=False)) + "\n"
        elif cap.body is not None:
            name, text = base + ".xml", red.redact_xml(cap.body.decode("utf-8", "replace"))
        else:
            name, text = None, None
        if name is not None:
            hits = scan_for_secrets(text, red.secrets, red.hosts)
            if hits:
                refused.append(f"{name}: {', '.join(sorted(set(hits)))}")
                entry["refused"] = sorted(set(hits))
            else:
                files[name] = text.encode("utf-8")
                entry["file"] = name
        entry["redactions"] = dict(red.counts - before)
        manifest.append(entry)
    return files, manifest, refused


# =====================================================================================================
# Command line
# =====================================================================================================
def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="capture_upstreams.py",
        description="Owner-run read-only capture of the adapters' upstream responses. Base URLs and tokens are "
                    "read from AVRANA_CAPTURE_* environment variables, never from arguments.")
    p.add_argument("--out", type=Path, help="output directory (default: ~/avrana-capture/<UTC time>); must be outside any Git work tree")
    p.add_argument("--services", default="", help="comma list of: " + ", ".join(SERVICES) + " (default: every configured one)")
    p.add_argument("--members", default="", help="comma list of usernames whose own records may be requested "
                   "(Jellyfin, Audiobookshelf). Use test accounts where you can. Without it only user lists are fetched")
    p.add_argument("--own-username", default="", help="your own username; the only one NOT replaced (or AVRANA_CAPTURE_OWN_USERNAME)")
    p.add_argument("--max-items", type=int, default=2, help=f"items or books per member, at most {MAX_ITEMS} (default 2)")
    p.add_argument("--images", action="store_true", help="also request one cover per service; only status, type and size are kept")
    p.add_argument("--calibre-probe-id", type=int, help="also request /opds/thumb_cover/<id> for an id the viewer should not see (status only)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT * 2.5,
                   help=f"seconds per request, at most {int(MAX_TIMEOUT)} (default {DEFAULT_TIMEOUT * 2.5})")
    p.add_argument("--allow-insecure-http", action="store_true", help="allow a non-loopback http:// base URL")
    p.add_argument("--keep-provider-ids", action="store_true", help="keep IMDb/TMDB/TVDB, ISBN and ASIN identifiers "
                   "(dropped by default). Only for a specific validation that needs them; they can reveal real titles")
    p.add_argument("--show-allowlist", action="store_true", help="print the fields kept per service and route, "
                   "and exit; makes no network call and needs no credentials")
    p.add_argument("--search-term", default="", help="also capture each adapter's SEARCH route with this term "
                   "(only routes the adapters in this checkout make). Pick a harmless common word; it must be plain "
                   "letters, digits and spaces, is sent only as a query parameter, and never printed or written")
    p.add_argument("--dry-run", action="store_true", help="print the requests that would be made, and make none")
    return p.parse_args(argv)


def build_clients(env: Mapping[str, str], selected: Sequence[str], timeout: float, dry: bool,
                  allow_http: bool) -> Tuple[Dict[str, Client], List[str], List[str], List[str]]:
    """(clients, hosts to redact, secrets, skipped service names). Raises CaptureError on a half-set service."""
    clients: Dict[str, Client] = {}
    hosts: List[str] = []
    secrets: List[str] = []
    skipped: List[str] = []
    for name in selected:
        spec = SERVICES[name]
        url, vals = env.get(PREFIX + spec["url"], ""), [env.get(PREFIX + v, "") for v in spec["secrets"]]
        if not url and not any(vals):
            skipped.append(name)
            continue
        missing = ([PREFIX + spec["url"]] if not url else []) + [PREFIX + v for v, x in zip(spec["secrets"], vals) if not x]
        if missing:
            raise CaptureError(f"{name}: set {', '.join(missing)}")
        base = validate_base_url(url, allow_http)
        if name == "jellyfin":
            headers = {"Authorization": f'MediaBrowser Token="{vals[0]}"'}
        elif name == "audiobookshelf":
            headers = {"Authorization": f"Bearer {vals[0]}"}
        elif name == "komga":
            headers = {"X-API-Key": vals[0]}
        else:
            blob = base64.b64encode(f"{vals[0]}:{vals[1]}".encode("utf-8")).decode("ascii")
            headers = {"Authorization": f"Basic {blob}"}
            secrets += [blob, f"{vals[0]}:{vals[1]}"]
        secrets += vals
        host = urllib.parse.urlsplit(base).hostname or ""
        hosts.append(host)
        labels = host.split(".")
        if len(labels) > 2 and not _is_loopback(host):
            hosts.append(".".join(labels[-2:]))
        clients[name] = Client(name, base, headers, timeout, dry)
    return clients, hosts, secrets, skipped


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None,
         out=None, err=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    env = os.environ if env is None else env
    args = parse_args(argv)

    def say(msg: str) -> None:
        print(msg, file=out)

    if args.show_allowlist:
        names = [s.strip() for s in args.services.split(",") if s.strip()] or list(SERVICES)
        if any(s not in SERVICES for s in names):
            print("capture_upstreams: unknown service in --services", file=err)
            return 1
        show_allowlist(names, args.keep_provider_ids, say)
        return 0

    try:
        selected = [s.strip() for s in args.services.split(",") if s.strip()] or list(SERVICES)
        if any(s not in SERVICES for s in selected):
            raise CaptureError("unknown service in --services")
        members = [m.strip() for m in args.members.split(",") if m.strip()]
        if not 1 <= args.max_items <= MAX_ITEMS or len(members) > MAX_MEMBERS:
            raise CaptureError(f"--max-items must be 1..{MAX_ITEMS} and --members at most {MAX_MEMBERS} names")
        timeout = min(max(args.timeout, 0.5), MAX_TIMEOUT)
        term = None
        if args.search_term:
            term = " ".join(args.search_term.split())
            if not _SEARCH_TERM.fullmatch(args.search_term) or not _SEARCH_TERM.fullmatch(term):
                raise CaptureError("--search-term must be 2 to 40 plain letters, digits and spaces")
        own = args.own_username or env.get(PREFIX + "OWN_USERNAME", "")
        clients, hosts, secrets, skipped = build_clients(env, selected, timeout, args.dry_run, args.allow_insecure_http)
        if not clients:
            raise CaptureError("no service is configured: set the AVRANA_CAPTURE_* variables (see the README)")
        outdir = None if args.dry_run else check_output_dir(args.out or default_output_dir())
    except CaptureError as exc:
        print(f"capture_upstreams: {exc}", file=err)
        return 1

    opts = Options(members, args.max_items, args.images, args.calibre_probe_id, term)
    caps: List[Capture] = []
    if args.dry_run:
        say("DRY RUN: no request is made, nothing is written. Host names and credentials are never printed.")
    for name, client in clients.items():
        try:
            caps += CAPTURE[name](client, opts)
        except CaptureError as exc:
            print(f"capture_upstreams: {exc}", file=err)
            return 1
        if args.dry_run:
            for line in client.log:
                say(f"  [{name}] GET {_dry_display(line)}")
        else:
            for cap in [c for c in caps if c.service == name]:
                if cap.error == "not_in_adapters":
                    say(f"  [{name}] {cap.route}: {SKIPPED_NOTE}")
                    continue
                say(f"  [{name}] {cap.route}: " + (f"HTTP {cap.status}" if cap.status else "no response") + (f" ({cap.error})" if cap.error else ""))
    for name in skipped:
        say(f"  [{name}] skipped: not configured")
    if args.dry_run:
        if not members:
            say("  note: no --members given, so per-member requests are not planned; only user lists are fetched.")
        return 0

    red = Redactor(secrets, hosts, own, members)
    files, manifest, refused = build_outputs(caps, red, args.keep_provider_ids)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        outdir.chmod(stat.S_IRWXU)
    except OSError:
        pass
    for fname, data in files.items():
        write_private(outdir / fname, data)
    note = {"captured_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": "capture_upstreams.py", "readonly_get_only": True,
            "field_allowlist": True, "provider_ids_kept": bool(args.keep_provider_ids),
            "unverified": "Record the server versions by hand. Titles, ids, names and hosts are replaced; read every file before sharing.",
            "entries": manifest}
    write_private(outdir / "manifest.json", (json.dumps(note, indent=2) + "\n").encode("utf-8"))
    say(f"wrote {len(files)} file(s) and manifest.json to the output directory")
    if refused:
        for line in refused:
            print(f"REFUSED (secret-like content still present, not written): {line}", file=err)
        return 3
    return 0


def _dry_display(line: str) -> str:
    """Replace any id in a planned request line with <id>, so the printout never shows a value."""
    return re.sub(r"(?<=/)(?:[0-9a-f]{32}|[0-9a-f-]{36}|li_[a-z0-9]+|ID?[A-Za-z0-9]{8,32}|DUMMYID01|\d+)(?=/|\?|$)", "<id>", re.sub(
        r"(userId|ids)=[^&]+", r"\1=<id>", line))


if __name__ == "__main__":
    sys.exit(main())
