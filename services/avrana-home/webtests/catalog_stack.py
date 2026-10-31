"""A synthetic stack for the Library catalogue: the four REAL adapters over in-memory upstreams that page the way each
upstream's published source does (docs/design/LIBRARY-CATALOG.md). Four members:

  member-a   videos + books      (Komga and Audiobookshelf absent)
  member-b   comics + audio
  member-c   no library
  member-d   all four; no Komga key unless `keyed_d`

Every title carries its owner, so a test can see a leak by searching the page for the other member's marker."""
import json
import os
import tempfile
import zlib
import struct

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.calibre_web import CalibreWebAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.member_keys import MemberKeyStore, read_keys, write_keys
from avrana_home.resilience import TransportResponse, classify_status

GROUPS = {"member-a": "avrana-users|avrana-videos|avrana-books", "member-b": "avrana-users|avrana-comics|avrana-audiobooks",
          "member-c": "avrana-users", "member-d": "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"}
UIDS = {"member-a": "a" * 32, "member-b": "b" * 32, "member-d": "d" * 32}
ABS_UIDS = {"member-b": "00000000-0000-4000-8000-00000000000b", "member-d": "00000000-0000-4000-8000-00000000000d"}
LIBRARY = "11111111-1111-4111-8111-111111111111"
KEY_B, KEY_D = "b" * 32, "d" * 32
BOOKS_PER_PAGE = 60


def png(rgb=(90, 80, 120)):
    raw = b"\x00" + bytes(rgb)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Wire:
    def __init__(self, handle, ctype="application/json"):
        self.handle, self.ctype, self.calls, self.status = handle, ctype, [], 200

    def request(self, method, path, query, timeout, max_bytes):
        self.calls.append((path, dict(query or {})))
        if self.status != 200:
            raise classify_status(self.status)
        status, body, *ctype = self.handle(path, dict(query or {}))
        if status >= 400:
            raise classify_status(status)
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        return TransportResponse(status, data, ctype[0] if ctype else self.ctype)


class Stack:
    def __init__(self, keyed_d=True, films=60, shows=30, books=130, audiobooks=50, series=50):
        self.films = {u: [] for u in UIDS.values()}
        for who, uid in UIDS.items():
            mark = "Alpha" if who == "member-a" else "Bravo" if who == "member-b" else "Delta"
            self.films[uid] = ([{"Id": f"{n:030x}{uid[:2]}", "Name": f"{mark} Film {n:04}", "Type": "Movie",
                                 "ImageTags": {"Primary": "t"}, "UserData": {}} for n in range(films)]
                               + [{"Id": f"{n + 5000:030x}{uid[:2]}", "Name": f"{mark} Show {n:04}", "Type": "Series",
                                   "ImageTags": {"Primary": "t"}, "UserData": {}} for n in range(shows)])
        self.audio = [{"id": f"00000000-0000-4000-9000-{n:012x}", "libraryId": LIBRARY, "mediaType": "book",
                       "isMissing": False, "isInvalid": False, "addedAt": 1,
                       "media": {"tags": [], "duration": 60.0, "metadata": {
                           "title": f"Bravo Audiobook {n:04}", "authorName": "Synthetic Author", "explicit": False}}}
                      for n in range(audiobooks)]
        self.series = {KEY_B: [self.one(n, "Bravo") for n in range(series)], KEY_D: [self.one(1000, "Delta")]}
        self.book_count = books
        self.jellyfin = Wire(self.jellyfin_handle)
        self.audiobookshelf = Wire(self.abs_handle)
        self.shared_komga = Wire(lambda p, q: (500, {}))
        self.calibre = Wire(self.calibre_handle, "application/atom+xml")
        self.keys = {}
        self.dir = tempfile.TemporaryDirectory()
        path = os.path.join(self.dir.name, "keys")
        filed = {"member-b@example.org": KEY_B}
        if keyed_d:
            filed["member-d@example.org"] = KEY_D
        write_keys(path, filed)
        self.store = MemberKeyStore(path, initial=read_keys(path))

    @staticmethod
    def one(n, mark):
        return {"id": f"SERIES{n:06}", "libraryId": "LIBCOMICS1", "name": f"folder {n}", "booksCount": n % 4 + 1,
                "deleted": False, "metadata": {"title": f"{mark} Series {n:04}"}}

    def jellyfin_handle(self, path, query):
        if path == "/Users":
            return 200, [{"Name": name, "Id": uid} for name, uid in UIDS.items()]
        if "/Images/" in path:
            return 200, png(), "image/png"
        rows = self.films.get(query.get("userId"), [])
        if "ids" in query:
            hits = [r for r in rows if r["Id"] in query["ids"].split(",")]
            return 200, {"Items": hits, "TotalRecordCount": len(hits)}
        rows = [r for r in rows if r["Type"] == query.get("includeItemTypes")]
        start, limit = int(query.get("startIndex", "0")), int(query.get("limit", "50"))
        return 200, {"Items": rows[start:start + limit], "TotalRecordCount": len(rows)}

    def abs_handle(self, path, query):
        if path == "/api/users":
            return 200, {"users": [{"id": uid, "username": n, "isActive": True} for n, uid in ABS_UIDS.items()]}
        if path.startswith("/api/users/"):
            uid = path.rsplit("/", 1)[1]
            name = next(n for n, u in ABS_UIDS.items() if u == uid)
            return 200, {"id": uid, "username": name, "isActive": True, "mediaProgress": [], "librariesAccessible": [],
                         "itemTagsSelected": [], "permissions": {"accessAllLibraries": True, "accessAllTags": True,
                                                                 "accessExplicitContent": True}}
        if path == "/api/libraries":
            return 200, {"libraries": [{"id": LIBRARY, "mediaType": "book"}]}
        if path.endswith("/cover"):
            return 200, png((120, 90, 80)), "image/png"
        if path.startswith("/api/items/"):
            iid = path.split("/")[3]
            return next(((200, x) for x in self.audio if x["id"] == iid), (404, {}))
        limit, page = int(query["limit"]), int(query.get("page", "0"))
        return 200, {"results": self.audio[page * limit:(page + 1) * limit], "total": len(self.audio)}

    def transport(self, key):
        def handle(path, query):
            if path.endswith("/thumbnail"):
                return 200, png((80, 120, 90)), "image/png"
            rows = self.series[key]
            size, page = int(query["size"]), int(query["page"])
            return 200, {"content": rows[page * size:(page + 1) * size], "totalElements": len(rows)}
        return self.keys.setdefault(key, Wire(handle))

    def calibre_handle(self, path, query):
        if path.startswith("/opds/cover_240_240/"):
            return 200, png((80, 90, 120)), "image/png"
        offset = int(query.get("offset", "0"))
        ends = offset + BOOKS_PER_PAGE
        link = f'<link rel="next" href="/opds/books/letter/00?offset={ends}"/>' if ends < self.book_count else ""
        rows = "".join(f'<entry><title>Alpha Novel {n:04}</title><author><name>Synthetic Author</name></author>'
                       f'<link rel="http://opds-spec.org/image/thumbnail" href="/opds/cover_240_240/{n + 1}"/></entry>'
                       for n in range(offset, min(ends, self.book_count)))
        return 200, ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Books</title>' + link + rows + "</feed>").encode()

    def adapters(self, timeout=2.0):
        return [JellyfinAdapter(self.jellyfin, timeout=timeout), AudiobookshelfAdapter(self.audiobookshelf, timeout=timeout),
                KomgaAdapter(self.shared_komga, timeout=timeout, owner_confirms_no_member_restrictions=True,
                             member_keys=self.store, member_transport=self.transport),
                CalibreWebAdapter(self.calibre, timeout=timeout, owner_confirms_no_member_restrictions=True)]


def headers(who, groups=None):
    return [("X-authentik-username", who), ("X-authentik-groups", groups or GROUPS[who]),
            ("X-authentik-email", f"{who}@example.org")]
