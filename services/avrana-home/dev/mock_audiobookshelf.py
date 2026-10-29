#!/usr/bin/env python3
"""A mock Audiobookshelf on 127.0.0.1, serving the repository's SYNTHETIC fixtures. Standard library only.

Not Audiobookshelf and not recorded from one. It wraps `tests/fake_abs.FakeAudiobookshelf` (the adapter's
own hand-written fixtures; imported read-only) behind a loopback HTTP server so the real
`UrllibTransport` is exercised. Modes: ok, slow, down (connection dropped), 500, malformed.
Control (loopback only): `POST /__mock/mode/<mode>`, `POST /__mock/reset`, `GET /__mock/requests`.
A request without the expected bearer token gets 401.

    python dev/mock_audiobookshelf.py --port 18097 --mode ok
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))
from dev.synthetic_art import cover   # noqa: E402


def load_fake(filename: str, cls: str):
    """Load tests/<filename> BY PATH (read-only reuse of an adapter's fixtures). Importing it as
    `tests.<name>` would run tests/__init__.py, which installs the adapter suite's socket guard."""
    spec = importlib.util.spec_from_file_location("avrana_" + filename[:-3], HOME / "tests" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, cls)


FakeAudiobookshelf = load_fake("fake_abs.py", "FakeAudiobookshelf")

MOCK_KEY = "mock-api-key-not-real"
MODES = ("ok", "slow", "down", "500", "malformed")
LOOPBACK = ("127.0.0.1", "::1")


class MockAudiobookshelf:
    FAKE = staticmethod(lambda: FakeAudiobookshelf())     # subclasses swap in another service's fake
    MALFORMED = b'{"users": [{"id": "aaaa'
    NAME = "audiobookshelf"
    SHAPE = "square"          # the natural shape of this service's covers (dev/synthetic_art.py)

    def __init__(self, host: str = "127.0.0.1", port: int = 0, mode: str = "ok",
                 slow_seconds: float = 5.0, api_key: str = MOCK_KEY):
        if host not in LOOPBACK:
            raise ValueError("the mock Audiobookshelf binds to loopback only")
        self._lock = threading.Lock()
        self._mode = "ok"
        self.set_mode(mode)
        self.slow_seconds = slow_seconds
        self.api_key = api_key
        self.fake = self.FAKE()
        if self.NAME == "audiobookshelf":
            self._seed_new_for_you()
        # Answer the fake's stock cover with a real, decodable synthetic PNG in this service's natural shape. A
        # test that sets `fake.image` to something else gets exactly that; False serves the fake's own bytes.
        self.synthetic_covers = True
        self._stock_image = self.fake.image
        self.requests = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "mock-" + mock.NAME

            def log_message(self, *a):
                pass

            def do_GET(self):
                mock._handle(self)

            def do_POST(self):
                mock._handle(self)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 64
            address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET

            def server_bind(self):
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = host, self.server_address[1]

        self.httpd = Server((host, port), Handler)
        self.host, self.port = host, self.httpd.server_address[1]
        self._thread = None

    def _seed_new_for_you(self) -> None:
        """A demo series for member-a (lib_aaa): books 1 and 2 finished, book 3 added two days ago, so New for You
        shows "Synthetic Chronicle Book 3" locally (series filter and expanded series: fake_abs, UNVERIFIED shapes)."""
        fake = self.fake
        fake.add_series("lib_aaa", "ser_chronicle01", "Synthetic Chronicle",
                        [("li_chron000001", 1, 120), ("li_chron000002", 2, 60), ("li_chron000003", 3, 2)])
        for n in (1, 2):
            fake.set_progress("aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa", f"li_chron00000{n}", 1.0, finished=True)

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    def start(self) -> "MockAudiobookshelf":
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

    def paths(self):
        with self._lock:
            return [p for _m, p in self.requests]

    @staticmethod
    def _send(h, status: int, body: bytes, ctype: str = "application/json") -> None:
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(h.path)
        path, query = parts.path, dict(parse_qsl(parts.query))
        if path.startswith("/__mock/"):
            if h.command == "GET" and path == "/__mock/requests":
                with self._lock:
                    body = {"count": len(self.requests), "paths": [p for _m, p in self.requests],
                            "mode": self._mode}
                return self._send(h, 200, json.dumps(body).encode())
            if h.command == "POST" and path.startswith("/__mock/mode/"):
                try:
                    self.set_mode(path.rsplit("/", 1)[1])
                except ValueError:
                    return self._send(h, 400, b"{}")
                return self._send(h, 200, b"{}")
            if h.command == "POST" and path == "/__mock/reset":
                self.reset()
                return self._send(h, 200, b"{}")
            return self._send(h, 404, b"{}")
        with self._lock:
            self.requests.append((h.command, path))
        if self.api_key not in (h.headers.get("Authorization", "") + h.headers.get("X-API-Key", "")):
            return self._send(h, 401, b"{}")
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
            return self._send(h, 200, self.MALFORMED)
        status, body, ctype = self.fake.handle("GET", path, query)
        if self.synthetic_covers and self.fake.image is self._stock_image and status == 200 \
                and body == self._stock_image[1]:
            body, ctype = cover(self.SHAPE, path), "image/png"
        self._send(h, status, body, ctype)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=18097)
    ap.add_argument("--mode", default="ok", choices=MODES)
    args = ap.parse_args(argv)
    with MockAudiobookshelf("127.0.0.1", args.port, args.mode) as mock:
        print(f"mock Audiobookshelf: {mock.url} (SYNTHETIC)", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
