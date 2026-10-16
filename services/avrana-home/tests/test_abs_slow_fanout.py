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
from tests.fake_abs import UA, FakeAudiobookshelf
from tests.fake_jellyfin import FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-audiobooks")


class SlowTransport(FakeTransport):
    """Every call takes `delay` seconds of fake time; a call whose timeout is shorter than that times out
    after the timeout, as a real socket read would."""

    timed_out = 0

    def __init__(self, fake, clock, delay):
        super().__init__(fake)
        self.clock, self.delay = clock, delay

    def request(self, method, path, query, timeout, max_bytes):
        if self.delay > timeout:
            self.clock.advance(timeout)
            self.calls += 1
            SlowTransport.timed_out += 1
            raise UpstreamTimeout()
        self.clock.advance(self.delay)
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
        """At 450 ms a call, member-a's two newest entries are books she may not see, so the budget runs out
        before anything visible is found: UNAVAILABLE for her (never "empty"), and never counted."""
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
