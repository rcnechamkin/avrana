"""AVR-373 phase 1: the fixture-only beta entry point (beta/run_beta.py) and its image (Dockerfile.beta).

Tier A (standard library): every refusal, the fixed loopback mock URLs, and static checks on the Dockerfile
and its ignore file. Tier B (the web framework): the app built by the beta entry point, with its four mocks on
ephemeral loopback ports, answers only a verified token; forged plain headers and forged tokens get the
no-principal page. Synthetic secret, issuer and audience only. Nothing here builds or runs a container; CI's
beta-image job does (.github/workflows/beta-image.yml).
"""
import re
import socket
import unittest
from pathlib import Path

from beta import run_beta
from beta.run_beta import BetaRefused, build_env

from .support import GROUPS, USER, require_framework
from .test_web_jwt_identity import AUD, ISS, JWT, SECRET, mint

HOME = Path(__file__).resolve().parents[1]
DOCKERFILE = HOME / "Dockerfile.beta"
IGNORE = HOME / "Dockerfile.beta.dockerignore"
GOOD = {"HOME_IDENTITY_MODE": "jwt_required", "HOME_JWT_ISSUER": ISS, "HOME_JWT_AUDIENCE": AUD,
        "HOME_JWT_SECRET": SECRET}


def free_ports(n):
    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


class Refusals(unittest.TestCase):
    def refused(self, extra=None, drop=()):
        env = {k: v for k, v in GOOD.items() if k not in drop}
        env.update(extra or {})
        with self.assertRaises(BetaRefused) as caught:
            run_beta.build(env, start=False)
        return str(caught.exception)

    def test_plain_headers_or_no_mode_are_refused(self):
        self.assertIn("jwt_required or jwt_log_only", self.refused({"HOME_IDENTITY_MODE": "headers"}))
        self.assertIn("jwt_required or jwt_log_only", self.refused(drop=("HOME_IDENTITY_MODE",)))

    def test_any_real_upstream_or_preview_or_dev_variable_is_refused(self):
        for name in ("JELLYFIN_BASE_URL", "JELLYFIN_API_KEY_FILE", "AUDIOBOOKSHELF_TOKEN", "KOMGA_BASE_URL",
                     "CALIBRE_WEB_PASSWORD_FILE", "PREVIEW_OWNER_USERNAME", "HOME_DEV_IDENTITY"):
            with self.subTest(name=name):
                self.assertIn(name, self.refused({name: "x"}))

    def test_real_mode_gates_and_unknown_home_settings_are_refused(self):
        for name, value in (("HOME_UPSTREAM_MODE", "real"), ("HOME_UPSTREAM_MODE", "mock"),
                            ("HOME_GATES_VERIFIED", "yes"), ("HOME_TIMEOUT", "30")):
            with self.subTest(name=name, value=value):
                self.assertIn(f"{name} is not a beta setting", self.refused({name: value}))

    def test_settings_problems_are_refusals_before_any_mock_starts(self):
        self.assertIn("HOME_JWT_SECRET", self.refused(drop=("HOME_JWT_SECRET",)))
        self.assertIn("HOME_ALLOWED_USERS", self.refused({"HOME_IDENTITY_MODE": "jwt_log_only",
                                                          "HOME_ALLOWED_USERS": "akadmin"}))

    def test_upstreams_are_the_four_loopback_mocks_in_mock_mode(self):
        env = build_env(GOOD)
        self.assertEqual("mock", env["HOME_UPSTREAM_MODE"])
        self.assertEqual("on", env["HOME_SECTIONS"])
        urls = {k: v for k, v in env.items() if k.endswith("_BASE_URL")}
        self.assertEqual({"JELLYFIN_BASE_URL", "AUDIOBOOKSHELF_BASE_URL", "KOMGA_BASE_URL",
                          "CALIBRE_WEB_BASE_URL"}, set(urls))
        for url in urls.values():
            self.assertRegex(url, r"^http://127\.0\.0\.1:\d+$")
        self.assertNotIn("HOME_DEV_IDENTITY", env)


class DockerfileStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOCKERFILE.read_text(encoding="utf-8")
        cls.code = "\n".join(l for l in cls.text.splitlines() if l.strip() and not l.lstrip().startswith("#"))
        cls.ignore = [l.strip() for l in IGNORE.read_text(encoding="utf-8").splitlines()
                      if l.strip() and not l.startswith("#")]

    def test_same_pinned_base_as_the_preview_image(self):
        base = re.search(r"^FROM (\S+)$", self.code, re.M).group(1)
        self.assertRegex(base, r"@sha256:[0-9a-f]{64}$")
        preview = (HOME / "Dockerfile.preview").read_text(encoding="utf-8")
        self.assertIn(f"FROM {base}\n", preview)

    def test_runs_the_beta_entry_point_as_a_non_root_user_with_hash_checked_wheels(self):
        self.assertIn('CMD ["python3", "-m", "beta.run_beta"]', self.code)
        self.assertRegex(self.code, r"(?m)^USER 1000:1000$")
        self.assertIn("pip install --no-cache-dir --require-hashes --only-binary=:all: -r /app/requirements.lock",
                      self.code)
        self.assertNotRegex(self.code, r"(?i)\b(JELLYFIN|AUDIOBOOKSHELF|KOMGA|CALIBRE_WEB|PREVIEW)_")
        self.assertNotIn("HOME_IDENTITY_MODE", self.code)      # the operator chooses the mode; there is no default

    def test_the_dev_identity_shim_never_enters_the_image(self):
        sources = [s for line in re.findall(r"(?m)^COPY (?!--from)(.+)$", self.code)
                   for s in line.split()[:-1] if s != "\\"]
        self.assertTrue(sources)
        for src in sources:
            self.assertNotIn("dev_identity", src)
            self.assertNotIn("run_dev", src)
            self.assertNotEqual("tests/__init__.py", src)
            self.assertTrue((HOME / src).exists(), src)
            with self.subTest(src=src):
                self.assertIn("!" + src, self.ignore)          # every input is explicitly allowed
        self.assertEqual("*", self.ignore[0])
        for denied in ("dev/dev_identity.py", "dev/run_dev.py", "tests/__init__.py", "secrets/", "*.env"):
            self.assertIn(denied, self.ignore)

    def test_the_copied_files_are_exactly_what_the_mocks_import(self):
        """The mocks' own imports, read from their source: a new dependency would be missing from the image."""
        copied = set(re.findall(r"(?:dev|tests)/[\w.]+\.py", self.code))
        for mock in ("mock_jellyfin", "mock_audiobookshelf", "mock_komga", "mock_calibre_web"):
            src = (HOME / "dev" / f"{mock}.py").read_text(encoding="utf-8")
            for module in re.findall(r"from dev\.(\w+) import", src):
                self.assertIn(f"dev/{module}.py", copied, mock)
            for fake in re.findall(r'load_fake\("(\w+\.py)"', src):
                self.assertIn(f"tests/{fake}", copied, mock)


class BetaApp(unittest.TestCase):
    """Tier B: the app run_beta builds, with its real mocks on loopback."""

    @classmethod
    def setUpClass(cls):
        require_framework()
        from fastapi.testclient import TestClient
        ports = dict(zip(run_beta.MOCK_PORTS, free_ports(4)))
        app, cls.settings, cls.mocks = run_beta.build(GOOD, ports=ports)
        cls.client = TestClient(app, base_url="http://beta.test", follow_redirects=False,
                                raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        for mock in getattr(cls, "mocks", ()):
            mock.stop()

    def test_settings_are_jwt_required_and_mock(self):
        self.assertEqual("jwt_required", self.settings.identity_mode)
        self.assertEqual("mock", self.settings.upstream_mode)

    def test_a_verified_token_gets_the_member_view_from_the_mocks(self):
        r = self.client.get("/home.json", headers=[(JWT, mint())])
        self.assertEqual(200, r.status_code)
        self.assertTrue(r.json())

    def test_forged_plain_headers_and_forged_tokens_get_no_principal(self):
        forged = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
        for headers in (forged, [(JWT, mint(secret="SYNTHETIC-WRONG-secret-not-real-0123456789ab"))], []):
            with self.subTest(headers=[h[0] for h in headers]):
                self.assertEqual(404, self.client.get("/home.json", headers=headers).status_code)
                self.assertEqual(404, self.client.get("/watch", headers=headers).status_code)
