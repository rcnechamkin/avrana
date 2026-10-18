"""A fake Calibre-Web OPDS served from a HAND-WRITTEN synthetic fixture (recalled from public behaviour;
unverified against any real server). No sockets: a router behind the same FakeTransport the other adapters'
tests use. It serves the ONE catalogue the shared viewer account sees, to everyone."""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "calibre_web"
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-image-bytes"


def load(name):
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert doc["_synthetic"].startswith("Hand-written SYNTHETIC"), name
    assert "unverified against the deployed version" in doc["_synthetic"], name
    assert "NOT confirmed" in doc["_target_version"], name
    assert "SYNTHETIC assumption" in doc["_provenance"] and "UNPROVEN" in doc["_provenance"], name
    return doc["response"]


class FakeCalibreWeb:
    def __init__(self, clock=None):
        self.clock = clock
        self.feed = load("new_feed.json")
        self.search_doc = load("search_feed.json")
        self.covers = {"101", "102", "103"}
        self.requests = []
        self.overrides = {}        # path -> ("status", int) | ("body", bytes) | ("raise", exc)
        self.slow = {}
        self.image = (200, PNG, "image/png")

    def handle(self, method, path, query):
        query = dict(query or {})
        self.requests.append((method, path, query))
        if path in self.slow and self.clock is not None:
            self.clock.advance(self.slow[path])
        kind, val = self.overrides.get(path, (None, None))
        if kind == "raise":
            raise val
        if kind == "status":
            return val, b"{}", "application/atom+xml"
        if kind == "body":
            return 200, val, "application/atom+xml"
        if path == "/opds/new":
            return 200, self.feed.encode("utf-8"), "application/atom+xml;profile=opds-catalog"
        if path == "/opds/search":
            term = query.get("query", "").casefold() if query else ""
            body = "".join(e["xml"] for e in self.search_doc["entries"] if term and term in e["title"].casefold())
            return 200, (self.search_doc["head"] + body + "</feed>").encode("utf-8"), "application/atom+xml"
        if path.startswith("/opds/cover_240_240/"):
            return self.image if path.rsplit("/", 1)[1] in self.covers else (404, b"", "text/html")
        return 404, b"", "text/html"

    def paths(self):
        return [p for _, p, _ in self.requests]
