"""Tier B: the Komga "Recently added" section through the HTTP layer, against the mock Komga (loopback,
SYNTHETIC fixtures from tests/fake_komga.py, real UrllibTransport). Komga is off unless
`komga_base_url` is set, and mock mode is the only mode that accepts it.

Komga is a SHARED regular-account view (ADAPTER-CONTRACT 12.2, owner decision 2026-10-15): there is no
member mapping, so any username that holds the comics group sees what the one shared account sees.
"""
import json
import unittest

from avrana_home.app.viewmodel import RAIL_MOST
from dev.mock_komga import MockKomga

from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()


def member(letter, groups="avrana-users|avrana-comics"):
    return [(USER, f"comics-{letter}"), (GROUPS, groups)]


A, B = member("a"), member("b")
NO_COMICS = member("a", "avrana-users|avrana-videos")
TOKEN = "mock-api-key-not-real"

A_BOOKS = sorted(["Synthetic Comic One", "Synthetic Comic Two", "Synthetic Manga One", "Synthetic Mature One",
                  "Synthetic Kids One", "Synthetic Teen One"])
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
        sec = self.recent(c, A)
        self.assertEqual("ok", sec["state"])
        self.assertEqual(A_BOOKS, sorted(i["title"] for i in sec["items"]))
        for it in sec["items"][:RAIL_MOST]:                  # the page shows one bounded rail
            self.assertIn(it["title"], r.text)
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

    def test_two_members_with_the_comics_group_see_the_same_shared_items(self):
        c = self.client()
        a = [i["id"] for i in self.recent(c, A)["items"]]
        b = [i["id"] for i in self.recent(c, B)["items"]]
        self.assertEqual(6, len(a))
        self.assertEqual(a, b)
        self.assertEqual([i["title"] for i in self.recent(c, A)["items"]],
                         [i["title"] for i in self.recent(c, B)["items"]])
        page_b = c.get("/", headers=B).text
        for title in [i["title"] for i in self.recent(c, A)["items"]][:RAIL_MOST]:
            self.assertIn(title, page_b)

    def test_no_per_member_restriction_and_no_user_listing_reaches_the_upstream(self):
        c = self.client()
        self.recent(c, A)
        self.recent(c, member("zzz"))                      # any username: there is no mapping to fail
        paths = self.komga.paths()
        self.assertTrue(paths)
        self.assertEqual([], [p for p in paths if "/users" in p or "/api/v2" in p])
        self.assertTrue(all(p.startswith("/api/v1/books/") for p in paths))

    def test_nothing_selects_another_identity_and_no_read_progress_is_shown(self):
        c = self.client()
        r = c.get("/home.json?user=comics-b&userId=USERBBBBBBBB2", headers=A + [
            ("cookie", "user=comics-b"), ("X-Forwarded-User", "comics-b")])
        self.assertEqual(200, r.status_code)
        sec = [s for s in r.json()["sections"] if s["service"] == "komga" and s["section"] == "recent"][0]
        self.assertEqual(6, len(sec["items"]))
        for item in sec["items"]:
            self.assertIsNone(item.get("progress"))
        # the fixtures carry the shared account's read progress (page 77); it never appears
        self.assertNotIn("77", json.dumps(sec))
        self.assertNotIn("readProgress", r.text)
        self.assertNotIn("Continue reading", c.get("/", headers=A).text)


class DegradationTests(Fixture):
    def test_komga_down_shows_the_member_safe_state_while_other_sections_render(self):
        stub = StubAdapter({"comics-a": [("a" * 31 + "1", "Stub Film", 0.5)]})
        from avrana_home.adapters.komga import KomgaAdapter
        from avrana_home.resilience import UrllibTransport
        self.komga.set_mode("down")
        komga = KomgaAdapter(UrllibTransport(self.komga.url, {"X-API-Key": TOKEN}), timeout=self.timeout,
                             owner_confirms_no_member_restrictions=True)
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
        self.assertFalse(ok.komga_owner_confirms)               # mock mode states it itself, never from the env
        self.assertNotIn(TOKEN, repr(ok))
        for env in ({"KOMGA_BASE_URL": "http://komga.internal:25600"},
                    {"KOMGA_BASE_URL": "http://127.0.0.1:18098", "KOMGA_TOKEN": "x"},
                    {"KOMGA_BASE_URL": "http://127.0.0.1:18098/"}):
            with self.subTest(env=sorted(env)):
                with self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping(env)
                self.assertNotIn("komga.internal", str(cm.exception))

    REAL = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
            "JELLYFIN_BASE_URL": "https://jf.example.test", "JELLYFIN_API_KEY": "k"}
    KOMGA = {"KOMGA_BASE_URL": "https://komga.example.test", "KOMGA_TOKEN": "sentinel-komga"}
    CONFIRM = {"KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "yes"}

    def test_real_mode_komga_needs_the_confirmation_gates_url_and_key(self):
        from avrana_home.app.settings import Settings, SettingsError
        Settings.from_mapping(self.REAL)                                 # without Komga it is fine
        ok = Settings.from_mapping({**self.REAL, **self.KOMGA, **self.CONFIRM})
        self.assertTrue(ok.komga_owner_confirms)
        self.assertEqual("https://komga.example.test", ok.komga_base_url)
        self.assertNotIn("sentinel-komga", repr(ok))
        for extra, needle in (
                (self.KOMGA, "KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS"),                       # no confirmation
                ({**self.KOMGA, "KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "no"}, "CONFIRMS"),
                ({**self.KOMGA, "KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "maybe"}, "on or off"),
                ({"KOMGA_BASE_URL": "https://komga.example.test", **self.CONFIRM}, "set together"),  # no key
                ({"KOMGA_TOKEN": "sentinel-komga", **self.CONFIRM}, "set together"),                 # no URL
                (self.CONFIRM, "not configured")):                                                   # flag alone
            with self.subTest(extra=sorted(extra)):
                with self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping({**self.REAL, **extra})
                self.assertIn(needle, str(cm.exception))
                self.assertNotIn("sentinel-komga", str(cm.exception))
                self.assertNotIn("komga.example.test", str(cm.exception))

    def test_real_mode_still_needs_the_gates_and_a_clean_url(self):
        from avrana_home.app.settings import Settings, SettingsError
        gates_off = {k: v for k, v in self.REAL.items() if k != "HOME_GATES_VERIFIED"}
        with self.assertRaises(SettingsError) as cm:
            Settings.from_mapping({**gates_off, **self.KOMGA, **self.CONFIRM})
        self.assertIn("HOME_GATES_VERIFIED", str(cm.exception))
        with self.assertRaises(SettingsError):
            Settings.from_mapping({**self.REAL, **self.KOMGA, **self.CONFIRM,
                                   "KOMGA_BASE_URL": "https://komga.example.test/"})

    def test_the_key_can_come_from_a_file_and_not_both(self):
        import os
        import tempfile
        from avrana_home.app.settings import Settings, SettingsError
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "komga-key")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("sentinel-komga-file\n")
            env = {**self.REAL, "KOMGA_BASE_URL": self.KOMGA["KOMGA_BASE_URL"], "KOMGA_TOKEN_FILE": path,
                   **self.CONFIRM}
            self.assertEqual("sentinel-komga-file", Settings.from_mapping(env).komga_token)
            with self.assertRaises(SettingsError):
                Settings.from_mapping({**env, **self.KOMGA})

    def test_mock_mode_builds_the_adapter_without_the_environment_flag(self):
        c = make_client(make_settings(home_sections=True, komga_base_url="http://127.0.0.1:1", komga_token=TOKEN))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        self.assertIn("komga", [a.service.value for a in c.fastapi_app.state.adapters])


if __name__ == "__main__":
    unittest.main()
