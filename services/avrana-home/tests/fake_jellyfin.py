"""A fake Jellyfin served from synthetic fixtures. No sockets: it is either a Transport or an
opener for UrllibTransport. Everything it returns is hand-written synthetic data."""
import io
import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from avrana_home.resilience import TransportResponse, classify_status

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jellyfin"
A = "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"
B = "bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb"
C = "cccccccccccc4ccc8ccccccccccccccc"
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-image-bytes"


def load(name):
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert doc["_synthetic"].startswith("Hand-written SYNTHETIC"), name
    return doc["response"]


def _hex(guid):
    return guid.replace("-", "").lower()


class FakeJellyfin:
    """Router. `handle(method, path, query)` -> (status, body bytes, content type)."""

    def __init__(self, clock=None):
        self.clock = clock
        self.users = load("users.json")
        self.requests = []                 # (method, path, query dict)
        self.overrides = {}                # path -> ("status", int) | ("body", bytes) | ("raise", exc)
        self.slow = {}                     # path -> seconds to advance the fake clock
        self.hostile_resume = None         # body served to resume queries (see hostile_users)
        self.hostile_users = None          # None = every asker; else only these 32-hex user ids
        self.image = (200, PNG, "image/png")

    def _name_for(self, user_id):
        for u in self.users:
            if _hex(u["Id"]) == user_id:
                return u["Name"].replace("-", "_").lower()
        return None

    def _per_user(self, kind, user_id):
        name = self._name_for(user_id)
        try:
            return load(f"{kind}_{name}.json")
        except (FileNotFoundError, TypeError):
            return {"Items": [], "TotalRecordCount": 0} if kind == "resume" else []

    def _visible(self, user_id):
        resume = self._per_user("resume", user_id)["Items"]
        latest = self._per_user("latest", user_id)
        return {_hex(i["Id"]): i for i in resume + latest if "Id" in i}

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
        if path == "/Users":
            return self._json(self.users)
        uid = _hex(query.get("userId", ""))
        if path == "/UserItems/Resume":
            if self.hostile_resume is not None and (self.hostile_users is None or uid in self.hostile_users):
                return self._json(self.hostile_resume)
            return self._json(self._per_user("resume", uid))
        if path == "/Items/Latest":
            return self._json(self._per_user("latest", uid))
        if path == "/Items":
            vis = self._visible(uid)
            found = [vis[i] for i in query.get("ids", "").split(",") if i in vis]
            return self._json({"Items": found, "TotalRecordCount": len(found)})
        if path.startswith("/Items/") and path.endswith("/Images/Primary"):
            return self.image
        return 404, b"{}", "application/json"

    @staticmethod
    def _json(obj):
        return 200, json.dumps(obj).encode("utf-8"), "application/json"

    def paths(self):
        return [p for _, p, _ in self.requests]


class FakeTransport:
    """Implements the Transport protocol over a FakeJellyfin. Counts every call."""

    def __init__(self, fake):
        self.fake = fake
        self.calls = 0
        self.timeouts = []

    def request(self, method, path, query, timeout, max_bytes):
        self.calls += 1
        self.timeouts.append(timeout)
        status, body, ctype = self.fake.handle(method, path, query)
        if status >= 400:
            raise classify_status(status)
        return TransportResponse(status, body, ctype)


class _Resp(io.BytesIO):
    def __init__(self, body, ctype):
        super().__init__(body)
        self.status = 200
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Stands in for urllib's opener under UrllibTransport; records outbound headers."""

    def __init__(self, fake):
        self.fake = fake
        self.seen_headers = []

    def open(self, req, timeout=None):
        parts = urlsplit(req.full_url)
        self.seen_headers.append(dict(req.header_items()))
        status, body, ctype = self.fake.handle(req.get_method(), parts.path, dict(parse_qsl(parts.query)))
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)
        return _Resp(body, ctype)
