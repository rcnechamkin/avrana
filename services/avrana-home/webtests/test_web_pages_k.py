"""Tier B: Concept K Search, Request, Me, Account and Help (MK-5b, AVR-719). SYNTHETIC data only: StubAdapter, or the
loopback mock Jellyfin, Audiobookshelf, Komga and Calibre-Web (real UrllibTransport).

What this slice adds and must never weaken:
  * /me, the Me hub: shell only (otherwise the standard 404, as an unknown route), the member's own name and
    username, rows only for what the member has; Operations and the role tag only behind the catalogue's own
    Operations gate; Sign out is the catalogue's address.
  * Search: the no-results offers are only the member's own request routes (and Contribute only for a member whose
    catalogue holds it); a library that could not answer is said in words in the warning panel, and a library the
    member cannot use is never named.
  * Request: grouped rows of the member's own request places; "Add to the library" only with Contribute.
  * Account: the section headings are the eyebrow role (wrapping), no longer the letter-spaced caps; Manage account
    and Sign out are rows in the page; sections off keeps the portal's page.
  * Every page: no script, no inline style, every glyph decorative, CSP and Cache-Control unchanged, and two members
    never see each other's names, libraries or results (mirrors test_web_isolation_h2.py).
"""
import re
import unittest
from pathlib import Path

from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_calibre_web import MockCalibreWeb
from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from avrana_home.app.middleware import CSP, CSP_SEARCH
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

TEMPLATES = Path(__file__).resolve().parents[1] / "avrana_home" / "app" / "templates"
SHELL_SOURCES = "; manifest-src 'self'; font-src 'self'; script-src 'self'; worker-src 'self'"   # + MK-3, O1
KEY = "mock-api-key-not-real"
CRED = "viewer:mock-api-key-not-real"
NAME = "X-authentik-name"
ALL = [(USER, "member-a"), (NAME, "Member A"),
       (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books")]
VIDEO = [(USER, "member-v"), (GROUPS, "avrana-users|avrana-videos")]
COMICS = [(USER, "comics-a"), (GROUPS, "avrana-users|avrana-comics")]
BOOKS = [(USER, "member-k"), (GROUPS, "avrana-users|avrana-books")]
CONTRIB = [(USER, "member-c"), (GROUPS, "avrana-users|avrana-videos|library-contributors")]
ADMIN = [(USER, "admin-a"), (NAME, "Admin A"), (GROUPS, "avrana-users|avrana-videos|authentik Admins")]
ADMIN_ONLY = [(USER, "synthetic-admin"), (GROUPS, "authentik Admins")]
NOLIB = [(USER, "member-n"), (GROUPS, "avrana-users")]
NO_GROUPS = [(USER, "member-a")]
PAGES = ("/me", "/account", "/help", "/help/movies", "/help/trouble", "/request", "/read", "/search")
MARKER = "  /* ---- MK-5b Search, requests and Me (AVR-719) ---- */\n"
# MK-3 (O1): shell pages carry exactly one first-party script tag in <head>; nothing else may script.
PAGE_SCRIPT = re.compile(r'<script src="/static/home\.[0-9a-f]{12}\.js" defer(?: data-sw="off")?></script>\n?')


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def footer_of(text):
    return text.split("<footer>", 1)[1].split("</footer>", 1)[0]


def hrefs(fragment, cls):
    return re.findall(rf'<a class="{cls}" href="([^"]*)"', fragment)


class Stub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = {"member-a": [("a" * 32, "Synthetic Pages Film", 0.5)]}
        cls.on = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)])
        cls.off = make_client(make_settings(home_sections=False))
        cls.on.__enter__()
        cls.off.__enter__()
        cls.cat = cls.on.fastapi_app.state.catalogue

    @classmethod
    def tearDownClass(cls):
        cls.on.__exit__(None, None, None)
        cls.off.__exit__(None, None, None)

    def page(self, path, headers=ALL):
        r = self.on.get(path, headers=headers)
        self.assertEqual(200, r.status_code, path)
        return r.text


class MeHub(Stub):
    def test_only_with_the_shell_and_a_member_otherwise_exactly_an_unknown_route(self):
        for client, headers in ((self.off, ALL), (self.on, []), (self.on, NO_GROUPS)):
            nope = client.get("/nope", headers=headers)
            for path in ("/me", "/me/", "/me?x=1"):
                r = client.get(path, headers=headers)
                self.assertEqual((404, nope.text), (r.status_code, r.text), (path, headers))
                self.assertEqual(nope.headers["content-security-policy"], r.headers["content-security-policy"])
                self.assertEqual(nope.headers["cache-control"], r.headers["cache-control"])

    def test_says_who_is_signed_in_from_the_principal_only(self):
        main = main_of(self.page("/me"))
        self.assertIn('<h2 class="topic">Me</h2>', main)
        self.assertIn('<span class="me-av" aria-hidden="true">M</span>', main)
        self.assertIn('<p class="me-name">Member A</p>', main)
        self.assertIn('<p class="k-meta">Signed in as member-a</p>', main)
        # no name header: the username stands in, never a guess
        self.assertIn('<p class="me-name">member-v</p>', main_of(self.page("/me", VIDEO)))

    def test_lists_only_what_the_member_has(self):
        main = main_of(self.page("/me"))
        self.assertEqual(["/account", "/help", "/help/trouble", "/signout"], hrefs(main, "krow-a"))
        for absent in ("/ops", "Operations", "k-tag", "Admin", "Install", "This phone"):
            self.assertNotIn(absent, main, absent)
        # a member with no library gets the same hub, and still no library word
        nolib = main_of(self.page("/me", NOLIB))
        self.assertEqual(["/account", "/help", "/help/trouble", "/signout"], hrefs(nolib, "krow-a"))
        for word in ("Movies", "Audiobook", "Comic", "Books"):
            self.assertNotIn(word, nolib, word)

    def test_operations_and_the_role_tag_only_behind_the_operations_gate(self):
        for headers in (ADMIN, ADMIN_ONLY):
            main = main_of(self.page("/me", headers))
            self.assertIn('<span class="k-tag">Admin</span>', main)
            self.assertIn('<a class="krow-a" href="/ops">', main)
            self.assertIn("Operations", main)
            self.assertIn('<span class="sr">, opens a separate website</span>', main)     # it leaves Avrana
            self.assertEqual(307, self.on.get("/ops", headers=headers).status_code)     # the row's own route works
        for headers in (ALL, VIDEO, CONTRIB, NOLIB):
            self.assertEqual(404, self.on.get("/ops", headers=headers).status_code)
            self.assertNotIn("k-tag", main_of(self.page("/me", headers)))

    def test_sign_out_is_the_signout_hop_on_me_and_on_account(self):
        # MK-3 (D10): the shell's Sign out goes through /signout, which clears this device and then sends the member
        # on to the catalogue's own sign-out address.
        out = '<a class="krow-a" href="/signout">'
        self.assertIn(out, main_of(self.page("/me")))
        self.assertIn(out, main_of(self.page("/account")))


class RequestPage(Stub):
    def test_only_the_members_own_request_places_each_leaving_avrana(self):
        main = main_of(self.page("/request"))
        self.assertEqual(["/requests", "/requestabook", "/requestacomic"], hrefs(main, "krow-a"))
        self.assertEqual(3, main.count("Opens the request website"))
        self.assertEqual(3, main.count('class="kic krow-go"'))
        self.assertIn('<h3 class="kgroup-h" id="g-ask">Ask for something</h3>', main)
        self.assertNotIn("Add to the library", main)
        comics = main_of(self.page("/request", COMICS))
        self.assertEqual(["/requestacomic"], hrefs(comics, "krow-a"))
        for word in ("film", "Movies", "book", "Book"):
            self.assertNotIn(word, comics, word)

    def test_add_to_the_library_only_with_contribute(self):
        main = main_of(self.page("/request", CONTRIB))
        self.assertEqual(["/requests", "/contribute"], hrefs(main, "krow-a"))
        self.assertIn('<h3 class="kgroup-h" id="g-add">Add to the library</h3>', main)
        self.assertEqual(307, self.on.get("/contribute", headers=CONTRIB).status_code)
        self.assertEqual(404, self.on.get("/contribute", headers=ALL).status_code)

    def test_read_lists_only_the_members_own_libraries(self):
        self.assertEqual(["/comics"], hrefs(main_of(self.page("/read", COMICS)), "krow-a"))

    def test_sections_off_keeps_the_portal_tiles(self):
        text = self.off.get("/request", headers=ALL).text
        self.assertIn('<nav class="tiles" aria-label="Request">', text)
        self.assertNotIn("krow", text)


class AccountPage(Stub):
    def test_section_headings_are_the_wrapping_eyebrow_not_the_letter_spaced_caps(self):
        main = main_of(self.page("/account"))
        heads = re.findall(r'<section class="block kgroup">\s*<h2>([^<]+)</h2>', main)
        self.assertEqual(["Signed in as", "Your access", "Signing in", "Signing out", "Getting help", "Preferences"], heads)
        self.assertNotRegex(main, r'<section class="block">')
        block = (TEMPLATES / "home.css").read_text(encoding="utf-8").split(MARKER, 1)[1].split("\n  /* ---- MK-", 1)[0]
        rule = re.search(r"\.kgroup-h,section\.kgroup>h2,\.found>h3\{([^}]*)\}", block).group(1)
        for decl in ("font-size:var(--text-eyebrow)", "font-weight:500", "letter-spacing:0.16em",
                     "text-transform:uppercase", "overflow-wrap:break-word"):
            self.assertIn(decl, rule)
        self.assertNotIn("0.22em", rule)

    def test_every_existing_control_is_still_there(self):
        text = self.page("/account")
        main = main_of(text)
        self.assertIn("<dt>Username</dt><dd>member-a</dd>", main)
        self.assertIn('<a class="link" href="/help">Help</a>', main)
        self.assertIn(f'<a class="krow-a" href="{self.cat.account_url}">', main)
        self.assertIn('<a class="krow-a" href="/signout">', main)
        self.assertEqual([], re.findall(r"<a [^>]*>", footer_of(text)))   # rows moved up; the Home tab is the way back
        off = footer_of(self.off.get("/account", headers=ALL).text)
        self.assertIn(">Manage account</a>", off)
        self.assertIn(">Sign out</a>", off)


class HelpPages(Stub):
    def test_topics_are_the_members_own_rows_then_what_to_do(self):
        self.assertEqual(["/help/movies", "/help/requests", "/help/trouble"],
                         hrefs(main_of(self.page("/help", VIDEO)), "krow-a"))
        comics = main_of(self.page("/help", COMICS))
        self.assertEqual(["/help/comics", "/help/trouble"], hrefs(comics, "krow-a"))
        self.assertNotIn("Movies", comics)
        nolib = main_of(self.page("/help", NOLIB))
        self.assertIn("Nothing is set up on this account yet.", nolib)
        self.assertEqual(["/help/trouble"], hrefs(nolib, "krow-a"))

    def test_topic_content_and_anchors_are_kept(self):
        self.assertIn("Add server: https://watch.avrana.net", self.page("/help/movies"))
        trouble = main_of(self.page("/help/trouble"))
        for anchor in ("what", "sign-in", "app", "missing", "unavailable", "not-set-up", "back"):
            self.assertIn(f'id="{anchor}"', trouble)


class Hygiene(Stub):
    def test_no_script_no_inline_style_decorative_glyphs_and_csp_unchanged(self):
        for headers in (ALL, ADMIN_ONLY, NOLIB):
            for path in PAGES:
                r = self.on.get(path, headers=headers)
                if r.status_code == 404:          # /read for a member without a reading library
                    continue
                with self.subTest(path=path, who=headers[0][1]):
                    want = (CSP_SEARCH if path.startswith("/search") else CSP).decode() + SHELL_SOURCES
                    self.assertEqual(want, r.headers["content-security-policy"])
                    self.assertEqual("no-store", r.headers["cache-control"])
                    self.assertEqual(1, len(PAGE_SCRIPT.findall(r.text)))
                    t = PAGE_SCRIPT.sub("", r.text)
                    self.assertNotRegex(t, r"(?i)<script|javascript:|\son[a-z]+\s*=|\sstyle\s*=")
                    for svg in re.findall(r"<svg[^>]*>", t):
                        self.assertIn('aria-hidden="true"', svg)
                        self.assertIn('focusable="false"', svg)
                    # JS-off parity: every control is a real link, or the search form's own submit button
                    self.assertEqual(len(re.findall(r"<button", t)), len(re.findall(r"<form", t)))
                    if path != "/search":
                        self.assertNotIn("<form", t)
                    for href in re.findall(r'<a [^>]*href="([^"]*)"', t):
                        self.assertTrue(href.startswith(("/", "https://", "#main")), href)

    def test_the_search_form_keeps_its_contract(self):
        t = self.page("/search")
        self.assertIn('<form class="srch" method="get" action="/search" role="search">', t)
        self.assertIn('<label for="q">Title or author</label>', t)
        self.assertRegex(t, r'<input id="q" name="q" type="search" value="" maxlength="100" autocomplete="off" '
                            r'spellcheck="false" aria-describedby="q-hint">')
        self.assertIn('<button type="submit">Search</button>', t)

    def test_sections_off_pages_carry_none_of_it(self):
        for path in ("/account", "/help", "/help/movies", "/request"):
            t = self.off.get(path, headers=ALL).text
            for mark in ("krow", "kgroup", "kpanel", "<svg"):
                self.assertNotIn(mark, t, (path, mark))


class Stylesheet(unittest.TestCase):
    def setUp(self):
        css = (TEMPLATES / "home.css").read_text(encoding="utf-8")
        self.assertEqual(1, css.count(MARKER))
        self.block = css.split(MARKER, 1)[1].split("\n  /* ---- MK-", 1)[0]
        self.rules = re.sub(r"/\*.*?\*/", "", self.block, flags=re.S)

    def test_the_block_names_no_section_library_or_member_word(self):
        for word in ("Continue", "Resume", "Recently", "New this week", "Jellyfin", "Audiobook", "audiobook", "Komga", "komga", "Comic",
                     "comic", "Calibre", "calibre", "Movies", "movie", "Books", "books", "listen", "manga", "member-"):
            self.assertNotIn(word, self.block, word)

    def test_yellow_only_on_the_role_tag_and_focus_and_never_in_the_warning(self):
        accents = re.findall(r"([^{}]+)\{[^}]*var\(--accent\)", self.rules)
        self.assertEqual([".k-tag"], [a.strip() for a in accents])
        warn = re.search(r"\.said\.kwarn\{([^}]*)\}", self.rules).group(1)
        self.assertIn("border:1px solid var(--warn)", warn)
        self.assertNotIn("accent", warn)
        self.assertIn("color:var(--warn)", re.search(r"\.kwarn-ic\{([^}]*)\}", self.rules).group(1))
        for banned in ("#e8cf8a", "#b9a9e8", "purple", "--accent-selected", "--accent-lens"):
            self.assertNotIn(banned, self.rules.lower())
        # the yellow only ever through its token: no literal hex or channel values (comments included)
        for literal in ("eada6e", "234 218 110"):
            self.assertNotIn(literal, self.block.lower())

    def test_everything_here_is_opaque_and_loads_nothing(self):
        for banned in ("url(", "backdrop-filter", ".glass", "@import"):
            self.assertNotIn(banned, self.rules)

    def test_large_text_keeps_whole_words(self):
        self.assertNotIn("word-break:break-all", self.rules)
        self.assertNotIn("overflow-wrap:anywhere", re.search(r"\.krow-t\{([^}]*)\}", self.rules).group(1))
        self.assertIn("@media (max-width:18em){.krow-ic{display:none;}", self.rules)


class Mocks(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.ab = MockAudiobookshelf(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()
        cls.cw = MockCalibreWeb(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        for m in (cls.jf, cls.ab, cls.kg, cls.cw):
            m.stop()

    def setUp(self):
        for m in (self.jf, self.ab, self.kg, self.cw):
            m.set_mode("ok")
            m.reset()

    def client(self):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.ab.url, audiobookshelf_token=KEY,
                                      komga_base_url=self.kg.url, komga_token=KEY, calibre_web_base_url=self.cw.url,
                                      calibre_web_credential=CRED, timeout=self.timeout))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c


class SearchStates(Mocks):
    # Upstream users that exist in the mock fixtures (an unknown user would be "not set up", not "no results").
    VIDEO = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]
    CONTRIB = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|library-contributors")]

    def test_no_results_offers_only_the_members_own_request_routes(self):
        c = self.client()
        video = main_of(c.get("/search", params={"q": "zzqxnothingzz"}, headers=self.VIDEO).text)
        self.assertIn('<h3 class="kgroup-h" id="h-ask">Ask for it</h3>', video)
        self.assertEqual(1, video.count('<li class="krow kask">'))
        self.assertIn('href="https://request.avrana.net/search?query=zzqxnothingzz"', video)
        for word in ("requestabook", "requestacomic", "Contribute", "Audiobook", "Comic"):
            self.assertNotIn(word, video, word)
        comics = main_of(c.get("/search", params={"q": "zzqxnothingzz"}, headers=COMICS).text)
        self.assertEqual(['/requestacomic'], re.findall(r'<li class="krow kask">.*?href="([^"]*)"', comics))
        self.assertNotIn("request.avrana.net", comics)
        # the row leaves Avrana (our route redirects to the request site), so it says so, in words and with the glyph
        row = re.search(r'<li class="krow kask">(.*?)</li>', comics).group(1)
        self.assertIn('href="/requestacomic">Ask for a comic<span class="sr">, opens the request website</span></a>', row)
        self.assertIn('<span class="hint" aria-hidden="true">Opens the request website</span>', row)
        self.assertIn('class="kic krow-go"', row)
        # every offer that shows the external-link glyph also says it leaves, for every member
        for page in (video, comics):
            for li in re.findall(r'<li class="krow kask">(.*?)</li>', page):
                self.assertEqual("krow-go" in li, "opens the request website" in li)

    def test_contribute_joins_the_offers_only_for_a_member_who_has_it_and_only_with_no_results(self):
        c = self.client()
        mine = main_of(c.get("/search", params={"q": "zzqxnothingzz"}, headers=self.CONTRIB).text)
        self.assertIn('<a class="krow-a" href="/contribute">', mine)
        self.assertIn('<span class="sr">, opens a separate website</span>', mine)
        self.assertNotIn("/contribute", main_of(c.get("/search", params={"q": "zzqxnothingzz"}, headers=self.VIDEO).text))
        found = main_of(c.get("/search", params={"q": "Synthetic"}, headers=self.CONTRIB).text)
        self.assertNotIn("/contribute", found)
        self.assertNotIn("Ask for it", found)

    def test_a_library_that_could_not_answer_is_a_warning_in_words(self):
        c = self.client()
        self.jf.set_mode("500")
        a = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-books")]
        main = main_of(c.get("/search", params={"q": "Synthetic"}, headers=a).text)
        warn = re.search(r'<p class="said kwarn" role="status">(.*?)</p>', main, re.S).group(1)
        self.assertIn('class="kic kwarn-ic"', warn)
        self.assertIn("The Movies and TV library could not be searched right now.", warn)
        self.assertIn('href="/search?q=Synthetic">Try again', warn)
        self.assertIn("Synthetic Book One", main)               # the library that answered still shows
        # a member without that library is never told it exists, not even as down
        books = c.get("/search", params={"q": "Synthetic"}, headers=BOOKS).text
        self.assertNotIn("Movies", books)
        self.assertNotIn("kwarn\"", books)
        self.assertNotIn('class="said kwarn"', books)

    def test_nothing_answering_is_one_warning_and_never_no_results(self):
        c = self.client()
        self.jf.set_mode("500")
        main = main_of(c.get("/search", params={"q": "Synthetic"}, headers=self.VIDEO).text)
        self.assertEqual(1, main.count('class="said kwarn"'))
        self.assertIn("could not be searched right now", main)
        for word in ("No results", "Nothing found", "Ask for it"):
            self.assertNotIn(word, main, word)


class Isolation(Mocks):
    """Mirrors test_web_isolation_h2.py for the MK-5b pages: two members with different groups and upstream users."""
    A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")]
    B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-comics")]
    # "comic" alone is not a marker: the shared stylesheet's artwork shape class carries it on every shell page.
    A_ONLY = ("member-a", "Synthetic Film One", "Synthetic Film Three", "Audiobook", "requestabook", "/help/audiobooks",
              "aaaa0000")
    B_ONLY = ("member-b", "Synthetic Film Two", "Synthetic Film Four", "Comic", "manga", "requestacomic",
              "/help/comics", "bbbb0000")
    ROUTES = ("/me", "/account", "/help", "/request", "/search?q=zzqxnothingzz", "/search?q=Synthetic")

    def check(self, c, rnd):
        seen = {}
        for route in self.ROUTES:
            for who, headers, foreign in (("A", self.A, self.B_ONLY), ("B", self.B, self.A_ONLY)):
                r = c.get(route, headers=headers)
                self.assertEqual(200, r.status_code, (rnd, route, who))
                for marker in foreign:
                    self.assertNotIn(marker, r.text, f"{rnd} {route}: {who} saw {marker!r}")
                seen[(who, route)] = r.text
        return seen

    def test_no_name_library_or_result_crosses_members_cold_warm_and_with_an_upstream_down(self):
        c = self.client()
        seen = self.check(c, "cold")
        self.check(c, "warm")
        # sanity: each member really sees their own, so the absence above means something
        self.assertIn("Signed in as member-a", seen[("A", "/me")])
        self.assertIn("Signed in as member-b", seen[("B", "/me")])
        self.assertIn("/requestabook", seen[("A", "/request")])
        self.assertIn("/requestacomic", seen[("B", "/request")])
        self.assertIn("Synthetic Film One", seen[("A", "/search?q=Synthetic")])
        self.assertIn("Synthetic Film Two", seen[("B", "/search?q=Synthetic")])
        for mode in ("500", "wrong-user"):
            self.jf.set_mode(mode)
            self.check(c, mode)


if __name__ == "__main__":
    unittest.main()
