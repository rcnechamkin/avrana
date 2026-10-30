"""Live beta 2026-10-29: Listen and Read answered 500 when their library had nothing added in two months. SYNTHETIC data.

Tier A (standard library): the Recently released fallback (Listen, Comics, Read) builds its rows without touching
All's New releases cards, so `released_items` stays empty on a filtered Home and stays cards on All.
Tier B (framework): each of those pages renders, and (T-02, coverage review 2026-10-29) the same state is requested
THROUGH HTTP, which is where the live 500 happened.
"""
import re
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import CardVM, build_home

from .support import GROUPS, USER, make_client, make_settings, require_framework

TILES = [("watch", Trusted("Watch"), Trusted("Movies")), ("listen", Trusted("Listen"), Trusted("Audio")),
         ("read", Trusted("Read"), Trusted("Books and comics")), ("comics", Trusted("Comics"), Trusted("Comics")),
         ("books", Trusted("Books"), Trusted("Books"))]
HOST = {"audiobookshelf": "https://listen.avrana.net/item/", "komga": "https://read.avrana.net/book/",
        "calibre-web": "https://books.avrana.net/book/"}
KIND = {"audiobookshelf": "audiobook", "komga": "comic", "calibre-web": "ebook"}


def item(service, upstream, shelf=None):
    out = {"id": f"{service}:{upstream}", "service": service, "kind": KIND[service], "title": f"Synthetic {upstream}",
           "series": None, "subtitle": None, "handoff_url": HOST[service] + upstream, "progress": None,
           "artwork": None, "released": "2025-01-01"}
    if shelf:
        out["shelf"] = shelf
    return out


def sec(service, section, *items):
    return {"service": service, "section": section, "state": "ok" if items else "empty", "items": list(items),
            "reason": None}


# Nothing added lately to Audiobookshelf or Komga; their shelves still hold the newest releases.
VIEW = {"sections": [sec("audiobookshelf", "recent"), sec("komga", "recent"),
                     sec("audiobookshelf", "shelves", item("audiobookshelf", "li_0001", "new"),
                         item("audiobookshelf", "li_0002", "classics")),
                     sec("komga", "shelves", item("komga", "BOOKNEW00001", "new")),
                     sec("calibre-web", "recent", item("calibre-web", "12")),
                     sec("audiobookshelf", "released", item("audiobookshelf", "li_0001"))]}
EXPECTED = {"listen": ["Recently released", "Classics"], "comics": ["Recently released"],
            "read": ["Recently released comics", "Books"]}


class Fallback(unittest.TestCase):
    def test_a_filtered_home_with_nothing_new_shows_recently_released_and_no_all_releases(self):
        for focus, headings in EXPECTED.items():
            home = build_home(VIEW, TILES, focus=focus)
            self.assertEqual(headings, [r.heading for r in home.rows], focus)
            self.assertEqual((), home.released_items, focus)

    def test_all_keeps_its_new_releases_cards(self):
        home = build_home(VIEW, TILES)
        self.assertTrue(home.released_items)
        self.assertTrue(all(isinstance(c, CardVM) for c in home.released_items))


class Markup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def test_listen_comics_and_read_render(self):
        for focus, headings in EXPECTED.items():
            html = self.env.get_template("_sections.html").render(home=build_home(VIEW, TILES, focus=focus))
            for heading in headings:
                self.assertIn(f">{heading}</h2>", html, focus)
            self.assertNotIn('id="h-released"', html, focus)


def headings(text):
    return re.findall(r"<h2[^>]*>([^<]*)</h2>", main_of(text))


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text, maxsplit=1)[1].split("</main>")[0]


class Routes(unittest.TestCase):
    """Tier B, T-02: the exact #146 shape through the real app. Audiobooks and Comics have NOTHING in Continue or Recently
    added; their shelves and released lists are fine. Every filtered page answers 200 with its headings, and a card
    appears once. SYNTHETIC adapters (plan_adapters.py), no mock server."""

    @classmethod
    def setUpClass(cls):
        require_framework()
        from avrana_home.contract import Service
        from jinja2 import StrictUndefined

        from .plan_adapters import ALL_GROUPS, COMICS_GROUPS, adapters_for
        empty = {"recent": "empty", "continue": "empty"}
        cls.ALL = [(USER, "member-a"), (GROUPS, ALL_GROUPS)]
        cls.COMICS = [(USER, "comics-a"), (GROUPS, COMICS_GROUPS)]
        cls.client = make_client(make_settings(home_sections=True),
                                 adapters=adapters_for({Service.AUDIOBOOKSHELF: empty, Service.KOMGA: empty}))
        cls.client.fastapi_app.state.env.undefined = StrictUndefined
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def page(self, url, headers=None):
        r = self.client.get(url, headers=headers or self.ALL)
        self.assertEqual(200, r.status_code, url)
        for word in ("Traceback", "UndefinedError", "Something went wrong"):
            self.assertNotIn(word, r.text, url)
        self.assertEqual(1, len(re.findall(r"<main[\s>]", r.text)), url)
        return r.text

    def assertCardsOnce(self, text, url, some=True):
        hrefs = re.findall(r'<a class="card(?: stack)?" href="([^"]*)"', main_of(text))
        if some:
            self.assertTrue(hrefs, url)
        self.assertEqual([], sorted({h for h in hrefs if hrefs.count(h) > 1}), url)

    def test_listen_and_read_show_their_expected_headings_and_no_all_releases(self):
        for focus, expected in (("listen", EXPECTED["listen"]), ("read", EXPECTED["read"])):
            url = f"/?for={focus}"
            with self.subTest(url=url):
                text = self.page(url)
                found = headings(text)
                for heading in expected:
                    self.assertIn(heading, found)
                self.assertNotIn('id="h-released"', text)
                self.assertNotIn("New Releases", found)
                self.assertCardsOnce(text, url)
                for heading in found:
                    self.assertTrue(heading.strip(), url)

    def test_listen_shelves_follow_recently_released_in_order(self):
        found = headings(self.page("/?for=listen"))
        self.assertEqual(["Recently released", "Classics", "Short listens", "Epic listens"], found[-4:])

    def test_comics_and_books_filters_answer_without_all_releases(self):
        # This member holds Read as ONE place, so `comics` and `books` are not filters of their own: they come back as All
        # (the All chip is current) and Home asks no extras. They must not 500 and must not print New Releases.
        for url in ("/?for=comics", "/?for=books"):
            with self.subTest(url=url):
                text = self.page(url)
                self.assertNotIn('id="h-released"', text)
                self.assertIn('aria-current="true">All', text)
        for url in ("/?for=comics", "/"):
            with self.subTest(url=url, member="comics-only"):
                text = self.page(url, self.COMICS)
                self.assertIn("Continue", headings(text))
                self.assertCardsOnce(text, url, some=url == "/")

    def test_the_audiobooks_library_chip_answers(self):
        # OBSERVATION (reported, not pinned): with Recently added empty the Audiobooks chip says "Nothing added to Audiobooks
        # recently." and shows none of the shelves the library does hold; the Listen filter on Home does show them.
        url = "/library?lib=audiobookshelf"
        text = self.page(url)
        self.assertIn("Audiobooks", headings(text))
        self.assertNotIn('id="h-released"', text)
        self.assertCardsOnce(text, url, some=False)
        for view in ("shelves", "grid", "compact", "list"):
            with self.subTest(view=view):
                self.assertCardsOnce(self.page(url + "&view=" + view), url + view, some=False)


if __name__ == "__main__":
    unittest.main()
