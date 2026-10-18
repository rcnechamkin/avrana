"""Tier B: the owner preview (preview/run_preview.py) end to end, in process, against the repository's mock
upstreams on 127.0.0.1 (SYNTHETIC fixtures, real UrllibTransport).

The preview runs in REAL upstream mode here, through the sealed owner-preview settings path and without
HOME_GATES_VERIFIED; the "real" upstreams are the loopback mocks and the keys are the mocks' fixed fake key,
read from temporary *_FILE files. The owner principal (`akadmin`, synthetic) is mapped to the mocks' synthetic
`member-a` by the per-service username overrides, standing in for Jellyfin `Cody` / Audiobookshelf `akadmin`.
Fixture success is not live API compatibility proof.
"""
import base64
import socket
import tempfile
import unittest
from pathlib import Path

from .support import PeerOverride, RealServer, require_framework

require_framework()

from fastapi.testclient import TestClient  # noqa: E402

from avrana_home.app.settings import MOCK_API_KEY, SettingsError  # noqa: E402
from dev.mock_audiobookshelf import MockAudiobookshelf  # noqa: E402
from dev.mock_calibre_web import MockCalibreWeb  # noqa: E402
from dev.mock_jellyfin import MockJellyfin  # noqa: E402
from dev.mock_komga import MockKomga  # noqa: E402
from preview import run_preview  # noqa: E402
from preview.gate import PreviewRefused  # noqa: E402

PASSWORD = "synthetic-preview-pass-0001"            # a test value only
GROUPS = "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books"


def auth(password=PASSWORD, user="ignored"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jf = MockJellyfin(slow_seconds=3.0).start()
        cls.ab = MockAudiobookshelf(slow_seconds=3.0).start()
        cls.kg = MockKomga(slow_seconds=3.0).start()
        cls.cw = MockCalibreWeb(slow_seconds=3.0).start()
        cls.mocks = (cls.jf, cls.ab, cls.kg, cls.cw)
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        files = {"pw": PASSWORD + "\n", "jf": MOCK_API_KEY, "ab": MOCK_API_KEY, "kg": MOCK_API_KEY,
                 "cw": "viewer:" + MOCK_API_KEY, "short": "fifteen-chars-x"}
        for name, value in files.items():
            (d / name).write_bytes(value.encode())
        cls.files = {k: str(d / k) for k in files}

    @classmethod
    def tearDownClass(cls):
        for m in cls.mocks:
            m.stop()
        cls.tmp.cleanup()

    def setUp(self):
        for m in self.mocks:
            m.set_mode("ok")
            m.reset()

    def env(self, **over):
        f = self.files
        env = {"HOME_OWNER_PREVIEW": "yes", "HOME_SECTIONS": "on", "HOME_UPSTREAM_MODE": "real",
               "HOME_TIMEOUT": "1.5", "PREVIEW_PASSWORD_FILE": f["pw"],
               "PREVIEW_OWNER_USERNAME": "akadmin", "PREVIEW_OWNER_GROUPS": GROUPS,
               "HOME_JELLYFIN_USERNAME": "member-a", "HOME_AUDIOBOOKSHELF_USERNAME": "member-a",
               "JELLYFIN_BASE_URL": self.jf.url, "JELLYFIN_API_KEY_FILE": f["jf"],
               "AUDIOBOOKSHELF_BASE_URL": self.ab.url, "AUDIOBOOKSHELF_TOKEN_FILE": f["ab"],
               "KOMGA_BASE_URL": self.kg.url, "KOMGA_TOKEN_FILE": f["kg"],
               "KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "yes",
               "CALIBRE_WEB_BASE_URL": self.cw.url, "CALIBRE_WEB_CREDENTIAL_FILE": f["cw"],
               "CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS": "yes"}
        env.update(over)
        return {k: v for k, v in env.items() if v is not None}

    def client(self, env=None, peer=("192.0.2.10", 50000)):
        _settings, app = run_preview.build_preview_app(env or self.env())
        c = TestClient(PeerOverride(app, peer), base_url="http://10.0.0.218:8197", follow_redirects=False,
                       raise_server_exceptions=False)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def upstream_calls(self):
        return sum(len(m.paths()) for m in self.mocks)

    @staticmethod
    def states(view):
        return {(s["service"], s["section"]): s["state"] for s in view["sections"]}


class EndToEnd(Fixture):
    def test_without_the_password_nothing_reaches_the_app_or_an_upstream(self):
        c = self.client()
        for path in ("/", "/home.json", "/search?q=Synthetic", "/healthz", "/art/x"):
            r = c.get(path, headers={"X-authentik-username": "akadmin", "X-authentik-groups": GROUPS})
            self.assertEqual(401, r.status_code, path)
            self.assertEqual('Basic realm="Avrana preview"', r.headers["www-authenticate"])
        self.assertEqual(401, c.get("/", headers=auth("synthetic-wrong-pass-01")).status_code)
        self.assertEqual(0, self.upstream_calls())

    def test_the_right_password_and_overrides_give_the_owners_sections(self):
        c = self.client()
        r = c.get("/home.json", headers=auth())
        self.assertEqual(200, r.status_code)
        states = self.states(r.json())
        self.assertEqual("ok", states[("jellyfin", "continue")])
        self.assertEqual("ok", states[("audiobookshelf", "continue")])
        self.assertEqual("ok", states[("komga", "recent")])
        self.assertEqual("ok", states[("calibre-web", "recent")])
        page = c.get("/", headers=auth())
        self.assertEqual(200, page.status_code)
        self.assertIn("New this week", page.text)
        self.assertGreater(self.upstream_calls(), 0)

    def test_forged_identity_headers_change_nothing(self):
        c = self.client()
        mine = c.get("/home.json", headers=auth()).json()
        forged = c.get("/home.json", headers=dict(auth(), **{
            "X-authentik-username": "member-b", "X-authentik-groups": "authentik Admins",
            "X-Forwarded-User": "member-b", "Remote-User": "member-b", "X-Forwarded-For": "127.0.0.1"})).json()
        self.assertEqual(mine, forged)
        nav = c.get("/", headers=dict(auth(), **{"X-authentik-groups": "authentik Admins"})).text
        self.assertNotIn("ops.avrana.net", nav)                    # the owner's injected groups, no admin tile

    def test_without_overrides_the_owner_is_not_linked_in_jellyfin_or_audiobookshelf(self):
        c = self.client(self.env(HOME_JELLYFIN_USERNAME=None, HOME_AUDIOBOOKSHELF_USERNAME=None))
        states = self.states(c.get("/home.json", headers=auth()).json())
        self.assertEqual("not_linked", states[("jellyfin", "continue")])
        self.assertEqual("not_linked", states[("audiobookshelf", "continue")])
        self.assertEqual("ok", states[("komga", "recent")])        # shared views have no mapping

    def test_the_throttle_answers_429_through_the_whole_stack(self):
        c = self.client()
        codes = [c.get("/", headers=auth("synthetic-wrong-pass-01")).status_code for _ in range(10)]
        self.assertEqual(429, codes[-1])
        self.assertEqual(429, c.get("/", headers=auth()).status_code)
        self.assertEqual(0, self.upstream_calls())


class StartupRefusals(Fixture):
    def assertRefused(self, env):
        with self.assertRaises((PreviewRefused, SettingsError)):
            run_preview.build_preview_app(env)
        self.assertEqual(0, self.upstream_calls())

    def test_password_file_missing_short_or_password_in_the_environment(self):
        self.assertRefused(self.env(PREVIEW_PASSWORD_FILE=None))
        self.assertRefused(self.env(PREVIEW_PASSWORD_FILE=self.files["short"]))
        self.assertRefused(self.env(PREVIEW_PASSWORD_FILE=self.files["pw"] + ".absent"))
        self.assertRefused(self.env(PREVIEW_PASSWORD=PASSWORD))

    def test_public_or_lan_bind_outside_the_container(self):
        for host in ("0.0.0.0", "::", "10.0.0.218", "192.0.2.1"):
            self.assertRefused(self.env(HOME_HOST=host))
        run_preview.build_preview_app(self.env(HOME_HOST="0.0.0.0", PREVIEW_IN_CONTAINER="yes"))
        self.assertRefused(self.env(HOME_HOST="10.0.0.218", PREVIEW_IN_CONTAINER="yes"))

    def test_preview_flag_gates_and_owner_identity(self):
        self.assertRefused(self.env(HOME_OWNER_PREVIEW=None))
        self.assertRefused(self.env(HOME_GATES_VERIFIED="yes"))
        self.assertRefused(self.env(PREVIEW_OWNER_USERNAME=None))
        self.assertRefused(self.env(PREVIEW_OWNER_GROUPS=None))
        self.assertRefused(self.env(PREVIEW_OWNER_GROUPS=GROUPS + "|authentik Admins"))
        self.assertRefused(self.env(HOME_SECTIONS="off"))
        self.assertRefused(self.env(KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=None))
        self.assertRefused(self.env(CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=None))

    def test_main_returns_2_and_prints_no_secret(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(2, run_preview.main(self.env(PREVIEW_PASSWORD=PASSWORD)))
            self.assertEqual(2, run_preview.main(self.env(HOME_HOST="0.0.0.0")))
        self.assertIn("refusing to start", err.getvalue())
        self.assertNotIn(PASSWORD, err.getvalue())

    def test_serve_main_still_refuses_real_mode_without_the_gates(self):
        import contextlib
        import io
        import os
        from unittest import mock
        from avrana_home.app import serve
        with mock.patch.dict(os.environ, self.env(), clear=True), \
                mock.patch.object(serve.uvicorn, "run") as ran, self.assertRaises(SettingsError):
            with contextlib.redirect_stderr(io.StringIO()):
                serve.main()
        ran.assert_not_called()


class OverRealUvicorn(Fixture):
    def test_loopback_healthz_is_open_and_everything_else_needs_the_password(self):
        _settings, app = run_preview.build_preview_app(self.env(HOME_PORT=str(free_port())))
        with RealServer(app) as server:                             # the peer is 127.0.0.1 here
            self.assertEqual(200, server.get("/healthz").status)
            self.assertEqual(401, server.get("/").status)
            self.assertEqual(401, server.get("/healthz?x=1").status)
            ok = server.get("/home.json", [("Authorization", auth()["Authorization"])])
            self.assertEqual(200, ok.status)
            self.assertIsNone(ok.header("server"))


if __name__ == "__main__":
    unittest.main()
