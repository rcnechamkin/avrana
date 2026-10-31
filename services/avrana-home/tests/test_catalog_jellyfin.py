"""The catalogue with Jellyfin (handoff 04): complete bounded pages, the member's own scope, the group first, a failure
never an empty library. Offline, SYNTHETIC; shapes from the 10.11.11 source, UNVERIFIED live (docs/design/LIBRARY-CATALOG.md)."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import unittest

from avrana_home import aggregate
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.contract import CATALOG_MAX_SIZE, Kind, SectionState
from avrana_home.resilience import FakeClock
from tests.catalog_support import SIZES, UID_A, UID_B, Wire, member, walk


class Jellyfin(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.catalogs = {UID_A: [], UID_B: []}
        self.status = 200
        self.wire = Wire(self.handle)
        self.adapter = JellyfinAdapter(self.wire, clock=self.clock)
        self.alice, self.bob = member("alice"), member("bob")

    def film(self, n, kind="Movie", owner=UID_A):
        uid = f"{n:030x}{'aa' if owner == UID_A else 'bb'}"
        return {"Id": uid, "Name": f"Synthetic {kind} {n:05}", "Type": kind, "ImageTags": {"Primary": "tag"},
                "UserData": {"Played": False, "PlaybackPositionTicks": 0}}

    def handle(self, path, query):
        if path == "/Users":
            return 200, [{"Name": "alice", "Id": UID_A}, {"Name": "bob", "Id": UID_B}]
        if self.status != 200:
            return self.status, {}
        assert path == "/Items" and query["recursive"] == "true" and query["sortBy"] == "SortName"
        rows = [x for x in self.catalogs[query["userId"]] if x["Type"] == query["includeItemTypes"]]
        start, limit = int(query["startIndex"]), int(query["limit"])
        return 200, {"Items": rows[start:start + limit], "TotalRecordCount": len(rows)}

    def test_every_size_pages_without_gaps_or_repeats(self):
        for n in SIZES:
            self.catalogs[UID_A] = [self.film(i) for i in range(n)]
            ad = JellyfinAdapter(self.wire, clock=self.clock)
            size = 48 if n > 1000 else 24
            if n > 1000:
                first = ad.catalog(self.alice, "movies", 1, size)
                last = ad.catalog(self.alice, "movies", 25000 // size + 1, size)
                self.assertEqual((n, True, size), (first.total, first.has_next, len(first.items)))
                self.assertEqual((False, 25000 % size), (last.has_next, len(last.items)))
                continue
            seen, _ = walk(ad, self.alice, "movies")
            self.assertEqual([f"Synthetic Movie {i:05}" for i in range(n)], [i.title for i in seen], n)
            self.assertEqual(n, len({i.id for i in seen}))

    def test_a_film_older_than_any_recent_feed_is_on_a_later_page_and_one_call_a_page(self):
        self.catalogs[UID_A] = [self.film(i) for i in range(50)]
        self.adapter.resolve_user(self.alice)
        self.wire.calls.clear()
        out = self.adapter.catalog(self.alice, "movies", 3)
        self.assertEqual(["Synthetic Movie 00048", "Synthetic Movie 00049"], [i.title for i in out.items])
        self.assertEqual((50, False), (out.total, out.has_next))
        self.assertEqual(["/Items"], [p for p, _ in self.wire.calls])
        self.assertEqual(UID_A, self.wire.calls[0][1]["userId"])

    def test_movies_and_shows_are_apart_and_an_episode_is_never_a_show(self):
        self.catalogs[UID_A] = [self.film(1), self.film(2, "Series"), self.film(3, "Episode")]
        self.assertEqual([Kind.MOVIE], [i.kind for i in self.adapter.catalog(self.alice, "movies").items])
        self.assertEqual([Kind.SERIES], [i.kind for i in self.adapter.catalog(self.alice, "series").items])

    def test_two_members_see_only_their_own_cold_and_warm(self):
        self.catalogs = {UID_A: [self.film(1)], UID_B: [self.film(2, owner=UID_B)]}
        for _ in range(2):
            a, b = self.adapter.catalog(self.alice, "movies"), self.adapter.catalog(self.bob, "movies")
            self.assertEqual({"Synthetic Movie 00001"}, {i.title for i in a.items})
            self.assertEqual({"Synthetic Movie 00002"}, {i.title for i in b.items})

    def test_a_group_lost_with_a_warm_cache_answers_nothing(self):
        self.catalogs[UID_A] = [self.film(1)]
        self.assertEqual(SectionState.OK, self.adapter.catalog(self.alice, "movies").state)
        self.wire.calls.clear()
        out = self.adapter.catalog(member("alice", "avrana-comics"), "movies")
        self.assertEqual((SectionState.NOT_PERMITTED, ()), (out.state, out.items))
        self.assertEqual([], self.wire.calls)

    def test_failures_are_never_an_empty_library(self):
        for status in (401, 403, 429, 500):
            self.status = status
            out = JellyfinAdapter(self.wire, clock=self.clock).catalog(self.alice, "movies")
            self.assertEqual(SectionState.UNAVAILABLE, out.state, status)

    def test_a_listing_without_its_count_is_malformed_not_a_last_page(self):
        self.adapter = JellyfinAdapter(Wire(lambda p, q: (200, {"Items": []} if p == "/Items"
                                                          else [{"Name": "alice", "Id": UID_A}])), clock=self.clock)
        self.assertEqual(SectionState.UNAVAILABLE, self.adapter.catalog(self.alice, "movies").state)

    def test_a_bad_group_page_or_size_asks_nobody(self):
        for group, page, size in (("episodes", 1, 24), ("movies", 0, 24), ("movies", 10 ** 6, 24), ("movies", True, 24),
                                  ("movies", 1, CATALOG_MAX_SIZE + 1), ("movies", 1, 0), ("movies", "2", 24)):
            self.assertEqual(SectionState.EMPTY, self.adapter.catalog(self.alice, group, page, size).state)
        self.assertEqual([], self.wire.calls)

    def test_gather_keeps_a_healthy_library_when_another_is_down(self):
        self.catalogs[UID_A] = [self.film(1)]
        broken = JellyfinAdapter(Wire(lambda p, q: (500, {})), clock=self.clock)
        good, bad = aggregate.gather_catalog(self.alice, [self.adapter, broken],
                                             [(self.adapter, "movies", 1, 3), (broken, "movies", 1, 3)])
        self.assertEqual((SectionState.OK, SectionState.UNAVAILABLE), (good.state, bad.state))


if __name__ == "__main__":
    unittest.main()
