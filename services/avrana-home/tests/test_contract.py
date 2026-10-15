import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import unittest

from avrana_home.contract import (HANDOFF_BASE, HandoffError, SectionState, Service,
                                  build_handoff_url, valid_upstream_id)
from avrana_home.resilience import FakeClock
from tests.helpers import FakeAdapter, make_principal


class HandoffTests(unittest.TestCase):
    def test_valid_ids_build_urls_on_fixed_bases(self):
        samples = {Service.JELLYFIN: "0123456789abcdef0123456789abcdef",
                   Service.AUDIOBOOKSHELF: "li_abc123def4", Service.KOMGA: "AbC12345",
                   Service.CALIBRE_WEB: "42"}
        for svc, ident in samples.items():
            url = build_handoff_url(svc, ident)
            self.assertTrue(url.startswith(HANDOFF_BASE[svc] + "/"), url)
            self.assertTrue(url.startswith("https://"))

    def test_jellyfin_base_is_watch_hostname(self):
        url = build_handoff_url(Service.JELLYFIN, "0123456789abcdef0123456789abcdef")
        self.assertTrue(url.startswith("https://watch.avrana.net/"))

    def test_hostile_ids_rejected(self):
        hostile = ["", "../x", "//evil.example/x", "https://evil.example/", "a" * 33,
                   "0123456789abcdef0123456789abcdeg", "0123456789ABCDEF0123456789ABCDEF",
                   "0123456789abcdef0123456789abcdef\n", "0123456789abcdef0123456789abcde%",
                   "0123456789abcdef0123456789abcdef/../", "０" * 32, None, 5, b"x"]
        for bad in hostile:
            self.assertFalse(valid_upstream_id(Service.JELLYFIN, bad), repr(bad))
            with self.assertRaises(HandoffError):
                build_handoff_url(Service.JELLYFIN, bad)
        for bad in ("١٢", "1 ", "12345678901", "-1", "1.5"):
            self.assertFalse(valid_upstream_id(Service.CALIBRE_WEB, bad), repr(bad))
        for bad in ("li_x", "LI_abc123def4", "li_abc123/..", "http://x"):
            self.assertFalse(valid_upstream_id(Service.AUDIOBOOKSHELF, bad), repr(bad))


class ContractBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.adapter = FakeAdapter(Service.JELLYFIN, {"member-a": "1", "member-b": "2"}, self.clock)

    def test_not_permitted_means_zero_upstream_calls_and_no_cache_touch(self):
        p = make_principal("member-a", groups=("avrana-users",))
        for result in (self.adapter.continue_items(p), self.adapter.recent_items(p)):
            self.assertIs(result.state, SectionState.NOT_PERMITTED)
            self.assertEqual(result.items, ())
        self.assertIsNone(self.adapter.resolve_user(p))
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(len(self.adapter.cache), 0)

    def test_raw_string_identity_rejected(self):
        for call in (self.adapter.continue_items, self.adapter.recent_items,
                     self.adapter.resolve_user, self.adapter.fetch_artwork):
            with self.assertRaises(TypeError):
                call("member-a")
        self.assertEqual(self.adapter.calls, 0)

    def test_unmapped_is_not_linked_never_a_fallback(self):
        p = make_principal("member-z")
        r = self.adapter.continue_items(p)
        self.assertIs(r.state, SectionState.NOT_LINKED)
        self.assertEqual(r.items, ())
        self.assertIsNone(self.adapter.resolve_user(p))

    def test_ok_and_isolation_of_two_members(self):
        a = self.adapter.continue_items(make_principal("member-a"))
        b = self.adapter.continue_items(make_principal("member-b"))
        self.assertEqual(a.items[0].title, "Synthetic Title 1")
        self.assertEqual(b.items[0].title, "Synthetic Title 2")

    def test_search_is_defined_but_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.adapter.search(make_principal(), "synthetic")

    def test_section_dicts_are_json_serialisable_and_stable(self):
        d = self.adapter.continue_items(make_principal("member-a")).to_dict()
        json.dumps(d)
        self.assertEqual(sorted(d), ["items", "section", "service", "state"])
        self.assertEqual(d["state"], "ok")
        item = d["items"][0]
        self.assertEqual(sorted(item), ["artwork", "handoff_url", "id", "kind", "progress",
                                        "series", "service", "subtitle", "title"])
        self.assertEqual(sorted(item["artwork"]), ["alt", "ref"])

    def test_artwork_requires_group_and_mapping(self):
        self.assertIs(self.adapter.fetch_artwork(make_principal(groups=("x",)), "r").state,
                      SectionState.NOT_PERMITTED)
        self.assertEqual(self.adapter.calls, 0)
        self.assertIs(self.adapter.fetch_artwork(make_principal("member-z"), "r").state,
                      SectionState.NOT_LINKED)
        self.assertIs(self.adapter.fetch_artwork(make_principal("member-a"), "r").state,
                      SectionState.OK)

    def test_cached_artwork_is_refetched_once_artwork_ttl_passes(self):
        """ARTWORK_TTL bounds how long artwork for an item hidden from a member can be served from
        cache (review of #31: nothing pinned it)."""
        from avrana_home.contract import ARTWORK_TTL
        self.assertLessEqual(ARTWORK_TTL, 300.0)
        who = make_principal("member-a")
        self.adapter.fetch_artwork(who, "r")
        first = self.adapter.calls
        self.clock.advance(ARTWORK_TTL - 1)
        self.adapter.fetch_artwork(who, "r")
        self.assertEqual(self.adapter.calls, first, "artwork should be served from cache within the TTL")
        self.clock.advance(2)
        self.adapter.fetch_artwork(who, "r")
        self.assertGreater(self.adapter.calls, first, "artwork outlived ARTWORK_TTL in the cache")


if __name__ == "__main__":
    unittest.main()
