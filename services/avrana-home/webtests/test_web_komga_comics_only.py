"""F-01 (RC2 audit 2026-10-29): a Komga e-book belongs with Books WHEN the member has Books (owner decision
2026-10-29, #141/#143). "Has Books" is the avrana-books group, NOT Home's tiles: the Read tile is every Comics
member's, so tiles cannot tell the two apart. A member with Comics alone never sees a Books library named; a member
with both sees the same book called a Book on Home, Library, Search and its Details page. SYNTHETIC data only.

The view-model tests use the tiles the REAL catalogue gives each set of groups (`decide`); the HTTP tests drive the
app with a mock Komga that holds one synthetic EPUB.
"""
import re
import unittest

from avrana_home.app import catalogue as catalogue_mod
from avrana_home.app.routing import decide
from avrana_home.app.settings import DEFAULT_CATALOGUE
from avrana_home.app.viewmodel import build_home, build_library, build_search, build_title
from dev.mock_komga import MockKomga

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

CAT = catalogue_mod.load(DEFAULT_CATALOGUE)
COMICS_G = frozenset({"avrana-users", "avrana-comics"})
BOTH_G = frozenset({"avrana-users", "avrana-comics", "avrana-books"})


def tiles(groups):
    return decide("/", groups, CAT).context["tiles"]


HOST = "https://read.avrana.net/book/"


def item(n, kind):
    up = f"BOOK{n:08d}"
    return {"id": f"komga:{up}", "service": "komga", "kind": kind, "title": f"Synthetic {kind} {n}", "series": None,
            "subtitle": None, "creator": "Synthetic Author", "handoff_url": HOST + up, "progress": None,
            "artwork": None, "added": "2026-10-28", "released": "2026-10-27"}


COMIC, EBOOK = item(1, "comic"), item(2, "ebook")
VIEW = {"sections": [{"service": "komga", "section": "recent", "state": "ok", "reason": None, "items": [COMIC, EBOOK]},
                     {"service": "komga", "section": "released", "state": "ok", "reason": None,
                      "items": [COMIC, EBOOK]}]}
TITLE = {"service": "komga", "section": "item", "state": "ok", "items": [EBOOK], "reason": None}


def search(*groups):
    return {"status": "ok", "entitled": True, "groups": list(groups)}


def grp(service, state, *items):
    return {"service": service, "state": state, "items": list(items)}


class RealCatalogueShape(unittest.TestCase):
    def test_a_comics_member_has_the_read_tile_so_tiles_cannot_say_who_has_books(self):
        self.assertIn("read", [t[0] for t in tiles(COMICS_G)])      # why the fix reads groups, not tiles


class ComicsOnlyMember(unittest.TestCase):
    T = tiles(COMICS_G)

    def test_home_names_no_books_library(self):
        home = build_home(VIEW, self.T, today="2026-10-29", books=False)
        self.assertEqual(["Comics"], [label for _k, label, _c in home.new_tabs])
        self.assertNotIn("Books", [label for _k, label, _c in home.released_tabs] if home.released_tabs else [])
        self.assertNotIn("calibre-web", repr(home.new_tabs) + repr(home.released_tabs))

    def test_the_ebook_is_visible_under_comics(self):
        home = build_home(VIEW, self.T, today="2026-10-29", new_tab="komga", books=False)
        self.assertEqual(["Synthetic comic 1", "Synthetic ebook 2"], [c.title for c in home.new_items])
        self.assertTrue(all("Books" not in (c.action_label or "") for c in home.new_items))

    def test_the_comics_release_chip_holds_the_ebook(self):
        home = build_home(VIEW, self.T, today="2026-10-29", rel_tab="comics", books=False)
        self.assertNotIn("Books", [t[1] for t in home.released_tabs])

    def test_library_has_no_books_chip_or_shelf(self):
        lib = build_library(VIEW, self.T, books=False)
        self.assertEqual(["All", "Comics"], [c.label for c in lib.chips])
        self.assertNotIn("Books", repr(lib.shelves))
        self.assertIn("Synthetic ebook 2", repr(lib.shelves))

    def test_search_keeps_one_comics_group(self):
        page = build_search(search(grp("komga", "ok", COMIC, EBOOK)), "synthetic", books=False)
        self.assertEqual({"Comics": ["Synthetic comic 1", "Synthetic ebook 2"]},
                         {g.label: [r.title for r in g.items] for g in page.groups})

    def test_title_page_stays_in_comics(self):
        page = build_title(TITLE, "komga", "BOOK00000002", None, books=False)
        self.assertEqual(("Comics", "Comics"), (page.library, page.opens))
        self.assertIn("in Comics", page.action_label)


class MemberWithBothLibraries(unittest.TestCase):
    T = tiles(BOTH_G)

    def test_home_new_tabs_offer_books_holding_the_ebook(self):
        home = build_home(VIEW, self.T, today="2026-10-29", new_tab="calibre-web", books=True)
        self.assertEqual(["All", "Comics", "Books"], [label for _k, label, _c in home.new_tabs])
        self.assertEqual(["Synthetic ebook 2"], [c.title for c in home.new_items])

    def test_library_has_a_books_chip(self):
        self.assertEqual(["All", "Comics", "Books"], [c.label for c in build_library(VIEW, self.T, books=True).chips])

    def test_search_groups_the_ebook_under_books(self):
        page = build_search(search(grp("komga", "ok", COMIC, EBOOK)), "synthetic", books=True)
        self.assertEqual({"Comics": ["Synthetic comic 1"], "Books": ["Synthetic ebook 2"]},
                         {g.label: [r.title for r in g.items] for g in page.groups})

    def test_search_has_one_books_group_when_calibre_web_found_nothing(self):
        page = build_search(search(grp("komga", "ok", COMIC, EBOOK), grp("calibre-web", "empty")), "synthetic",
                            books=True)
        self.assertEqual([("Comics", "ok"), ("Books", "ok")], [(g.label, g.state) for g in page.groups])
        self.assertEqual(["Synthetic ebook 2"], [r.title for r in page.groups[1].items])

    def test_search_keeps_the_ebook_in_komga_when_books_is_unavailable(self):
        page = build_search(search(grp("komga", "ok", COMIC, EBOOK), grp("calibre-web", "unavailable")), "synthetic",
                            books=True)
        self.assertEqual(["Comics", "Books"], [g.label for g in page.groups])
        self.assertEqual("unavailable", page.groups[1].state)
        self.assertEqual(["Synthetic comic 1", "Synthetic ebook 2"], [r.title for r in page.groups[0].items])

    def test_title_page_says_books_but_opens_in_komga(self):
        page = build_title(TITLE, "komga", "BOOK00000002", None, books=True)
        self.assertEqual(("Books", "Comics", "Books"), (page.library, page.opens, page.kicker))
        self.assertIn("in Books", page.action_label)


# ---- through the app, over HTTP, against a mock Komga that holds one synthetic EPUB ---------------------
COMICS_ONLY = [(USER, "comics-a"), (GROUPS, "avrana-users|avrana-comics")]
WITH_BOOKS = [(USER, "member-both"), (GROUPS, "avrana-users|avrana-comics|avrana-books")]
EPUB_ID = "BOOKNOVEL099"
LEAKS = ("calibre-web", "rel=books", "lib=calibre-web", "Recently added to Books", "in Books", ">Books<",
         "Books library")


class OverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.komga = MockKomga().start()
        fake = cls.komga.fake
        book = {"id": EPUB_ID, "seriesId": "SERIESNOVEL1", "seriesTitle": "Synthetic Novels", "libraryId": "LIBCOMICS1",
                "name": "Synthetic Lantern Novel", "number": 1, "deleted": False,
                "media": {"status": "READY", "mediaType": "application/epub+zip", "mediaProfile": "EPUB",
                          "epubDivinaCompatible": False, "pagesCount": 0},
                "metadata": {"title": "Synthetic Lantern Novel", "number": "1", "tags": [],
                             "authors": [{"name": "Synthetic Author", "role": "writer"}],
                             "releaseDate": None},
                "created": fake.latest["content"][0]["created"]}
        fake.books[EPUB_ID] = book
        fake.latest["content"].insert(0, book)

    @classmethod
    def tearDownClass(cls):
        cls.komga.stop()

    def client(self):
        c = make_client(make_settings(home_sections=True, komga_base_url=self.komga.url,
                                      komga_token="mock-api-key-not-real", timeout=2.0))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def pages(self, c, headers):
        return {path: c.get(path, headers=headers) for path in
                ("/", "/?new=komga", "/library", "/search?q=lantern", f"/title/komga/{EPUB_ID}")}

    def test_a_comics_only_member_never_sees_books_named(self):
        c = self.client()
        pages = self.pages(c, COMICS_ONLY)
        for path, r in pages.items():
            self.assertEqual(200, r.status_code, path)
            for leak in LEAKS:
                self.assertNotIn(leak, r.text, f"{path}: {leak}")
        self.assertIn("Synthetic Lantern Novel", pages["/search?q=lantern"].text)
        self.assertIn("Comics", pages["/search?q=lantern"].text)
        self.assertEqual(200, c.get("/library?lib=komga", headers=COMICS_ONLY).status_code)
        self.assertNotIn("Books shelf", c.get("/library?lib=calibre-web", headers=COMICS_ONLY).text)

    def test_a_member_with_books_sees_the_ebook_as_a_book_everywhere(self):
        c = self.client()
        home = c.get("/?new=calibre-web", headers=WITH_BOOKS).text
        self.assertIn("Synthetic Lantern Novel", home)
        self.assertIn("?new=calibre-web", c.get("/", headers=WITH_BOOKS).text)
        self.assertTrue(re.search(r"Books", c.get("/library", headers=WITH_BOOKS).text))
        title = c.get(f"/title/komga/{EPUB_ID}", headers=WITH_BOOKS).text
        self.assertIn("in Books", title)
        self.assertIn("Opens in Comics", title)       # the app it opens in is Komga's, whatever the library is called


if __name__ == "__main__":
    unittest.main()
