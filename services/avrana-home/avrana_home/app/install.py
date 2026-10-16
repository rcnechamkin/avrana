"""Installable Home (PWA-lite, AVR-364/386): the web app manifest and its monochrome icons.

Standard library only, no request object, no member data. What this provides, and what it does not:

  * `GET /manifest.webmanifest` (application/manifest+json): name and short name "Avrana", `display:
    standalone`, `start_url` and `scope` "/", black background and theme, three PNG icons.
  * `GET /icons/avrana-180.png`, `-192.png`, `-512.png` (image/png). The repository tracks no binary files
    (tests/ui/README.md), and iOS does not take an SVG `apple-touch-icon`, so the PNG bytes are GENERATED here
    from code: a white geometric "A" on black, 8-bit greyscale, deterministic, built once on first use.
  * No service worker and no script of any kind: there is no offline mode. Opened from the home screen
    without a connection, the page simply fails to load like any web page.

The routes are served ONLY when the Home shell can render (`HOME_SECTIONS` on and adapters built): with
sections off the paths are unknown and answer the portal's 404, exactly as today (portal parity). They do
not depend on the identity: a browser fetches the manifest without credentials unless the link says
`crossorigin="use-credentials"` (base.html does say so), and the bytes are the same for everyone.
"""
from __future__ import annotations

import functools
import json
import struct
import zlib
from typing import Optional, Tuple

MANIFEST_PATH = "/manifest.webmanifest"
MANIFEST_TYPE = "application/manifest+json"
ICON_SIZES = (180, 192, 512)
ICON_PATHS = {f"/icons/avrana-{n}.png": n for n in ICON_SIZES}
APPLE_TOUCH_ICON = "/icons/avrana-180.png"
THEME = "#000000"
# Caching: these responses keep the middleware's `Cache-Control: no-store` like every other response. They are
# a few kilobytes, and no new caching exception is needed for them.


def manifest() -> dict:
    return {
        "name": "Avrana",
        "short_name": "Avrana",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": THEME,
        "theme_color": THEME,
        "icons": [
            {"src": "/icons/avrana-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icons/avrana-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            # the mark sits well inside the maskable safe zone (the middle 80%) on a full black square
            {"src": "/icons/avrana-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


@functools.lru_cache(maxsize=1)
def manifest_bytes() -> bytes:
    return json.dumps(manifest(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _spans(n: int, y: int):
    """White pixel spans [x0, x1) on row y of an n x n icon: two slanted strokes and a crossbar."""
    v = (y + 0.5) / n
    top, foot, half = 0.22, 0.78, 0.055        # apex row, foot row, stroke half-width (fractions of n)
    apex, left, right = 0.5, 0.27, 0.73        # x of the apex and the two feet
    if not top <= v <= foot:
        return []
    t = (v - top) / (foot - top)
    lx, rx = apex + (left - apex) * t, apex + (right - apex) * t
    spans = [(lx - half, lx + half), (rx - half, rx + half)]
    if 0.58 <= v <= 0.64:                      # the crossbar joins the inner edges
        spans.append((lx, rx))
    out = []
    for a, b in spans:
        x0, x1 = max(0, int(round(a * n))), min(n, int(round(b * n)))
        if x1 > x0:
            out.append((x0, x1))
    return out


@functools.lru_cache(maxsize=len(ICON_SIZES))
def icon_png(n: int) -> bytes:
    if n not in ICON_SIZES:
        raise ValueError("unknown icon size")
    raw = bytearray()
    for y in range(n):
        row = bytearray(n)                     # black
        for x0, x1 in _spans(n, y):
            row[x0:x1] = b"\xff" * (x1 - x0)
        raw += b"\x00" + row                   # filter type 0 (none)
    ihdr = struct.pack(">IIBBBBB", n, n, 8, 0, 0, 0, 0)   # 8-bit greyscale, no interlace
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def asset_for(route: str) -> Optional[Tuple[bytes, str]]:
    """(body, content type) for an install route, or None for any other path."""
    if route == MANIFEST_PATH:
        return manifest_bytes(), MANIFEST_TYPE
    size = ICON_PATHS.get(route)
    if size is not None:
        return icon_png(size), "image/png"
    return None
