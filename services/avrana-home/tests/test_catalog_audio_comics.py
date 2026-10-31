"""The catalogue with Audiobookshelf and Komga (handoff 04, 05). Offline, SYNTHETIC; shapes from the 2.36.0 and 1.25.0
sources, UNVERIFIED live. Komga is read only with the member's own key, never the shared account."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import os
import tempfile
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.adapters.komga import KomgaAdapter
from avrana_home.contract import Kind, SectionState
from avrana_home.member_keys import MemberKeyStore, read_keys, write_keys
from avrana_home.resilience import FakeClock
from tests.catalog_support import ABS_A, ABS_B, KEY_A, KEY_B, LIB_1, LIB_2, SIZES, Wire, member, walk


def abs_record(uid, name, libraries=None, tags=None, explicit=True):
    return {"id": uid, "username": name, "isActive": True, "mediaProgress": [],
            "librariesAccessible": libraries or [], "itemTagsSelected": list(tags[1]) if tags else [],
            "permissions": {"accessAllLibraries": libraries is None, "accessAllTags": tags is None,
                            "accessExplicitContent": explicit, "selectedTagsNotAccessible": bool(tags and tags[0])}}


class Audiobookshelf(unittest.TestCase):
    def setUp(self):
        self.lists = {LIB_1: [], LIB_2: []}
        self.records = {ABS_A: abs_record(ABS_A, "alice"), ABS_B: abs_record(ABS_B, "bob", libraries=[LIB_2])}
        self.wire = Wire(self.handle)
        self.adapter = AudiobookshelfAdapter(self.wire, clock=FakeClock())
        self.alice, self.bob = member("alice"), member("bob")

    def book(self, library, n, tags=(), explicit=False):
        uid = f"00000000-0000-4000-8000-{n:012x}"
        return {"id": uid, "libraryId": library, "mediaType": "book", "isMissing": False, "isInvalid": False,
                "addedAt": 1, "media": {"tags": list(tags), "duration": 60.0, "metadata": {
                    "title": f"Synthetic Book {n:05}", "authorName": "Synthetic Author", "explicit": explicit}}}

    def handle(self, path, query):
        if path == "/api/users":
            return 200, {"users": [{"id": r["id"], "username": r["username"], "isActive": True}
                                   for r in self.records.values()]}
        if path.startswith("/api/users/"):
            return 200, self.records[path.rsplit("/", 1)[1]]
        if path == "/api/libraries":
            return 200, {"libraries": [{"id": lid, "mediaType": "book"} for lid in self.lists]}
        lid = path.split("/")[3]
        assert query["sort"] == "media.metadata.title"
        rows, limit, page = self.lists[lid], int(query["limit"]), int(query["page"])
        return 200, {"results": rows[page * limit:(page + 1) * limit], "total": len(rows), "limit": limit, "page": page}

    def test_every_size_pages_without_gaps_or_repeats(self):
        for n in SIZES[:-1]:
            self.lists = {LIB_1: [self.book(LIB_1, i) for i in range(n)]}
            seen, _ = walk(AudiobookshelfAdapter(self.wire, clock=FakeClock()), self.alice, "titles")
            self.assertEqual([f"Synthetic Book {i:05}" for i in range(n)], [i.title for i in seen], n)

    def test_libraries_follow_each_other_and_the_count_is_the_sum(self):
        self.lists = {LIB_1: [self.book(LIB_1, i) for i in range(30)], LIB_2: [self.book(LIB_2, 100 + i) for i in range(5)]}
        seen, pages = walk(self.adapter, self.alice, "titles")
        self.assertEqual(35, len({i.id for i in seen}))
        self.assertEqual(3, pages)
        self.assertEqual(35, self.adapter.catalog(self.alice, "titles", 1).total)

    def test_a_member_is_asked_only_their_own_library(self):
        self.lists = {LIB_1: [self.book(LIB_1, 1)], LIB_2: [self.book(LIB_2, 2)]}
        out = self.adapter.catalog(self.bob, "titles")
        self.assertEqual(["Synthetic Book 00002"], [i.title for i in out.items])
        self.assertEqual(1, out.total)
        self.assertFalse(any(LIB_1 in p for p, _ in self.wire.calls))

    def test_a_tag_or_explicit_rule_hides_the_item_and_the_count_but_keeps_the_walk(self):
        self.records[ABS_A] = abs_record(ABS_A, "alice", tags=(True, ("Hidden",)), explicit=False)
        self.lists = {LIB_1: [self.book(LIB_1, i, tags=("Hidden",)) for i in range(24)]
                      + [self.book(LIB_1, 50, explicit=True), self.book(LIB_1, 51)]}
        first = self.adapter.catalog(self.alice, "titles", 1)
        self.assertEqual((SectionState.OK, (), None, True), (first.state, first.items, first.total, first.has_next))
        second = self.adapter.catalog(self.alice, "titles", 2)
        self.assertEqual(["Synthetic Book 00051"], [i.title for i in second.items])
        self.assertIsNone(second.total)

    def test_a_listing_without_a_total_is_malformed(self):
        self.lists = {LIB_1: [self.book(LIB_1, 1)]}
        handle, self.wire.handle = self.wire.handle, None

        def no_total(path, query):
            status, body = handle(path, query)
            if isinstance(body, dict):
                body.pop("total", None)
            return status, body
        self.wire.handle = no_total
        self.assertEqual(SectionState.UNAVAILABLE, self.adapter.catalog(self.alice, "titles").state)


class Komga(unittest.TestCase):
    def setUp(self):
        self.series = {KEY_A: [self.one(i, "LIBCOMICS1") for i in range(50)], KEY_B: [self.one(900, "LIBCOMICS1")]}
        self.status, self.cover = 200, 200
        self.shared = Wire(lambda p, q: self.fail("the shared account was used"))
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        path = os.path.join(self.dir.name, "keys")
        write_keys(path, {"alice@example.org": KEY_A, "bob@example.org": KEY_B})
        self.store = MemberKeyStore(path, initial=read_keys(path))
        self.wires = {}
        self.adapter = self.build()
        self.alice, self.bob = member("alice"), member("bob")

    def build(self, books=frozenset()):
        return KomgaAdapter(self.shared, clock=FakeClock(), owner_confirms_no_member_restrictions=True,
                            member_keys=self.store, member_transport=self.transport, book_libraries=books)

    def transport(self, key):
        return self.wires.setdefault(key, Wire(lambda p, q: self.handle(key, p, q), "image/png"))

    @staticmethod
    def one(n, library):
        return {"id": f"SERIES{n:06}", "libraryId": library, "name": f"folder {n}", "booksCount": n % 3 + 1,
                "deleted": False, "metadata": {"title": f"Synthetic Series {n:05}"}}

    def handle(self, key, path, query):
        if path == "/api/v1/libraries":
            return 200, [{"id": "LIBCOMICS1"}, {"id": "LIBBOOKS01"}]
        if path.endswith("/thumbnail"):
            return self.cover, b"\x89PNG\r\n\x1a\n" + b"0" * 16
        if self.status != 200:
            return self.status, {}
        assert path == "/api/v1/series" and query["sort"] == "metadata.titleSort,asc" and query["deleted"] == "false"
        rows = self.series[key]
        if "library_id" in query:
            rows = [r for r in rows if r["libraryId"] in query["library_id"].split(",")]
        size, page = int(query["size"]), int(query["page"])
        return 200, {"content": rows[page * size:(page + 1) * size], "totalElements": len(rows), "size": size}

    def test_series_page_completely_with_the_members_own_key_and_never_the_shared_account(self):
        seen, pages = walk(self.adapter, self.alice, "series")
        self.assertEqual((50, 3), (len({i.id for i in seen}), pages))
        self.assertEqual(Kind.COMIC_SERIES, seen[0].kind)
        self.assertEqual("https://read.avrana.net/series/SERIES000000", seen[0].handoff_url)
        self.assertEqual("komga/series/SERIES000000", seen[0].artwork.ref)
        self.assertEqual("komga:series:SERIES000000", seen[0].id)        # never mistaken for a book's title page
        self.assertEqual(50, self.adapter.catalog(self.alice, "series").total)
        self.assertEqual([], self.shared.calls)
        self.assertNotIn(KEY_B, self.wires)

    def test_two_keys_two_catalogues_cold_and_warm(self):
        for _ in range(2):
            self.assertEqual(1, self.adapter.catalog(self.bob, "series").total)
            self.assertEqual(50, self.adapter.catalog(self.alice, "series").total)

    def test_without_a_key_the_member_is_not_linked_and_nothing_is_called(self):
        out = self.adapter.catalog(member("carol"), "series")
        self.assertEqual((SectionState.NOT_LINKED, "no_member_key"), (out.state, out.reason))
        self.assertEqual(SectionState.EMPTY, self.adapter.fetch_artwork(member("carol"), "komga/series/SERIES000001").state)
        self.assertEqual([], self.shared.calls)

    def test_the_group_comes_before_the_key_and_the_cache(self):
        self.adapter.catalog(self.alice, "series")
        self.wires[KEY_A].calls.clear()
        lost = member("alice", "avrana-videos")
        self.assertEqual(SectionState.NOT_PERMITTED, self.adapter.catalog(lost, "series").state)
        self.assertEqual(SectionState.NOT_PERMITTED, self.adapter.fetch_artwork(lost, "komga/series/SERIES000001").state)
        self.assertEqual([], self.wires[KEY_A].calls)

    def test_a_refused_key_is_that_member_alone_and_never_opens_the_shared_circuit(self):
        self.status = 401
        for _ in range(5):
            self.assertEqual(SectionState.NOT_LINKED, self.adapter.catalog(self.alice, "series").state)
        self.assertEqual("ok", self.adapter.health().state)

    def test_an_outage_is_unavailable(self):
        self.status = 500
        self.assertEqual(SectionState.UNAVAILABLE, self.adapter.catalog(self.alice, "series").state)

    def test_book_libraries_are_left_out_of_comics_and_the_count(self):
        self.series[KEY_A] = [self.one(1, "LIBCOMICS1"), self.one(2, "LIBBOOKS01")]
        out = self.build(frozenset({"LIBBOOKS01"})).catalog(self.alice, "series")
        self.assertEqual((1, ["Synthetic Series 00001"]), (out.total, [i.title for i in out.items]))
        self.assertEqual("LIBCOMICS1", self.wires[KEY_A].calls[-1][1]["library_id"])

    def test_a_series_from_a_library_not_asked_for_discards_the_page(self):
        ad = self.build(frozenset({"LIBBOOKS01"}))
        self.handle_real, self.series[KEY_A] = self.handle, [self.one(2, "LIBBOOKS01")]
        self.wires[KEY_A] = Wire(lambda p, q: ((200, {"content": self.series[KEY_A], "totalElements": 1})
                                               if p == "/api/v1/series" else self.handle_real(KEY_A, p, q)))
        self.assertEqual(SectionState.UNAVAILABLE, ad.catalog(self.alice, "series").state)

    def test_a_cover_is_read_with_the_key_and_a_hidden_one_is_nothing(self):
        ok = self.adapter.fetch_artwork(self.alice, "komga/series/SERIES000001")
        self.assertEqual(SectionState.OK, ok.state)
        self.cover = 404
        self.assertEqual(SectionState.EMPTY, self.adapter.fetch_artwork(self.bob, "komga/series/SERIES000002").state)
        self.cover = 403
        self.assertEqual(SectionState.EMPTY, self.adapter.fetch_artwork(self.bob, "komga/series/SERIES000003").state)
        self.assertEqual([], self.shared.calls)


if __name__ == "__main__":
    unittest.main()
