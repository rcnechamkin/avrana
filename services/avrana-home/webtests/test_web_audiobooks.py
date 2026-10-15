"""Tier B: the Audiobookshelf "Continue listening" section through the HTTP layer, against the mock
Jellyfin and the mock Audiobookshelf (both loopback, SYNTHETIC fixtures, real UrllibTransport).

Audiobookshelf is off unless `audiobookshelf_base_url` is set; these tests set it to the loopback mock.
"""
import json
import unittest

from dev.mock_audiobookshelf import MockAudiobookshelf
from dev.mock_jellyfin import MockJellyfin

from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

BOTH_A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")]
BOTH_B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks")]
VIDEO_ONLY = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
LISTENER_ONLY = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-audiobooks")]

A_ONLY_BOOK = "Synthetic Audiobook Two"      # in member-a's progress and library; not member-b's
B_ONLY_BOOK = "Synthetic Audiobook Ten"      # in member-b's progress; not member-a's
A_ONLY_FILM = "Synthetic Film One"
AUDIOBOOK_TRACES = ("Audiobook", "audiobook", "listening", "li_book", "Continue listening")


class Fixture(unittest.TestCase):
    timeout = 0.6

    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.abs = MockAudiobookshelf(slow_seconds=3.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.jf.stop()
        cls.abs.stop()

    def setUp(self):
        self.jf.set_mode("ok")
        self.abs.set_mode("ok")
        self.jf.reset()
        self.abs.reset()

    def client(self, **kw):
        c = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                      audiobookshelf_base_url=self.abs.url,
                                      audiobookshelf_token="mock-api-key-not-real",
                                      timeout=self.timeout, **kw))
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c


class ContinueListeningTests(Fixture):
    def test_a_member_with_both_groups_sees_both_services_continue_items(self):
        r = self.client().get("/", headers=BOTH_A)
        self.assertEqual(200, r.status_code)
        text = r.text
        self.assertIn("Continue watching", text)
        self.assertIn("Continue listening", text)
        self.assertIn(A_ONLY_FILM, text)
        self.assertIn("Synthetic Audiobook One", text)
        self.assertIn(A_ONLY_BOOK, text)
        self.assertIn("left)", text)
        self.assertEqual(["jellyfin", "audiobookshelf"],
                         [s["service"] for s in json.loads(self.client().get("/home.json", headers=BOTH_A).text)["sections"]
                          if s["section"] == "continue"])

    def test_audiobook_items_hand_off_with_the_contract_url_and_service_name(self):
        view = self.client().get("/home.json", headers=BOTH_A).json()
        books = next(s for s in view["sections"] if s["service"] == "audiobookshelf")
        self.assertEqual("ok", books["state"])
        for it in books["items"]:
            self.assertEqual("audiobookshelf", it["service"])
            self.assertEqual("audiobook", it["kind"])
            self.assertTrue(it["handoff_url"].startswith("https://"))
            self.assertIsNone(it["artwork"])       # the adapter offers no artwork
        text = self.client().get("/", headers=BOTH_A).text
        for it in books["items"]:
            self.assertIn(f'href="{it["handoff_url"]}"', text)
        # the adapter offers no "recent" list: the JSON says empty, the HTML renders nothing for it
        recent = next(s for s in view["sections"]
                      if s["service"] == "audiobookshelf" and s["section"] == "recent")
        self.assertEqual(("empty", []), (recent["state"], recent["items"]))
        self.assertNotIn("Recently added to Audiobooks", text)

    def test_a_video_only_member_has_no_audiobook_trace_in_html_or_json_and_no_call(self):
        c = self.client()
        html = c.get("/", headers=VIDEO_ONLY).text
        raw = c.get("/home.json", headers=VIDEO_ONLY).text
        self.assertIn(A_ONLY_FILM, html)
        for token in AUDIOBOOK_TRACES + ("audiobookshelf",):
            self.assertNotIn(token, html, token)
            self.assertNotIn(token, raw, token)
        self.assertEqual([], self.abs.paths())

    def test_html_for_a_video_only_member_matches_the_page_without_audiobookshelf_configured(self):
        other = make_client(make_settings(home_sections=True, jellyfin_base_url=self.jf.url,
                                          timeout=self.timeout))
        other.__enter__()
        self.addCleanup(other.__exit__, None, None, None)
        self.assertEqual(other.get("/", headers=VIDEO_ONLY).text,
                         self.client().get("/", headers=VIDEO_ONLY).text)

    def test_a_listener_without_the_video_group_sees_no_video_trace(self):
        c = self.client()
        html = c.get("/", headers=LISTENER_ONLY).text
        raw = c.get("/home.json", headers=LISTENER_ONLY).text
        self.assertIn("Continue listening", html)
        for token in ("Continue watching", "Synthetic Film", "jellyfin"):
            self.assertNotIn(token, html, token)
            self.assertNotIn(token, raw, token)
        self.assertEqual([], self.jf.paths())

    def test_audiobookshelf_down_keeps_video_items_and_shows_a_member_safe_message(self):
        self.abs.set_mode("down")
        c = self.client()
        r = c.get("/", headers=BOTH_A)
        self.assertEqual(200, r.status_code)
        self.assertIn(A_ONLY_FILM, r.text)
        self.assertIn("Audiobooks are unavailable right now.", r.text)
        self.assertNotIn("Synthetic Audiobook", r.text)
        view = c.get("/home.json", headers=BOTH_A).json()
        by = {(s["service"], s["section"]): s for s in view["sections"]}
        self.assertEqual("ok", by[("jellyfin", "continue")]["state"])
        self.assertEqual("unavailable", by[("audiobookshelf", "continue")]["state"])
        for token in ("127.0.0.1", "Traceback", "refused", "mock"):
            self.assertNotIn(token, r.text)

    def test_other_failure_modes_cost_only_the_audiobook_section(self):
        for mode in ("500", "malformed", "slow"):
            with self.subTest(mode=mode):
                self.abs.set_mode(mode)
                r = self.client().get("/", headers=BOTH_A)
                self.assertEqual(200, r.status_code)
                self.assertIn(A_ONLY_FILM, r.text)
                self.assertIn("Audiobooks are unavailable right now.", r.text)

    def test_two_members_never_see_each_others_items(self):
        c = self.client()
        a = c.get("/", headers=BOTH_A).text
        b = c.get("/", headers=BOTH_B).text
        self.assertIn(A_ONLY_BOOK, a)
        self.assertNotIn(B_ONLY_BOOK, a)
        self.assertIn(B_ONLY_BOOK, b)
        self.assertNotIn(A_ONLY_BOOK, b)
        # the same book carries each member's OWN progress (a: 0.42 of 10h, b: 0.07)
        ja = c.get("/home.json", headers=BOTH_A).json()
        jb = c.get("/home.json", headers=BOTH_B).json()

        def progress(view):
            sec = next(s for s in view["sections"] if s["service"] == "audiobookshelf")
            return {i["id"]: i["progress"]["fraction"] for i in sec["items"]}
        self.assertAlmostEqual(0.42, progress(ja)["audiobookshelf:li_book000001"])
        self.assertAlmostEqual(0.07, progress(jb)["audiobookshelf:li_book000001"])
        self.assertNotIn("audiobookshelf:li_book000010", progress(ja))
        self.assertNotIn("audiobookshelf:li_book000002", progress(jb))

    def test_query_and_cookie_cannot_select_another_member(self):
        c = self.client()
        r = c.get("/home.json?userId=bbbbbbbb-2222-4bbb-8bbb-bbbbbbbbbbbb&user=member-b",
                  headers=BOTH_A + [("cookie", "user=member-b")])
        self.assertNotIn(B_ONLY_BOOK, r.text)
        self.assertIn(A_ONLY_BOOK, r.text)


class SettingsTests(unittest.TestCase):
    def test_off_by_default_and_no_adapter_built(self):
        from avrana_home.app.settings import Settings
        s = Settings()
        self.assertEqual("", s.audiobookshelf_base_url)
        client = make_client(make_settings(home_sections=True))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(["jellyfin"], [a.service.value for a in client.fastapi_app.state.adapters])

    def test_mock_mode_accepts_only_a_loopback_url_and_never_a_real_token(self):
        from avrana_home.app.settings import Settings, SettingsError
        base = {"HOME_UPSTREAM_MODE": "mock"}
        ok = Settings.from_mapping({**base, "AUDIOBOOKSHELF_BASE_URL": "http://127.0.0.1:18097"})
        self.assertEqual("mock-api-key-not-real", ok.audiobookshelf_token)
        self.assertNotIn("mock-api-key", repr(ok))
        for env in ({"AUDIOBOOKSHELF_BASE_URL": "http://abs.internal:13378"},
                    {"AUDIOBOOKSHELF_BASE_URL": "http://127.0.0.1:18097",
                     "AUDIOBOOKSHELF_TOKEN": "sentinel-token-must-not-echo"},
                    {"AUDIOBOOKSHELF_BASE_URL": "http://127.0.0.1:18097/"}):
            with self.subTest(env=sorted(env)):
                with self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping({**base, **env})
                self.assertNotIn("abs.internal", str(cm.exception))
                self.assertNotIn("sentinel-token", str(cm.exception))   # review of #38: never echo the token

    def test_real_mode_needs_url_and_token_together_and_the_gates(self):
        from avrana_home.app.settings import Settings, SettingsError
        real = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
                "JELLYFIN_BASE_URL": "https://jf.example.test", "JELLYFIN_API_KEY": "k"}
        Settings.from_mapping(real)                                   # Audiobookshelf stays off
        with self.assertRaises(SettingsError):
            Settings.from_mapping({**real, "AUDIOBOOKSHELF_BASE_URL": "https://abs.example.test"})
        with self.assertRaises(SettingsError):
            Settings.from_mapping({**real, "AUDIOBOOKSHELF_TOKEN": "t"})
        both = Settings.from_mapping({**real, "AUDIOBOOKSHELF_BASE_URL": "https://abs.example.test",
                                      "AUDIOBOOKSHELF_TOKEN": "sentinel-token"})
        self.assertNotIn("sentinel-token", repr(both))
        with self.assertRaises(SettingsError):
            Settings.from_mapping({k: v for k, v in real.items() if k != "HOME_GATES_VERIFIED"}
                                  | {"AUDIOBOOKSHELF_BASE_URL": "https://abs.example.test",
                                     "AUDIOBOOKSHELF_TOKEN": "t"})


if __name__ == "__main__":
    unittest.main()
