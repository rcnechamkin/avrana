"""The transport's deadline is TOTAL, not per socket operation: a loopback server that sends one byte per
0.2 s (in the body, in the headers, or nothing at all) must not hold the call, its in-flight slots or the page
past the deadline. The scenario runs in a subprocess because this process has the network guard installed;
the subprocess talks only to a throw-away server on 127.0.0.1."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import json
import subprocess
import unittest

from avrana_home.resilience import FakeClock, UpstreamTimeout, UrllibTransport
from tests.fake_jellyfin import FakeOpener

PROBE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "slowdrip_probe.py")
DEADLINE = 0.6
MARGIN = 0.5          # generous: CI and Windows timers are coarse; per-socket behaviour would take many seconds


class SlowDrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(_os.environ)
        env.pop("PYTHONPATH", None)
        run = subprocess.run([_sys.executable, "-B", PROBE], capture_output=True, text=True, timeout=120, env=env)
        if run.returncode != 0:
            raise AssertionError("probe failed: " + run.stderr[-500:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    def test_a_slow_drip_in_the_body_headers_or_silence_times_out_at_the_deadline(self):
        for mode in ("body", "header", "silent"):
            err, elapsed = self.out[mode]["direct"]
            self.assertEqual(err, "UpstreamTimeout", mode)
            self.assertGreaterEqual(elapsed, DEADLINE - 0.05, mode)
            self.assertLess(elapsed, DEADLINE + MARGIN, mode)          # a per-socket timeout would never fire

    def test_the_section_is_unavailable_with_a_timeout_not_the_gather_hard_cap_and_slots_are_free(self):
        for mode in ("body", "header", "silent"):
            state, reason, elapsed = self.out[mode]["gather"]
            self.assertEqual((state, reason), ("unavailable", "UpstreamTimeout"), mode)
            self.assertLess(elapsed, DEADLINE + MARGIN, mode)
            self.assertEqual(self.out[mode]["in_flight"], 0, mode)
            self.assertEqual(self.out[mode]["by_member"], {}, mode)

    def test_the_timeout_is_counted_toward_the_circuit(self):
        self.assertEqual(self.out["body"]["breaker"], "failing")


class DeadlineRules(unittest.TestCase):
    def test_a_non_positive_or_non_numeric_timeout_is_a_timeout_before_any_io(self):
        opener = FakeOpener(type("F", (), {"handle": lambda *a: self.fail("called")})())
        t = UrllibTransport("https://x.invalid", {}, opener=opener)
        for bad in (0, -1, float("nan"), None, "2", True):
            with self.assertRaises(UpstreamTimeout):
                t.request("GET", "/x", None, bad, 100)
        self.assertEqual(opener.seen_headers, [])


if __name__ == "__main__":
    unittest.main()
