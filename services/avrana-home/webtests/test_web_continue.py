"""Tier B: Continue across two services through the real transport (Home 2.0, AVR-381). The mock Jellyfin and the
mock Audiobookshelf on loopback, SYNTHETIC fixtures only.

One failing service never blanks Home: Continue from the other keeps its cards, its Resume/Open verbs and its
remaining time, and the failing one says one neutral sentence naming only itself. The JSON view is what the page
is built from, so the card semantics are checked by building Home from it.
"""
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import build_home
from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_jellyfin import MockJellyfin

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

BOTH_A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")]
TILES = [("watch", Trusted("Watch"), Trusted("Movies")), ("listen", Trusted("Listen"), Trusted("Audiobooks"))]
FILM, BOOK = "Synthetic Film One", "Synthetic Audiobook One"
FILM_B, BOOK_B = "Synthetic Film Two", "Synthetic Audiobook Ten"     # member-b's, never member-a's


class Fixture(unittest.TestCase):
    timeout = 2.0

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.abs = MockAudiobookshelf(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.jf.stop()
        cls.abs.stop()

    def setUp(self):
        self.jf.set_mode("ok")
        self.abs.set_mode("ok")

    def client(self):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.abs.url,
                                      audiobookshelf_token="mock-api-key-not-real", timeout=self.timeout))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def home(self, c):
        page = c.get("/", headers=BOTH_A)
        self.assertEqual(200, page.status_code)
        view = c.get("/home.json", headers=BOTH_A).json()
        return page.text, build_home(view, TILES, limit=12)


class BothUp(Fixture):
    def test_continue_merges_both_with_resume_and_member_language(self):
        _text, home = self.home(self.client())
        by = {c.title: c for c in home.continue_items}
        self.assertIn(FILM, by)
        self.assertIn(BOOK, by)
        film, book = by[FILM], by[BOOK]
        self.assertEqual(("Resume", "Movie", "70 minutes left"), (film.action, film.kind_label, film.progress))
        self.assertEqual("Resume in Movies and TV", film.action_label)
        self.assertEqual(("Resume", "Audiobook", "5 hours 48 minutes left"), (book.action, book.kind_label, book.progress))
        self.assertTrue(film.href.startswith("https://watch.avrana.net/web/#/details?id="))
        self.assertTrue(book.href.startswith("https://listen.avrana.net/item/"))
        for c in home.continue_items:
            self.assertNotIn("Jellyfin", c.action_label)
            self.assertNotIn("Audiobookshelf", c.action_label)
            self.assertNotEqual("finished", c.progress)
        self.assertLessEqual(len(build_home({"sections": []}, TILES).continue_items), 4)


class OneServiceFailing(Fixture):
    def assert_other_survives(self, text, home, survivor, gone, sentence):
        titles = [c.title for c in home.continue_items]
        self.assertIn(survivor, titles)
        self.assertNotIn(gone, text)
        self.assertIn(sentence, text)
        self.assertNotIn("Traceback", text)
        self.assertTrue(all(c.action in ("Resume", "Open") for c in home.continue_items))

    def test_jellyfin_down_slow_or_malformed_keeps_audiobooks(self):
        for mode in ("down", "slow", "malformed", "500"):
            with self.subTest(mode=mode):
                self.jf.set_mode(mode)
                text, home = self.home(self.client())
                self.assert_other_survives(text, home, BOOK, FILM, "Movies and TV are unavailable right now.")

    def test_audiobookshelf_down_slow_or_malformed_keeps_movies(self):
        for mode in ("down", "slow", "malformed", "500"):
            with self.subTest(mode=mode):
                self.abs.set_mode(mode)
                text, home = self.home(self.client())
                self.assert_other_survives(text, home, FILM, BOOK, "Audiobooks are unavailable right now.")

    def test_jellyfin_answering_with_another_members_data_is_discarded_and_audiobooks_stay(self):
        self.jf.set_mode("wrong-user")
        text, home = self.home(self.client())
        self.assertNotIn(FILM_B, text)
        self.assertNotIn(BOOK_B, text)
        self.assertIn(BOOK, [c.title for c in home.continue_items])
        self.assertIn("Movies and TV are unavailable right now.", text)

    def test_both_failing_is_a_calm_page_with_a_way_on(self):
        self.jf.set_mode("down")
        self.abs.set_mode("500")
        text = self.client().get("/", headers=BOTH_A).text
        # Once, calmly: one combined line, not a line per library on top of the calm block (#13).
        self.assertEqual(1, text.count("None of your libraries is answering right now."))
        self.assertNotIn("Movies and TV are unavailable right now.", text)
        self.assertNotIn("Audiobooks are unavailable right now.", text)
        self.assertIn('href="/help/trouble#unavailable"', text)
        self.assertIn('href="/help"', text)


if __name__ == "__main__":
    unittest.main()
