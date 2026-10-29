"""Continue in the order the member actually used things, and New for You (owner requests 2026-10-28). Offline,
synthetic data only.

  * Continue is ordered by when THIS member last touched each item (contract `active`), across libraries: an audiobook
    left a week ago no longer leads because its library comes first. Undated items go last, in the old round-robin.
  * New for You sits right under Continue: what arrived lately that is the next episode, issue or book of a series the
    member is caught up on (each library decides), newest arrival first, each card saying what it is and when it came.
    It is absent when there is nothing. An item it shows is not repeated in Continue, Up next or New Releases.
  * With nothing in progress, the hero is the newest New for You item (its heading starts "New for You").
"""
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import (ALL_EXTRAS, NEW_FOR_YOU, build_continue_page, build_home, by_activity,
                                       extra_sections_for, for_you_words, ItemVM)

from .support import make_client, make_settings, require_framework

TODAY = "2026-10-28"
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "audiobookshelf": "https://listen.avrana.net/item/",
           "komga": "https://read.avrana.net/book/"}
TILES = [("watch", Trusted("Watch"), Trusted("")), ("listen", Trusted("Listen"), Trusted("")),
         ("read", Trusted("Read"), Trusted("")), ("help", Trusted("Help"), Trusted(""))]
TITLES = frozenset({"jellyfin", "audiobookshelf", "komga"})
PROGRESS = {"fraction": 0.5, "percent": 50, "position_seconds": 600, "duration_seconds": 1200}


def item(service, uid, title, kind="movie", **extra):
    out = {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": title,
           "handoff_url": HANDOFF[service] + uid}
    out.update(extra)
    return out


def jf(n):
    return f"{n:032x}"


def sec(service, section, items=(), state="ok"):
    return {"service": service, "section": section, "state": state, "items": list(items)}


def view(*sections):
    return {"sections": list(sections)}


FILM = item("jellyfin", jf(1), "Synthetic Film", progress=PROGRESS, active="2026-10-27T21:00:00Z")
BOOK = item("audiobookshelf", "li_book000001", "Synthetic Listen", "audiobook", progress=PROGRESS,
            active="2026-10-21T08:00:00Z")
COMIC = item("komga", "READ00000001", "Synthetic Comic #4", "comic", progress={"fraction": 0.4, "percent": 40},
             active="2026-10-28T07:30:00Z")
ISSUE = item("komga", "NEWISSUE0001", "Synthetic Hero #9", "comic", series="Synthetic Hero", subtitle="#9",
             shelf="next", active="2026-10-28T06:00:00Z")
EPISODE = item("jellyfin", jf(9), "Synthetic Pilot", "episode", series="Synthetic Show", subtitle="S2 E1",
               artwork={"ref": f"jellyfin/primary/{jf(90)}", "alt": "Poster for Synthetic Show", "shape": "poster"},
               active="2026-10-26T12:00:00Z")
SEQUEL = item("audiobookshelf", "li_book000009", "Synthetic Saga Book 3", "audiobook", series="Synthetic Saga",
              active="2026-10-20T12:00:00Z")


class ContinueOrder(unittest.TestCase):
    def test_the_most_recently_touched_leads_whatever_its_library(self):
        v = view(sec("jellyfin", "continue", [FILM]), sec("audiobookshelf", "continue", [BOOK]),
                 sec("komga", "continue", [COMIC]))
        home = build_home(v, TILES, title_services=TITLES, today=TODAY)
        self.assertEqual(["Synthetic Comic #4", "Synthetic Film", "Synthetic Listen"],
                         [c.title for c in home.continue_items])
        self.assertEqual("Synthetic Comic #4", home.hero.title)
        page = build_continue_page(v, TILES)
        self.assertEqual(["Synthetic Comic #4", "Synthetic Film", "Synthetic Listen"], [c.title for c in page.items])

    def test_a_week_old_listen_is_not_first_because_its_library_is(self):
        old = dict(BOOK, active="2026-10-21T08:00:00Z")
        films = [item("jellyfin", jf(n), f"Film {n}", progress=PROGRESS, active=f"2026-10-2{n}T10:00:00Z")
                 for n in (7, 6, 5)]
        home = build_home(view(sec("audiobookshelf", "continue", [old]), sec("jellyfin", "continue", films)), TILES,
                          today=TODAY)
        self.assertEqual(["Film 7", "Film 6", "Film 5", "Synthetic Listen"], [c.title for c in home.continue_items])

    def test_undated_items_go_last_in_round_robin_and_bad_dates_count_as_none(self):
        a = [item("jellyfin", jf(n), f"Film {n}", progress=PROGRESS) for n in (1, 2)]
        b = [item("audiobookshelf", f"li_book00000{n}", f"Book {n}", "audiobook", progress=PROGRESS,
                  active="2026-10-28 junk") for n in (1, 2)]
        dated = item("audiobookshelf", "li_book000009", "Dated", "audiobook", progress=PROGRESS,
                     active="2026-10-01T00:00:00Z")
        home = build_home(view(sec("jellyfin", "continue", a), sec("audiobookshelf", "continue", b + [dated])), TILES,
                          today=TODAY)
        self.assertEqual(["Dated", "Film 1", "Book 1", "Film 2", "Book 2"], [c.title for c in home.continue_items])

    def test_up_next_takes_its_series_last_watch(self):
        nxt = item("jellyfin", jf(5), "Next Episode", "episode", series="Synthetic Show", subtitle="S1 E5",
                   active="2026-10-28T09:00:00Z")
        v = view(sec("jellyfin", "continue", [FILM]), sec("jellyfin", "next_up", [nxt]),
                 sec("audiobookshelf", "continue", [BOOK]))
        home = build_home(v, TILES, today=TODAY)
        self.assertEqual(["Next Episode", "Synthetic Film", "Synthetic Listen"], [c.title for c in home.continue_items])

    def test_by_activity_is_stable(self):
        x = [ItemVM("A", "h", "movie", None, None, active="2026-10-01T00:00:00Z"),
             ItemVM("B", "h", "movie", None, None, active="2026-10-01T00:00:00Z")]
        self.assertEqual(["A", "B"], [i.title for i in by_activity([x])])


class NewForYou(unittest.TestCase):
    def full(self):
        return view(sec("jellyfin", "continue", [FILM]), sec("audiobookshelf", "continue", [BOOK]),
                    sec("komga", "continue", [COMIC, ISSUE]), sec("jellyfin", "next_up", [EPISODE]),
                    sec("jellyfin", "for_you", [EPISODE]), sec("audiobookshelf", "for_you", [SEQUEL]),
                    sec("komga", "for_you", [ISSUE]),
                    sec("komga", "released", [dict(ISSUE, released="2026-10-28"),
                                              item("komga", "OTHERISSUE01", "Other #1", "comic",
                                                   released="2026-10-27")]))

    def test_newest_arrival_first_with_words_and_never_twice(self):
        home = build_home(self.full(), TILES, title_services=TITLES, today=TODAY)
        self.assertEqual(["Synthetic Hero #9", "Synthetic Pilot", "Synthetic Saga Book 3"],
                         [c.title for c in home.for_you_items])
        self.assertEqual(["New issue · today", "New episode · 2 days ago", "Next in series · 8 days ago"],
                         [c.progress for c in home.for_you_items])
        self.assertEqual("poster", home.for_you_items[1].shape)              # the show's poster, as Continue
        shown = {c.title for c in home.continue_items} | {c.title for c in home.released_items}
        self.assertFalse(shown & {c.title for c in home.for_you_items})
        self.assertEqual(["Synthetic Comic #4", "Synthetic Film", "Synthetic Listen"],
                         [c.title for c in home.continue_items])
        self.assertTrue(home.for_you_items[0].href.startswith("/title/"))     # a title page, as New Releases

    def test_absent_when_nothing_and_inside_a_filter_only_that_place(self):
        home = build_home(view(sec("jellyfin", "continue", [FILM]), sec("jellyfin", "for_you", [])), TILES,
                          today=TODAY)
        self.assertEqual((), home.for_you_items)
        listen = build_home(self.full(), TILES, today=TODAY, focus="listen")
        self.assertEqual(["Synthetic Saga Book 3"], [c.title for c in listen.for_you_items])
        watch = build_home(self.full(), TILES, today=TODAY, focus="watch")
        self.assertEqual(["Synthetic Pilot"], [c.title for c in watch.for_you_items])
        up_next = next(r for r in watch.rows if r.key == "next")
        self.assertNotIn("Synthetic Pilot", [c.title for c in up_next.items])

    def test_with_nothing_in_progress_the_hero_is_new_for_you(self):
        home = build_home(view(sec("komga", "for_you", [ISSUE]), sec("komga", "recent", [COMIC])), TILES,
                          title_services=TITLES, today=TODAY)
        self.assertEqual(("for_you", "Synthetic Hero #9"), (home.hero.state, home.hero.title))
        self.assertIn("New issue · today", home.hero.meta)

    def test_every_view_asks_for_it_last(self):
        self.assertEqual([("jellyfin", "for_you"), ("audiobookshelf", "for_you"), ("komga", "for_you")],
                         [x for x in ALL_EXTRAS if x[1] == "for_you"])
        self.assertEqual(("komga", "week"), ALL_EXTRAS[-1])          # then This week in comics (2026-10-29)
        self.assertEqual(("jellyfin", "for_you"), extra_sections_for("watch")[-1])

    def test_words(self):
        it = ItemVM("T", "h", "episode", None, None, active="2026-10-27T23:59:59Z")
        self.assertEqual("New episode · yesterday", for_you_words(it, TODAY))
        self.assertEqual("New episode", for_you_words(ItemVM("T", "h", "episode", None, None), TODAY))


class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def test_the_section_follows_continue_and_the_hero_says_new_for_you(self):
        html = self.env.get_template("_sections.html").render(
            home=build_home(NewForYou.full(None), TILES, title_services=TITLES, today=TODAY))
        self.assertIn(f'<h2 id="h-foryou">{NEW_FOR_YOU}</h2>', html)
        self.assertLess(html.index('id="h-continue"'), html.index('id="h-foryou"'))
        self.assertLess(html.index('id="h-foryou"'), html.index('id="h-released"'))
        self.assertIn("New issue · today", html)
        empty = self.env.get_template("_sections.html").render(
            home=build_home(view(sec("komga", "for_you", [ISSUE])), TILES, title_services=TITLES, today=TODAY))
        self.assertIn('<span class="sr">New for You: </span>', empty)
        none = self.env.get_template("_sections.html").render(
            home=build_home(view(sec("jellyfin", "continue", [FILM])), TILES, today=TODAY))
        self.assertNotIn("h-foryou", none)


if __name__ == "__main__":
    unittest.main()
