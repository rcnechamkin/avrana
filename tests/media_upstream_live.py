#!/usr/bin/env python3
"""RC3 Gate C (AVR-772, AVR-386): Home's real adapters against REAL, throwaway Jellyfin, Audiobookshelf and Komga.

CI only (.github/workflows/upstream-contracts.yml, through tests/media_upstream_live.sh), on an --internal Docker
network, at production's image digests. Standard library plus Home's own stdlib adapters. Every credential is random
and made here for this run; nothing is printed but check names, synthetic titles and fixed outcomes.

What the fakes cannot prove and this does (the question in every check): does the UPSTREAM enforce what Home's
adapters assume? The reference in each parity check is what the upstream answers to that member's OWN token, never a
Home fixture:

  * Jellyfin: Home holds a global admin key and sends `userId`. Does Jellyfin scope /Items, /Items?ids=, /Items/Latest,
    /UserItems/Resume and /Shows/NextUp to that user when the caller is an API key?
  * Audiobookshelf: Home holds an admin-capable token, and `_Access` does the filtering. Does it match ABS's own?
  * Komga: Home holds one shared key (a shared view, by owner decision) plus members' own keys. What does each see?
  * Revocation: what changes at once, and what only when a cached section expires.
"""
import base64
import json
import os
import secrets
import shutil
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import zipfile
import zlib
from pathlib import Path

HOME = Path(os.environ.get("HOME_SRC", "/repo/services/avrana-home"))
PINS = HOME / "contracts" / "upstream-pins.json"
sys.path.insert(0, str(HOME))

JF, ABS, KG = "http://10.0.1.11:8096", "http://10.0.1.12:80", "http://10.0.1.13:25600"
FULL, LIMITED = "member-full", "member-limited"
TIMEOUT = 15.0


# ---- reporting -----------------------------------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.passed, self.failed = 0, []

    def check(self, name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)
        if ok:
            self.passed += 1
        else:
            self.failed.append(name)

    @staticmethod
    def fact(name, value):
        print(f"FACT {name}: {value}", flush=True)


report = Report()


def http(method, url, headers=None, body=None, raw=False, timeout=30):
    data = None
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            status, payload = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, exc.read()
    except (urllib.error.URLError, OSError):
        return 0, None
    if raw:
        return status, payload
    try:
        return status, json.loads(payload.decode("utf-8")) if payload else None
    except ValueError:
        return status, None


def wait(what, probe, seconds=240, every=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        got = probe()
        if got:
            return got
        time.sleep(every)
    sys.exit(f"TIMEOUT waiting for {what}")


def expect(what, got, *ok):
    if got[0] not in (ok or (200, 201, 204)):
        sys.exit(f"SETUP FAILED {what}: HTTP {got[0]}")
    return got[1]


# ---- fixtures (no network) -------------------------------------------------------------------------------------------
def png(colour=(40, 80, 160), size=32):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    row = b"\0" + bytes(colour) * size
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def cbz(path: Path, colour):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for n in range(1, 4):
            z.writestr(f"page{n:03}.png", png(colour))


def wav(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80" * 8000 * 30)
    (path.parent / "cover.png").write_bytes(png((120, 40, 40), 64))


def movie(root: Path, sample: Path, name: str, nfo: str = ""):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample, folder / f"{name}.mp4")
    (folder / "poster.png").write_bytes(png((40, 120, 40), 64))
    if nfo:
        (folder / "movie.nfo").write_text(nfo, encoding="utf-8")


def episodes(root: Path, sample: Path, show: str):
    season = root / show / "Season 01"
    season.mkdir(parents=True, exist_ok=True)
    (root / show / "poster.png").write_bytes(png((40, 40, 120), 64))
    for n in (1, 2):
        shutil.copy(sample, season / f"{show} S01E0{n}.mp4")


def fixtures(base: str):
    base = Path(base)
    sample = base / "sample.mp4"
    cbz(base / "komga/open/Open Series/Open Series 001.cbz", (10, 10, 200))
    cbz(base / "komga/open/Open Series/Open Series 002.cbz", (10, 10, 210))
    cbz(base / "komga/closed/Closed Series/Closed Series 001.cbz", (200, 10, 10))
    wav(base / "abs/open/Author One/Open Book One/book.wav")
    wav(base / "abs/open/Author One/Open Book Explicit/book.wav")
    wav(base / "abs/open/Author One/Open Book Tagged/book.wav")
    wav(base / "abs/closed/Author Two/Closed Book Two/book.wav")
    movie(base / "jf/open", sample, "Open Alpha (2020)")
    movie(base / "jf/open", sample, "Open Tagged (2021)",
          '<?xml version="1.0"?><movie><title>Open Tagged</title><tag>secret</tag></movie>')
    movie(base / "jf/closed", sample, "Closed Bravo (2019)")
    episodes(base / "jf/tv", sample, "Open Show")
    episodes(base / "jf/tvclosed", sample, "Closed Show")
    for dirpath, dirs, files in os.walk(base):
        os.chmod(dirpath, 0o755)
        for f in files:
            os.chmod(os.path.join(dirpath, f), 0o644)
    print("fixtures written")


# ---- Home's adapters -------------------------------------------------------------------------------------------------
def member(username, *groups, email=None):
    from avrana_home.principal import principal_from_headers
    headers = [("X-authentik-username", username), ("X-authentik-groups", "|".join(("avrana-users",) + groups))]
    if email:
        headers.append(("X-authentik-email", email))
    return principal_from_headers(headers)


def cache():
    from avrana_home.cache import MemberCache
    from avrana_home.resilience import FakeClock
    clock = FakeClock()
    store = MemberCache(clock)
    store.test_clock = clock
    return store


def titles(section):
    return sorted(i.title for i in section.items)


def state(section):
    return section.state.value


def ids(section):
    return {i.id.split(":", 1)[1] for i in section.items}


# ---- Jellyfin --------------------------------------------------------------------------------------------------------
JF_CLIENT = 'MediaBrowser Client="ci", Device="ci", DeviceId="rc3-live", Version="1"'


class Jellyfin:
    def __init__(self):
        self.admin_pw = secrets.token_hex(16)
        self.token = None
        self.key = None

    def auth(self, token=None):
        return {"Authorization": JF_CLIENT + (f', Token="{token or self.token}"' if token or self.token else "")}

    def call(self, method, path, body=None, token=None, **kw):
        return http(method, JF + path, self.auth(token), body, **kw)

    def login(self, name, password):
        got = expect("jellyfin login", http("POST", JF + "/Users/AuthenticateByName", {"Authorization": JF_CLIENT},
                                            {"Username": name, "Pw": password}))
        return got["AccessToken"], got["User"]["Id"]

    def setup(self):
        wait("jellyfin up", lambda: http("GET", JF + "/System/Info/Public")[0] == 200)
        wait("jellyfin first user", lambda: self.call("GET", "/Startup/User")[0] == 200)
        expect("startup config", self.call("POST", "/Startup/Configuration", {
            "UICulture": "en-US", "MetadataCountryCode": "US", "PreferredMetadataLanguage": "en"}))
        expect("startup user", self.call("POST", "/Startup/User", {"Name": "rootadmin", "Password": self.admin_pw}))
        expect("startup done", self.call("POST", "/Startup/Complete"))
        self.token, self.admin_id = wait("jellyfin login", lambda: self.try_login())
        expect("api key", self.call("POST", "/Auth/Keys?app=home-ci"))
        self.key = expect("list keys", self.call("GET", "/Auth/Keys"))["Items"][0]["AccessToken"]
        self.libs = {}
        for name, kind, path in (("Open", "movies", "/media/open"), ("Closed", "movies", "/media/closed"),
                                 ("OpenTV", "tvshows", "/media/tv"), ("ClosedTV", "tvshows", "/media/tvclosed")):
            query = urllib.parse.urlencode({"name": name, "collectionType": kind, "paths": path,
                                            "refreshLibrary": "false"})
            # No fetchers: the network is --internal, and only the local files and .nfo matter here.
            options = {"EnableRealtimeMonitor": False, "EnableInternetProviders": False,
                       "TypeOptions": [{"Type": t, "MetadataFetchers": [], "ImageFetchers": []}
                                       for t in ("Movie", "Series", "Season", "Episode")]}
            expect("library", self.call("POST", "/Library/VirtualFolders?" + query, {"LibraryOptions": options}))
        expect("refresh", self.call("POST", "/Library/Refresh"))
        wanted = {"Open Alpha", "Open Tagged", "Closed Bravo", "Open Show", "Closed Show"}

        def listed():
            items = self.items(self.admin_id)
            names = {i["Name"] for i in items}
            eps = sum(i["Type"] == "Episode" for i in items)
            self.seen = (sorted(names), eps)
            return items if wanted <= names and eps == 4 else None
        try:
            self.all_items = wait("jellyfin scan", listed, seconds=300, every=3)
        except SystemExit:
            Report.fact("jellyfin scan saw", self.seen)
            raise
        self.id_of = {i["Name"]: i["Id"].replace("-", "") for i in self.all_items if i["Type"] != "Episode"}
        self.eps = {(i.get("SeriesName"), i.get("IndexNumber")): i["Id"].replace("-", "")
                    for i in self.all_items if i["Type"] == "Episode"}
        folders = expect("folders", self.call("GET", "/Library/VirtualFolders"))
        self.libs = {f["Name"]: f["ItemId"] for f in folders}

    def try_login(self):
        status, got = http("POST", JF + "/Users/AuthenticateByName", {"Authorization": JF_CLIENT},
                           {"Username": "rootadmin", "Pw": self.admin_pw})
        return (got["AccessToken"], got["User"]["Id"]) if status == 200 else None

    def items(self, user_id, token=None):
        query = urllib.parse.urlencode({"userId": user_id, "recursive": "true", "fields": "Tags",
                                        "includeItemTypes": "Movie,Series,Episode", "limit": "100"})
        got = self.call("GET", "/Items?" + query, token=token)
        return (got[1] or {}).get("Items", []) if got[0] == 200 else []

    def new_user(self, name):
        password = secrets.token_hex(16)
        user = expect("new user", self.call("POST", "/Users/New", {"Name": name, "Password": password}))
        return user["Id"], password

    def policy(self, user_id, **changes):
        policy = expect("user", self.call("GET", f"/Users/{user_id}"))["Policy"]
        policy.update(changes)
        expect("policy", self.call("POST", f"/Users/{user_id}/Policy", policy))

    def progress(self, user_id, item_id, ticks=300000000):
        expect("progress", self.call("POST", f"/UserItems/{item_id}/UserData?userId={user_id}",
                                     {"PlaybackPositionTicks": ticks}))

    def played(self, user_id, item_id):
        expect("played", self.call("POST", f"/UserPlayedItems/{item_id}?userId={user_id}"))


def jellyfin_checks():
    from avrana_home.adapters.jellyfin import JellyfinAdapter
    from avrana_home.resilience import UrllibTransport
    jf = Jellyfin()
    jf.setup()
    version = (http("GET", JF + "/System/Info/Public")[1] or {}).get("Version")
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    report.check("jellyfin version is the pinned one", version == pins["jellyfin"]["version"], str(version))
    full_id, _ = jf.new_user(FULL)
    limited_id, limited_pw = jf.new_user(LIMITED)
    tagged_id, tagged_pw = jf.new_user("member-tagged")
    open_movie, closed_movie = jf.id_of["Open Alpha"], jf.id_of["Closed Bravo"]
    tagged_movie = jf.id_of["Open Tagged"]
    # Progress on every library first, THEN the restriction: what a member did before losing a library.
    jf.progress(limited_id, open_movie)
    jf.progress(limited_id, closed_movie)
    jf.progress(full_id, closed_movie, 600000000)
    jf.played(limited_id, jf.eps[("Closed Show", 1)])
    jf.played(limited_id, jf.eps[("Open Show", 1)])
    open_only = [jf.libs["Open"], jf.libs["OpenTV"]]
    jf.policy(limited_id, EnableAllFolders=False, EnabledFolders=open_only)
    jf.policy(tagged_id, BlockedTags=["secret"])
    limited_token, _ = jf.login(LIMITED, limited_pw)
    tagged_token, _ = jf.login("member-tagged", tagged_pw)

    store = cache()
    adapter = JellyfinAdapter(UrllibTransport(JF, {"Authorization": f'MediaBrowser Token="{jf.key}"'}),
                              timeout=TIMEOUT, cache=store)
    adapter.cache = store
    group = adapter.required_group
    p_full, p_lim, p_tag = member(FULL, group), member(LIMITED, group), member("member-tagged", group)

    # Authorisation parity: the reference is the member's OWN token.
    own = {i["Id"].replace("-", "") for i in jf.items(limited_id, limited_token)}
    report.check("jellyfin own token: the limited member cannot list the closed library", closed_movie not in own)
    through_key = {i["Id"].replace("-", "") for i in jf.items(limited_id)}
    report.check("jellyfin API key + userId lists exactly what the member's own token lists", through_key == own,
                 f"{len(through_key)} vs {len(own)}")
    own_tagged = {i["Id"].replace("-", "") for i in jf.items(tagged_id, tagged_token)}
    Report.fact("jellyfin blocked tag hidden from own token", tagged_movie not in own_tagged)
    key_tagged = {i["Id"].replace("-", "") for i in jf.items(tagged_id)}
    report.check("jellyfin API key + userId honours a blocked tag like the own token", key_tagged == own_tagged,
                 f"{len(key_tagged)} vs {len(own_tagged)}")

    recent = adapter.recent_items(p_lim, 12)
    report.check("jellyfin recent: limited sees no closed title", state(recent) in ("ok", "empty")
                 and not {"Closed Bravo", "Closed Show"} & set(titles(recent)), str(titles(recent)))
    report.check("jellyfin recent: limited sees an open title", "Open Alpha" in titles(recent), str(titles(recent)))
    report.check("jellyfin recent: full sees the closed title", "Closed Bravo" in titles(adapter.recent_items(p_full, 12)))
    search = adapter.search(p_lim, "Bravo", 12)
    report.check("jellyfin search: closed title absent for limited", state(search) == "empty", state(search))
    report.check("jellyfin search: found for full", "Closed Bravo" in titles(adapter.search(p_full, "Bravo", 12)))
    cont = adapter.continue_items(p_lim, 12)
    report.check("jellyfin continue: own open progress shown", "Open Alpha" in titles(cont), str(titles(cont)))
    report.check("jellyfin continue: progress in a revoked library is not shown",
                 closed_movie not in ids(cont), str(titles(cont)))
    report.check("jellyfin continue: another member's position never shown",
                 all(i.position_seconds != 60 for i in cont.items))
    nextup = adapter.next_up_items(p_lim, 12)
    report.check("jellyfin up next: limited gets the open show only",
                 {i.series for i in nextup.items} <= {"Open Show"}, str([i.series for i in nextup.items]))
    report.check("jellyfin up next: real answer parses", state(nextup) in ("ok", "empty"), state(nextup))
    released = adapter.released_items(p_lim, 12)
    report.check("jellyfin released: no closed title", closed_movie not in ids(released) and state(released) != "unavailable",
                 state(released))
    foryou = adapter.for_you_items(p_lim, 12)
    report.check("jellyfin for you: answers", state(foryou) in ("ok", "empty"), state(foryou))

    # Item enumeration: the id is known (a shared link), the title page and the cover are the two gates.
    item = adapter.item(p_lim, closed_movie, fresh=True)
    report.check("jellyfin title: closed id is empty for limited (item enumeration)",
                 state(item) == "empty" and not item.items, f"{state(item)} {titles(item)}")
    report.check("jellyfin title: closed episode id is empty for limited",
                 not adapter.item(p_lim, jf.eps[("Closed Show", 1)], fresh=True).items)
    report.check("jellyfin title: closed id is shown to full", titles(adapter.item(p_full, closed_movie, fresh=True)) == ["Closed Bravo"])
    art = adapter.fetch_artwork(p_lim, f"jellyfin/primary/{closed_movie}")
    report.check("jellyfin cover: closed id not served to limited", art.state.value != "ok" and not art.data, art.state.value)
    art = adapter.fetch_artwork(p_full, f"jellyfin/primary/{closed_movie}")
    report.check("jellyfin cover: real image for full", art.state.value == "ok" and art.content_type.startswith("image/"),
                 art.state.value)
    art = adapter.fetch_artwork(p_lim, f"jellyfin/primary/{open_movie}")
    report.check("jellyfin cover: real image for limited on an open title", art.state.value == "ok", art.state.value)
    report.check("jellyfin tag: blocked title not on the title page",
                 not adapter.item(p_tag, tagged_movie, fresh=True).items)
    report.check("jellyfin tag: blocked cover not served",
                 adapter.fetch_artwork(p_tag, f"jellyfin/primary/{tagged_movie}").state.value != "ok")

    # Revocation with a warm cache: Open taken away mid-session.
    warm = titles(adapter.recent_items(p_lim, 12))
    jf.policy(limited_id, EnabledFolders=[])
    report.check("jellyfin revoke: title page is empty at once", not adapter.item(p_lim, open_movie, fresh=True).items)
    report.check("jellyfin revoke: cover is refused at once though its bytes are cached",
                 adapter.fetch_artwork(p_lim, f"jellyfin/primary/{open_movie}").state.value != "ok")
    report.check("jellyfin revoke: search at once", state(adapter.search(p_lim, "Alpha", 12)) == "empty")
    still = titles(adapter.recent_items(p_lim, 12))
    report.check("jellyfin revoke: a cached section keeps its titles until its TTL (KNOWN WINDOW)", still == warm, str(still))
    store.test_clock.t += 121
    report.check("jellyfin revoke: the cached section is gone after its TTL", "Open Alpha" not in titles(adapter.recent_items(p_lim, 12)))
    jf.policy(limited_id, EnabledFolders=open_only)

    jf.policy(limited_id, IsDisabled=True)
    store.test_clock.t += 61
    report.check("jellyfin disabled user: not linked after the mapping TTL",
                 state(adapter.recent_items(p_lim, 12)) == "not_linked")
    unknown = adapter.recent_items(member("member-unknown", group), 12)
    report.check("jellyfin unmapped member: not linked, nothing shown", state(unknown) == "not_linked" and not unknown.items)
    twin = adapter.recent_items(member("Member-Full", group), 12)
    report.check("jellyfin case twin never links", state(twin) == "not_linked" and not twin.items, state(twin))
    report.check("jellyfin no group: not permitted, no upstream call",
                 state(adapter.recent_items(member(FULL), 12)) == "not_permitted")


# ---- Audiobookshelf --------------------------------------------------------------------------------------------------
class Audiobookshelf:
    def __init__(self):
        self.pw = secrets.token_hex(16)

    def auth(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def call(self, method, path, body=None, token=None, **kw):
        return http(method, ABS + path, self.auth(token), body, **kw)

    def login(self, name, password):
        got = expect("abs login", http("POST", ABS + "/login", None, {"username": name, "password": password}))
        return got["user"].get("accessToken") or got["user"]["token"]

    def setup(self):
        wait("abs up", lambda: http("GET", ABS + "/status")[0] == 200)
        expect("abs init", http("POST", ABS + "/init", None, {"newRoot": {"username": "rootadmin", "password": self.pw}}))
        got = expect("abs root login", http("POST", ABS + "/login", None, {"username": "rootadmin", "password": self.pw}))
        self.token = got["user"]["token"]              # the legacy no-expiry kind Home's token may be (E6)
        self.libs = {}
        for name, path in (("Open", "/media/open"), ("Closed", "/media/closed")):
            lib = expect("abs library", self.call("POST", "/api/libraries", {
                "name": name, "folders": [{"fullPath": path}], "mediaType": "book"}))
            self.libs[name] = lib["id"]
            expect("abs scan", self.call("POST", f"/api/libraries/{lib['id']}/scan"))

        def listed(lib, want):
            got = self.call("GET", f"/api/libraries/{lib}/items?limit=50")
            rows = (got[1] or {}).get("results", []) if got[0] == 200 else []
            return rows if len(rows) >= want else None
        rows = wait("abs scan", lambda: listed(self.libs["Open"], 3)) + wait("abs scan", lambda: listed(self.libs["Closed"], 1))
        self.id_of = {r["media"]["metadata"]["title"]: r["id"] for r in rows}
        expect("abs tag", self.call("PATCH", f"/api/items/{self.id_of['Open Book Tagged']}/media", {"tags": ["secret"]}))
        expect("abs explicit", self.call("PATCH", f"/api/items/{self.id_of['Open Book Explicit']}/media",
                                         {"metadata": {"explicit": True}}))

    def new_user(self, name, **fields):
        password = secrets.token_hex(16)
        body = {"username": name, "password": password, "type": "user", "isActive": True,
                "permissions": {"download": True, "update": False, "delete": False, "upload": False,
                                "accessAllLibraries": True, "accessAllTags": True, "accessExplicitContent": True,
                                "selectedTagsNotAccessible": False},
                "librariesAccessible": [], "itemTagsSelected": []}
        perms = fields.pop("permissions", {})
        body["permissions"].update(perms)
        body.update(fields)
        got = expect("abs user", self.call("POST", "/api/users", body))
        return (got.get("user") or got)["id"], password

    def visible(self, token):
        """What ABS itself lets this token list: the reference for parity."""
        libs = self.call("GET", "/api/libraries", token=token)
        out = set()
        for lib in (libs[1] or {}).get("libraries", []):
            got = self.call("GET", f"/api/libraries/{lib['id']}/items?limit=50", token=token)
            out |= {r["id"] for r in (got[1] or {}).get("results", [])}
        return out


def audiobookshelf_checks():
    from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
    from avrana_home.resilience import UrllibTransport
    ab = Audiobookshelf()
    ab.setup()
    version = (http("GET", ABS + "/status")[1] or {}).get("serverVersion")
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    report.check("audiobookshelf version is the pinned one", version == pins["audiobookshelf"]["version"], str(version))
    full_id, full_pw = ab.new_user(FULL)
    limited_id, limited_pw = ab.new_user(
        LIMITED, permissions={"accessAllLibraries": True, "accessAllTags": True, "accessExplicitContent": True})
    book, closed = ab.id_of["Open Book One"], ab.id_of["Closed Book Two"]
    tagged, explicit = ab.id_of["Open Book Tagged"], ab.id_of["Open Book Explicit"]
    full_token, limited_token = ab.login(FULL, full_pw), ab.login(LIMITED, limited_pw)
    for token, item, at in ((limited_token, book, 5), (limited_token, closed, 7), (full_token, closed, 9)):
        expect("abs progress", ab.call("PATCH", f"/api/me/progress/{item}",
                                       {"currentTime": at, "duration": 30, "progress": at / 30, "isFinished": False},
                                       token=token))
    restricted = {"permissions": {"accessAllLibraries": False, "accessAllTags": False, "accessExplicitContent": False,
                                  "selectedTagsNotAccessible": True, "download": True, "update": False, "delete": False,
                                  "upload": False},
                  "librariesAccessible": [ab.libs["Open"]], "itemTagsSelected": ["secret"]}
    expect("abs restrict", ab.call("PATCH", f"/api/users/{limited_id}", restricted))
    limited_token = ab.login(LIMITED, limited_pw)

    store = cache()
    adapter = AudiobookshelfAdapter(UrllibTransport(ABS, {"Authorization": f"Bearer {ab.token}"}), timeout=TIMEOUT,
                                    cache=store)
    adapter.cache = store
    group = adapter.required_group
    p_full, p_lim = member(FULL, group), member(LIMITED, group)

    own = ab.visible(limited_token)
    report.check("abs own token: the limited member lists one book", own == {book}, str(sorted(own)))
    recent = adapter.recent_items(p_lim, 12)
    report.check("abs recent: adapter view equals the member's own upstream view (parity)", ids(recent) == own,
                 f"{sorted(ids(recent))} vs {sorted(own)}")
    report.check("abs recent: full sees all four", len(adapter.recent_items(p_full, 12).items) == 4)
    for term, name in (("Closed", "closed library"), ("Tagged", "denied tag"), ("Explicit", "explicit flag")):
        found = adapter.search(p_lim, term, 12)
        report.check(f"abs search: {name} absent for limited", state(found) == "empty", f"{state(found)} {titles(found)}")
    report.check("abs search: found for full", titles(adapter.search(p_full, "Closed", 12)) == ["Closed Book Two"])
    cont = adapter.continue_items(p_lim, 12)
    report.check("abs continue: own progress shown", titles(cont) == ["Open Book One"], str(titles(cont)))
    report.check("abs continue: position is the member's own (5 s)", cont.items and cont.items[0].position_seconds == 5)
    for item_id, why in ((closed, "closed library"), (tagged, "denied tag"), (explicit, "explicit flag")):
        report.check(f"abs title: {why} is empty for limited (item enumeration)",
                     not adapter.item(p_lim, item_id, fresh=True).items)
        report.check(f"abs cover: {why} not served to limited",
                     adapter.fetch_artwork(p_lim, f"audiobookshelf/cover/{item_id}").state.value != "ok")
    status = ab.call("GET", f"/api/items/{closed}", token=limited_token)[0]
    report.check("abs own token: the upstream itself refuses the closed item", status in (403, 404), str(status))
    art = adapter.fetch_artwork(p_lim, f"audiobookshelf/cover/{book}")
    report.check("abs cover: real image for limited", art.state.value == "ok", art.state.value)
    for name in ("released_items", "shelves_items", "for_you_items"):
        got = getattr(adapter, name)(p_lim, 12)
        report.check(f"abs {name}: answers, nothing hidden", state(got) in ("ok", "empty")
                     and not ids(got) & {closed, tagged, explicit}, state(got))

    warm = titles(adapter.recent_items(p_lim, 12))
    expect("abs revoke", ab.call("PATCH", f"/api/users/{limited_id}", {"librariesAccessible": [ab.libs["Closed"]]}))
    report.check("abs revoke: title page is empty at once", not adapter.item(p_lim, book, fresh=True).items)
    report.check("abs revoke: cover refused at once though cached",
                 adapter.fetch_artwork(p_lim, f"audiobookshelf/cover/{book}").state.value != "ok")
    report.check("abs revoke: a cached section keeps its titles until its TTL (KNOWN WINDOW)",
                 titles(adapter.recent_items(p_lim, 12)) == warm)
    store.test_clock.t += 121
    report.check("abs revoke: gone after the TTL", book not in ids(adapter.recent_items(p_lim, 12)))
    expect("abs disable", ab.call("PATCH", f"/api/users/{limited_id}", {"isActive": False}))
    report.check("abs deactivated: a cached mapping does not keep reads open",
                 state(adapter.search(p_lim, "Closed", 12)) == "not_linked",
                 state(adapter.search(p_lim, "Closed", 12)))
    twin = adapter.recent_items(member("Member-Full", group), 12)
    report.check("abs case twin never links", state(twin) == "not_linked", state(twin))


# ---- Komga -----------------------------------------------------------------------------------------------------------
class Komga:
    def __init__(self):
        self.email, self.pw = "root@example.test", secrets.token_hex(16)
        self.passwords = {self.email: self.pw}

    def auth(self, email=None):
        email = email or self.email
        return {"Authorization": "Basic " + base64.b64encode(f"{email}:{self.passwords[email]}".encode()).decode()}

    def call(self, method, path, body=None, email=None, **kw):
        return http(method, KG + path, self.auth(email), body, **kw)

    def with_key(self, key, path):
        return http("GET", KG + path, {"X-API-Key": key})

    def setup(self):
        wait("komga up", lambda: http("GET", KG + "/api/v1/claim")[0] == 200)
        expect("komga claim", http("POST", KG + "/api/v1/claim",
                                   {"X-Komga-Email": self.email, "X-Komga-Password": self.pw}))
        self.libs = {}
        for name, root in (("Open", "/media/open"), ("Closed", "/media/closed")):
            lib = expect("komga library", self.call("POST", "/api/v1/libraries", {"name": name, "root": root}))
            self.libs[name] = lib["id"]
            expect("komga scan", self.call("POST", f"/api/v1/libraries/{lib['id']}/scan"), 200, 202)

        def ready():
            got = self.call("GET", "/api/v1/books?size=50&unpaged=true")
            rows = (got[1] or {}).get("content", []) if got[0] == 200 else []
            return rows if len(rows) == 3 and all(r.get("media", {}).get("status") == "READY" for r in rows) else None
        rows = wait("komga scan", ready)
        self.ids = {r["name"]: r["id"] for r in rows}

    def new_user(self, email, shared):
        self.passwords[email] = secrets.token_hex(16)
        made = expect("komga user", self.call("POST", "/api/v2/users", {
            "email": email, "password": self.passwords[email], "roles": []}))
        self.share(made["id"], shared)
        key = expect("komga key", self.call("POST", "/api/v2/users/me/api-keys", {"comment": "avrana-home"}, email=email))
        return made["id"], key["key"], key["id"]

    def share(self, user_id, libraries):
        body = {"sharedLibraries": {"all": False, "libraryIds": libraries}}
        expect("komga share", self.call("PATCH", f"/api/v2/users/{user_id}", body))

    def progress(self, book, email, page=2):
        expect("komga progress", self.call("PATCH", f"/api/v1/books/{book}/read-progress",
                                           {"page": page, "completed": False}, email=email))


def komga_checks():
    from avrana_home.adapters.komga import KomgaAdapter
    from avrana_home.member_keys import MemberKeyStore
    from avrana_home.resilience import UrllibTransport
    kg = Komga()
    kg.setup()
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    info = kg.call("GET", "/actuator/info")[1] or {}
    version = (info.get("build") or {}).get("version")
    report.check("komga version is the pinned one", version == pins["komga"]["version"], str(version))
    open_lib, closed_lib = kg.libs["Open"], kg.libs["Closed"]
    book, closed = kg.ids["Open Series 001"], kg.ids["Closed Series 001"]
    full_mail, limited_mail = "full@example.test", "limited@example.test"
    _viewer_id, viewer_key, _ = kg.new_user("viewer@example.test", [open_lib])
    full_id, full_key, _ = kg.new_user(full_mail, [open_lib, closed_lib])
    limited_id, limited_key, limited_key_id = kg.new_user(limited_mail, [open_lib, closed_lib])
    kg.progress(book, limited_mail)
    kg.progress(closed, limited_mail)
    kg.progress(closed, full_mail, 3 - 1)
    kg.share(limited_id, [open_lib])

    folder = tempfile.mkdtemp()
    keys_file = os.path.join(folder, "keys")
    Path(keys_file).write_text(json.dumps({full_mail: full_key, limited_mail: limited_key}), encoding="utf-8")
    store = cache()

    def build(key):
        keys = MemberKeyStore(keys_file)
        adapter = KomgaAdapter(UrllibTransport(KG, {"X-API-Key": key}), timeout=TIMEOUT, cache=store,
                               owner_confirms_no_member_restrictions=True, member_keys=keys,
                               member_transport=lambda k: UrllibTransport(KG, {"X-API-Key": k}))
        adapter.cache = store
        return adapter
    adapter = build(viewer_key)
    group = adapter.required_group
    p_full = member(FULL, group, email=full_mail)
    p_lim = member(LIMITED, group, email=limited_mail)
    p_nokey = member("member-nokey", group, email="nokey@example.test")

    recent = adapter.recent_items(p_lim, 12)
    report.check("komga shared view: a restricted shared account hides the closed library",
                 closed not in ids(recent) and book in {*ids(recent), kg.ids["Open Series 002"]} | ids(recent), str(titles(recent)))
    report.check("komga shared view: the same list for every member (by owner decision)",
                 ids(adapter.recent_items(p_full, 12)) == ids(recent))
    item = adapter.item(p_lim, closed, fresh=True)
    report.check("komga title: a book the shared account may not read is empty (no 403/404 oracle)",
                 state(item) == "empty" and not item.items, state(item))
    gone = adapter.item(p_lim, "ZZZZZZZZZZZZZ", fresh=True)
    report.check("komga title: forbidden and unknown look the same", state(gone) == state(item), state(gone))
    Report.fact("komga shared key, forbidden book status", kg.with_key(viewer_key, f"/api/v1/books/{closed}")[0])
    art = adapter.fetch_artwork(p_lim, f"komga/book/{closed}")
    report.check("komga cover: a forbidden book is not served", art.state.value != "ok" and not art.data, art.state.value)
    report.check("komga cover: real image for an open book",
                 adapter.fetch_artwork(p_lim, f"komga/book/{book}").state.value == "ok")
    report.check("komga search: closed absent in the shared view", not adapter.search(p_full, "Closed", 12).items)
    report.check("komga circuit: forbidden books did not trip the shared circuit",
                 state(adapter.recent_items(member("member-other", group), 12)) == "ok")

    cont = adapter.continue_items(p_lim, 12)
    report.check("komga continue: own key shows own progress", book in ids(cont), str(titles(cont)))
    report.check("komga continue: own key hides a library unshared from the member", closed not in ids(cont), str(titles(cont)))
    report.check("komga continue: full member sees their own closed book, which the shared view hides",
                 closed in ids(adapter.continue_items(p_full, 12)))
    nokey = adapter.continue_items(p_nokey, 12)
    report.check("komga continue: no key, not offered, nothing from the shared account",
                 state(nokey) == "empty" and nokey.reason == "not_offered", f"{state(nokey)} {nokey.reason}")
    foryou = adapter.for_you_items(p_lim, 12)
    report.check("komga for you: answers, own key", state(foryou) in ("ok", "empty") and closed not in ids(foryou), state(foryou))

    # A restriction on the member's own Komga account does NOT reach the shared view: the documented limit of the design.
    kg.share(limited_id, [])
    store.test_clock.t += 301
    still = adapter.recent_items(p_lim, 12)
    report.check("komga DOCUMENTED LIMIT: a member with no Komga library still sees the shared view", bool(still.items))
    report.check("komga revoke: own-key Continue follows the upstream after its TTL", not adapter.continue_items(p_lim, 12).items)
    kg.share(limited_id, [open_lib])

    expect("komga revoke key", kg.call("DELETE", f"/api/v2/users/me/api-keys/{limited_key_id}", email=limited_mail), 200, 204)
    store.test_clock.t += 31
    refused = adapter.continue_items(p_lim, 12)
    report.check("komga revoked key: empty, says member_key_refused, no shared data",
                 not refused.items and refused.reason == "member_key_refused", f"{state(refused)} {refused.reason}")
    report.check("komga revoked key: the shared circuit is unaffected",
                 state(adapter.recent_items(member("member-third", group), 12)) == "ok")

    # What T-07 would mean (E1, 2026-10-30: the live shared key is REPORTED to be an admin's; not verified here).
    admin_key = expect("komga admin key", kg.call("POST", "/api/v2/users/me/api-keys", {"comment": "ci"}))["key"]
    store.test_clock.t += 301
    admin = build(admin_key).recent_items(member("member-admin-view", group), 12)
    report.check("komga T-07: with an ADMIN shared key every comics member sees every library", closed in ids(admin) or
                 any("Closed" in t for t in titles(admin)), str(titles(admin)))


def main():
    if sys.argv[1:] and sys.argv[1] == "fixtures":
        return fixtures(sys.argv[2])
    only = sys.argv[1] if sys.argv[1:] else "all"
    for name, run in (("jellyfin", jellyfin_checks), ("audiobookshelf", audiobookshelf_checks), ("komga", komga_checks)):
        if only in ("all", name):
            print(f"== {name}", flush=True)
            try:
                run()
            except SystemExit as exc:                    # one upstream's setup failing must not hide the others
                report.check(f"{name} setup", False, str(exc))
    print(f"{report.passed} passed, {len(report.failed)} failed")
    for name in report.failed:
        print("FAILED:", name)
    sys.exit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
