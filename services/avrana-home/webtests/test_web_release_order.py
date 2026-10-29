"""New Releases' order for books with only a release year (owner request 2026-10-29). Offline, synthetic data only.

Audiobookshelf keeps only the year of what it matches, and Calibre writes a year as 1 January, so such books used to
sort as 1 January of their year and sink below every comic. A year-only book is now placed by the day it reached the
library, kept inside its year; without an added day it stays at 1 January (never claimed newer than it may be).
"""
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import ItemVM, build_home, release_key

TODAY = "2026-10-29"
TILES = [("listen", Trusted("Listen"), Trusted("")), ("read", Trusted("Read"), Trusted("")),
         ("help", Trusted("Help"), Trusted(""))]
HANDOFF = {"audiobookshelf": "https://listen.avrana.net/item/", "komga": "https://read.avrana.net/book/",
           "calibre-web": "https://books.avrana.net/book/"}


def vm(kind="audiobook", year=None, released=None, added=None):
    return ItemVM("T", "h", kind, None, None, year=year, released=released, added=added)


class Key(unittest.TestCase):
    def test_a_year_only_book_takes_the_day_it_arrived_inside_its_year(self):
        self.assertEqual("2026-10-25", release_key(vm(year=2026, added="2026-10-25"), TODAY))
        self.assertEqual("1999-12-31", release_key(vm(year=1999, added="2026-10-22"), TODAY))
        self.assertEqual("2027-01-01", release_key(vm(year=2027, added="2026-10-01"), "2027-03-01"))   # never before its year
        self.assertEqual("2026-01-01", release_key(vm(year=2026), TODAY))                            # no added day

    def test_calibres_1_january_is_a_missing_day_for_books_only(self):
        self.assertEqual("2026-09-14", release_key(vm("ebook", 2026, "2026-01-01", "2026-09-14"), TODAY))
        self.assertEqual("2026-03-02", release_key(vm("audiobook", 2026, "2026-03-02", "2026-09-14"), TODAY))

    def test_a_comic_is_dated_by_the_day_it_arrived_for_now(self):
        # Owner request 2026-10-29: the day it reached Komga, not the cover date; its cover date only without one.
        self.assertEqual("2026-09-14", release_key(vm("comic", 2026, "2026-01-01", "2026-09-14"), TODAY))
        self.assertEqual("2026-01-01", release_key(vm("comic", 2026, "2026-01-01"), TODAY))
        self.assertEqual("2026-03-02", release_key(vm("ebook", 2026, "2026-03-02", "2026-09-14"), TODAY))

    def test_never_later_than_today(self):
        self.assertEqual(TODAY, release_key(vm(year=2026, added="2026-12-01"), TODAY))
        self.assertEqual(TODAY, release_key(vm("comic", 2026, "2026-12-16"), TODAY))


def item(service, uid, title, kind, **extra):
    out = {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": title,
           "handoff_url": HANDOFF[service] + uid}
    out.update(extra)
    return out


class Shelf(unittest.TestCase):
    def test_a_book_added_this_week_stands_among_this_weeks_comics(self):
        comics = [item("komga", f"ISSUE{n:07d}", f"Issue {n}", "comic", released=f"2026-10-{20 + n:02d}")
                  for n in range(1, 8)]
        listen = item("audiobookshelf", "li_book000001", "New Listen", "audiobook", year=2026, added="2026-10-25")
        old = item("calibre-web", "7", "Old Novel", "ebook", year=1999, released="1999-01-01", added="2026-10-28")
        v = {"sections": [{"service": "komga", "section": "released", "state": "ok", "items": comics},
                          {"service": "audiobookshelf", "section": "released", "state": "ok", "items": [listen]},
                          {"service": "calibre-web", "section": "released", "state": "ok", "items": [old]}]}
        home = build_home(v, TILES, today=TODAY)
        # The comics fold into one card on All (owner 2026-10-29), standing where the newest issue (the 27th) would.
        self.assertEqual(["New Listen", "Old Novel"], [c.title for c in home.released_items])
        self.assertEqual((0, "7"), (home.released_stack_at, home.released_stack.count))


if __name__ == "__main__":
    unittest.main()
