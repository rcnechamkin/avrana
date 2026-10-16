"""Calibre-Web read-only catalogue adapter: one section, "Recently added" (ebooks), through OPDS.

Status: proposed, not deployed. Standard library only. Proven only against HAND-WRITTEN fixtures that
are unverified against the deployed Calibre-Web (Automated); a recorded, read-only contract check is a
separate, owner-approved step that must happen before any real data is read (ADAPTER-CONTRACT.md, 13.6).

THIS IS A SHARED VIEW, NOT A MEMBER VIEW (OWNER INVARIANT, contract section 13.2). Calibre-Web's public
interface is OPDS over HTTP Basic, and the home holds one dedicated local viewer account, never a member's
password. Everything it reads is what that one account may see. The home cannot read Calibre-Web's user
table, so it cannot know or reproduce a member's own tag or custom-column restrictions. What it does:

  * The Authentik group `avrana-books` is checked before any upstream call (and before any cache read).
  * There is no per-member mapping: every member who holds the group is mapped to the same fixed,
    non-member "shared viewer" (`SHARED_VIEWER`). `resolve_user` never names a real Calibre-Web account.
  * The route table has no per-account feed (shelves, read books, hot, discover, downloads): the viewer
    account's own state never reaches a member. No read state, no progress, no download link is exposed.
  * The credential lives only inside the transport (a header, never a URL).
  * Hand-off and artwork never use an upstream URL: only the numeric book id is extracted from a
    RELATIVE feed link and validated, and the contract builder makes the hand-off URL.

If any member has a Calibre-Web restriction, the shared view would show that member more than Calibre-Web
does. That must be false before the adapter is enabled, or the owner must choose another design.

OPDS is Atom/XML from an upstream: the body is size-capped by the transport, documents with a DOCTYPE or
entity declaration are refused before parsing, and every parser failure is `UpstreamMalformed`.

Route, feed and field names are recalled from Calibre-Web's public behaviour and are UNVERIFIED.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, List, Optional, Tuple

from ..contract import (ArtworkRef, ArtworkResult, DEFAULT_LIMIT, Kind, MediaItem, SectionResult,
                        SectionState, Service, UpstreamUser, build_handoff_url, clean_text,
                        valid_upstream_id)
from ..principal import MemberPrincipal
from ..resilience import DEFAULT_TIMEOUT, ItemGone, RouteMissing, Transport, UpstreamMalformed
from ._base import GuardedAdapter, Route
from ._base import GuardedTransport as _Guard

SHARED_VIEWER = "shared"                      # the fixed, non-member upstream "user": a shared view, by design
_BOUND_ID = re.compile(SHARED_VIEWER)
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARTWORK_REF = re.compile(r"calibre-web/cover/([0-9]{1,9})")
_COVER_HREF = re.compile(r"/opds/(?:cover|thumb_cover)/([0-9]{1,9})")
_DOWNLOAD_HREF = re.compile(r"/opds/download/([0-9]{1,9})/[a-z0-9]{1,10}/?")
MAX_ENTRIES = 100                             # a feed with more entries than this is not a "new" feed
MAX_ELEMENTS = 5000                           # every element in the document, so deep or wide nesting is bounded
_FORBIDDEN_XML = re.compile(rb"<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST)", re.IGNORECASE)

ALLOWED_ROUTES = (
    Route("new", r"/opds/new", (), user_scoped=False, not_found=RouteMissing),
    Route("search", r"/opds/search", ("query",), user_scoped=False, not_found=RouteMissing),
    Route("cover", r"/opds/thumb_cover/[0-9]{1,9}", (), user_scoped=False, not_found=ItemGone),
)


class GuardedTransport(_Guard):
    """The Calibre-Web allow-list around an inner Transport."""

    def __init__(self, inner, bound_user_id: Optional[str] = None):
        super().__init__(inner, ALLOWED_ROUTES, _BOUND_ID, bound_user_id)

    def _clone(self, user_id):
        return GuardedTransport(self._inner, user_id)


def parse_feed(body: bytes) -> ET.Element:
    """The root of an Atom feed, or UpstreamMalformed. Never raises anything else."""
    # Only ASCII-compatible UTF-8 is accepted (an optional UTF-8 BOM, then "<"). UTF-16/32 bodies would hide a
    # DOCTYPE from the byte check below between NUL bytes (review of #39), so they are refused outright.
    text = body[3:] if body.startswith(b"\xef\xbb\xbf") else body
    if b"\x00" in text or not text.lstrip(b" \t\r\n").startswith(b"<"):
        raise UpstreamMalformed()
    if _FORBIDDEN_XML.search(text):
        raise UpstreamMalformed()             # entity expansion and external subsets are never parsed
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError, RecursionError, MemoryError):
        raise UpstreamMalformed() from None
    if sum(1 for _ in root.iter()) > MAX_ELEMENTS:
        raise UpstreamMalformed()
    if root.tag != _ATOM + "feed":
        raise UpstreamMalformed()             # for example an HTML login page
    return root


def _relative(href: Any) -> Optional[str]:
    """An absolute PATH on the same host only: never a URL, never protocol-relative."""
    if isinstance(href, str) and href.startswith("/") and not href.startswith("//") and "\\" not in href:
        return href
    return None


class CalibreWebAdapter(GuardedAdapter):
    service = Service.CALIBRE_WEB
    not_offered = frozenset({"continue", "item"})

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT, *,
                 owner_confirms_no_member_restrictions: bool = False, **kw):
        # A shared view (contract 13.2): every member sees what the viewer account sees, so Calibre-Web's own
        # per-member restrictions are NOT applied. The owner must opt in on purpose, and only while no member
        # has a Calibre-Web restriction.
        if owner_confirms_no_member_restrictions is not True:
            raise ValueError("Calibre-Web adapter is a shared view; the owner must confirm no member is restricted")
        super().__init__(GuardedTransport(transport), timeout, **kw)

    def __repr__(self) -> str:
        return "CalibreWebAdapter(<redacted>)"

    # -- what this adapter does not offer: no upstream call, nothing cached ----------------
    def continue_items(self, principal: MemberPrincipal, limit: int = DEFAULT_LIMIT) -> SectionResult:
        return self._not_offered(principal, "continue")      # per-member read state needs the member's own password

    def item(self, principal: MemberPrincipal, item_id: str) -> SectionResult:
        return self._not_offered(principal, "item")          # OPDS has no single-entry route (UNVERIFIED)

    # -- mapping: none. A shared view (OWNER INVARIANT, contract 13.2) ------------------------
    def _resolve_user(self, principal) -> UpstreamUser:
        return UpstreamUser(Service.CALIBRE_WEB, SHARED_VIEWER)

    # -- the one section -------------------------------------------------------------------
    @staticmethod
    def _book(entry: ET.Element) -> Tuple[Optional[MediaItem], str]:
        """(item, status): "ok" or "bad". Only a numeric id from a RELATIVE link is used."""
        ids = set()
        for link in entry.findall(_ATOM + "link"):
            href = _relative(link.get("href"))
            if href is None:
                continue
            m = _COVER_HREF.fullmatch(href) or _DOWNLOAD_HREF.fullmatch(href)
            if m is not None:
                ids.add(m.group(1))
        if len(ids) != 1:
            return None, "bad"                 # no usable id, or links that disagree
        book_id = next(iter(ids))
        if not valid_upstream_id(Service.CALIBRE_WEB, book_id):
            return None, "bad"
        title = clean_text(entry.findtext(_ATOM + "title")) or "Untitled"
        author = clean_text(entry.findtext(f"{_ATOM}author/{_ATOM}name"))
        return MediaItem(id=f"calibre-web:{book_id}", service=Service.CALIBRE_WEB, kind=Kind.EBOOK,
                         title=title, handoff_url=build_handoff_url(Service.CALIBRE_WEB, book_id),
                         subtitle=author, artwork=ArtworkRef(f"calibre-web/cover/{book_id}",
                                                             f"Cover of {title}")), "ok"

    def _recent_items(self, user: UpstreamUser, limit: int) -> SectionResult:
        guard = self._guard.bind(user.upstream_id)
        resp = self._get(guard, self._budget(), "/opds/new", None)
        entries: List[Any] = parse_feed(resp.body).findall(_ATOM + "entry")
        items = self._parse_many(entries, MAX_ENTRIES, self._book)
        return SectionResult.of(Service.CALIBRE_WEB, "recent", items[:limit])

    def _search(self, user: UpstreamUser, query: str, limit: int) -> SectionResult:
        """OPDS search of the SHARED viewer account's catalogue (contract 13.2 invariant), like recent. The term
        is a query parameter (`/opds/search?query=`, the OpenSearch form, UNVERIFIED), never part of the path."""
        resp = self._get(self._guard.bind(user.upstream_id), self._budget(), "/opds/search", {"query": query})
        entries: List[Any] = parse_feed(resp.body).findall(_ATOM + "entry")
        items = self._parse_many(entries, MAX_ENTRIES, self._book)
        return SectionResult.of(Service.CALIBRE_WEB, "search", items[:limit])

    def _fetch_artwork(self, user: UpstreamUser, ref: str) -> ArtworkResult:
        m = _ARTWORK_REF.fullmatch(ref)
        if m is None:
            return ArtworkResult(SectionState.EMPTY)
        # The viewer account's own rights decide whether this cover exists (404 = EMPTY); there is no
        # per-member visibility to check (contract 13.2).
        return self._fetch_image(self._guard.bind(user.upstream_id), self._budget(),
                                 f"/opds/thumb_cover/{m.group(1)}", None)
