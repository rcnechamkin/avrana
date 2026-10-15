"""Raw-header principal constructor, and tests that kill previously surviving mutations."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import threading
import unittest
import urllib.error

from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.contract import SectionState, Service
from avrana_home.principal import (PrincipalError, principal_from_headers,
                                   principal_from_raw_headers)
from avrana_home.resilience import (FakeClock, UpstreamAuthError, UpstreamHTTPError,
                                    UpstreamMalformed, UpstreamNotFound, UpstreamTimeout,
                                    UpstreamUnreachable, UrllibTransport)
from tests.fake_jellyfin import FakeJellyfin, FakeOpener, FakeTransport
from tests.helpers import FakeAdapter, make_principal

GROUPS = ("avrana-users", "avrana-videos")
U, G = b"X-Authentik-Username", b"x-authentik-groups"


class RawHeaderTests(unittest.TestCase):
    def reason(self, pairs):
        with self.assertRaises(PrincipalError) as cm:
            principal_from_raw_headers(pairs)
        return cm.exception.reason

    def test_happy_path_and_case_insensitive_names(self):
        p = principal_from_raw_headers([(U, b"member-a"), (G, b"avrana-users|avrana-videos"),
                                        (b"Host", b"x"), (b"X-authentik-email", b"m@example.invalid")])
        self.assertEqual((p.username, p.email), ("member-a", "m@example.invalid"))
        self.assertTrue(p.has_group("avrana-videos"))

    def test_duplicates_stay_visible(self):
        self.assertEqual(self.reason([(U, b"member-a"), (U, b"member-b"), (G, b"g")]), "duplicate_header")
        self.assertEqual(self.reason([(U, b"member-a"), (b"x-authentik-USERNAME", b"member-a"), (G, b"g")]),
                         "duplicate_header")

    def test_non_ascii_and_non_utf8_identity_values_yield_no_principal(self):
        cases = {
            "utf-8 e-acute": b"member-\xc3\xa9",
            "latin-1 e-acute (invalid utf-8)": b"member-\xe9",
            "mojibake already re-encoded": "member-Ã©".encode("utf-8"),
            "nbsp as latin-1": b"member\xa0a",
            "nul": b"member\x00a",
        }
        for label, value in cases.items():
            self.assertEqual(self.reason([(U, value), (G, b"g")]), "malformed_header", label)
            self.assertEqual(self.reason([(U, b"member-a"), (G, value)]), "malformed_header", label)

    def test_bad_inputs(self):
        for bad in (None, "x", [("a", "b")], [(b"a",)], [(b"a", b"b", b"c")], [(5, b"x")],
                    [(b"\xff", b"x")], [(U, 5)], iter([(U, b"a")])):
            with self.assertRaises(PrincipalError):
                principal_from_raw_headers(bad)

    def test_optional_headers_that_are_not_utf8_are_dropped_not_fatal(self):
        p = principal_from_raw_headers([(U, b"member-a"), (G, b"g"), (b"x-authentik-name", b"\xff\xfe")])
        self.assertIsNone(p.name)

    def test_existing_constructor_still_works(self):
        self.assertEqual(principal_from_headers({"X-authentik-username": "member-a",
                                                 "X-authentik-groups": "g"}).username, "member-a")

    def test_pair_with_a_non_str_name_is_no_principal(self):
        for bad in ([(5, "x"), ("X-authentik-username", "a"), ("X-authentik-groups", "g")],
                    {5: "x", "X-authentik-username": "a", "X-authentik-groups": "g"},
                    [(b"X-authentik-username", "a"), ("X-authentik-groups", "g")]):
            with self.assertRaises(PrincipalError):
                principal_from_headers(bad)


class KillMutations(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)

    def resume_limits(self):
        return [q["limit"] for _, p, q in self.fake.requests if p == "/UserItems/Resume"]

    def test_limit_is_clamped_to_fifty_and_junk_falls_back_to_twelve(self):
        self.adapter.continue_items(self.a, 500)
        self.assertEqual(self.resume_limits(), ["50"])
        for junk in (0, -3, True, "5", None, 1.5):
            self.setUp()
            self.adapter.continue_items(self.a, junk)
            self.assertEqual(self.resume_limits(), ["12"], repr(junk))
        self.setUp()
        self.adapter.continue_items(self.a, 50)
        self.assertEqual(self.resume_limits(), ["50"])

    def test_cache_key_includes_the_limit(self):
        self.adapter.continue_items(self.a, 6)
        self.adapter.continue_items(self.a, 7)
        self.adapter.continue_items(self.a, 6)                       # cached
        self.assertEqual(self.resume_limits(), ["6", "7"])

    def test_duplicate_ids_in_one_response_are_deduplicated(self):
        item = {"Id": "aaaa0000000000000000000000000001", "Name": "Dup", "Type": "Movie",
                "UserData": {"PlaybackPositionTicks": 5}}
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps({"Items": [item, dict(item)]}).encode())
        self.assertEqual(len(self.adapter.continue_items(self.a).items), 1)

    def test_stale_artwork_and_negative_mapping_are_not_cached(self):
        for op, user, call in (("artwork", "member-a", lambda ad, p: ad.fetch_artwork(p, "r")),
                               ("resolve", "member-z", lambda ad, p: ad.continue_items(p))):
            ad = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, self.clock, mode="block")
            ad.block_ops = {op}
            if op == "artwork":
                ad.mode = "ok"                              # let the mapping through, block the fetch
                ad.continue_items(make_principal("member-a", GROUPS))
                ad.cache.clear()
                ad.mode = "block"
                ad.block_ops = {"artwork"}
            p = make_principal(user, GROUPS)
            t = threading.Thread(target=call, args=(ad, p))
            t.start()
            self.assertTrue(ad.started.acquire(timeout=2), op)
            ad.breaker.force_open("HardCap")                 # the circuit moves on while the call hangs
            ad.release.set()
            t.join(3)
            # only the mapping, cached while the circuit was still the one that admitted the call
            self.assertEqual(len(ad.cache), 1 if op == "artwork" else 0, op)

    def test_ambiguous_and_absent_mappings_are_cached_per_member(self):
        self.fake.users = self.fake.users + [dict(self.fake.users[0], Id="ffffffff-ffff-4fff-8fff-ffffffffffff")]
        self.adapter.continue_items(self.a)
        self.adapter.recent_items(self.a)
        self.assertEqual(self.fake.paths().count("/Users"), 1)


class TransportMappingTests(unittest.TestCase):
    def raiser(self, exc):
        opener = FakeOpener(FakeJellyfin())
        opener.open = lambda req, timeout=None: (_ for _ in ()).throw(exc)
        return UrllibTransport("https://jellyfin.invalid", {}, opener)

    def expect(self, exc, cls):
        with self.assertRaises(cls) as cm:
            self.raiser(exc).request("GET", "/Users", None, 2.0, 100)
        self.assertIs(type(cm.exception), cls)
        return cm.exception

    def test_mapping_table(self):
        self.expect(TimeoutError(), UpstreamTimeout)
        self.expect(urllib.error.URLError(TimeoutError()), UpstreamTimeout)
        self.expect(urllib.error.URLError("refused"), UpstreamUnreachable)
        self.expect(ConnectionResetError(), UpstreamUnreachable)
        self.expect(OSError("x"), UpstreamUnreachable)
        self.expect(ValueError("bad url"), UpstreamMalformed)
        self.expect(RecursionError(), UpstreamMalformed)
        self.assertEqual(self.expect(urllib.error.HTTPError("u", 500, "x", {}, None), UpstreamHTTPError).status, 500)
        self.expect(urllib.error.HTTPError("u", 404, "x", {}, None), UpstreamNotFound)
        self.expect(urllib.error.HTTPError("u", 401, "x", {}, None), UpstreamAuthError)

    def test_base_url_is_validated(self):
        for bad in ("", "jellyfin.invalid", "file:///x", "https://x/"):
            with self.assertRaises(ValueError):
                UrllibTransport(bad, {})


if __name__ == "__main__":
    unittest.main()
