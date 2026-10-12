"""Tier B: health, response hygiene on every response, redirects, and the log contract."""
import logging
import re
import time
import unittest

from avrana_home.app.logsafe import ForbiddenValues
from avrana_home.app.middleware import CSP
from dev.mock_jellyfin import MockJellyfin

from .support import (GROUPS, IDENTITIES, USER, RealServer, StubAdapter, ident_headers, make_client,
                      make_settings, require_framework)

require_framework()

A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos"), ("X-authentik-email", "member-a@example.test"),
     ("X-authentik-name", "Member A")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-books")]
HYGIENE = {"cache-control": "no-store", "referrer-policy": "no-referrer",
           "x-content-type-options": "nosniff", "content-security-policy": CSP.decode()}


def add_test_routes(app):
    """Routes that exist only in tests: one raising, one with a validated parameter (422)."""
    from fastapi.routing import APIRoute
    from starlette.routing import Route

    async def boom(request):
        raise RuntimeError("member-a@example.test watched Synthetic Film One via mock-api-key-not-real")

    async def needs_int(n: int):
        return {"n": n}

    app.router.routes.insert(0, Route("/__boom", boom))
    app.router.routes.insert(0, APIRoute("/__t422", needs_int, methods=["GET"]))


class HealthTests(unittest.TestCase):
    def test_healthz_makes_no_upstream_call_and_carries_no_member_data(self):
        stub = StubAdapter({"member-a": [("a" * 32, "Synthetic Film One", 0.5)]})
        client = make_client(make_settings(home_sections=True), adapters=[stub])
        for headers in ([], A, B):
            for target in ("/healthz", "/healthz/", "/healthz?x=1"):
                r = client.get(target, headers=headers)
                self.assertEqual(200, r.status_code)
                self.assertEqual("ok", r.text)
                self.assertTrue(r.headers["content-type"].startswith("text/plain"))
        self.assertEqual(0, stub.calls)
        head = client.head("/healthz")
        self.assertEqual((200, b""), (head.status_code, head.content))

    def test_healthz_is_fast_and_unaffected_when_the_upstream_is_dead(self):
        mock = MockJellyfin(mode="down").start()
        client = make_client(make_settings(home_sections=True, jellyfin_base_url=mock.url, timeout=1.0))
        for _ in range(3):
            client.get("/", headers=A)                    # open the circuit
        mock.reset()
        started = time.monotonic()
        self.assertEqual(200, client.get("/healthz").status_code)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual([], mock.paths())
        mock.stop()

    def test_readyz_detail_is_hidden_from_everyone_arriving_through_the_outpost_path(self):
        client = make_client(make_settings(home_sections=True))          # peer 203.0.113.7
        unknown = client.get("/definitely-not-a-route", headers=A)
        for headers in ([], A, B):
            r = client.get("/readyz", headers=headers)
            self.assertEqual(404, r.status_code)
            self.assertEqual(unknown.content, r.content)

    def test_readyz_loopback_peer_gets_per_adapter_state_only(self):
        mock = MockJellyfin(mode="500").start()
        client = make_client(make_settings(home_sections=True, jellyfin_base_url=mock.url, timeout=0.5),
                             peer=("127.0.0.1", 40000))
        self.assertEqual("unknown", client.get("/readyz").json()["adapters"][0]["state"])
        for _ in range(3):
            client.get("/", headers=A)
        doc = client.get("/readyz").json()
        self.assertEqual({"home", "libraries", "adapters"}, set(doc))
        self.assertEqual("degraded", doc["libraries"])
        row = doc["adapters"][0]
        self.assertEqual({"service", "state", "last_error_class", "retry_in_seconds"}, set(row))
        self.assertEqual(("jellyfin", "cooling_off"), (row["service"], row["state"]))
        text = client.get("/readyz").text
        for forbidden in ("member-a", "Synthetic", "127.0.0.1", "mock-api-key"):
            self.assertNotIn(forbidden, text)
        mock.stop()

    def test_readyz_refuses_a_loopback_peer_that_carries_identity_or_forwarding_headers(self):
        client = make_client(make_settings(home_sections=True), peer=("127.0.0.1", 40000))
        self.assertEqual(200, client.get("/readyz").status_code)
        for extra in (A, [("X-authentik-username", "member-a")], [("X_authentik_groups", "x")],
                      [("X-Forwarded-For", "127.0.0.1")], [("Forwarded", "for=127.0.0.1")]):
            self.assertEqual(404, client.get("/readyz", headers=extra).status_code, extra)

    def test_readyz_can_be_turned_off(self):
        client = make_client(make_settings(health_detail="off"), peer=("127.0.0.1", 40000))
        self.assertEqual(404, client.get("/readyz").status_code)

    def test_readyz_over_a_real_socket(self):
        client = make_client(make_settings(home_sections=True))
        with RealServer(client.fastapi_app) as srv:
            r = srv.get("/readyz")
            self.assertEqual(200, r.status)
            self.assertIn('"adapters"', r.text)
            self.assertEqual(404, srv.get("/readyz", [("X-authentik-username", "member-a")]).status)
            # a client cannot claim to be loopback by header: proxy headers are not honoured
            self.assertEqual(404, srv.get("/readyz", [("X-Forwarded-For", "10.9.9.9")]).status)


class HygieneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = make_client(make_settings(home_sections=False))
        add_test_routes(cls.client.fastapi_app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def check(self, r, label):
        for name, value in HYGIENE.items():
            self.assertEqual([value], r.headers.get_list(name), f"{label}: {name}")

    def test_every_matrix_response_including_errors(self):
        cases = [("GET", "/"), ("GET", "/account"), ("GET", "/help"), ("GET", "/help/movies"),
                 ("GET", "/watch"), ("GET", "/ops"), ("GET", "/read"), ("GET", "/healthz"),
                 ("GET", "/nope"), ("GET", "/readyz"), ("GET", "/home.json"), ("HEAD", "/"),
                 ("HEAD", "/watch"), ("HEAD", "/nope"), ("POST", "/"), ("PUT", "/watch"), ("DELETE", "/ops"),
                 ("OPTIONS", "/"), ("PATCH", "/x"), ("TRACE", "/"), ("FOO", "/"),
                 ("GET", "/__t422"), ("GET", "/__t422?n=abc"), ("GET", "/__boom")]
        for ident in IDENTITIES:
            for method, path in cases:
                with self.subTest(ident=ident, method=method, path=path):
                    r = self.client.request(method, path, headers=ident_headers(ident, "member-a"))
                    self.check(r, f"{method} {path}")

    def test_framework_generated_errors_are_covered_and_generic(self):
        r = self.client.get("/__t422")
        self.assertEqual(422, r.status_code)
        self.assertIn("Something went wrong", r.text)
        self.assertNotIn("Field required", r.text)             # no validation detail
        r = self.client.get("/__boom")
        self.assertEqual(500, r.status_code)
        self.assertIn("Something went wrong", r.text)
        for leaked in ("member-a", "Synthetic", "mock-api-key", "RuntimeError", "Traceback"):
            self.assertNotIn(leaked, r.text)

    def test_unsupported_methods_are_501_for_every_path_and_identity(self):
        seen = set()
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "FOO"):
            for path in ("/", "/ops", "/nope", "/healthz", "/readyz", "/__boom"):
                for ident in ("no_header", "admin_and_all"):
                    r = self.client.request(method, path, headers=ident_headers(ident, "member-a"))
                    self.assertEqual(501, r.status_code)
                    self.assertNotIn("location", r.headers)
                    seen.add(r.text)
        self.assertEqual(1, len(seen))
        self.assertNotIn("FOO", next(iter(seen)))                 # the method is not echoed

    def test_csp_has_no_script_source_and_pages_have_no_script_or_inline_handlers(self):
        csp = HYGIENE["content-security-policy"]
        self.assertIn("default-src 'none'", csp)
        for bad in ("script-src", "unsafe-eval", "unsafe-inline'", "*", "data:", "http:"):
            if bad == "unsafe-inline'":
                self.assertEqual(1, csp.count("unsafe-inline"))          # style only
                self.assertIn("style-src 'unsafe-inline'", csp)
                continue
            self.assertNotIn(bad, csp)
        for ident in IDENTITIES:
            for path in ("/", "/account", "/help", "/help/movies", "/help/audiobooks", "/read", "/request",
                         "/watch", "/nope"):
                text = self.client.get(path, headers=ident_headers(ident, "member-a")).text
                self.assertNotRegex(text, r"(?i)<script|javascript:|\son[a-z]+\s*=|<iframe|<object|<embed|<form")

    def test_redirect_targets_are_a_fixed_table_whatever_the_request_says(self):
        allowed = self.client.fastapi_app.state.catalogue.all_redirect_targets()
        hosts = ["evil.example", "watch.avrana.net@evil.example", "evil.example:80", "avrana.net"]
        extras = [[], [("X-Forwarded-Host", "evil.example")], [("X-Forwarded-Proto", "http")],
                  [("X-Original-URL", "https://evil.example/")], [("Referer", "https://evil.example/")],
                  [("Forwarded", "host=evil.example;proto=https")], [("Origin", "https://evil.example")]]
        targets = ["/watch", "/listen", "/comics", "/books", "/kindle", "/requests", "/requestabook",
                   "/requestacomic", "/contribute", "/ops", "/ops?next=https://evil.example",
                   "/comics?continue=//evil.example", "//listen", "/listen/", "/listen//"]
        ident = ident_headers("admin_and_all", "member-a")
        for host in hosts:
            for extra in extras:
                for target in targets:
                    r = self.client.get(target, headers=ident + extra + [("Host", host)])
                    if r.status_code == 307:
                        self.assertIn(r.headers["location"], allowed, (host, extra, target))
                        self.assertNotIn("evil", r.headers["location"])
                    else:
                        self.assertNotIn("location", r.headers)
                    self.assertNotIn("evil.example", r.text)

    def test_hostile_paths_never_become_a_redirect(self):
        ident = ident_headers("admin_and_all", "member-a")
        for target in ("//evil.example", "/%2f%2fevil.example", "/watch/%2e%2e/ops", "/\\evil.example",
                       "/watch@evil.example", "/https://evil.example", "/watch;https://evil.example"):
            r = self.client.get(target, headers=ident)
            self.assertIn(r.status_code, (200, 307, 404), target)
            self.assertNotIn("evil", r.headers.get("location", ""))


class LogContractTests(unittest.TestCase):
    """Capture EVERY log record (message, args, exc_info, extra) across a request matrix and
    assert none contains an identity, a title, an id, a key, an upstream address or a query."""

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.records = []

        def emit(self, record):
            if not record.name.startswith(("httpx", "httpcore")):       # the TEST CLIENT's own logs
                self.records.append(record)

    @classmethod
    def setUpClass(cls):
        cls.cap = cls.Capture()
        cls.root = logging.getLogger()
        cls.prev_level = cls.root.level
        cls.root.addHandler(cls.cap)
        cls.root.setLevel(logging.DEBUG)

    @classmethod
    def tearDownClass(cls):
        cls.root.removeHandler(cls.cap)
        cls.root.setLevel(cls.prev_level)

    def test_no_identity_title_key_address_or_query_in_any_record(self):
        self.cap.records.clear()
        mock = MockJellyfin(slow_seconds=1.0).start()
        forbidden = ["member-a", "member-b", "member-c", "member-d", "member-nolib", "@example.test",
                     "Member A", "avrana-videos", "avrana-books", "avrana-users", "authentik Admins",
                     "Synthetic Film", "Synthetic Pilot", "Synthetic Series", "Synthetic Documentary",
                     "aaaa0000", "bbbb0000", "cccc0000", "mock-api-key", "MediaBrowser", "Bearer",
                     f"127.0.0.1:{mock.port}", "SECRETQ", "SECRETPATHID", "boom-message-marker"]
        scan = ForbiddenValues(forbidden)
        hostile = StubAdapter({"member-a": [("a" * 32, "Synthetic Film Hostile <script>", 0.4)]})
        try:
            idents = [A, B, [], [(USER, "member-nolib"), (GROUPS, "avrana-users|avrana-comics")],
                      [(USER, "member-c"), (GROUPS, "avrana-users|avrana-videos")],
                      [(USER, "member-d"), (GROUPS, "avrana-users|avrana-videos")],
                      [(USER, "member-a"), (USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]]
            paths = ["/", "/home.json", "/account", "/help", "/help/movies", "/watch?token=SECRETQ", "/read",
                     "/request", "/ops", "/nope?SECRETQ=1", "/SECRETPATHID", "/healthz", "/readyz",
                     "/__boom", "/__t422?n=SECRETQ", "/comics?userId=SECRETQ"]
            for mode in ("ok", "500", "malformed", "down", "slow", "wrong-user"):
                mock.set_mode(mode)            # a fresh app per mode: a warm cache would hide the failure
                clients = [make_client(make_settings(home_sections=True, jellyfin_base_url=mock.url,
                                                     timeout=0.4)),
                           make_client(make_settings(home_sections=True), adapters=[hostile]),
                           make_client(make_settings(home_sections=False))]
                add_test_routes(clients[0].fastapi_app)
                for client in clients:
                    client.__enter__()
                    for headers in idents:
                        for path in paths:
                            client.get(path, headers=headers)
                    client.post("/?SECRETQ=1", headers=A, content=b"user=member-a")
                    client.__exit__(None, None, None)
        finally:
            mock.stop()
        self.assertGreater(len(self.cap.records), 100)
        hits = [(r.name, r.getMessage()[:80], scan.scan(r)) for r in self.cap.records if scan.scan(r)]
        self.assertEqual([], hits[:5])
        # not vacuous: the structured fields are really there
        fields = [getattr(r, "avrana_fields") for r in self.cap.records if hasattr(r, "avrana_fields")]
        routes = {f.get("route") for f in fields if "route" in f}
        self.assertLessEqual({"/", "/account", "/help", "/help/{slug}", "/{service}", "/{chooser}", "not_found",
                              "/home.json", "/healthz", "method_not_supported"}, routes)
        for f in fields:
            self.assertLessEqual(set(f), {"route", "method", "status", "duration_ms", "service", "section",
                                          "state", "reason", "error_class", "count"})
        sections = [f for f in fields if "section" in f]
        self.assertTrue(sections)
        self.assertTrue(any(f.get("state") == "unavailable" and f.get("service") == "jellyfin" for f in sections))
        requests = [f for f in fields if "duration_ms" in f]
        self.assertTrue(all(isinstance(f["status"], int) and f["status"] > 0 for f in requests))
        errors = [f for f in fields if f.get("error_class")]
        self.assertTrue(any(f["error_class"] == "RuntimeError" for f in errors))     # class only

    def test_real_server_with_uvicorn_access_log_requested_logs_no_query_string(self):
        self.cap.records.clear()
        client = make_client(make_settings())
        with RealServer(client.fastapi_app, access_log=True) as srv:
            srv.get("/watch?token=SECRETQ", A)
            srv.get("/?userId=SECRETQ&x=SECRETQ", A)
        blob = "\n".join(f"{r.name} {r.getMessage()} {vars(r)}" for r in self.cap.records)
        self.assertNotIn("SECRETQ", blob)
        self.assertEqual([], [r for r in self.cap.records if r.name == "uvicorn.access"])
        self.assertTrue([r for r in self.cap.records if getattr(r, "avrana_fields", {}).get("route") == "/{service}"])


if __name__ == "__main__":
    unittest.main()
