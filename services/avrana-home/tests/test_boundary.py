"""Upstream-controlled input must never make a public adapter method raise."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import http.client
import json
import unittest
import urllib.error

from avrana_home.adapters.jellyfin import JellyfinAdapter, normalise_guid
from avrana_home.contract import ArtworkResult, SectionResult, SectionState
from avrana_home.resilience import FakeClock, UpstreamUnreachable, UrllibTransport
from tests.fake_jellyfin import FakeJellyfin, FakeOpener, FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")
ITEM = "aaaa0000000000000000000000000001"


class Boundary(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.adapter = JellyfinAdapter(FakeTransport(self.fake), clock=self.clock)
        self.a = make_principal("member-a", GROUPS)

    def every_method(self):
        out = [self.adapter.continue_items(self.a), self.adapter.recent_items(self.a),
               self.adapter.item(self.a, ITEM),
               self.adapter.fetch_artwork(self.a, "jellyfin/primary/" + ITEM)]
        self.adapter.resolve_user(self.a)
        for r in out:
            self.assertIsInstance(r, (SectionResult, ArtworkResult))
        return out

    def test_deeply_nested_json_does_not_raise(self):
        deep = b"[" * 200000 + b"]" * 200000
        for path in ("/UserItems/Resume", "/Items/Latest", "/Items", "/Users"):
            self.setUp()
            self.fake.overrides[path] = ("body", deep)
            for r in self.every_method():
                self.assertIn(r.state, (SectionState.UNAVAILABLE, SectionState.OK,
                                        SectionState.EMPTY, SectionState.NOT_LINKED), path)

    def test_deeply_nested_resume_is_unavailable(self):
        self.fake.overrides["/UserItems/Resume"] = ("body", b"[" * 200000 + b"]" * 200000)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMalformed"))

    def test_hostile_numbers_do_not_raise(self):
        huge = 10 ** 400
        body = {"Items": [
            {"Id": ITEM, "Name": "Big", "Type": "Movie", "RunTimeTicks": huge,
             "UserData": {"PlaybackPositionTicks": huge}},
            {"Id": "aaaa0000000000000000000000000002", "Name": "Ratio", "Type": "Movie",
             "RunTimeTicks": 1, "UserData": {"PlaybackPositionTicks": huge}},
            {"Id": "aaaa0000000000000000000000000003", "Name": "Neg", "Type": "Movie",
             "RunTimeTicks": -5, "UserData": {"PlaybackPositionTicks": -huge}},
            {"Id": "aaaa0000000000000000000000000004", "Name": "Good", "Type": "Movie",
             "RunTimeTicks": 100000000, "UserData": {"PlaybackPositionTicks": 50000000}},
            {"Id": "aaaa0000000000000000000000000005", "Name": "Year", "Type": "Movie",
             "ProductionYear": huge, "RunTimeTicks": 10 ** 30,
             "UserData": {"PlaybackPositionTicks": 10 ** 29}}]}
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps(body).encode())
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.OK)
        self.assertIn("Good", [i.title for i in r.items])
        for i in r.items:
            self.assertTrue(i.progress_fraction is None or 0 <= i.progress_fraction <= 1)
            self.assertLess(i.position_seconds or 0, 2 ** 63)

    def test_only_hostile_numbers_is_unavailable_not_a_crash(self):
        body = {"Items": [{"Id": ITEM, "Name": "Big", "Type": "Movie",
                           "UserData": {"PlaybackPositionTicks": 10 ** 400}}]}
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps(body).encode())
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.UNAVAILABLE)

    def test_hook_arithmetic_and_type_errors_are_converted(self):
        for exc in (OverflowError("x"), ZeroDivisionError("x"), TypeError("x"), KeyError("x"),
                    IndexError("x"), AttributeError("x"), RecursionError("x"), ValueError("x"),
                    MemoryError()):
            self.setUp()
            adapter = self.adapter

            def boom(user, limit, exc=exc):
                raise exc
            adapter._continue_items = boom
            adapter._recent_items = boom
            adapter._item = lambda user, item_id, exc=exc: (_ for _ in ()).throw(exc)
            adapter._fetch_artwork = lambda user, ref, exc=exc: (_ for _ in ()).throw(exc)
            for r in self.every_method():
                if isinstance(r, SectionResult):
                    self.assertIs(r.state, SectionState.UNAVAILABLE, repr(exc))
                    self.assertEqual(r.reason, "UpstreamMalformed", repr(exc))
                else:
                    self.assertIs(r.state, SectionState.UNAVAILABLE, repr(exc))

    def test_http_client_exceptions_are_converted(self):
        excs = (http.client.BadStatusLine("x"), http.client.IncompleteRead(b"ab", 5),
                http.client.RemoteDisconnected("x"), http.client.CannotSendRequest(),
                ConnectionResetError(), BrokenPipeError(), http.client.InvalidURL("x"))
        for exc in excs:
            self.setUp()
            self.fake.overrides["/UserItems/Resume"] = ("raise", exc)
            r = self.adapter.continue_items(self.a)
            self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamUnreachable"),
                             repr(exc))
            self.setUp()
            self.fake.overrides["/Users"] = ("raise", exc)
            for res in self.every_method():
                self.assertIn(res.state, (SectionState.UNAVAILABLE,))

    def test_real_transport_maps_http_client_errors(self):
        for exc in (http.client.BadStatusLine("x"), http.client.IncompleteRead(b"a"),
                    http.client.RemoteDisconnected("x")):
            opener = FakeOpener(self.fake)
            opener.open = lambda req, timeout=None, exc=exc: (_ for _ in ()).throw(exc)
            t = UrllibTransport("https://jellyfin.invalid", {}, opener)
            with self.assertRaises(UpstreamUnreachable):
                t.request("GET", "/Users", None, 2.0, 100)

    def test_oversized_ints_are_bounded_at_the_source(self):
        from avrana_home.adapters.jellyfin import _int
        self.assertIsNone(_int(10 ** 400))
        self.assertIsNone(_int(-(10 ** 30)))
        self.assertIsNone(_int(float("nan")))
        self.assertEqual(_int(5), 5)

    def test_guid_normaliser_rejects_trailing_junk(self):
        self.assertIsNone(normalise_guid("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/../x"))
        self.assertIsNone(normalise_guid("aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa\n"))
        self.assertIsNone(normalise_guid("xaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"))


if __name__ == "__main__":
    unittest.main()
