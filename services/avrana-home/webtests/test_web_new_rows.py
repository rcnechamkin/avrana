"""Home's New releases and New to Avrana (owner decision 2026-10-28): New releases by the release date itself, across
libraries, newest first; New to Avrana is the rail that was Recently added (by when it was added). Offline."""
import re
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import NEW_RELEASES, NEW_TO_AVRANA, build_home, release_key, _item_vm

from .support import make_client, make_settings, require_framework

TODAY = "2026-10-28"
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "audiobookshelf": "https://listen.avrana.net/item/",
           "komga": "https://read.avrana.net/book/", "calibre-web": "https://books.avrana.net/book/"}
TILES = [("watch", Trusted("Watch"), Trusted("")), ("listen", Trusted("Listen"), Trusted("")),
         ("read", Trusted("Read"), Trusted("")), ("help", Trusted("Help"), Trusted(""))]
JF = ("a" * 31) + "1", ("a" * 31) + "2", ("a" * 31) + "3"


def item(service, uid, title, kind="movie", released=None, year=None, series=None):
    out = {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": title,
           "handoff_url": HANDOFF[service] + uid, "year": year, "series": series}
    if released:
        out["released"] = released
    return out


def sec(service, section, state, items=()):
    return {"service": service, "section": section, "state": state, "items": list(items)}


def released_view(*extra):
    return {"sections": [
        sec("jellyfin", "continue", "empty"), sec("jellyfin", "recent", "ok", [item("jellyfin", JF[2], "Synthetic Added")]),
        sec("audiobookshelf", "continue", "empty"), sec("audiobookshelf", "recent", "empty"),
        sec("komga", "recent", "empty"),
        sec("jellyfin", "released", "ok", [item("jellyfin", JF[0], "Synthetic Episode", "episode", "2026-10-27",
                                                series="Synthetic Show"),
                                           item("jellyfin", JF[1], "Synthetic Film", "movie", "2026-10-20", 2026)]),
        sec("audiobookshelf", "released", "ok", [item("audiobookshelf", "li_book000001", "Synthetic Book", "audiobook",
                                                      year=2026)]),
        sec("komga", "released", "ok", [item("komga", "BOOKAAAA0001", "Synthetic Cover Dated", "comic", "2026-12-15"),
                                        item("komga", "BOOKAAAA0002", "Synthetic Undated", "comic")]),
        *extra]}


class ViewModel(unittest.TestCase):
    def test_new_releases_sort_on_the_day_across_libraries(self):
        home = build_home(released_view(), TILES, today=TODAY)
        # a cover date ahead of sale counts as today; a bare year as 1 January; nothing undated
        self.assertEqual([c.title for c in home.released_items],
                         ["Synthetic Cover Dated", "Synthetic Episode", "Synthetic Film", "Synthetic Book"])
        self.assertEqual(home.released_items[1].line, "Synthetic Show")              # an episode keeps its series
        self.assertEqual(home.released_items[2].line, "Movies and TV")               # else the library

    def test_new_to_avrana_is_still_the_recently_added_list(self):
        home = build_home(released_view(), TILES, today=TODAY)
        self.assertTrue(home.show_new)
        self.assertEqual([c.title for c in home.new_items], ["Synthetic Added"])

    def test_a_title_once_and_the_rail_bounded(self):
        dupe = sec("jellyfin", "released", "ok", [item("jellyfin", JF[1], "Synthetic Film", "movie", "2026-10-20")])
        home = build_home(released_view(dupe), TILES, today=TODAY)
        titles = [c.title for c in home.released_items]
        self.assertEqual(titles.count("Synthetic Film"), 1)
        self.assertLessEqual(len(titles), 4)

    def test_what_continue_shows_is_left_out(self):
        v = released_view()
        v["sections"][0] = sec("jellyfin", "continue", "ok", [dict(item("jellyfin", JF[1], "Synthetic Film"),
                                                                   progress={"fraction": 0.4, "position_seconds": 60,
                                                                             "duration_seconds": 150})])
        home = build_home(v, TILES, today=TODAY)
        self.assertIn("Synthetic Film", [c.title for c in home.continue_items])
        self.assertNotIn("Synthetic Film", [c.title for c in home.released_items])

    def test_no_release_dates_means_no_row(self):
        v = {"sections": [s for s in released_view()["sections"] if s["section"] != "released"]}
        self.assertEqual(build_home(v, TILES, today=TODAY).released_items, ())

    def test_watch_gets_new_releases_after_up_next(self):
        v = released_view(sec("jellyfin", "next_up", "empty"))
        home = build_home(v, TILES, focus="watch", today=TODAY)
        self.assertEqual([r.key for r in home.rows][:2], ["next", "released"])
        self.assertEqual(home.rows[1].heading, NEW_RELEASES)
        self.assertEqual([c.title for c in home.rows[1].items], ["Synthetic Episode", "Synthetic Film"])
        self.assertEqual(home.released_items, ())                                     # a filter shows rows only

    def test_the_sort_key_never_trusts_odd_dates(self):
        bad = _item_vm(item("komga", "BOOKAAAA0003", "Odd", "comic", "2026-1-1"))
        self.assertIsNone(bad.released)
        self.assertIsNone(release_key(bad, TODAY))


class Markup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def render(self, v):
        return self.env.get_template("_sections.html").render(home=build_home(v, TILES, today=TODAY))

    def test_new_releases_comes_before_new_to_avrana(self):
        html = self.render(released_view())
        heads = re.findall(r'<h2 id="h-([a-z]+)"[^>]*>(?:<span[^>]*>)?([^<]*)', html)
        keys = [k for k, _ in heads]
        self.assertLess(keys.index("released"), keys.index("new"))
        self.assertIn(f'<h2 id="h-released">{NEW_RELEASES}</h2>', html)
        self.assertIn(f'<h2 id="h-new">{NEW_TO_AVRANA}</h2>', html)
        self.assertIn(f'<span class="k-eyebrow">{NEW_TO_AVRANA}<span class="sr">: </span>', html)   # the hero
        self.assertNotIn("Recently added", html)

    def test_no_dates_no_section(self):
        v = {"sections": [s for s in released_view()["sections"] if s["section"] != "released"]}
        self.assertNotIn('id="h-released"', self.render(v))


if __name__ == "__main__":
    unittest.main()
