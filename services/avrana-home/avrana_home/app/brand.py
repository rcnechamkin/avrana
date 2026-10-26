"""Approved AVRANA Brand v1.0.0 files for the Home shell (AVR-584): the Media L3 lockup, the favicon and the install
icons; and the shell's interface font, Plus Jakarta Sans (AVR-715, Concept K). Standard library only, no request object, no member data.

The files live in `brand/`, copied from the brand package by `tools/sync_brand_assets.py`; `brand/SOURCES.json`
records each one's package path (or, for the font, its npm source) and the SHA-256 of the original bytes. Binary files are stored as base64 text
(the repository tracks no binary files). Every file is checked against its recorded SHA-256 the first time it is
read, and a mismatch raises instead of serving altered artwork.

Routes (served only where the shell can render, like the manifest; see install.py and main.py):

  * `/brand/avrana-media-l3.svg` (image/svg+xml): the Media product lockup, cream, trimmed. Used by the masthead
    through `<img>`, so nothing in it can run; the file has no script, link or text element either.
  * `/brand/favicon.svg` (image/svg+xml): the 16 px micro cut, ink on light browser chrome, cream on dark.
  * `/brand/spire-a-24.svg` (image/svg+xml): the Spire-A 24 px micro cut, cream (AVR-716, Concept K). The glass Home
    button on shell pages other than Home, through `<img>` at exactly 24 px, the only size the cut is drawn for.
  * `/brand/plus-jakarta-sans-latin.woff2` and `/brand/plus-jakarta-sans-latin-ext.woff2` (font/woff2): Plus Jakarta
    Sans, variable weight 200 to 800, the Latin and Latin Extended subsets from `@fontsource-variable/plus-jakarta-sans`
    5.3.0, byte for byte the files Avrana Party ships. SIL OFL 1.1 (`OFL-PlusJakartaSans.txt`).
"""
from __future__ import annotations

import base64
import functools
import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple

BRAND_DIR = Path(__file__).resolve().parent / "brand"
LOCKUP = "/brand/avrana-media-l3.svg"
FAVICON = "/brand/favicon.svg"
HOME_MARK = "/brand/spire-a-24.svg"
FONT = "/brand/plus-jakarta-sans-latin.woff2"
FONT_EXT = "/brand/plus-jakarta-sans-latin-ext.woff2"
# route -> (file name in SOURCES.json, content type)
ROUTES = {
    LOCKUP: ("avrana-media-lockup-product_cream_trim.svg", "image/svg+xml"),
    FAVICON: ("favicon.svg", "image/svg+xml"),
    HOME_MARK: ("avrana-symbol-micro24_cream.svg", "image/svg+xml"),
    FONT: ("PlusJakartaSans-Latin-Variable.woff2", "font/woff2"),
    FONT_EXT: ("PlusJakartaSans-LatinExt-Variable.woff2", "font/woff2"),
}
# The lockup's own proportions (viewBox 1384.38 x 650), for the <img> width and height attributes.
LOCKUP_RATIO = 1384.38 / 650


@functools.lru_cache(maxsize=1)
def sources() -> dict:
    return json.loads((BRAND_DIR / "SOURCES.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def file_bytes(name: str) -> bytes:
    """The original package bytes of one recorded file, verified against SOURCES.json."""
    entry = sources()["files"][name]
    if entry["stored_as"] == "base64":
        data = base64.b64decode((BRAND_DIR / (name + ".b64")).read_bytes(), validate=False)
    else:
        data = (BRAND_DIR / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"brand file {name} does not match SOURCES.json")
    return data


def asset_for(route: str) -> Optional[Tuple[bytes, str]]:
    """(body, content type) for a brand route, or None for any other path."""
    hit = ROUTES.get(route)
    if hit is None:
        return None
    return file_bytes(hit[0]), hit[1]
