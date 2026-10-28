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
    timeout = 1.5

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


class CoverTests(Fixture):
    """`/art/audiobookshelf/cover/<id>`: re-checked against the member's own Audiobookshelf rights."""

    def test_a_member_gets_the_cover_of_a_book_they_may_see_with_safe_headers(self):
        self.abs.synthetic_covers = False         # the fake's own JPEG: this test is about the JPEG path
        self.addCleanup(setattr, self.abs, "synthetic_covers", True)
        r = self.client().get("/art/audiobookshelf/cover/li_book000001", headers=BOTH_A)
        self.assertEqual(200, r.status_code)
        self.assertEqual("image/jpeg", r.headers["content-type"])
        self.assertTrue(r.content.startswith(b"\xff\xd8\xff"))
        self.assertEqual("private, no-cache", r.headers["cache-control"])
        self.assertEqual("nosniff", r.headers["x-content-type-options"])
        self.assertIn("/api/items/li_book000001/cover", self.abs.paths())

    def test_pages_embed_the_cover_and_keep_the_letter_for_a_book_without_one(self):
        html = self.client().get("/", headers=BOTH_A).text
        self.assertIn('src="/art/audiobookshelf/cover/li_book000001"', html)
        self.assertNotIn("/art/audiobookshelf/cover/li_book000002", html)    # coverPath null: letter only

    def test_a_book_this_member_may_not_see_is_the_standard_404_without_a_cover_call(self):
        c = self.client()
        nf = c.get("/definitely-not-a-route", headers=BOTH_A).text
        for path in ("/art/audiobookshelf/cover/li_book000003",      # a library member-a may not access
                     "/art/audiobookshelf/cover/li_book000004",      # explicit
                     "/art/audiobookshelf/cover/li_book999999",      # unknown
                     "/art/audiobookshelf/cover/li_book000002"):     # no cover
            r = c.get(path, headers=BOTH_A)
            self.assertEqual((404, nf), (r.status_code, r.text), path)
        self.assertFalse([p for p in self.abs.paths() if p.endswith("/cover")])
        self.assertEqual(200, c.get("/art/audiobookshelf/cover/li_book000003", headers=BOTH_B).status_code)

    def test_without_the_group_a_404_and_no_upstream_call(self):
        r = self.client().get("/art/audiobookshelf/cover/li_book000001", headers=VIDEO_ONLY)
        self.assertEqual(404, r.status_code)
        self.assertEqual([], self.abs.paths())


class ContinueListeningTests(Fixture):
    def test_a_member_with_both_groups_sees_both_services_continue_items(self):
        r = self.client().get("/", headers=BOTH_A)
        self.assertEqual(200, r.status_code)
        text = r.text
        self.assertIn("Continue", text)
        self.assertIn(A_ONLY_FILM, text)
        self.assertIn("Synthetic Audiobook One", text)
        self.assertIn(A_ONLY_BOOK, text)
        self.assertIn(" left", text)
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
            art = it["artwork"]                    # a cover ref, or none when the item says it has no cover
            if art is not None:
                self.assertEqual(it["id"].replace("audiobookshelf:", "audiobookshelf/cover/"), art["ref"])
        self.assertTrue(any(it["artwork"] for it in books["items"]))
        self.assertTrue(any(it["artwork"] is None for it in books["items"]))
        text = self.client().get("/", headers=BOTH_A).text
        for it in books["items"]:
            self.assertIn(f'href="{it["handoff_url"]}"', text)
        # the adapter declares "recent" not offered (AVR-385): gather does not request it, so the member view
        # has no audiobookshelf recent entry at all, and the HTML renders nothing for it
        self.assertEqual([], [s for s in view["sections"]
                              if s["service"] == "audiobookshelf" and s["section"] == "recent"])
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
        self.assertIn("Continue", html)
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
        self.assertIn(B_ONLY_BOOK, c.get("/home.json", headers=BOTH_B).text)   # the page rail is bounded to four
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
        both = Settings.from_mapping({**real, **JWT_REQUIRED, "AUDIOBOOKSHELF_BASE_URL": "https://abs.example.test",
                                      "AUDIOBOOKSHELF_TOKEN": "sentinel-token"})
        self.assertNotIn("sentinel-token", repr(both))
        with self.assertRaises(SettingsError):
            Settings.from_mapping({k: v for k, v in real.items() if k != "HOME_GATES_VERIFIED"}
                                  | {"AUDIOBOOKSHELF_BASE_URL": "https://abs.example.test",
                                     "AUDIOBOOKSHELF_TOKEN": "t"})


    def test_the_admin_token_in_real_mode_needs_verified_identity(self):
        # Independent ABS admin-token review 2026-10-27 (HIGH): the token reads every member's progress, so a
        # forged plain header must never reach it. Real mode accepts it only with HOME_IDENTITY_MODE=jwt_required.
        from avrana_home.app.settings import Settings, SettingsError
        real = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
                "JELLYFIN_BASE_URL": "https://jf.example.test", "JELLYFIN_API_KEY": "k",
                "AUDIOBOOKSHELF_BASE_URL": "https://abs.example.test", "AUDIOBOOKSHELF_TOKEN": "sentinel-token"}
        jwt = {k: v for k, v in JWT_REQUIRED.items() if k != "HOME_IDENTITY_MODE"}
        for env in ({}, {"HOME_IDENTITY_MODE": "headers"}, {**jwt, "HOME_IDENTITY_MODE": "jwt_log_only"}):
            with self.subTest(mode=env.get("HOME_IDENTITY_MODE", "default")):
                with self.assertRaises(SettingsError) as cm:
                    Settings.from_mapping({**real, **env})
                self.assertIn("jwt_required", str(cm.exception))
                self.assertNotIn("sentinel-token", str(cm.exception))
        ok = Settings.from_mapping({**real, **JWT_REQUIRED})
        self.assertEqual("jwt_required", ok.identity_mode)
        # Without Audiobookshelf nothing changes: real mode with headers keeps today's behaviour.
        Settings.from_mapping({k: v for k, v in real.items() if not k.startswith("AUDIOBOOKSHELF_")})
        # Mock mode is synthetic data: unaffected.
        Settings.from_mapping({"HOME_UPSTREAM_MODE": "mock", "AUDIOBOOKSHELF_BASE_URL": "http://127.0.0.1:18097"})


JWT_REQUIRED = {"HOME_IDENTITY_MODE": "jwt_required", "HOME_JWT_ISSUER": "https://auth.example.test/application/o/t/",
                "HOME_JWT_AUDIENCE": "t", "HOME_JWT_SECRET": "x" * 48}


if __name__ == "__main__":
    unittest.main()
