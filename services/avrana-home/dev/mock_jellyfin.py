#!/usr/bin/env python3
"""A mock Jellyfin on 127.0.0.1, serving the repository's SYNTHETIC fixtures. Standard library only.

Not Jellyfin and not recorded from one: it answers the read-only routes the adapter uses, for the
invented members in tests/fixtures/jellyfin, and can be switched into failure modes:

  ok          normal answers
  slow        every answer is delayed by `slow_seconds` (default 5), longer than the adapter timeout
  down        the connection is accepted and dropped without a reply
  500         HTTP 500 for every request
  malformed   HTTP 200 with a truncated JSON body
  wrong-user  resume lists answer with the OTHER member's items and name that member in the user
              data (the upstream-ignores-userId case the adapter's tripwire exists for)

Control (loopback only, like everything else here): `POST /__mock/mode/<mode>`,
`POST /__mock/reset` (clears the request log), `GET /__mock/requests` (count and paths).
A request without the expected token gets 401, so the credential path is exercised too.

    python dev/mock_jellyfin.py --port 18096 --mode ok
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

try:
    from dev.synthetic_art import JELLYFIN_SHAPE, cover
except ImportError:                        # run as a script: dev/ itself is on the path
    from synthetic_art import JELLYFIN_SHAPE, cover

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "jellyfin"
QC_WAITING = "123456"                        # the code a synthetic TV is showing
QC_USED = "111111"                           # a code that was already approved
MOCK_KEY = "mock-api-key-not-real"
MODES = ("ok", "slow", "down", "500", "malformed", "wrong-user")
LOOPBACK = ("127.0.0.1", "::1")


def _fixture(name):
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if not str(doc.get("_synthetic", "")).startswith("Hand-written SYNTHETIC"):
        raise RuntimeError("fixture is not marked synthetic: " + name)
    return doc["response"]


def _hex(guid: str) -> str:
    return guid.replace("-", "").lower()


class MockJellyfin:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, mode: str = "ok",
                 slow_seconds: float = 5.0, api_key: str = MOCK_KEY):
        if host not in LOOPBACK:
            raise ValueError("the mock Jellyfin binds to loopback only")
        self._lock = threading.Lock()
        self._mode = "ok"
        self.set_mode(mode)
        self.slow_seconds = slow_seconds
        self.api_key = api_key
        self.requests = []                   # (method, path, userId-or-None)
        # Quick Connect (SYNTHETIC): a TV waiting with QC_WAITING; QC_USED is "already authorized" (Jellyfin's 500).
        self.quick_connect_on = True
        self.approvals = []                  # (code, userId) of every approval the mock accepted
        self.users = _fixture("users.json")
        self._by_id = {_hex(u["Id"]): u["Name"] for u in self.users}
        self._by_name = {u["Name"]: _hex(u["Id"]) for u in self.users}
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "mock-jellyfin"

            def log_message(self, *a):          # keep the console free of request detail
                pass

            def do_GET(self):
                mock._handle(self)

            def do_POST(self):
                mock._handle(self)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 64
            address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET

            def server_bind(self):           # no reverse DNS (HTTPServer would call getfqdn)
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = host, self.server_address[1]

        self.httpd = Server((host, port), Handler)
        self.host, self.port = host, self.httpd.server_address[1]
        self._thread = None

    # ---- lifecycle ---------------------------------------------------------------------------
    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    def start(self) -> "MockJellyfin":
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ---- state -------------------------------------------------------------------------------
    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError("unknown mode")
        with self._lock:
            self._mode = mode

    def reset(self) -> None:
        with self._lock:
            self.requests = []
            self.approvals = []

    def paths(self):
        with self._lock:
            return [p for _m, p, _u in self.requests]

    # ---- request handling --------------------------------------------------------------------
    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(h.path)
        path, query = parts.path, dict(parse_qsl(parts.query))
        if path.startswith("/__mock/"):
            return self._control(h, path)
        with self._lock:
            self.requests.append((h.command, path, query.get("userId")))
        auth = h.headers.get("Authorization", "")
        if self.api_key not in auth:
            return self._send(h, 401, b"{}")
        if path.startswith("/QuickConnect/"):
            return self._quick_connect(h, path, query)
        if h.command != "GET":
            return self._send(h, 405, b"{}")
        mode = self.mode
        if mode == "down":
            try:
                h.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        if mode == "slow":
            time.sleep(self.slow_seconds)
        if mode == "500":
            return self._send(h, 500, b"{}")
        if mode == "malformed":
            return self._send(h, 200, b'{"Items": [{"Id": "aaaa')
        self._answer(h, path, query, wrong_user=(mode == "wrong-user"))

    def _quick_connect(self, h, path, query):
        """The two Quick Connect routes Home uses (quickconnect.py), shaped like Jellyfin 10.11. SYNTHETIC."""
        if h.command == "GET" and path == "/QuickConnect/Enabled":
            return self._send(h, 200, b"true" if self.quick_connect_on else b"false")
        if h.command == "POST" and path == "/QuickConnect/Authorize":
            if not self.quick_connect_on:
                return self._send(h, 401, b"{}")
            code = query.get("code", "")
            if code == QC_USED:
                return self._send(h, 500, b"{}")
            if code != QC_WAITING:
                return self._send(h, 404, b"{}")
            with self._lock:
                self.approvals.append((code, query.get("userId")))
            return self._send(h, 200, b"true")
        return self._send(h, 405, b"{}")

    def _control(self, h, path):
        if h.command == "GET" and path == "/__mock/requests":
            with self._lock:
                body = {"count": len(self.requests), "paths": [p for _m, p, _u in self.requests],
                        "mode": self._mode}
            return self._send(h, 200, json.dumps(body).encode())
        if h.command == "POST" and path.startswith("/__mock/mode/"):
            try:
                self.set_mode(path.rsplit("/", 1)[1])
            except ValueError:
                return self._send(h, 400, b"{}")
            return self._send(h, 200, json.dumps({"mode": self.mode}).encode())
        if h.command == "POST" and path == "/__mock/reset":
            self.reset()
            return self._send(h, 200, b"{}")
        return self._send(h, 404, b"{}")

    def _name_for(self, user_id: str):
        name = self._by_id.get(_hex(user_id or ""))
        return name.replace("-", "_").lower() if name else None

    def _per_user(self, kind: str, name):
        try:
            return _fixture(f"{kind}_{name}.json")
        except (FileNotFoundError, TypeError):
            return {"Items": [], "TotalRecordCount": 0} if kind in ("resume", "nextup") else []

    def _types(self):
        """Every synthetic item's Type by id, across all members' fixtures (for the cover's shape only)."""
        out = {}
        for f in sorted(FIXTURES.glob("*.json")):
            if f.name.startswith(("resume_", "latest_", "nextup_")):
                doc = _fixture(f.name)
                for i in (doc.get("Items", []) if isinstance(doc, dict) else doc):
                    if isinstance(i, dict) and "Id" in i:
                        out[_hex(i["Id"])] = i.get("Type", "")
        return out

    def _visible(self, name):
        resume = self._per_user("resume", name)["Items"]
        latest = self._per_user("latest", name)
        next_up = self._per_user("nextup", name)["Items"]
        return {_hex(i["Id"]): i for i in resume + latest + next_up if "Id" in i}

    def _answer(self, h, path, query, wrong_user):
        uid = _hex(query.get("userId", ""))
        name = self._name_for(uid)
        if path == "/Users":
            return self._json(h, self.users)
        if path == "/Items" and "searchTerm" in query:      # user-scoped search through userId (SYNTHETIC)
            term = query.get("searchTerm", "").casefold()
            kinds = set(query.get("includeItemTypes", "").split(","))
            found = [i for i in self._visible(name).values()
                     if term and term in str(i.get("Name", "")).casefold() and i.get("Type") in kinds]
            found = found[:int(query.get("limit", "50"))]
            return self._json(h, {"Items": found, "TotalRecordCount": len(found)})
        if path == "/UserItems/Resume":
            if wrong_user and name in ("member_a", "member_b"):
                other = "member_b" if name == "member_a" else "member_a"
                body = copy.deepcopy(self._per_user("resume", other))
                other_id = self._by_name[other.replace("_", "-")]
                for item in body["Items"]:
                    item.setdefault("UserData", {})["UserId"] = other_id
                return self._json(h, body)
            return self._json(h, _dated(self._per_user("resume", name), "LastPlayedDate", (1, 3, 9)))
        if path == "/Items/Latest":
            return self._json(h, self._per_user("latest", name))
        if path == "/Shows/NextUp":
            # Continue's order and New for You (2026-10-28): the third Up next episode arrived yesterday (SYNTHETIC).
            return self._json(h, _dated(self._per_user("nextup", name), "DateCreated", (200, 200, 1, 200)))
        if path == "/Items" and "sortBy" in query:          # New releases: a premiere date per item (SYNTHETIC)
            kinds = set(query.get("includeItemTypes", "").split(","))
            today = datetime.date.today()
            found = [dict(i, PremiereDate=(today - datetime.timedelta(days=4 * n + 1)).isoformat() + "T00:00:00Z")
                     for n, i in enumerate(i for i in self._visible(name).values() if i.get("Type") in kinds)]
            found = found[:int(query.get("limit", "50"))]
            return self._json(h, {"Items": found, "TotalRecordCount": len(found)})
        if path == "/Items":
            vis = self._visible(name)
            found = [vis[i] for i in query.get("ids", "").split(",") if i in vis]
            return self._json(h, {"Items": found, "TotalRecordCount": len(found)})
        if path.startswith("/Items/") and path.endswith("/Images/Backdrop"):
            return self._send(h, 200, cover("still", path), "image/png")   # a wide synthetic backdrop
        if path.startswith("/Items/") and path.endswith("/Images/Primary"):
            # A real, decodable synthetic PNG in the item's natural shape (poster, or a still for an episode).
            item_id = path[len("/Items/"):-len("/Images/Primary")].lower()
            shape = JELLYFIN_SHAPE.get(self._types().get(item_id, ""), "poster")
            return self._send(h, 200, cover(shape, path), "image/png")
        return self._send(h, 404, b"{}")

    def _json(self, h, obj):
        self._send(h, 200, json.dumps(obj).encode("utf-8"))

    @staticmethod
    def _send(h, status, body, ctype="application/json"):
        try:
            h.send_response(status)
            h.send_header("Content-Type", ctype)
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            h.wfile.write(body)
        except OSError:                      # the client gave up (a timeout is the point of slow mode)
            pass


def _dated(body, field, days_ago):
    """A copy of a list body whose items carry a SYNTHETIC date `field` (LastPlayedDate in UserData, else on the item),
    n days ago in `days_ago` order, the last value repeated. Counted from the start of today (UTC), so two requests
    a moment apart see the same dates."""
    body = copy.deepcopy(body)
    now = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for n, item in enumerate(body.get("Items", [])):
        when = (now - datetime.timedelta(days=days_ago[min(n, len(days_ago) - 1)])).strftime("%Y-%m-%dT%H:%M:%SZ")
        (item.setdefault("UserData", {}) if field == "LastPlayedDate" else item)[field] = when
    return body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18096)
    ap.add_argument("--mode", default="ok", choices=MODES)
    ap.add_argument("--slow-seconds", type=float, default=5.0)
    args = ap.parse_args()
    mock = MockJellyfin(args.host, args.port, args.mode, args.slow_seconds)
    print(f"mock Jellyfin on {mock.url} (mode {mock.mode}); Ctrl+C to stop", flush=True)
    try:
        mock.httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
