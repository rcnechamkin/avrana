"""Owner review 2026-10-29 (live beta): e-books in a Komga library belong with Books, not Comics. SYNTHETIC data only.

Tier A (standard library): a Komga e-book is filed under Books everywhere Home names a library (cards, hero, Recently
added tabs, Read's rows), still opens in Komga, and the comics beside it stay under Comics.
"""
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import build_home

TILES = [("read", Trusted("Read"), Trusted("Books and comics")), ("comics", Trusted("Comics"), Trusted("Comics")),
         ("books", Trusted("Books"), Trusted("Books")), ("listen", Trusted("Listen"), Trusted("Audio"))]
HOST = "https://read.avrana.net/book/"


def item(upstream, title, kind, subtitle=None, series=None, progress=None):
    return {"id": f"komga:{upstream}", "service": "komga", "kind": kind, "title": title, "subtitle": subtitle,
            "series": series, "handoff_url": HOST + upstream, "progress": progress,
            "artwork": {"ref": f"komga/book/{upstream}"}}


def sec(section, *items, state="ok"):
    return {"service": "komga", "section": section, "state": state, "items": list(items), "reason": None}


NOVEL = item("BOOKNOVEL001", "Synthetic Novel", "ebook", subtitle="Synthetic Author")
ISSUE = item("BOOKISSUE001", "Synthetic Saga #2", "comic", subtitle="#2", series="Synthetic Saga")
READING = {"fraction": 0.4, "percent": 40, "position_seconds": None, "duration_seconds": None}


class KomgaBooks(unittest.TestCase):
    def test_an_ebook_card_says_books_and_a_comic_card_says_comics(self):
        home = build_home({"sections": [sec("recent", NOVEL, ISSUE)]}, TILES)
        labels = {c.title: c.action_label for c in home.new_items}
        self.assertEqual(labels, {"Synthetic Novel": "Open in Books", "Synthetic Saga #2": "Open in Comics"})

    def test_recently_added_offers_a_books_tab_holding_the_ebook(self):
        home = build_home({"sections": [sec("recent", NOVEL, ISSUE)]}, TILES, new_tab="calibre-web")
        self.assertIn("calibre-web", [t[0] for t in home.new_tabs])
        self.assertEqual([c.title for c in home.new_items], ["Synthetic Novel"])

    def test_read_has_a_books_row_and_a_comics_row(self):
        home = build_home({"sections": [sec("recent", NOVEL, ISSUE)]}, TILES, focus="read")
        self.assertEqual({r.heading: [c.title for c in r.items] for r in home.rows},
                         {"Books": ["Synthetic Novel"], "Comics": ["Synthetic Saga #2"]})

    def test_the_hero_names_books_and_still_opens_komga(self):
        hero = build_home({"sections": [sec("continue", dict(NOVEL, progress=READING))]}, TILES).hero
        self.assertEqual((hero.title, hero.meta, hero.action, hero.action_href),
                         ("Synthetic Novel", "40 percent read · Books", "Read in Komga", HOST + "BOOKNOVEL001"))

    def test_a_komga_outage_is_still_a_comics_notice_only(self):
        home = build_home({"sections": [sec("recent", state="unavailable")]}, TILES)
        self.assertEqual(home.notices, ("Comics are unavailable right now.",))


if __name__ == "__main__":
    unittest.main()
