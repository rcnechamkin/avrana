"""Tier B: the one-command development stack (mock Jellyfin + app + identity shim) end to end.

Everything is exercised through a real uvicorn server on an ephemeral loopback port, with the real
UrllibTransport talking to the mock over loopback HTTP.
"""
import socket
import unittest

from .support import GROUPS, USER, RealServer, require_framework

require_framework()

from dev import run_dev  # noqa: E402
from dev.dev_identity import DEV_IDENTITIES, DevIdentityRefused  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StartupRefusalTests(unittest.TestCase):
    def test_build_stack_refuses_before_starting_anything(self):
        port = free_port()
        for host, enabled in (("0.0.0.0", True), ("::", True), ("192.0.2.1", True), ("127.0.0.1", False)):
            with self.subTest(host=host, enabled=enabled), self.assertRaises(DevIdentityRefused):
                run_dev.build_stack(host, free_port(), port, enabled)
        with socket.socket() as s:                      # the mock port was never taken
            s.bind(("127.0.0.1", port))

    def test_main_returns_nonzero_and_starts_nothing_without_the_explicit_flag(self):
        self.assertEqual(2, run_dev.main(["--port", str(free_port()), "--mock-port", str(free_port())]))
        self.assertEqual(2, run_dev.main(["--dev-identity", "--host", "0.0.0.0",
                                          "--port", str(free_port()), "--mock-port", str(free_port())]))


class DevStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock, cls.app, cls.settings = run_dev.build_stack("127.0.0.1", free_port(), free_port(), True)
        cls.server = RealServer(cls.app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.set_mode("ok")
        self.mock.reset()

    def page(self, who, path="/"):
        return self.server.get(path, [("X-Dev-Identity", who)] if who else [])

    def test_stack_uses_the_mock_and_the_sections_flag(self):
        self.assertTrue(self.settings.home_sections)
        self.assertEqual("mock", self.settings.upstream_mode)
        self.assertEqual(self.mock.url, self.settings.jellyfin_base_url)

    def test_each_synthetic_member_gets_their_own_page_over_real_http(self):
        a, b = self.page("member-a"), self.page("member-b")
        self.assertEqual((200, 200), (a.status, b.status))
        self.assertIn("Synthetic Film One", a.text)
        self.assertNotIn("Synthetic Film Two", a.text)
        self.assertIn("Synthetic Film Two", b.text)
        self.assertNotIn("Synthetic Film One", b.text)
        self.assertIn("/web/#/details?id=aaaa", a.text)

    def test_scenarios_for_the_design_team(self):
        self.assertIn("are not set up for your account yet", self.page("member-c").text)
        self.assertIn("are not set up for your account yet", self.page("member-d").text)
        nolib = self.page("member-nolib").text
        self.assertNotIn("Movies", nolib)
        self.assertNotIn("<h2", nolib.split("</header>")[1].split("<nav")[0])
        admin = self.page("synthetic-admin").text
        self.assertIn('href="/ops"', admin)

    def test_every_page_carries_the_development_banner(self):
        for who in list(DEV_IDENTITIES) + [None]:
            for path in ("/", "/account", "/help", "/watch", "/nope", "/_dev/identity"):
                r = self.page(who, path)
                if r.status in (307,):
                    continue
                with self.subTest(who=who, path=path):
                    self.assertIn("DEVELOPMENT IDENTITY", r.text)
                    self.assertEqual(str(len(r.body)), r.header("Content-Length"))

    def test_client_supplied_identity_is_never_trusted_through_the_shim(self):
        forged = [(USER, "member-a"), (GROUPS, "authentik Admins"), ("X_authentik_groups", "authentik Admins")]
        r = self.server.get("/", forged)
        self.assertNotIn("Synthetic Film One", r.text)
        self.assertNotIn('href="/ops"', r.text)
        r = self.server.get("/ops", forged)
        self.assertEqual(404, r.status)
        # forged headers cannot widen a selected identity either
        r = self.server.get("/ops", forged + [("X-Dev-Identity", "member-a")])
        self.assertEqual(404, r.status)
        r = self.server.get("/account", forged + [("X-Dev-Identity", "member-a")])
        self.assertIn("<dd>member-a</dd>", r.text)

    def test_cookie_flow_selects_an_identity(self):
        r = self.server.get("/_dev/identity/member-b")
        self.assertEqual(303, r.status)
        cookie = r.header("Set-Cookie").split(";")[0]
        page = self.server.get("/", [("Cookie", cookie)])
        self.assertIn("Synthetic Film Two", page.text)

    def test_failure_mode_degrades_the_section_and_keeps_navigation(self):
        """A fresh stack (cold cache) with the mock down, as `--mode down` would start it."""
        mock, app, _ = run_dev.build_stack("127.0.0.1", free_port(), free_port(), True, mode="down")
        self.addCleanup(mock.stop)
        with RealServer(app) as srv:
            r = srv.get("/", [("X-Dev-Identity", "member-a")])
        self.assertEqual(200, r.status)
        self.assertIn("Movies and TV are unavailable right now.", r.text)
        self.assertIn('href="/help"', r.text)
        self.assertNotIn("Synthetic Film One", r.text)

    def test_hygiene_headers_survive_the_shim(self):
        for path in ("/", "/_dev/identity", "/nope"):
            r = self.page("member-a", path)
            self.assertEqual(["no-store"], r.all("Cache-Control"))
            self.assertEqual(1, len(r.all("Content-Security-Policy")))


if __name__ == "__main__":
    unittest.main()
