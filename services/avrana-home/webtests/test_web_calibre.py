"""Tier B: the Calibre-Web "New to Avrana" section (a SHARED view, ADAPTER-CONTRACT 13.2) through the HTTP
layer, against the mock Calibre-Web (loopback, SYNTHETIC fixture, real UrllibTransport, HTTP Basic)."""
import json
import unittest

from dev.mock_calibre_web import MockCalibreWeb

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

BOOKS = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-books")]
BOOKS_2 = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-books")]
NO_BOOKS = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-comics")]
CRED = "viewer:mock-api-key-not-real"
TITLES = ["Synthetic Book One", "Synthetic Book Two", "Synthetic Book Three"]
TRACES = ("Synthetic Book", "Recently added to Books", "calibre", "Calibre", "books.avrana.net/book/",
          "/art/calibre-web")


class Fixture(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        cls.cw = MockCalibreWeb(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.cw.stop()

    def setUp(self):
        self.cw.set_mode("ok")
        self.cw.reset()

    def client(self, adapters=None, **kw):
        c = make_client(make_settings(home_sections=True, calibre_web_base_url=self.cw.url,
                                      calibre_web_credential=CRED, timeout=self.timeout, **kw),
                        adapters=adapters)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c


class RecentBooksTests(Fixture):
    def test_a_books_member_sees_recent_books_with_contract_handoff_and_covers(self):
        c = self.client()
        r = c.get("/", headers=BOOKS)
        self.assertEqual(200, r.status_code)
        self.assertIn('<h2 id="h-new">New to Avrana</h2>', r.text)     # memo section 4: not date-bounded
        for title in TITLES:
            self.assertIn(title, r.text)
        view = c.get("/home.json", headers=BOOKS).json()
        sec = next(s for s in view["sections"] if s["service"] == "calibre-web" and s["section"] == "recent")
        self.assertEqual("ok", sec["state"])
        for it in sec["items"]:
            self.assertTrue(it["handoff_url"].startswith("https://"))
            self.assertIn(f'href="{it["handoff_url"]}"', r.text)
        self.assertNotIn("Continue reading", r.text)             # per-member read state is not offered
        self.assertIn('<img class="art" src="/art/calibre-web/cover/103" alt=""', r.text)

    def test_every_books_member_sees_the_same_shared_catalogue(self):
        c = self.client()
        self.assertEqual(c.get("/home.json", headers=BOOKS).json(), c.get("/home.json", headers=BOOKS_2).json())

    def test_a_member_without_books_has_no_trace_and_no_upstream_call(self):
        c = self.client()
        html = c.get("/", headers=NO_BOOKS).text
        raw = c.get("/home.json", headers=NO_BOOKS).text
        for token in TRACES:
            self.assertNotIn(token, html, token)
            self.assertNotIn(token, raw, token)
        self.assertEqual([], self.cw.paths())
        self.assertNotIn("calibre-web", [s["service"] for s in json.loads(raw)["sections"]])

    def test_the_page_for_a_member_without_books_equals_the_page_without_calibre_web(self):
        other = make_client(make_settings(home_sections=True))
        other.__enter__()
        self.addCleanup(other.__exit__, None, None, None)
        self.assertEqual(other.get("/", headers=NO_BOOKS).text, self.client().get("/", headers=NO_BOOKS).text)

    def test_calibre_web_down_leaves_other_sections_rendering(self):
        stub = StubAdapter({"member-a": [("a" * 31 + "1", "Stub Film", 0.5)]})
        from avrana_home.adapters.calibre_web import CalibreWebAdapter
        from avrana_home.resilience import UrllibTransport
        self.cw.set_mode("down")
        cw = CalibreWebAdapter(UrllibTransport(self.cw.url, {"Authorization": "Basic x"}),
                               timeout=self.timeout, owner_confirms_no_member_restrictions=True)
        c = self.client(adapters=[stub, cw])
        r = c.get("/", headers=[(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-books")])
        self.assertEqual(200, r.status_code)
        self.assertIn("Stub Film", r.text)
        self.assertIn("Books are unavailable right now.", r.text)
        for token in ("127.0.0.1", "Traceback", "refused", "mock", "Synthetic Book"):
            self.assertNotIn(token, r.text)

    def test_other_failure_modes_show_the_same_neutral_state(self):
        for mode in ("500", "malformed", "slow"):
            with self.subTest(mode=mode):
                self.cw.set_mode(mode)
                r = self.client().get("/", headers=BOOKS)
                self.assertEqual(200, r.status_code)
                self.assertIn("Books are unavailable right now.", r.text)
                self.assertNotIn("Synthetic Book", r.text)


class ArtworkTests(Fixture):
    def test_a_books_member_can_fetch_a_cover_with_the_standard_headers(self):
        r = self.client().get("/art/calibre-web/cover/101", headers=BOOKS)
        self.assertEqual(200, r.status_code)
        self.assertEqual("image/png", r.headers["content-type"])
        self.assertEqual("private, no-cache", r.headers["cache-control"])
        self.assertEqual("nosniff", r.headers["x-content-type-options"])

    def test_the_same_404_rules_apply(self):
        c = self.client()
        standard = c.get("/definitely-not-a-route", headers=BOOKS).text
        for path, headers in (("/art/calibre-web/cover/101", NO_BOOKS),     # no group
                              ("/art/calibre-web/cover/101", []),           # no identity
                              ("/art/calibre-web/cover/999", BOOKS),        # the viewer cannot see it
                              ("/art/calibre-web/cover/1x", BOOKS),         # malformed id
                              ("/art/calibre-web/cover/%2e%2e", BOOKS),
                              ("/art/calibre-web/thumb/101", BOOKS),        # wrong kind
                              ("/art/komga/book/BOOKAAAA0001", BOOKS)):     # another service's ref
            with self.subTest(path=path, member=len(headers)):
                self.cw.reset()
                r = c.get(path, headers=headers)
                self.assertEqual(404, r.status_code)
                self.assertEqual(standard, r.text)
                if headers in ([], NO_BOOKS):
                    self.assertEqual([], self.cw.paths())

    def test_upstream_failure_is_a_plain_404(self):
        for mode in ("down", "500", "malformed", "slow"):
            with self.subTest(mode=mode):
                self.cw.set_mode(mode)
                r = self.client().get("/art/calibre-web/cover/101", headers=BOOKS)
                self.assertEqual(404, r.status_code)
                for token in ("127.0.0.1", "Traceback", "refused"):
                    self.assertNotIn(token, r.text)


class SettingsTests(unittest.TestCase):
    REAL = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
            "JELLYFIN_BASE_URL": "https://jf.example.test", "JELLYFIN_API_KEY": "k",
            "HOME_IDENTITY_MODE": "jwt_required", "HOME_JWT_ISSUER": "https://auth.example.test/application/o/t/", "HOME_JWT_AUDIENCE": "t", "HOME_JWT_SECRET": "x" * 48}
    CW = {"CALIBRE_WEB_BASE_URL": "https://cw.example.test", "CALIBRE_WEB_CREDENTIAL": "viewer:sentinel-cw"}
    OWNER = {"CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "yes"}

    @staticmethod
    def settings(**env):
        from avrana_home.app.settings import Settings
        return Settings.from_mapping(env)

    def test_off_by_default_and_no_adapter_built(self):
        from avrana_home.app.settings import Settings
        s = Settings()
        self.assertEqual(("", False), (s.calibre_web_base_url, s.calibre_web_owner_confirms))
        c = make_client(make_settings(home_sections=True))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        self.assertNotIn("calibre-web", [a.service.value for a in c.fastapi_app.state.adapters])

    def test_mock_mode_accepts_only_a_loopback_url_and_never_a_real_credential(self):
        from avrana_home.app.settings import SettingsError
        ok = self.settings(CALIBRE_WEB_BASE_URL="http://127.0.0.1:18099")
        self.assertTrue(ok.calibre_web_credential.startswith("viewer:"))
        self.assertNotIn("mock-api-key", repr(ok))
        for env in ({"CALIBRE_WEB_BASE_URL": "http://calibre.internal:8083"},
                    {"CALIBRE_WEB_BASE_URL": "http://127.0.0.1:18099", "CALIBRE_WEB_CREDENTIAL": "u:sentinel-cw"}):
            with self.subTest(env=sorted(env)):
                with self.assertRaises(SettingsError) as cm:
                    self.settings(**env)
                self.assertNotIn("sentinel-cw", str(cm.exception))
                self.assertNotIn("calibre.internal", str(cm.exception))

    def test_real_mode_refuses_calibre_web_without_the_owner_setting(self):
        from avrana_home.app.settings import SettingsError
        self.settings(**self.REAL)                                   # without Calibre-Web it is fine
        for extra in (self.CW, {"CALIBRE_WEB_BASE_URL": "https://cw.example.test"},
                      {"CALIBRE_WEB_CREDENTIAL": "viewer:sentinel-cw"},
                      {**self.CW, "CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "no"},
                      {**self.CW, "CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": ""}):
            with self.subTest(extra=sorted(extra)):
                with self.assertRaises(SettingsError) as cm:
                    self.settings(**self.REAL, **extra)
                self.assertIn("13.2", str(cm.exception))
                self.assertNotIn("sentinel-cw", str(cm.exception))

    def test_even_with_the_owner_setting_real_mode_needs_the_gates_and_a_complete_config(self):
        from avrana_home.app.settings import SettingsError
        ok = self.settings(**self.REAL, **self.CW, **self.OWNER)
        self.assertTrue(ok.calibre_web_owner_confirms)
        self.assertNotIn("sentinel-cw", repr(ok))
        ungated = {k: v for k, v in self.REAL.items() if k != "HOME_GATES_VERIFIED"}
        with self.assertRaises(SettingsError):
            self.settings(**ungated, **self.CW, **self.OWNER)
        for partial in ({"CALIBRE_WEB_BASE_URL": "https://cw.example.test"},
                        {"CALIBRE_WEB_CREDENTIAL": "viewer:sentinel-cw"},
                        {**self.CW, "CALIBRE_WEB_CREDENTIAL": "no-colon"}):
            with self.assertRaises(SettingsError):
                self.settings(**self.REAL, **partial, **self.OWNER)
        with self.assertRaises(SettingsError):                       # the setting alone configures nothing
            self.settings(**self.REAL, **self.OWNER)

    def test_the_constructor_gets_true_only_from_mock_mode_or_the_owner_setting(self):
        from avrana_home.app.main import build_adapters
        from avrana_home.cache import MemberCache
        from avrana_home.resilience import SystemClock
        mock = make_settings(home_sections=True, calibre_web_base_url="http://127.0.0.1:1",
                             calibre_web_credential=CRED)
        self.assertIn("calibre-web", [a.service.value for a in build_adapters(mock, MemberCache(SystemClock()))])
        real = make_settings(home_sections=True, upstream_mode="real", calibre_web_base_url="https://cw.test",
                             calibre_web_credential="u:p", calibre_web_owner_confirms=False,
                             jellyfin_base_url="https://jf.test", jellyfin_api_key="k")
        with self.assertRaises(ValueError):                          # not even settings could make this pass
            build_adapters(real, MemberCache(SystemClock()))


if __name__ == "__main__":
    unittest.main()
