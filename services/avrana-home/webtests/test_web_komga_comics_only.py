"""F-01 (RC2 audit 2026-10-29): a Komga e-book belongs with Books WHEN the member has Books (owner decision
2026-10-29, #141/#143). A member with Comics alone has no Books library, so Home and Library never name one for
them and the e-book stays under Comics. A member with both sees the same book called a Book on Home, Library,
Search and its Details page. SYNTHETIC data only.
"""
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import books_held, build_home, build_library, build_search, build_title

COMICS_ONLY = [("comics", Trusted("Comics"), Trusted("Comics")), ("request", Trusted("Request"), Trusted("Ask"))]
BOTH = [("read", Trusted("Read"), Trusted("Books and comics")), ("comics", Trusted("Comics"), Trusted("Comics")),
        ("books", Trusted("Books"), Trusted("Books"))]
HOST = "https://read.avrana.net/book/"


def item(n, kind):
    up = f"BOOK{n:08d}"
    return {"id": f"komga:{up}", "service": "komga", "kind": kind, "title": f"Synthetic {kind} {n}", "series": None,
            "subtitle": None, "creator": "Synthetic Author", "handoff_url": HOST + up, "progress": None,
            "artwork": None, "added": "2026-10-28"}


COMIC, EBOOK = item(1, "comic"), item(2, "ebook")
VIEW = {"sections": [{"service": "komga", "section": "recent", "state": "ok", "reason": None,
                      "items": [COMIC, EBOOK]}]}
SEARCH = {"status": "ok", "entitled": True,
          "groups": [{"service": "komga", "state": "ok", "items": [COMIC, EBOOK]}]}
TITLE = {"service": "komga", "section": "item", "state": "ok", "items": [EBOOK], "reason": None}


def tabs(home):
    return {label: key for key, label, _cur in home.new_tabs}


class ComicsOnlyMember(unittest.TestCase):
    def test_there_is_no_books_place(self):
        self.assertFalse(books_held(COMICS_ONLY))
        self.assertTrue(books_held(BOTH))

    def test_new_tabs_name_no_books_library(self):
        # Comics is the member's only library, so the tabs are Comics alone (All is not offered for one library).
        home = build_home(VIEW, COMICS_ONLY, today="2026-10-29")
        self.assertEqual(["Comics"], [label for _k, label, _c in home.new_tabs])

    def test_the_ebook_is_visible_under_comics(self):
        home = build_home(VIEW, COMICS_ONLY, today="2026-10-29", new_tab="komga")
        self.assertEqual(["Synthetic comic 1", "Synthetic ebook 2"], [c.title for c in home.new_items])
        self.assertTrue(all("Books" not in (c.action_label or "") for c in home.new_items), [c for c in home.new_items])

    def test_library_chips_are_all_and_comics_and_the_ebook_stays_in_komga(self):
        lib = build_library(VIEW, COMICS_ONLY)
        self.assertEqual(["All", "Comics"], [c.label for c in lib.chips])
        self.assertNotIn("Books", repr(lib.shelves))
        self.assertIn("Synthetic ebook 2", repr(lib.shelves))


class MemberWithBothLibraries(unittest.TestCase):
    def test_home_new_tabs_offer_books_holding_the_ebook(self):
        home = build_home(VIEW, BOTH, today="2026-10-29", new_tab="calibre-web")
        self.assertEqual(["All", "Comics", "Books"], [label for _k, label, _c in home.new_tabs])
        self.assertEqual(["Synthetic ebook 2"], [c.title for c in home.new_items])

    def test_library_has_a_books_chip(self):
        self.assertEqual(["All", "Comics", "Books"], [c.label for c in build_library(VIEW, BOTH).chips])

    def test_search_groups_the_ebook_under_books(self):
        page = build_search(SEARCH, "synthetic", books=books_held(BOTH))
        by = {g.label: [r.title for r in g.items] for g in page.groups}
        self.assertEqual({"Comics": ["Synthetic comic 1"], "Books": ["Synthetic ebook 2"]}, by)

    def test_search_for_comics_only_keeps_one_comics_group(self):
        page = build_search(SEARCH, "synthetic", books=books_held(COMICS_ONLY))
        by = {g.label: [r.title for r in g.items] for g in page.groups}
        self.assertEqual({"Comics": ["Synthetic comic 1", "Synthetic ebook 2"]}, by)

    def test_title_page_calls_it_a_book_in_books(self):
        page = build_title(TITLE, "komga", "BOOK00000002", None, books=True)
        self.assertEqual("Books", page.library)
        self.assertEqual("Books", page.kicker)
        self.assertIn("in Books", page.action_label)

    def test_title_page_for_comics_only_stays_in_comics(self):
        page = build_title(TITLE, "komga", "BOOK00000002", None, books=False)
        self.assertEqual("Comics", page.library)
        self.assertIn("in Comics", page.action_label)


if __name__ == "__main__":
    unittest.main()
