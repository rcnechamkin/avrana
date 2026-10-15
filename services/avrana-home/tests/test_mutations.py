"""Tests that pin behaviours a plausible code mutation would otherwise break silently."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import copy
import io
import json
import logging
import unittest
import urllib.request
import urllib.response
from email.message import Message

from avrana_home.adapters.jellyfin import GuardedTransport, JellyfinAdapter, check_request
from avrana_home.contract import ForbiddenRequest, SectionState
from avrana_home.resilience import (FakeClock, UpstreamHTTPError, UpstreamTimeout, UrllibTransport,
                                    _NoRedirect)
from tests.fake_jellyfin import A, B, FakeJellyfin, FakeTransport, load
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)


class GuidAndMappingTests(Base):
    def test_user_id_with_trailing_path_is_not_a_valid_account(self):
        self.fake.users = [dict(self.fake.users[0], Id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/../x"),
                           self.fake.users[1]]               # one parsable entry: not wholesale drift
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "unmapped"))
        self.assertEqual(self.fake.paths(), ["/Users"])

    def test_item_id_with_trailing_path_is_dropped(self):
        body = {"Items": [{"Id": "aaaa0000000000000000000000000001/../x", "Name": "N", "Type": "Movie",
                           "UserData": {"PlaybackPositionTicks": 5}},
                          {"Id": "aaaa0000000000000000000000000002", "Name": "Ok", "Type": "Movie",
                           "UserData": {"PlaybackPositionTicks": 5}}]}
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps(body).encode())
        r = self.adapter.continue_items(self.a)
        self.assertEqual([i.title for i in r.items], ["Ok"])


class LimitAndLookupTests(Base):
    def listing(self, n):
        return {"Items": [{"Id": "aaaa00000000000000000000000000%02x" % i, "Name": f"T{i}",
                           "Type": "Movie", "RunTimeTicks": 100000000,
                           "UserData": {"PlaybackPositionTicks": 5000000}} for i in range(n)]}

    def test_exactly_limit_is_fine_one_more_is_hostile(self):
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps(self.listing(12)).encode())
        self.assertEqual(len(self.adapter.continue_items(self.a, 12).items), 12)
        self.setUp()
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps(self.listing(13)).encode())
        r = self.adapter.continue_items(self.a, 12)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMisbehaved"))
        self.assertEqual(r.items, ())

    def test_item_lookup_returns_only_the_requested_id(self):
        other = load("resume_member_a.json")["Items"][0]               # a different visible item
        self.fake.overrides["/Items"] = ("body", json.dumps({"Items": [other]}).encode())
        r = self.adapter.item(self.a, "aaaa0000000000000000000000000010")
        self.assertIs(r.state, SectionState.EMPTY)
        self.assertEqual(r.items, ())
        art = self.adapter.fetch_artwork(self.a, "jellyfin/primary/aaaa0000000000000000000000000010")
        self.assertIs(art.state, SectionState.EMPTY)
        self.assertFalse([p for p in self.fake.paths() if p.endswith("/Images/Primary")])


class GuardTests(unittest.TestCase):
    def test_user_id_is_refused_on_the_unscoped_image_route(self):
        image = "/Items/" + "a" * 32 + "/Images/Primary"
        with self.assertRaises(ForbiddenRequest):
            check_request("GET", image, {"userId": A}, A)
        check_request("GET", image, {"maxWidth": "400"}, A)

    def test_bound_user_id_must_itself_be_a_guid(self):
        inner = FakeTransport(FakeJellyfin())
        for bad in ("../x", "AAAA", "", "a" * 31, "a" * 33, "a" * 32 + "\n", 5, "A" * 32):
            with self.assertRaises(ForbiddenRequest, msg=repr(bad)):
                GuardedTransport(inner).bind(bad)
            with self.assertRaises(ForbiddenRequest, msg=repr(bad)):
                GuardedTransport(inner, bad)
        GuardedTransport(inner).bind(A).bind(None)
        self.assertEqual(inner.calls, 0)

    def test_check_request_rejects_unvalidated_bound_id_even_when_it_matches_the_query(self):
        with self.assertRaises(ForbiddenRequest):
            check_request("GET", "/UserItems/Resume", {"userId": "../x"}, "../x")


class LoggingTests(Base):
    SECRET = "fake-secret-in-message-0042"

    def records_for(self, action):
        with self.assertLogs("avrana_home", "DEBUG") as cm:
            action()
        for rec in cm.records:
            text = rec.getMessage() + repr(rec.args) + str(rec.exc_info) + str(rec.exc_text)
            self.assertNotIn(self.SECRET, text)
            self.assertIsNone(rec.exc_info)
        return cm.output

    def test_exception_messages_never_reach_logs(self):
        self.fake.overrides["/UserItems/Resume"] = ("raise", UpstreamTimeout(self.SECRET))
        out = self.records_for(lambda: self.adapter.continue_items(self.a))
        self.assertIn("UpstreamTimeout", "".join(out))
        self.setUp()
        self.fake.overrides["/UserItems/Resume"] = ("raise", UpstreamHTTPError(500))
        self.records_for(lambda: self.adapter.continue_items(self.a))
        self.setUp()
        self.fake.overrides["/UserItems/Resume"] = ("raise", ValueError(self.SECRET))
        self.records_for(lambda: self.adapter.continue_items(self.a))
        self.setUp()
        self.fake.overrides["/Users"] = ("raise", OSError(self.SECRET))
        self.records_for(lambda: self.adapter.continue_items(self.a))


class _Redirecting(urllib.request.HTTPHandler):
    """Answers every request with a 302 to another host and counts what it was asked for."""

    def __init__(self):
        super().__init__()
        self.opened = []

    def http_open(self, req):
        self.opened.append(req.full_url)
        hdrs = Message()
        hdrs["Location"] = "http://elsewhere.invalid/steal"
        resp = urllib.response.addinfourl(io.BytesIO(b""), hdrs, req.full_url, 302)
        resp.msg = "Found"
        return resp


class RedirectTests(unittest.TestCase):
    def test_a_302_is_an_error_and_is_not_followed(self):
        handler = _Redirecting()
        opener = urllib.request.build_opener(_NoRedirect, handler)
        t = UrllibTransport("http://upstream.invalid", {"Authorization": "test-synthetic"}, opener)
        with self.assertRaises(UpstreamHTTPError) as cm:
            t.request("GET", "/Users", None, 2.0, 100)
        self.assertEqual(cm.exception.status, 302)
        self.assertEqual(handler.opened, ["http://upstream.invalid/Users"])   # never the Location


if __name__ == "__main__":
    unittest.main()
