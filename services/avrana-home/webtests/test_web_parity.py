"""Portal parity (Tier B): the new application against services/avrana-portal/portal.py.

For every fixture identity and every route, the stdlib portal (in memory) and the new app
(Starlette test client) must give the same status, the same Location and, after the documented
normalisation (whitespace, and the &#39;/&#x27; entity spelling), the same body.

Identities whose headers do not form a valid principal (no groups header, empty groups header)
are compared with the portal given NO identity headers at all: that is the documented, stricter
behaviour (HOME-APP.md, "Differences from today's portal"). When this test fails after the
portal changes, the templates in avrana_home/app/templates must be updated to match.
"""
import unittest

from .support import (IDENTITIES, ident_headers, make_client, normalise, portal_request,
                      require_framework, valid_principal_identity)

require_framework()

HELP_SLUGS = ["audiobooks", "movies", "books", "comics", "requests"]
SERVICE_PATHS = ["watch", "listen", "comics", "books", "kindle", "requests", "requestabook",
                 "requestacomic", "contribute", "ops"]
UNKNOWN = ["/nope", "/admin", "/ops/x", "/help/nope", "/help/movies/extra", "/index.html",
           "/favicon.ico", "/outpost.goauthentik.io/sign_out", "/read/comics", "/static",
           "/help/Movies", "/WATCH", "/Watch", "/Ops", "/readyz", "/home.json", "/metrics",
           "/docs", "/openapi.json", "/redoc", "/me"]   # /me: the Me hub exists only with the shell (AVR-719)
ROUTES = (["/", "/account", "/help", "/healthz"] + [f"/help/{s}" for s in HELP_SLUGS]
          + ["/read", "/request"] + [f"/{p}" for p in SERVICE_PATHS] + UNKNOWN)
VARIANTS = ["/watch/", "/watch?q=1", "/watch/?q=1", "/watch//", "/?q=1", "//", "/help/",
            "/help/movies/", "/account/", "/read?x=1", "/healthz/", "/ops?next=https://evil.example"]


def expected_for(ident, route, method="GET"):
    """The portal's answer. An invalid principal is compared with an identity-free request."""
    headers = ident_headers(ident, "member-a") if valid_principal_identity(ident) else []
    return portal_request(route, headers, method)


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = make_client()
        cls.client.__enter__()          # one portal/event loop for the whole class (speed only)

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def app_get(self, ident, route, method="GET"):
        headers = ident_headers(ident, "member-a")
        return self.client.request(method, route, headers=headers)

    def compare(self, ident, route):
        want = expected_for(ident, route)
        got = self.app_get(ident, route)
        self.assertEqual(want.status, got.status_code, (ident, route))
        self.assertEqual(want.location, got.headers.get("location"), (ident, route))
        self.assertEqual(want.header("Content-Type"), got.headers.get("content-type"), (ident, route))
        self.assertEqual(normalise(want.text), normalise(got.text), (ident, route))

    def test_every_route_for_every_identity(self):
        for ident in IDENTITIES:
            for route in ROUTES + VARIANTS:
                with self.subTest(ident=ident, route=route):
                    self.compare(ident, route)

    def test_head_matches_get(self):
        for ident in ("no_header", "videos", "all_members", "admin_only"):
            for route in ROUTES + VARIANTS:
                with self.subTest(ident=ident, route=route):
                    want = expected_for(ident, route, "HEAD")
                    g = self.app_get(ident, route)
                    h = self.app_get(ident, route, "HEAD")
                    self.assertEqual(want.status, h.status_code)
                    self.assertEqual(want.location, h.headers.get("location"))
                    self.assertEqual(b"", h.content)
                    self.assertEqual(g.status_code, h.status_code)
                    self.assertEqual(g.headers.get("content-length"), h.headers.get("content-length"))

    def test_only_documented_statuses(self):
        for ident in IDENTITIES:
            for route in ROUTES:
                with self.subTest(ident=ident, route=route):
                    self.assertIn(self.app_get(ident, route).status_code, (200, 307, 404))

    def test_unsupported_methods_are_501_with_hygiene_for_every_identity(self):
        """Portal: http.server answers 501 before any routing. Same status and headers here; the
        body is fixed text that does not echo the method (documented difference)."""
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "FOO", "PROPFIND"):
            for route in ("/", "/ops", "/watch", "/account", "/nope", "/healthz", "/home.json"):
                bodies = set()
                for ident in ("no_header", "admin_and_all"):
                    r = self.app_get(ident, route, method)
                    with self.subTest(method=method, route=route, ident=ident):
                        self.assertEqual(501, r.status_code)
                        self.assertIsNone(r.headers.get("location"))
                        for name in ("cache-control", "referrer-policy", "x-content-type-options",
                                     "content-security-policy"):
                            self.assertIn(name, r.headers)
                        bodies.add(r.text)
                self.assertEqual(1, len(bodies), "501 body must not depend on identity or path")

    def test_portal_501_status_is_what_we_compare_with(self):
        self.assertEqual(501, portal_request("/", [], "POST").status)


if __name__ == "__main__":
    unittest.main()
