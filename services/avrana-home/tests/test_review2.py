"""Second-review findings F1 to F11: breaker accounting, trial lease, drift, caps, budgets."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import concurrent.futures as cf
import json
import threading
import time
import unittest

from avrana_home import aggregate
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.aggregate import DEFAULT_HARD_CAP, gather
from avrana_home.contract import SectionState, Service
from avrana_home.resilience import (REQUEST_BUDGET, CircuitBreaker, FakeClock, UpstreamAuthError,
                                    UpstreamTimeout, counts_toward_breaker)
from tests.fake_jellyfin import A, B, FakeJellyfin, FakeTransport
from tests.helpers import FakeAdapter, make_principal

GROUPS = ("avrana-users", "avrana-videos")
ITEM = "aaaa0000000000000000000000000001"


class JF(unittest.TestCase):
    def build(self, **kw):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock, **kw)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)
        self.z = make_principal("member-z", GROUPS)         # not provisioned in the fake Jellyfin

    def setUp(self):
        self.build()


class F1CachedOutcomesAreNotUpstreamEvidence(JF):
    def test_cached_unlinked_requests_cannot_keep_a_failing_service_closed(self):
        self.assertIs(self.adapter.continue_items(self.z).state, SectionState.NOT_LINKED)   # fresh
        self.fake.overrides["/UserItems/Resume"] = ("status", 500)
        for _ in range(3):
            self.adapter.continue_items(self.a)                       # counted failure
            self.adapter.continue_items(self.z)                       # cached: no upstream call
        self.assertEqual(self.adapter.health().state, "cooling_off")

    def test_cached_ambiguous_mapping_is_cached_and_not_upstream_evidence(self):
        self.fake.users = self.fake.users + [dict(self.fake.users[0], Id="ffffffff-ffff-4fff-8fff-ffffffffffff")]
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "ambiguous"))
        n = self.fake.paths().count("/Users")
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "ambiguous"))
        self.assertEqual(self.fake.paths().count("/Users"), n)          # served from the cache

    def test_negative_mapping_is_cached_for_sixty_seconds(self):
        self.adapter.continue_items(self.z)
        n = self.fake.paths().count("/Users")
        self.adapter.recent_items(self.z)
        self.assertEqual(self.fake.paths().count("/Users"), n)
        self.clock.advance(61)
        self.adapter.recent_items(self.z)
        self.assertEqual(self.fake.paths().count("/Users"), n + 1)

    def test_resolve_user_from_cache_is_not_a_success(self):
        self.adapter.breaker = CircuitBreaker(self.clock, threshold=2)
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)    # mapping cached
        self.fake.overrides["/Items/Latest"] = ("status", 500)
        self.adapter.recent_items(self.a)                                            # failure 1
        self.assertIsNotNone(self.adapter.resolve_user(self.a))                      # cache only
        self.fake.overrides["/Items"] = ("status", 500)
        self.adapter.item(self.a, "aaaa0000000000000000000000000003")                # failure 2
        self.assertEqual(self.adapter.health().state, "cooling_off")


class F2UnexpectedTransportExceptions(JF):
    def test_runtime_error_from_the_transport_is_a_per_call_failure(self):
        class Weird(Exception):
            pass
        for exc in (RuntimeError("secret-in-message"), Weird("secret-in-message"), Exception("secret-in-message")):
            self.build()
            self.fake.overrides["/UserItems/Resume"] = ("raise", exc)
            with self.assertLogs("avrana_home", "WARNING") as cm:
                res = gather(self.a, [self.adapter], sections=("continue",))
            (r,) = res.sections
            self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamUnreachable"))
            self.assertNotEqual(self.adapter.health().state, "cooling_off")        # no force-open
            self.assertNotIn("secret-in-message", "\n".join(cm.output))

    def test_programming_errors_in_our_code_stay_visible_and_open_the_circuit(self):
        class Buggy(JellyfinAdapter):
            def _continue_items(self, user, limit):
                raise RuntimeError("bug in adapter code")
        a = Buggy(self.transport, clock=self.clock)
        with self.assertRaises(RuntimeError):
            a.continue_items(self.a)
        a = Buggy(self.transport, clock=self.clock)
        res = gather(self.a, [a], sections=("continue",))
        self.assertEqual(res.sections[0].state, SectionState.UNAVAILABLE)
        self.assertEqual(a.health().state, "cooling_off")          # documented: OUR bug trips it

    def test_programming_error_is_not_counted_as_success(self):
        self.adapter.breaker = CircuitBreaker(self.clock, threshold=3)

        class Buggy(JellyfinAdapter):
            def _recent_items(self, user, limit):
                raise RuntimeError("bug")
        bug = Buggy(self.transport, clock=self.clock, breaker=self.adapter.breaker)
        self.fake.overrides["/UserItems/Resume"] = ("status", 500)
        bug.continue_items(self.a)
        bug.continue_items(self.b)                                        # two counted failures
        with self.assertRaises(RuntimeError):
            bug.recent_items(self.a)                                       # must not reset the run
        bug.continue_items(self.a)
        self.assertEqual(bug.health().state, "cooling_off")


class F3TrialLease(unittest.TestCase):
    def test_a_trial_that_never_reports_is_re_admitted_after_the_lease(self):
        clock = FakeClock()
        cb = CircuitBreaker(clock, cooloff=60, threshold=1, trial_lease=10)
        cb.failure("X", cb.acquire())
        clock.advance(61)
        t1 = cb.acquire()
        self.assertIsNotNone(t1)
        clock.advance(5)
        self.assertIsNone(cb.acquire())                       # still within the lease
        clock.advance(6)
        t2 = cb.acquire()                                      # lease over: one new trial
        self.assertIsNotNone(t2)
        self.assertIsNone(cb.acquire())
        self.assertFalse(cb.valid(t1))
        self.assertFalse(cb.success(t1))                       # the stale trial's late result is ignored
        self.assertEqual(cb.snapshot("x").state, "unknown")
        self.assertTrue(cb.success(t2))
        self.assertEqual(cb.snapshot("x").state, "ok")

    def test_adapter_recovers_after_a_lost_trial(self):
        clock = FakeClock()
        fake = FakeJellyfin(clock)
        a = JellyfinAdapter(FakeTransport(fake), clock=clock,
                            breaker=CircuitBreaker(clock, threshold=1, trial_lease=10))
        p = make_principal("member-a", GROUPS)
        fake.overrides["/UserItems/Resume"] = ("status", 500)
        a.continue_items(p)
        del fake.overrides["/UserItems/Resume"]
        clock.advance(61)
        lost = a.breaker.acquire()                              # a caller took the trial and vanished
        self.assertIsNotNone(lost)
        self.assertEqual(a.continue_items(p).reason, "cooling_off")
        clock.advance(11)
        self.assertIs(a.continue_items(p).state, SectionState.OK)


class F4UserListDrift(JF):
    def test_nonempty_user_list_with_no_parsable_entry_is_drift(self):
        self.fake.overrides["/Users"] = ("body", b'[1, "x", null, {"Name": 5}, {"Id": "not-a-guid", "Name": "member-a"}]')
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMalformed"))
        self.assertEqual(self.adapter.health().last_error_class, "UpstreamMalformed")
        n = self.fake.paths().count("/Users")
        self.adapter.continue_items(self.a)
        self.assertEqual(self.fake.paths().count("/Users"), n + 1)       # nothing was cached

    def test_empty_user_list_is_legitimately_unlinked(self):
        self.fake.overrides["/Users"] = ("body", b"[]")
        self.assertEqual(self.adapter.continue_items(self.a).reason, "unmapped")


class F5PerMemberInFlightCap(unittest.TestCase):
    def test_one_member_cannot_starve_the_others(self):
        clock = FakeClock()
        ad = FakeAdapter(Service.JELLYFIN, {"member-a": "1", "member-b": "2"}, clock, mode="block",
                         max_in_flight=4, max_in_flight_per_member=1)
        ad.block_users = {"member-a"}
        pa, pb = make_principal("member-a", GROUPS), make_principal("member-b", GROUPS)
        t = threading.Thread(target=ad.continue_items, args=(pa,))
        t.start()
        try:
            self.assertTrue(ad.started.acquire(timeout=2))
            r = ad.recent_items(pa)
            self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "member_busy"))
            self.assertIs(ad.continue_items(pb).state, SectionState.OK)          # B is unaffected
            self.assertEqual(ad.in_flight, 1)
        finally:
            ad.release.set()
            t.join(2)
        for _ in range(200):
            if ad.in_flight == 0:
                break
            time.sleep(0.005)
        self.assertEqual(ad.in_flight, 0)
        self.assertIs(ad.recent_items(pa).state, SectionState.OK)

    def test_defaults_are_per_member_below_service_cap(self):
        ad = FakeAdapter(Service.JELLYFIN, {}, FakeClock())
        self.assertLess(ad._max_per_member, ad._max_in_flight)


class F6RouteVersusUserNotFound(JF):
    def test_404_with_a_freshly_confirmed_mapping_is_route_drift(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 404)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UserGone"))
        for _ in range(2):
            self.clock.advance(61)                                            # mapping expires: fresh each time
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")        # 3 counted: route is gone

    def test_404_after_a_cached_mapping_means_user_gone_and_is_member_specific(self):
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        self.clock.advance(31)                                               # section cache gone, mapping kept
        self.fake.overrides["/UserItems/Resume"] = ("status", 404)
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "upstream_user_not_found"))
        self.assertNotEqual(self.adapter.health().state, "cooling_off")
        self.assertEqual(self.adapter.health().last_error_class, None)
        self.fake.users = [u for u in self.fake.users if u["Name"] != "member-a"]
        del self.fake.overrides["/UserItems/Resume"]
        self.assertEqual(self.adapter.continue_items(self.a).reason, "unmapped")   # re-resolved, now gone

    def test_404_from_the_user_list_is_route_drift_and_counts(self):
        self.fake.overrides["/Users"] = ("status", 404)
        for _ in range(3):
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")


class F7SharedBudget(JF):
    def test_mapping_and_work_share_one_deadline(self):
        self.fake.slow["/Users"] = 1.7
        self.fake.slow["/UserItems/Resume"] = 1.7
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamTimeout"))
        self.assertEqual(len(self.transport.timeouts), 2)
        self.assertLessEqual(self.transport.timeouts[0], REQUEST_BUDGET)
        self.assertLessEqual(self.transport.timeouts[1], REQUEST_BUDGET - 1.7 + 1e-6)   # what is left

    def test_a_request_that_respects_its_budget_cannot_reach_the_hard_cap(self):
        self.assertGreater(DEFAULT_HARD_CAP, REQUEST_BUDGET)
        self.fake.slow["/Users"] = 0.9
        self.fake.slow["/UserItems/Resume"] = 0.9
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)    # 1.8 s < budget
        self.assertEqual(self.adapter.health().state, "ok")

    def test_artwork_lookup_and_image_share_it_too(self):
        self.fake.slow["/Users"] = 0.7
        self.fake.slow["/Items"] = 0.7
        self.fake.slow["/Items/" + ITEM + "/Images/Primary"] = 0.7
        r = self.adapter.fetch_artwork(self.a, "jellyfin/primary/" + ITEM)
        self.assertIs(r.state, SectionState.UNAVAILABLE)                              # 2.1 s > 2.0 s


class F8AuthErrors(JF):
    def test_counting_rule(self):
        self.assertTrue(counts_toward_breaker(UpstreamAuthError(401)))
        self.assertTrue(counts_toward_breaker(UpstreamAuthError(403)))                # default: service scope
        self.assertTrue(counts_toward_breaker(UpstreamAuthError(401), member_scoped=True))
        self.assertFalse(counts_toward_breaker(UpstreamAuthError(403), member_scoped=True))

    def test_403_on_a_member_scoped_call_is_neutral(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 403)
        for _ in range(5):
            r = self.adapter.continue_items(self.a)
            self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamAuthError"))
        self.assertNotEqual(self.adapter.health().state, "cooling_off")
        self.assertIs(self.adapter.continue_items(self.b).state, SectionState.UNAVAILABLE)

    def test_401_counts_and_403_on_the_user_list_counts(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 401)
        for _ in range(3):
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        self.build()
        self.fake.overrides["/Users"] = ("status", 403)
        for _ in range(3):
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")


class F9MappingBound(JF):
    def test_mapping_is_bounded_to_sixty_seconds_so_a_rename_surfaces_quickly(self):
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        self.fake.users = [dict(u, Name="member-renamed") if u["Name"] == "member-a" else u
                           for u in self.fake.users]
        n = self.fake.paths().count("/Users")
        self.clock.advance(31)
        self.assertIsNot(self.adapter.continue_items(self.a).state, SectionState.NOT_LINKED)   # inside the window
        self.assertEqual(self.fake.paths().count("/Users"), n)                        # mapping still cached
        self.clock.advance(31)                                                        # 62 s total
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.NOT_LINKED, "unmapped"))


class F10Gather(unittest.TestCase):
    def test_gather_requires_a_minted_principal(self):
        class Duck:
            username = "member-a"
            groups = frozenset({"avrana-videos"})
        for bad in (Duck(), "member-a", None, object.__new__(type(make_principal()))):
            with self.assertRaises(TypeError):
                gather(bad, [])

    def test_work_that_never_started_neither_runs_nor_opens_a_circuit(self):
        clock = FakeClock()
        hung = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, clock, mode="block")
        queued = FakeAdapter(Service.KOMGA, {"member-a": "1"}, clock)
        pool = cf.ThreadPoolExecutor(max_workers=1)
        original = aggregate._shared_pool
        aggregate._shared_pool = lambda: pool
        try:
            p = make_principal("member-a", ("avrana-videos", "avrana-comics"))
            res = gather(p, [hung, queued], sections=("continue",), hard_cap=0.05)
            states = {s.service: (s.state, s.reason) for s in res.sections}
            self.assertEqual(states[Service.JELLYFIN], (SectionState.UNAVAILABLE, "hard_cap"))
            self.assertEqual(states[Service.KOMGA], (SectionState.UNAVAILABLE, "queued"))
            self.assertEqual(hung.health().state, "cooling_off")
            self.assertNotEqual(queued.health().state, "cooling_off")
            hung.release.set()
            pool.shutdown(wait=True)
            self.assertEqual(queued.calls, 0)                 # cancelled, never ran
        finally:
            aggregate._shared_pool = original
            hung.release.set()
            pool.shutdown(wait=False)


class F11ArtworkMagic(JF):
    URL = "jellyfin/primary/" + ITEM

    def fetch(self, ctype, body):
        self.build()
        self.fake.image = (200, body, ctype)
        return self.adapter.fetch_artwork(self.a, self.URL)

    def test_matching_magic_numbers_pass(self):
        self.assertIs(self.fetch("image/png", b"\x89PNG\r\n\x1a\nxx").state, SectionState.OK)
        self.assertIs(self.fetch("image/jpeg", b"\xff\xd8\xff\xe0xx").state, SectionState.OK)
        self.assertIs(self.fetch("image/webp", b"RIFF\x04\x00\x00\x00WEBPVP8 ").state, SectionState.OK)

    def test_mismatched_or_missing_magic_is_refused_and_not_cached(self):
        for ctype, body in (("image/png", b"GIF89a"), ("image/jpeg", b"\x89PNG\r\n\x1a\n"),
                            ("image/webp", b"RIFF\x04\x00\x00\x00WAVEfmt "), ("image/png", b"<html>"),
                            ("image/png", b"\x89PNG"), ("image/png", b"")):
            r = self.fetch(ctype, body)
            self.assertIs(r.state, SectionState.UNAVAILABLE, (ctype, body))
            self.assertEqual(r.data, b"")
            self.assertEqual(len(self.adapter.cache), 1)       # only the member's mapping

    def test_image_size_bound_is_enforced_by_the_adapter(self):
        png = b"\x89PNG\r\n\x1a\n"
        five = 5 * 1024 * 1024
        self.assertIs(self.fetch("image/png", png + b"x" * (five - len(png))).state, SectionState.OK)
        self.assertIs(self.fetch("image/png", png + b"x" * (five - len(png) + 1)).state,
                      SectionState.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
