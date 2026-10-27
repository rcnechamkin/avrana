"""F2 (AVR-503): the bounded queue for section slots. Fifteen members opening Home together must all get their
sections, without letting a hung or failing upstream add queueing latency. No sockets."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import threading
import time
import unittest

from avrana_home import contract
from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.resilience import CallBudget, FakeClock
from tests.fake_jellyfin import FakeJellyfin, FakeTransport


class Queue(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.adapter = JellyfinAdapter(FakeTransport(FakeJellyfin(self.clock)), clock=self.clock)

    def budget(self):
        return CallBudget(self.clock, 2.0)

    def fill(self):
        """Take every service slot, two per member, as eight members would."""
        for i in range(contract.DEFAULT_MAX_IN_FLIGHT):
            self.assertIsNone(self.adapter._acquire_slot(f"filler-{i // 2}", self.budget()))

    def test_a_queued_section_takes_the_next_free_slot(self):
        self.fill()
        threading.Timer(0.1, self.adapter._release_slot, args=("filler-0",)).start()
        t0 = time.monotonic()
        self.assertIsNone(self.adapter._acquire_slot("member-x", self.budget()))
        self.assertLess(time.monotonic() - t0, contract.SECTION_SLOT_WAIT)
        self.assertEqual(self.adapter.in_flight, contract.DEFAULT_MAX_IN_FLIGHT)

    def test_the_wait_is_bounded_then_busy(self):
        self.fill()
        t0 = time.monotonic()
        self.assertEqual(self.adapter._acquire_slot("member-x", self.budget()), "busy")
        waited = time.monotonic() - t0
        self.assertGreaterEqual(waited, contract.SECTION_SLOT_WAIT - 0.05)
        self.assertLess(waited, contract.SECTION_SLOT_WAIT + 0.25)

    def test_never_more_than_half_of_the_calls_own_deadline(self):
        self.fill()
        t0 = time.monotonic()
        self.assertEqual(self.adapter._acquire_slot("member-x", CallBudget(self.clock, 0.2)), "busy")
        self.assertLess(time.monotonic() - t0, 0.1 + 0.2)

    def test_an_open_circuit_refuses_at_once(self):
        self.fill()
        self.adapter.breaker.force_open("UpstreamTimeout")
        t0 = time.monotonic()
        self.assertEqual(self.adapter._acquire_slot("member-x", self.budget()), "busy")
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_the_queue_itself_is_bounded(self):
        self.fill()
        self.adapter._waiting = contract.SECTION_MAX_WAITERS          # as if that many were already queued
        t0 = time.monotonic()
        self.assertEqual(self.adapter._acquire_slot("member-x", self.budget()), "busy")
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_the_per_member_cap_never_waits(self):
        for _ in range(contract.DEFAULT_MAX_IN_FLIGHT_PER_MEMBER):
            self.assertIsNone(self.adapter._acquire_slot("member-x", self.budget()))
        t0 = time.monotonic()
        self.assertEqual(self.adapter._acquire_slot("member-x", self.budget()), "member_busy")
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_fifteen_members_at_once_all_get_a_slot_as_calls_finish(self):
        """Each call holds its slot 50 ms; 30 sections (15 members x 2) through 8 slots all get in."""
        results, lock = [], threading.Lock()
        barrier = threading.Barrier(30)

        def section(member):
            barrier.wait()
            got = self.adapter._acquire_slot(member, self.budget())
            if got is None:
                time.sleep(0.05)
                self.adapter._release_slot(member)
            with lock:
                results.append(got)
        threads = [threading.Thread(target=section, args=(f"m{i // 2}",)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(None), 30, results)
        self.assertEqual(self.adapter.in_flight, 0)
        self.assertEqual(self.adapter._waiting, 0)

    def test_without_a_budget_it_is_the_old_immediate_refusal(self):
        self.fill()
        t0 = time.monotonic()
        self.assertEqual(self.adapter._acquire_slot("member-x"), "busy")
        self.assertLess(time.monotonic() - t0, 0.05)


if __name__ == "__main__":
    unittest.main()
