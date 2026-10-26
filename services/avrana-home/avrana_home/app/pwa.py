"""The installed-app layer of Home's shell (MK-3, AVR-717; owner decision O1, 2026-10-25, DECISIONS.md).

Standard library only, no request object, no member data. Every byte here is the same for every viewer.

  * `GET /static/home.<hash>.js` (text/javascript): the one first-party page script (assets/home.js), loaded with
    `<script src defer>` by shell pages only. The path carries a short content hash, so the `no-store` default is
    still correct: HTML (always from the network) names the current file.
  * `GET /sw.js` (text/javascript): the service worker (assets/sw.js with the build, the offline path and the
    allow-list filled in). With `HOME_PWA_SW=off` it is a worker that removes itself instead.
  * `GET /offline` (text/html): a static page with nothing about any member, kept by the worker and shown only
    when a page navigation fails because the device has no connection.
  * `GET /signout`: clears this site's cache and storage on the device, then hands over to the outpost sign-out.

The worker stores exactly the paths in `precache_paths()`, which come from the routes that already exist
(brand.ROUTES, install.ICON_PATHS) plus the script and the offline page. Nothing else is stored.

The routes exist only where the shell can render (sections on, adapters built), like the manifest (main.py).
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import brand, install

ASSETS = Path(__file__).resolve().parent / "assets"
SW_PATH = "/sw.js"
OFFLINE_PATH = "/offline"
SIGNOUT_PATH = "/signout"
SCRIPT_PREFIX = "/static/home."
SCRIPT_SUFFIX = ".js"
JS_TYPE = "text/javascript; charset=utf-8"
HTML_TYPE = "text/html; charset=utf-8"
# `Clear-Site-Data` for sign-out. Never "cookies": on a shared registered domain that signs the member out of every
# other app too (owner decision D10).
CLEAR_SITE_DATA = '"cache", "storage"'

# What a killed worker does: no fetch handler, so every request goes straight to the network; it deletes the caches
# this app made, unregisters itself and is gone. `skipWaiting` so it replaces the old worker at once.
SELF_DESTRUCT = b"""/* Avrana Media service worker: switched off (HOME_PWA_SW=off). Removes itself and its caches. */
'use strict';
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key.indexOf('avrana-') === 0; })
      .map(function (key) { return caches.delete(key); }));
  }).then(function () { return self.registration.unregister(); }));
});
"""


def signout_headers(signout_url: str) -> Dict[str, str]:
    """Headers of the /signout 303. `signout_url` is the catalogue's fixed target (the outpost's sign-out path), never
    anything from the request."""
    return {"Location": signout_url, "Clear-Site-Data": CLEAR_SITE_DATA}


@functools.lru_cache(maxsize=1)
def script_bytes() -> bytes:
    return (ASSETS / "home.js").read_bytes()


@functools.lru_cache(maxsize=1)
def script_path() -> str:
    return SCRIPT_PREFIX + hashlib.sha256(script_bytes()).hexdigest()[:12] + SCRIPT_SUFFIX


def is_script_path(route: str) -> bool:
    return route == script_path()


def precache_types() -> Dict[str, str]:
    """path -> the one content type it may be stored with: the page script, the offline page, the brand files and
    the install icons. Taken from the code that serves them, never typed here."""
    out: Dict[str, str] = {script_path(): "text/javascript", OFFLINE_PATH: "text/html"}
    for route, (_name, ctype) in brand.ROUTES.items():
        out[route] = ctype
    for route in install.ICON_PATHS:
        out[route] = "image/png"
    return out


def precache_paths() -> Tuple[str, ...]:
    return tuple(precache_types())


def build_id(offline_html: bytes) -> str:
    """Short hash over everything the worker stores and the worker's own source: a changed file means a new cache
    name, so the old cache is deleted on activate and a stale file can never pair with new HTML."""
    h = hashlib.sha256()
    h.update((ASSETS / "sw.js").read_bytes())
    for path, ctype in sorted(precache_types().items()):
        h.update(path.encode("utf-8") + b"\0" + ctype.encode("ascii") + b"\0")
        if path == OFFLINE_PATH:
            h.update(offline_html)
        elif path == script_path():
            h.update(script_bytes())
        else:
            asset = install.asset_for(path)
            h.update(asset[0] if asset is not None else b"")
    return h.hexdigest()[:12]


def worker_bytes(offline_html: bytes, enabled: bool = True) -> bytes:
    """The body of /sw.js: the worker, or the self-destruct worker when the kill switch is on."""
    if not enabled:
        return SELF_DESTRUCT
    template = (ASSETS / "sw.js").read_text(encoding="utf-8")
    body = (template.replace("__BUILD__", build_id(offline_html))
            .replace("__OFFLINE__", OFFLINE_PATH)
            .replace("__ALLOW__", json.dumps(precache_types(), sort_keys=True, indent=2)))
    return body.encode("utf-8")


def asset_for(route: str) -> Optional[Tuple[bytes, str]]:
    """(body, content type) for the page script, or None. The worker and the offline page need app state and are
    answered by main.py."""
    if is_script_path(route):
        return script_bytes(), JS_TYPE
    return None
