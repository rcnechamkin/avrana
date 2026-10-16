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

Standard library only, no request object: it takes the path text and the principal.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

from ..contract import ARTWORK_TTL, ArtworkResult, SectionState
from ..principal import MemberPrincipal
from ..resilience import MAX_IMAGE_BYTES

# Never SVG, never HTML: only the raster types the adapters vouch for.
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
REF = re.compile(r"[a-z][a-z-]{1,23}/[A-Za-z0-9_-]{1,32}/[A-Za-z0-9_-]{1,64}")
PREFIX = "/art/"
# Private, and never reusable beyond the contract's artwork window (we choose none at all).
CACHE_CONTROL = "private, no-store"
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
