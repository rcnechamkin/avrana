"""Tier B: the member-scoped artwork route `GET /art/<service>/<kind>/<id>` through the HTTP layer,
against the mock Jellyfin and mock Komga (loopback, SYNTHETIC fixtures, real UrllibTransport)."""
import unittest

from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from avrana_home.contract import ArtworkResult, SectionState
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

JF_A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
JF_B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]
NO_VIDEO = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-comics")]
KG_A = [(USER, "member-a@synthetic.invalid"), (GROUPS, "avrana-users|avrana-comics")]
KG_B = [(USER, "member-b@synthetic.invalid"), (GROUPS, "avrana-users|avrana-comics")]

A_ONLY_FILM = "/art/jellyfin/primary/aaaa0000000000000000000000000001"
B_ONLY_FILM = "/art/jellyfin/primary/bbbb0000000000000000000000000001"
ADULT_BOOK = "/art/komga/book/BOOKCCCC0004"       # age 18 + 'adult' label: member-a sees it, member-b not
COMIC_BOOK = "/art/komga/book/BOOKAAAA0001"
PNG = b"\x89PNG\r\n\x1a\n"


class Fixture(unittest.TestCase):
    timeout = 0.6

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.jf.stop()
        cls.kg.stop()

    def setUp(self):
        for mock in (self.jf, self.kg):
            mock.set_mode("ok")
            mock.reset()

    def client(self, **kw):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      komga_base_url=self.kg.url, komga_token="mock-api-key-not-real",
                                      timeout=self.timeout, **kw))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def assertStandard404(self, response):
        self.assertEqual(404, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertEqual(self.not_found, response.text)

    @property
    def not_found(self):
        if not hasattr(Fixture, "_nf"):
            Fixture._nf = self.client().get("/definitely-not-a-route", headers=JF_A).text
        return Fixture._nf


class ArtworkRouteTests(Fixture):
    def test_a_member_can_fetch_their_own_cover_with_safe_headers(self):
        c = self.client()
        for path, headers in ((A_ONLY_FILM, JF_A), (COMIC_BOOK, KG_A)):
            with self.subTest(path=path):
                r = c.get(path, headers=headers)
                self.assertEqual(200, r.status_code)
                self.assertEqual("image/png", r.headers["content-type"])
                self.assertTrue(r.content.startswith(PNG))
                self.assertEqual("private, no-store", r.headers["cache-control"])
                self.assertNotIn("public", r.headers["cache-control"])
                self.assertEqual("nosniff", r.headers["x-content-type-options"])
                self.assertEqual("no-referrer", r.headers["referrer-policy"])
                self.assertIn("img-src 'self'", r.headers["content-security-policy"])

    def test_pages_embed_covers_as_same_origin_lazy_images_with_escaped_alt(self):
        html = self.client().get("/", headers=JF_A).text
        self.assertRegex(html, r'<img src="/art/jellyfin/primary/aaaa0000000000000000000000000001" '
                               r'alt="Synthetic Film One" width="80" height="120" loading="lazy">')

    def test_another_members_cover_is_the_standard_404(self):
        c = self.client()
        self.assertStandard404(c.get(B_ONLY_FILM, headers=JF_A))           # B-only film, asked by A
        self.assertEqual(200, c.get(B_ONLY_FILM, headers=JF_B).status_code)
        self.assertStandard404(c.get(ADULT_BOOK, headers=KG_B))            # restricted out for B
        self.assertEqual(200, c.get(ADULT_BOOK, headers=KG_A).status_code)

    def test_a_member_without_the_group_gets_a_404_and_no_upstream_call(self):
        c = self.client()
        self.assertStandard404(c.get(A_ONLY_FILM, headers=NO_VIDEO))
        self.assertStandard404(c.get(COMIC_BOOK, headers=JF_A))
        self.assertStandard404(c.get(A_ONLY_FILM, headers=[]))             # no identity at all
        self.assertEqual([], self.jf.paths())
        self.assertEqual([], self.kg.paths())

    def test_hostile_refs_are_the_standard_404_without_an_upstream_call(self):
        c = self.client()
        hostile = ["/art/", "/art/jellyfin", "/art/jellyfin/primary", "/art/plex/primary/abc123",
                   "/art/jellyfin/primary/%2e%2e/%2e%2e/etc/passwd",
                   "/art/jellyfin/primary/aaaa0000000000000000000000000001%2f..%2fx",
                   "/art/https://evil.example/x/y", "/art//evil.example/x/y",
                   "/art/jellyfin/primary/aaaa0000000000000000000000000001/extra",
                   "/art/jellyfin/primary/aaaa0000000000000000000000000001.svg",
                   "/art/jellyfin/primary/AAAA", "/art/jellyfin/primary/" + "a" * 200,
                   "/art/%6aellyfin/primary/aaaa0000000000000000000000000001",
                   "/art/jellyfin\\primary\\x"]
        for path in hostile:
            with self.subTest(path=path):
                headers = JF_A if "komga" not in path else KG_A
                r = c.get(path, headers=headers)
                self.assertEqual(404, r.status_code)
                self.assertNotIn("image", r.headers["content-type"])
        # a query string is ignored (it can never choose a service or a URL): this is the plain Komga ref
        r = c.get("/art/komga/book/BOOKAAAA0001?url=http://evil.example/x.png&service=jellyfin", headers=KG_A)
        self.assertEqual(200, r.status_code)
        self.assertNotIn("evil", str(self.kg.paths()))
        # path traversal is rejected by the ref shape itself (an HTTP client would normalise "/../" away)
        from avrana_home.app.artwork import ref_from_route, src_for
        for route in ("/art/jellyfin/primary/../../komga/book/BOOKAAAA0001", "/art/komga/book/..",
                      "/art/komga/book/a/b", "/art/komga/./book/x", "/art/komga/book/x y"):
            self.assertIsNone(ref_from_route(route), route)
            self.assertIsNone(src_for(route[len("/art/"):]), route)
        # another service's ref asked by a member who lacks that service's group never reaches upstream:
        self.kg.reset()
        self.assertStandard404(c.get(COMIC_BOOK, headers=JF_A))
        self.assertEqual([], self.kg.paths())

    def test_upstream_failure_is_a_plain_404_never_a_5xx_with_details(self):
        for mode in ("down", "500", "malformed", "slow"):
            with self.subTest(mode=mode):
                self.jf.set_mode(mode)
                self.kg.set_mode(mode)
                for path, headers in ((A_ONLY_FILM, JF_A), (COMIC_BOOK, KG_A)):
                    r = self.client().get(path, headers=headers)
                    self.assertEqual(404, r.status_code, (mode, path))
                    for token in ("127.0.0.1", "Traceback", "refused", "mock", "Error"):
                        self.assertNotIn(token, r.text)

    def test_the_route_is_absent_when_sections_are_off(self):
        off = make_client(make_settings(home_sections=False))
        off.__enter__()
        self.addCleanup(off.__exit__, None, None, None)
        self.assertStandard404(off.get(A_ONLY_FILM, headers=JF_A))

    def test_only_get_and_head_are_served(self):
        c = self.client()
        self.assertEqual(501, c.post(A_ONLY_FILM, headers=JF_A).status_code)
        self.assertEqual(200, c.head(A_ONLY_FILM, headers=JF_A).status_code)


class _Svg(StubAdapter):
    """Whatever the adapter hands back, the gateway re-checks it."""
    result = ArtworkResult(SectionState.OK, "image/svg+xml", b"<svg onload=alert(1)></svg>")

    def fetch_artwork(self, principal, ref):
        return self.result


class GatewayRecheckTests(unittest.TestCase):
    def serve(self, result):
        adapter = _Svg({"member-a": []})
        adapter.result = result
        c = make_client(make_settings(home_sections=True), adapters=[adapter])
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c.get("/art/jellyfin/primary/aaaa0000000000000000000000000001", headers=JF_A)

    def test_svg_and_html_content_types_are_refused(self):
        for ctype in ("image/svg+xml", "text/html", "text/html; charset=utf-8", "application/xml",
                      "image/svg+xml; charset=utf-8", "image/gif", "", None):
            with self.subTest(ctype=ctype):
                r = self.serve(ArtworkResult(SectionState.OK, ctype, b"<svg onload=alert(1)></svg>"))
                self.assertEqual(404, r.status_code)
                self.assertNotIn("svg", r.text)

    def test_oversized_and_empty_bodies_are_refused_and_a_png_passes(self):
        from avrana_home.resilience import MAX_IMAGE_BYTES
        self.assertEqual(404, self.serve(ArtworkResult(SectionState.OK, "image/png",
                                                       PNG + b"x" * MAX_IMAGE_BYTES)).status_code)
        self.assertEqual(404, self.serve(ArtworkResult(SectionState.OK, "image/png", b"")).status_code)
        ok = self.serve(ArtworkResult(SectionState.OK, "image/png", PNG + b"x"))
        self.assertEqual(200, ok.status_code)
        self.assertEqual("private, no-store", ok.headers["cache-control"])

    def test_every_non_ok_state_is_the_same_404(self):
        for state in (SectionState.EMPTY, SectionState.NOT_PERMITTED, SectionState.UNAVAILABLE,
                      SectionState.NOT_LINKED):
            with self.subTest(state=state):
                self.assertEqual(404, self.serve(ArtworkResult(state, "image/png", PNG)).status_code)


if __name__ == "__main__":
    unittest.main()
