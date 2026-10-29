"""Home's shelves and the richer Details (owner request 2026-10-28). Offline, synthetic data only.

  * Continue shows up to the section limit (12) across the member's libraries; on All it includes Up next (the next
    episode of a show they are watching, with the show's poster); "See all" opens the Continue page, and only when there
    is more than the rail shows. The same inside each filter.
  * New to Avrana and New Releases show 12, then "Show more" up to 20 in all (no date window on either).
  * New Releases is capitalised and has chips by kind (All, Movies and TV, Audiobooks, Comics, Books), each only when
    the list holds something of that kind.
  * The title page lists credits, genres and tags, only those the library returned.
  * No visible scroll bars; scrolling itself is untouched.
"""
import re
import unittest

from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import (CONTINUE_PATH, NEW_RELEASES, SHELF_MOST, UP_NEXT, build_continue_page,
                                       build_home, build_title, title_facts)

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

TODAY = "2026-10-28"
HANDOFF = {"jellyfin": "https://watch.avrana.net/web/#/details?id=", "audiobookshelf": "https://listen.avrana.net/item/",
           "komga": "https://read.avrana.net/book/", "calibre-web": "https://books.avrana.net/book/"}
TILES = [("watch", Trusted("Watch"), Trusted("")), ("listen", Trusted("Listen"), Trusted("")),
         ("read", Trusted("Read"), Trusted("")), ("help", Trusted("Help"), Trusted(""))]
NO_BOOKS_TILES = [t for t in TILES if t[0] != "read"]      # a member with no books library
TITLES = frozenset({"jellyfin", "audiobookshelf", "komga"})
PROGRESS = {"fraction": 0.5, "percent": 50, "position_seconds": 600, "duration_seconds": 1200}


def jf(n: int) -> str:
    return f"{n:032x}"


def item(service, uid, title, kind="movie", **extra):
    out = {"id": f"{service}:{uid}", "service": service, "kind": kind, "title": title,
           "handoff_url": HANDOFF[service] + uid}
    out.update(extra)
    return out


def sec(service, section, state, items=()):
    return {"service": service, "section": section, "state": state, "items": list(items)}


def films(n, start=1, **extra):
    return [item("jellyfin", jf(start + i), f"Synthetic Film {start + i}", **extra) for i in range(n)]


def books(n, start=1, **extra):
    return [item("audiobookshelf", f"li_book{start + i:06d}", f"Synthetic Book {start + i}", "audiobook", **extra)
            for i in range(n)]


def view(*sections):
    return {"sections": list(sections)}


class ContinueRail(unittest.TestCase):
    def test_up_to_twelve_across_libraries_then_see_all_only_when_there_is_more(self):
        v = view(sec("jellyfin", "continue", "ok", films(8, progress=PROGRESS)),
                 sec("audiobookshelf", "continue", "ok", books(5, progress=PROGRESS)))
        home = build_home(v, TILES, limit=12)
        self.assertEqual(12, len(home.continue_items))
        self.assertEqual({"Synthetic Book 1", "Synthetic Film 1"}, {c.title for c in home.continue_items[:2]})
        self.assertEqual(CONTINUE_PATH, home.continue_more_href)
        exactly = view(sec("jellyfin", "continue", "ok", films(7, progress=PROGRESS)),
                       sec("audiobookshelf", "continue", "ok", books(5, progress=PROGRESS)))
        home = build_home(exactly, TILES, limit=12)
        self.assertEqual((12, None), (len(home.continue_items), home.continue_more_href))

    def test_inside_a_filter_the_same_rule_holds_for_that_place_alone(self):
        v = view(sec("jellyfin", "continue", "ok", films(13, progress=PROGRESS)),
                 sec("audiobookshelf", "continue", "ok", books(2, progress=PROGRESS)))
        watch = build_home(v, TILES, limit=12, focus="watch")
        self.assertEqual((12, "/continue?for=watch"), (len(watch.continue_items), watch.continue_more_href))
        self.assertTrue(all(c.title.startswith("Synthetic Film") for c in watch.continue_items))
        listen = build_home(v, TILES, limit=12, focus="listen")
        self.assertEqual((2, None), (len(listen.continue_items), listen.continue_more_href))

    def test_all_includes_up_next_with_the_show_poster_and_never_twice(self):
        poster = {"ref": f"jellyfin/primary/{jf(90)}", "alt": "Poster for Synthetic Show", "shape": "poster"}
        watching = item("jellyfin", jf(1), "Synthetic Episode 3", "episode", series="Synthetic Show", subtitle="S1 E3",
                        progress=PROGRESS, artwork=poster)
        nxt = [item("jellyfin", jf(1), "Synthetic Episode 3", "episode", series="Synthetic Show", artwork=poster),
               item("jellyfin", jf(2), "Synthetic Pilot", "episode", series="Synthetic Other", subtitle="S1 E1",
                    artwork={"ref": f"jellyfin/primary/{jf(91)}", "alt": "Poster", "shape": "poster"})]
        v = view(sec("jellyfin", "continue", "ok", [watching]), sec("jellyfin", "next_up", "ok", nxt),
                 sec("audiobookshelf", "continue", "ok", books(1, progress=PROGRESS)))
        home = build_home(v, TILES, limit=12)
        titles = [c.title for c in home.continue_items]
        self.assertEqual(1, titles.count("Synthetic Episode 3"))
        pilot = home.continue_items[titles.index("Synthetic Pilot")]
        self.assertEqual((UP_NEXT, "poster", "Open"), (pilot.progress, pilot.shape, pilot.action))
        self.assertEqual("/art/jellyfin/primary/" + jf(91), pilot.image)
        # Watch keeps Up next as its own row, never inside Continue as well
        watch = build_home(v, TILES, limit=12, focus="watch")
        self.assertNotIn("Synthetic Pilot", [c.title for c in watch.continue_items])
        self.assertIn("Synthetic Pilot", [c.title for r in watch.rows if r.key == "next" for c in r.items])

    def test_up_next_is_interleaved_so_a_long_continue_never_hides_it(self):
        v = view(sec("jellyfin", "continue", "ok", films(20, progress=PROGRESS)),
                 sec("jellyfin", "next_up", "ok", [item("jellyfin", jf(99), "Synthetic Next", "episode")]))
        titles = [c.title for c in build_home(v, TILES, limit=12).continue_items]
        self.assertEqual(["Synthetic Film 1", "Synthetic Next", "Synthetic Film 2"], titles[:3])

    def test_the_continue_page_lists_everything_and_keeps_the_filter(self):
        v = view(sec("jellyfin", "continue", "ok", films(30, progress=PROGRESS)),
                 sec("audiobookshelf", "continue", "ok", books(4, progress=PROGRESS)))
        page = build_continue_page(v, TILES)
        self.assertEqual((34, None, "/"), (len(page.items), page.focus_label, page.back_href))
        watch = build_continue_page(v, TILES, focus="watch")
        self.assertEqual((30, "/?for=watch"), (len(watch.items), watch.back_href))
        self.assertEqual("Watch", str(watch.focus_label))
        for foreign in ("help", "nope", "<b>"):
            self.assertEqual(34, len(build_continue_page(v, TILES, focus=foreign).items), foreign)
        empty = build_continue_page(view(sec("jellyfin", "continue", "empty")), TILES)
        self.assertEqual(((), "Nothing in progress right now."), (empty.items, empty.said))
        down = build_continue_page(view(sec("jellyfin", "continue", "unavailable"),
                                        sec("audiobookshelf", "continue", "ok", books(1, progress=PROGRESS))), TILES)
        self.assertEqual(("Movies and TV are unavailable right now.",), down.notices)
        self.assertEqual(CONTINUE_PATH, down.retry_href)


class NewRails(unittest.TestCase):
    def recent_view(self, n_films, n_books=0):
        return view(sec("jellyfin", "continue", "empty"), sec("jellyfin", "recent", "ok", films(n_films)),
                    sec("audiobookshelf", "continue", "empty"), sec("audiobookshelf", "recent", "ok", books(n_books)))

    def test_new_to_avrana_shows_twelve_then_show_more_up_to_twenty(self):
        home = build_home(self.recent_view(15, 10), TILES, limit=12, title_services=TITLES)
        self.assertEqual((12, SHELF_MOST - 12), (len(home.new_items), len(home.new_more)))
        self.assertEqual("/?more=new#h-new", home.new_more_href)
        expanded = build_home(self.recent_view(15, 10), TILES, limit=12, more="new")
        self.assertEqual((SHELF_MOST, (), None), (len(expanded.new_items), expanded.new_more, expanded.new_more_href))
        few = build_home(self.recent_view(8, 4), TILES, limit=12)
        self.assertEqual((12, (), None), (len(few.new_items), few.new_more, few.new_more_href))

    def test_a_library_tab_keeps_its_choice_in_the_more_link_and_unknown_more_is_ignored(self):
        home = build_home(self.recent_view(16, 3), TILES, limit=12, new_tab="jellyfin")
        self.assertEqual((12, 4), (len(home.new_items), len(home.new_more)))
        self.assertEqual("/?new=jellyfin&more=new#h-new", home.new_more_href)
        self.assertEqual(("/#h-new", "/?new=jellyfin#h-new", "/?new=audiobookshelf#h-new"), home.new_hrefs)
        for junk in ("all", "<b>", "released;x", "new " * 3):
            self.assertEqual(12, len(build_home(self.recent_view(16, 3), TILES, limit=12, more=junk).new_items), junk)

    def released_view(self):
        def rel(service, uid, title, kind, day):
            return item(service, uid, title, kind, released=day)
        return view(sec("jellyfin", "continue", "empty"), sec("jellyfin", "recent", "empty"),
                    sec("jellyfin", "released", "ok", [rel("jellyfin", jf(i), f"Synthetic Film {i}", "movie",
                                                           f"2026-09-{i:02d}") for i in range(1, 15)]),
                    sec("audiobookshelf", "released", "ok", [rel("audiobookshelf", "li_book000001", "Synthetic Book",
                                                                 "audiobook", "2026-10-01")]),
                    sec("komga", "released", "ok", [rel("komga", "BOOKAAAA0001", "Synthetic Issue", "comic",
                                                        "2026-10-02"),
                                                    rel("komga", "BOOKAAAA0002", "Synthetic Novel", "ebook",
                                                        "2026-10-03")]))

    def test_new_releases_has_chips_by_kind_for_what_it_holds(self):
        home = build_home(self.released_view(), TILES, limit=12, today=TODAY)
        self.assertEqual(["All", "Movies and TV", "Audiobooks", "Comics", "Books"],
                         [label for _k, label, _c, _h in home.released_tabs])
        self.assertEqual(("/#h-released", "/?rel=books#h-released"),
                         (home.released_tabs[0][3], home.released_tabs[4][3]))
        self.assertTrue(home.released_tabs[0][2])
        self.assertEqual((12, 5), (len(home.released_items), len(home.released_more)))
        self.assertEqual("/?more=released#h-released", home.released_more_href)
        books_only = build_home(self.released_view(), TILES, limit=12, today=TODAY, rel_tab="books")
        self.assertEqual(["Synthetic Novel"], [c.title for c in books_only.released_items])
        self.assertTrue(books_only.released_tabs[4][2])
        self.assertEqual(("/?rel=books#h-new",), books_only.new_hrefs)    # New to Avrana keeps the chosen chip
        for junk in ("nope", "<b>", "all", "jellyfin"):
            self.assertEqual(12, len(build_home(self.released_view(), TILES, today=TODAY, rel_tab=junk).released_items))

    def test_one_kind_alone_has_no_chips(self):
        v = view(sec("jellyfin", "continue", "empty"),
                 sec("jellyfin", "released", "ok", films(3, released="2026-10-01")))
        self.assertEqual((), build_home(v, NO_BOOKS_TILES, today=TODAY).released_tabs)

    # Owner request 2026-10-28: a Books chip, for a member who has a books library.
    def kinds_view(self):
        return view(sec("jellyfin", "continue", "empty"),
                    sec("jellyfin", "released", "ok", films(2, released="2026-10-01")),
                    sec("audiobookshelf", "released", "ok", [item("audiobookshelf", "li_book000001", "Synthetic Book",
                                                                 "audiobook", released="2026-10-02")]))

    def test_the_books_chip_is_offered_to_a_member_with_a_books_library_before_any_book_is_dated(self):
        home = build_home(self.kinds_view(), TILES, today=TODAY)         # TILES has Read (Komga and Calibre-Web)
        self.assertEqual(["All", "Movies and TV", "Audiobooks", "Books"], [t[1] for t in home.released_tabs])
        only_books_place = [t for t in TILES if t[0] != "watch"]
        self.assertIn("Books", [t[1] for t in build_home(self.kinds_view(), only_books_place, today=TODAY).released_tabs])
        home = build_home(self.kinds_view(), NO_BOOKS_TILES, today=TODAY)        # no books library: no Books chip
        self.assertEqual(["All", "Movies and TV", "Audiobooks"], [t[1] for t in home.released_tabs])
        asked = build_home(self.kinds_view(), NO_BOOKS_TILES, today=TODAY, rel_tab="books")    # and `?rel=books` is ignored
        self.assertEqual((3, None), (len(asked.released_items), asked.released_said))

    def test_choosing_books_with_none_dated_keeps_the_chips_and_says_so_calmly(self):
        home = build_home(self.kinds_view(), TILES, today=TODAY, rel_tab="books")
        self.assertEqual(((), "No new releases in Books right now."), (home.released_items, home.released_said))
        self.assertEqual([False, False, False, True], [t[2] for t in home.released_tabs])
        self.assertIsNone(build_home(self.kinds_view(), TILES, today=TODAY).released_said)      # All says nothing

    def test_calibre_web_books_with_a_publication_date_fill_the_books_chip(self):
        v = self.kinds_view()
        v["sections"].append(sec("calibre-web", "released", "ok", [
            item("calibre-web", "101", "Synthetic Calibre Novel", "ebook", released="2026-09-15"),
            item("calibre-web", "102", "Synthetic Older Calibre Novel", "ebook", released="2008-03-01")]))
        books_only = build_home(v, TILES, today=TODAY, rel_tab="books")
        self.assertEqual(["Synthetic Calibre Novel", "Synthetic Older Calibre Novel"],
                         [c.title for c in books_only.released_items])
        self.assertIsNone(books_only.released_said)
        everything = build_home(v, TILES, today=TODAY)
        self.assertEqual(5, len(everything.released_items))                # All loses nothing
        self.assertEqual("Synthetic Older Calibre Novel", everything.released_items[-1].title)   # oldest last

    def test_episodes_with_a_series_poster_make_a_tall_rail_and_a_lone_still_is_lifted_to_it(self):
        poster = {"ref": "jellyfin/primary/" + "b" * 32, "alt": "Poster", "shape": "poster"}
        still = {"ref": "jellyfin/primary/" + "c" * 32, "alt": "Still"}
        v = view(sec("jellyfin", "released", "ok", [
            item("jellyfin", jf(1), "Synthetic Episode", "episode", released="2026-10-05", artwork=poster),
            item("jellyfin", jf(2), "Synthetic Film", "movie", released="2026-10-04")]))
        home = build_home(v, NO_BOOKS_TILES, today=TODAY)
        self.assertEqual((["poster", "poster"], ""), ([c.shape for c in home.released_items], home.released_rail))
        v["sections"][0]["items"][0]["artwork"] = still                  # a show with no poster keeps its still
        home = build_home(v, NO_BOOKS_TILES, today=TODAY)
        self.assertEqual((["still", "poster"], "mixed"), ([c.shape for c in home.released_items], home.released_rail))

    def test_watch_new_releases_row_shows_more_too(self):
        v = self.released_view()
        watch = build_home(v, TILES, limit=12, today=TODAY, focus="watch")
        row = next(r for r in watch.rows if r.key == "released")
        self.assertEqual((NEW_RELEASES, 12, 2, "/?for=watch&more=released#h-released"),
                         (row.heading, len(row.items), len(row.more), row.more_href))


class Markup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        cls.env = make_client(make_settings(home_sections=False)).fastapi_app.state.env

    def render(self, home):
        return self.env.get_template("_sections.html").render(home=home)

    def test_see_all_ends_continue_and_show_more_ends_its_rail_with_hidden_cards(self):
        v = view(sec("jellyfin", "continue", "ok", films(14, progress=PROGRESS)),
                 sec("jellyfin", "recent", "ok", films(16, start=40)))
        html = self.render(build_home(v, TILES, limit=12))
        cont = html.split('id="h-continue"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(12, cont.count('class="card"'))
        self.assertIn('<a class="card more" href="/continue">', cont)
        self.assertIn('See all<span class="sr">: everything you can continue</span>', cont)
        new = html.split('id="h-new"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<ul class="rail tall" id="rail-new">', new)
        self.assertEqual(4, new.count(" data-more hidden>"))
        self.assertIn('href="/?more=new#h-new" data-reveal="rail-new"', new)
        self.assertNotRegex(html, r"style=|<svg|<script|on\w+=")

    def test_new_releases_is_capitalised_with_its_chips(self):
        home = build_home(NewRails().released_view(), TILES, limit=12, today=TODAY)
        html = self.render(home)
        self.assertIn('<h2 id="h-released">New Releases</h2>', html)
        self.assertIn('<nav class="tabs" aria-label="New Releases, by kind">', html)
        self.assertIn('<a href="/?rel=comics#h-released">Comics</a>', html)
        self.assertIn('<a href="/#h-released" aria-current="true">All<span class="ul" aria-hidden="true"></span></a>', html)
        self.assertNotIn("New releases", html)

    def test_new_releases_chips_are_the_same_submenu_as_new_to_avrana_with_the_yellow_rule_under_the_chosen_one(self):
        v = NewRails().released_view()
        v["sections"] += [sec("jellyfin", "recent", "ok", films(2, start=40)),
                          sec("audiobookshelf", "recent", "ok", books(2, start=40))]
        html = self.render(build_home(v, TILES, limit=12, today=TODAY, rel_tab="comics"))
        navs = re.findall(r'<nav class="tabs" aria-label="([^"]+)">(.*?)</nav>', html, re.S)
        self.assertEqual(["New Releases, by kind", "New to Avrana, by library"], [label for label, _body in navs])
        for _label, body in navs:
            anchors = re.findall(r"<a [^>]*>.*?</a>", body, re.S)
            self.assertGreater(len(anchors), 2)
            current = [a for a in anchors if "aria-current" in a]
            self.assertEqual(1, len(current), body)
            self.assertRegex(current[0], r'^<a href="[^"]+" aria-current="true">[^<]+<span class="ul" aria-hidden="true"></span></a>$')
            self.assertEqual(len(anchors) - 1, len([a for a in anchors if re.fullmatch(r'<a href="[^"]+">[^<]+</a>', a)]))
        self.assertEqual("Comics", re.search(r'>([^<]+)<span class="ul"', navs[0][1]).group(1))
        self.assertNotRegex(html, r"style=|<svg|<script|on\w+=")

    def test_a_chosen_chip_with_nothing_still_shows_the_chips_and_one_calm_line(self):
        v = NewRails().kinds_view()
        html = self.render(build_home(v, TILES, limit=12, today=TODAY, rel_tab="books"))
        released = html.split('id="h-released"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<a href="/?rel=books#h-released" aria-current="true">Books<span class="ul"', released)
        self.assertIn('<p class="said">No new releases in Books right now.</p>', released)
        self.assertNotIn("<ul", released)

    def test_the_released_rail_is_tall_and_mixed_when_a_still_stands_among_posters(self):
        poster = {"ref": "jellyfin/primary/" + "b" * 32, "alt": "Poster", "shape": "poster"}
        still = {"ref": "jellyfin/primary/" + "c" * 32, "alt": "Still"}

        def rail(artwork):
            v = view(sec("jellyfin", "released", "ok", [
                item("jellyfin", jf(1), "Synthetic Episode", "episode", released="2026-10-05", artwork=artwork),
                item("jellyfin", jf(2), "Synthetic Film", "movie", released="2026-10-04", artwork=poster)]))
            return self.render(build_home(v, NO_BOOKS_TILES, limit=12, today=TODAY))
        tall = rail(poster)
        self.assertIn('<ul class="rail tall" id="rail-released">', tall)
        self.assertEqual(0, tall.count('class="w-still"'))
        mixed = rail(still)
        self.assertIn('<ul class="rail tall mixed" id="rail-released">', mixed)
        self.assertIn('<li class="w-still">', mixed)


class TitleFacts(unittest.TestCase):
    def section(self, **extra):
        it = item("jellyfin", jf(5), "Synthetic Film", **extra)
        return {"state": "ok", "items": [it]}

    def test_credits_genres_and_tags_with_fixed_labels(self):
        page = build_title(self.section(credits={"cast": ["Synthetic Lead", "Synthetic Second"],
                                                 "directors": ["Synthetic Director"], "producers": ["Nope"],
                                                 "writers": "not a list"},
                                        genres=["Synthetic Drama"], tags=["Synthetic Tag", "Synthetic Other"]),
                           "jellyfin", jf(5), None)
        self.assertEqual((("Cast", ("Synthetic Lead", "Synthetic Second")), ("Director", ("Synthetic Director",)),
                          ("Genre", ("Synthetic Drama",)), ("Tags", ("Synthetic Tag", "Synthetic Other"))), page.facts)

    def test_nothing_returned_is_nothing_shown(self):
        self.assertEqual((), build_title(self.section(), "jellyfin", jf(5), None).facts)
        self.assertEqual((), title_facts({"credits": ["cast"], "genres": "Drama", "tags": [7, None, ""]}))

    def test_every_role_has_its_label(self):
        it = {"credits": {"authors": ["A", "B"], "narrators": ["N"], "artists": ["P"], "writers": ["W1", "W2"]}}
        self.assertEqual(["Writers", "Authors", "Narrator", "Artist"], [label for label, _n in title_facts(it)])

    def test_the_title_page_renders_the_facts_as_a_list_after_about(self):
        require_framework()
        env = make_client(make_settings(home_sections=False)).fastapi_app.state.env
        page = build_title(self.section(summary="A synthetic summary.", credits={"cast": ["Synthetic <Lead>"]},
                                        genres=["Synthetic Drama"]), "jellyfin", jf(5), None)
        html = env.get_template("title.html").render(page=page)
        self.assertLess(html.index('class="title-about"'), html.index('<dl class="title-facts">'))
        self.assertIn('<dt class="kicker">Cast</dt><dd dir="auto">Synthetic &lt;Lead&gt;</dd>', html)
        self.assertIn('<dt class="kicker">Genre</dt><dd dir="auto">Synthetic Drama</dd>', html)


class Stylesheet(unittest.TestCase):
    def test_no_visible_scroll_bars_and_scrolling_is_left_alone(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parents[1] / "avrana_home/app/templates/home.css").read_text(encoding="utf-8")
        self.assertIn("*{scrollbar-width:none;}", css)
        self.assertIn("*::-webkit-scrollbar{display:none;", css)
        self.assertIn("overflow-x:auto", css)                  # rails still scroll
        self.assertNotRegex(css, r"overflow(-x)?:hidden[^}]*\.rail\b")


A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
NOBODY = [(USER, "member-x"), (GROUPS, "avrana-users")]


class ContinuePage(unittest.TestCase):
    """The route end to end over an in-memory adapter (StubAdapter ignores the limit and returns everything)."""

    @classmethod
    def setUpClass(cls):
        require_framework()
        data = {"member-a": [(jf(i), f"Synthetic Film {i}", 0.5) for i in range(1, 16)]}
        cls.client = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)])
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_home_shows_twelve_and_see_all_opens_every_one(self):
        home = self.client.get("/", headers=A).text
        cont = home.split('id="h-continue"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(12, cont.count('class="card"'))
        self.assertIn('href="/continue"', cont)
        r = self.client.get("/continue", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertEqual(15, r.text.count('class="card"'))
        self.assertIn('<h2 class="topic" id="h-continue">Continue</h2>', r.text)
        self.assertIn('<a class="link" href="/">Back to Home</a>', r.text)
        self.assertIn('class="tabbar glass"', r.text)

    def test_unknown_filters_are_all_and_never_echoed(self):
        for value in ("nope", "%3Cscript%3E", "x" * 600):
            r = self.client.get(f"/continue?for={value}", headers=A)
            self.assertEqual(200, r.status_code)
            self.assertNotIn("<script>", r.text)
            self.assertNotIn("nope", re.sub(r"<style>.*?</style>", "", r.text, flags=re.S))

    def test_no_identity_or_no_library_is_the_standard_404(self):
        self.assertEqual(404, self.client.get("/continue").status_code)
        self.assertEqual(404, self.client.get("/continue", headers=NOBODY).status_code)


if __name__ == "__main__":
    unittest.main()
