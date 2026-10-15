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

from avrana_home.resilience import (MAX_TRANSPORT_TIMEOUT, UpstreamTimeout, UrllibTransport, _Abort,
                                    _DeadlineRaw, _DeadlineSocket)
from tests.fake_jellyfin import FakeOpener

PROBE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "slowdrip_probe.py")
DEADLINE = 0.6
MARGIN = 0.4          # every blocking receive is bounded by the time left, so the real overshoot is tens of ms


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
        for bad in (0, -1, float("nan"), float("inf"), float("-inf"), None, "2", True):
            with self.assertRaises(UpstreamTimeout):
                t.request("GET", "/x", None, bad, 100)
        self.assertEqual(opener.seen_headers, [])

    def test_a_huge_finite_timeout_is_capped_not_an_overflow(self):
        seen = []

        class Opener:
            def open(self, req, timeout=None):
                seen.append(timeout)
                return _Resp(b"{}")
        t = UrllibTransport("https://x.invalid", {}, opener=Opener())
        for huge in (1e300, 1e308, 31, 30.0):
            self.assertEqual(t.request("GET", "/x", None, huge, 100).body, b"{}")
        self.assertEqual(seen, [MAX_TRANSPORT_TIMEOUT] * 4)

    def test_a_timer_that_fired_never_yields_a_truncated_success(self):
        class Slow(_Resp):
            def read1(self, n=-1):
                import time
                time.sleep(0.35)                        # past the 0.2 s deadline, then a clean-looking EOF
                return b""

        class Opener:
            def open(self, req, timeout=None):
                return Slow(b"")
        t = UrllibTransport("https://x.invalid", {}, opener=Opener())
        with self.assertRaises(UpstreamTimeout):
            t.request("GET", "/x", None, 0.2, 100)


class _Resp:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read1(self, n=-1):
        out, self._body = self._body, b""
        return out


class FakeSock:
    def __init__(self, chunks=()):
        self.timeouts, self.chunks, self.closed = [], list(chunks), False

    def settimeout(self, t):
        self.timeouts.append(t)

    def recv_into(self, buffer):
        data = self.chunks.pop(0) if self.chunks else b""
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self.closed = True


class EveryReceiveIsBoundedByTheTimeLeft(unittest.TestCase):
    """Deterministic (no sockets, no sleeping): a receive that blocks is bounded by the deadline because the socket
    timeout is set to the time left BEFORE each one, not because a timer interrupts it."""

    def test_the_socket_timeout_is_the_time_left_before_every_receive(self):
        now = [100.0]
        abort = _Abort(deadline=101.0, now=lambda: now[0])
        sock = FakeSock([b"a", b"b", b"c"])
        raw = _DeadlineRaw(sock, abort)
        buf = bytearray(8)
        for expect in (1.0, 0.75, 0.5):
            self.assertEqual(raw.readinto(buf), 1)
            self.assertAlmostEqual(sock.timeouts[-1], expect)
            now[0] += 0.25

    def test_a_passed_deadline_or_a_fired_timer_raises_before_any_receive(self):
        now = [100.0]
        abort = _Abort(deadline=101.0, now=lambda: now[0])
        sock = FakeSock([b"a"])
        raw = _DeadlineRaw(sock, abort)
        now[0] = 101.0
        with self.assertRaises(TimeoutError):
            raw.readinto(bytearray(4))
        now[0] = 100.0
        abort.fired = True
        with self.assertRaises(TimeoutError):
            raw.readinto(bytearray(4))
        self.assertEqual(sock.timeouts, [])

    def test_the_wrapper_keeps_the_socket_open_until_its_readers_are_closed(self):
        sock = FakeSock([b"x"])
        wrapped = _DeadlineSocket(sock, _Abort(deadline=1e12))
        reader = wrapped.makefile("rb")
        wrapped.close()                                 # what urllib does after getresponse()
        self.assertFalse(sock.closed)
        self.assertEqual(reader.read1(4), b"x")
        reader.close()
        self.assertTrue(sock.closed)
        other = FakeSock()
        _DeadlineSocket(other, _Abort(deadline=1e12)).close()
        self.assertTrue(other.closed)


if __name__ == "__main__":
    unittest.main()
