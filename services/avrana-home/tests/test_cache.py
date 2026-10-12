import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import unittest

from avrana_home.cache import MemberCache, SharedCache
from avrana_home.resilience import FakeClock
from tests.helpers import make_principal


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cache = MemberCache(self.clock)

    def test_members_never_share_entries(self):
        a, b = make_principal("member-a"), make_principal("member-b")
        self.cache.for_member(a).set("jellyfin", "continue", "A-DATA", ttl=30)
        self.assertEqual(self.cache.for_member(a).get("jellyfin", "continue"), "A-DATA")
        self.assertIsNone(self.cache.for_member(b).get("jellyfin", "continue"))

    def test_username_variants_are_different_members(self):
        self.cache.for_member(make_principal("member-a")).set("jellyfin", "continue", "A-DATA", 30)
        for variant in ("Member-A", "member-a​".replace("​", "x"), "member_a"):
            self.assertIsNone(self.cache.for_member(make_principal(variant)).get("jellyfin", "continue"))

    def test_raw_string_rejected(self):
        with self.assertRaises(TypeError):
            self.cache.for_member("member-a")

    def test_ttl_expiry_with_fake_clock(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "continue", "v", ttl=30)
        self.clock.advance(29.9)
        self.assertEqual(s.get("jellyfin", "continue"), "v")
        self.clock.advance(0.2)
        self.assertIsNone(s.get("jellyfin", "continue"))
        self.assertEqual(len(self.cache), 0)            # expired entry dropped on read

    def test_zero_ttl_not_stored(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", ttl=0)
        self.assertEqual(len(self.cache), 0)

    def test_bounded_size(self):
        small = MemberCache(self.clock, max_entries=3)
        s = small.for_member(make_principal("member-a"))
        for i in range(10):
            s.set("jellyfin", f"k{i}", i, ttl=10 + i)
        self.assertLessEqual(len(small), 3)

    def test_clear_is_only_a_speed_cost(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", 30)
        self.cache.clear()
        self.assertIsNone(s.get("jellyfin", "x"))

    def test_bounded_by_bytes(self):
        small = MemberCache(self.clock, max_bytes=1000, member_max_bytes=1000)
        s = small.for_member(make_principal("member-a"))
        for i in range(10):
            s.set("jellyfin", f"k{i}", i, ttl=100, size=300)
        self.assertLessEqual(small.total_bytes(), 1000)
        self.assertLessEqual(len(small), 3)
        s.set("jellyfin", "huge", "v", ttl=100, size=5000)         # larger than any quota: refused
        self.assertIsNone(s.get("jellyfin", "huge"))

    def test_one_member_cannot_evict_everyone_else(self):
        cache = MemberCache(self.clock, max_entries=40, member_max_entries=10)
        a, b = cache.for_member(make_principal("member-a")), cache.for_member(make_principal("member-b"))
        for i in range(5):
            b.set("jellyfin", f"k{i}", i, ttl=100)
        for i in range(500):
            a.set("jellyfin", f"flood{i}", i, ttl=100)
        self.assertEqual([b.get("jellyfin", f"k{i}") for i in range(5)], [0, 1, 2, 3, 4])
        mine = sum(1 for i in range(500) if a.get("jellyfin", f"flood{i}") is not None)
        self.assertLessEqual(mine, 10)

    def test_global_pressure_evicts_the_heaviest_member_first(self):
        cache = MemberCache(self.clock, max_entries=12, member_max_entries=10)
        a, b = cache.for_member(make_principal("member-a")), cache.for_member(make_principal("member-b"))
        for i in range(3):
            b.set("jellyfin", f"k{i}", i, ttl=100)
        for i in range(10):
            a.set("jellyfin", f"f{i}", i, ttl=100)
        c = cache.for_member(make_principal("member-c"))
        for i in range(3):
            c.set("jellyfin", f"k{i}", i, ttl=100)
        self.assertEqual([b.get("jellyfin", f"k{i}") for i in range(3)], [0, 1, 2])
        self.assertEqual([c.get("jellyfin", f"k{i}") for i in range(3)], [0, 1, 2])
        self.assertLessEqual(len(cache), 12)

    def test_delete_is_member_scoped(self):
        a, b = (self.cache.for_member(make_principal(n)) for n in ("member-a", "member-b"))
        a.set("jellyfin", "mapping", 1, 60)
        b.set("jellyfin", "mapping", 2, 60)
        a.delete("jellyfin", "mapping")
        self.assertIsNone(a.get("jellyfin", "mapping"))
        self.assertEqual(b.get("jellyfin", "mapping"), 2)

    def test_artwork_ttl_and_visibility_window(self):
        from avrana_home.contract import ARTWORK_TTL, MediaAdapter
        self.assertEqual(ARTWORK_TTL, 300.0)       # the longest an item hidden from a member can linger
        self.assertGreater(ARTWORK_TTL, MediaAdapter.cache_ttl(None, "item"))

    def test_shared_cache_is_a_separate_store(self):
        shared = SharedCache(self.clock)
        shared.set("public", "k", "v", 10)
        self.assertEqual(shared.get("public", "k"), "v")
        self.cache.for_member(make_principal("shared")).set("public", "k", "member", 10)
        self.assertEqual(shared.get("public", "k"), "v")


if __name__ == "__main__":
    unittest.main()
