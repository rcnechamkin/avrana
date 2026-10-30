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
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "komga": "https://read.avrana.net/book/",
           "audiobookshelf": "https://listen.avrana.net/item/"}


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

    def test_a_quiet_week_still_folds_the_comics_as_new_in_comics(self):
        # Owner 2026-10-29: comics never take the rail on All; with fewer than two issues this week, the card holds
        # New Releases' own comics (one issue per series).
        home = build_home(page(week=1), TILES, today=TODAY)
        s = home.released_stack
        self.assertEqual(("New in comics", "3", "New issues in 3 series", None), (s.title, s.count, s.line, s.series))
        self.assertEqual(["Film 1", "Film 2"], [c.title for c in home.released_items])
        html = Rendered.env.get_template("_sections.html").render(home=home) if hasattr(Rendered, "env") else ""
        if html:
            self.assertIn('<span class="t">New in comics</span>', html)

    def test_one_comic_in_all_stays_a_card(self):
        one = page(week=1)
        one["sections"][1]["items"] = one["sections"][1]["items"][:1]
        home = build_home(one, TILES, today=TODAY)
        self.assertIsNone(home.released_stack)
        self.assertIn("Issue 1", [c.title for c in home.released_items])

    def test_nothing_folds_on_a_chip_or_in_a_filter(self):
        self.assertIsNone(build_home(page(), TILES, today=TODAY, rel_tab="comics").released_stack)
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


class CardLinkGoesSomewhere(unittest.TestCase):
    """F-02: the card's link must land on a Comics chip that lists the week's issues, whatever New Releases holds."""

    def follow(self, view):
        home = build_home(view, TILES, today=TODAY)
        self.assertIsNotNone(home.released_stack, "precondition: the card is drawn")
        self.assertEqual("/?rel=comics#h-released", home.released_stack.href)
        followed = build_home(view, TILES, today=TODAY, rel_tab="comics")
        self.assertEqual(["comics"], [k for k, _l, cur, _h in followed.released_tabs if cur])
        return followed

    def test_normal_case_is_unchanged(self):
        followed = self.follow(page())
        self.assertEqual({"Issue 1", "Issue 2", "Issue 3"}, {c.title for c in followed.released_items})

    def test_komga_released_unavailable_still_lists_the_week(self):
        view = page()
        view["sections"][1] = {"service": "komga", "section": "released", "state": "unavailable", "items": []}
        followed = self.follow(view)
        self.assertEqual({f"Issue {10 + n}" for n in range(6)}, {c.title for c in followed.released_items})

    def test_a_caught_up_reader_whose_released_comics_are_all_in_for_you_still_lists_the_week(self):
        view = page()
        view["sections"].append(sec("komga", "for_you", [issue(1), issue(2), issue(3)]))
        followed = self.follow(view)
        self.assertEqual({f"Issue {10 + n}" for n in range(6)}, {c.title for c in followed.released_items})


    def three_kinds(self, view):
        """The reported case: Movies and TV + Audiobooks + Comics, so the card is drawn on All."""
        book = item("audiobookshelf", "li_syn000001", "Audio 1", "audiobook", released="2026-10-26")
        view["sections"].append(sec("audiobookshelf", "released", [book]))
        return view

    def test_reported_case_released_unavailable_with_movies_audiobooks_and_comics(self):
        view = self.three_kinds(page())
        view["sections"][1] = {"service": "komga", "section": "released", "state": "unavailable", "items": []}
        home = build_home(view, TILES, today=TODAY)
        self.assertIsNotNone(home.released_stack, "on baseline the card is drawn here and its link reloads All")
        self.assertEqual({"watch", "listen", "comics"}, {k for k, _l, _c, _h in home.released_tabs} - {"all"})
        followed = self.follow(view)
        self.assertEqual({f"Issue {10 + n}" for n in range(6)}, {c.title for c in followed.released_items})

    def test_reported_case_every_released_comic_is_also_in_for_you(self):
        view = self.three_kinds(page())
        view["sections"].append(sec("komga", "for_you", [issue(1), issue(2), issue(3)]))
        home = build_home(view, TILES, today=TODAY)
        self.assertIsNotNone(home.released_stack)
        self.assertEqual({"watch", "listen", "comics"}, {k for k, _l, _c, _h in home.released_tabs} - {"all"})
        followed = self.follow(view)
        self.assertEqual({f"Issue {10 + n}" for n in range(6)}, {c.title for c in followed.released_items})


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
