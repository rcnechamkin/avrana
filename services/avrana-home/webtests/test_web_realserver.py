"""Tier B: behaviour only a real server shows. The same bytes go to the stdlib portal (in memory)
and to the application running under uvicorn on an ephemeral loopback port."""
import concurrent.futures
import re
import socket
import unittest

from .support import (GROUPS, IDENTITIES, USER, RealServer, ident_headers, make_client, make_settings,
                      normalise, portal_raw, require_framework, valid_principal_identity, wire)

require_framework()

from avrana_home.app import identity, logsafe, main, middleware, routing, viewmodel  # noqa: E402

ODD_TARGETS = [
    "/", "/watch", "/watch/", "/watch//", "/watch?x=1", "/watch?next=https://evil.example",
    "/watch#frag", "/books#https://evil.example", "//watch", "///watch", "//listen", "//", "/?q=1",
    "/%77atch", "/watch%2f", "/watch%00", "/wat%63h", "/WATCH", "/watch;x", "/watch/.", "/watch/../watch",
    "/./watch", "/watch%20", "/help/%6dovies", "/ac%63ount", "/help/", "/help/movies/", "/account/",
    "//evil.example", "///evil.example", "/%2f%2fevil.example", "/requests/../ops", "/watch\\evil.example",
    "/https://evil.example", "http://evil.example/watch", "/.evil.example", "/@evil.example", "/;evil.example",
    "/healthz/", "/healthz?x=1", "/home.json", "/<script>alert(1)</script>", "/%3Cscript%3E",
]
IDENTS = ["no_header", "books", "videos", "all_members", "admin_and_all"]


class WireParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = RealServer(make_client(make_settings()).fastapi_app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_odd_targets_decide_the_same_as_the_portal(self):
        for ident in IDENTS:
            headers = ident_headers(ident, "member-a") if valid_principal_identity(ident) else []
            for target in ODD_TARGETS:
                with self.subTest(ident=ident, target=target):
                    want = portal_raw(wire(target, headers))
                    got = self.server.exchange(wire(target, headers, host="127.0.0.1"))
                    if want.status >= 400 and want.status != 404:
                        # the portal's own http.server refused the request line; so may uvicorn
                        self.assertIn(got.status, (400, 404, -1, want.status))
                        self.assertNotIn('class="tile"', got.text)
                        continue
                    self.assertEqual(want.status, got.status)
                    self.assertEqual(want.location, got.location)
                    if want.status != 307:
                        self.assertEqual(normalise(want.text), normalise(got.text))

    def test_head_over_the_wire_has_no_body_and_the_same_length_as_get(self):
        for target in ("/", "/watch", "/account", "/nope", "/healthz"):
            h = ident_headers("all_members", "member-a")
            g = self.server.exchange(wire(target, h, "GET", "127.0.0.1"))
            hd = self.server.exchange(wire(target, h, "HEAD", "127.0.0.1"))
            self.assertEqual((g.status, g.location), (hd.status, hd.location))
            self.assertEqual(b"", hd.body)
            self.assertEqual(g.header("Content-Length"), hd.header("Content-Length"))

    def test_unsupported_methods_over_the_wire(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "FOO", "get", "PROPFIND"):
            for target in ("/", "/ops", "/nope", "/healthz"):
                r = self.server.exchange(wire(target, ident_headers("admin_and_all", "member-a"), method, "127.0.0.1"))
                with self.subTest(method=method, target=target):
                    self.assertEqual(501, r.status)
                    for name in ("Cache-Control", "Referrer-Policy", "X-Content-Type-Options",
                                 "Content-Security-Policy"):
                        self.assertEqual(1, len(r.all(name)), name)

    def test_post_with_a_body_changes_nothing(self):
        body = b"groups=authentik+Admins"
        raw = (b"POST /ops HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nContent-Length: "
               + str(len(body)).encode() + b"\r\n\r\n" + body)
        self.assertEqual(501, self.server.exchange(raw).status)
        self.assertEqual(404, self.server.get("/ops", ident_headers("no_header")).status)


class ConnectionReuseTests(unittest.TestCase):
    """The portal pins HTTP/1.0 so a connection never carries two identities. uvicorn keeps
    connections alive, so the application must (and does) read identity per request only."""

    @classmethod
    def setUpClass(cls):
        cls.server = RealServer(make_client(make_settings()).fastapi_app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_two_identities_on_one_keep_alive_connection_never_mix(self):
        def req(user, groups, last=False):
            return (f"GET /account HTTP/1.1\r\nHost: 127.0.0.1\r\n{USER}: {user}\r\n{GROUPS}: {groups}\r\n"
                    + ("Connection: close\r\n" if last else "") + "\r\n").encode()

        with socket.create_connection(("127.0.0.1", self.server.port), timeout=10) as s:
            s.sendall(req("member-a", "avrana-users|avrana-videos"))
            first = self._read_one(s)
            s.sendall(req("member-b", "avrana-users|avrana-books"))
            second = self._read_one(s)
            s.sendall(req("member-a", "avrana-users", last=True))
            third = self._read_one(s)
        self.assertIn("<dd>member-a</dd>", first)
        self.assertIn("Watch", first.split("Your access")[1])
        self.assertIn("<dd>member-b</dd>", second)
        self.assertNotIn("member-a", second)
        self.assertNotIn("Movies", second)
        self.assertIn("<dd>member-a</dd>", third)
        self.assertNotIn("Movies", third.split("Your access")[1])

    def test_pipelined_requests_each_get_their_own_identity(self):
        wire_bytes = (
            f"GET /account HTTP/1.1\r\nHost: x\r\n{USER}: member-a\r\n{GROUPS}: avrana-users\r\n\r\n"
            f"GET /account HTTP/1.1\r\nHost: x\r\n{USER}: member-b\r\n{GROUPS}: avrana-users\r\nConnection: close\r\n\r\n"
        ).encode()
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=10) as s:
            s.sendall(wire_bytes)
            chunks = []
            while True:
                d = s.recv(65536)
                if not d:
                    break
                chunks.append(d)
        text = b"".join(chunks).decode("utf-8", "replace")
        self.assertEqual(2, text.count("HTTP/1.1 200"))
        self.assertLess(text.index("<dd>member-a</dd>"), text.index("<dd>member-b</dd>"))
        self.assertEqual(1, text.count("<dd>member-a</dd>"))
        self.assertEqual(1, text.count("<dd>member-b</dd>"))

    @staticmethod
    def _read_one(sock):
        data = b""
        while b"\r\n\r\n" not in data:
            data += sock.recv(65536)
        head, _, body = data.partition(b"\r\n\r\n")
        length = int(re.search(rb"(?i)content-length: (\d+)", head).group(1))
        while len(body) < length:
            body += sock.recv(65536)
        return body.decode("utf-8")

    def test_concurrent_connections_never_cross_identities(self):
        def fetch(i):
            name = f"member-{'ab'[i % 2]}-{i}"
            r = self.server.get("/account", [(USER, name), (GROUPS, "avrana-users")])
            return name, r.text

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for name, text in pool.map(fetch, range(40)):
                self.assertIn(f"<dd>{name}</dd>", text)
                self.assertEqual(1, len(re.findall(r"<dt>Username</dt><dd>([^<]*)</dd>", text)))


class ServerGeneratedErrorTests(unittest.TestCase):
    """Replies uvicorn itself produces before the application runs. Recorded, not hidden: they
    cannot carry the application's headers, and they contain no application data."""

    @classmethod
    def setUpClass(cls):
        cls.server = RealServer(make_client(make_settings()).fastapi_app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_malformed_requests_get_a_bare_server_error(self):
        # (An unknown HTTP version such as HTTP/9.9 is accepted by h11; the portal answers 505.
        # Documented in HOME-APP.md as a protocol-level difference with no security effect.)
        for raw in (b"GARBAGE\r\n\r\n", b"GET /\x00 HTTP/1.1\r\nHost: x\r\n\r\n", b"GET / HTTP/1.1\r\n\r\n"):
            r = self.server.exchange(raw)
            with self.subTest(raw=raw[:12]):
                self.assertIn(r.status, (-1, 0, 400, 505))
                self.assertNotIn("tile", r.text)
                self.assertNotIn("<!doctype", r.text.lower())


class FactoryTests(unittest.TestCase):
    def test_two_apps_share_nothing(self):
        a = make_client(make_settings(home_sections=True)).fastapi_app
        b = make_client(make_settings(home_sections=True)).fastapi_app
        self.assertIsNot(a.state.adapters[0], b.state.adapters[0])
        self.assertIsNot(a.state.adapters[0].cache, b.state.adapters[0].cache)
        self.assertIsNot(a.state.env, b.state.env)

    def test_sections_off_builds_no_adapter_and_no_transport(self):
        app = make_client(make_settings(home_sections=False)).fastapi_app
        self.assertEqual([], app.state.adapters)

    def test_modules_hold_no_mutable_module_level_state(self):
        import types
        for module in (main, identity, middleware, routing, viewmodel, logsafe):
            for name, value in vars(module).items():
                if name.startswith("__") or isinstance(value, (types.ModuleType, types.FunctionType, type)):
                    continue
                if isinstance(value, (dict, list, set, bytearray)):
                    self.assertTrue(name.isupper() or name.startswith("_"), f"{module.__name__}.{name}")
                    self.assertTrue(name.isupper(), f"{module.__name__}.{name} should be a constant")

    def test_invalid_catalogue_path_stops_creation(self):
        from avrana_home.app.catalogue import CatalogueError
        from pathlib import Path
        with self.assertRaises(CatalogueError):
            main.create_app(make_settings(catalogue_path=Path("/nonexistent/portal.py")))

    def test_importing_the_package_does_not_touch_uvicorn_logging(self):
        import importlib
        import logging
        logging.getLogger("uvicorn.access").disabled = False
        importlib.reload(main)
        self.assertFalse(logging.getLogger("uvicorn.access").disabled)


if __name__ == "__main__":
    unittest.main()
