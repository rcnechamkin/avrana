"""New Releases' "This week in comics" card (owner request 2026-10-29). Offline, synthetic data only.

  * On All, the comics fold into one card for the issues that reached Komga in the last seven days (Komga's `week`
    section, every issue, not one per series), when there are at least two; it sits where the newest comic would have.
  * The card is one link to the Comics chip, which still lists the issues one by one. It shows the three newest covers,
    the count ("100+" for a full page), and how many are from the member's series (their Continue and New for You),
    else how many series. It takes one of the rail's slots.
  * Nothing changes on a chosen chip, inside a filter, with one issue, or when comics are the only kind.
"""
import os
import sys
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import ALL_EXTRAS, StackVM, build_home, stack_of, ItemVM

from .support import make_client, make_settings, require_framework

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TODAY = "2026-10-29"
TILES = [("watch", Trusted("Watch"), Trusted("")), ("comics", Trusted("Comics"), Trusted("")),
         ("help", Trusted("Help"), Trusted(""))]
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "komga": "https://read.avrana.net/book/"}


def item(service, uid, title, kind, **extra):
    out = {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": title,
           "handoff_url": HANDOFF[service] + uid}
    out.update(extra)
    return out


def issue(n, series=None, day="2026-10-28"):
    return item("komga", f"ISSUE{n:07d}", f"Issue {n}", "comic", series=series or f"Series {n}", released=day,
                artwork={"ref": f"komga/book/ISSUE{n:07d}", "alt": f"Cover of Issue {n}"})


def film(n, day):
    return item("jellyfin", f"{n:032x}", f"Film {n}", "movie", released=day)


def sec(service, section, items):
    return {"service": service, "section": section, "state": "ok", "items": list(items)}


def page(week=6, mine=()):
    released = [film(1, "2026-10-29"), issue(1), issue(2), film(2, "2026-10-27"), issue(3, day="2026-10-20")]
    return {"sections": [sec("jellyfin", "released", released[0:1] + released[3:4]),
                         sec("komga", "released", [released[1], released[2], released[4]]),
                         sec("komga", "week", [issue(10 + n, "Absolute Batman" if n < 2 else None)
                                               for n in range(week)]),
                         sec("komga", "continue", list(mine))]}


class Card(unittest.TestCase):
    def test_on_all_the_comics_fold_into_one_card_where_the_newest_comic_was(self):
        home = build_home(page(), TILES, today=TODAY)
        s = home.released_stack
        self.assertIsInstance(s, StackVM)
        self.assertEqual(("6", "6 new issues", "/?rel=comics#h-released"), (s.count, s.line, s.href))
        self.assertEqual(3, len(s.images))
        self.assertEqual(["Film 1", "Film 2"], [c.title for c in home.released_items])
        self.assertEqual(1, home.released_stack_at)            # after Film 1 (29th), before Film 2 (27th)
        self.assertEqual("5 series", s.series)

    def test_from_your_series_when_the_member_reads_it(self):
        mine = [issue(99, "Absolute Batman")]
        s = build_home(page(mine=mine), TILES, today=TODAY).released_stack
        self.assertEqual(("2 from your series", None), (s.mine, s.series))

    def test_nothing_folds_on_a_chip_with_one_issue_or_in_a_filter(self):
        self.assertIsNone(build_home(page(), TILES, today=TODAY, rel_tab="comics").released_stack)
        self.assertIsNone(build_home(page(week=1), TILES, today=TODAY).released_stack)
        self.assertIsNone(build_home(page(), TILES, today=TODAY, focus="comics").released_stack)
        comics_only = {"sections": [s for s in page()["sections"] if s["service"] == "komga"]}
        self.assertIsNone(build_home(comics_only, TILES, today=TODAY).released_stack)

    def test_a_full_page_is_100_plus_and_the_card_takes_a_slot(self):
        week = [ItemVM(f"I{n}", "h", "comic", None, None) for n in range(100)]
        self.assertEqual(("100+", "100+ new issues"), (stack_of(week, set(), "/").count, stack_of(week, set(), "/").line))
        films = [film(n, f"2026-10-{10 + n:02d}") for n in range(15)]
        v = page()
        v["sections"][0] = sec("jellyfin", "released", films)
        home = build_home(v, TILES, today=TODAY, limit=12)
        self.assertEqual(11, len(home.released_items))

    def test_asked_on_all_only_and_last(self):
        self.assertEqual(("komga", "week"), ALL_EXTRAS[-1])


class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def test_one_link_named_by_its_words_with_decorative_covers(self):
        html = self.env.get_template("_sections.html").render(home=build_home(page(mine=[issue(99, "Absolute Batman")]),
                                                                               TILES, today=TODAY))
        start = html.index('<li class="w-comic w-stack">')
        card = html[start:html.index("</li>", start)]
        self.assertIn('href="/?rel=comics#h-released"', card)
        self.assertIn('<span class="t">This week in comics</span>', card)
        self.assertIn("6 new issues", card)
        self.assertIn('<span class="p mine"><span class="sr">, </span>2 from your series</span>', card)
        self.assertEqual(3, card.count('aria-hidden="true"><img class="art"'))
        self.assertIn('<span class="count" aria-hidden="true">6</span>', card)
        self.assertNotIn("aria-label", card)
        self.assertNotRegex(card, r"style=|<svg")
        rail = html[html.index('id="rail-released"'):]
        self.assertLess(rail.index("Film 1"), rail.index("w-stack"))
        self.assertLess(rail.index("w-stack"), rail.index("Film 2"))


if __name__ == "__main__":
    unittest.main()
