"""RC1 finding S1: a username is accepted only as the Authentik user it was first seen as (identity_bindings.py).

Synthetic only: the HS256 secret is a fixture, tokens are minted here, `sub` values are invented. The scenarios are
the ones the S1 investigation found Home exposed to: a member deleted and a NEW Authentik user given the same name
(invitation or administrator rename) inheriting the old member's Jellyfin history, requests and profile. Offline:
loopback only (the mock Jellyfin).
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from avrana_home.app.settings import Settings, SettingsError

from .support import make_client, make_settings, require_framework
from .test_web_jwt_identity import AUD, ISS, JWT, JWT_ENV, SECRET, mint

HOME = Path(__file__).resolve().parents[1]
A1, A2, B1 = "synthetic-sub-member-a", "synthetic-sub-member-a-RECREATED", "synthetic-sub-member-b"
B_GROUPS = ["avrana-users", "avrana-videos"]


class SettingsTests(unittest.TestCase):
    def test_needs_jwt_required_and_an_existing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "identity_bindings.json")
            ok = Settings.from_mapping(dict(JWT_ENV, HOME_IDENTITY_MODE="jwt_required", HOME_IDENTITY_BINDINGS_FILE=path))
            self.assertEqual(path, ok.identity_bindings_file)
            for mode in ("jwt_log_only", None):
                env = dict(JWT_ENV, HOME_IDENTITY_BINDINGS_FILE=path)
                if mode:
                    env["HOME_IDENTITY_MODE"] = mode
                else:
                    env = {"HOME_IDENTITY_BINDINGS_FILE": path}
                with self.subTest(mode=mode), self.assertRaises(SettingsError):
                    Settings.from_mapping(env)
            with self.assertRaises(SettingsError):
                Settings.from_mapping(dict(JWT_ENV, HOME_IDENTITY_MODE="jwt_required",
                                           HOME_IDENTITY_BINDINGS_FILE=os.path.join(tmp, "missing", "b.json")))

    def test_off_by_default(self):
        self.assertEqual("", Settings.from_mapping(dict(JWT_ENV, HOME_IDENTITY_MODE="jwt_required")).identity_bindings_file)


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_framework()
        from dev.mock_jellyfin import MockJellyfin
        cls.mock = MockJellyfin().start()
        cls.base = dict(home_sections=True, jellyfin_base_url=cls.mock.url, timeout=1.0, identity_mode="jwt_required",
                        jwt_issuer=ISS, jwt_audience=AUD, jwt_secret=SECRET)
        cls.unbound = make_client(make_settings(**cls.base))
        cls.unbound.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.unbound.__exit__(None, None, None)
        cls.mock.stop()

    def setUp(self):
        self.mock.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "identity_bindings.json")
        self.client = make_client(make_settings(**self.base, identity_bindings_file=self.path))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.records = []
        test = self

        class Capture(logging.Handler):
            def emit(self, record):
                test.records.append(record)
        log, handler = logging.getLogger("avrana_home.app"), Capture(level=logging.DEBUG)
        old = log.level
        log.setLevel(logging.INFO)
        log.addHandler(handler)
        self.addCleanup(lambda: (log.removeHandler(handler), log.setLevel(old)))

    def as_(self, sub, user="member-a", groups=None):
        claims = {"sub": sub, "preferred_username": user}
        if groups:
            claims["groups"] = groups
        return [(JWT, mint(**claims))]

    def reasons(self):
        return [r.avrana_fields["reason"] for r in self.records if r.msg == "identity_jwt"]

    def test_the_first_sign_in_binds_and_the_member_sees_their_own_home(self):
        r = self.client.get("/home.json", headers=self.as_(A1))
        self.assertEqual(200, r.status_code)
        self.assertEqual(self.unbound.get("/home.json", headers=self.as_(A1)).json(), r.json())
        data = json.loads(Path(self.path).read_text())
        self.assertEqual(["member-a"], list(data))
        self.assertNotIn(A1, Path(self.path).read_text())          # only a digest of the sub is kept
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)   # same user again

    def test_a_recreated_user_with_the_same_name_gets_nothing_of_the_old_members(self):
        self.client.get("/", headers=self.as_(A1))
        self.mock.reset()
        nobody = self.client.get("/").content
        for path in ("/", "/library", "/continue", "/me", "/account", "/search?q=Synthetic"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).content, self.client.get(path, headers=self.as_(A2)).content)
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A2)).status_code)
        self.assertEqual(nobody, self.client.get("/", headers=self.as_(A2)).content)
        self.assertEqual([], self.mock.paths())                    # nothing of member-a's was asked for
        self.assertIn("identity_changed", self.reasons())
        self.assertFalse(any(A2 in repr(vars(r)) or A1 in repr(vars(r)) for r in self.records))
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)   # the real one still

    def test_another_member_is_unaffected(self):
        self.client.get("/", headers=self.as_(A1))
        r = self.client.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS))
        self.assertEqual(200, r.status_code)
        self.assertEqual(self.unbound.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS)).json(), r.json())

    def test_a_token_without_sub_is_refused_when_bindings_are_on(self):
        nobody = self.client.get("/").content
        self.assertEqual(nobody, self.client.get("/", headers=[(JWT, mint(sub=...))]).content)
        self.assertIn("no_subject", self.reasons())
        self.assertEqual(200, self.unbound.get("/home.json", headers=[(JWT, mint(sub=...))]).status_code)  # off: as before

    def test_the_owner_release_lets_the_new_user_bind(self):
        self.client.get("/", headers=self.as_(A1))
        done = subprocess.run([sys.executable, "-B", "-m", "avrana_home.identity_bindings", "--file", self.path,
                               "release", "member-a"], cwd=str(HOME), capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A2)).status_code)
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A1)).status_code)   # now the old one is out

    def test_a_broken_file_refuses_everyone_until_it_is_good_again(self):
        self.client.get("/", headers=self.as_(A1))
        good = Path(self.path).read_text()
        Path(self.path).write_text("{not json")
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(A1)).status_code)
        self.assertEqual(404, self.client.get("/home.json", headers=self.as_(B1, "member-b", B_GROUPS)).status_code)
        self.assertIn("bindings_unavailable", self.reasons())
        Path(self.path).write_text(good)
        self.assertEqual(200, self.client.get("/home.json", headers=self.as_(A1)).status_code)


if __name__ == "__main__":
    unittest.main()
