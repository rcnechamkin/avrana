#!/usr/bin/env python3
"""Degraded-library rehearsal against the fixture-only beta (AVR-388, offline half). Standard library only.

Run where both the app and the Jellyfin mock's control port are reachable, normally inside the container:

    docker exec beta python3 -B beta/rehearse_degraded.py

It takes the Jellyfin MOCK down (never a real service), then checks what MEDIA-2.0.md section 5 promises:
Jellyfin's Continue turns unavailable once its 30 s member cache lapses (Recently added keeps its cached items
for up to 120 s, by design: contract.cache_ttl), while Audiobookshelf, Komga and Calibre-Web stay ok and the
page still answers 200; then it brings the mock back and waits for Jellyfin to recover by itself, with no
restart. Prints a timeline and exits 0 only when degradation and recovery both happened.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from beta.smoke import mint  # noqa: E402

APP = os.environ.get("BETA_URL", "http://127.0.0.1:8096").rstrip("/")
MOCK = os.environ.get("JELLYFIN_MOCK_URL", "http://127.0.0.1:18096").rstrip("/")
GROUPS = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")
RECOVERY_LIMIT = float(os.environ.get("REHEARSAL_RECOVERY_SECONDS", "150"))


def sections(token: str):
    req = urllib.request.Request(APP + "/home.json", headers={"X-authentik-jwt": token})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, {(s["service"], s["section"]): s["state"] for s in json.load(r)["sections"]}


def mock_mode(mode: str) -> None:
    urllib.request.urlopen(urllib.request.Request(f"{MOCK}/__mock/mode/{mode}", method="POST", data=b""),
                           timeout=5).read()


def main() -> int:
    token = mint(os.environ["HOME_JWT_SECRET"], os.environ["HOME_JWT_ISSUER"], os.environ["HOME_JWT_AUDIENCE"],
                 groups=GROUPS)
    t0 = time.monotonic()
    log = lambda msg: print(f"{time.monotonic() - t0:6.1f}s  {msg}", flush=True)   # noqa: E731
    status, before = sections(token)
    log(f"before: {status} {sorted(before.items())}")
    if status != 200 or not before or any(v != "ok" for v in before.values()):
        log("FAIL: not every section was ok before the rehearsal")
        return 1
    others = {k for k in before if k[0] != "jellyfin"}

    mock_mode("down")
    log("Jellyfin mock -> down")
    degraded = None
    for _ in range(60):
        time.sleep(1)
        status, now = sections(token)
        if status == 200 and now.get(("jellyfin", "continue")) == "unavailable":
            degraded = now
            break
    if degraded is None:
        log("FAIL: Jellyfin's Continue never turned unavailable")
        mock_mode("ok")
        return 1
    log(f"degraded: {sorted(degraded.items())}")
    if any(degraded.get(k) != "ok" for k in others):
        log("FAIL: another library's section changed while only Jellyfin was down")
        mock_mode("ok")
        return 1
    log("PASS: Jellyfin's Continue is unavailable, every other library is ok, the page answers 200")

    mock_mode("ok")
    log("Jellyfin mock -> ok (no restart of the app)")
    deadline = time.monotonic() + RECOVERY_LIMIT
    while time.monotonic() < deadline:
        time.sleep(2)
        status, now = sections(token)
        if status == 200 and all(v == "ok" for v in now.values()) and set(now) == set(before):
            log(f"PASS: recovered by itself: {sorted(now.items())}")
            return 0
    log(f"FAIL: not recovered within {RECOVERY_LIMIT:.0f} s: {sorted(now.items())}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as exc:
        print(f"FAIL: could not reach the app or the mock control port ({exc.reason})", file=sys.stderr)
        sys.exit(1)
