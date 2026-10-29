"""Komga adapter, a SHARED regular-account view (ADAPTER-CONTRACT 12.2, owner decision 2026-10-15): Recently
added and the New releases shelf (owner decision 2026-10-28), proven against HAND-WRITTEN fixtures that are unverified against any real
server. Offline, synthetic data only. Live compatibility is UNPROVEN."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import logging
import unittest
from datetime import datetime, timedelta, timezone

from avrana_home.adapters.komga import ALLOWED_ROUTES, SHARED_VIEWER, GuardedTransport, KomgaAdapter
from avrana_home.contract import ForbiddenRequest, Kind, SectionState
from avrana_home.resilience import MAX_IMAGE_BYTES, MAX_JSON_BYTES, FakeClock, UrllibTransport
from tests.fake_jellyfin import FakeOpener, FakeTransport
from tests.fake_komga import FIXTURES, PNG, FakeKomga
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-comics")
TOKEN = "SENTINEL-KOMGA-KEY-0000"
ALL_TITLES = ["Synthetic Teen One", "Synthetic Kids One", "Synthetic Mature One", "Synthetic Manga One",
              "Synthetic Comic Two", "Synthetic Comic One"]            # newest first, as the shared account sees them
RECENT_TITLES = ALL_TITLES[:5]          # one book per series: Comic One is older than Comic Two in the same series


def titles(result):
    return [i.title for i in result.items]


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeKomga(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = KomgaAdapter(self.transport, clock=self.clock, owner_confirms_no_member_restrictions=True)
        self.a, self.b = (make_principal(f"member-{x}", GROUPS) for x in "ab")

    def reset(self):
        self.fake.overrides.clear()
        self.fake.requests.clear()
        self.adapter.cache.clear()
        self.adapter.breaker.success(self.adapter.breaker.acquire())


class Constructor(Base):
    def test_refuses_unless_the_owner_confirmation_is_explicitly_true(self):
        for value in (None, False, 0, 1, "yes", "true", "True"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                KomgaAdapter(self.transport, owner_confirms_no_member_restrictions=value)
        with self.assertRaises(ValueError):
            KomgaAdapter(self.transport)                               # the default is refusal

    def test_there_is_no_user_route_and_no_member_mapping(self):
        self.assertEqual([r.name for r in ALLOWED_ROUTES], ["books", "book", "thumbnail", "series"])
        self.assertEqual(self.adapter.resolve_user(self.a).upstream_id, SHARED_VIEWER)
        self.assertEqual(self.adapter.resolve_user(self.b).upstream_id, SHARED_VIEWER)
        self.assertEqual(self.fake.requests, [])

    def test_the_series_route_is_one_series_by_id_and_nothing_under_it(self):
        g = GuardedTransport(self.transport).bind(SHARED_VIEWER)
        self.fake.series["SERIESAAA001"] = {"id": "SERIESAAA001", "metadata": {}}
        g.request("GET", "/api/v1/series/SERIESAAA001", None, 1.0, 1000)        # allowed: it reaches the upstream
        for path, query in (("/api/v1/series", None), ("/api/v1/series/latest", None), ("/api/v1/series/updated", None),
                            ("/api/v1/series/SERIESAAA001/books", None), ("/api/v1/series/SERIESAAA001/thumbnail", None),
                            ("/api/v1/series/SERIESAAA001", {"anything": "1"}), ("/api/v1/series/%2e%2e", None)):
            with self.assertRaises(ForbiddenRequest, msg=path):
                g.request("GET", path, query, 1.0, 1000)
        self.assertEqual(self.fake.paths(), ["/api/v1/series/SERIESAAA001"])


class SharedView(Base):
    def test_every_comics_member_sees_the_same_items_in_the_same_order(self):
        ra, rb = self.adapter.recent_items(self.a), self.adapter.recent_items(self.b)
        self.assertEqual(titles(ra), RECENT_TITLES)
        self.assertEqual(titles(rb), RECENT_TITLES)
        self.assertEqual([i.id for i in ra.items], [i.id for i in rb.items])

    def test_no_user_listing_is_ever_requested(self):
        self.adapter.recent_items(self.a)
        self.adapter.item(self.b, "BOOKAAAA0001")
        self.adapter.fetch_artwork(self.a, "komga/book/BOOKAAAA0001")
        self.assertEqual([p for p in self.fake.paths() if "/users" in p or "/api/v2" in p], [])
        self.assertTrue(self.fake.paths())                    # calls did happen: v1 book routes, and the title's series
        self.assertTrue(all(p.startswith("/api/v1/books") or p == "/api/v1/series/SERIESAAA001"
                            for p in self.fake.paths()), self.fake.paths())

    def test_a_regular_key_works_when_the_user_list_is_forbidden(self):
        self.fake.overrides["/api/v2/users"] = ("status", 403)          # what a regular key gets, if it were asked
        self.assertEqual(titles(self.adapter.recent_items(self.a)), RECENT_TITLES)

    def test_the_item_shape_and_the_handoff_url_come_from_the_contract(self):
        r = self.adapter.recent_items(self.a)
        one = r.items[-1]
        self.assertIs(one.kind, Kind.COMIC)
        self.assertEqual(one.id, "komga:BOOKAAAA0002")
        self.assertEqual(one.handoff_url, "https://read.avrana.net/book/BOOKAAAA0002")
        self.assertEqual((one.subtitle, one.series), ("#2", "Synthetic 001"))
        self.assertEqual(one.artwork.ref, "komga/book/BOOKAAAA0002")

    def test_the_shared_accounts_read_progress_is_never_a_members_own(self):
        for fixture_row in self.fake.latest["content"] + list(self.fake.books.values()):
            self.assertEqual(fixture_row["readProgress"]["page"], 77)   # the fixture does carry progress
        for result in (self.adapter.recent_items(self.a), self.adapter.item(self.a, "BOOKAAAA0001")):
            self.assertTrue(result.items)
            for item in result.items:
                self.assertIsNone(item.progress_fraction)
            blob = json.dumps(result.to_dict())
            for token in ("77", "readProgress", "readDate", "completed"):
                self.assertNotIn(token, blob, token)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason, r.items), (SectionState.EMPTY, "not_offered", ()))

    def test_the_title_page_lists_writers_artists_genres_and_tags(self):
        """Richer Details (owner request 2026-10-28): writers and artists from the book's authors by role, genres from
        its series, tags from the book and the series. Letterers and editors are left out."""
        book = self.fake.books["BOOKAAAA0001"]
        book["metadata"] = dict(book["metadata"], tags=["Synthetic Tag"], authors=[
            {"name": "Synthetic Inker", "role": "inker"}, {"name": "Synthetic Writer", "role": "writer"},
            {"name": "Synthetic Penciller", "role": "penciller"}, {"name": "Synthetic Letterer", "role": "letterer"},
            {"name": "Synthetic Editor", "role": "editor"}, {"name": "Synthetic Writer", "role": "writer"}])
        self.fake.series["SERIESAAA001"] = {"id": "SERIESAAA001", "metadata": {
            "genres": ["Synthetic Genre", "", 7], "tags": ["Synthetic Tag", "Synthetic Series Tag"]}}
        item = self.adapter.item(self.a, "BOOKAAAA0001", fresh=True).items[0]
        self.assertEqual(item.credits, (("writers", ("Synthetic Writer",)),
                                        ("artists", ("Synthetic Inker", "Synthetic Penciller"))))
        self.assertEqual((item.genres, item.tags), (("Synthetic Genre",), ("Synthetic Tag", "Synthetic Series Tag")))
        self.assertEqual(item.to_dict()["credits"], {"writers": ["Synthetic Writer"],
                                                     "artists": ["Synthetic Inker", "Synthetic Penciller"]})

    def test_a_series_that_cannot_be_read_never_fails_the_title_page(self):
        for answer in (("status", 404), ("status", 403), ("body", b'{"id": "SERIESOTHER1", "metadata": {}}'),
                       ("body", b'["not", "a", "series"]')):
            with self.subTest(answer=answer):
                self.reset()
                self.fake.overrides["/api/v1/series/SERIESAAA001"] = answer
                r = self.adapter.item(self.a, "BOOKAAAA0001", fresh=True)
                self.assertEqual(titles(r), ["Synthetic Comic One"])
                self.assertEqual((r.items[0].genres, r.items[0].credits[0][0]), ((), "writers"))

    def test_only_a_title_page_reads_the_series(self):
        self.adapter.recent_items(self.a)
        self.adapter.released_items(self.a)
        self.adapter.search(self.a, "synthetic")
        self.adapter.fetch_artwork(self.a, "komga/book/BOOKAAAA0001")
        self.assertEqual([p for p in self.fake.paths() if "/series" in p], [])

    def test_item_lookup_is_the_shared_accounts_view(self):
        self.assertEqual(titles(self.adapter.item(self.a, "BOOKAAAA0001")), ["Synthetic Comic One"])
        self.assertEqual(titles(self.adapter.item(self.b, "BOOKAAAA0001")), ["Synthetic Comic One"])
        r = self.adapter.item(self.a, "BOOKNOTTHERE1")                  # a 404 from Komga: not visible to the account
        self.assertEqual((r.state, r.items), (SectionState.EMPTY, ()))
        self.assertEqual(self.adapter.health().state, "ok")             # an item-class 404 never counts

    def test_deleted_unreadable_and_vanished_books_are_left_out_neutrally(self):
        for bid, change in (("BOOKAAAA0001", {"deleted": True}), ("BOOKAAAA0002", {"media": {"status": "ERROR"}})):
            self.fake.latest["content"] = [dict(b, **change) if b["id"] == bid else b
                                           for b in self.fake.latest["content"]]
        self.assertEqual(titles(self.adapter.recent_items(self.a)), ALL_TITLES[:4])
        self.reset()
        self.fake.latest["content"] = []
        self.assertEqual(self.adapter.recent_items(self.a).state, SectionState.EMPTY)

    def test_the_page_is_bounded_and_a_larger_answer_is_misbehaviour(self):
        self.adapter.recent_items(self.a, limit=2)
        latest = [q for _, p, q in self.fake.requests if p == "/api/v1/books"]
        self.assertEqual(latest, [{"page": "0", "size": "100", "sort": "created,desc"}])
        page = self.fake.copy_of(self.fake.latest)
        page["content"] = page["content"] * 20
        self.reset()
        self.fake.serve("/api/v1/books", page)
        self.assertEqual(self.adapter.recent_items(self.b, limit=1).reason, "UpstreamMisbehaved")

    def test_the_cache_is_per_member_and_serves_without_a_second_call(self):
        self.adapter.recent_items(self.a)
        self.adapter.recent_items(self.b)
        n = len(self.fake.requests)
        self.assertEqual(titles(self.adapter.recent_items(self.a)), RECENT_TITLES)
        self.assertEqual(len(self.fake.requests), n)


class FileNameTitles(unittest.TestCase):
    """Owner review 2026-10-28: a book with no metadata has its file name as `metadata.title` (scanner tags and all).
    Home shows "<series> #<number>" from the book's own fields instead, and never makes anything up."""

    @staticmethod
    def title(title, name, series="Synthetic Saga", number="2"):
        raw = {"id": "BOOKTITLE001", "name": name, "seriesTitle": series, "media": {"status": "READY"},
               "metadata": {"title": title, "number": number}}
        item, status = KomgaAdapter._book(raw)
        assert status == "ok"
        return item.title, item.series, item.subtitle

    def test_a_file_name_with_scanner_tags_becomes_series_and_number(self):
        raw = "Synthetic Saga 002 (2026) (Digital) (Synthetic-Scanner)"
        self.assertEqual(self.title(raw, raw), ("Synthetic Saga #2", "Synthetic Saga", "#2"))

    def test_a_bare_series_and_padded_number_file_name_becomes_series_and_number(self):
        self.assertEqual(self.title("Synthetic Saga 002", "Synthetic Saga 002")[0], "Synthetic Saga #2")
        self.assertEqual(self.title("synthetic saga - 2", "synthetic saga - 2")[0], "Synthetic Saga #2")

    def test_a_real_title_or_a_file_name_that_reads_as_one_is_kept(self):
        self.assertEqual(self.title("The Quiet Issue", "Synthetic Saga 002 (2026) (Digital)")[0], "The Quiet Issue")
        self.assertEqual(self.title("Synthetic Comic One", "Synthetic Comic One")[0], "Synthetic Comic One")
        self.assertEqual(self.title("Synthetic Saga (2016)", "x")[0], "Synthetic Saga (2016)")   # one group: a title

    def test_without_series_or_number_only_the_tags_go(self):
        raw = "Synthetic Saga 002 (2026) (Digital)"
        self.assertEqual(self.title(raw, raw, series=None)[0], "Synthetic Saga 002")
        self.assertEqual(self.title(raw, raw, number=None)[0], "Synthetic Saga 002")
        self.assertEqual(self.title("(2026) (Digital)", "(2026) (Digital)", series=None)[0], "(2026) (Digital)")

    def test_no_title_falls_back_to_the_name_then_untitled(self):
        self.assertEqual(self.title(None, "Synthetic Saga 002 (2026) (Digital)")[0], "Synthetic Saga #2")
        self.assertEqual(self.title(None, None, series=None)[0], "Untitled")


class EbooksInKomga(unittest.TestCase):
    """Owner review 2026-10-29: EPUB novels in a Komga library showed as comics with "#1" under them. A reflowable
    EPUB is a book: its own title, the author underneath, and no Calibre "Title (id)" folder posing as a series."""

    @staticmethod
    def book(series, media=None, number="1", title="Synthetic Novel"):
        raw = {"id": "BOOKEPUB0001", "name": "synthetic-novel", "seriesTitle": series,
               "media": media if media is not None else {"status": "READY", "mediaProfile": "EPUB"},
               "metadata": {"title": title, "number": number, "authors": [{"name": "Synthetic Author", "role": "writer"}]}}
        item, status = KomgaAdapter._book(raw)
        assert status == "ok"
        return item

    def test_a_reflowable_epub_is_a_book_with_its_author_under_it(self):
        item = self.book("Synthetic Novel (51)")
        self.assertEqual((item.kind, item.title, item.subtitle, item.series),
                         (Kind.EBOOK, "Synthetic Novel", "Synthetic Author", None))

    def test_a_calibre_file_name_title_loses_its_author_tail(self):
        self.assertEqual(self.book("x", title="Synthetic Novel - Synthetic Author").title, "Synthetic Novel")
        self.assertEqual(self.book("x", title="Synthetic Novel - Someone Else").title, "Synthetic Novel - Someone Else")

    def test_a_real_series_is_kept_and_a_one_shot_series_is_dropped(self):
        self.assertEqual(self.book("Synthetic Cycle").series, "Synthetic Cycle")
        self.assertIsNone(self.book("Synthetic Novel").series)

    def test_a_fixed_layout_epub_and_an_archive_stay_comics(self):
        divina = self.book("Synthetic Saga", {"status": "READY", "mediaProfile": "EPUB", "epubDivinaCompatible": True})
        cbz = self.book("Synthetic Saga", {"status": "READY", "mediaProfile": "DIVINA"})
        for item in (divina, cbz):
            self.assertEqual((item.kind, item.subtitle), (Kind.COMIC, "#1"))


class RecentAndReleased(Base):
    """Owner decision 2026-10-28: Recently added is sorted by `created` and shows one book per series, with no date
    window (owner request later that day); New releases is sorted by release date, one book per series."""

    def test_recent_asks_for_the_created_order_never_the_latest_route(self):
        self.adapter.recent_items(self.a)
        self.assertEqual(self.fake.requests, [("GET", "/api/v1/books",
                                               {"sort": "created,desc", "page": "0", "size": "100"})])

    def test_books_added_long_ago_are_still_recent_when_they_are_the_newest(self):
        for b in self.fake.latest["content"]:
            if b["id"] in ("BOOKEEEE0006", "BOOKDDDD0005"):
                b["created"] = "2020-01-01T00:00:00Z"
        self.assertEqual(titles(self.adapter.recent_items(self.a)), RECENT_TITLES)

    def test_a_missing_or_unreadable_added_time_is_never_recent(self):
        for b, value in zip(self.fake.latest["content"], (None, "yesterday", 17, "2026-13-45T00:00:00Z")):
            b["created"] = value
        self.assertEqual(titles(self.adapter.recent_items(self.a)), ["Synthetic Comic Two"])

    def test_nothing_added_in_two_months_still_shows_the_newest_additions(self):
        for b in self.fake.latest["content"]:
            b["created"] = "2020-01-01T00:00:00Z"
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, titles(r)), (SectionState.OK, RECENT_TITLES))

    def test_one_series_never_fills_the_row(self):
        content = self.fake.latest["content"]
        clones = [dict(content[-1], id=f"BOOKAAAA01{n:02d}") for n in range(10)]
        self.fake.latest["content"] = clones + content
        r = self.adapter.recent_items(self.a)
        self.assertEqual([i.series for i in r.items].count("Synthetic 001"), 1)
        self.assertEqual(len(r.items), 5)

    def test_new_releases_are_newest_release_first_one_per_series_and_marked_with_their_shelf(self):
        r = self.adapter.shelves_items(self.a)
        self.assertIs(r.state, SectionState.OK)
        # release dates (days ago): Mature 10, Comic Two -30 (a cover date ahead), Comic One 20 (same series),
        # Teen 40, Kids 70, Manga 100
        self.assertEqual(titles(r), ["Synthetic Comic Two", "Synthetic Mature One", "Synthetic Teen One",
                                     "Synthetic Kids One", "Synthetic Manga One"])
        self.assertEqual({i.shelf for i in r.items}, {"new"})
        self.assertIn(("GET", "/api/v1/books", {"sort": "metadata.releaseDate,desc", "page": "0", "size": "100"}),
                      self.fake.requests)

    def test_a_release_date_far_in_the_future_or_missing_is_not_new(self):
        for b in self.fake.latest["content"]:
            if b["id"] == "BOOKAAAA0002":
                b["metadata"] = dict(b["metadata"], releaseDate="2099-01-01")
            if b["id"] == "BOOKCCCC0004":
                b["metadata"] = {k: v for k, v in b["metadata"].items() if k != "releaseDate"}
        self.assertEqual(titles(self.adapter.shelves_items(self.a)),
                         ["Synthetic Comic One", "Synthetic Teen One", "Synthetic Kids One", "Synthetic Manga One"])

    def test_home_new_releases_is_the_same_listing_as_its_own_section_with_the_day(self):
        r = self.adapter.released_items(self.a)
        self.assertEqual(r.section, "released")
        self.assertEqual(titles(r), titles(self.adapter.shelves_items(self.a)))
        self.assertEqual({i.shelf for i in r.items}, {None})
        self.assertTrue(all(i.released and len(i.released) == 10 for i in r.items))

    def novel(self, n, title, release, created_days_ago, series=None):
        return {"id": f"BOOKNOVEL{n:03d}", "seriesId": series or f"SERIESNOV{n:03d}", "seriesTitle": title,
                "libraryId": "LIBBOOKS01", "name": title, "deleted": False,
                "media": {"status": "READY", "mediaProfile": "EPUB"},
                "metadata": {"title": title, "number": "1", "releaseDate": release, "authors": []},
                "created": (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()}

    def test_novels_and_issues_are_counted_apart_so_a_run_of_issues_cannot_crowd_novels_out(self):
        # Five issues newer than the novel: with a limit of 3 a single list would hold three issues and no novel.
        self.fake.latest["content"].append(self.novel(1, "Synthetic Old Novel", "2001-05-01", 3))
        r = self.adapter.released_items(self.a, limit=3)
        self.assertEqual([i.kind for i in r.items], [Kind.COMIC] * 3 + [Kind.EBOOK])
        self.assertEqual((r.items[-1].title, r.items[-1].released), ("Synthetic Old Novel", "2001-05-01"))

    def test_enough_novels_on_the_newest_page_cost_no_second_request(self):
        self.fake.latest["content"].append(self.novel(1, "Synthetic Old Novel", "2001-05-01", 3))
        self.adapter.released_items(self.a, limit=1)
        self.assertEqual([q["sort"] for _m, _p, q in self.fake.requests], ["metadata.releaseDate,desc"])

    def test_when_the_newest_page_holds_too_few_novels_the_newest_additions_fill_the_rest(self):
        self.fake.latest["content"] += [self.novel(2, "Synthetic Added Novel", "1999-01-02", 0),
                                        self.novel(3, "Synthetic Undated Novel", None, 0)]
        handle = self.fake.handle

        def newest_page_of_issues_only(method, path, query):     # more issues than a page, all newer than any novel
            status, body, ctype = handle(method, path, query)
            if (query or {}).get("sort") == "metadata.releaseDate,desc":
                page = json.loads(body)
                page["content"] = [b for b in page["content"] if not b["id"].startswith("BOOKNOVEL")]
                body = json.dumps(page).encode("utf-8")
            return status, body, ctype
        self.fake.handle = newest_page_of_issues_only
        r = self.adapter.released_items(self.a)
        self.assertEqual([q["sort"] for _m, _p, q in self.fake.requests],
                         ["metadata.releaseDate,desc", "created,desc"])
        self.assertEqual([i.title for i in r.items if i.kind is Kind.EBOOK], ["Synthetic Added Novel"])
        self.assertEqual(r.items[-1].released, "1999-01-02")     # no release day (the undated novel): nothing to sort on
        self.assertEqual(len(r.items), 6)

    def test_novels_are_never_listed_twice_and_issues_are_unchanged(self):
        self.fake.latest["content"].append(self.novel(4, "Synthetic Dated Novel", "2020-02-02", 5))
        r = self.adapter.released_items(self.a)
        ids = [i.id for i in r.items]
        self.assertEqual(len(ids), len(set(ids)))
        issues = [i.title for i in r.items if i.kind is Kind.COMIC]
        self.assertEqual(issues, [i.title for i in self.adapter.shelves_items(self.a).items if i.kind is Kind.COMIC])

    def test_the_shelf_needs_the_group_too(self):
        outsider = make_principal("member-a", ("avrana-users",))
        self.assertIs(self.adapter.shelves_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertEqual(self.fake.requests, [])


class NoGroup(Base):
    def test_the_group_gates_before_any_upstream_call_or_cache_read(self):
        outsider = make_principal("member-b", ("avrana-users", "avrana-videos"))
        for r in (self.adapter.recent_items(outsider), self.adapter.continue_items(outsider),
                  self.adapter.item(outsider, "BOOKBBBB0003")):
            self.assertEqual((r.state, r.items), (SectionState.NOT_PERMITTED, ()))
            self.assertNotIn("Manga", repr(r.to_dict()))
        self.assertIs(self.adapter.fetch_artwork(outsider, "komga/book/BOOKBBBB0003").state,
                      SectionState.NOT_PERMITTED)
        self.assertIsNone(self.adapter.resolve_user(outsider))
        self.assertEqual(self.fake.requests, [])
        self.adapter.recent_items(self.b)                      # a warm cache for the same name is not served either
        n = len(self.fake.requests)
        self.assertIs(self.adapter.recent_items(outsider).state, SectionState.NOT_PERMITTED)
        self.assertEqual(len(self.fake.requests), n)


class Artwork(Base):
    def test_a_member_gets_the_cover_of_any_book_the_shared_account_can_see(self):
        for who in (self.a, self.b):
            r = self.adapter.fetch_artwork(who, "komga/book/BOOKCCCC0004")
            self.assertEqual((r.state, r.content_type, r.data), (SectionState.OK, "image/png", PNG))

    def test_hostile_or_unknown_refs_are_empty_and_never_interpolated(self):
        for ref in ("komga/book/latest", "komga/book/../users", "komga/book/BOOK", "jellyfin/primary/x",
                    "komga/book/BOOKAAAA0001/thumbnail", "komga/book/BOOKAAAA0001?x=1",
                    "komga/series/SERIESAAA001"):
            self.assertEqual(self.adapter.fetch_artwork(self.a, ref).state, SectionState.EMPTY, ref)
        self.assertEqual(self.fake.requests, [])

    def test_reserved_sub_routes_are_never_requested_as_book_ids(self):
        """Komga sub-routes that look like ids (review of #37 named ondeck) never reach upstream."""
        for word in ("latest", "updated", "ondeck"):
            self.assertNotEqual(self.adapter.item(self.b, word).state, SectionState.OK, word)
            self.assertEqual(self.adapter.fetch_artwork(self.b, f"komga/book/{word}").state, SectionState.EMPTY, word)
        self.assertEqual(self.fake.requests, [])

    def test_missing_thumbnails_and_bad_images_are_graceful(self):
        self.fake.overrides["/api/v1/books/BOOKAAAA0001/thumbnail"] = ("status", 404)
        self.assertEqual(self.adapter.fetch_artwork(self.b, "komga/book/BOOKAAAA0001").state, SectionState.EMPTY)
        self.assertEqual("unknown", self.adapter.health().state)   # artwork is neutral for the circuit
        for image in ((200, b"<html>", "text/html"), (200, b"not a png", "image/png"),
                      (200, PNG + b"x" * (MAX_IMAGE_BYTES + 1), "image/png")):
            self.reset()
            self.fake.image = image
            self.assertEqual(self.adapter.fetch_artwork(self.b, "komga/book/BOOKAAAA0001").state,
                             SectionState.UNAVAILABLE, image[2])


class Failures(Base):
    def test_unreachable_costs_the_section_only_and_never_raises(self):
        for exc in (ConnectionRefusedError("refused"), OSError("unreachable"), TimeoutError()):
            self.reset()
            self.fake.overrides["/api/v1/books"] = ("raise", exc)
            r = self.adapter.recent_items(self.a)
            self.assertEqual((r.state, r.items), (SectionState.UNAVAILABLE, ()), exc)

    def test_a_timeout_costs_the_section_only_and_a_warm_cache_still_serves(self):
        self.adapter.recent_items(self.a)
        self.fake.slow["/api/v1/books"] = 5.0
        self.assertEqual(self.adapter.recent_items(self.a).state, SectionState.OK)       # cache hit
        self.assertEqual(self.adapter.recent_items(self.b).reason, "UpstreamTimeout")

    def test_401_403_and_404_on_the_latest_route_are_unavailable(self):
        for code in (401, 403, 404):
            self.reset()
            self.fake.overrides["/api/v1/books"] = ("status", code)
            self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE, code)

    def test_malformed_bodies_are_unavailable_not_exceptions(self):
        for body in (b"[" * 100000, b'{"id": 5}', b"not json", b"\xff\xfe", b"null", b"{}", b'"x"'):
            self.reset()
            self.fake.overrides["/api/v1/books"] = ("body", body)
            self.assertIs(self.adapter.recent_items(self.b).state, SectionState.UNAVAILABLE, body[:12])
        self.reset()                                           # every book unusable: drift, never "nothing new"
        page = self.fake.copy_of(self.fake.latest)
        page["content"] = [{"id": 5}, "x", None]
        self.fake.serve("/api/v1/books", page)
        self.assertIs(self.adapter.recent_items(self.b).state, SectionState.UNAVAILABLE)

    def test_an_oversized_body_is_unavailable_and_counted(self):
        self.fake.overrides["/api/v1/books"] = ("body", b" " * (MAX_JSON_BYTES + 1))
        r = self.adapter.recent_items(self.b)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamTooLarge"))
        self.assertEqual(self.adapter.health().state, "failing")

    def test_a_breaker_trip_stops_all_traffic_for_every_member_until_the_cool_off(self):
        self.fake.overrides["/api/v1/books"] = ("raise", ConnectionRefusedError())
        for name in ("m1", "m2", "m3"):
            self.adapter.recent_items(make_principal(name, GROUPS))
        self.assertEqual(self.adapter.health().state, "cooling_off")
        n = len(self.fake.requests)
        self.assertEqual(self.adapter.recent_items(make_principal("m4", GROUPS)).reason, "cooling_off")
        self.assertEqual(len(self.fake.requests), n)
        self.fake.overrides.clear()
        self.clock.advance(61)
        self.assertIs(self.adapter.recent_items(make_principal("m4", GROUPS)).state, SectionState.OK)

    def test_a_404_on_the_latest_route_is_route_drift_and_opens_the_circuit_after_three(self):
        self.fake.overrides["/api/v1/books"] = ("status", 404)
        reasons = [self.adapter.recent_items(make_principal(n, GROUPS)).reason for n in ("m1", "m2", "m3")]
        self.assertEqual(reasons, ["RouteMissing"] * 3)
        self.assertEqual(self.adapter.health().state, "cooling_off")


class GuardAndSecrets(Base):
    def test_only_get_on_listed_routes_and_no_query_keys_beyond_the_list(self):
        g = GuardedTransport(self.transport).bind(SHARED_VIEWER)
        for method, path, query in (("POST", "/api/v1/books", None), ("GET", "/api/v2/users", None),
                                    ("GET", "/api/v2/users/me", None), ("GET", "/api/v1/users/me", None),
                                    ("DELETE", "/api/v1/books/BOOKAAAA0001", None),
                                    ("GET", "/api/v1/books/ondeck", None),
                                    ("POST", "/api/v1/series/SERIESAAA001", None),
                                    ("GET", "/api/v1/series/SERIESAAA001/books", None),
                                    ("GET", "/api/v1/readlists", None), ("GET", "/api/v1/collections", None),
                                    ("GET", "/api/v1/books/BOOKAAAA0001/read-progress", None),
                                    ("GET", "/api/v1/books/BOOKAAAA0001/pages/1", None),
                                    ("GET", "/api/v1/books/BOOKAAAA0001/file", None),
                                    ("GET", "/api/v1/books/%2e%2e", None),
                                    ("GET", "/api/v1/books", {"unpaged": "true"}),
                                    ("GET", "/api/v1/books/BOOKAAAA0001", {"anything": "1"})):
            with self.assertRaises(ForbiddenRequest, msg=(method, path)):
                g.request(method, path, query, 1.0, 1000)
        self.assertEqual(self.fake.requests, [])

    def test_routes_need_the_shared_binding_and_reject_any_other_user_id(self):
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind(None).request("GET", "/api/v1/books", None, 1.0, 1000)
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind("../x")
        with self.assertRaises(ForbiddenRequest):
            GuardedTransport(self.transport).bind("USERAAAAAAAA1")      # a real-looking Komga user id is refused
        self.assertEqual([r.name for r in ALLOWED_ROUTES], ["books", "book", "thumbnail", "series"])
        for word in ("latest", "updated"):
            self.assertEqual(self.adapter.item(self.a, word).items, ())
            self.assertEqual(self.adapter.fetch_artwork(self.a, f"komga/book/{word}").state, SectionState.EMPTY)
        self.assertEqual([p for p in self.fake.paths() if "latest" in p or "updated" in p], [])

    def test_the_credential_is_never_in_a_repr_a_result_a_health_report_or_a_log_line(self):
        opener = FakeOpener(self.fake)
        transport = UrllibTransport("https://komga.invalid", {"X-API-Key": TOKEN}, opener=opener)
        ad = KomgaAdapter(transport, clock=self.clock, owner_confirms_no_member_restrictions=True)
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            logging.getLogger("avrana_home").warning("probe")
            ok = ad.recent_items(self.b)
            self.fake.overrides["/api/v1/books"] = ("status", 401)
            ad.cache.clear()
            bad = ad.recent_items(self.b)
        blob = " ".join([repr(ad), repr(ok), repr(bad), repr(ad.health()), repr(ad._guard),
                         json.dumps(ok.to_dict()), *logs.output])
        self.assertNotIn(TOKEN, blob)
        self.assertTrue(opener.seen_headers)                   # requests went out through the transport

    def test_logs_carry_no_username_title_or_id(self):
        self.fake.overrides["/api/v1/books"] = ("status", 500)
        with self.assertLogs("avrana_home", level=logging.WARNING) as logs:
            self.adapter.recent_items(self.b)
        text = " ".join(logs.output)
        for secret in ("member-b", "Synthetic", "BOOK", "SERIES"):
            self.assertNotIn(secret, text)

    def test_fixtures_declare_their_target_version_and_which_shapes_are_synthetic(self):
        files = sorted(FIXTURES.glob("*.json"))
        self.assertEqual([f.name for f in files], ["books.json", "books_latest.json"])
        for f in files:
            doc = json.loads(f.read_text(encoding="utf-8"))
            self.assertIn("Komga", doc["_target_version"], f.name)
            self.assertIn("NOT confirmed", doc["_target_version"], f.name)
            self.assertIn("SYNTHETIC assumption", doc["_provenance"], f.name)
            self.assertIn("UNPROVEN", doc["_provenance"], f.name)


if __name__ == "__main__":
    unittest.main()
