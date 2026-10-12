"""Hung adapters: bounded concurrency, and a late result cannot change breaker or cache state."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import threading
import time
import unittest

from avrana_home.aggregate import gather
from avrana_home.contract import SectionState, Service
from avrana_home.resilience import FakeClock
from tests.helpers import FakeAdapter, make_principal

GROUPS = ("avrana-users", "avrana-videos")


class HungTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.adapter = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, self.clock, mode="block",
                                   max_in_flight=2)
        self.p = make_principal("member-a", GROUPS)

    def tearDown(self):
        self.adapter.release.set()
        self.wait_idle()

    def wait_idle(self):
        for _ in range(400):
            if self.adapter.in_flight == 0:
                return
            time.sleep(0.005)
        self.fail("worker threads did not finish")

    def test_late_result_cannot_close_the_circuit_or_fill_the_cache(self):
        res = gather(self.p, [self.adapter], hard_cap=0.05)
        self.assertTrue(all(s.reason == "hard_cap" for s in res.sections))
        self.assertEqual(self.adapter.health().state, "cooling_off")
        self.adapter.release.set()                     # the hung calls now finish "successfully"
        self.wait_idle()
        self.assertEqual(self.adapter.health().state, "cooling_off")
        self.assertEqual(len(self.adapter.cache), 0)
        self.clock.advance(61)
        self.adapter.mode = "ok"
        self.assertIs(self.adapter.continue_items(self.p).state, SectionState.OK)

    def test_in_flight_cap_bounds_hung_calls(self):
        before = threading.active_count()
        gather(self.p, [self.adapter], hard_cap=0.05)
        self.assertEqual(self.adapter.in_flight, 2)
        calls = self.adapter.calls
        for _ in range(5):
            self.clock.advance(61)                      # circuit would allow a trial again
            res = gather(self.p, [self.adapter], hard_cap=0.05)
            self.assertTrue(all(s.state is SectionState.UNAVAILABLE for s in res.sections))
            self.assertIn(res.sections[0].reason, ("busy", "hard_cap"))
        self.assertEqual(self.adapter.calls, calls)      # no new upstream work was started
        self.assertEqual(self.adapter.in_flight, 2)
        self.assertLessEqual(threading.active_count() - before, 4)

    def test_busy_is_immediate_without_waiting_for_the_cap(self):
        gather(self.p, [self.adapter], hard_cap=0.05)
        self.clock.advance(61)
        t0 = time.monotonic()
        r = self.adapter.continue_items(self.p)
        self.assertEqual((r.state, r.reason), (SectionState.UNAVAILABLE, "busy"))
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_repeated_gathers_do_not_grow_threads_without_limit(self):
        before = threading.active_count()
        for _ in range(30):
            self.clock.advance(61)
            gather(self.p, [self.adapter], hard_cap=0.01)
        self.assertLessEqual(threading.active_count() - before, 8)


if __name__ == "__main__":
    unittest.main()
