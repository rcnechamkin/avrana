"""Tier A: the mock Jellyfin, and the whole adapter path over real loopback HTTP.

principal -> JellyfinAdapter -> real UrllibTransport -> HTTP on 127.0.0.1 -> mock. Standard
library only; every title and id is synthetic.
"""
import json
import time
import unittest
import urllib.request

from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.aggregate import gather
from avrana_home.contract import SectionState
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import UrllibTransport
from dev.mock_jellyfin import MOCK_KEY, MockJellyfin

A = "aaaa0000000000000000000000000001"
B_TITLE = "Synthetic Film Two"


def principal(name, groups="avrana-users|avrana-videos"):
    return principal_from_headers({"X-authentik-username": name, "X-authentik-groups": groups})


def adapter_for(mock, timeout=2.0, key=MOCK_KEY):
    return JellyfinAdapter(UrllibTransport(mock.url, {"Authorization": f'MediaBrowser Token="{key}"'}),
                           timeout=timeout)


def titles(result):
    return [i.title for i in result.items]


class MockServerTests(unittest.TestCase):
    def test_binds_loopback_only(self):
        for host in ("0.0.0.0", "192.0.2.1", "localhost", ""):
            with self.subTest(host=host), self.assertRaises(ValueError):
                MockJellyfin(host=host)

    def test_unknown_mode_is_rejected(self):
        with MockJellyfin() as mock:
            with self.assertRaises(ValueError):
                mock.set_mode("explode")

    def test_control_endpoints(self):
        with MockJellyfin() as mock:
            req = urllib.request.Request(mock.url + "/__mock/mode/down", method="POST")
            self.assertEqual("down", json.load(urllib.request.urlopen(req, timeout=5))["mode"])
            self.assertEqual("down", mock.mode)
            req = urllib.request.Request(mock.url + "/__mock/mode/bogus", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(400, cm.exception.code)
            mock.set_mode("ok")
            info = json.load(urllib.request.urlopen(mock.url + "/__mock/requests", timeout=5))
            self.assertEqual(0, info["count"])

    def test_missing_or_wrong_token_is_401(self):
        with MockJellyfin() as mock:
            for headers in ({}, {"Authorization": 'MediaBrowser Token="wrong"'}):
                req = urllib.request.Request(mock.url + "/Users", headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(401, cm.exception.code)

    def test_fixtures_are_synthetic_only(self):
        with MockJellyfin() as mock:
            names = {u["Name"] for u in mock.users}
            self.assertEqual({"member-a", "member-b", "member-c", "synthetic-admin"}, names)


class AdapterOverHttpTests(unittest.TestCase):
    def test_ok_each_member_sees_only_their_own_items(self):
        with MockJellyfin() as mock:
            ad = adapter_for(mock)
            ra = ad.continue_items(principal("member-a"))
            rb = ad.continue_items(principal("member-b"))
            self.assertEqual(SectionState.OK, ra.state)
            self.assertIn("Synthetic Film One", titles(ra))
            self.assertNotIn(B_TITLE, titles(ra))
            self.assertIn(B_TITLE, titles(rb))
            self.assertNotIn("Synthetic Film One", titles(rb))

    def test_not_permitted_makes_no_upstream_call(self):
        with MockJellyfin() as mock:
            ad = adapter_for(mock)
            r = ad.continue_items(principal("member-a", "avrana-users|avrana-books"))
            self.assertEqual(SectionState.NOT_PERMITTED, r.state)
            self.assertEqual([], mock.paths())

    def test_unmapped_and_disabled_members_are_not_linked(self):
        with MockJellyfin() as mock:
            ad = adapter_for(mock)
            self.assertEqual(SectionState.NOT_LINKED, ad.continue_items(principal("member-d")).state)
            self.assertEqual(SectionState.NOT_LINKED, ad.continue_items(principal("member-c")).state)

    def test_down_is_unavailable_and_then_cools_off(self):
        with MockJellyfin(mode="down") as mock:
            ad = adapter_for(mock)
            for _ in range(3):
                r = ad.continue_items(principal("member-a"))
                self.assertEqual(SectionState.UNAVAILABLE, r.state)
            seen = len(mock.paths())
            self.assertEqual("cooling_off", ad.continue_items(principal("member-a")).reason)
            self.assertEqual(seen, len(mock.paths()))          # no traffic while cooling off

    def test_failure_modes_are_unavailable_never_an_exception(self):
        for mode in ("500", "malformed", "wrong-user", "down"):
            with self.subTest(mode=mode), MockJellyfin(mode=mode) as mock:
                ad = adapter_for(mock)
                r = ad.continue_items(principal("member-a"))
                self.assertEqual(SectionState.UNAVAILABLE, r.state, mode)
                self.assertEqual((), r.items)

    def test_wrong_user_data_never_reaches_the_result(self):
        with MockJellyfin(mode="wrong-user") as mock:
            ad = adapter_for(mock)
            r = ad.continue_items(principal("member-a"))
            self.assertEqual(SectionState.UNAVAILABLE, r.state)
            self.assertEqual("UpstreamMisbehaved", r.reason)
            self.assertNotIn(B_TITLE, json.dumps(r.to_dict()))

    def test_slow_beyond_the_timeout_costs_only_that_section(self):
        with MockJellyfin(mode="slow", slow_seconds=1.5) as mock:
            ad = adapter_for(mock, timeout=0.3)
            started = time.monotonic()
            r = ad.continue_items(principal("member-a"))
            self.assertEqual(SectionState.UNAVAILABLE, r.state)
            self.assertLess(time.monotonic() - started, 1.2)

    def test_wrong_token_is_unavailable_and_counts_as_a_service_failure(self):
        with MockJellyfin() as mock:
            ad = adapter_for(mock, key="some-other-fake-key")
            r = ad.continue_items(principal("member-a"))
            self.assertEqual(SectionState.UNAVAILABLE, r.state)
            self.assertEqual("UpstreamAuthError", r.reason)

    def test_gather_through_real_http_returns_both_sections(self):
        with MockJellyfin() as mock:
            ad = adapter_for(mock)
            view = gather(principal("member-a"), [ad]).member_view()
            self.assertEqual(["continue", "recent"], [s["section"] for s in view["sections"]])
            self.assertTrue(all(s["state"] == "ok" for s in view["sections"]))

    def test_stopped_server_is_unavailable(self):
        mock = MockJellyfin().start()
        ad = adapter_for(mock)
        mock.stop()
        self.assertEqual(SectionState.UNAVAILABLE, ad.continue_items(principal("member-a")).state)


if __name__ == "__main__":
    unittest.main()
