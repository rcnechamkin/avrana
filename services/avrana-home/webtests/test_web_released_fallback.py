"""Live beta 2026-10-29: Listen and Read answered 500 when their library had nothing added in two months. SYNTHETIC data.

Tier A (standard library): the Recently released fallback (Listen, Comics, Read) builds its rows without touching
All's New releases cards, so `released_items` stays empty on a filtered Home and stays cards on All.
Tier B (framework): each of those pages renders.
"""
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import CardVM, build_home

from .support import make_client, make_settings, require_framework

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


if __name__ == "__main__":
    unittest.main()
