"""Tier B: title pages `GET /title/<service>/<id>` (AVR-384) and search's links into them (AVR-383), through the
HTTP layer against the loopback mocks (SYNTHETIC data, real UrllibTransport).

A title the member may not see, an unknown one, a malformed or hostile id, a library the member cannot use and a
missing identity all get the ONE standard 404, byte for byte the unknown-route page (portal parity, never 403).
An unavailable library is a calm page that says nothing about whether the title exists."""
import re
import unittest

from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_calibre_web import MockCalibreWeb
from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

CRED = "viewer:mock-api-key-not-real"
EVERYTHING = "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"
A = [(USER, "member-a"), (GROUPS, EVERYTHING)]
B = [(USER, "member-b"), (GROUPS, EVERYTHING)]
A_NO_VIDEO = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-audiobooks|avrana-comics|avrana-books")]
A_VIDEO_ONLY = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
FILM_A = "aaaa0000000000000000000000000001"          # member-a's, with a saved position
FILM_A3 = "aaaa0000000000000000000000000010"         # member-a's, not started
FILM_B = "bbbb0000000000000000000000000001"          # member-b's only
# (Dot segments are sent raw over a real socket below: the test client would resolve them itself.)
HOSTILE = ("/title/jellyfin/" + FILM_A + "%2f..", "/title/jellyfin/%2e%2e",
           "/title/jellyfin/" + FILM_A.upper(), "/title/jellyfin/" + FILM_A + "%0d%0aX-Evil:%201",
           "/title/jellyfin/" + FILM_A + "%00", "/title/jellyfin/" + "a" * 4000, "/title/calibre-web/101",
           "/title/nope/" + FILM_A, "/title/jellyfin", "/title/", "/title/komga/latest",
           "/title/jellyfin/" + FILM_A + "/Images/Primary", "/title/audiobookshelf/li_book000003%2F",
           "/title//jellyfin/" + FILM_A + "/x")


class Fixture(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.ab = MockAudiobookshelf(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()
        cls.cw = MockCalibreWeb(slow_seconds=3.0).start()
        cls.mocks = (cls.jf, cls.ab, cls.kg, cls.cw)

    @classmethod
    def tearDownClass(cls):
        for m in cls.mocks:
            m.stop()

    def setUp(self):
        for m in self.mocks:
            m.set_mode("ok")
            m.reset()

    def client(self, **kw):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.ab.url, audiobookshelf_token="mock-api-key-not-real",
                                      komga_base_url=self.kg.url, komga_token="mock-api-key-not-real",
                                      calibre_web_base_url=self.cw.url, calibre_web_credential=CRED,
                                      timeout=self.timeout, **kw))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def calls(self):
        return sum(len(m.paths()) for m in self.mocks)

    def assert_standard_404(self, c, r, who=A):
        unknown = c.get("/definitely-not-a-route", headers=who)
        self.assertEqual((404, unknown.text), (r.status_code, r.text))
        self.assertEqual(unknown.headers["content-security-policy"], r.headers["content-security-policy"])


class TitlePage(Fixture):
    def test_a_members_own_title_with_resume_and_safe_links(self):
        c = self.client()
        r = c.get("/title/jellyfin/" + FILM_A, headers=A)
        self.assertEqual(200, r.status_code)
        self.assertIn('<h2 id="h-title" class="t">Synthetic Film One</h2>', r.text)
        self.assertIn('aria-label="Resume Synthetic Film One in Movies and TV">Resume</a>', r.text)
        self.assertIn("left", r.text)                                    # progress in words
        self.assertIn('<p class="kicker">Movies and TV</p>', r.text)      # not "Movie · Movies and TV" (#13)
        self.assertNotIn("Movie · Movies and TV", r.text)
        # Return navigation like the other shell pages (#4): Back to home, no extra Help (it is in the places bar);
        # the hint is an inline link to the trouble topic, not a padded block before an orphaned full stop.
        foot = r.text.split("<footer>", 1)[1]
        self.assertIn('<a class="link" href="/">Back to home</a>', foot)
        self.assertNotIn('href="/help"', foot)
        self.assertIn('see <a class="inline" href="/help/trouble">If something doesn&#x27;t open</a>.</p>', r.text)
        self.assertNotIn("playing", r.text.lower())
        self.assertNotIn("Back to search", r.text)                       # not reached from a search
        self.assertIn("form-action 'none'", r.headers["content-security-policy"])   # the strict default
        self.assertEqual(1, len(re.findall(r'<a class="open"', r.text)))            # one primary action
        hrefs = re.findall(r'href="([^"]*)"', r.text)
        self.assertTrue(all(h.startswith(("https://watch.avrana.net/", "/", "#main")) for h in hrefs), hrefs)
        for src in re.findall(r'<img class="art"[^>]*src="([^"]*)"', r.text):
            self.assertTrue(src.startswith("/art/jellyfin/primary/"), src)
        # the only other image is the glass Home button's Spire-A mark, a fixed same-origin brand file (AVR-584, D5)
        self.assertEqual(["/brand/spire-a-24.svg"], re.findall(r'<img class="(?!art")[^"]*"[^>]*src="([^"]*)"', r.text))
        w = c.get("/title/jellyfin/" + FILM_A3, headers=A)
        self.assertIn(">Watch</a>", w.text)
        self.assertIn("2020", w.text)

    def test_two_members_never_see_each_others_titles(self):
        c = self.client()
        self.assertEqual(200, c.get("/title/jellyfin/" + FILM_B, headers=B).status_code)
        self.assert_standard_404(c, c.get("/title/jellyfin/" + FILM_B, headers=A))
        self.assert_standard_404(c, c.get("/title/jellyfin/" + FILM_A, headers=B), B)
        self.assertEqual(200, c.get("/title/audiobookshelf/li_book000003", headers=B).status_code)
        self.assert_standard_404(c, c.get("/title/audiobookshelf/li_book000003", headers=A))   # a's rights
        self.assert_standard_404(c, c.get("/title/audiobookshelf/li_book000004", headers=A))   # explicit

    def test_audiobook_and_comic_pages(self):
        c = self.client()
        r = c.get("/title/audiobookshelf/li_book000001", headers=A)
        self.assertIn(">Resume</a>", r.text)
        self.assertIn("Synthetic Author · 2011", r.text)
        self.assertIn("https://listen.avrana.net/item/li_book000001", r.text)
        k = c.get("/title/komga/BOOKAAAA0001", headers=A)
        self.assertEqual(200, k.status_code)
        self.assertIn(">Read</a>", k.text)
        self.assertIn("Synthetic Writer · 2019", k.text)

    def test_a_revoked_group_is_the_standard_404_at_once(self):
        c = self.client()
        self.assertEqual(200, c.get("/title/jellyfin/" + FILM_A, headers=A).status_code)    # warms a's cache
        before = self.calls()
        self.assert_standard_404(c, c.get("/title/jellyfin/" + FILM_A, headers=A_NO_VIDEO), A_NO_VIDEO)
        self.assertEqual(before, self.calls())
        self.assert_standard_404(c, c.get("/title/komga/BOOKAAAA0001", headers=A_VIDEO_ONLY), A_VIDEO_ONLY)

    def test_hostile_and_unknown_ids_are_the_standard_404_and_ask_nobody(self):
        c = self.client()
        for target in HOSTILE:
            with self.subTest(target=target[:50]):
                self.assert_standard_404(c, c.get(target, headers=A))
        self.assertEqual(0, self.calls())
        self.assert_standard_404(c, c.get("/title/jellyfin/" + "f" * 32, headers=A))         # well-formed, unknown

    def test_raw_dot_segments_and_encoded_separators_over_a_real_socket(self):
        from avrana_home.app.main import create_app
        from .support import RealServer
        app = create_app(make_settings(home_sections=True, jellyfin_base_url=self.jf.url, timeout=self.timeout))
        with RealServer(app) as srv:
            unknown = srv.get("/definitely-not-a-route", headers=A)
            for target in ("/title/jellyfin/../jellyfin/" + FILM_A, "/title/jellyfin/./" + FILM_A,
                           "/title/jellyfin/" + FILM_A + "/..", "/title/jellyfin/%2E%2E/" + FILM_A,
                           "/title/jellyfin%2f" + FILM_A, "/title/jellyfin/" + FILM_A + "%00"):
                r = srv.get(target, headers=A)
                self.assertEqual((404, unknown.body), (r.status, r.body), target)
        self.assertEqual(0, self.calls())

    def test_no_identity_and_sections_off_are_the_standard_404(self):
        c = self.client()
        self.assert_standard_404(c, c.get("/title/jellyfin/" + FILM_A), [])
        off = make_client(make_settings(home_sections=False))
        unknown = off.get("/definitely-not-a-route", headers=A)
        r = off.get("/title/jellyfin/" + FILM_A, headers=A)
        self.assertEqual((404, unknown.text), (r.status_code, r.text))

    def test_unavailable_is_calm_says_nothing_about_the_title_and_offers_try_again(self):
        self.jf.set_mode("500")
        c = self.client()
        mine = c.get("/title/jellyfin/" + FILM_A + "?q=Synthetic", headers=A)
        unknown = c.get("/title/jellyfin/" + "f" * 32, headers=A)
        self.assertEqual((503, 503), (mine.status_code, unknown.status_code))
        self.assertIn("The Movies and TV library is unavailable right now.", mine.text)
        self.assertNotIn("Synthetic Film", mine.text)
        self.assertIn(f'href="/title/jellyfin/{FILM_A}?q=Synthetic">Try again', mine.text)
        self.assertIn('href="/search?q=Synthetic">Back to search', mine.text)
        self.assertNotIn('class="open"', mine.text)                     # no action at all: nothing to open

    def test_a_title_is_never_served_from_cache(self):
        """Review of #58: every view is the permission-checked upstream lookup, so access removal and outages show
        at once; while down, a seen and an unseen title answer the same 503."""
        c = self.client()
        shared = "/title/jellyfin/cccc0000000000000000000000000001"
        self.assertEqual(200, c.get(shared, headers=A).status_code)
        self.jf.set_mode("500")
        self.assertEqual(503, c.get(shared, headers=A).status_code)
        self.assertEqual(503, c.get(shared, headers=B).status_code)

    def test_a_komga_book_the_shared_account_may_not_open_is_the_standard_404(self):
        c = self.client()
        self.kg.fake.overrides["/api/v1/books/BOOKAAAA0001"] = ("status", 403)
        try:
            forbidden = c.get("/title/komga/BOOKAAAA0001", headers=A)
            unknown = c.get("/title/komga/BOOKZZZZ9999", headers=A)
        finally:
            self.kg.fake.overrides.pop("/api/v1/books/BOOKAAAA0001", None)
        self.assert_standard_404(c, forbidden)
        self.assertEqual((unknown.status_code, unknown.text), (forbidden.status_code, forbidden.text))

    def test_back_to_search_carries_only_a_valid_term_encoded(self):
        c = self.client()
        r = c.get("/title/jellyfin/" + FILM_A, params={"q": 'Synth"><script>'}, headers=A)
        self.assertIn('href="/search?q=Synth%20%3E%3Cscript%3E">Back to search', r.text)
        self.assertNotIn("<script>", r.text)
        for bad in ("*", "a", "x" * 400):
            t = c.get("/title/jellyfin/" + FILM_A, params={"q": bad}, headers=A).text
            self.assertNotIn("Back to search", t)
        t = c.get("/title/jellyfin/" + FILM_A + "?next=https://evil.example&q=Film&q=Other", headers=A).text
        self.assertNotIn("evil", t)
        self.assertIn('href="/search?q=Film">Back to search', t)


    def test_titles_ids_and_terms_are_never_logged(self):
        import logging
        from avrana_home.app.logsafe import ForbiddenValues
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(record)

        root, handler = logging.getLogger(), Grab(logging.DEBUG)
        old = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            c = self.client()
            c.get("/title/jellyfin/" + FILM_A + "?q=zzqxsentinelzz", headers=A)
            c.get("/title/jellyfin/" + FILM_B, headers=A)
            c.get("/title/audiobookshelf/li_book000001", headers=A)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        server = [r for r in records if not r.name.startswith(("httpx", "httpcore"))]
        self.assertTrue([r for r in server if r.name.startswith("avrana_home")])
        scan = ForbiddenValues(["zzqxsentinelzz", FILM_A, FILM_B, "li_book000001", "Synthetic Film One",
                                "Synthetic Audiobook One"])
        self.assertEqual([], [(r.name, hit) for r in server for hit in scan.scan(r)])


class SearchLinks(Fixture):
    def test_results_link_to_title_pages_that_work_for_the_same_member(self):
        c = self.client()
        r = c.get("/search", params={"q": "Synthetic Film"}, headers=A)
        links = re.findall(r'<a class="t" href="(/title/[^"]+)">', r.text)
        self.assertIn(f"/title/jellyfin/{FILM_A}?q=Synthetic%20Film", links)
        for href in links:
            page = c.get(href.replace("&amp;", "&"), headers=A)
            self.assertEqual(200, page.status_code, href)
            self.assertIn('href="/search?q=Synthetic%20Film">Back to search', page.text)
        self.assertNotIn(FILM_B, r.text)

    def test_results_say_medium_creator_and_year(self):
        c = self.client()
        r = c.get("/search", params={"q": "Synthetic"}, headers=A)
        self.assertIn("<span class=\"sr\">, Movie</span>", r.text)
        self.assertIn("Audiobook · Synthetic Author · 2011", r.text)
        self.assertIn("Comic · Synthetic Writer · 2019", r.text)
        self.assertIn("Book · Synthetic Author A · 2008", r.text)
        self.assertIn("Opens in Books", r.text)            # Calibre-Web has no title page: straight to the library
        for li in re.findall(r"<li class=\"w-[a-z]+\">.*?</li>", r.text, re.S):
            self.assertEqual(1, li.count("<a "), li)

    def test_a_cover_from_a_result_is_not_served_to_another_member(self):
        c = self.client()
        r = c.get("/search", params={"q": "Audiobook One"}, headers=A)
        self.assertIn("/art/audiobookshelf/cover/li_book000001", r.text)
        hidden = c.get("/art/audiobookshelf/cover/li_book000003", headers=A)          # a may not use lib_bbb
        self.assert_standard_404(c, hidden)
        self.assertEqual(200, c.get("/art/audiobookshelf/cover/li_book000003", headers=B).status_code)

    def test_every_library_down_is_never_no_results(self):
        for m in self.mocks:
            m.set_mode("500")
        r = self.client().get("/search", params={"q": "Synthetic"}, headers=A)
        self.assertEqual(200, r.status_code)
        self.assertIn("Your libraries could not be searched right now.", r.text)
        for word in ("No results", "No matches", "Nothing found", "Request this title"):
            self.assertNotIn(word, r.text, word)
        self.assertIn('href="/search?q=Synthetic">Try again', r.text)

    def test_every_audiobookshelf_library_404_is_unavailable_not_empty(self):
        listener = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-audiobooks")]
        c = self.client()
        self.ab.fake.overrides["/api/libraries/lib_aaa/search"] = ("status", 404)
        try:
            r = c.get("/search", params={"q": "Synthetic"}, headers=listener)
        finally:
            self.ab.fake.overrides.pop("/api/libraries/lib_aaa/search", None)
        self.assertIn("The Audiobooks library could not be searched right now.", r.text)
        self.assertNotIn("No matches", r.text)

    def test_no_matches_offers_request_only_for_the_members_own_request_services(self):
        c = self.client()
        r = c.get("/search", params={"q": "nomatch here"}, headers=A)
        # The Seerr link leaves Avrana with the term: the page says so, visibly and to screen readers (#8).
        self.assertIn('href="https://request.avrana.net/search?query=nomatch%20here">Ask for a film or show'
                      '<span class="sr">, opens the request website</span></a> '
                      '<span class="hint" aria-hidden="true">Opens the request website</span>', r.text)
        # The others leave Avrana too, through our own route's redirect (MK-5b review): each says so as well.
        self.assertIn('href="/requestacomic">Ask for a comic<span class="sr">, opens the request website</span></a> '
                      '<span class="hint" aria-hidden="true">Opens the request website</span>', r.text)
        self.assertIn('href="/requestabook">Ask for ', r.text)
        self.assertEqual(3, r.text.count("Opens the request website</span>"))   # one per offer, each leaves
        self.assertNotIn("Request this title", r.text)
        self.assertNotIn("an ebook", r.text)
        v = c.get("/search", params={"q": "nomatch here"}, headers=A_VIDEO_ONLY).text
        self.assertIn("Ask for a film or show", v)
        for word in ("requestabook", "requestacomic", "a comic", "ebook", "audiobook"):
            self.assertNotIn(word, v, word)
        found = c.get("/search", params={"q": "Synthetic"}, headers=A).text
        self.assertNotIn("Ask for a", found)


if __name__ == "__main__":
    unittest.main()
