#!/usr/bin/env python3
"""AVR-503: catalogue and cache benchmark for Avrana Home. OFFLINE, SYNTHETIC data only.

    python -B services/avrana-home/tools/bench_catalog.py            # the full run recorded in the decision doc
    python -B services/avrana-home/tools/bench_catalog.py --quick    # one round, fewer scenarios (smoke)
    python -B services/avrana-home/tools/bench_catalog.py --json out.json

What it does. It builds the REAL application (`create_app`) with the REAL four adapters (Jellyfin,
Audiobookshelf, Komga, Calibre-Web) and the real `MemberCache`, but every adapter talks to an in-process
simulated upstream (`SimTransport`): no socket is opened, not even on loopback, and requests go through
Starlette's in-process `TestClient`. The simulated upstreams serve generated, synthetic catalogues of a chosen
size (100, 5,000 or 50,000 items per service) to 15 synthetic members with mixed groups, and impose a latency
profile per service: a fixed delay (20 ms, 200 ms), a hang until the caller's timeout (the 2 s request budget),
or "down" (connection refused at once).

Note: webtests/test_bench_cache_revocation.py imports this module's synthetic world; changing it can
break that web test.

What it measures, per scenario and phase: the SERVER-SIDE time of each request (the `duration_ms` of the app's
own access-log line), the number of upstream calls that request made (counted in the transport), and how many
sections came back unavailable (from the app's `section` log events). Phases: cold Home (empty cache), warm Home,
the New-this-week tabs (`/?new=<library>`), cold and warm thumbnails (`/art/<ref>`), search (`/search?q=`, which
is never cached), and Home again after 31 s and 131 s of simulated time (continue and recent TTLs expired).
A separate burst scenario sends all 15 members' cold Home at once.

Time: the request path runs on real time (real sleeps for the modelled latency, real budgets). Between phases the
bench subtracts the phase's own wall time from the adapters' clock, so each phase finds the cache as the previous
phase left it; TTL ageing is applied only where a phase says so (+31 s, +131 s).

What it is NOT: a measurement of real upstreams. The simulated search is a word index (O(hits)), so the catalogue
size changes the upstream's answer, not its cost; real Jellyfin/Komga/Audiobookshelf/Calibre-Web search cost at
these sizes is unmeasured. There is deliberately no "real" mode: running against live services needs the owner's
explicit approval and is out of scope for this tool.

Deterministic: generated data depends only on `--seed`; timings naturally vary run to run.
Not collected by the unit runners (this directory is not under `tests/` or `webtests/`, and the file is not
named `test_*.py`).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import platform
import random
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

BENCH_VERSION = "1"

SERVICES = ("jellyfin", "audiobookshelf", "komga", "calibre-web")
GROUP = {"jellyfin": "avrana-videos", "audiobookshelf": "avrana-audiobooks", "komga": "avrana-comics",
         "calibre-web": "avrana-books"}
# 15 synthetic members. Each tuple: the services whose group the member holds. Mixed on purpose: all four,
# pairs, singles, none (portal only), and one member in the videos group with NO Jellyfin account (not linked).
MEMBER_SERVICES = (
    ("jellyfin", "audiobookshelf", "komga", "calibre-web"),
    ("jellyfin", "audiobookshelf", "komga", "calibre-web"),
    ("jellyfin", "audiobookshelf"),
    ("jellyfin",),
    ("jellyfin",),
    ("jellyfin", "komga"),
    ("audiobookshelf",),
    ("audiobookshelf", "calibre-web"),
    ("calibre-web",),
    ("komga", "calibre-web"),
    ("jellyfin", "calibre-web"),
    ("jellyfin", "audiobookshelf", "komga", "calibre-web"),
    ("jellyfin", "audiobookshelf", "komga"),
    (),
    ("jellyfin",),                         # bench-m15: holds the group but has no Jellyfin account
)
UNLINKED = {"bench-m15": "jellyfin"}

ADJ = ("Amber", "Bright", "Cold", "Distant", "Silent", "Hidden", "Iron", "Golden", "Last", "Lost", "Northern",
       "Pale", "Quiet", "Red", "Salt", "Second", "Stone", "Sunken", "Velvet", "Wild", "Winter", "Young", "Hollow",
       "Glass")
NOUN = ("Harbour", "Garden", "Signal", "Archive", "Lantern", "River", "Orchard", "Engine", "Valley", "Mirror",
        "Bridge", "Station", "Island", "Letter", "Atlas", "Market", "Forest", "Tower", "Voyage", "Comet", "Meadow",
        "Circuit", "Canal", "Theatre")
# Search terms: broad (every title), common (one noun, ~1/24 of titles), rare (one item number), miss.
SEARCH_TERMS = ("synthetic", "harbour", "rare", "zzqxmiss")

CALIBRE_SEARCH_PAGE = 60          # ASSUMPTION: Calibre-Web pages OPDS search results (its "books per page")
ART_PER_MEMBER = 6                # thumbnails requested per member (the first ones on their Home)
IMG_BYTES = 48 * 1024             # synthetic thumbnail size; real 400 px posters are roughly 20-80 KiB (UNMEASURED)


# ---- clock -------------------------------------------------------------------------------------
class BenchClock:
    """Real monotonic time plus an offset the bench controls (TTL ageing, phase compression)."""

    def __init__(self):
        self.offset = 0.0
        self._lock = threading.Lock()

    def now(self) -> float:
        return time.monotonic() + self.offset

    def shift(self, seconds: float) -> None:
        with self._lock:
            self.offset += seconds


# ---- synthetic world ---------------------------------------------------------------------------
def _title(rng: random.Random, n: int) -> str:
    return f"Synthetic {rng.choice(ADJ)} {rng.choice(NOUN)} {n}"


def _fold_words(title: str):
    return set(title.casefold().split())


class WordIndex:
    """word -> item positions, newest first. Exact-word, case-folded; a term that is no word matches nothing."""

    def __init__(self, titles: List[str]):
        self._ix: Dict[str, List[int]] = {}
        for pos in range(len(titles) - 1, -1, -1):
            for w in _fold_words(titles[pos]):
                self._ix.setdefault(w, []).append(pos)

    def find(self, term: str):
        return self._ix.get(term.casefold().strip(), ())


def _png(tag: bytes) -> bytes:
    head = b"\x89PNG\r\n\x1a\n" + tag
    return head + b"\x00" * (IMG_BYTES - len(head))


def _jpeg(tag: bytes) -> bytes:
    head = b"\xff\xd8\xff\xe0" + tag
    return head + b"\x00" * (IMG_BYTES - len(head))


class Member:
    def __init__(self, index: int, services: Tuple[str, ...]):
        self.index = index
        self.username = f"bench-m{index:02d}"
        self.services = services
        self.groups = ("avrana-users",) + tuple(GROUP[s] for s in services)

    def headers(self, groups: Optional[Tuple[str, ...]] = None):
        return {"X-authentik-username": self.username,
                "X-authentik-groups": "|".join(self.groups if groups is None else groups),
                "X-authentik-name": f"Bench Member {self.index}",
                "X-authentik-email": f"{self.username}@example.test"}


def make_members() -> List[Member]:
    return [Member(i + 1, s) for i, s in enumerate(MEMBER_SERVICES)]


class JellyfinSim:
    LIBS = 3

    def __init__(self, rng: random.Random, size: int, members: List[Member]):
        self.titles = [_title(rng, n) for n in range(size)]
        self.ids = [f"{0xbe000000 + n:08x}" + "0" * 24 for n in range(size)]
        self.by_id = {iid: n for n, iid in enumerate(self.ids)}
        self.index = WordIndex(self.titles)
        self.items = [{"Id": self.ids[n], "Name": self.titles[n], "Type": "Movie", "ProductionYear": 1950 + n % 75,
                       "RunTimeTicks": 72_000_000_000, "ImageTags": {"Primary": f"t{n}"}, "UserData": {"Played": False}}
                      for n in range(size)]
        self.users, self.libs, self.resume = [], {}, {}
        for m in members:
            if "jellyfin" not in m.services or UNLINKED.get(m.username) == "jellyfin":
                continue
            uid = uuid.UUID(int=rng.getrandbits(128)).hex
            self.users.append({"Id": uid, "Name": m.username, "Policy": {"IsAdministrator": False, "IsDisabled": False}})
            libs = frozenset(rng.sample(range(self.LIBS), rng.randint(1, self.LIBS)))
            self.libs[uid] = libs
            visible = [n for n in rng.sample(range(size), min(size, 60)) if n % self.LIBS in libs][:8]
            self.resume[uid] = [dict(self.items[n], UserData={"PlaybackPositionTicks": 9_000_000_000 + n,
                                                              "PlayedPercentage": 12.5, "Played": False})
                                for n in visible]
        self.users.append({"Id": uuid.UUID(int=rng.getrandbits(128)).hex, "Name": "bench-admin",
                           "Policy": {"IsAdministrator": True, "IsDisabled": False}})
        self.image = _png(b"jellyfin")

    def _visible(self, uid, n):
        return n % self.LIBS in self.libs.get(uid, ())

    def handle(self, path, q):
        if path == "/Users":
            return 200, self.users
        uid = q.get("userId")
        if path == "/UserItems/Resume":
            if uid not in self.libs:
                return 404, {}
            return 200, {"Items": self.resume[uid][:int(q.get("limit", "12"))], "TotalRecordCount": 0}
        if path == "/Shows/NextUp":           # Up next, on All's Continue since 2026-10-28: nothing in this world
            if uid not in self.libs:
                return 404, {}
            return 200, {"Items": [], "TotalRecordCount": 0}
        if path == "/Items/Latest":
            if uid not in self.libs:
                return 404, {}
            out, limit = [], int(q.get("limit", "12"))
            for n in range(len(self.items) - 1, -1, -1):
                if self._visible(uid, n):
                    out.append(self.items[n])
                    if len(out) >= limit:
                        break
            return 200, out
        if path == "/Items":
            n = self.by_id.get(q.get("ids", ""))
            found = [self.items[n]] if n is not None and self._visible(uid, n) else []
            return 200, {"Items": found, "TotalRecordCount": len(found)}
        m = re.fullmatch(r"/Users/([0-9a-f]{32})/Items", path)
        if m:
            uid, limit = m.group(1), int(q.get("limit", "50"))
            if uid not in self.libs:
                return 404, {}
            hits = [self.items[n] for n in self.index.find(q.get("searchTerm", "")) if self._visible(uid, n)]
            return 200, {"Items": hits[:limit], "TotalRecordCount": len(hits)}
        m = re.fullmatch(r"/Items/([0-9a-f]{32})/Images/Primary", path)
        if m and m.group(1) in self.by_id:
            return 200, ("image/png", self.image)
        return 404, {}


class AudiobookshelfSim:
    LIBS = ("lib_one", "lib_two")

    def __init__(self, rng: random.Random, size: int, members: List[Member]):
        self.titles = [_title(rng, n) for n in range(size)]
        self.index = WordIndex(self.titles)
        self.items = {}
        self.order = []
        for n in range(size):
            iid = f"li_bk{n:07d}"
            self.order.append(iid)
            self.items[iid] = {"id": iid, "libraryId": self.LIBS[n % 2], "mediaType": "book", "isMissing": False,
                               "isInvalid": False,
                               "media": {"metadata": {"title": self.titles[n], "authorName": "Synthetic Author",
                                                      "seriesName": None, "explicit": False},
                                         "tags": [], "duration": 36000.0, "coverPath": f"/metadata/{iid}.jpg"}}
        self.users, self.records = [], {}
        for m in members:
            if "audiobookshelf" not in m.services:
                continue
            uid = str(uuid.UUID(int=rng.getrandbits(128)))
            everything = rng.random() < 0.5
            libs = list(self.LIBS) if everything else ["lib_one"]
            progress = []
            for k, n in enumerate(rng.sample(range(size), min(size, 8))):
                progress.append({"id": f"mp_{k}", "userId": uid, "libraryItemId": self.order[n], "episodeId": None,
                                 "mediaItemType": "book", "duration": 36000.0, "progress": 0.1 + k / 20,
                                 "currentTime": 3600.0 + k, "isFinished": False, "hideFromContinueListening": False,
                                 "lastUpdate": 1_700_000_000_000 + k})
            self.users.append({"id": uid, "username": m.username, "type": "user", "isActive": True})
            self.records[uid] = {"id": uid, "username": m.username, "type": "user", "isActive": True,
                                 "permissions": {"accessAllLibraries": everything, "accessAllTags": True,
                                                 "accessExplicitContent": False, "selectedTagsNotAccessible": False},
                                 "librariesAccessible": [] if everything else libs, "itemTagsSelected": [],
                                 "mediaProgress": progress}
        self.image = _jpeg(b"abs")

    def handle(self, path, q):
        if path == "/api/users":
            return 200, {"users": self.users}
        if path.startswith("/api/users/"):
            rec = self.records.get(path[len("/api/users/"):])
            return (200, rec) if rec else (404, {})
        if path == "/api/libraries":
            return 200, {"libraries": [{"id": "lib_one", "mediaType": "book"}, {"id": "lib_two", "mediaType": "book"},
                                       {"id": "lib_pod", "mediaType": "podcast"}]}
        m = re.fullmatch(r"/api/libraries/([a-z0-9_]+)/search", path)
        if m:
            lib, limit = m.group(1), int(q.get("limit", "12"))
            hits = []
            for n in self.index.find(q.get("q", "")):
                it = self.items[self.order[n]]
                if it["libraryId"] == lib:
                    hits.append({"libraryItem": it, "matchKey": "title", "matchText": it["media"]["metadata"]["title"]})
                    if len(hits) >= limit:
                        break
            return 200, {"book": hits, "tags": [], "authors": [], "series": [], "narrators": [], "genres": []}
        m = re.fullmatch(r"/api/libraries/([a-z0-9_]+)/items", path)
        if m:                                  # newest first: the highest numbers were added last
            lib, limit = m.group(1), int(q.get("limit", "12"))
            listed = [self.items[iid] for iid in reversed(self.order) if self.items[iid]["libraryId"] == lib][:limit]
            return 200, {"results": [dict(it, addedAt=1_700_000_000_000 + int(it["id"][5:])) for it in listed],
                         "total": len(listed), "limit": limit, "page": 0}
        if re.fullmatch(r"/api/libraries/([a-z0-9_]+)/filterdata", path):
            return 200, {"genres": [], "authors": [], "tags": [], "series": [], "narrators": []}
        m = re.fullmatch(r"/api/items/(li_[a-z0-9]+)(/cover)?", path)
        if m and m.group(1) in self.items:
            return (200, ("image/jpeg", self.image)) if m.group(2) else (200, self.items[m.group(1)])
        return 404, {}


def _iso_days_ago(n: int, suffix: str) -> str:
    """Now minus `n` minutes as an ISO date, so thousands of books stay inside Recently added's 60-day window."""
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - n * 60)) + suffix


class KomgaSim:
    def __init__(self, rng: random.Random, size: int, members: List[Member]):
        self.titles = [_title(rng, n) for n in range(size)]
        self.index = WordIndex(self.titles)
        self.ids = [f"BK{n:08d}" for n in range(size)]
        self.by_id = {b: n for n, b in enumerate(self.ids)}
        self.books = [{"id": self.ids[n], "seriesId": f"SR{n // 10:08d}", "seriesTitle": f"Synthetic Series {n // 10}",
                       "libraryId": "LIBCOMICS1", "name": self.titles[n], "number": n % 10 + 1, "deleted": False,
                       "media": {"status": "READY", "mediaType": "application/zip", "pagesCount": 24},
                       "created": _iso_days_ago(size - n, "T00:00:00Z"),        # newest last, within Recently added's window
                       "metadata": {"title": self.titles[n], "number": str(n % 10 + 1), "tags": [],
                                    "releaseDate": _iso_days_ago(size - n, "")}}
                      for n in range(size)]
        self.image = _png(b"komga")

    def handle(self, path, q):
        size = int(q.get("size", "20"))
        if path == "/api/v1/books" and "search" not in q:       # Recently added and New releases
            content = self.books[-size:][::-1]
            return 200, {"content": content, "number": 0, "size": size, "totalElements": len(self.books)}
        if path == "/api/v1/books":
            found = self.index.find(q.get("search", ""))
            return 200, {"content": [self.books[n] for n in found[:size]], "number": 0, "totalElements": len(found)}
        m = re.fullmatch(r"/api/v1/books/([A-Za-z0-9]+)(/thumbnail)?", path)
        if m and m.group(1) in self.by_id:
            return (200, ("image/png", self.image)) if m.group(2) else (200, self.books[self.by_id[m.group(1)]])
        return 404, {}


class CalibreWebSim:
    HEAD = ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
            '<id>urn:uuid:bench</id><title>Bench</title><updated>2026-01-01T00:00:00+00:00</updated>')

    def __init__(self, rng: random.Random, size: int, members: List[Member]):
        self.titles = [_title(rng, n) for n in range(size)]
        self.index = WordIndex(self.titles)
        self.size = size
        self.image = _png(b"calibre")

    def _entry(self, n: int) -> str:
        bid = n + 1
        return (f"<entry><title>{self.titles[n]}</title><id>urn:uuid:bench-{bid}</id>"
                f"<updated>2026-01-01T00:00:00+00:00</updated><author><name>Synthetic Author</name></author>"
                f'<link rel="http://opds-spec.org/image" href="/opds/cover/{bid}" type="image/jpeg"/>'
                f'<link rel="http://opds-spec.org/acquisition" href="/opds/download/{bid}/epub/" '
                f'type="application/epub+zip"/></entry>')

    def handle(self, path, q):
        if path == "/opds/new":
            body = "".join(self._entry(n) for n in range(self.size - 1, max(-1, self.size - 31), -1))
            return 200, ("application/atom+xml", (self.HEAD + body + "</feed>").encode("utf-8"))
        if path == "/opds/search":
            hits = self.index.find((q or {}).get("query", ""))[:CALIBRE_SEARCH_PAGE]
            body = "".join(self._entry(n) for n in hits)
            return 200, ("application/atom+xml", (self.HEAD + body + "</feed>").encode("utf-8"))
        m = re.fullmatch(r"/opds/cover_240_240/([0-9]+)", path)
        if m and 1 <= int(m.group(1)) <= self.size:
            return 200, ("image/png", self.image)
        return 404, b""


class World:
    def __init__(self, seed: int, size: int):
        self.seed, self.size = seed, size
        self.members = make_members()
        rng = random.Random(f"{seed}:{size}")
        self.sims = {"jellyfin": JellyfinSim(random.Random(rng.random()), size, self.members),
                     "audiobookshelf": AudiobookshelfSim(random.Random(rng.random()), size, self.members),
                     "komga": KomgaSim(random.Random(rng.random()), size, self.members),
                     "calibre-web": CalibreWebSim(random.Random(rng.random()), size, self.members)}
        # the "rare" term: one item number that exists in every catalogue
        self.rare = str(size // 2)

    def term(self, name: str) -> str:
        return self.rare if name == "rare" else name


# ---- transport -----------------------------------------------------------------------------------
class Counter:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = {s: 0 for s in SERVICES}
        self.compute_max = 0.0

    def add(self, service: str) -> None:
        with self._lock:
            self.calls[service] += 1

    def compute(self, seconds: float) -> None:
        with self._lock:
            self.compute_max = max(self.compute_max, seconds)

    def take(self) -> Dict[str, int]:
        with self._lock:
            out = dict(self.calls)
            self.calls = {s: 0 for s in SERVICES}
            return out


class SimTransport:
    """The Transport protocol over a simulated upstream. Modes: ("ok", latency_s) | ("hang", None) | ("down", None).
    "hang" waits for the caller's own timeout and raises UpstreamTimeout, as a socket read would. No socket."""

    def __init__(self, service: str, sim, profile: Dict[str, Tuple[str, Optional[float]]], counter: Counter):
        self.service, self.sim, self.profile, self.counter = service, sim, profile, counter

    def request(self, method, path, query, timeout, max_bytes):
        from avrana_home.resilience import TransportResponse, UpstreamTimeout, UpstreamUnreachable, classify_status
        self.counter.add(self.service)
        mode, latency = self.profile[self.service]
        if mode == "down":
            raise UpstreamUnreachable()
        if mode == "hang":
            time.sleep(timeout)
            raise UpstreamTimeout()
        started = time.perf_counter()
        status, payload = self.sim.handle(path, dict(query or {}))
        if isinstance(payload, tuple):
            ctype, body = payload
        else:
            ctype, body = "application/json", json.dumps(payload).encode("utf-8")
        spent = time.perf_counter() - started
        self.counter.compute(spent)
        wait = latency - spent
        if wait > timeout:
            time.sleep(timeout)
            raise UpstreamTimeout()
        if wait > 0:
            time.sleep(wait)
        if status >= 400:
            raise classify_status(status)
        return TransportResponse(status, body, ctype)


# ---- log capture -----------------------------------------------------------------------------------
class Capture(logging.Handler):
    """Collects the app's own structured events (fields only, never free text)."""

    def __init__(self):
        super().__init__(logging.INFO)
        self._lock = threading.Lock()
        self.events: List[Tuple[str, dict]] = []

    def emit(self, record):
        from avrana_home.app.logsafe import ATTR
        fields = getattr(record, ATTR, None)
        with self._lock:
            self.events.append((record.getMessage() if fields is None else record.msg, dict(fields or {})))

    def take(self) -> List[Tuple[str, dict]]:
        with self._lock:
            out, self.events = self.events, []
            return out


def install_capture() -> Capture:
    cap = Capture()
    root = logging.getLogger("avrana_home")
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(cap)
    root.setLevel(logging.INFO)
    root.propagate = False
    for name in ("avrana_home.access", "avrana_home.app"):
        logging.getLogger(name).setLevel(logging.INFO)
    return cap


# ---- the application under test ------------------------------------------------------------------
class Bench:
    def __init__(self, world: World, profile: Dict[str, Tuple[str, Optional[float]]], cap: Capture):
        from fastapi.testclient import TestClient
        from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
        from avrana_home.adapters.calibre_web import CalibreWebAdapter
        from avrana_home.adapters.jellyfin import JellyfinAdapter
        from avrana_home.adapters.komga import KomgaAdapter
        from avrana_home.app.main import create_app
        from avrana_home.app.settings import Settings
        from avrana_home.cache import MemberCache

        self.world, self.cap = world, cap
        self.clock = BenchClock()
        self.counter = Counter()
        # As build_adapters does: ONE shared MemberCache, every adapter on it, timeout 2.0, section limit 12.
        self.cache = MemberCache(self.clock)
        t = {s: SimTransport(s, world.sims[s], profile, self.counter) for s in SERVICES}
        kw = dict(timeout=2.0, cache=self.cache, clock=self.clock)
        self.adapters = [JellyfinAdapter(t["jellyfin"], **kw), AudiobookshelfAdapter(t["audiobookshelf"], **kw),
                         KomgaAdapter(t["komga"], owner_confirms_no_member_restrictions=True, **kw),
                         CalibreWebAdapter(t["calibre-web"], owner_confirms_no_member_restrictions=True, **kw)]
        for a in self.adapters:
            a.cache = self.cache
        settings = Settings(home_sections=True, timeout=2.0, section_limit=12)
        self.app = create_app(settings, adapters=self.adapters)
        self.client = TestClient(self.app, base_url="http://portal.test", follow_redirects=False,
                                 raise_server_exceptions=False)
        self.client.__enter__()
        cap.take()

    def close(self):
        self.client.__exit__(None, None, None)
        self.cache.close()

    def get(self, target: str, headers: dict, client=None):
        """(status, body text, server ms, upstream calls, unavailable sections). The reasons of the unavailable
        sections are kept in `self.last_reasons`."""
        self.counter.take()
        resp = (client or self.client).get(target, headers=headers)
        calls = sum(self.counter.take().values())
        server_ms, unavailable, self.last_reasons = None, 0, {}
        for event, fields in self.cap.take():
            if event == "request":
                server_ms = fields.get("duration_ms")
            elif event == "section" and fields.get("state") == "unavailable":
                unavailable += 1
                why = fields.get("reason") or "?"
                self.last_reasons[why] = self.last_reasons.get(why, 0) + 1
        return resp.status_code, resp.text, server_ms, calls, unavailable


ART = re.compile(r'src="(/art/[a-z-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+)"')


def pct(values: List[float], p: float) -> float:
    """Nearest-rank percentile."""
    s = sorted(values)
    if not s:
        return float("nan")
    k = max(1, math.ceil(p / 100.0 * len(s)))
    return s[k - 1]


class Results:
    def __init__(self):
        self.rows: Dict[Tuple[str, str], dict] = {}

    def add(self, scenario: str, phase: str, server_ms, calls: int, unavailable: int, status: int, reasons=None):
        r = self.rows.setdefault((scenario, phase), {"ms": [], "calls": [], "unavailable": 0, "errors": 0,
                                                     "reasons": {}})
        for why, n in (reasons or {}).items():
            r["reasons"][why] = r["reasons"].get(why, 0) + n
        if server_ms is not None:
            r["ms"].append(float(server_ms))
        r["calls"].append(calls)
        r["unavailable"] += unavailable
        r["errors"] += status >= 500

    def table(self) -> str:
        lines = ["| scenario | phase | n | p50 ms | p95 ms | upstream calls / req (mean, max) | unavailable sections "
                 "(reasons) | 5xx |",
                 "|---|---|---:|---:|---:|---:|---:|---:|"]
        for (scenario, phase), r in self.rows.items():
            n = len(r["calls"])
            mean = sum(r["calls"]) / n if n else 0
            lines.append(f"| {scenario} | {phase} | {n} | {pct(r['ms'], 50):.0f} | {pct(r['ms'], 95):.0f} | "
                         f"{mean:.1f}, {max(r['calls']) if n else 0:.0f} | {r['unavailable']}{self._why(r)} | "
                         f"{r['errors']} |")
        return "\n".join(lines)

    @staticmethod
    def _why(r) -> str:
        reasons = r.get("reasons") or {}
        return (" (" + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items())) + ")") if reasons else ""

    def as_json(self) -> list:
        return [{"scenario": s, "phase": p, "n": len(r["calls"]), "p50_ms": pct(r["ms"], 50),
                 "p95_ms": pct(r["ms"], 95), "calls_mean": sum(r["calls"]) / max(1, len(r["calls"])),
                 "calls_max": max(r["calls"] or [0]), "unavailable_sections": r["unavailable"], "reasons": r.get("reasons", {}),
                 "http_5xx": r["errors"]}
                for (s, p), r in self.rows.items()]


def run_sequential(name: str, world: World, profile, cap: Capture, results: Results, rounds: int,
                   search: bool = True, notes: Optional[dict] = None) -> None:
    for _round in range(rounds):
        b = Bench(world, profile, cap)
        try:
            art: Dict[str, List[str]] = {}

            def phase(label, fn):
                started = time.monotonic()
                for m in world.members:
                    for target in fn(m):
                        status, text, ms, calls, unavailable = b.get(target, m.headers())
                        results.add(name, label, ms, calls, unavailable, status, b.last_reasons)
                        if label == "home cold":
                            art[m.username] = ART.findall(text)[:ART_PER_MEMBER]
                b.clock.shift(-(time.monotonic() - started))     # the phase took no simulated time

            phase("home cold", lambda m: ["/"])
            phase("home warm", lambda m: ["/"])
            phase("new tabs (warm)", lambda m: [f"/?new={s}" for s in m.services
                                                if s in ("jellyfin", "komga", "calibre-web")])
            phase("art cold", lambda m: art.get(m.username, []))
            phase("art warm", lambda m: art.get(m.username, []))
            if search:
                phase("search (never cached)", lambda m: [f"/search?q={world.term(t)}" for t in SEARCH_TERMS])
            b.clock.shift(31)
            phase("home +31 s (continue expired)", lambda m: ["/"])
            b.clock.shift(100)
            phase("home +131 s (all sections, mapping expired)", lambda m: ["/"])
            if notes is not None:
                notes.setdefault(name, []).append({"cache_entries": len(b.cache), "cache_bytes": b.cache.total_bytes(),
                                                   "fake_compute_max_ms": round(b.counter.compute_max * 1000, 2)})
        finally:
            b.close()


def run_burst(name: str, world: World, profile, cap: Capture, results: Results, rounds: int,
              notes: Optional[dict] = None) -> None:
    """All 15 members open a cold Home at the same moment (one client per member, one shared app)."""
    from fastapi.testclient import TestClient
    for _round in range(rounds):
        b = Bench(world, profile, cap)
        try:
            barrier = threading.Barrier(len(world.members))
            statuses: List[int] = []
            lock = threading.Lock()

            def one(m):
                client = TestClient(b.app, base_url="http://portal.test", follow_redirects=False,
                                    raise_server_exceptions=False)
                barrier.wait()
                status = client.get("/", headers=m.headers()).status_code
                with lock:
                    statuses.append(status)
            b.counter.take()
            threads = [threading.Thread(target=one, args=(m,)) for m in world.members]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            calls = sum(b.counter.take().values())
            reasons: Dict[str, int] = {}
            ms: List[float] = []
            for event, fields in cap.take():
                if event == "request":
                    ms.append(float(fields.get("duration_ms")))
                elif event == "section" and fields.get("state") == "unavailable":
                    reasons[fields.get("reason") or "?"] = reasons.get(fields.get("reason") or "?", 0) + 1
            r = results.rows.setdefault((name, "home cold, 15 at once"),
                                        {"ms": [], "calls": [], "unavailable": 0, "errors": 0, "reasons": {}})
            for why, n in reasons.items():
                r["reasons"][why] = r["reasons"].get(why, 0) + n
            r["ms"].extend(ms)
            r["calls"].extend([calls / len(world.members)] * len(world.members))
            r["unavailable"] += sum(reasons.values())
            r["errors"] += sum(1 for s in statuses if s >= 500)
            if notes is not None:
                notes.setdefault(name, []).append({"unavailable_reasons": reasons})
        finally:
            b.close()


def fast(ms):
    return {s: ("ok", ms / 1000.0) for s in SERVICES}


def scenarios(quick: bool, burst_only: bool = False):
    if burst_only:                       # F2 (AVR-503): the concurrency cap, before and after a change
        return [("burst 20 ms, 5,000 items", 5000, fast(20), "burst"),
                ("burst 200 ms, 5,000 items", 5000, fast(200), "burst"),
                ("burst, Jellyfin hangs (2 s timeout), others 20 ms", 5000,
                 dict(fast(20), jellyfin=("hang", None)), "burst")]
    out = [("normal 20 ms, 100 items", 100, fast(20), "seq"),
           ("normal 20 ms, 5,000 items", 5000, fast(20), "seq"),
           ("normal 20 ms, 50,000 items", 50000, fast(20), "seq")]
    if quick:
        return out[:1] + [("burst 20 ms, 5,000 items", 5000, fast(20), "burst")]
    out += [("slow 100 ms, 5,000 items", 5000, fast(100), "seq"),
            ("slow 200 ms, 5,000 items", 5000, fast(200), "seq"),
            ("Jellyfin hangs (2 s timeout), others 20 ms", 5000, dict(fast(20), jellyfin=("hang", None)), "seq"),
            ("Audiobookshelf down, others 20 ms", 5000, dict(fast(20), audiobookshelf=("down", None)), "seq"),
            ("all upstreams down", 5000, {s: ("down", None) for s in SERVICES}, "seq"),
            ("burst 20 ms, 5,000 items", 5000, fast(20), "burst"),
            ("burst 200 ms, 5,000 items", 5000, fast(200), "burst")]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=503)
    ap.add_argument("--rounds", type=int, default=3, help="fresh app (cold cache) per round; 15 members each")
    ap.add_argument("--quick", action="store_true", help="one round, three scenarios (smoke)")
    ap.add_argument("--json", help="also write the raw summary as JSON to this path")
    ap.add_argument("--burst-only", action="store_true", help="only the 15-members-at-once scenarios (F2)")
    args = ap.parse_args(argv)
    rounds = 1 if args.quick else args.rounds
    cap = install_capture()
    results, notes = Results(), {}
    worlds: Dict[int, World] = {}
    started = time.monotonic()
    for name, size, profile, kind in scenarios(args.quick, args.burst_only):
        world = worlds.get(size) or worlds.setdefault(size, World(args.seed, size))
        print(f"... {name}", file=sys.stderr, flush=True)
        if kind == "burst":
            run_burst(name, world, profile, cap, results, rounds, notes)
        else:
            run_sequential(name, world, profile, cap, results, rounds, notes=notes)
    import fastapi
    header = (f"bench_catalog v{BENCH_VERSION} seed={args.seed} rounds={rounds} members={len(make_members())} "
              f"python={platform.python_version()} fastapi={fastapi.__version__} os={platform.system()} "
              f"{platform.release()} machine={platform.machine()} cpus={os.cpu_count()} "
              f"wall={time.monotonic() - started:.0f}s")
    print(header)
    print()
    print(results.table())
    print()
    print("notes: " + json.dumps(notes, sort_keys=True))
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"header": header, "rows": results.as_json(), "notes": notes}, fh, indent=1)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
