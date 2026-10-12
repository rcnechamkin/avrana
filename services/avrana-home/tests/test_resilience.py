import io
import logging
import unittest
import urllib.error

from avrana_home.contract import SectionState, Service
from avrana_home.resilience import (CallBudget, CircuitBreaker, FakeClock, UpstreamAuthError,
                                    UpstreamNotFound, UpstreamTimeout, UrllibTransport,
                                    classify_status)
from tests.helpers import FakeAdapter, make_principal


class CircuitTests(unittest.TestCase):
    def test_opens_after_failure_and_recovers_after_cooloff(self):
        clock = FakeClock()
        cb = CircuitBreaker(clock, cooloff=60)
        self.assertTrue(cb.allow())
        cb.record_failure("UpstreamTimeout")
        self.assertFalse(cb.allow())
        self.assertEqual(cb.snapshot("jellyfin").state, "cooling_off")
        clock.advance(59)
        self.assertFalse(cb.allow())
        clock.advance(2)
        self.assertTrue(cb.allow())
        cb.record_success()
        self.assertEqual(cb.snapshot("jellyfin").state, "ok")

    def test_trial_failure_reopens(self):
        clock = FakeClock()
        cb = CircuitBreaker(clock, cooloff=60)
        cb.record_failure("X")
        clock.advance(61)
        self.assertTrue(cb.allow())
        cb.record_failure("X")
        self.assertFalse(cb.allow())

    def test_budget_exhaustion_raises_timeout(self):
        clock = FakeClock()
        b = CallBudget(clock, 2.0)
        self.assertAlmostEqual(b.remaining(), 2.0)
        clock.advance(2.5)
        with self.assertRaises(UpstreamTimeout):
            b.remaining()


class AdapterResilienceTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.adapter = FakeAdapter(Service.JELLYFIN, {"member-a": "1"}, self.clock, mode="timeout")
        self.p = make_principal("member-a")

    def test_failure_is_unavailable_with_no_retry_and_cooloff(self):
        r = self.adapter.continue_items(self.p)
        self.assertIs(r.state, SectionState.UNAVAILABLE)
        self.assertEqual(self.adapter.calls, 1)              # exactly one attempt: no retry
        for _ in range(5):                                    # cooling off: zero upstream traffic
            r = self.adapter.recent_items(self.p)
            self.assertIs(r.state, SectionState.UNAVAILABLE)
        self.assertEqual(self.adapter.calls, 1)
        self.clock.advance(61)
        self.adapter.mode = "ok"
        self.assertIs(self.adapter.continue_items(self.p).state, SectionState.OK)
        self.assertEqual(self.adapter.health().state, "ok")

    def test_failures_never_cached(self):
        self.adapter.continue_items(self.p)
        self.clock.advance(61)
        self.adapter.mode = "ok"
        self.assertIs(self.adapter.continue_items(self.p).state, SectionState.OK)

    def test_logs_carry_service_and_class_only(self):
        with self.assertLogs("avrana_home", level="WARNING") as cm:
            self.adapter.continue_items(self.p)
        text = "\n".join(cm.output)
        self.assertIn("jellyfin", text)
        self.assertIn("UpstreamTimeout", text)
        self.assertNotIn("member-a", text)
        self.assertNotIn("Synthetic", text)

    def test_health_has_no_member_data(self):
        self.adapter.continue_items(self.p)
        h = self.adapter.health().to_dict()
        self.assertEqual(sorted(h), ["last_error_class", "retry_in_seconds", "service", "state"])
        self.assertEqual(h["state"], "cooling_off")
        self.assertNotIn("member", repr(h))


class StatusTests(unittest.TestCase):
    def test_classify(self):
        self.assertIsInstance(classify_status(401), UpstreamAuthError)
        self.assertIsInstance(classify_status(403), UpstreamAuthError)
        self.assertIsInstance(classify_status(404), UpstreamNotFound)
        self.assertEqual(classify_status(500).status, 500)


class FakeResp(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.requests = resp, exc, []

    def open(self, req, timeout=None):
        self.requests.append((req.get_method(), req.full_url, timeout, dict(req.header_items())))
        if self.exc:
            raise self.exc
        return self.resp


class UrllibTransportTests(unittest.TestCase):
    """The real transport is exercised only through an injected fake opener: no sockets."""

    def make(self, opener):
        return UrllibTransport("http://upstream.invalid", {"Authorization": "test-synthetic"}, opener)

    def test_request_and_repr_hide_credential(self):
        op = FakeOpener(FakeResp(b"[]"))
        t = self.make(op)
        r = t.request("GET", "/Users", {"a": "1"}, 2.0, 1000)
        self.assertEqual(r.body, b"[]")
        self.assertEqual(op.requests[0][1], "http://upstream.invalid/Users?a=1")
        self.assertEqual(op.requests[0][2], 2.0)
        self.assertNotIn("test-synthetic", repr(t))

    def test_oversized_body(self):
        from avrana_home.resilience import UpstreamTooLarge
        with self.assertRaises(UpstreamTooLarge):
            self.make(FakeOpener(FakeResp(b"x" * 11))).request("GET", "/x", None, 2.0, 10)

    def test_error_mapping(self):
        from avrana_home.resilience import UpstreamUnreachable
        http = urllib.error.HTTPError("http://u", 403, "no", {}, None)
        with self.assertRaises(UpstreamAuthError):
            self.make(FakeOpener(exc=http)).request("GET", "/x", None, 2.0, 10)
        with self.assertRaises(UpstreamTimeout):
            self.make(FakeOpener(exc=TimeoutError())).request("GET", "/x", None, 2.0, 10)
        with self.assertRaises(UpstreamUnreachable):
            self.make(FakeOpener(exc=urllib.error.URLError("x"))).request("GET", "/x", None, 2.0, 10)

    def test_bad_base_url(self):
        with self.assertRaises(ValueError):
            UrllibTransport("ftp://x", {})
        with self.assertRaises(ValueError):
            UrllibTransport("http://x/", {})


if __name__ == "__main__":
    unittest.main()
