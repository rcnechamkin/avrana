"""Installable Home (PWA-lite, AVR-364/386): the web app manifest and its icons.

Standard library only, no request object, no member data. What this provides, and what it does not:

  * `GET /manifest.webmanifest` (application/manifest+json): name and short name "Avrana", `display:
    standalone`, `start_url` and `scope` "/", Spire Ink background and theme, the brand's PNG icons.
  * `GET /icons/avrana-180.png`, `-192.png`, `-512.png` and `/icons/avrana-maskable-512.png` (image/png): the
    approved AVRANA Brand v1.0.0 icons (AVR-584), byte for byte from the brand package and checked against their
    recorded SHA-256 (brand.py, brand/SOURCES.json). iOS does not take an SVG `apple-touch-icon`, so these are PNG.
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
from typing import Optional, Tuple

from . import brand

MANIFEST_PATH = "/manifest.webmanifest"
MANIFEST_TYPE = "application/manifest+json"
# route -> the brand package file it serves (brand/SOURCES.json)
ICON_PATHS = {
    "/icons/avrana-180.png": "apple-touch-icon.png",
    "/icons/avrana-192.png": "icon-192.png",
    "/icons/avrana-512.png": "icon-512.png",
    "/icons/avrana-maskable-512.png": "icon-maskable-512.png",
}
APPLE_TOUCH_ICON = "/icons/avrana-180.png"
THEME = "#121214"   # Spire Ink, the brand package's theme and background colour
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
            # the brand's own maskable cut: the mark inside the 80% safe circle on a full Spire Ink square
            {"src": "/icons/avrana-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


@functools.lru_cache(maxsize=1)
def manifest_bytes() -> bytes:
    return json.dumps(manifest(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def asset_for(route: str) -> Optional[Tuple[bytes, str]]:
    """(body, content type) for an install or brand route (brand.py), or None for any other path."""
    if route == MANIFEST_PATH:
        return manifest_bytes(), MANIFEST_TYPE
    name = ICON_PATHS.get(route)
    if name is not None:
        return brand.file_bytes(name), "image/png"
    return brand.asset_for(route)
