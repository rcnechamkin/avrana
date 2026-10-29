"""A fake Audiobookshelf served from HAND-WRITTEN synthetic fixtures (written from recollection of the
public API; unverified against any real server). No sockets: it is a router behind the same
FakeTransport / FakeOpener the Jellyfin tests use."""
import base64
import copy
import json
import re
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audiobookshelf"
UA = "aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa"
UB = "bbbbbbbb-2222-4bbb-8bbb-bbbbbbbbbbbb"
UC = "cccccccc-3333-4ccc-8ccc-cccccccccccc"
UD = "dddddddd-4444-4ddd-8ddd-dddddddddddd"
UE = "eeeeeeee-5555-4eee-8eee-eeeeeeeeeeee"
JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-cover-bytes"      # a synthetic cover: a JPEG magic number only


def load(name):
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert doc["_synthetic"].startswith("Hand-written SYNTHETIC"), name
    assert "unverified against the deployed version" in doc["_synthetic"], name
    assert doc["_target_version"].startswith("Audiobookshelf 2.36") and "NOT confirmed" in doc["_target_version"], name
    assert "SYNTHETIC assumption" in doc["_provenance"] and "UNPROVEN" in doc["_provenance"], name
    return doc["response"]


class FakeAudiobookshelf:
    """Router. `handle(method, path, query)` -> (status, body bytes, content type)."""

    def __init__(self, clock=None):
        self.clock = clock
        self.users_doc = load("users.json")
        self.records = {}
        for name in ("member_a", "member_b", "member_c", "member_d"):
            rec = load(f"user_{name}.json")
            self.records[rec["id"]] = rec
        self.items = load("items.json")
        year = str(time.gmtime().tm_year)
        now = int(time.time() * 1000)
        text = json.dumps(load("library_items.json")).replace('"@this_year"', f'"{year}"')
        text = re.sub(r'"@days_ago:(\d+)"', lambda m: str(now - int(m.group(1)) * 86_400_000), text)
        self.lists = json.loads(text)
        # A listed item that items.json lacks is still found by id (item and cover routes; not search).
        self.listed = {it["id"]: it for entries in self.lists.values() for it in entries}
        self.libraries_doc = load("libraries.json")
        self.requests = []
        self.overrides = {}        # path -> ("status", int) | ("body", bytes) | ("raise", exc)
        self.slow = {}
        self.image = (200, JPEG, "image/jpeg")   # what the cover route answers for an item with a cover
        # Series (add_series): item id -> [{id, name, sequence}], served as `media.metadata.series` of the EXPANDED item
        # and used by `filter=series.<base64 id>`. `series_dict`: a series-filtered minified entry carries the single
        # {id, name, sequence} object under `media.metadata.series` (as recalled from the server); False: only `seriesName`.
        self.series_of = {}
        self.series_dict = True

    def record(self, uid):
        """A private copy of a fixture user record, to be edited and served through `overrides`."""
        return copy.deepcopy(self.records[uid])

    def serve(self, path, obj):
        self.overrides[path] = ("body", json.dumps(obj).encode("utf-8"))

    def handle(self, method, path, query):
        query = dict(query or {})
        self.requests.append((method, path, query))
        if path in self.slow and self.clock is not None:
            self.clock.advance(self.slow[path])
        kind, val = self.overrides.get(path, (None, None))
        if kind == "raise":
            raise val
        if kind == "status":
            return val, b"{}", "application/json"
        if kind == "body":
            return 200, val, "application/json"
        if path == "/api/users":
            return self._json(self.users_doc)
        if path.startswith("/api/users/"):
            rec = self.records.get(path[len("/api/users/"):])
            return self._json(rec) if rec is not None else (404, b"{}", "application/json")
        if path == "/api/libraries":
            return self._json(self.libraries_doc)
        if path.startswith("/api/libraries/") and path.endswith("/search"):
            return self._search(path[len("/api/libraries/"):-len("/search")], query)
        if path.startswith("/api/libraries/") and path.endswith("/items"):
            return self._list(path[len("/api/libraries/"):-len("/items")], query)
        if path.startswith("/api/libraries/") and path.endswith("/filterdata"):
            lid = path[len("/api/libraries/"):-len("/filterdata")]
            if lid not in {x["id"] for x in self.libraries_doc["libraries"]}:
                return 404, b"{}", "application/json"
            genres = sorted({g for it in self.lists.get(lid, ()) for g in it["media"]["metadata"].get("genres", ())})
            return self._json({"authors": [], "genres": genres, "tags": [], "series": [], "narrators": [],
                               "languages": [], "publishers": []})
        if path.startswith("/api/items/") and path.endswith("/cover"):
            iid = path[len("/api/items/"):-len("/cover")]
            it = self.items.get(iid) or self.listed.get(iid)
            if it is None or it["media"].get("coverPath") is None:
                return 404, b"{}", "application/json"      # unknown item, or no cover
            return self.image
        if path.startswith("/api/items/"):
            iid = path[len("/api/items/"):]
            it = self.items.get(iid) or self.listed.get(iid)
            if it is not None and iid in self.series_of:
                it = copy.deepcopy(it)
                it["media"]["metadata"]["series"] = copy.deepcopy(self.series_of[iid])
            return self._json(it) if it is not None else (404, b"{}", "application/json")
        return 404, b"{}", "application/json"

    def _search(self, library_id, query):
        """Library search, synthesised from items.json: title or author contains the term (case-folded)."""
        lib = next((x for x in self.libraries_doc["libraries"] if x["id"] == library_id), None)
        if lib is None:
            return 404, b"{}", "application/json"
        if lib["mediaType"] != "book":
            return self._json({"podcast": [], "tags": [], "genres": []})
        term = query.get("q", "").casefold()
        hits = [{"libraryItem": it, "matchKey": "title", "matchText": it["media"]["metadata"]["title"]}
                for it in self.items.values()
                if it.get("libraryId") == library_id and term
                and (term in it["media"]["metadata"]["title"].casefold()
                     or term in (it["media"]["metadata"].get("authorName") or "").casefold())]
        return self._json({"book": hits[:int(query.get("limit", "12"))], "tags": [], "authors": [],
                           "series": [], "narrators": [], "genres": []})

    def _list(self, library_id, query):
        """A library list, synthesised from library_items.json: sorted by `sort` (addedAt, publishedYear or duration),
        `desc`, filtered by `filter=genres.<base64>`, cut to `limit`."""
        lib = next((x for x in self.libraries_doc["libraries"] if x["id"] == library_id), None)
        if lib is None:
            return 404, b"{}", "application/json"
        entries = list(self.lists.get(library_id, ()))
        flt = query.get("filter", "")
        if flt.startswith("genres."):
            genre = base64.b64decode(flt[len("genres."):]).decode("utf-8")
            entries = [it for it in entries if genre in it["media"]["metadata"].get("genres", ())]
        elif flt.startswith("series."):
            sid = base64.b64decode(flt[len("series."):]).decode("utf-8")
            entries = [self._in_series(it, sid) for it in entries
                       if any(s["id"] == sid for s in self.series_of.get(it["id"], ()))]
        key = {"addedAt": lambda it: it.get("addedAt") or 0,
               "media.metadata.publishedYear": lambda it: int(it["media"]["metadata"].get("publishedYear") or 0),
               "media.duration": lambda it: it["media"].get("duration") or 0}.get(query.get("sort"))
        if key is not None:
            entries.sort(key=key, reverse=query.get("desc") == "1")
        limit = int(query.get("limit", "0") or 0)
        results = entries[:limit] if limit else entries
        return self._json({"results": results, "total": len(entries), "limit": limit, "page": 0,
                           "sortBy": query.get("sort"), "sortDesc": query.get("desc") == "1",
                           "filterBy": flt or None, "mediaType": lib["mediaType"], "minified": True})

    def _in_series(self, item, series_id):
        """A minified entry as a series-filtered list serves it (UNVERIFIED shape, see `series_dict`)."""
        item = copy.deepcopy(item)
        if self.series_dict:
            item["media"]["metadata"]["series"] = next(s for s in self.series_of[item["id"]] if s["id"] == series_id)
        return item

    def add_series(self, library_id, series_id, name, books):
        """Add a series to a library. `books`: (item id, sequence or None, days ago it was added). Each is listed
        (minified, `seriesName` "<name> #<sequence>"), found by id, and filterable by the series."""
        now = int(time.time() * 1000)
        for item_id, sequence, days_ago in books:
            label = name if sequence is None else f"{name} #{sequence}"
            entry = {"id": item_id, "libraryId": library_id, "mediaType": "book", "isMissing": False,
                     "isInvalid": False, "addedAt": now - int(days_ago * 86_400_000),
                     "media": {"metadata": {"title": f"{name} Book {sequence}", "authorName": "Synthetic Author",
                                            "seriesName": label, "publishedYear": "2020", "explicit": False,
                                            "genres": ["Fantasy"]},
                               "tags": [], "duration": 36000.0,
                               "coverPath": f"/metadata/items/{item_id}/cover.jpg"}}
            self.lists.setdefault(library_id, []).append(entry)
            self.listed[item_id] = entry
            self.series_of[item_id] = [{"id": series_id, "name": name,
                                        "sequence": None if sequence is None else str(sequence)}]

    def set_progress(self, uid, item_id, progress, finished=False):
        """Give a member a progress entry for a book (their own record; `finished` also sets isFinished)."""
        self.records[uid]["mediaProgress"].append({
            "id": "mp_" + item_id, "userId": uid, "libraryItemId": item_id, "episodeId": None, "mediaItemType": "book",
            "duration": 36000.0, "progress": float(progress), "currentTime": 36000.0 * progress,
            "isFinished": bool(finished), "hideFromContinueListening": False, "lastUpdate": 1700000000000,
            "startedAt": 1700000000000, "finishedAt": None})

    @staticmethod
    def _json(obj):
        return 200, json.dumps(obj).encode("utf-8"), "application/json"

    def paths(self):
        return [p for _, p, _ in self.requests]
