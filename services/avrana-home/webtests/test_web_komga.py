"""Tier B: the Komga "Recently added" section through the HTTP layer, against the mock Komga (loopback,
SYNTHETIC fixtures from tests/fake_komga.py, real UrllibTransport). Komga is off unless
`komga_base_url` is set, and mock mode is the only mode that accepts it.

Members are linked by the adapter's default rule: the Authentik username must equal the Komga login
exactly, so the fixtures' logins (`member-a@synthetic.invalid`, ...) are the usernames here. How real
members are mapped is an open owner decision (ADAPTER-CONTRACT 12.2).
"""
import json
import unittest

from dev.mock_komga import MockKomga

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()


def member(letter, groups="avrana-users|avrana-comics"):
    return [(USER, f"member-{letter}@synthetic.invalid"), (GROUPS, groups)]


A, B, C, D = member("a"), member("b"), member("c"), member("d")
NO_COMICS = member("a", "avrana-users|avrana-videos")
TOKEN = "mock-api-key-not-real"

A_BOOKS = ["Synthetic Comic One", "Synthetic Comic Two", "Synthetic Mature One", "Synthetic Teen One"]
TRACES = ("Comic", "Manga", "Kids One", "Mature", "Teen", "Recently added to Comics", "komga", "SERIES",
          "BOOKAAAA")


class Fixture(unittest.TestCase):
    timeout = 1.5

    @classmethod
    def setUpClass(cls):
        cls.komga = MockKomga(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.komga.stop()

    def setUp(self):
        self.komga.set_mode("ok")
        self.komga.reset()

    def client(self, adapters=None, **kw):
        c = make_client(make_settings(home_sections=True, komga_base_url=self.komga.url,
                                      komga_token=TOKEN, timeout=self.timeout, **kw),
                        adapters=adapters)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    @staticmethod
    def recent(client, headers):
        view = client.get("/home.json", headers=headers).json()
        sec = [s for s in view["sections"] if s["service"] == "komga" and s["section"] == "recent"]
        return sec[0] if sec else None


class RecentComicsTests(Fixture):
    def test_a_comics_member_sees_their_recent_comics_with_the_contract_handoff(self):
        c = self.client()
        r = c.get("/", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertIn("New this week", r.text)
        for title in A_BOOKS:
            self.assertIn(title, r.text)
        sec = self.recent(c, A)
        self.assertEqual("ok", sec["state"])
        for it in sec["items"]:
            self.assertEqual("komga", it["service"])
            self.assertTrue(it["handoff_url"].startswith("https://"))
            self.assertIn(f'href="{it["handoff_url"]}"', r.text)
        # Komga offers no "continue": empty in the JSON, nothing in the HTML
        self.assertNotIn("Continue reading", r.text)

    def test_a_member_without_comics_has_no_trace_in_html_or_json_and_no_call(self):
        c = self.client()
        html = c.get("/", headers=NO_COMICS).text
        raw = c.get("/home.json", headers=NO_COMICS).text
        for token in TRACES:
            self.assertNotIn(token, html, token)
            self.assertNotIn(token, raw, token)
        self.assertEqual([], self.komga.paths())
        self.assertNotIn("komga", [s["service"] for s in json.loads(raw)["sections"]])

    def test_html_for_a_member_without_comics_equals_the_page_with_komga_unconfigured(self):
        other = make_client(make_settings(home_sections=True))
        other.__enter__()
        self.addCleanup(other.__exit__, None, None, None)
        self.assertEqual(other.get("/", headers=NO_COMICS).text, self.client().get("/", headers=NO_COMICS).text)

    def test_an_age_restricted_member_sees_only_allowed_titles(self):
        c = self.client()
        # member-b: allowed up to 12, label "adult" excluded; member-d: 16 and over excluded
        for headers, shown, hidden in (
                (B, ["Synthetic Manga One", "Synthetic Comic Two", "Synthetic Comic One"],
                 ["Synthetic Mature One", "Synthetic Teen One", "Synthetic Kids One"]),
                (D, ["Synthetic Kids One", "Synthetic Manga One", "Synthetic Comic Two"],
                 ["Synthetic Mature One", "Synthetic Teen One"])):
            with self.subTest(member=headers[0][1]):
                html = c.get("/", headers=headers).text
                raw = c.get("/home.json", headers=headers).text
                for title in shown:
                    self.assertIn(title, html)
                for title in hidden:
                    self.assertNotIn(title, html, title)
                    self.assertNotIn(title, raw, title)

    def test_a_label_allow_list_member_sees_only_labelled_titles(self):
        html = self.client().get("/", headers=C).text
        self.assertIn("Synthetic Kids One", html)
        for title in ("Synthetic Comic One", "Synthetic Manga One", "Synthetic Mature One"):
            self.assertNotIn(title, html)

    def test_two_members_never_see_each_others_items(self):
        c = self.client()
        a = {i["title"] for i in self.recent(c, A)["items"]}
        b = {i["title"] for i in self.recent(c, B)["items"]}
        self.assertIn("Synthetic Mature One", a - b)
        self.assertIn("Synthetic Manga One", b - a)
        self.assertFalse(a & {"Synthetic Manga One"})
        # nothing selects another member: not a query, a cookie, nor a spoofed look-alike header
        r = c.get("/home.json?user=member-b%40synthetic.invalid&userId=USERBBBBBBBB2", headers=A + [
            ("cookie", "user=member-b@synthetic.invalid"), ("X-Forwarded-User", "member-b@synthetic.invalid")])
        self.assertIn("Synthetic Mature One", r.text)
        self.assertNotIn("Synthetic Manga One", r.text)

    def test_an_unlinked_member_gets_the_neutral_state_not_anothers_items(self):
        c = self.client()
        r = c.get("/", headers=member("zzz"))
        self.assertEqual(200, r.status_code)
        self.assertIn("Comics are not set up for your account yet.", r.text)
        self.assertNotIn("Synthetic", r.text)


class DegradationTests(Fixture):
    def test_komga_down_shows_the_member_safe_state_while_other_sections_render(self):
        stub = StubAdapter({"member-a@synthetic.invalid": [("a" * 31 + "1", "Stub Film", 0.5)]})
        from avrana_home.adapters.komga import KomgaAdapter
        from avrana_home.resilience import UrllibTransport
        self.komga.set_mode("down")
        komga = KomgaAdapter(UrllibTransport(self.komga.url, {"X-API-Key": TOKEN}), timeout=self.timeout)
        c = self.client(adapters=[stub, komga])
        r = c.get("/", headers=member("a", "avrana-users|avrana-videos|avrana-comics"))
        self.assertEqual(200, r.status_code)
        self.assertIn("Stub Film", r.text)
        self.assertIn("Comics are unavailable right now.", r.text)
        self.assertNotIn("Synthetic Comic", r.text)
        for token in ("127.0.0.1", "Traceback", "refused", "mock"):
            self.assertNotIn(token, r.text)

    def test_other_failure_modes_show_the_same_neutral_state(self):
        for mode in ("500", "malformed", "slow"):
            with self.subTest(mode=mode):
                self.komga.set_mode(mode)
                r = self.client().get("/", headers=A)
                self.assertEqual(200, r.status_code)
                self.assertIn("Comics are unavailable right now.", r.text)
                self.assertNotIn("Synthetic Comic", r.text)


class SettingsTests(unittest.TestCase):
    def test_off_by_default_and_no_adapter_built(self):
        from avrana_home.app.settings import Settings
        self.assertEqual("", Settings().komga_base_url)
        c = make_client(make_settings(home_sections=True))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        self.assertNotIn("komga", [a.service.value for a in c.fastapi_app.state.adapters])

    def test_mock_mode_accepts_only_a_loopback_url_and_never_a_real_token(self):
        from avrana_home.app.settings import Settings, SettingsError
        ok = Settings.from_mapping({"KOMGA_BASE_URL": "http://127.0.0.1:18098"})
        self.assertEqual(TOKEN, ok.komga_token)
        self.assertNotIn(TOKEN, repr(ok))
        for env in ({"KOMGA_BASE_URL": "http://komga.internal:25600"},
                    {"KOMGA_BASE_URL": "http://127.0.0.1:18098", "KOMGA_TOKEN": "x"},
                    {"KOMGA_BASE_URL": "http://127.0.0.1:18098/"}):
            with self.subTest(env=sorted(env)):
                with self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping(env)
                self.assertNotIn("komga.internal", str(cm.exception))

    def test_real_mode_refuses_komga_until_the_owner_decides(self):
        from avrana_home.app.settings import Settings, SettingsError
        real = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
                "JELLYFIN_BASE_URL": "https://jf.example.test", "JELLYFIN_API_KEY": "k"}
        Settings.from_mapping(real)                                     # without Komga it is fine
        for extra in ({"KOMGA_BASE_URL": "https://komga.example.test", "KOMGA_TOKEN": "sentinel-komga"},
                      {"KOMGA_BASE_URL": "https://komga.example.test"}, {"KOMGA_TOKEN": "sentinel-komga"}):
            with self.subTest(extra=sorted(extra)):
                with self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping({**real, **extra})
                self.assertIn("12.2", str(cm.exception))
                self.assertNotIn("sentinel-komga", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
