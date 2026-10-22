"""AVR-503 benchmark defect F1: Audiobookshelf Continue makes one item lookup per progress entry, one after
another, inside one 2 s request budget. At 200 ms per upstream call that used to run out of budget every time,
and the timeout counted toward the circuit shared by every member, so a merely slow Audiobookshelf went dark for
search and covers too. SYNTHETIC fixtures, a fake clock, no sockets.
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import unittest

from avrana_home.adapters.audiobookshelf import AudiobookshelfAdapter
from avrana_home.contract import SectionState
from avrana_home.resilience import (CircuitBreaker, FakeClock, FanOutSpent, REQUEST_BUDGET, UpstreamTimeout,
                                    counts_toward_breaker)
from tests.fake_abs import UA, UB, FakeAudiobookshelf
from tests.fake_jellyfin import FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-audiobooks")


class SlowTransport(FakeTransport):
    """Every call takes `delay` seconds of fake time; a call whose timeout is shorter than that times out
    after the timeout, as a real socket read would."""

    timed_out = 0

    def __init__(self, fake, clock, delay):
        super().__init__(fake)
        self.clock = clock
        self.delay = delay if callable(delay) else (lambda _path: delay)   # seconds, or path -> seconds

    def request(self, method, path, query, timeout, max_bytes):
        delay = self.delay(path)
        if delay > timeout:
            self.clock.advance(timeout)
            self.calls += 1
            SlowTransport.timed_out += 1
            raise UpstreamTimeout()
        self.clock.advance(delay)
        return super().request(method, path, query, timeout, max_bytes)


class SlowFanOut(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeAudiobookshelf(self.clock)
        self.breaker = CircuitBreaker(self.clock)
        self.a = make_principal("member-a", GROUPS)

    def adapter(self, delay):
        """A fresh adapter (cold cache) sharing the one circuit, as every request of one process does."""
        return AudiobookshelfAdapter(SlowTransport(self.fake, self.clock, delay), clock=self.clock,
                                     breaker=self.breaker)

    def test_200ms_per_call_answers_within_budget_and_never_trips_the_circuit(self):
        for _ in range(6):                                # more requests than the breaker threshold
            start = self.clock.now()
            r = self.adapter(0.2).continue_items(self.a, limit=12)
            self.assertIs(SectionState.OK, r.state)
            self.assertTrue(r.items)
            self.assertLessEqual(self.clock.now() - start, REQUEST_BUDGET)
        self.assertEqual("ok", self.breaker_state())
        # search and covers stay available
        self.assertIs(SectionState.OK, self.adapter(0.2).search(self.a, "Synthetic").state)
        art = self.adapter(0.2).fetch_artwork(self.a, "audiobookshelf/cover/li_book000001")
        self.assertIs(SectionState.OK, art.state)

    def breaker_state(self):
        return self.adapter(0.2).health().state

    def test_when_the_budget_runs_short_continue_stops_and_the_circuit_stays_closed(self):
        """At 450 ms a call, member-a's two newest entries are books she may not see (both answer 200), so the
        budget runs out before anything visible is found: UNAVAILABLE for her (never "empty"), never counted."""
        for _ in range(6):
            r = self.adapter(0.45).continue_items(self.a, limit=12)
            self.assertIn((r.state, r.reason), ((SectionState.UNAVAILABLE, "FanOutSpent"), (SectionState.OK, None)))
        self.assertNotIn(self.breaker_state(), ("cooling_off", "failing"))
        self.assertIs(SectionState.OK, self.adapter(0.2).fetch_artwork(self.a, "audiobookshelf/cover/li_book000001").state)

    def test_no_lookup_is_started_that_cannot_finish(self):
        SlowTransport.timed_out = 0
        for delay in (0.2, 0.3):
            self.adapter(delay).continue_items(self.a, limit=12)
        self.assertEqual(0, SlowTransport.timed_out)

    def test_items_found_before_the_budget_runs_short_are_shown(self):
        rec = self.fake.record(UA)
        visible = [e for e in rec["mediaProgress"] if e["libraryItemId"] in ("li_book000001", "li_book000002")]
        rec["mediaProgress"] = [dict(e, lastUpdate=2 * 10 ** 12 + i) for i, e in enumerate(visible)] + rec["mediaProgress"]
        self.fake.serve(f"/api/users/{UA}", rec)
        r = self.adapter(0.45).continue_items(self.a, limit=12)
        self.assertIs(SectionState.OK, r.state)
        self.assertEqual(2, len(r.items))
        self.assertNotIn(self.breaker_state(), ("cooling_off", "failing"))

    def test_case_c_a_fast_404_then_hanging_lookups_still_opens_the_circuit(self):
        """A stale progress entry for a deleted book answers 404 at once; every real lookup after it hangs. A 404
        is not evidence that the item route works, so the hang counts and the circuit opens."""
        rec = self.fake.record(UA)
        gone = dict(rec["mediaProgress"][0], libraryItemId="li_gone000001", lastUpdate=2 * 10 ** 12)
        rec["mediaProgress"] = [gone] + rec["mediaProgress"]
        self.fake.serve(f"/api/users/{UA}", rec)
        delay = lambda path: (0.01 if not path.startswith("/api/items/") or "li_gone" in path else 30.0)  # noqa: E731
        for _ in range(3):
            r = self.adapter(delay).continue_items(self.a, limit=12)
            self.assertEqual((SectionState.UNAVAILABLE, "UpstreamTimeout"), (r.state, r.reason))
        self.assertEqual("cooling_off", self.breaker_state())

    def test_case_b_a_slow_user_record_counts_instead_of_hiding_as_fan_out(self):
        delay = lambda path: 1.65 if path == f"/api/users/{UA}" else 0.01   # noqa: E731
        for _ in range(3):
            r = self.adapter(delay).continue_items(self.a, limit=12)
            self.assertEqual((SectionState.UNAVAILABLE, "UpstreamTimeout"), (r.state, r.reason))
        self.assertEqual("cooling_off", self.breaker_state())

    def test_a_truncated_list_is_cached_only_briefly(self):
        from avrana_home.contract import TRUNCATED, TRUNCATED_TTL
        rec = self.fake.record(UA)
        visible = [e for e in rec["mediaProgress"] if e["libraryItemId"] in ("li_book000001", "li_book000002")]
        rec["mediaProgress"] = [dict(e, lastUpdate=2 * 10 ** 12 + i) for i, e in enumerate(visible)] + rec["mediaProgress"]
        self.fake.serve(f"/api/users/{UA}", rec)
        adapter = self.adapter(0.45)
        r = adapter.continue_items(self.a, limit=12)
        self.assertEqual((SectionState.OK, TRUNCATED), (r.state, r.reason))
        n = len(self.fake.paths())
        adapter.continue_items(self.a, limit=12)
        self.assertEqual(n, len(self.fake.paths()))          # served from the cache within the short TTL
        self.clock.advance(TRUNCATED_TTL + 0.1)
        adapter.continue_items(self.a, limit=12)
        self.assertGreater(len(self.fake.paths()), n)        # ... and refetched soon after, not 30 s later

    def test_d2_an_answered_but_invisible_entry_then_a_hang_still_counts(self):
        """member-a's newest entry answers 200 but is a book she may not see; every later lookup hangs. Those
        lookups had well over 2 x LOOKUP_RESERVE to answer, so the hang counts and the circuit opens."""
        delay = lambda path: (30.0 if path.startswith("/api/items/") and "li_book000003" not in path  # noqa: E731
                              else 0.01)
        for _ in range(3):
            r = self.adapter(delay).continue_items(self.a, limit=12)
            self.assertEqual((SectionState.UNAVAILABLE, "UpstreamTimeout"), (r.state, r.reason))
        self.assertEqual("cooling_off", self.breaker_state())

    def test_d1_truncated_lists_neither_reset_nor_extend_the_shared_failure_run(self):
        """member-a's newest entry is visible and answers, later lookups hang: she gets a short list each time.
        member-b's user record is too slow: a counted timeout each time. Interleaved, a's partial lists must
        not reset the run, so b's three timeouts still open the circuit for everyone."""
        from avrana_home.contract import TRUNCATED
        rec = self.fake.record(UA)
        first = next(e for e in rec["mediaProgress"] if e["libraryItemId"] == "li_book000001")
        rec["mediaProgress"] = [dict(first, lastUpdate=2 * 10 ** 12)] + rec["mediaProgress"]
        self.fake.serve(f"/api/users/{UA}", rec)
        b = make_principal("member-b", GROUPS)

        def delay(path):
            if path == f"/api/users/{UB}":
                return 1.65
            if path.startswith("/api/items/") and "li_book000001" not in path:
                return 30.0
            return 0.01
        for _ in range(3):
            ra = self.adapter(delay).continue_items(self.a, limit=12)
            self.assertEqual((SectionState.OK, TRUNCATED), (ra.state, ra.reason))
            rb = self.adapter(delay).continue_items(b, limit=12)
            self.assertEqual((SectionState.UNAVAILABLE, "UpstreamTimeout"), (rb.state, rb.reason))
        self.assertEqual("cooling_off", self.breaker_state())

    def test_fan_out_spent_is_unavailable_but_never_counted(self):
        self.assertFalse(counts_toward_breaker(FanOutSpent()))
        self.assertTrue(counts_toward_breaker(UpstreamTimeout()))

    def test_a_really_slow_service_still_counts(self):
        for _ in range(3):
            r = self.adapter(REQUEST_BUDGET + 0.5).continue_items(self.a)
            self.assertIs(SectionState.UNAVAILABLE, r.state)
        self.assertEqual("cooling_off", self.breaker_state())


if __name__ == "__main__":
    unittest.main()
