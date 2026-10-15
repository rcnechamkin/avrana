"""AVR-385 regression: the transport must not pay a fixed setup cost per request.

Building a urllib opener costs about 25 ms on Windows (proxy discovery, handler scan). The deadline change built
one per request, and an adapter makes several sequential calls inside one 0.6 s section budget, so the web suite
failed intermittently with "unavailable" sections (the last calls of a section ran out of budget). The opener is
built once per transport; the per-request abort travels in a thread-local, so concurrent requests stay separate."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import unittest
import urllib.request
from unittest import mock

from avrana_home.resilience import UrllibTransport


class OpenerBuiltOnce(unittest.TestCase):
    def test_many_requests_build_no_opener(self):
        with mock.patch.object(urllib.request, "build_opener", wraps=urllib.request.build_opener) as build:
            transport = UrllibTransport("http://127.0.0.1:9", {})
            self.assertEqual(1, build.call_count)           # at construction
            for _ in range(5):
                try:
                    transport.request("GET", "/x", None, 0.05, 1024)   # nothing listens: refused, which is fine
                except Exception:
                    pass
            self.assertEqual(1, build.call_count)           # never again

    def test_each_request_gets_its_own_abort_and_the_slot_is_cleared(self):
        transport = UrllibTransport("http://127.0.0.1:9", {})
        seen = []
        real = transport._opener.open

        def spy(req, timeout=None):
            seen.append(transport._slot.abort)
            return real(req, timeout=timeout)
        transport._opener.open = spy
        for _ in range(2):
            try:
                transport.request("GET", "/x", None, 0.05, 1024)
            except Exception:
                pass
        self.assertEqual(2, len(seen))
        self.assertIsNot(seen[0], seen[1])
        self.assertIsNone(transport._slot.abort)


if __name__ == "__main__":
    unittest.main()
