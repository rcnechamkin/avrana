"""The Home page (AVR-374/452/478): view-model unit tests (pure functions) and two synthetic members
through the HTTP layer. Everything is synthetic; nothing leaves loopback."""
import re
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import (NEW_ALL, RAIL_MOST, build_home, build_places, initial_of,
                                       service_notice)

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

URL = "https://watch.avrana.net/web/#/details?id="


def item(i, title, kind="movie", url=None, progress=None, ref=None, series=None):
    return {"id": f"x:{i}", "service": "x", "kind": kind, "title": title, "series": series, "subtitle": None,
            "handoff_url": URL + str(i) if url is None else url, "progress": progress,
            "artwork": {"ref": ref} if ref else None}


def sec(service, section, state, items=()):
    return {"service": service, "section": section, "state": state, "items": list(items), "reason": None}


TILES = [("watch", Trusted("Watch"), Trusted("Movies &amp; TV")), ("listen", Trusted("Listen"), Trusted("Audiobooks")),
         ("read", Trusted("Read"), Trusted("Comics")), ("request", Trusted("Request"), Trusted("Ask")),
         ("help", Trusted("Help"), Trusted("Guides"))]


class HomeViewModelTests(unittest.TestCase):
    def view(self, *sections):
        return {"sections": list(sections)}

    def test_places_keep_an_unavailable_library_in_place_and_never_add_one(self):
        v = self.view(sec("jellyfin", "continue", "unavailable"), sec("jellyfin", "recent", "unavailable"),
                      sec("audiobookshelf", "continue", "ok", [item(1, "A", "audiobook")]))
        places = build_places(TILES[:2] + TILES[3:], v)
        self.assertEqual(["/watch", "/listen", "/request", "/help"], [p.href for p in places])
        self.assertEqual([False, True, True, True], [p.up for p in places])

    def test_one_section_unavailable_strikes_the_place_and_the_notice_says_the_rest_may_be_old(self):
        # #6: in the first minutes of an outage Continue fails while New this week still answers from the cache.
        # One rule (library_down) drives both the places bar and the notice, so they cannot contradict each other.
        v = self.view(sec("jellyfin", "continue", "unavailable"), sec("jellyfin", "recent", "ok", [item(1, "A")]))
        self.assertFalse(build_places(TILES, v)[0].up)
        home = build_home(v, TILES)
        self.assertFalse(home.places[0].up)
        self.assertEqual(("Movies and TV are unavailable right now. Anything shown from them may be out of date.",),
                         home.notices)
        self.assertEqual(["A"], [c.title for c in home.new_items])     # still shown, and said to be possibly old
        self.assertEqual("/", home.retry_href)

    def test_a_library_that_answers_in_full_is_up_and_has_no_notice(self):
        v = self.view(sec("jellyfin", "continue", "empty"), sec("jellyfin", "recent", "ok", [item(1, "A")]))
        self.assertTrue(build_places(TILES, v)[0].up)
        self.assertEqual((), build_home(v, TILES).notices)

    def test_read_is_unavailable_only_when_every_library_behind_it_is(self):
        both = self.view(sec("komga", "recent", "unavailable"), sec("calibre-web", "recent", "unavailable"))
        one = self.view(sec("komga", "recent", "unavailable"), sec("calibre-web", "recent", "ok", [item(1, "B", "ebook")]))
        self.assertFalse(build_places(TILES, both)[2].up)
        self.assertTrue(build_places(TILES, one)[2].up)

    def test_no_library_tile_means_nothing_to_show(self):
        home = build_home(self.view(), [TILES[3], TILES[4]], member_name="Pat")
        self.assertTrue(home.no_library)
        self.assertEqual((), home.continue_items)
        self.assertFalse(home.show_continue or home.show_new)

    def test_continue_is_one_bounded_rail_merged_across_services_with_words_for_progress(self):
        prog = {"position_seconds": 600, "duration_seconds": 4200}
        v = self.view(
            sec("jellyfin", "continue", "ok", [item(i, f"Film {i}", progress=prog) for i in range(1, 6)]),
            sec("audiobookshelf", "continue", "ok", [item(10, "Book", "audiobook", url="https://listen.avrana.net/item/10")]))
        home = build_home(v, TILES, limit=12)
        # Owner request 2026-10-28: up to the section limit (12) across libraries, "See all" only when there is more
        self.assertEqual(["Film 1", "Book", "Film 2", "Film 3", "Film 4", "Film 5"], [c.title for c in home.continue_items])
        self.assertIsNone(home.continue_more_href)
        self.assertEqual("60 minutes left", home.continue_items[0].progress)
        self.assertEqual("square", home.continue_items[1].shape)
        two = build_home(v, TILES, limit=2)
        self.assertEqual((2, "/continue"), (len(two.continue_items), two.continue_more_href))
        self.assertEqual("/continue?for=watch", build_home(v, TILES, limit=2, focus="watch").continue_more_href)
        self.assertGreater(12, RAIL_MOST)                  # the Library keeps its own four

    def test_hrefs_are_https_only_and_unsafe_items_are_dropped(self):
        bad = ["http://x.example/a", "javascript:alert(1)", "//evil.example", "/relative", "", 5]
        v = self.view(sec("jellyfin", "continue", "ok",
                          [item(i, f"Bad {i}", url=u) for i, u in enumerate(bad)] + [item(99, "Good")]))
        home = build_home(v, TILES)
        self.assertEqual(["Good"], [c.title for c in home.continue_items])
        self.assertTrue(all(c.href.startswith("https://") for c in home.continue_items))

    def test_empty_continue_is_one_sentence_but_not_when_the_service_is_down(self):
        empty = build_home(self.view(sec("jellyfin", "continue", "empty"), sec("jellyfin", "recent", "ok", [item(1, "N")])), TILES)
        self.assertIn("Nothing in progress", empty.continue_said)
        down = build_home(self.view(sec("jellyfin", "continue", "unavailable"), sec("jellyfin", "recent", "ok", [item(1, "N")])), TILES)
        self.assertIsNone(down.continue_said)
        self.assertEqual(("Movies and TV are unavailable right now. Anything shown from them may be out of date.",),
                         down.notices)

    def test_new_tabs_come_from_the_members_own_libraries_and_unknown_values_fall_back_to_all(self):
        v = self.view(sec("jellyfin", "recent", "ok", [item(1, "F1"), item(2, "F2")]),
                      sec("audiobookshelf", "recent", "empty"))
        for bad in (None, "", "all", "calibre-web", "komga", "../etc", "JELLYFIN", "jellyfin ", "x" * 500, 7):
            home = build_home(v, TILES, new_tab=bad)
            self.assertEqual([("all", "All", True), ("jellyfin", "Movies and TV", False),
                              ("audiobookshelf", "Audiobooks", False)], list(home.new_tabs), bad)
            self.assertEqual(["F1", "F2"], [c.title for c in home.new_items])
        own = build_home(v, TILES, new_tab="audiobookshelf")
        self.assertEqual("Nothing added to Audiobooks recently.", own.new_said)
        self.assertEqual(NEW_ALL, [k for k, _n, cur in build_home(v, TILES).new_tabs if cur][0])

    def test_all_says_which_library_and_a_library_tab_says_what_it_is(self):
        v = self.view(sec("jellyfin", "recent", "ok", [item(1, "F1", series="S")]),
                      sec("audiobookshelf", "recent", "ok", [item(2, "B1", "audiobook", url="https://listen.avrana.net/item/2")]))
        self.assertEqual(["Movies and TV", "Audiobooks"], [c.line for c in build_home(v, TILES).new_items])
        self.assertEqual(["S"], [c.line for c in build_home(v, TILES, new_tab="jellyfin").new_items])

    def test_everything_down_says_so_once_and_shows_no_rails(self):
        v = self.view(sec("jellyfin", "continue", "unavailable"), sec("jellyfin", "recent", "unavailable"))
        home = build_home(v, TILES)
        self.assertTrue(home.all_down)
        self.assertEqual(("Movies and TV are unavailable right now.",), home.notices)
        self.assertFalse(home.show_continue or home.show_new)
        self.assertFalse(home.no_library)
        two = build_home(self.view(*v["sections"], sec("audiobookshelf", "continue", "unavailable")), TILES)
        self.assertEqual(("None of your libraries is answering right now.",), two.notices)   # one line, not two

    def test_every_library_not_set_up_is_one_block_with_the_next_step(self):
        home = build_home(self.view(sec("jellyfin", "continue", "not_linked"), sec("jellyfin", "recent", "not_linked")),
                          TILES)
        self.assertTrue(home.all_unset)
        self.assertFalse(home.all_down)
        self.assertEqual("/help/trouble#not-set-up", home.setup_href)
        self.assertIsNone(home.retry_href)
        mixed = build_home(self.view(sec("jellyfin", "recent", "not_linked"),
                                     sec("audiobookshelf", "recent", "ok", [item(1, "B", "audiobook")])), TILES)
        self.assertFalse(mixed.all_unset)
        self.assertEqual("/help/trouble#not-set-up", mixed.setup_href)

    def test_not_linked_sentence_and_no_mention_of_a_library_that_is_not_in_the_view(self):
        home = build_home(self.view(sec("jellyfin", "recent", "not_linked")), TILES)
        self.assertEqual(("Movies and TV are not set up for your account yet.",), home.notices)
        self.assertIsNone(service_notice("jellyfin", "ok"))
        self.assertIsNone(service_notice("nope", "unavailable"))
        text = repr(build_home(self.view(sec("jellyfin", "recent", "ok", [item(1, "F")])), TILES[:1] + TILES[3:]))
        for word in ("Audiobooks", "Comics", "Books"):
            self.assertNotIn(word, text)

    def test_not_permitted_is_never_present(self):
        home = build_home(self.view(sec("komga", "recent", "not_permitted"), sec("jellyfin", "recent", "ok", [item(1, "F")])), TILES)
        self.assertEqual(["jellyfin"], [k for k, _n, _c in home.new_tabs])

    def test_initial_and_name_are_plain_text(self):
        self.assertEqual("P", initial_of("pat"))
        self.assertEqual("A", initial_of(""))
        self.assertEqual("1", initial_of("‮ 1x"))
        self.assertEqual("Member", build_home(self.view(), TILES, member_name="").member_name)


require_framework()

A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-books|avrana-comics")]
NOTHING = [(USER, "member-x"), (GROUPS, "avrana-users")]


def main_of(text):
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def places_of(text):
    return re.search(r'<nav class="places[^"]*".*?</nav>', text, flags=re.S).group(0)


class HomePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dev.mock_jellyfin import MockJellyfin
        cls.mock = MockJellyfin(slow_seconds=3.0).start()
        cls.client = make_client(make_settings(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=0.6))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.set_mode("ok")
        self.mock.reset()

    def test_two_members_each_see_only_their_own_places_and_items(self):
        a, b = self.client.get("/", headers=A).text, self.client.get("/", headers=B).text
        self.assertIn("Synthetic Film One", main_of(a))
        self.assertNotIn("Synthetic Film Two", a)
        self.assertIn("Synthetic Film Two", main_of(b))
        self.assertNotIn("Synthetic Film One", b)
        # Home's filters (owner decision 2026-10-27) name only each member's own places
        self.assertNotIn('read"', places_of(a))
        self.assertRegex(places_of(b), r'href="/(\?for=)?read"')
        self.assertIn("signed in as member-a", a)            # the Me tab names who is signed in
        self.assertIn("signed in as member-b", b)
        self.assertNotIn("member-b", a)

    def test_unknown_tab_values_fall_back_to_all_and_are_never_echoed(self):
        base = main_of(self.client.get("/", headers=A).text)
        for value in ("calibre-web", "nope", "%3Cscript%3E", "all", "jellyfin%00", "x" * 600, ""):
            r = self.client.get(f"/?new={value}", headers=A)
            self.assertEqual(200, r.status_code, value)
            self.assertEqual(base, main_of(r.text), value)
            self.assertNotIn("<script>", r.text)
        one = main_of(self.client.get("/?new=jellyfin", headers=A).text)
        # this member has one library: nothing to choose between, so no filter row (owner decision 2026-10-27)
        self.assertNotIn('class="tabs"', one)
        self.assertIn('<h2 id="h-new">New to Avrana</h2>', one)

    def test_a_member_cannot_select_a_library_they_cannot_use(self):
        r = self.client.get("/?new=audiobookshelf", headers=A)
        self.assertNotIn("Audiobooks", r.text)
        self.assertNotIn("?new=audiobookshelf", r.text)

    def test_member_with_no_library_gets_nothing_to_show(self):
        r = self.client.get("/", headers=NOTHING)
        self.assertEqual(200, r.status_code)
        self.assertIn("No library yet", r.text)
        self.assertIn("No library is shared with this account yet.", r.text)
        self.assertNotIn('class="rail', r.text)
        self.assertEqual([], self.mock.paths())

    def test_unavailable_library_is_struck_in_place_with_a_sentence_and_no_error_page(self):
        self.mock.set_mode("500")
        from webtests.support import make_client as mk
        c = mk(make_settings(home_sections=True, jellyfin_base_url=self.mock.url, timeout=0.6))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        r = c.get("/", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertIn('<s>Watch</s><span class="sr">, unavailable: what to do</span>', places_of(r.text))
        self.assertIn("Movies and TV are unavailable right now.", main_of(r.text))
        self.assertNotIn("Traceback", r.text)
        self.assertNotIn("500", main_of(r.text))

    def test_titles_are_escaped_and_hrefs_are_https_only_even_from_a_hostile_adapter(self):
        hostile = ['<script>alert(1)</script>', '"><img src=x onerror=1>', "a&b"]
        client = make_client(make_settings(home_sections=True),
                             adapters=[StubAdapter({"member-a": [(f"{i:032x}", t, 0.5) for i, t in enumerate(hostile, 1)]})])
        page = client.get("/", headers=A).text
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("a&amp;b", page)
        hrefs = re.findall(r'class="card" href="([^"]*)"', main_of(page))
        self.assertTrue(hrefs)
        # the contract's https hand-off, or (Recently added, owner decision 2026-10-27) the item's own title page
        self.assertTrue(all(h.startswith("https://") or re.match(r"^/title/(jellyfin|audiobookshelf|komga|calibre-web)/[A-Za-z0-9_-]+$", h) for h in hrefs), hrefs)


if __name__ == "__main__":
    unittest.main()
