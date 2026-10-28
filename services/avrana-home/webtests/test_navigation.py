"""Tier B: navigation and recovery with the Home shell on (Home 2.0, AVR-479). SYNTHETIC data, loopback only.

Every shell page has a way back to Home; the place pages (Read, Request, the Watch interstitial) explain what
happens and offer Help; an unavailable place is a link to what to do next, not a dead span; the "If something
doesn't open" topic exists only with the shell and names only the member's own libraries. With the shell off,
every one of these pages stays the portal's (test_web_parity.py), and /help/trouble is the standard 404.
"""
import re
import unittest

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

ALL = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books")]
VIDEO = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
COMICS = [(USER, "member-c"), (GROUPS, "avrana-users|avrana-comics")]
NOLIB = [(USER, "member-n"), (GROUPS, "avrana-users")]
OTHER_LIBRARIES = ("Audiobooks", "audiobook", "Comics", "comics", "Books", "books", "Listen", "/listen", "/read")
SHELL_PAGES = ["/", "/library", "/search", "/me", "/account", "/help", "/help/movies", "/help/trouble", "/read", "/request", "/watch"]


def footer(text):
    return text.split("<footer>", 1)[1].split("</footer>", 1)[0]


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = {"member-a": [("a" * 32, "Synthetic Nav Film", 0.5)]}
        cls.on = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)])
        cls.off = make_client(make_settings(home_sections=False))
        cls.on.__enter__()
        cls.off.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.on.__exit__(None, None, None)
        cls.off.__exit__(None, None, None)


class ReturnNavigationTests(Fixture):
    def test_every_shell_page_has_the_shell_and_a_way_home(self):
        lockup = (r'<h1><a href="/" aria-current="page"><img class="lockup" src="/brand/avrana-media-l3.svg" '
                  r'alt="Avrana Media" width="1384" height="650">'
                  r'<span class="lockup-text" aria-hidden="true">Avrana Media</span></a></h1>')
        home_button = ('<a class="homebtn glass" href="/"><img class="spire" src="/brand/spire-a-24.svg" alt="Home" '
                       'width="24" height="24"><span class="homebtn-text" aria-hidden="true">Home</span></a>')
        for path in SHELL_PAGES:
            with self.subTest(path=path):
                r = self.on.get(path, headers=ALL)
                self.assertEqual(200, r.status_code)
                # the Home tab is on every shell page (D1)
                self.assertRegex(r.text, r'<nav class="tabbar glass" aria-label="Sections"[^>]*>\s*<a class="tab" href="/"')
                if path == "/":
                    self.assertRegex(r.text, lockup)                          # L3 on Home (D5)
                    self.assertIn('<nav class="places" aria-label="Avrana">', r.text)   # kept on Home (D16)
                else:
                    self.assertNotRegex(r.text, r'<img class="lockup"')
                    # the tab bar's Home tab is the way back; no "Back to home" link (owner review 2026-10-27)
                    self.assertNotIn(">Back to home</a>", r.text)
                    # pages that are not tabs carry the glass Home button (D5); tab pages show their own title
                    if path in ("/library", "/search", "/me", "/account", "/help"):
                        self.assertNotIn('class="homebtn', r.text)
                    else:
                        self.assertIn(home_button, r.text)
                self.assertNotRegex(footer(r.text), r">Back<")          # one wording for return, everywhere

    def test_footers_never_repeat_the_masthead(self):
        """Search and Account (Me) are tabs, Help is a place on Home and a link on Account. The one exception is
        "All help" on a help topic, which is the way up one level from that topic, not a copy of a shell link."""
        for path in SHELL_PAGES:
            f = footer(self.on.get(path, headers=ALL).text).replace('href="/help">All help<', "")
            self.assertNotRegex(f, r'href="/(account|help|search)"', path)

    def test_me_is_the_one_way_to_account_and_help_is_a_step_from_it(self):
        text = self.on.get("/", headers=ALL).text
        bar = re.search(r'<nav class="tabbar.*?</nav>', text, flags=re.S).group(0)
        # Me opens the Me hub (AVR-719), which is the one way on to Account and Help
        self.assertEqual(1, bar.count('href="/me"'))
        self.assertNotIn('href="/account"', text)
        hub = main_of(self.on.get("/me", headers=ALL).text)
        self.assertIn('<a class="krow-a" href="/account">', hub)
        self.assertIn('<a class="krow-a" href="/help">', hub)
        self.assertIn('<span class="tl">Me<span class="sr">, signed in as member-a</span></span>', bar)
        self.assertNotIn('<details class="account">', text)
        self.assertNotIn('href="/account"', footer(text))        # the footer does not repeat the shell
        self.assertNotIn('href="/help"', footer(text))
        self.assertIn('href="/help/trouble"', footer(text))
        self.assertIn('<a class="link" href="/help">Help</a>', main_of(self.on.get("/account", headers=ALL).text))

    def test_place_pages_explain_and_offer_help(self):
        watch = self.on.get("/watch", headers=ALL).text
        self.assertIn("Before you continue", watch)
        self.assertIn("a separate website with its own sign-in", watch)
        self.assertIn("If you opened Avrana from your Home Screen", watch)        # no back button there
        self.assertIn('href="/help/movies"', main_of(watch))
        self.assertIn('href="/help/trouble"', main_of(watch))
        self.assertIn('href="https://watch.avrana.net"', main_of(watch))
        request = self.on.get("/request", headers=ALL).text
        self.assertIn("Ask for something that is missing from a library.", request)
        self.assertIn("Asking does not add it straight away", request)
        self.assertIn('href="/help/trouble"', footer(request))
        read = self.on.get("/read", headers=ALL).text
        self.assertIn("Each place below opens a separate library website", read)

    def test_chooser_intro_names_no_library(self):
        for path in ("/read", "/request"):
            text = main_of(self.on.get(path, headers=COMICS).text)
            intro = text.split('<nav class="tiles', 1)[0]
            for word in ("Movies", "Audiobook", "Books", "ebook", "film"):
                self.assertNotIn(word, intro, (path, word))

    def test_no_misleading_success_words(self):
        for path in SHELL_PAGES:
            text = main_of(self.on.get(path, headers=ALL).text).lower()
            for word in ("success", "playing now", "now playing", "started playing", "done!", "added!"):
                self.assertNotIn(word, text, (path, word))


class TroubleTopicTests(Fixture):
    def test_only_with_the_shell_and_otherwise_the_standard_404(self):
        nope = self.off.get("/nope", headers=ALL)
        r = self.off.get("/help/trouble", headers=ALL)
        self.assertEqual((404, nope.text), (r.status_code, r.text))
        anon = self.on.get("/help/trouble")
        self.assertEqual(404, anon.status_code)
        self.assertEqual(200, self.on.get("/help/trouble", headers=ALL).status_code)
        self.assertEqual(200, self.on.get("/help/trouble/", headers=ALL).status_code)

    def test_listed_in_help_and_linked_from_help_topics(self):
        self.assertIn('href="/help/trouble"', main_of(self.on.get("/help", headers=ALL).text))
        self.assertIn('href="/help/trouble"', footer(self.on.get("/help/movies", headers=ALL).text))
        self.assertNotIn("/help/trouble", self.off.get("/help", headers=ALL).text)

    def test_says_what_happens_and_covers_each_recovery_case(self):
        text = main_of(self.on.get("/help/trouble", headers=ALL).text)
        for anchor in ("what", "sign-in", "app", "missing", "unavailable", "not-set-up", "back"):
            self.assertIn(f'id="{anchor}"', text)
        self.assertIn("It does not start anything for you", text)
        self.assertIn("Movies and TV: sign in with your Avrana username and password.", text)
        self.assertIn("Audiobooks: sign in with the Avrana sign-in button.", text)

    def test_names_only_the_members_own_libraries(self):
        text = main_of(self.on.get("/help/trouble", headers=VIDEO).text)
        self.assertIn("Movies and TV", text)
        for word in OTHER_LIBRARIES:
            self.assertNotIn(word, text, word)

    def test_a_member_with_no_library_is_told_only_that(self):
        text = main_of(self.on.get("/help/trouble", headers=NOLIB).text)
        self.assertIn("No library is shared with this account yet.", text)
        for word in ("Movies", "Resume", "sign-in button") + OTHER_LIBRARIES:
            self.assertNotIn(word, text, word)


class UnavailablePlaceTests(unittest.TestCase):
    def test_a_struck_place_is_a_link_to_what_to_do_next(self):
        from dev.mock_jellyfin import MockJellyfin
        mock = MockJellyfin().start()
        self.addCleanup(mock.stop)
        mock.set_mode("500")
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=mock.url, timeout=1.0))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        text = c.get("/", headers=VIDEO).text
        self.assertIn('<a class="off" href="/help/trouble#unavailable"><s>Watch</s><span class="sr">, unavailable: what to do</span></a>',
                      text)
        self.assertNotIn('<span class="off">', text)
        self.assertIn('id="unavailable"', c.get("/help/trouble", headers=VIDEO).text)


if __name__ == "__main__":
    unittest.main()
