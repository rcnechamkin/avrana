"""Static checks on the live-data beta kit (AVR-771): docker-compose.beta-live.yml, beta-live.env.example,
Dockerfile.live and its ignore file, and that the kit's settings pass settings.py. Standard library; nothing here
runs Docker or touches Authentik or a library."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import re
import tempfile
import unittest
from pathlib import Path

from avrana_home.app.settings import Settings, SettingsError

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parents[1]
COMPOSE = (HOME / "docker-compose.beta-live.yml").read_text(encoding="utf-8")
EXAMPLE = (HOME / "beta-live.env.example").read_text(encoding="utf-8")
DOCKERFILE = (HOME / "Dockerfile.live").read_text(encoding="utf-8")
IGNORE = (HOME / "Dockerfile.live.dockerignore").read_text(encoding="utf-8")
BLUEPRINT = (HOME / "beta" / "authentik-home-beta.yaml").read_text(encoding="utf-8")


def code(text):
    return "\n".join(ln.split("#", 1)[0].rstrip() for ln in text.splitlines() if ln.split("#", 1)[0].strip())


def compose_env():
    return dict(m.groups() for m in re.finditer(r"(?m)^\s*- ([A-Z_]+)=(.*)$", code(COMPOSE)))


class Compose(unittest.TestCase):
    def test_no_host_port_and_only_the_outpost_and_library_networks(self):
        c = code(COMPOSE)
        self.assertNotRegex(c, r"(?m)^\s*ports\s*:")
        self.assertNotIn("network_mode", c)
        self.assertIn("networks: [authentik_home_beta, audiobookshelf_default, komga_default, "
                      "calibre-web-automated_default]", c)
        for net in ("authentik_home_beta", "audiobookshelf_default", "komga_default", "calibre-web-automated_default"):
            self.assertRegex(c, rf"{net}:\s*\n\s*external: true")
        self.assertNotRegex(c, r"authentik_(frontend|backend|portal|kindle|olivetin)\b")

    def test_state_volume_is_active_whenever_the_bindings_file_is(self):
        # S-11: the repo file alone must be a usable rebuild record. Bindings point into /var/lib/avrana-home, so
        # ./state must be mounted there (the only writable mount); otherwise Home refuses every member.
        c = code(COMPOSE)
        if "HOME_IDENTITY_BINDINGS_FILE=/var/lib/avrana-home/" in c:
            self.assertIn('volumes: ["./state:/var/lib/avrana-home:rw"]', c)
        self.assertEqual(len(re.findall(r"(?m)^\s*volumes\s*:", c)), 1)

    def test_same_container_as_the_provider_expects(self):
        self.assertIn("container_name: avrana-home-beta", code(COMPOSE))
        self.assertIn("internal_host: http://avrana-home-beta:8096", BLUEPRINT)

    def test_real_mode_only_with_gates_verified_identity_and_files_for_secrets(self):
        env = compose_env()
        self.assertEqual(env["HOME_UPSTREAM_MODE"], "real")
        self.assertEqual(env["HOME_GATES_VERIFIED"], "yes")
        self.assertEqual(env["HOME_IDENTITY_MODE"], "jwt_required")
        for name in ("HOME_JWT_SECRET", "JELLYFIN_API_KEY", "AUDIOBOOKSHELF_TOKEN", "KOMGA_TOKEN",
                     "CALIBRE_WEB_CREDENTIAL"):
            self.assertNotIn(name, env)                       # never inline; only the _FILE form
            self.assertTrue(env[name + "_FILE"].startswith("/run/secrets/"))
        for forbidden in ("HOME_OWNER_PREVIEW", "PREVIEW_", "HOME_DEV_", "HOME_JELLYFIN_USERNAME",
                          "HOME_AUDIOBOOKSHELF_USERNAME"):
            self.assertFalse([k for k in env if k.startswith(forbidden)], forbidden)

    def test_upstreams_are_docker_names_or_the_host_gateway_never_a_lan_address(self):
        env = compose_env()
        self.assertEqual(env["JELLYFIN_BASE_URL"], "http://host.docker.internal:8096")
        self.assertEqual(env["AUDIOBOOKSHELF_BASE_URL"], "http://audiobookshelf:80")
        self.assertEqual(env["KOMGA_BASE_URL"], "http://komga:25600")
        self.assertEqual(env["CALIBRE_WEB_BASE_URL"], "http://calibre-web-automated:8083")
        # shared views: only with the owner's no-restriction statement (2026-10-15, docs/DECISIONS.md)
        self.assertEqual(env["KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS"], "yes")
        self.assertEqual(env["CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS"], "yes")
        self.assertIn('extra_hosts: ["host.docker.internal:host-gateway"]', code(COMPOSE))
        self.assertNotRegex(code(COMPOSE), r"\b10\.0\.0\.\d+")

    def test_hardened_like_the_synthetic_beta(self):
        c = code(COMPOSE)
        for line in ("read_only: true", "cap_drop: [ALL]", "security_opt: [no-new-privileges:true]",
                     "pids_limit:", "mem_limit:", "healthcheck:", "dockerfile: Dockerfile.live"):
            self.assertIn(line, c)

    def test_the_example_holds_placeholders_only(self):
        pairs = dict(ln.split("=", 1) for ln in EXAMPLE.splitlines() if ln and not ln.startswith("#") and "=" in ln)
        self.assertEqual({"HOME_JWT_ISSUER", "HOME_JWT_AUDIENCE", "HOME_ALLOWED_USERS"}, set(pairs))
        self.assertTrue(all(v.startswith("<") for v in pairs.values()), pairs)

    def test_the_kit_settings_pass_settings_py(self):
        # The compose environment plus a filled-in example: settings.py must accept it (no SettingsError), so the
        # container will not refuse at start for a reason the repository could have caught.
        with tempfile.TemporaryDirectory() as tmp:
            env = compose_env()
            for name, value in list(env.items()):
                if name.endswith("_FILE"):
                    path = Path(tmp) / Path(value).name
                    path.write_text(("viewer:" if "CREDENTIAL" in name else "") + "x" * 40, encoding="utf-8")
                    env[name] = str(path)
            env.update(HOME_JWT_ISSUER="https://auth.example.test/application/o/avrana-home-beta/",
                       HOME_JWT_AUDIENCE="client-id", HOME_ALLOWED_USERS="tester")
            settings = Settings.from_mapping(env)
            self.assertTrue(settings.uses_real_upstream)
            self.assertEqual(settings.allowed_users, ("tester",))
            env["HOME_IDENTITY_MODE"] = "jwt_log_only"                 # the ABS admin token needs jwt_required
            with self.assertRaises(SettingsError):
                Settings.from_mapping(env)

    def test_env_and_secrets_are_gitignored(self):
        rules = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("*.env", rules)
        self.assertIn("**/secrets/", rules)


class Image(unittest.TestCase):
    def test_runs_the_plain_server_and_copies_only_the_application(self):
        d = code(DOCKERFILE)
        self.assertIn('CMD ["python3", "-m", "avrana_home.app.serve"]', d)
        self.assertEqual(sorted(re.findall(r"(?m)^COPY (?:--from=\S+ )?(\S+)", d)),
                         ["avrana_home/", "portal.py", "requirements.lock"])
        self.assertIn("USER 1000:1000", d)
        self.assertRegex(d, r"FROM python:3\.12-slim@sha256:[0-9a-f]{64}")
        self.assertEqual(re.search(r"FROM (\S+)", d).group(1),
                         re.search(r"FROM (\S+)", (HOME / "Dockerfile.preview").read_text(encoding="utf-8")).group(1))

    def test_ignore_file_allows_only_the_two_inputs(self):
        allowed = [ln for ln in IGNORE.splitlines() if ln.startswith("!")]
        self.assertEqual(allowed, ["!requirements.lock", "!avrana_home/"])
        rules = IGNORE.splitlines()
        self.assertIn("*", rules)
        for denied in ("dev/", "preview/", "beta/", "tests/", "secrets/", "*.env"):
            self.assertIn(denied, rules)


if __name__ == "__main__":
    unittest.main()
