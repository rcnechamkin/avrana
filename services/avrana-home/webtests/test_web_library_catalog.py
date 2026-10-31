"""The Library as a complete catalogue, through HTTP (handoff 02, 03, 05, 08). SYNTHETIC data only, real adapters over the
in-memory upstreams of catalog_stack.py. The flag off is the old page; on, each member sees only their own libraries,
counts, titles, covers and links, cold and warm, and a library that is down is never an empty one."""
import re
import unittest

from avrana_home.app import catalogvm
from .catalog_stack import KEY_D, Stack, headers
from .support import make_client, make_settings, require_framework

A, B, C, D = headers("member-a"), headers("member-b"), headers("member-c"), headers("member-d")


class Base(unittest.TestCase):
    catalog = True

    def setUp(self):
        require_framework()
        self.stack = self.make_stack()
        self.client = make_client(make_settings(home_sections=True, library_catalog=self.catalog),
                                  adapters=self.stack.adapters())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.stack.dir.cleanup)

    def make_stack(self):
        return Stack()

    def get(self, url, who=A):
        return self.client.get(url, headers=who)


class FlagOff(Base):
    catalog = False

    def test_the_old_library_is_untouched(self):
        page = self.get("/library")
        self.assertEqual(200, page.status_code)
        self.assertIn('class="chip', page.text)
        self.assertNotIn('class="lib-cats"', page.text)
        self.assertNotIn('class="lib-switch"', page.text)


class Overview(Base):
    def test_each_member_gets_a_card_for_each_library_they_hold_and_no_other(self):
        a, b = self.get("/library", A).text, self.get("/library", B).text
        self.assertEqual(["/library?lib=jellyfin", "/library?lib=calibre-web"], re.findall(r'class="lib-cat" href="([^"]+)"', a))
        self.assertEqual(["/library?lib=audiobookshelf", "/library?lib=komga"], re.findall(r'class="lib-cat" href="([^"]+)"', b))
        for hidden in ("Comics", "Audiobooks", "lib=komga", "lib=audiobookshelf"):
            self.assertNotIn(hidden, a)
        for hidden in ("Movies and TV", "lib=jellyfin", "lib=calibre-web", "Books<"):
            self.assertNotIn(hidden, b)

    def test_counts_are_real_say_what_they_count_and_are_left_out_when_unknown(self):
        a, b = self.get("/library", A).text, self.get("/library", B).text
        self.assertIn('<span class="lib-cat-d">60 movies</span>', a)
        self.assertIn('<span class="lib-cat-d">50 series</span>', b)
        self.assertIn('<span class="lib-cat-d">50 audiobooks</span>', b)
        books = a.split('href="/library?lib=calibre-web"')[1].split("</a>")[0]
        self.assertNotRegex(books, r"\d+ books?")                  # more than one window: the feed has no count

    def test_covers_are_decorative_and_at_most_three(self):
        card = self.get("/library", A).text.split('class="lib-cat"')[1].split("</a>")[0]
        self.assertEqual(3, card.count("<img"))
        self.assertEqual(3, card.count('alt=""'))
        self.assertIn('<span class="sr">Browse </span>Movies and TV', card)

    def test_one_page_asks_each_library_for_one_small_page_and_no_per_card_call(self):
        self.get("/library", A)
        listings = [c for c in self.stack.jellyfin.calls if c[0] == "/Items"]
        self.assertEqual(1, len(listings))
        self.assertEqual("3", listings[0][1]["limit"])

    def test_no_library(self):
        page = self.get("/library", C)
        self.assertIn("No library yet", page.text)
        self.assertEqual([], self.stack.jellyfin.calls + self.stack.calibre.calls)

    def test_a_down_library_is_said_and_the_others_stay(self):
        self.stack.calibre.status = 500
        page = self.get("/library", A).text
        self.assertIn("60 movies", page)
        self.assertIn("Not answering right now", page)
        self.assertIn("Try again", page)
        self.assertNotIn("0 books", page)

    def test_the_way_to_search_and_ask_stays(self):
        self.assertIn('<a href="/search">Search</a>', self.get("/library", A).text)


class Catalog(Base):
    def test_page_two_is_real_and_works_without_script(self):
        one = self.get("/library?lib=jellyfin", A).text
        self.assertIn("Alpha Film 0000", one)
        self.assertNotIn("Alpha Film 0024", one)
        self.assertIn('<a href="/library?lib=jellyfin&amp;page=2" rel="next">', one)
        self.assertNotIn('rel="prev"', one)
        two = self.get("/library?lib=jellyfin&page=2", A).text
        self.assertIn("Alpha Film 0024", two)
        self.assertNotIn("Alpha Film 0023", two)
        self.assertIn('<a href="/library?lib=jellyfin" rel="prev">', two)
        last = self.get("/library?lib=jellyfin&page=3", A).text
        self.assertIn("Alpha Film 0059", last)
        self.assertNotIn('rel="next"', last)

    def test_an_old_book_past_every_recent_feed_is_reachable(self):
        self.assertIn("Alpha Novel 0129", self.get("/library?lib=calibre-web&page=6", A).text)
        self.assertEqual([], [c for c in self.stack.calibre.calls if c[0] == "/opds/new"])

    def test_movies_and_shows_are_apart(self):
        films = self.get("/library?lib=jellyfin", A).text
        shows = self.get("/library?lib=jellyfin&group=series", A).text
        self.assertNotIn("Alpha Show", films)
        self.assertNotIn("Alpha Film", shows)
        self.assertIn("30 shows", shows)
        self.assertIn('href="/library?lib=jellyfin&amp;group=series" aria-current="true"', shows)

    def test_a_library_with_one_grouping_shows_no_control(self):
        self.assertNotIn('class="tabs"', self.get("/library?lib=calibre-web", A).text)

    def test_comics_are_series_and_open_the_series(self):
        page = self.get("/library?lib=komga", B).text
        self.assertIn("Bravo Series 0000", page)
        self.assertIn('href="https://read.avrana.net/series/SERIES000000"', page)
        self.assertIn("/art/komga/series/SERIES000000", page)
        self.assertEqual([], self.stack.shared_komga.calls)

    def test_the_switcher_holds_only_the_members_own_and_changes_directly(self):
        menu = self.get("/library?lib=jellyfin", A).text.split('class="lib-menu"')[1].split("</ul>")[0]
        self.assertEqual(["/library", "/library?lib=jellyfin", "/library?lib=calibre-web"], re.findall(r'href="([^"]+)"', menu))
        self.assertIn('href="/library?lib=jellyfin" aria-current="page"', menu)

    def test_a_foreign_or_hostile_library_is_the_overview_asks_nobody_and_is_not_echoed(self):
        for raw in ("komga", "audiobookshelf", "%3Cscript%3Ealert(1)%3C/script%3E", "x" * 400):
            page = self.get(f"/library?lib={raw}", A)
            self.assertEqual(200, page.status_code)
            self.assertIn('class="lib-cats"', page.text)
            self.assertNotIn("<script>alert", page.text)
            self.assertNotIn("Series 0000", page.text)
        self.assertEqual({}, self.stack.keys)
        self.assertEqual([], self.stack.audiobookshelf.calls)

    def test_bad_group_page_and_view_fall_back_and_are_not_echoed(self):
        base = self.get("/library?lib=jellyfin", A).text
        for query in ("group=%22onload", "page=0", "page=-1", "page=abc", "page=999999", "page=1e3", "view=%3Cb%3E"):
            page = self.get(f"/library?lib=jellyfin&{query}", A).text
            self.assertEqual(base, page, query)

    def test_old_layout_links_still_work(self):
        for raw, wanted in (("list", "lib-v-list"), ("details", "lib-v-list"), ("small", "lib-v-compact"),
                            ("compact", "lib-v-compact")):
            self.assertIn(f'class="lib-grid {wanted}"', self.get(f"/library?lib=jellyfin&view={raw}", A).text)
        self.assertIn('class="lib-grid"', self.get("/library?lib=jellyfin&view=shelves", A).text)

    def test_grouping_and_layout_are_kept_across_pages_and_a_grouping_change_starts_over(self):
        page = self.get("/library?lib=jellyfin&group=movies&view=list&page=2", A).text
        self.assertIn('href="/library?lib=jellyfin&amp;view=list&amp;page=3"', page)
        self.assertIn('href="/library?lib=jellyfin&amp;group=series&amp;view=list"', page)

    def test_past_the_end_is_said_with_a_way_back(self):
        page = self.get("/library?lib=jellyfin&page=9", A).text
        self.assertIn(catalogvm.PAST_THE_END, page)
        self.assertIn('rel="prev"', page)

    def test_nothing_yet(self):
        self.stack.films["a" * 32] = []
        self.assertIn(catalogvm.NOTHING_YET, self.get("/library?lib=jellyfin", A).text)

    def test_outage_is_never_empty(self):
        self.stack.jellyfin.status = 500
        page = self.get("/library?lib=jellyfin", A).text
        self.assertIn("answering right now", page)
        self.assertNotIn(catalogvm.NOTHING_YET, page)
        self.assertIn("Try again", page)

    def test_titles_are_escaped(self):
        self.stack.films["a" * 32][0]["Name"] = '<img src=x onerror=alert(1)>'
        page = self.get("/library?lib=jellyfin", A).text
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x", page)

    def test_the_page_scripts_nothing_inline_and_is_not_stored(self):
        page = self.get("/library?lib=jellyfin", A)
        self.assertNotRegex(page.text, r"<script(?![^>]*src=)")
        self.assertNotRegex(page.text, r"<[^>]+ on[a-z]+=")
        self.assertIn("no-store", page.headers["cache-control"])


class ConnectComics(unittest.TestCase):
    """Me -> Comics open to the member: the state says what to do and links there; a refused key says reconnect."""

    def stack_for(self, **kwargs):
        require_framework()
        self.stack = Stack(writable_keys=True, **kwargs)
        self.client = make_client(make_settings(home_sections=True, library_catalog=True, komga_connect=True,
                                                komga_base_url="http://komga.test"),
                                  adapters=self.stack.adapters(), komga_key_client=object())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.stack.dir.cleanup)

    def get(self, url):
        return self.client.get(url, headers=D).text

    def test_without_a_key_it_says_connect_and_links_to_me_comics(self):
        self.stack_for(keyed_d=False)
        card = self.get("/library").split('href="/me/comics"')[1].split("</a>")[0]
        self.assertIn("Connect comics", card)
        page = self.get("/library?lib=komga")
        self.assertIn('<a class="link" href="/me/comics">Connect comics</a>', page)
        self.assertNotIn("Reconnect", page)
        self.assertEqual([], self.stack.shared_komga.calls)

    def test_a_refused_key_says_reconnect(self):
        self.stack_for()
        self.stack.transport(KEY_D).status = 401
        page = self.get("/library?lib=komga")
        self.assertIn('<a class="link" href="/me/comics">Reconnect comics</a>', page)
        self.assertNotIn(catalogvm.NOTHING_YET, page)
        self.assertIn("Reconnect comics", self.get("/library").split('href="/me/comics"')[1].split("</a>")[0])

    def test_no_link_for_a_member_without_comics(self):
        self.stack_for(keyed_d=False)
        self.assertNotIn("/me/comics\"", self.client.get("/library", headers=A).text.split("lib-cats")[1])


class NoKey(Base):
    def make_stack(self):
        return Stack(keyed_d=False)

    def test_comics_without_a_key_is_not_set_up_and_never_the_shared_account(self):
        card = self.get("/library", D).text.split('href="/library?lib=komga"')[1].split("</a>")[0]
        self.assertIn("Not set up yet", card)
        page = self.get("/library?lib=komga", D).text
        self.assertIn("What to do next", page)
        self.assertNotIn(catalogvm.NOTHING_YET, page)
        self.assertEqual([], self.stack.shared_komga.calls)
        self.assertEqual({}, {k: v for k, v in self.stack.keys.items() if k == "d" * 32})


class Isolation(Base):
    OTHER = {"member-a": ("Bravo", "Delta"), "member-b": ("Alpha", "Delta"), "member-d": ()}

    def urls(self, who):
        return {"member-a": ("/library", "/library?lib=jellyfin", "/library?lib=jellyfin&page=2", "/library?lib=calibre-web",
                             "/library?lib=komga", "/library?lib=audiobookshelf"),
                "member-b": ("/library", "/library?lib=komga", "/library?lib=komga&page=2", "/library?lib=audiobookshelf",
                             "/library?lib=jellyfin", "/library?lib=calibre-web")}[who]

    def test_nothing_of_another_member_on_any_page_cold_or_warm(self):
        for _round in ("cold", "warm"):
            for name, who in (("member-a", A), ("member-b", B)):
                for url in self.urls(name):
                    text = self.get(url, who).text
                    for mark in self.OTHER[name]:
                        self.assertNotIn(f"{mark} ", text, (name, url, _round))

    def test_a_forbidden_library_makes_no_call(self):
        self.get("/library?lib=komga", A)
        self.get("/library?lib=audiobookshelf", A)
        self.assertEqual(({}, []), (self.stack.keys, self.stack.audiobookshelf.calls))
        self.stack.calibre.calls.clear()
        self.stack.jellyfin.calls.clear()
        self.get("/library?lib=jellyfin", B)
        self.get("/library?lib=calibre-web", B)
        self.assertEqual([], self.stack.calibre.calls + self.stack.jellyfin.calls)

    def test_a_hidden_cover_is_the_standard_404(self):
        self.assertEqual(200, self.get("/art/komga/series/SERIES000000", B).status_code)
        self.assertEqual(404, self.get("/art/komga/series/SERIES000000", A).status_code)
        self.assertEqual(404, self.get("/art/jellyfin/primary/" + "0" * 30 + "aa", B).status_code)

    def test_a_group_lost_with_a_warm_cache_is_gone_at_once(self):
        self.assertIn("Alpha Film", self.get("/library?lib=jellyfin", A).text)
        narrowed = headers("member-a", "avrana-users|avrana-books")
        page = self.get("/library?lib=jellyfin", narrowed).text
        self.assertNotIn("Alpha Film", page)
        self.assertNotIn("Movies and TV", page)

    def test_no_identity_or_a_forged_one_is_the_standard_404(self):
        self.assertEqual(404, self.client.get("/library?lib=jellyfin").status_code)
        doubled = A + [("X-authentik-username", "member-b")]
        self.assertEqual(404, self.get("/library?lib=jellyfin", doubled).status_code)

    def test_an_address_cannot_choose_another_member(self):
        text = self.get("/library?lib=jellyfin&user=member-b&username=member-b&userId=" + "b" * 32, A).text
        self.assertIn("Alpha Film", text)
        self.assertNotIn("Bravo", text)


class Addresses(unittest.TestCase):
    def test_the_builder_leaves_defaults_out(self):
        groups = ("movies", "series")
        self.assertEqual("/library?lib=jellyfin", catalogvm.catalog_href("jellyfin", groups))
        self.assertEqual("/library?lib=jellyfin&group=series&view=list&page=3",
                         catalogvm.catalog_href("jellyfin", groups, "series", "list", 3))

    def test_page_numbers(self):
        for raw, wanted in (("1", 1), ("99999", 99999), ("100000", 1), ("٣", 1), ("0", 1), ("", 1), (None, 1), ("2 ", 1)):
            self.assertEqual(wanted, catalogvm.clean_page(raw), raw)

    def test_counts_say_what_they_count(self):
        self.assertEqual("1 movie", catalogvm.count_words("jellyfin", "movies", 1))
        self.assertEqual("1,204 series", catalogvm.count_words("komga", "series", 1204))
        self.assertIsNone(catalogvm.count_words("calibre-web", "titles", None))


if __name__ == "__main__":
    unittest.main()
