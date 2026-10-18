"""A fake Audiobookshelf served from HAND-WRITTEN synthetic fixtures (written from recollection of the
public API; unverified against any real server). No sockets: it is a router behind the same
FakeTransport / FakeOpener the Jellyfin tests use."""
import copy
import json
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
        self.libraries_doc = load("libraries.json")
        self.requests = []
        self.overrides = {}        # path -> ("status", int) | ("body", bytes) | ("raise", exc)
        self.slow = {}
        self.image = (200, JPEG, "image/jpeg")   # what the cover route answers for an item with a cover

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
        if path.startswith("/api/items/") and path.endswith("/cover"):
            it = self.items.get(path[len("/api/items/"):-len("/cover")])
            if it is None or it["media"].get("coverPath") is None:
                return 404, b"{}", "application/json"      # unknown item, or no cover
            return self.image
        if path.startswith("/api/items/"):
            it = self.items.get(path[len("/api/items/"):])
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

    @staticmethod
    def _json(obj):
        return 200, json.dumps(obj).encode("utf-8"), "application/json"

    def paths(self):
        return [p for _, p, _ in self.requests]
