"""A fake Komga served from HAND-WRITTEN synthetic fixtures (written from recollection of the public API;
unverified against any real server). No sockets: a router behind the same FakeTransport the Jellyfin tests
use. It stands for the ONE regular (non-admin) shared account (ADAPTER-CONTRACT 12.2): it returns what that
account sees, and has no user list at all (`/api/v2/users` is a 404 here, as it is for a regular key)."""
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "komga"
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-image-bytes"


def load(name):
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert doc["_synthetic"].startswith("Hand-written SYNTHETIC"), name
    assert "unverified against the deployed version" in doc["_synthetic"], name
    assert "NOT confirmed" in doc["_target_version"], name
    assert "SYNTHETIC assumption" in doc["_provenance"] and "UNPROVEN" in doc["_provenance"], name
    return doc["response"]


class FakeKomga:
    def __init__(self, clock=None):
        self.clock = clock
        self.books = load("books.json")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        text = json.dumps(load("books_latest.json"))
        text = re.sub(r'"@days_ago:(-?\d+)"', lambda m: json.dumps(
            (now - timedelta(days=int(m.group(1)))).isoformat().replace("+00:00", "Z")), text)
        text = re.sub(r'"@date_ago:(-?\d+)"', lambda m: json.dumps(
            (now - timedelta(days=int(m.group(1)))).date().isoformat()), text)
        self.latest = json.loads(text)        # newest `created` first, as GET /api/v1/books?sort=created,desc
        self.series = {}                      # series id -> SeriesDto (title pages only); empty: every series is a 404
        self.requests = []
        self.overrides = {}        # path -> ("status", int) | ("body", bytes) | ("raise", exc)
        self.slow = {}
        self.image = (200, PNG, "image/png")

    def copy_of(self, obj):
        return copy.deepcopy(obj)

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
        if path == "/api/v1/books" and "search" not in query:
            page = dict(self.latest)
            content = list(page["content"])
            if query.get("sort") == "metadata.releaseDate,desc":
                content.sort(key=lambda b: b["metadata"].get("releaseDate") or "", reverse=True)
            elif query.get("sort") != "created,desc":
                return 400, b"{}", "application/json"
            page["content"] = content[:int(query.get("size", "20"))]
            return self._json(page)
        if path == "/api/v1/books":
            term = query.get("search", "").casefold()
            hits = [b for b in reversed(list(self.books.values()))
                    if term and term in b["metadata"]["title"].casefold()]
            page = {"content": hits[:int(query.get("size", "20"))], "number": 0, "totalElements": len(hits)}
            return self._json(page)
        if path == "/api/v2/users/me":        # the shared account's own record: a regular account (AVR-782)
            return self._json({"id": "SHAREDUSER01", "email": "viewer@example.test",
                               "roles": ["FILE_DOWNLOAD", "PAGE_STREAMING"]})
        parts = path.strip("/").split("/")
        if parts[:3] == ["api", "v1", "books"] and len(parts) == 4:
            return self._lookup(self.books, parts[3])
        if parts[:3] == ["api", "v1", "series"] and len(parts) == 4:
            return self._lookup(self.series, parts[3])
        if parts[:3] == ["api", "v1", "books"] and len(parts) == 5 and parts[4] == "thumbnail":
            return self.image if parts[3] in self.books else (404, b"{}", "application/json")
        return 404, b"{}", "application/json"

    def _lookup(self, table, key):
        return self._json(table[key]) if key in table else (404, b"{}", "application/json")

    @staticmethod
    def _json(obj):
        return 200, json.dumps(obj).encode("utf-8"), "application/json"

    def paths(self):
        return [p for _, p, _ in self.requests]
