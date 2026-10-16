"""Tier B: the Home 2.0 polish pass. Cross-lane consistency found by the end-to-end review, each pinned here so it
cannot drift back. SYNTHETIC data, loopback only.

  1  Help describes the real verb rule (Resume, then Watch/Listen/Read/Open, then a card with no verb).
  2  The title page and Continue agree on Resume (viewmodel.continue_state): a fraction with no position is Open.
  3  "Not set up" is never a dead end: Home, Search and the title page link /help/trouble#not-set-up.
  5  Account's "Your access" (shell only): Libraries and Requests in Home's language, each name once.
  7  The trouble topic does not send a member to a struck place, and has one "Back to home".
  8  Search: what a screen reader hears for a result that leaves matches what is shown.
  9  Help's index has a heading like the other shell pages.
 10  Help topics wrap the "Recommended" tag instead of pushing the page sideways (shell CSS only).
 11  The Watch interstitial speaks member language in the shell; the portal's own page is unchanged.
 13  Small things: the title kicker, the results heading sizes, dead CSS.
"""
import re
import unittest

from avrana_home.app import recovery, viewmodel
from avrana_home.app.viewmodel import account_access, build_home, build_title, kicker_of
from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_jellyfin import MockJellyfin

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

EVERYTHING = "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"
ALL = [(USER, "member-a"), (GROUPS, EVERYTHING)]
VIDEO = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
BOOKS = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-books")]
AUDIO = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-audiobooks")]
UNSET = [(USER, "member-c"), (GROUPS, "avrana-users|avrana-videos")]      # Jellyfin account disabled (mock)
ABS_A = "aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa"                            # member-a in the synthetic ABS fixtures


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def footer(text):
    return text.split("<footer>", 1)[1].split("</footer>", 1)[0]


class StubFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = {"member-a": [("a" * 32, "Synthetic Polish Film", 0.5)]}
        cls.on = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)])
        cls.off = make_client(make_settings(home_sections=False))
        cls.on.__enter__()
        cls.off.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.on.__exit__(None, None, None)
        cls.off.__exit__(None, None, None)


class VerbRuleInHelp(StubFixture):
    def test_help_states_the_rule_title_pages_and_cards_follow(self):
        text = main_of(self.on.get("/help/trouble", headers=ALL).text)
        self.assertIn("Resume means that library saved where you stopped. Watch, Listen, Read and Open open the "
                      "item&#39;s page in its library. A card with no word on it opens the item too.", text)
        self.assertNotIn("always say Open", text)                      # the old claim title pages contradicted

    def test_the_verbs_named_are_only_the_members_own(self):
        for who, verbs in ((VIDEO, "Watch and Open"), (BOOKS, "Read and Open"), (AUDIO, "Listen and Open")):
            text = main_of(self.on.get("/help/trouble", headers=who).text)
            self.assertIn(f"stopped. {verbs} open the item", text, verbs)


class TroubleCopy(StubFixture):
    def test_unavailable_does_not_point_at_a_struck_place_and_back_to_home_is_once(self):
        r = self.on.get("/help/trouble", headers=ALL)
        self.assertNotIn("from its place at the top of the page", r.text)
        unavailable = r.text.split('id="unavailable"', 1)[1].split("</section>", 1)[0]
        self.assertIn("You can still try opening the library itself with the links below.", unavailable)
        self.assertIn('<a class="link" href="/watch">Open Movies and TV</a>', unavailable)
        self.assertEqual(1, r.text.count(">Back to home</a>"))
        self.assertIn('<a class="link" href="/">Back to home</a>', footer(r.text))
        self.assertIn('id="not-set-up"', r.text)                   # the anchor the not-set-up links use
        nolib = self.on.get("/help/trouble", headers=[(USER, "member-n"), (GROUPS, "avrana-users")])
        self.assertEqual(1, nolib.text.count(">Back to home</a>"))


class ResumeAgreement(unittest.TestCase):
    """#2: one rule for Resume. A fraction without a saved position is Open on the title page AND on Continue, with
    the progress in words on both."""
    ITEM = {"id": "audiobookshelf:li_book000001", "service": "audiobookshelf", "kind": "audiobook",
            "title": "Synthetic Listen", "handoff_url": "https://listen.avrana.net/item/li_book000001",
            "progress": {"fraction": 0.42, "percent": 42, "position_seconds": None, "duration_seconds": None}}

    def test_fraction_without_position_is_open_with_percent_on_both(self):
        section = {"service": "audiobookshelf", "section": "item", "state": "ok", "items": [self.ITEM]}
        page = build_title(section, "audiobookshelf", "li_book000001", None)
        self.assertEqual(("Open", "42 percent listened"), (page.action, page.progress))
        home = build_home({"sections": [dict(section, section="continue")]},
                          [("listen", "Listen", "Audiobooks"), ("help", "Help", "Guides")])
        card = home.continue_items[0]
        self.assertEqual(("Open", "42 percent listened"), (card.action, card.progress))

    def test_a_saved_position_is_resume_on_both_and_nothing_is_the_kind_verb(self):
        saved = dict(self.ITEM, progress={"fraction": 0.42, "percent": 42, "position_seconds": 15120,
                                          "duration_seconds": 36000})
        section = {"service": "audiobookshelf", "section": "item", "state": "ok", "items": [saved]}
        self.assertEqual("Resume", build_title(section, "audiobookshelf", "li_book000001", None).action)
        home = build_home({"sections": [dict(section, section="continue")]}, [("listen", "Listen", "Audiobooks")])
        self.assertEqual("Resume", home.continue_items[0].action)
        fresh = {"service": "audiobookshelf", "section": "item", "state": "ok", "items": [dict(self.ITEM, progress=None)]}
        page = build_title(fresh, "audiobookshelf", "li_book000001", None)
        self.assertEqual(("Listen", None), (page.action, page.progress))
        done = dict(self.ITEM, progress={"fraction": 1.0, "percent": 100, "position_seconds": None,
                                         "duration_seconds": None})
        page = build_title(dict(fresh, items=[done]), "audiobookshelf", "li_book000001", None)
        self.assertEqual(("Listen", None), (page.action, page.progress))      # finished: no "nearly finished"


class ResumeAgreementThroughTheAdapter(unittest.TestCase):
    """The same, end to end: the synthetic Audiobookshelf reports progress 0.42 with no currentTime."""

    @classmethod
    def setUpClass(cls):
        cls.ab = MockAudiobookshelf().start()

    @classmethod
    def tearDownClass(cls):
        cls.ab.stop()

    def test_title_and_continue_both_say_open_with_percent(self):
        rec = self.ab.fake.record(ABS_A)
        for mp in rec["mediaProgress"]:
            if mp["libraryItemId"] == "li_book000001":
                mp.pop("currentTime", None)
        self.ab.fake.serve("/api/users/" + ABS_A, rec)
        self.addCleanup(self.ab.fake.overrides.clear)
        c = make_client(make_settings(home_sections=True, audiobookshelf_base_url=self.ab.url,
                                      audiobookshelf_token="mock-api-key-not-real", timeout=1.5))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        title = c.get("/title/audiobookshelf/li_book000001", headers=AUDIO).text
        self.assertRegex(title, r'aria-label="Open [^"]* in Audiobooks">Open</a>')
        self.assertIn("42 percent listened", title)
        self.assertNotIn(">Resume</a>", title)
        home = c.get("/", headers=AUDIO).text
        card = re.search(r'<a class="card" href="https://listen\.avrana\.net/item/li_book000001">.*?</a>', home, re.S)
        self.assertIsNotNone(card)
        self.assertIn("42 percent listened", card.group(0))
        self.assertIn('<span aria-hidden="true">Open</span>', card.group(0))


class NotSetUpIsNotADeadEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin().start()

    @classmethod
    def tearDownClass(cls):
        cls.jf.stop()

    def client(self):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url, timeout=1.5))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def test_home_search_and_title_link_the_not_set_up_help(self):
        c = self.client()
        home = main_of(c.get("/", headers=UNSET).text)
        self.assertIn('<h2 id="h-setup">Not set up yet</h2>', home)
        self.assertIn('href="/help/trouble#not-set-up"', home)
        search = main_of(c.get("/search", params={"q": "Synthetic"}, headers=UNSET).text)
        self.assertIn("Not searched", search)
        self.assertIn('href="/help/trouble#not-set-up"', search)
        self.assertNotIn('href="/help"', search)
        title = main_of(c.get("/title/jellyfin/aaaa0000000000000000000000000001", headers=UNSET).text)
        self.assertIn("The Movies and TV library is not set up for your account yet.", title)
        self.assertIn('<a class="link" href="/help/trouble#not-set-up">What to do next</a>', title)
        self.assertNotIn("See Help", title)
        self.assertIn('id="not-set-up"', c.get("/help/trouble", headers=UNSET).text)


class AccountAccess(StubFixture):
    def section(self, text):
        return text.split("<h2>Your access</h2>", 1)[1].split("</section>", 1)[0]

    def test_libraries_and_requests_in_home_language_each_once(self):
        acc = self.section(self.on.get("/account", headers=ALL).text)
        libs = acc.split('<h3 class="sub">Requests</h3>')[0]
        reqs = acc.split('<h3 class="sub">Requests</h3>')[1].split('<h3 class="sub">Also</h3>')[0]
        items = lambda part: re.findall(r"<li>([^<]*)</li>", part)   # noqa: E731
        self.assertEqual(["Movies and TV", "Audiobooks", "Comics", "Books"], items(libs))
        self.assertEqual(["Movies and TV", "Audiobooks", "Comics", "Books"], items(reqs))
        self.assertEqual(["Send to Kindle"], items(acc.split('<h3 class="sub">Also</h3>')[1]))
        for portal_word in ("Movies &amp; TV", "Movies &amp;amp; TV", "<li>Watch</li>", "<li>Listen</li>",
                            "<li>Kindle</li>"):
            self.assertNotIn(portal_word, acc)

    def test_a_books_member_never_reads_audiobooks(self):
        acc = self.section(self.on.get("/account", headers=BOOKS).text)
        self.assertNotIn("Audiobook", acc)
        self.assertEqual(["Books", "Books", "Send to Kindle"], re.findall(r"<li>([^<]*)</li>", acc))

    def test_pure_function_dedupes_and_adds_nothing(self):
        vm = account_access([("watch", "Watch"), ("requests", "Movies &amp; TV"), ("ops", "Operations")],
                            {"avrana-videos"})
        self.assertEqual((("Movies and TV",), ("Movies and TV",), ("Operations",)),
                         (vm.libraries, vm.requests, vm.other))
        self.assertEqual(((), (), ()), tuple(tuple(x) for x in vars(account_access([], set())).values()))

    def test_sections_off_account_is_still_the_portals(self):
        text = self.off.get("/account", headers=ALL).text
        self.assertNotIn('class="sub"', text)
        self.assertIn("<li>Watch</li>", text)                 # the portal's own list (parity test checks bytes)


class HelpIndexAndTopics(StubFixture):
    def test_shell_help_index_has_an_h2_and_the_portal_one_does_not(self):
        self.assertIn('<h2 class="topic">Help</h2>', main_of(self.on.get("/help", headers=ALL).text))
        self.assertNotIn('<h2 class="topic">Help</h2>', self.off.get("/help", headers=ALL).text)

    def test_topic_client_row_wraps_in_the_shell_only(self):
        on = self.on.get("/help/movies", headers=ALL).text
        self.assertIn(".client>div{display:flex;flex-wrap:wrap;", on)
        self.assertNotIn(".client>div{", self.off.get("/help/movies", headers=ALL).text)


class WatchInterstitial(StubFixture):
    def test_shell_uses_member_language_and_portal_is_unchanged(self):
        on = main_of(self.on.get("/watch", headers=ALL).text)
        self.assertIn("Apps and setup for Movies and TV", on)
        self.assertNotIn("Apps and setup for Watch", on)
        self.assertIn("For the most stable playback, use the Jellyfin app on your device.", on)
        self.assertNotIn("It is advised", on)
        off = self.off.get("/watch", headers=ALL).text
        self.assertIn("Apps and setup for Watch", off)
        self.assertIn("It is advised to use the Jellyfin app for the most stable playback.", off)


class SearchScreenReaderText(unittest.TestCase):
    def test_a_result_that_leaves_says_opens_in_like_the_visible_text(self):
        from avrana_home.app.main import make_environment
        from avrana_home.app.viewmodel import ResultVM, SearchGroupVM, SearchVM
        hit = ResultVM("Synthetic Book", "https://books.avrana.net/book/1", "Book", "Book", "book", None, opens="Books")
        page = SearchVM("results", term="Synthetic", found=1, outcome="1 result", result_state="found",
                        groups=(SearchGroupVM("calibre-web", "Books", "ok", (hit,)),))
        html = make_environment().get_template("search.html").render(page=page, shell=None)
        self.assertIn('Synthetic Book<span class="sr">, Book, opens in Books</span></a>', html)
        self.assertIn('<span class="d" aria-hidden="true">Opens in Books</span>', html)


class SmallThings(unittest.TestCase):
    def test_kicker_drops_a_medium_the_library_name_already_says(self):
        self.assertEqual("Movies and TV", kicker_of("Movie", "Movies and TV"))
        self.assertEqual("Episode · Movies and TV", kicker_of("Episode", "Movies and TV"))
        self.assertEqual("Series · Movies and TV", kicker_of("Series", "Movies and TV"))
        self.assertEqual("Audiobooks", kicker_of("Audiobook", "Audiobooks"))
        self.assertEqual("Books", kicker_of("Book", "Books"))
        self.assertEqual("Comics", kicker_of("Comic", "Comics"))
        self.assertEqual("Books", kicker_of("", "Books"))

    def test_results_group_heading_is_not_larger_than_the_section_label_and_dead_css_is_gone(self):
        from pathlib import Path
        css = (Path(viewmodel.__file__).parent / "templates" / "home.css").read_text(encoding="utf-8")
        h3 = float(re.search(r"\.found h3\{[^}]*font-size:([\d.]+)rem", css).group(1))
        self.assertLessEqual(h3, 1.0)
        self.assertNotIn("ul.hits a.open", css)

    def test_recovery_names_only_held_libraries_verbs(self):
        text = repr(recovery.build_trouble({"avrana-comics"}))
        self.assertIn("Read and Open", text)
        for word in ("Watch", "Listen", "Movies", "Audiobooks"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
