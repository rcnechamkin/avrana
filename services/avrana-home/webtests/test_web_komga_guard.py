"""AVR-782 through the HTTP layer: real mode, the real transport, a mock Komga on loopback (SYNTHETIC fixtures). The
everyday key must be a regular account's, and a bad or unprovable key costs Comics only: Home still starts, stays
healthy and serves every other library. No start-time call to Komga, so start order and a Komga outage cannot
crash-loop Home.
"""
import unittest

from avrana_home.app.main import build_adapters
from avrana_home.cache import MemberCache
from avrana_home.resilience import SystemClock
from dev.mock_komga import MockKomga

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

MEMBER = [(USER, "alice"), (GROUPS, "avrana-users|avrana-comics|avrana-videos")]
TOKEN = "mock-api-key-not-real"
SELF = "/api/v2/users/me"


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.komga = MockKomga(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.komga.stop()

    def setUp(self):
        self.komga.set_mode("ok")
        self.komga.reset()
        self.komga.fake.overrides.clear()
        self.addCleanup(self.komga.fake.overrides.clear)

    def client(self, url=None):
        settings = make_settings(home_sections=True, upstream_mode="real", komga_base_url=url or self.komga.url,
                                 komga_token=TOKEN, komga_owner_confirms=True, timeout=1.5)
        komga = [a for a in build_adapters(settings, MemberCache(SystemClock())) if a.service.value == "komga"]
        other = StubAdapter({"alice": [("a" * 32, "Synthetic Film", None)]})
        c = make_client(settings, adapters=komga + [other])
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def sections(self, client):
        response = client.get("/home.json", headers=MEMBER)
        self.assertEqual(response.status_code, 200)
        return response.json()["sections"]

    @staticmethod
    def state(sections, service, section="recent"):
        return next(s["state"] for s in sections if s["service"] == service and s["section"] == section)

    def assert_comics_only_are_down(self, client):
        sections = self.sections(client)
        self.assertEqual(self.state(sections, "komga"), "unavailable")
        self.assertEqual(self.state(sections, "jellyfin"), "ok")
        self.assertEqual(client.get("/healthz").status_code, 200)

    def test_a_regular_key_passes_and_is_asked_first(self):
        c = self.client()
        self.assertEqual(self.komga.paths(), [])                    # nothing at start
        self.assertEqual(self.state(self.sections(c), "komga"), "ok")
        self.assertEqual(self.komga.paths()[0], SELF)
        self.assertEqual(self.komga.paths().count(SELF), 1)

    def test_an_admin_key_is_refused_and_no_book_is_read(self):
        self.komga.fake.serve(SELF, {"id": "U1", "email": "owner@example.test", "roles": ["ADMIN", "USER"]})
        c = self.client()
        with self.assertLogs("avrana_home", "WARNING") as logs:
            self.assert_comics_only_are_down(c)
        self.assertTrue(any("error=SharedKeyIsAdmin" in line for line in logs.output))
        self.assertEqual(set(self.komga.paths()), {SELF})

    def test_komga_down_at_start_costs_comics_only_and_clears_without_a_restart(self):
        self.komga.set_mode("500")
        c = self.client()
        self.assert_comics_only_are_down(c)
        self.assertEqual(set(self.komga.paths()), {SELF})           # an unproven key reads nothing
        self.komga.set_mode("ok")
        komga = next(a for a in c.fastapi_app.state.adapters if a.service.value == "komga")
        komga.breaker.success(komga.breaker.acquire())
        self.assertEqual(self.state(self.sections(c), "komga"), "ok")

    def test_komga_unreachable_costs_comics_only(self):
        self.assert_comics_only_are_down(self.client("http://127.0.0.1:9"))


if __name__ == "__main__":
    unittest.main()
