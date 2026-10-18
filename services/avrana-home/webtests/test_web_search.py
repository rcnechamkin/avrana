"""Tier B: the cross-library search page `GET /search?q=` (AVR-383) through the HTTP layer, against the mock
Jellyfin, Komga and Calibre-Web (loopback, SYNTHETIC data, real UrllibTransport). Two members with different
groups each see only their own libraries; a library the member cannot use never appears, not even as
"unavailable"."""
import logging
import re
import unittest

from dev.mock_calibre_web import MockCalibreWeb
from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from avrana_home.app.logsafe import ForbiddenValues
from avrana_home.app.viewmodel import build_search
from avrana_home.contract import Kind, MediaItem, SectionResult, build_handoff_url
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

CRED = "viewer:mock-api-key-not-real"
A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-books")]      # Movies and TV + Books
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]                   # Movies and TV only
KA = [(USER, "comics-a"), (GROUPS, "avrana-users|avrana-comics")]   # Comics: the shared view (contract 12.2)
KB = [(USER, "comics-b"), (GROUPS, "avrana-users|avrana-comics")]   # Comics: the same shared view
NOTHING = [(USER, "member-a"), (GROUPS, "avrana-users")]
FORBIDDEN_WORDS = ("Audiobooks", "Comics", "Books", "Movies and TV")
SENTINEL = "zzqxsentineltermzz"


class Fixture(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()
        cls.cw = MockCalibreWeb(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        for m in (cls.jf, cls.kg, cls.cw):
            m.stop()

    def setUp(self):
        for m in (self.jf, self.kg, self.cw):
            m.set_mode("ok")
            m.reset()

    def client(self, adapters=None, **kw):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url, komga_base_url=self.kg.url,
                                      komga_token="mock-api-key-not-real", calibre_web_base_url=self.cw.url,
                                      calibre_web_credential=CRED, timeout=self.timeout, **kw), adapters=adapters)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def search(self, who, term, **kw):
        return self.client(**kw).get("/search", params={"q": term}, headers=who)

    def upstream_calls(self):
        return sum(len(m.paths()) for m in (self.jf, self.kg, self.cw))


class PerMemberResults(Fixture):
    def test_each_member_sees_only_their_own_libraries(self):
        c = self.client()
        a = c.get("/search", params={"q": "Synthetic"}, headers=A)
        b = c.get("/search", params={"q": "Synthetic"}, headers=B)
        self.assertEqual((200, 200), (a.status_code, b.status_code))
        self.assertIn("Synthetic Film One", a.text)
        self.assertIn("Synthetic Book One", a.text)
        self.assertNotIn("Synthetic Film Two", a.text)
        self.assertIn("Movies and TV", a.text)
        self.assertIn("Books", a.text)
        self.assertIn("Synthetic Film Two", b.text)
        self.assertNotIn("Synthetic Film One", b.text)
        for word in ("Books", "Comics", "Audiobooks", "Synthetic Book", "Synthetic Comic"):
            self.assertNotIn(word, b.text, word)
        k = c.get("/search", params={"q": "Synthetic"}, headers=KB)
        self.assertIn("Comics", k.text)
        for word in ("Movies and TV", "Books", "Audiobooks", "Synthetic Film", "Synthetic Book"):
            self.assertNotIn(word, k.text, word)

    def test_a_forbidden_library_is_not_even_unavailable(self):
        self.kg.set_mode("down")
        self.cw.set_mode("down")
        r = self.search(B, "Synthetic")
        self.assertEqual(200, r.status_code)
        self.assertIn("Synthetic Film Two", r.text)
        for word in ("Comics", "Books", "Audiobooks", "unavailable", "not set up"):
            self.assertNotIn(word, r.text, word)
        self.assertEqual([], self.kg.paths())            # nobody even asked the library B may not use
        self.assertEqual([], self.cw.paths())

    def test_komga_search_is_the_shared_view(self):
        """Komga is a shared regular-account view (owner decision 2026-10-15): two comics members get the
        same answer; Komga itself applies that one account's library sharing."""
        c = self.client()
        ra = c.get("/search", params={"q": "Mature"}, headers=KA)
        rb = c.get("/search", params={"q": "Mature"}, headers=KB)
        self.assertIn("Synthetic Mature One", ra.text)
        self.assertIn("Synthetic Mature One", rb.text)
        self.assertIn("Nothing found", c.get("/search", params={"q": "nomatchatall"}, headers=KA).text)

    def test_no_searchable_library_gets_no_box_and_points_to_help(self):
        r = self.search(NOTHING, "Synthetic")
        self.assertEqual(200, r.status_code)
        self.assertNotIn("<input", r.text)
        self.assertNotIn("<form", r.text)
        self.assertIn('href="/help"', r.text)
        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, r.text, word)
        self.assertEqual(0, self.upstream_calls())

    def test_no_identity_is_the_standard_404(self):
        c = self.client()
        self.assertEqual(c.get("/definitely-not-a-route").text, c.get("/search", params={"q": "Synthetic"}).text)
        self.assertEqual(404, c.get("/search?q=Synthetic").status_code)


class States(Fixture):
    def test_one_service_down_is_said_truthfully_and_the_rest_still_answer(self):
        self.jf.set_mode("down")
        r = self.search(A, "Synthetic")
        self.assertEqual(200, r.status_code)
        self.assertIn("The Movies and TV library could not be searched right now", r.text)
        self.assertIn("Synthetic Book One", r.text)
        self.assertNotIn("No matches in Movies", r.text)

    def test_no_matches_has_its_own_message(self):
        r = self.search(A, "nothingmatchesthis")
        self.assertIn("Nothing found. Check the spelling", r.text)
        self.assertIn("No matches in Movies and TV.", r.text)
        self.assertNotIn("unavailable", r.text)

    def test_everything_down_is_not_reported_as_no_matches(self):
        self.jf.set_mode("500")
        self.cw.set_mode("500")
        r = self.search(A, "Synthetic")
        self.assertEqual(200, r.status_code)
        self.assertNotIn("Check the spelling", r.text)
        self.assertNotIn("No results", r.text)                  # unavailable is not empty (review LOW on #53)
        self.assertNotIn("No matches", r.text)
        self.assertNotIn("Nothing found", r.text)
        self.assertIn("Your libraries could not be searched right now.", r.text)
        self.assertIn('href="/search?q=Synthetic">Try again', r.text)
        self.assertNotIn("Request this title", r.text)
        self.assertEqual(2, r.text.count("library could not be searched right now"))

    def test_not_set_up_is_its_own_state(self):
        view = {"status": "ok", "entitled": True,
                "groups": [{"service": "komga", "state": "not_linked", "items": []}]}
        page = build_search(view, "Synthetic")
        self.assertEqual("The Comics library is not set up for your account yet.", page.groups[0].message)

    def test_invalid_terms_say_so_with_a_hint_and_ask_nobody(self):
        for term in ("a", " ", "*", "%", "??", "x" * 300):
            with self.subTest(term=term[:10]):
                r = self.search(A, term)
                self.assertEqual(200, r.status_code)
                self.assertIn("That search term cannot be used.", r.text)
                self.assertIn("At least 2 characters", r.text)
        self.assertEqual(0, self.upstream_calls())

    def test_no_term_is_an_empty_form(self):
        r = self.client().get("/search", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertIn('name="q"', r.text)
        self.assertNotIn("cannot be used", r.text)
        self.assertEqual(0, self.upstream_calls())

    def test_wildcards_do_not_widen_results(self):
        def titles(term):
            return sorted(re.findall(r'<a class="t" href="[^"]*">([^<]*)<', self.search(A, term).text))

        plain = titles("Synthetic Film")
        self.assertTrue(plain)
        for term in ("Synthetic Film*", "Synthetic Film%", "Synthetic Film?", "Synthetic Film_"):
            self.assertEqual(plain, titles(term), term)          # a wildcard is a space, never "anything"
        for term in ("S_nthetic", "Synth*c Film", "Syn?hetic", "Synthetic%Fi%m One", "S%"):
            self.assertEqual([], titles(term), term)
        for term in ("*", "%", "_", "??", "% %"):
            self.assertIn("cannot be used", self.search(A, term).text, term)
        sent = self.jf.paths() + self.kg.paths() + self.cw.paths()
        self.assertFalse([p for p in sent if "*" in p or "%25" in p])


class Safety(Fixture):
    def test_a_hostile_term_is_escaped_and_bounded(self):
        term = '"><script>alert(1)</script>' + "x" * 200
        r = self.search(A, term)
        self.assertEqual(200, r.status_code)
        self.assertNotIn("<script>alert", r.text)
        self.assertNotIn('"><script', r.text)
        for value in re.findall(r'<input id="q"[^>]*value="([^"]*)"', r.text):
            self.assertLessEqual(len(value), 100 * 6)

    def test_a_hostile_title_is_escaped_and_hrefs_are_https_only(self):
        hostile = "<img src=x onerror=alert(1)>\"'<b>"

        class Hostile(StubAdapter):
            def _search(self, user, query, limit):
                item_id = "aaaa0000000000000000000000000001"
                items = (MediaItem(id="jellyfin:" + item_id, service=self.service, kind=Kind.MOVIE, title=hostile,
                                   handoff_url=build_handoff_url(self.service, item_id)),)
                return SectionResult.of(self.service, "search", items)

        c = make_client(make_settings(home_sections=True), adapters=[Hostile({"member-a": []})])
        r = c.get("/search", params={"q": "Synthetic"}, headers=A)
        self.assertEqual(200, r.status_code)
        self.assertNotIn("<img src=x", r.text)
        self.assertNotIn("<b>", r.text)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", r.text)
        for href in re.findall(r'href="([^"]*)"', r.text):
            self.assertTrue(href.startswith(("https://", "/", "#main")), href)
        # StubAdapter offers no item lookup of its own here, so the one link goes straight to the library
        self.assertTrue(re.search(r'<a class="t" href="(?:https://|/title/)[^"]+"', r.text))

    def test_only_https_handoffs_and_art_routes_survive_the_view_model(self):
        def item(url, art):
            return {"title": "T", "kind": "movie", "handoff_url": url, "artwork": {"ref": art}}

        view = {"status": "ok", "entitled": True, "groups": [{"service": "jellyfin", "state": "ok", "items": [
            item("http://x.example/a", "jellyfin/primary/aaa"), item("javascript:alert(1)", None),
            item("//x.example/b", None), item("https://x.example/e", None),      # https, but not the service's host
            item("https://watch.avrana.net/c", "https://evil.example/x.png"),
            item("https://watch.avrana.net/d", "jellyfin/primary/ddd")]}]}
        items = build_search(view, "tt").groups[0].items
        self.assertEqual(["https://watch.avrana.net/c", "https://watch.avrana.net/d"], [i.href for i in items])
        self.assertEqual([None, "/art/jellyfin/primary/ddd"], [i.image for i in items])

    def test_images_come_only_from_the_art_route(self):
        r = self.search(A, "Synthetic")
        srcs = re.findall(r'<img[^>]*src="([^"]*)"', r.text)
        self.assertTrue(srcs)
        self.assertTrue(all(s.startswith("/art/") for s in srcs), srcs)

    def test_the_term_is_never_logged(self):
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(record)

        root, handler = logging.getLogger(), Grab(logging.DEBUG)
        old = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            for who in (A, KA, NOTHING):
                self.search(who, SENTINEL)
            self.search(A, SENTINEL.upper() + "%00" + "?" + SENTINEL)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        self.assertTrue(records)
        # httpx is the TEST CLIENT logging its own outgoing request line; the server side is everything else.
        server = [r for r in records if not r.name.startswith(("httpx", "httpcore"))]
        self.assertTrue([r for r in server if r.name.startswith("avrana_home")])      # the app did log (no term)
        scan = ForbiddenValues([SENTINEL, SENTINEL.upper()])
        self.assertEqual([], [(r.name, hit) for r in server for hit in scan.scan(r)])

    def test_csp_allows_the_form_to_submit_on_search_only(self):
        c = self.client()
        search, other = c.get("/search", headers=A), c.get("/", headers=A)
        self.assertIn("form-action 'self'", search.headers["content-security-policy"])
        self.assertIn("form-action 'none'", other.headers["content-security-policy"])
        self.assertEqual("no-store", search.headers["cache-control"])
        self.assertIn("img-src 'self'", search.headers["content-security-policy"])


class FlagOff(Fixture):
    def test_with_sections_off_search_is_exactly_an_unknown_route(self):
        c = make_client(make_settings(home_sections=False))
        unknown = c.get("/definitely-not-a-route", headers=A)
        for target in ("/search", "/search?q=Synthetic", "/search/"):
            r = c.get(target, headers=A)
            self.assertEqual((404, unknown.text), (r.status_code, r.text), target)
            self.assertEqual(unknown.headers["content-type"], r.headers["content-type"])
            self.assertEqual(unknown.headers["content-security-policy"], r.headers["content-security-policy"])
        self.assertEqual(0, self.upstream_calls())


if __name__ == "__main__":
    unittest.main()
