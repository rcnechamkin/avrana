"""The member-scoped artwork gateway: the ONE place in the application that calls `fetch_artwork`.

`GET /art/<ref>` where `<ref>` is the contract's opaque artwork reference (for example
`jellyfin/primary/<id>` or `komga/book/<id>`). The first segment names the service; the adapter for
that service decides, for THIS member, whether the image may be shown (library group first, then the
item's visibility to that member) and returns bytes it already vetted: an allowed image type whose
magic number matches, at most MAX_IMAGE_BYTES. This module only

  * accepts a ref of the exact shape `service/word/id` made of `[A-Za-z0-9_-]` (no dots, percent
    escapes, slashes beyond two, absolute URLs or traversal can match),
  * picks the adapter by that service name and passes the VERIFIED principal and the ref, nothing else,
  * re-checks the answer (state OK, content type in an image allow-list that excludes SVG, size bound),
  * returns None for every other outcome so the caller serves the one standard 404.

Browser caching (owner decision 2026-10-27, replaces D11 for `/art` only): the browser may keep a cover but must
ask again before every use (`private, no-cache`). The answer to that question goes through the same checks as a
first fetch, and only a member allowed to see the image gets `304 Not Modified` for an `If-None-Match` that equals
the image's validator; everyone else gets the same 404. So a revoked group or a hidden item stops the cover on the
next display, as before; what changes is that an allowed member's phone no longer downloads the same bytes again.

Standard library only, no request object: it takes the path text, the principal and the If-None-Match value
(read by `identity.if_none_match_from_scope`, the one module that reads request input).
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional, Sequence

from ..contract import ARTWORK_TTL, ArtworkResult, SectionState
from ..principal import MemberPrincipal
from ..resilience import MAX_IMAGE_BYTES

# Never SVG, never HTML: only the raster types the adapters vouch for.
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
REF = re.compile(r"[a-z][a-z-]{1,23}/[A-Za-z0-9_-]{1,32}/[A-Za-z0-9_-]{1,64}")
PREFIX = "/art/"
# Private (never a shared or proxy cache), and revalidated before every use, so the permission check runs each time.
CACHE_CONTROL = "private, no-cache"
assert ARTWORK_TTL > 0


def ref_from_route(route: str) -> Optional[str]:
    """The artwork ref in a normalised route like `/art/komga/book/AbC123`, or None."""
    if not route.startswith(PREFIX):
        return None
    ref = route[len(PREFIX):]
    return ref if REF.fullmatch(ref) else None


def src_for(ref: object) -> Optional[str]:
    """The same-origin URL for an artwork ref from the contract's JSON, or None when it is not of the
    exact shape (the template then renders no image)."""
    return PREFIX + ref if isinstance(ref, str) and REF.fullmatch(ref) else None


def etag_for(data: bytes) -> str:
    """A strong validator for vetted image bytes: a digest of the bytes only, so it says nothing the image does not.
    Sent only with a 200 the member was allowed to receive."""
    return '"' + hashlib.sha256(data).hexdigest()[:32] + '"'


def not_modified(header: Optional[str], etag: str) -> bool:
    """True when `header` names `etag` (RFC 9110 13.1.2: weak comparison, so a `W/` prefix still matches) or is `*`.
    Call it only AFTER `fetch` returned a result for this member."""
    if not header:
        return False
    tags = [t.strip() for t in header.split(",")]
    return "*" in tags or etag in (t[2:] if t.startswith("W/") else t for t in tags)


def fetch(principal: Optional[MemberPrincipal], adapters: Sequence, ref: str) -> Optional[ArtworkResult]:
    """Blocking (run it in a thread pool). Returns a vetted OK result, or None for everything else."""
    if principal is None or not REF.fullmatch(ref):
        return None
    service = ref.split("/", 1)[0]
    adapter = next((a for a in adapters if a.service.value == service), None)
    if adapter is None:
        return None
    try:
        result = adapter.fetch_artwork(principal, ref)
    except Exception:                       # an adapter must not raise; if it does, it is a 404
        return None
    if not isinstance(result, ArtworkResult) or result.state is not SectionState.OK:
        return None
    ctype = (result.content_type or "").split(";")[0].strip().lower()
    if ctype not in IMAGE_TYPES or not isinstance(result.data, (bytes, bytearray)):
        return None
    if not 0 < len(result.data) <= MAX_IMAGE_BYTES:
        return None
    return ArtworkResult(SectionState.OK, ctype, bytes(result.data))
