"""New Releases' All is never one kind (owner 2026-10-29, "still way too comic book heavy"). Offline, synthetic data.

  * On All, no chip's kinds take more than a third of the rail while the other kinds still have cards.
  * A kind that runs out leaves its room to the rest; a chip still lists its own kind in full.
"""
import os
import sys
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import ItemVM, balanced, build_home

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TODAY = "2026-10-29"
TILES = [("watch", Trusted("Watch"), Trusted("")), ("listen", Trusted("Listen"), Trusted("")),
         ("comics", Trusted("Comics"), Trusted("")), ("help", Trusted("Help"), Trusted(""))]
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "komga": "https://read.avrana.net/book/",
           "audiobookshelf": "https://listen.avrana.net/item/"}


def item(service, uid, kind, day):
    return {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": f"{kind} {uid}",
            "handoff_url": HANDOFF[service] + uid, "released": day}


def page(comics=12, films=10, books=10):
    sec = lambda s, items: {"service": s, "section": "released", "state": "ok", "items": items}  # noqa: E731
    return {"sections": [
        sec("komga", [item("komga", f"C{n:07d}", "comic", f"2026-10-{28 - n:02d}") for n in range(comics)]),
        sec("jellyfin", [item("jellyfin", f"{n:032x}", "movie", f"2026-09-{28 - n:02d}") for n in range(films)]),
        sec("audiobookshelf", [item("audiobookshelf", f"ABS{n:05d}", "audiobook", f"2026-08-{28 - n:02d}")
                               for n in range(books)])]}


class Share(unittest.TestCase):
    def test_on_all_no_kind_takes_more_than_a_third(self):
        home = build_home(page(), TILES, today=TODAY, limit=12)
        kinds = [c.title.split()[0] for c in home.released_items]
        self.assertEqual((4, 4, 4), (kinds.count("comic"), kinds.count("movie"), kinds.count("audiobook")))
        self.assertEqual(["comic"] * 4, kinds[:4])                  # still newest first

    def test_a_kind_that_runs_out_leaves_its_room(self):
        home = build_home(page(films=2, books=1), TILES, today=TODAY, limit=12)
        kinds = [c.title.split()[0] for c in home.released_items]
        self.assertEqual((9, 2, 1), (kinds.count("comic"), kinds.count("movie"), kinds.count("audiobook")))

    def test_the_comics_chip_still_lists_comics_in_full(self):
        home = build_home(page(), TILES, today=TODAY, limit=12, rel_tab="comics")
        self.assertEqual(12, len(home.released_items))

    def test_order_is_kept_and_nothing_is_lost(self):
        items = [ItemVM(f"{k}{n}", "h", k, None, None) for n, k in enumerate("comic comic comic comic comic movie".split())]
        out = balanced(items, 3)
        self.assertEqual(["comic", "comic", "movie"], [i.kind for i in out[:3]])
        self.assertEqual(sorted(i.title for i in items), sorted(i.title for i in out))


if __name__ == "__main__":
    unittest.main()
