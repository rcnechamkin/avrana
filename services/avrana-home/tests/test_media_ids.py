"""Media identity (R2-B, AVR-747): validation, work vs edition keys, ambiguity, and what the adapters carry.
Offline; synthetic fixtures only."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
from dataclasses import dataclass
import json
import unittest

from avrana_home import media_ids
from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.contract import Kind, Service
from avrana_home.resilience import FakeClock
from tests.fake_abs import FakeAudiobookshelf
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.fake_komga import FakeKomga
from tests.helpers import make_principal

ALL = ("avrana-users", "avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")


@dataclass(frozen=True)
class Item:
    id: str
    service: Service
    kind: Kind
    external_ids: tuple


class IsbnTests(unittest.TestCase):
    def test_valid_isbn10_becomes_its_isbn13(self):
        self.assertEqual(media_ids.isbn13("0-00-000000-0"), "9780000000002")
        self.assertEqual(media_ids.isbn13("0 306 40615 2"), "9780306406157")
        self.assertEqual(media_ids.isbn13("080442957X"), "9780804429573")
        self.assertEqual(media_ids.isbn13("080442957x"), "9780804429573")

    def test_valid_isbn13_is_kept(self):
        self.assertEqual(media_ids.isbn13("978-0-306-40615-7"), "9780306406157")
        self.assertEqual(media_ids.isbn13("9790000000001"), "9790000000001")

    def test_anything_else_is_refused(self):
        for bad in ("9780306406158", "0306406153", "978030640615", "1234567890123", "", "X306406152",
                    "97803064061577", "978-0-306-40615-7" + " " * 40, None, 9780306406157, ["9780306406157"],
                    "９７８０３０６４０６１５７", "978–0306406157"):
            self.assertIsNone(media_ids.isbn13(bad), repr(bad))


class ExternalIdTests(unittest.TestCase):
    def test_patterns(self):
        ok = media_ids.external_ids([("tmdb", "603"), ("imdb", "tt0133093"), ("tvdb", " 81189 "),
                                     ("asin", "B0SYNTH001")])
        self.assertEqual(ok, (("asin", "B0SYNTH001"), ("imdb", "tt0133093"), ("tmdb", "603"), ("tvdb", "81189")))

    def test_hostile_or_malformed_values_are_dropped(self):
        for scheme, value in (("tmdb", "0603"), ("tmdb", "-1"), ("tmdb", "60 3"), ("tmdb", "１２３"),
                              ("tmdb", "12345678901"), ("imdb", "tt12"), ("imdb", "TT0133093"),
                              ("imdb", "tt0133093/../"), ("imdb", "nm0000206"), ("tvdb", "81189?x=1"),
                              ("asin", "b0synth001"), ("asin", "B0SYNTH00"), ("asin", "B0SYNTH0012"),
                              ("tmdb", 603), ("tmdb", True), ("tmdb", None), ("imdb", "tt013\n3093"),
                              ("unknown", "1"), ("tmdb", "1" * 40)):
            got = media_ids.external_ids([(scheme, value)])
            self.assertNotIn(scheme, dict(got), (scheme, value))

    def test_a_contradicting_scheme_is_dropped_entirely(self):
        self.assertEqual(media_ids.external_ids([("tmdb", "1"), ("tmdb", "2"), ("imdb", "tt0000001")]),
                         (("imdb", "tt0000001"),))
        self.assertEqual(media_ids.external_ids([("tmdb", "1"), ("tmdb", "1")]), (("tmdb", "1"),))

    def test_an_isbn10_given_as_asin_is_an_isbn(self):
        self.assertEqual(media_ids.external_ids([("asin", "0306406152")]), (("isbn13", "9780306406157"),))
        # ... and it must then agree with an explicit ISBN, or neither is trusted
        self.assertEqual(media_ids.external_ids([("asin", "0306406152"), ("isbn13", "9780000000002")]), ())

    def test_from_jellyfin_reads_only_known_keys(self):
        got = media_ids.from_jellyfin({"Tmdb": "1", "imdb": "tt0000001", "Tvdb": "", "AniDB": "5",
                                       "Zap2It": "x", 7: "tt1"})
        self.assertEqual(got, (("imdb", "tt0000001"), ("tmdb", "1")))
        for hostile in (None, [], "Tmdb=1", 5, {"Tmdb": {"nested": "1"}}):
            self.assertEqual(media_ids.from_jellyfin(hostile), (), repr(hostile))

    def test_from_book_metadata(self):
        self.assertEqual(media_ids.from_book_metadata({"isbn": "0-00-000000-0", "asin": "B0SYNTH001"}),
                         (("asin", "B0SYNTH001"), ("isbn13", "9780000000002")))
        self.assertEqual(media_ids.from_book_metadata({"isbn": None, "asin": ""}), ())
        self.assertEqual(media_ids.from_book_metadata("isbn"), ())


class LinkTests(unittest.TestCase):
    def test_keys_carry_the_kind_for_work_schemes_only(self):
        self.assertEqual(media_ids.identity_keys("movie", (("tmdb", "1"), ("isbn13", "9780000000002"))),
                         ("isbn13:9780000000002", "movie:tmdb:1"))

    def test_a_movie_and_a_series_with_the_same_tmdb_number_are_not_linked(self):
        linked = media_ids.link([Item("jellyfin:a", Service.JELLYFIN, Kind.MOVIE, (("tmdb", "1"),)),
                                 Item("jellyfin:b", Service.JELLYFIN, Kind.SERIES, (("tmdb", "1"),))])
        self.assertEqual(linked.groups, ())
        self.assertEqual(linked.ambiguous, ())

    def test_the_same_edition_in_two_services_is_linked(self):
        linked = media_ids.link([Item("komga:B1", Service.KOMGA, Kind.COMIC, (("isbn13", "9780000000019"),)),
                                 Item("calibre-web:7", Service.CALIBRE_WEB, Kind.EBOOK,
                                      (("isbn13", "9780000000019"),))])
        self.assertEqual(linked.groups, (("calibre-web:7", "komga:B1"),))

    def test_an_ebook_and_its_audiobook_with_different_isbns_are_not_linked(self):
        linked = media_ids.link([
            Item("audiobookshelf:x", Service.AUDIOBOOKSHELF, Kind.AUDIOBOOK, (("isbn13", "9780000000002"),)),
            Item("komga:y", Service.KOMGA, Kind.EBOOK, (("isbn13", "9780000000019"),))])
        self.assertEqual(linked.groups, ())

    def test_a_key_two_items_of_one_service_share_is_ambiguous_and_links_nothing(self):
        items = [Item("komga:A1", Service.KOMGA, Kind.COMIC, (("isbn13", "9780000000019"),)),
                 Item("komga:A2", Service.KOMGA, Kind.COMIC, (("isbn13", "9780000000019"),)),
                 Item("calibre-web:1", Service.CALIBRE_WEB, Kind.EBOOK, (("isbn13", "9780000000019"),))]
        linked = media_ids.link(items)
        self.assertEqual(linked.groups, ())
        self.assertEqual(linked.ambiguous, ("isbn13:9780000000019",))

    def test_the_same_item_seen_twice_is_not_ambiguous(self):
        a = Item("komga:A1", Service.KOMGA, Kind.COMIC, (("isbn13", "9780000000019"),))
        b = Item("calibre-web:1", Service.CALIBRE_WEB, Kind.EBOOK, (("isbn13", "9780000000019"),))
        self.assertEqual(media_ids.link([a, a, b]).groups, (("calibre-web:1", "komga:A1"),))

    def test_no_ids_no_links(self):
        self.assertEqual(media_ids.link([Item("komga:A1", Service.KOMGA, Kind.COMIC, ())]).groups, ())
        self.assertEqual(media_ids.link([]).groups, ())


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.member = make_principal("member-a", ALL)

    def test_jellyfin_asks_for_provider_ids_and_keeps_only_valid_ones(self):
        fake = FakeJellyfin(FakeClock())
        adapter = JellyfinAdapter(FakeTransport(fake), clock=FakeClock())
        recent = {i.title: i for i in adapter.recent_items(self.member).items}
        self.assertEqual(recent["Synthetic Film Three"].external_ids,
                         (("imdb", "tt9000001"), ("tmdb", "900001")))
        self.assertEqual(recent["Synthetic Series Alpha"].external_ids, (("tmdb", "900001"),))
        for _method, path, query in fake.requests:
            if "fields" in query:
                self.assertIn("ProviderIds", query["fields"].split(","), path)
        # the movie and the series share a TMDB number but are different works
        self.assertEqual(media_ids.link(recent.values()).groups, ())

    def test_audiobookshelf_and_komga_carry_book_identifiers(self):
        abs_adapter = AudiobookshelfAdapter(FakeTransport(FakeAudiobookshelf(FakeClock())), clock=FakeClock())
        book = abs_adapter.item(self.member, "li_book000001", fresh=True).items
        self.assertEqual(book[0].external_ids, (("asin", "B0SYNTH001"), ("isbn13", "9780000000002")))
        komga = KomgaAdapter(FakeTransport(FakeKomga(FakeClock())), clock=FakeClock(),
                             owner_confirms_no_member_restrictions=True)
        comic = komga.item(self.member, "BOOKAAAA0001", fresh=True).items
        self.assertEqual(comic[0].external_ids, (("isbn13", "9780000000019"),))

    def test_identifiers_are_never_in_the_public_json(self):
        fake = FakeJellyfin(FakeClock())
        adapter = JellyfinAdapter(FakeTransport(fake), clock=FakeClock())
        result = adapter.recent_items(self.member)
        text = json.dumps(result.to_dict())
        for marker in ("900001", "tt9000001", "external_ids"):
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
