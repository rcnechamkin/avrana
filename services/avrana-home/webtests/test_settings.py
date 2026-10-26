"""Tier A: settings validation. The app must refuse to start rather than run half configured."""
import tempfile
import unittest
from pathlib import Path

from avrana_home.app.settings import MOCK_API_KEY, Settings, SettingsError


class SettingsTests(unittest.TestCase):
    def test_defaults_are_the_safe_ones(self):
        s = Settings.from_mapping({})
        self.assertFalse(s.home_sections)
        self.assertEqual("mock", s.upstream_mode)
        self.assertFalse(s.uses_real_upstream)
        self.assertEqual("127.0.0.1", s.host)
        self.assertEqual("loopback", s.health_detail)
        self.assertEqual(MOCK_API_KEY, s.jellyfin_api_key)
        self.assertTrue(s.jellyfin_base_url.startswith("http://127.0.0.1:"))

    def test_booleans(self):
        for raw, want in (("on", True), ("TRUE", True), ("1", True), ("off", False), ("no", False)):
            self.assertEqual(want, Settings.from_mapping({"HOME_SECTIONS": raw}).home_sections)
        with self.assertRaises(SettingsError):
            Settings.from_mapping({"HOME_SECTIONS": "maybe"})

    def test_pwa_kill_switch(self):
        """MK-3 (AVR-717): the service worker is on unless HOME_PWA_SW says off; anything else refuses to start.
        An empty value is 'not set' (the default, on) like every other flag here."""
        self.assertTrue(Settings.from_mapping({}).pwa_sw)
        for raw in ("on", "TRUE", "1", "yes", ""):
            self.assertTrue(Settings.from_mapping({"HOME_PWA_SW": raw}).pwa_sw, raw)
        for raw in ("off", "OFF", "0", "false", "no"):
            self.assertFalse(Settings.from_mapping({"HOME_PWA_SW": raw}).pwa_sw, raw)
        for raw in ("maybe", "disabled", "2"):
            with self.subTest(raw=raw), self.assertRaises(SettingsError) as cm:
                Settings.from_mapping({"HOME_PWA_SW": raw})
            self.assertIn("HOME_PWA_SW", str(cm.exception))
        self.assertFalse(Settings.from_mapping({"HOME_SECTIONS": "on", "HOME_PWA_SW": "off"}).pwa_sw)

    def test_invalid_values_refuse_start_and_name_the_variable(self):
        bad = [{"HOME_UPSTREAM_MODE": "live"}, {"HOME_HEALTH_DETAIL": "all"}, {"LOG_LEVEL": "LOUD"},
               {"HOME_TIMEOUT": "fast"}, {"HOME_TIMEOUT": "0"}, {"HOME_TIMEOUT": "99"},
               {"HOME_SECTION_LIMIT": "0"}, {"HOME_SECTION_LIMIT": "51"}, {"HOME_PORT": "0"},
               {"HOME_PORT": "70000"}, {"HOME_HOST": "a b"},
               {"HOME_CATALOGUE_PATH": "/nonexistent/portal.py"}]
        for env in bad:
            with self.subTest(env=env), self.assertRaises(SettingsError) as cm:
                Settings.from_mapping(env)
            self.assertIn(next(iter(env)), str(cm.exception))

    def test_mock_mode_is_loopback_only_and_never_sends_a_real_key(self):
        for url in ("http://192.0.2.10:8096", "https://jellyfin.example", "http://watch.avrana.net"):
            with self.subTest(url=url), self.assertRaises(SettingsError):
                Settings.from_mapping({"JELLYFIN_BASE_URL": url})
        with self.assertRaises(SettingsError):
            Settings.from_mapping({"JELLYFIN_API_KEY": "not-the-mock-key"})
        ok = Settings.from_mapping({"JELLYFIN_BASE_URL": "http://[::1]:9000"})
        self.assertEqual(MOCK_API_KEY, ok.jellyfin_api_key)

    def test_real_mode_needs_every_explicit_step(self):
        full = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
                "JELLYFIN_BASE_URL": "http://jellyfin.internal:8096", "JELLYFIN_API_KEY": "fake-key-for-test"}
        self.assertTrue(Settings.from_mapping(full).uses_real_upstream)
        for missing in ("HOME_GATES_VERIFIED", "JELLYFIN_BASE_URL", "JELLYFIN_API_KEY"):
            env = {k: v for k, v in full.items() if k != missing}
            with self.subTest(missing=missing), self.assertRaises(SettingsError):
                Settings.from_mapping(env)
        with self.assertRaises(SettingsError):
            Settings.from_mapping(dict(full, HOME_GATES_VERIFIED="true"))

    def test_url_shape(self):
        base = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes", "JELLYFIN_API_KEY": "k-fake"}
        for url in ("ftp://x", "http://" + "someone" + ":" + "fake" + "@x:1", "http://x:1/", "http://x:1?q=1", "http://x:1#f", "x:1", ""):
            with self.subTest(url=url), self.assertRaises(SettingsError):
                Settings.from_mapping(dict(base, JELLYFIN_BASE_URL=url))

    def test_key_from_file_and_only_one_source(self):
        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "jf_key"
            key.write_text("fake-key-from-file\n", encoding="utf-8")
            env = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
                   "JELLYFIN_BASE_URL": "http://jellyfin.internal:8096", "JELLYFIN_API_KEY_FILE": str(key)}
            self.assertEqual("fake-key-from-file", Settings.from_mapping(env).jellyfin_api_key)
            with self.assertRaises(SettingsError):
                Settings.from_mapping(dict(env, JELLYFIN_API_KEY="also-set"))
            with self.assertRaises(SettingsError):
                Settings.from_mapping(dict(env, JELLYFIN_API_KEY_FILE=str(Path(d) / "missing")))

    def test_secret_values_never_appear_in_repr_or_errors(self):
        secret = "fake-key-DO-NOT-LEAK-12345"
        env = {"HOME_UPSTREAM_MODE": "real", "HOME_GATES_VERIFIED": "yes",
               "JELLYFIN_BASE_URL": "http://jellyfin.internal:8096", "JELLYFIN_API_KEY": secret}
        s = Settings.from_mapping(env)
        self.assertNotIn(secret, repr(s))
        self.assertNotIn(secret, str(s))
        with self.assertRaises(SettingsError) as cm:
            Settings.from_mapping(dict(env, HOME_TIMEOUT="nope", HOME_PORT="x"))
        self.assertNotIn(secret, str(cm.exception))
        with self.assertRaises(SettingsError) as cm:
            Settings.from_mapping({"JELLYFIN_API_KEY": secret})      # mock mode refuses a key
        self.assertNotIn(secret, str(cm.exception))

    def test_several_problems_are_reported_together(self):
        with self.assertRaises(SettingsError) as cm:
            Settings.from_mapping({"HOME_TIMEOUT": "x", "LOG_LEVEL": "x"})
        self.assertIn("HOME_TIMEOUT", str(cm.exception))
        self.assertIn("LOG_LEVEL", str(cm.exception))

    def test_no_setting_enables_a_cache_file(self):
        """The cache is in-memory only until the owner decides otherwise (HOME-APP.md)."""
        s = Settings.from_mapping({"HOME_CACHE_PATH": "/tmp/x.db", "CACHE_PATH": "/tmp/y.db"})
        self.assertFalse([f for f in vars(s) if "cache" in f])

    def test_dev_identity_is_not_a_setting(self):
        """The default app has no dev switch to ignore: Settings does not even read it."""
        s = Settings.from_mapping({"HOME_DEV_IDENTITY": "on", "AVRANA_DEV_IDENTITY": "on"})
        self.assertFalse(hasattr(s, "dev_identity"))
        self.assertFalse([f for f in vars(s) if "dev" in f])


if __name__ == "__main__":
    unittest.main()
