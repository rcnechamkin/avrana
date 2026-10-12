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

    def test_shared_cache_is_a_separate_store(self):
        shared = SharedCache(self.clock)
        shared.set("public", "k", "v", 10)
        self.assertEqual(shared.get("public", "k"), "v")
        self.cache.for_member(make_principal("shared")).set("public", "k", "member", 10)
        self.assertEqual(shared.get("public", "k"), "v")


if __name__ == "__main__":
    unittest.main()
