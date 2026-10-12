"""Shared-circuit policy: what counts toward it, the threshold, and the single half-open trial."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import unittest

from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.contract import SectionState
from avrana_home.resilience import (CircuitBreaker, FakeClock, UpstreamAuthError, UpstreamHTTPError,
                                    UpstreamMalformed, UpstreamMisbehaved, UpstreamNotFound,
                                    UpstreamTimeout, UpstreamTooLarge, UpstreamUnreachable,
                                    counts_toward_breaker)
from tests.fake_jellyfin import A, B, FakeJellyfin, FakeTransport, load
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")


class CountingRuleTests(unittest.TestCase):
    def test_which_errors_count(self):
        counted = [UpstreamTimeout(), UpstreamUnreachable(), UpstreamMalformed(), UpstreamTooLarge(),
                   UpstreamMisbehaved(), UpstreamAuthError(401), UpstreamAuthError(403),
                   UpstreamHTTPError(500), UpstreamHTTPError(503), UpstreamHTTPError(429),
                   UpstreamHTTPError(302)]
        not_counted = [UpstreamNotFound(404), UpstreamHTTPError(400), UpstreamHTTPError(410),
                       UpstreamHTTPError(422)]
        for e in counted:
            self.assertTrue(counts_toward_breaker(e), repr(e))
        for e in not_counted:
            self.assertFalse(counts_toward_breaker(e), repr(e))


class BreakerUnitTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cb = CircuitBreaker(self.clock, cooloff=60, threshold=3)

    def fail(self):
        self.cb.failure("UpstreamTimeout", self.cb.acquire())

    def test_threshold_of_consecutive_failures(self):
        self.fail()
        self.fail()
        self.assertIsNotNone(self.cb.acquire())            # still closed after two
        self.cb.success(self.cb.acquire())                   # a success resets the run
        self.fail()
        self.fail()
        self.assertIsNotNone(self.cb.acquire())
        self.fail()
        self.assertIsNone(self.cb.acquire())                 # third consecutive opens it
        self.assertEqual(self.cb.snapshot("x").state, "cooling_off")

    def test_half_open_allows_exactly_one_trial(self):
        for _ in range(3):
            self.fail()
        self.clock.advance(61)
        trial = self.cb.acquire()
        self.assertIsNotNone(trial)
        self.assertIsNone(self.cb.acquire())                 # no thundering herd
        self.assertIsNone(self.cb.acquire())
        self.cb.success(trial)
        self.assertIsNotNone(self.cb.acquire())              # closed again

    def test_failed_trial_reopens_for_a_full_cooloff(self):
        for _ in range(3):
            self.fail()
        self.clock.advance(61)
        self.cb.failure("UpstreamTimeout", self.cb.acquire())  # one failure is enough in half-open
        self.assertIsNone(self.cb.acquire())
        self.clock.advance(59)
        self.assertIsNone(self.cb.acquire())
        self.clock.advance(2)
        self.assertIsNotNone(self.cb.acquire())

    def test_neutral_result_releases_the_trial_slot(self):
        for _ in range(3):
            self.fail()
        self.clock.advance(61)
        self.cb.neutral(self.cb.acquire())
        self.assertIsNotNone(self.cb.acquire())

    def test_stale_results_cannot_change_state(self):
        token = self.cb.acquire()
        self.cb.force_open("HardCap")
        self.cb.success(token)                                # late success from a hung call
        self.assertIsNone(self.cb.acquire())
        self.assertFalse(self.cb.valid(token))
        self.clock.advance(61)
        t2 = self.cb.acquire()
        self.cb.failure("X", token)                           # stale failure is ignored too
        self.cb.success(t2)
        self.assertEqual(self.cb.snapshot("x").state, "ok")


class SharedCircuitAcrossMembersTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.transport = FakeTransport(self.fake)
        self.adapter = JellyfinAdapter(self.transport, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)
        self.b = make_principal("member-b", GROUPS)

    def test_404_drops_the_cached_mapping(self):
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        self.fake.overrides["/UserItems/Resume"] = ("status", 404)
        self.clock.advance(31)                                 # section cache expired, mapping not
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.NOT_LINKED)
        before = self.fake.paths().count("/Users")
        del self.fake.overrides["/UserItems/Resume"]
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.OK)
        self.assertEqual(self.fake.paths().count("/Users"), before + 1)   # mapping re-resolved

    def test_other_4xx_is_per_request_and_uncounted(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 400)
        for _ in range(6):
            self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)
        self.assertNotEqual(self.adapter.health().state, "cooling_off")

    def test_service_wide_failures_open_after_threshold_for_everyone(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 500)
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)
        self.assertIs(self.adapter.continue_items(self.b).state, SectionState.UNAVAILABLE)
        self.assertNotEqual(self.adapter.health().state, "cooling_off")     # two of three
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        n = len(self.fake.requests)
        r = self.adapter.recent_items(self.b)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "cooling_off"))
        self.assertEqual(len(self.fake.requests), n)

    def test_one_members_odd_data_cannot_open_it_while_others_succeed(self):
        self.fake.hostile_resume = load("hostile_resume_b_for_a.json")
        self.fake.hostile_users = {A}
        for _ in range(5):
            self.assertIs(self.adapter.continue_items(self.a).state, SectionState.UNAVAILABLE)
            self.clock.advance(31)                              # let caches expire
            self.assertIs(self.adapter.continue_items(self.b).state, SectionState.OK)   # resets the run
            self.clock.advance(31)
        self.assertNotEqual(self.adapter.health().state, "cooling_off")

    def test_half_open_single_trial_across_members(self):
        self.fake.overrides["/UserItems/Resume"] = ("status", 500)
        for _ in range(3):
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")
        del self.fake.overrides["/UserItems/Resume"]
        self.clock.advance(61)
        held = self.adapter.breaker.acquire()                   # a trial call is in flight
        self.assertIsNotNone(held)
        r = self.adapter.continue_items(self.b)                 # everyone else waits
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "cooling_off"))
        self.adapter.breaker.success(held)
        self.assertIs(self.adapter.continue_items(self.b).state, SectionState.OK)

    def test_unauthorised_service_credential_counts(self):
        self.fake.overrides["/Users"] = ("status", 401)
        for _ in range(3):
            self.adapter.continue_items(self.a)
        self.assertEqual(self.adapter.health().state, "cooling_off")

    def test_total_schema_drift_is_unavailable_counted_and_not_cached(self):
        self.fake.overrides["/UserItems/Resume"] = (
            "body", b'{"Items": [5, "x", null, {"Id": 5}, {"Id": "../../x", "Type": "Movie"}]}')
        r = self.adapter.continue_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMalformed"))
        self.assertEqual(self.adapter.health().last_error_class, "UpstreamMalformed")
        n = self.fake.paths().count("/UserItems/Resume")
        self.adapter.continue_items(self.a)
        self.assertEqual(self.fake.paths().count("/UserItems/Resume"), n + 1)   # nothing was cached
        self.fake.overrides["/Items/Latest"] = ("body", b'[1, 2, "x"]')
        r = self.adapter.recent_items(self.a)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "UpstreamMalformed"))

    def test_legitimately_filtered_listing_is_empty_not_drift(self):
        self.fake.overrides["/Items/Latest"] = (
            "body", b'[{"Id": "aaaa0000000000000000000000000012", "Name": "F", "Type": "Folder"}]')
        self.assertIs(self.adapter.recent_items(self.a).state, SectionState.EMPTY)
        self.fake.overrides["/UserItems/Resume"] = ("body", b'{"Items": []}')
        self.assertIs(self.adapter.continue_items(self.a).state, SectionState.EMPTY)


if __name__ == "__main__":
    unittest.main()
