"""Jellyfin adapter against SYNTHETIC fixtures and a fake transport. No sockets, no real server."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import json
import unittest

from avrana_home.adapters.jellyfin import (ALLOWED_ROUTES, GuardedTransport, JellyfinAdapter,
                                           check_request, normalise_guid)
from avrana_home.contract import ForbiddenRequest, SectionState, Service
from avrana_home.principal import PrincipalError, principal_from_headers
from avrana_home.resilience import (CircuitBreaker, FakeClock, UpstreamTimeout, UpstreamUnreachable,
                                    UrllibTransport)
from tests.fake_jellyfin import A, B, FakeJellyfin, FakeOpener, FakeTransport, load
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")
A_MARKERS = ("aaaa0000", "Film One", "Synthetic Pilot", "Film Three", "Series Alpha", "synthtag1",
             "synthtag2", A)
B_MARKERS = ("bbbb0000", "Film Two", "Documentary B", "Film Four", "synthtagb", B)


def as_json(*results):
    return json.dumps([r.to_dict() if hasattr(r, "to_dict") else repr(r) for r in results])


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)

    def assertNone(self, text, markers):
        for m in markers:
            self.assertNotIn(m, text, m)


class FixtureSanityTests(unittest.TestCase):
    def test_fixture_ids_are_valid_guids_and_labelled(self):
        for name in ("resume_member_a.json", "resume_member_b.json", "latest_member_a.json"):
            for item in (load(name)["Items"] if "resume" in name else load(name)):
                if item["Id"].startswith("../"):
                    self.assertIsNone(normalise_guid(item["Id"]))
                else:
                    self.assertIsNotNone(normalise_guid(item["Id"]), item["Id"])
        for u in load("users.json"):
            self.assertIsNotNone(normalise_guid(u["Id"]), u["Id"])
        self.assertEqual(normalise_guid("aaaa0000-0000-0000-0000-000000000002"),
                         "aaaa0000000000000000000000000002")


class MappingTests(Base):
    def test_exact_name_maps(self):
        self.assertEqual(self.adapter.resolve_user(self.a).upstream_id, A)
        self.assertEqual(self.adapter.resolve_user(self.b).upstream_id, B)

    def test_unmapped_is_not_linked_and_only_user_list_is_called(self):
        self.fake.users = [u for u in self.fake.users if u["Name"] != "member-a"]
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.NOT_LINKED)
        self.assertEqual(r.reason, "unmapped")
        self.assertEqual(self.fake.paths(), ["/Users"])
        self.assertIs(self.adapter.recent_items(self.a).state, SectionState.NOT_LINKED)
        self.assertEqual(self.fake.paths(), ["/Users"])           # negative mapping is cached
        self.assertIs(self.adapter.continue_items(self.b).state, SectionState.OK)

    def test_disabled_upstream_account_not_linked(self):
        c = make_principal("member-c", GROUPS)
        r = self.adapter.continue_items(c)
        self.assertIs(r.state, SectionState.NOT_LINKED)
        self.assertEqual(r.reason, "disabled")

    def test_case_whitespace_unicode_variants_never_get_anyones_data(self):
        for variant in ("Member-A", "MEMBER-A", "membeр-a".replace("р", "г"),
                        "member‐a", "ｍembｅr-a", "member-ａ"):
            self.setUp()
            p = make_principal(variant, GROUPS)
            for result in (self.adapter.continue_items(p), self.adapter.recent_items(p),
                           self.adapter.item(p, "aaaa0000000000000000000000000001")):
                self.assertIs(result.state, SectionState.NOT_LINKED, variant)
                self.assertEqual(result.items, ())
                self.assertNone(as_json(result), A_MARKERS + B_MARKERS)
            self.assertEqual(self.fake.paths(), ["/Users"], variant)
            self.assertEqual(self.adapter.fetch_artwork(p, "jellyfin/primary/" + "a" * 28 + "0001").state,
                             SectionState.NOT_LINKED)

    def test_loose_match_reason_is_reported_for_operators(self):
        self.assertEqual(self.adapter.continue_items(make_principal("Member-A", GROUPS)).reason,
                         "case_or_unicode_mismatch")
        self.setUp()
        self.assertEqual(self.adapter.continue_items(make_principal("ｍembｅr-a", GROUPS)).reason,
                         "case_or_unicode_mismatch")

    def test_whitespace_and_nfd_usernames_never_become_principals(self):
        for bad in ("member-a ", " member-a", "member-a\t", "é"):
            with self.assertRaises(PrincipalError):
                principal_from_headers({"X-authentik-username": bad, "X-authentik-groups": "g"})

    def test_case_collision_in_upstream_is_refused(self):
        self.fake.users = self.fake.users + [
            {"Id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", "Name": "Member-A", "Policy": {}}]
        for name in ("member-a", "Member-A"):
            r = self.adapter.continue_items(make_principal(name, GROUPS))
            self.assertIs(r.state, SectionState.NOT_LINKED, name)
            self.assertEqual(r.reason, "ambiguous")
        self.assertEqual([p for p in self.fake.paths() if p != "/Users"], [])
        self.assertIsNone(self.adapter.resolve_user(make_principal("member-a", GROUPS)))

    def test_duplicate_exact_names_with_different_ids_are_refused(self):
        self.fake.users = self.fake.users + [
            {"Id": "ffffffff-ffff-4fff-8fff-ffffffffffff", "Name": "member-a", "Policy": {}}]
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "ambiguous"))
        self.assertEqual(self.fake.paths(), ["/Users"])

    def test_same_account_listed_twice_is_not_ambiguous(self):
        self.fake.users = self.fake.users + [dict(self.fake.users[0])]
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)

    def test_user_list_malformed_is_unavailable(self):
        self.fake.overrides["/Users"] = ("body", b'{"not": "a list"}')
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.UNAVAILABLE)


class PermissionTests(Base):
    def test_member_without_videos_group_makes_zero_transport_calls(self):
        p = make_principal("member-a", ("avrana-users", "avrana-audiobooks", "avrana-videos-extra",
                                        "Avrana-Videos"))
        results = [self.adapter.continue_items(p), self.adapter.recent_items(p),
                   self.adapter.item(p, "aaaa0000000000000000000000000001"),
                   self.adapter.item(p, "../bad")]
        for r in results:
            self.assertIs(r.state, SectionState.NOT_PERMITTED)
            self.assertEqual(r.items, ())
        self.assertIs(self.adapter.fetch_artwork(p, "jellyfin/primary/" + "a" * 28 + "0001").state,
                      SectionState.NOT_PERMITTED)
        self.assertIsNone(self.adapter.resolve_user(p))
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(self.fake.requests, [])

    def test_group_removal_beats_a_warm_cache(self):
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        n = self.transport.calls
        demoted = make_principal("member-a", ("avrana-users",))      # same username, group gone
        self.assertIs(self.adapter.continue_items(demoted).state, SectionState.NOT_PERMITTED)
        self.assertEqual(self.transport.calls, n)


class ContinueAndRecentTests(Base):
    def test_continue_for_a(self):
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.OK)
        self.assertEqual([i.title for i in r.items],
                         ["Synthetic Film One", "Synthetic Pilot", "Untitled"])
        film, ep, untitled = r.items
        self.assertEqual((film.progress_fraction, film.position_seconds, film.duration_seconds),
                         (0.42, 3024, 7200))
        self.assertEqual((ep.series, ep.subtitle, ep.kind.value), ("Synthetic Series Alpha", "S1 E3", "episode"))
        self.assertAlmostEqual(ep.progress_fraction, 0.25)
        self.assertAlmostEqual(untitled.progress_fraction, 0.1)
        self.assertEqual(film.artwork.ref, "jellyfin/primary/aaaa0000000000000000000000000001")
        self.assertEqual(film.artwork.alt, "Poster for Synthetic Film One")
        self.assertEqual(ep.artwork.alt, "Still from Synthetic Series Alpha, Synthetic Pilot")
        self.assertIsNone(untitled.artwork)
        for i in r.items:
            self.assertRegex(i.handoff_url, r"^https://watch\.avrana\.net/web/#/details\?id=[0-9a-f]{32}$")
        self.assertNone(as_json(r), B_MARKERS)
        self.assertNotIn("Played", as_json(r))

    def test_bad_entries_are_dropped_not_interpolated(self):
        self.adapter.continue_items(self.a)
        for _, path, query in self.fake.requests:
            blob = path + json.dumps(query)
            self.assertNotIn("..", blob)
            self.assertNotIn("Users/aaaa", blob)

    def test_recent_for_a_and_b_differ_and_hide_user_flags(self):
        ra, rb = self.adapter.recent_items(self.a), self.adapter.recent_items(self.b)
        self.assertEqual([i.title for i in ra.items],
                         ["Synthetic Film Three", "Synthetic Series Alpha", "Synthetic Shared Film"])
        self.assertEqual([i.title for i in rb.items], ["Synthetic Film Four", "Synthetic Shared Film"])
        for r in (ra, rb):
            self.assertTrue(all(i.progress_fraction is None for i in r.items))
            self.assertNotIn("Played", as_json(r))
            self.assertNotIn("Favorite", as_json(r))
        self.assertNone(as_json(ra), B_MARKERS)
        self.assertNone(as_json(rb), A_MARKERS)

    def test_empty_when_nothing_in_progress(self):
        self.fake.users.append({"Id": "99999999-9999-4999-8999-999999999999", "Name": "member-z",
                                "Policy": {}})
        r = self.adapter.continue_items(make_principal("member-z", GROUPS))
        self.assertIs(r.state, SectionState.EMPTY)

    def test_item_metadata_is_member_scoped(self):
        ok = self.adapter.item(self.a, "aaaa0000000000000000000000000001")
        self.assertEqual([i.title for i in ok.items], ["Synthetic Film One"])
        self.assertIsNotNone(ok.items[0].progress_fraction)
        other = self.adapter.item(self.a, "bbbb0000000000000000000000000001")
        self.assertIs(other.state, SectionState.EMPTY)
        self.assertNone(as_json(other), B_MARKERS)
        mine = self.adapter.item(self.b, "bbbb0000000000000000000000000001")
        self.assertEqual(len(mine.items), 1)
        self.assertIs(self.adapter.item(self.b, "aaaa0000000000000000000000000001").state,
                      SectionState.EMPTY)

    def test_invalid_item_ids_make_no_request(self):
        for bad in ("../x", "AAAA0000000000000000000000000001", "aaaa", "", "a" * 33,
                    "aaaa0000-0000-0000-0000-000000000001", None, 5):
            r = self.adapter.item(self.a, bad)
            self.assertIs(r.state, SectionState.EMPTY, repr(bad))
        self.assertEqual(self.fake.requests, [])

    def test_search_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.adapter.search(self.a, "synthetic")


class IsolationTests(Base):
    def full_run(self, p):
        return [self.adapter.continue_items(p), self.adapter.recent_items(p),
                self.adapter.item(p, "aaaa0000000000000000000000000001"),
                self.adapter.item(p, "bbbb0000000000000000000000000001")]

    def test_a_gets_nothing_of_b_and_b_nothing_of_a(self):
        ra = as_json(*self.full_run(self.a))
        rb = as_json(*self.full_run(self.b))
        self.assertNone(ra, B_MARKERS)
        self.assertNone(rb, A_MARKERS)

    def test_every_request_is_scoped_and_allow_listed(self):
        for p in (self.a, self.b):
            self.full_run(p)
            self.adapter.fetch_artwork(p, "jellyfin/primary/aaaa0000000000000000000000000001")
        for method, path, query in self.fake.requests:
            self.assertEqual(method, "GET")
            if path == "/Users":
                self.assertNotIn("userId", query)
                continue
            if "userId" in query:
                self.assertIn(query["userId"], (A, B))
            else:
                self.assertTrue(path.endswith("/Images/Primary"), path)
            check_request(method, path, query, query.get("userId") or A)
        a_queries = [q for _, _, q in self.fake.requests if q.get("userId") == A]
        self.assertTrue(a_queries)

    def test_cache_warm_with_b_then_a(self):
        b1 = self.adapter.continue_items(self.b)
        self.adapter.recent_items(self.b)
        self.adapter.item(self.b, "bbbb0000000000000000000000000001")
        a1 = self.adapter.continue_items(self.a)
        a2 = self.adapter.recent_items(self.a)
        self.assertNone(as_json(a1, a2), B_MARKERS)
        self.assertIsNot(a1, b1)
        n = len(self.fake.requests)
        self.assertIs(self.adapter.continue_items(self.a), a1)         # own cache hit
        self.assertEqual(len(self.fake.requests), n)
        self.assertEqual(self.adapter.item(self.a, "bbbb0000000000000000000000000001").items, ())

    def test_artwork_visibility_check_blocks_other_members_items(self):
        ok = self.adapter.fetch_artwork(self.a, "jellyfin/primary/aaaa0000000000000000000000000001")
        self.assertEqual((ok.state, ok.content_type), (SectionState.OK, "image/png"))
        before = [p for p in self.fake.paths() if p.endswith("/Images/Primary")]
        denied = self.adapter.fetch_artwork(self.a, "jellyfin/primary/bbbb0000000000000000000000000001")
        self.assertIs(denied.state, SectionState.EMPTY)
        self.assertEqual(denied.data, b"")
        after = [p for p in self.fake.paths() if p.endswith("/Images/Primary")]
        self.assertEqual(before, after)                                 # no image request for B's item
        cached_for_b = self.adapter.fetch_artwork(self.b, "jellyfin/primary/aaaa0000000000000000000000000001")
        self.assertIs(cached_for_b.state, SectionState.EMPTY)           # A's warm artwork is not B's

    def test_artwork_bad_refs_and_types(self):
        for ref in ("", "jellyfin/primary/../../Users", "jellyfin/primary/AAAA", "x" * 101,
                    "komga/primary/" + "a" * 32, None):
            self.assertIs(self.adapter.fetch_artwork(self.a, ref).state, SectionState.EMPTY, repr(ref))
        self.assertEqual({p for p in self.fake.paths()}, {"/Users"})   # no item or image request
        self.fake.image = (200, b"<html>", "text/html")
        r = self.adapter.fetch_artwork(self.a, "jellyfin/primary/aaaa0000000000000000000000000001")
        self.assertIs(r.state, SectionState.UNAVAILABLE)
        # an item without artwork has none to fetch
        self.setUp()
        r = self.adapter.fetch_artwork(self.a, "jellyfin/primary/cccc0000000000000000000000000001")
        self.assertIs(r.state, SectionState.EMPTY)

    def test_hostile_upstream_naming_another_user_is_discarded(self):
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock,
                                       breaker=CircuitBreaker(self.clock, threshold=1))
        self.fake.hostile_resume = load("hostile_resume_b_for_a.json")
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.UNAVAILABLE)
        self.assertEqual(r.reason, "UpstreamMisbehaved")
        self.assertEqual(r.items, ())
        self.assertNone(as_json(r), B_MARKERS)
        n = len(self.fake.requests)
        self.assertIs(self.adapter.recent_items(self.a).state, SectionState.UNAVAILABLE)   # cooling off
        self.assertEqual(len(self.fake.requests), n)
        self.assertEqual(self.adapter.health().state, "cooling_off")

    def test_hostile_item_naming_another_item_is_discarded(self):
        body = load("resume_member_a.json")
        body["Items"][0]["UserData"]["ItemId"] = "bbbb0000000000000000000000000001"
        self.fake.hostile_resume = body
        self.assertEqual(self.adapter.continue_items(self.a).reason, "UpstreamMisbehaved")

    def test_hostile_unbounded_listing_is_discarded(self):
        body = {"Items": [dict(load("resume_member_b.json")["Items"][0], Id="bbbb00000000000000000000000000%02x" % i)
                          for i in range(13)]}
        self.fake.hostile_resume = body
        r = self.adapter.continue_items(self.a)           # default limit 12, upstream returned 13
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMisbehaved"))

    def test_unattributable_response_limit_is_scoping_only(self):
        """A hostile body that carries no identity hint cannot be detected from the response.
        What the adapter CAN guarantee, and this test pins, is that the request named only A."""
        body = {"Items": [dict(load("resume_member_b.json")["Items"][0])]}
        body["Items"][0]["UserData"].pop("ItemId")
        self.fake.hostile_resume = body
        self.adapter.continue_items(self.a)
        resume = [q for _, p, q in self.fake.requests if p == "/UserItems/Resume"]
        self.assertEqual([q["userId"] for q in resume], [A])


class UpstreamFailureTests(Base):
    def run_with(self, override, path="/UserItems/Resume"):
        self.setUp()
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock,
                                       breaker=CircuitBreaker(self.clock, threshold=1))
        self.fake.overrides[path] = override
        with self.assertLogs("avrana_home", "WARNING") as cm:
            r = self.adapter.continue_items(self.a)
        return r, "\n".join(cm.output)

    def test_every_failure_is_unavailable_never_an_exception(self):
        cases = {
            "401": ("status", 401), "403": ("status", 403), "500": ("status", 500),
            "400": ("status", 400), "timeout": ("raise", UpstreamTimeout()),
            "unreachable": ("raise", UpstreamUnreachable()), "not json": ("body", b"not json"),
            "bad utf8": ("body", b"\xff\xfe"), "string": ("body", b'"s"'), "list": ("body", b"[]"),
            "null": ("body", b"null"), "oversized": ("body", b"x" * (2 * 1024 * 1024)),
        }
        for label, override in cases.items():
            r, logs = self.run_with(override)
            self.assertIs(r.state, SectionState.UNAVAILABLE, label)
            self.assertEqual(r.items, (), label)
            self.assertNotIn("member-a", logs, label)
            self.assertNotIn("Synthetic", logs, label)
            self.assertIn("service=jellyfin", logs, label)
            if label in ("400", "403"):             # per-request 4xx / member-scoped 403: never counted
                self.assertNotEqual(self.adapter.health().state, "cooling_off", label)
            else:
                self.assertEqual(self.adapter.health().state, "cooling_off", label)
            self.assertEqual(self.fake.paths().count("/UserItems/Resume"), 1, label)   # no retry

    def test_failure_on_user_list(self):
        for override in (("status", 500), ("raise", UpstreamTimeout()), ("body", b"{")):
            r, _ = self.run_with(override, "/Users")
            self.assertIs(r.state, SectionState.UNAVAILABLE)
            self.assertEqual(self.fake.paths(), ["/Users"])

    def test_slow_upstream_exceeds_budget(self):
        self.fake.slow["/UserItems/Resume"] = 2.5
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamTimeout"))
        self.assertTrue(all(t <= 2.0 for t in self.transport.timeouts))

    def test_recovers_after_cooloff_and_failures_are_not_cached(self):
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock,
                                       breaker=CircuitBreaker(self.clock, threshold=1))
        self.fake.overrides["/UserItems/Resume"] = ("status", 500)
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)
        del self.fake.overrides["/UserItems/Resume"]
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)  # cooling
        self.clock.advance(61)
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)

    def test_drift_and_malformed_items_are_dropped_not_raised(self):
        junk = {"Items": [
            5, "x", None, {"Id": 5}, {"Id": "aaaa0000000000000000000000000009", "Name": 123,
             "Type": "Movie", "RunTimeTicks": "abc", "UserData": [1], "ImageTags": "x"},
            {"Id": "aaaa000000000000000000000000000a", "Name": "Extra\x00Field\nTitle" + "z" * 300,
             "Type": "Movie", "RunTimeTicks": 0, "NewUpstreamField": {"x": 1},
             "UserData": {"PlaybackPositionTicks": 600000000, "PlayedPercentage": "n/a"},
             "ImageTags": {"Primary": ""}}], "TotalRecordCount": "many"}
        self.fake.overrides["/UserItems/Resume"] = ("body", json.dumps(junk).encode())
        r = self.adapter.continue_items(self.a)
        self.assertIs(r.state, SectionState.OK)
        (item,) = r.items
        self.assertLessEqual(len(item.title), 200)
        self.assertTrue(item.title.startswith("ExtraField"))
        self.assertTrue(item.title.isprintable())
        d = item.to_dict()
        self.assertEqual(d["progress"], {"fraction": None, "percent": None,
                                         "position_seconds": 60, "duration_seconds": None})
        self.assertIsNone(d["artwork"])
        json.dumps(d)


class AllowListTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeJellyfin()
        self.inner = FakeTransport(self.fake)
        self.guard = GuardedTransport(self.inner).bind(A)

    def refuse(self, method, path, query=None, guard=None):
        with self.assertRaises(ForbiddenRequest):
            (guard or self.guard).request(method, path, query, 2.0, 1000)
        self.assertEqual(self.inner.calls, 0)

    def test_only_get(self):
        for m in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "get", "", None):
            self.refuse(m, "/Users")
            self.refuse(m, "/UserItems/Resume", {"userId": A})

    def test_unlisted_paths(self):
        for p in ("/System/Restart", "/Users/" + A + "/Password", "/Users/New", "/Users/" + A,
                  "/Items/../System/Restart", "/Items/" + A + "/Images/Primary/../..",
                  "/Items/" + "z" * 32 + "/Images/Primary", "/Items/%2e%2e/x", "/UserItems/Resume/",
                  "/Sessions", "/Library/Refresh", "/Users/Public", "/Items/Latest\n", "users", "",
                  "/Items/" + A + "/Download", "http://evil.example/Users", None, 5):
            self.refuse("GET", p, {"userId": A})

    def test_query_rules(self):
        self.refuse("GET", "/UserItems/Resume", {"userId": B})                  # other user
        self.refuse("GET", "/UserItems/Resume", {})                             # no scope
        self.refuse("GET", "/UserItems/Resume", {"userId": A, "api_key": "x"})  # unknown key
        self.refuse("GET", "/UserItems/Resume", {"userId": A.upper()})          # not the bound id
        self.refuse("GET", "/UserItems/Resume", {"userId": [A]})
        self.refuse("GET", "/Users", {"userId": A})                              # not a scoped route
        self.refuse("GET", "/Items", {"userId": A, "ids": A, "ApiKey": "x"})
        self.refuse("GET", "/UserItems/Resume", {"userId": A}, guard=GuardedTransport(self.inner))  # unbound
        self.refuse("GET", "/Items/" + A + "/Images/Primary", None, guard=GuardedTransport(self.inner))

    def test_allowed_requests_pass(self):
        self.guard.request("GET", "/UserItems/Resume", {"userId": A, "limit": "3"}, 2.0, 1000)
        self.guard.request("GET", "/Items/" + A + "/Images/Primary", {"maxWidth": "400"}, 2.0, 1000)
        GuardedTransport(self.inner).request("GET", "/Users", None, 2.0, 1000)
        self.assertEqual(self.inner.calls, 3)

    def test_route_table_has_no_write_capable_template(self):
        names = sorted(r.name for r in ALLOWED_ROUTES)
        self.assertEqual(names, ["image", "items", "latest", "resume", "users"])

    def test_adapter_cannot_bypass_the_guard(self):
        adapter = JellyfinAdapter(self.inner, clock=FakeClock())
        guard = adapter._guard.bind(A)
        with self.assertRaises(ForbiddenRequest):
            adapter._get(guard, adapter._budget(), "/Users/" + A + "/Password", None)
        self.assertEqual(self.inner.calls, 0)


class SecretHandlingTests(unittest.TestCase):
    KEY = "test-synthetic-key-0001"

    def test_api_key_is_used_but_never_appears_in_results_reprs_or_logs(self):
        clock = FakeClock()
        fake = FakeJellyfin(clock)
        opener = FakeOpener(fake)
        transport = UrllibTransport("https://jellyfin.invalid",
                                    {"Authorization": f'MediaBrowser Token="{self.KEY}"'}, opener)
        adapter = JellyfinAdapter(transport, clock=clock)
        a = make_principal("member-a", GROUPS)
        seen = []
        with self.assertLogs("avrana_home", "DEBUG") as cm:
            seen += [adapter.continue_items(a), adapter.recent_items(a),
                     adapter.item(a, "aaaa0000000000000000000000000001")]
            art = adapter.fetch_artwork(a, "jellyfin/primary/aaaa0000000000000000000000000001")
            fake.overrides["/Items/Latest"] = ("status", 401)
            adapter.cache.clear()
            seen.append(adapter.recent_items(a))
            fake.overrides["/UserItems/Resume"] = ("status", 500)
            clock.advance(61)
            seen.append(adapter.continue_items(make_principal("member-b", GROUPS)))
        self.assertTrue(opener.seen_headers)
        self.assertTrue(all(self.KEY in h.get("Authorization", "") for h in opener.seen_headers))
        user = adapter.resolve_user(a)
        blobs = [as_json(*seen), repr(seen), repr(art), repr(adapter), repr(transport), repr(user),
                 repr(adapter._guard), "\n".join(cm.output), json.dumps(adapter.health().to_dict()),
                 repr(a)]
        for blob in blobs:
            self.assertNotIn(self.KEY, blob)
            self.assertNotIn("Token=", blob)
        self.assertIn("adapter_failure service=jellyfin", "\n".join(cm.output))

    def test_no_redirects_are_followed(self):
        from avrana_home.resilience import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "http://elsewhere"))


if __name__ == "__main__":
    unittest.main()
