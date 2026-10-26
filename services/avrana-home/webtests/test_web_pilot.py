"""The Home pilot (combined Home + Search + navigation + skip link): behaviours a member can see, through the
HTTP layer, for two synthetic members, against loopback mocks. Everything is synthetic."""
import re
import time
import unittest
from urllib.parse import quote

from dev.mock_calibre_web import MockCalibreWeb
from dev.mock_jellyfin import MockJellyfin
from dev.mock_komga import MockKomga

from avrana_home import contract
from avrana_home.app import viewmodel
from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import build_home, build_shell

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

CRED = "viewer:mock-api-key-not-real"
A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-books")]     # Movies and TV + Books
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos")]                  # Movies and TV only
NOTHING = [(USER, "member-x"), (GROUPS, "avrana-users")]
SHELL_ROUTES = ["/", "/search", "/account", "/help", "/help/movies"]


def mains(text):
    return len(re.findall(r"<main[\s>]", text))


def tabbar(text):
    """The tab bar (Concept K, AVR-716): after the footer, last in the page."""
    return re.search(r'<nav class="tabbar glass" aria-label="Sections".*?</nav>', text, re.S).group(0)


def aria_current(text):
    """(href, aria-current value) for everything in the masthead, the places bar and the tab bar that is marked."""
    head = text.split("<main", 1)[0] + tabbar(text)
    return re.findall(r'<a [^>]*href="([^"]*)"[^>]*aria-current="([^"]*)"', head)


class Mocks(unittest.TestCase):
    timeout = 1.0

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

    def client(self, **kw):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url, komga_base_url=self.kg.url,
                                      komga_token="mock-api-key-not-real", calibre_web_base_url=self.cw.url,
                                      calibre_web_credential=CRED, timeout=self.timeout, **kw))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c


class NavigationTests(Mocks):
    def test_every_shell_page_has_one_main_the_skip_link_the_shell_and_a_way_to_help(self):
        c = self.client()
        for who in (A, B):
            for route in SHELL_ROUTES:
                r = c.get(route, headers=who)
                with self.subTest(route=route, who=who[0][1]):
                    self.assertEqual(200, r.status_code)
                    t = r.text
                    self.assertEqual(1, mains(t))
                    self.assertIn('<a class="skip-link" href="#main">', t)
                    self.assertIn('<main id="main" tabindex="-1">', t)
                    self.assertIn('class="mast', t)
                    self.assertEqual(1, t.count('<nav class="tabbar glass" aria-label="Sections"'))
                    bar = tabbar(t)
                    self.assertIn('<a class="tab" href="/"', bar)
                    self.assertIn('<a class="tab" href="/search"', bar)      # Search is a tab (D1), never a sixth place
                    self.assertIn('<a class="tab" href="/account"', bar)
                    # the old top row (Search link, account disclosure) is gone: those are tabs now
                    self.assertNotIn('class="idlink"', t)
                    self.assertNotIn('<details class="account">', t)
                    if route == "/":
                        self.assertIn('<h1><a href="/"', t)
                        # Help is the last place in the places bar on Home (AVR-452, D16)
                        self.assertIn('href="/help"', re.search(r'<nav class="places".*?</nav>', t, re.S).group(0))
                    else:
                        self.assertIn('<h1 class="sr">Avrana Media</h1>', t)
                        self.assertNotIn('<nav class="places"', t)
        # elsewhere Help is one step away, from Me (Account)
        self.assertIn('href="/help"', c.get("/account", headers=A).text.split("<main", 1)[1].split("</main>", 1)[0])

    def test_the_current_page_is_marked_and_nothing_else_is(self):
        c = self.client()
        # "page" marks the tab (and on Home the lockup) that is this page; "true" marks the section a deeper page
        # belongs to: Help and its topics are reached from Me.
        want = {"/": [("/", "page"), ("/", "page")], "/search": [("/search", "page")],
                "/account": [("/account", "page")], "/help": [("/account", "true")],
                "/help/movies": [("/account", "true")]}
        for route, expected in want.items():
            with self.subTest(route=route):
                self.assertEqual(sorted(expected), sorted(aria_current(c.get(route, headers=A).text)))
        # the lens follows the same section, printed by the server so it is right without JavaScript
        at = {"/": "0", "/search": "2", "/account": "3", "/help": "3", "/help/movies": "3"}
        for route, index in at.items():
            self.assertIn(f'data-tabs="4" data-at="{index}"', tabbar(c.get(route, headers=A).text), route)

    def test_search_and_library_are_offered_only_to_a_member_with_a_library(self):
        c = self.client()
        for route in ("/", "/account", "/help"):
            t = c.get(route, headers=NOTHING).text
            self.assertNotIn('href="/search"', t, route)
            bar = tabbar(t)
            self.assertIn('data-tabs="2"', bar, route)
            self.assertEqual(["/", "/account"], re.findall(r'<a class="tab" href="([^"]*)"', bar), route)
        self.assertIn('href="/help"', re.search(r'<nav class="places".*?</nav>', c.get("/", headers=NOTHING).text, re.S).group(0))
        self.assertEqual(1, mains(c.get("/search", headers=NOTHING).text))

    def test_error_and_unknown_pages_stay_plain_and_have_one_main(self):
        t = self.client().get("/nope", headers=A).text
        self.assertEqual(1, mains(t))
        self.assertNotIn('class="mast"', t)

    def test_sections_off_leaves_the_portal_pages_without_the_shell(self):
        c = make_client(make_settings(home_sections=False))
        for route in ("/", "/account", "/help", "/help/movies"):
            t = c.get(route, headers=A).text
            self.assertNotIn('class="mast"', t, route)
            self.assertEqual(1, mains(t), route)
            self.assertIn('class="skip-link"', t, route)

    def test_the_tab_bar_is_the_same_markup_on_every_page_apart_from_what_marks_the_current_section(self):
        c = self.client()
        strip = lambda t: re.sub(r' (aria-current|data-at)="[a-z0-9]+"', "", tabbar(t))
        pages = [strip(c.get(r, headers=A).text) for r in SHELL_ROUTES]
        self.assertEqual(1, len(set(pages)))


class SearchBehaviourTests(Mocks):
    def search(self, who, term, client=None):
        return (client or self.client()).get("/search", params={"q": term}, headers=who)

    def test_the_term_stays_in_the_box_and_is_escaped(self):
        term = '"><script>alert(1)</script>'
        r = self.search(A, term)
        self.assertNotIn("<script>alert", r.text)
        self.assertIn('value="&#34;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"', r.text)
        self.assertNotIn(quote(term), r.text.split("<main")[0])

    def test_results_have_a_count_heading_and_never_echo_the_term_into_a_heading(self):
        for who in (A, B):
            t = self.search(who, "Synthetic").text
            heads = re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", t, re.S)
            self.assertTrue(any(re.fullmatch(r"\d+ results?", h) for h in heads), heads)
            self.assertFalse(any("Synthetic" in h for h in heads), heads)
        self.assertIn('id="h-outcome">No results<', self.search(A, "zzqxnothingzz").text)

    def test_one_result_is_singular(self):
        t = self.search(B, "Synthetic Film Two").text
        self.assertIn('id="h-outcome">1 result<', t)

    def test_the_outcome_is_in_the_page_title_so_it_is_announced_on_load(self):
        # A screen reader reads the <title> on a full page load; the term itself is never in it.
        self.assertIn("<title>1 result · Search · Avrana</title>", self.search(B, "Synthetic Film Two").text)
        self.assertIn("<title>No results · Search · Avrana</title>", self.search(A, "zzqxnothingzz").text)
        t = self.search(A, "Synthetic").text
        title = re.search(r"<title>(.*?)</title>", t).group(1)
        self.assertRegex(title, r"^\d+ results? · Search · Avrana$")

    def test_each_hit_has_exactly_one_action_and_groups_are_per_library(self):
        t = self.search(A, "Synthetic").text
        hits = re.findall(r'<li class="w-[a-z]+">.*?</li>', t, re.S)
        self.assertTrue(hits)
        self.assertEqual([1] * len(hits), [h.count("<a ") for h in hits])      # one link per result, no more
        self.assertRegex(t, r'<h3 id="g-1">Movies and TV</h3>')
        self.assertIn(">Books</h3>", t)
        self.assertNotIn("Comics", t)

    def test_an_unavailable_library_offers_try_again_that_reruns_the_same_search(self):
        self.jf.set_mode("500")
        t = self.search(A, "Synthetic", self.client()).text
        self.assertIn("The Movies and TV library could not be searched right now.", t)
        self.assertIn('<a class="link" href="/search?q=Synthetic">Try again', t)
        self.assertIn("Synthetic Book One", t)                  # the other library still answered
        again = self.client().get("/search?q=Synthetic", headers=A)
        self.assertEqual(200, again.status_code)

    def test_try_again_carries_the_term_percent_encoded(self):
        self.jf.set_mode("500")
        t = self.search(B, "a b&c", self.client()).text
        self.assertIn('href="/search?q=a%20b%26c"', t)

    def test_an_invalid_term_is_announced_and_described_and_not_searched(self):
        before = sum(len(m.paths()) for m in (self.jf, self.kg, self.cw))
        t = self.search(A, "**").text
        self.assertIn('aria-invalid="true" aria-describedby="q-error q-hint"', t)
        self.assertIn('<p class="err" id="q-error" role="alert">That search term cannot be used.</p>', t)
        self.assertNotIn("autofocus", t)
        self.assertEqual(before, sum(len(m.paths()) for m in (self.jf, self.kg, self.cw)))
        self.assertNotIn('id="h-outcome"', t)

    def test_the_hint_promises_only_what_clean_query_does(self):
        # #12: plain guidance, no list of regex characters. What it promises must still be exactly true:
        hint = viewmodel.SEARCH_HINT
        self.assertEqual(f"At least {contract.MIN_QUERY} characters.", hint)
        self.assertIsNone(contract.clean_query("a" * (contract.MIN_QUERY - 1)))      # fewer is refused
        self.assertEqual("ab", contract.clean_query("ab"))                            # that many is enough
        # ...and it names no character a member must avoid, because none makes a term unusable while letters
        # remain: each neutralised character becomes a space, the words around it are still searched.
        for ch in sorted(contract._QUERY_NEUTRALISED):
            self.assertNotIn(ch, hint, ch)
            self.assertEqual("ab cd", contract.clean_query(f"ab{ch}cd"), ch)
        t = self.search(A, "").text
        self.assertIn(f'<p class="hint" id="q-hint">Searches the libraries on your account. {hint}</p>', t)
        self.assertNotIn("treated as spaces", t)

    def test_a_member_without_a_searchable_library_is_told_calmly(self):
        t = self.search(NOTHING, "Synthetic").text
        self.assertIn("Search is not available on your account yet.", t)
        self.assertIn('<a class="link" href="/help">Help</a>', t)
        self.assertNotIn("<form", t)


class LibraryPresentationTests(unittest.TestCase):
    def view(self, *sections):
        return {"sections": list(sections)}

    TILES = [("watch", Trusted("Watch"), Trusted("Movies")), ("listen", Trusted("Listen"), Trusted("Audio")),
             ("help", Trusted("Help"), Trusted("Guides"))]

    @staticmethod
    def item(i, title, kind="movie", progress=None, series=None, subtitle=None, art=None):
        return {"id": f"x:{i}", "service": "x", "kind": kind, "title": title, "series": series, "subtitle": subtitle,
                "handoff_url": f"https://watch.avrana.net/web/#/details?id={i}", "progress": progress,
                "artwork": {"ref": art} if art else None}

    @staticmethod
    def sec(service, section, state, items=()):
        return {"service": service, "section": section, "state": state, "items": list(items), "reason": None}

    def test_a_member_with_exactly_one_library_has_no_all_tab(self):
        v = self.view(self.sec("jellyfin", "recent", "ok", [self.item(1, "Film")]))
        home = build_home(v, self.TILES)
        self.assertEqual(["jellyfin"], [k for k, _n, _c in home.new_tabs])
        self.assertTrue(home.new_tabs[0][2])
        self.assertEqual(["Film"], [c.title for c in home.new_items])

    def test_two_libraries_keep_all_first_and_current(self):
        v = self.view(self.sec("jellyfin", "recent", "ok", [self.item(1, "Film")]),
                      self.sec("audiobookshelf", "recent", "ok", [self.item(2, "Book", "audiobook")]))
        tabs = build_home(v, self.TILES).new_tabs
        self.assertEqual(["all", "jellyfin", "audiobookshelf"], [k for k, _n, _c in tabs])

    def test_cards_carry_a_secondary_line_and_progress_in_words(self):
        prog = {"position_seconds": 600, "duration_seconds": 4200}
        v = self.view(self.sec("jellyfin", "continue", "ok",
                               [self.item(1, "Pilot", "episode", prog, series="Synthetic Show", subtitle="S1 E1")]))
        card = build_home(v, self.TILES).continue_items[0]
        self.assertEqual("S1 E1 · Synthetic Show", card.line)      # episode marker first (Home 2.0, Lane B)
        self.assertEqual("1 hour left", card.progress)

    def test_art_has_a_frame_of_its_own_shape_and_a_letter_when_there_is_no_image(self):
        c = make_client(make_settings(home_sections=False))
        env = c.fastapi_app.state.env
        html = env.get_template("_parts.html").module.card(
            viewmodel.CardVM("Zebra", "https://x.example/1", "square", None, None))
        self.assertIn('<li class="w-square">', html)
        self.assertIn('<span class="frame"><span class="ph" aria-hidden="true">Z</span></span>', html)
        self.assertNotIn("<img", html)
        css = env.globals["home_stylesheet"]
        for shape, ratio in (("poster", "2/3"), ("square", "1"), ("still", "16/9"), ("comic", "13/20"), ("book", "2/3")):
            self.assertRegex(css, rf"\.w-{shape} \.frame[^}}]*aspect-ratio:{re.escape(ratio)}")

    @staticmethod
    def _name_of(link_html):
        """A rough accessible name from the link's content: aria-hidden parts dropped, tags removed, whitespace
        collapsed. It is only valid while the link has no aria-label/aria-labelledby, which the test asserts."""
        text = re.sub(r'<span [^>]*aria-hidden="true">[^<]*</span>', "", link_html)
        return " ".join(re.sub(r"<[^>]+>", "", text).split()).replace(" ,", ",")

    def test_a_card_is_one_link_with_the_full_title_and_one_action(self):
        env = make_client(make_settings(home_sections=False)).fastapi_app.state.env
        card = env.get_template("_parts.html").module.card
        long_title = "Synthetic Film: A Very Long Subtitle That Is Clamped to Two Lines (Extended Edition) <b>&"
        c = viewmodel.CardVM(long_title, "https://x.example/1", "poster", "Synthetic Series · S3 E10", None,
                             "1 hour 21 minutes left", kind_label="Movie", action="Resume")
        html = str(card(c, verb=True))
        self.assertEqual(1, html.count("<a "))                        # one link, no second control
        link = re.search(r"<a [^>]*>", html).group(0)
        self.assertNotRegex(link, r"aria-label|aria-labelledby")      # the content IS the name: nothing hides it
        self.assertEqual(1, html.count('<span class="go"><span class="sr">, </span>Resume</span>'))
        self.assertNotIn("<b>", html)                                  # still autoescaped
        # the full title first, then the line, progress and verb, each after a spoken comma
        self.assertEqual("Synthetic Film: A Very Long Subtitle That Is Clamped to Two Lines (Extended Edition) "
                         "&lt;b&gt;&amp;, Synthetic Series · S3 E10, 1 hour 21 minutes left, Resume",
                         self._name_of(html))
        self.assertRegex(html, r'class="t">[^<]*</span>\s*<span class="d"><span class="sr">, </span>Synthetic Series · S3 E10'
                               r'</span>\s*<span class="p"><span class="sr">, </span>1 hour 21 minutes left</span>\s*'
                               r'<span class="go"><span class="sr">, </span>Resume</span>\s*</a>')
        # an action_label stands in for the verb for assistive technology; the verb stays visible
        labelled = str(card(viewmodel.CardVM("Pilot", "https://x.example/2", "still", None, None, "40 minutes left",
                                             action="Resume", action_label="Resume, 40 minutes left"), verb=True))
        self.assertIn('<span class="go"><span class="sr">, </span><span aria-hidden="true">Resume</span>'
                      '<span class="sr">Resume, 40 minutes left</span></span>', labelled)
        self.assertNotRegex(re.search(r"<a [^>]*>", labelled).group(0), r"aria-label|aria-labelledby")
        self.assertEqual("Pilot, 40 minutes left, Resume, 40 minutes left", self._name_of(labelled))
        # New this week: no verb; the kind label stands in when there is no line
        new = str(card(viewmodel.CardVM("Book", "https://x.example/3", "book", None, None, kind_label="Book")))
        self.assertNotIn('class="go"', new)
        self.assertIn('<span class="d"><span class="sr">, </span>Book</span>', new)
        self.assertEqual("Book, Book", self._name_of(new))

    def test_titles_clamp_visually_and_rails_share_one_artwork_height(self):
        css = make_client(make_settings(home_sections=False)).fastapi_app.state.env.globals["home_stylesheet"]
        self.assertRegex(css, r"\.t\{[^}]*-webkit-line-clamp:2;line-clamp:2;overflow:hidden;")
        self.assertRegex(css, r"\.d\{[^}]*white-space:nowrap;overflow:hidden;text-overflow:ellipsis;")
        self.assertRegex(css, r"\.rail \.frame\{[^}]*height:var\(--fh\)[^}]*margin-top:calc\(var\(--art-h\) - var\(--fh\)\)")
        self.assertRegex(css, r"\.art\{[^}]*object-fit:contain")      # natural shape, never cropped
        self.assertNotIn("scrollbar-width:none", css.split(".rail{", 1)[1].split("}", 1)[0])
        # keyboard focus: the right scroll-padding leaves an optimal region one card wide, so a peeking card is
        # wholly outside it and Tab scrolls it fully into view (browser-checked by tests/ui/check_home_export.mjs)
        self.assertIn("scroll-padding-inline:var(--pad) max(var(--pad),calc(100% - var(--pad) - max(var(--cw),var(--wide-max)) - 0.5rem))", css)
        self.assertRegex(css, r"\.rail\{[^}]*scroll-snap-type:x mandatory;")      # cards rest card-aligned
        self.assertIn('.rail::after{content:"";flex:none;width:calc(100% - var(--cw) - 0.875rem);}', css)

    def test_the_shell_data_never_calls_anything_and_marks_current(self):
        shell = build_shell(self.TILES, "search", "Pat")
        self.assertTrue(shell.can_search)
        self.assertEqual("search", shell.current)
        self.assertTrue(all(p.up for p in shell.places))
        self.assertFalse(build_shell([self.TILES[2]], "home", "Pat").can_search)


class FailureRecoveryTests(Mocks):
    def test_unavailable_sections_offer_try_again_to_the_same_page(self):
        self.jf.set_mode("500")
        t = self.client().get("/", headers=A).text
        self.assertIn("Movies and TV are unavailable right now.", t)
        self.assertRegex(t, r'<p class="retry"><a class="link" href="/">Try again')
        self.assertNotIn("Your libraries are resting", t)

    def test_retry_keeps_the_chosen_new_tab(self):
        self.jf.set_mode("500")
        t = self.client().get("/?new=calibre-web", headers=A).text
        self.assertRegex(t, r'<p class="retry"><a class="link" href="/\?new=calibre-web">')

    def test_all_unavailable_is_a_calm_page_that_still_offers_help_and_account(self):
        for m in (self.jf, self.kg, self.cw):
            m.set_mode("500")
        for who in (A, B):
            r = self.client().get("/", headers=who)
            self.assertEqual(200, r.status_code)
            t = r.text
            self.assertIn("Your libraries are resting", t)
            self.assertRegex(t, r'<p class="retry"><a class="link" href="/">Try again')
            body = t.split("<main", 1)[1]
            self.assertIn('href="/account"', body)
            self.assertIn('href="/help"', body)
            self.assertNotIn("Traceback", t)
            self.assertEqual(1, mains(t))

    def test_one_hung_upstream_never_holds_the_page_past_the_hard_cap(self):
        self.jf.set_mode("slow")                       # answers after 3.0 s; the member-facing cap is shorter
        c = self.client()
        cap = self.timeout + 1.0                             # request timeout + the aggregate's margin
        t0 = time.monotonic()
        r = c.get("/", headers=A)
        took = time.monotonic() - t0
        self.assertEqual(200, r.status_code)
        self.assertLess(took, cap + 0.5, took)
        self.assertIn("Movies and TV are unavailable right now.", r.text)
        self.assertRegex(r.text, r'<p class="retry">')

    def test_a_hung_library_also_leaves_search_inside_the_cap(self):
        self.jf.set_mode("slow")
        c = self.client()
        t0 = time.monotonic()
        r = c.get("/search", params={"q": "Synthetic"}, headers=A)
        self.assertLess(time.monotonic() - t0, self.timeout + 1.6)
        self.assertEqual(200, r.status_code)
        self.assertIn("Try again", r.text)


if __name__ == "__main__":
    unittest.main()
