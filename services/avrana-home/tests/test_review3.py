"""App-team additions: health vocabulary, single-flight mapping, display-header cleaning."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import threading
import time
import unittest

from avrana_home.adapters.jellyfin import JellyfinAdapter
from avrana_home.aggregate import gather, health_summary
from avrana_home.contract import SectionState
from avrana_home.principal import principal_from_headers
from avrana_home.resilience import CircuitBreaker, FakeClock, TransportResponse
from tests.fake_jellyfin import FakeJellyfin, FakeTransport
from tests.helpers import make_principal

GROUPS = ("avrana-users", "avrana-videos")


class HealthVocabulary(unittest.TestCase):
    def test_states_closed_failing_open_unknown(self):
        clock = FakeClock()
        cb = CircuitBreaker(clock, threshold=3)
        h = cb.snapshot("jellyfin")
        self.assertEqual((h.state, h.consecutive_failures), ("unknown", 0))
        cb.success(cb.acquire())
        self.assertEqual(cb.snapshot("jellyfin").state, "ok")
        cb.failure("UpstreamTimeout", cb.acquire())
        h = cb.snapshot("jellyfin")
        self.assertEqual((h.state, h.consecutive_failures, h.last_error_class),
                         ("failing", 1, "UpstreamTimeout"))
        cb.failure("UpstreamTimeout", cb.acquire())
        self.assertEqual((cb.snapshot("x").state, cb.snapshot("x").consecutive_failures), ("failing", 2))
        cb.failure("UpstreamTimeout", cb.acquire())
        h = cb.snapshot("x")
        self.assertEqual((h.state, h.consecutive_failures), ("cooling_off", 0))
        self.assertGreaterEqual(h.retry_in_seconds, 1)
        clock.advance(61)
        self.assertEqual(cb.snapshot("x").state, "unknown")
        cb.success(cb.acquire())
        self.assertEqual(cb.snapshot("x").state, "ok")

    def test_a_success_clears_failing(self):
        cb = CircuitBreaker(FakeClock(), threshold=3)
        cb.failure("X", cb.acquire())
        cb.success(cb.acquire())
        h = cb.snapshot("x")
        self.assertEqual((h.state, h.consecutive_failures, h.last_error_class), ("ok", 0, None))

    def test_dict_shape_and_summary(self):
        clock = FakeClock()
        fake = FakeJellyfin(clock)
        ad = JellyfinAdapter(FakeTransport(fake), clock=clock)
        self.assertEqual(health_summary([ad])["libraries"], "ok")
        fake.overrides["/UserItems/Resume"] = ("status", 500)
        ad.continue_items(make_principal("member-a", GROUPS))
        h = health_summary([ad])
        self.assertEqual(h["libraries"], "degraded")                  # early outage is visible
        row = h["adapters"][0]
        self.assertEqual(sorted(row), ["consecutive_failures", "last_error_class", "retry_in_seconds",
                                       "service", "state"])
        self.assertEqual((row["state"], row["consecutive_failures"]), ("failing", 1))


class GatedTransport:
    """Holds the first request to `gate_path` until released, so two sections overlap."""

    def __init__(self, inner, gate_path):
        self.inner, self.gate_path = inner, gate_path
        self.reached = threading.Semaphore(0)
        self.release = threading.Event()
        self.calls = 0

    def request(self, method, path, query, timeout, max_bytes):
        self.calls += 1
        if path == self.gate_path:
            self.reached.release()
            self.release.wait(5)
        return self.inner.request(method, path, query, timeout, max_bytes)


class SingleFlightMapping(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeJellyfin(self.clock)
        self.gated = GatedTransport(FakeTransport(self.fake), "/Users")
        self.adapter = JellyfinAdapter(self.gated, clock=self.clock)
        self.a = make_principal("member-a", GROUPS)

    def run_page(self):
        box = {}

        def page():
            box["res"] = gather(self.a, [self.adapter])
        t = threading.Thread(target=page)
        t.start()
        self.assertTrue(self.gated.reached.acquire(timeout=2))
        for _ in range(400):                       # wait until the second section is in flight too
            if self.adapter.in_flight == 2:
                break
            time.sleep(0.005)
        self.assertEqual(self.adapter.in_flight, 2)
        time.sleep(0.05)                           # let the follower reach the single-flight wait
        self.gated.release.set()
        t.join(5)
        return box["res"]

    def test_one_cold_page_is_one_mapping_call(self):
        res = self.run_page()
        self.assertEqual(self.fake.paths().count("/Users"), 1)
        self.assertTrue(all(s.state is SectionState.OK for s in res.sections))
        self.assertEqual(len(res.sections), 2)

    def test_one_outage_page_counts_one_failure(self):
        self.fake.overrides["/Users"] = ("status", 500)
        res = self.run_page()
        self.assertEqual(self.fake.paths().count("/Users"), 1)
        self.assertTrue(all(s.state is SectionState.UNAVAILABLE for s in res.sections))
        self.assertEqual(self.adapter.health().consecutive_failures, 1)
        self.assertEqual(self.adapter.health().state, "failing")

    def test_unlinked_member_page_is_one_call_and_both_sections_not_linked(self):
        self.a = make_principal("member-z", GROUPS)
        res = self.run_page()
        self.assertEqual(self.fake.paths().count("/Users"), 1)
        self.assertTrue(all(s.state is SectionState.NOT_LINKED for s in res.sections))

    def test_different_members_are_not_serialised_together(self):
        # a second member's mapping is a separate flight: it proceeds while the first is gated
        b = make_principal("member-b", GROUPS)
        t = threading.Thread(target=self.adapter.continue_items, args=(self.a,))
        t.start()
        self.assertTrue(self.gated.reached.acquire(timeout=2))
        done = {}
        t2 = threading.Thread(target=lambda: done.setdefault("r", self.adapter.continue_items(b)))
        t2.start()
        self.assertTrue(self.gated.reached.acquire(timeout=2))      # B reached /Users independently
        self.gated.release.set()
        t.join(5)
        t2.join(5)
        self.assertEqual(self.fake.paths().count("/Users"), 2)
        self.assertIs(done["r"].state, SectionState.OK)


class DisplayHeaders(unittest.TestCase):
    def build(self, **extra):
        h = {"X-authentik-username": "member-a", "X-authentik-groups": "g"}
        h.update(extra)
        return principal_from_headers(h)

    def test_display_values_are_stripped(self):
        p = self.build(**{"X-authentik-name": "  Member A  ", "X-authentik-email": "\tm@example.invalid "})
        self.assertEqual((p.name, p.email), ("Member A", "m@example.invalid"))

    def test_empty_after_strip_or_control_characters_are_dropped(self):
        for bad in ("   ", "", "\t", "a\x00b", "a\nb", "a b", "a b"):
            p = self.build(**{"X-authentik-name": bad, "X-authentik-email": bad})
            self.assertIsNone(p.name, repr(bad))
            self.assertIsNone(p.email, repr(bad))

    def test_length_is_checked_after_strip(self):
        p = self.build(**{"X-authentik-name": " " + "a" * 254 + " "})
        self.assertEqual(len(p.name), 254)
        p = self.build(**{"X-authentik-name": "a" * 255})
        self.assertIsNone(p.name)


if __name__ == "__main__":
    unittest.main()
