"""Static checks on the beta deploy kit (AVR-373): docker-compose.beta.yml, beta.env.example and the Authentik
blueprint. Text only, standard library. Nothing here runs Docker or touches Authentik."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import re
import unittest
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parents[1]
COMPOSE = (HOME / "docker-compose.beta.yml").read_text(encoding="utf-8")
EXAMPLE = (HOME / "beta.env.example").read_text(encoding="utf-8")
BLUEPRINT_PATH = HOME / "beta" / "authentik-home-beta.yaml"
BLUEPRINT = BLUEPRINT_PATH.read_text(encoding="utf-8")


def code(text):
    return "\n".join(ln.split("#", 1)[0].rstrip() for ln in text.splitlines() if ln.split("#", 1)[0].strip())


class Compose(unittest.TestCase):
    def test_no_host_port_and_only_the_private_outpost_network(self):
        c = code(COMPOSE)
        self.assertNotRegex(c, r"(?m)^\s*ports\s*:")
        self.assertNotIn("network_mode", c)
        self.assertIn("networks: [authentik_home_beta]", c)
        self.assertRegex(c, r"authentik_home_beta:\s*\n\s*external: true")

    def test_jwt_required_secret_from_a_file_and_synthetic_data(self):
        c = code(COMPOSE)
        self.assertIn("HOME_IDENTITY_MODE=jwt_required", c)
        self.assertIn("HOME_JWT_SECRET_FILE=/run/secrets/home_jwt_secret", c)
        self.assertIn("file: ./secrets/home_jwt_secret", c)
        self.assertIn("dockerfile: Dockerfile.beta", c)
        for forbidden in ("HOME_UPSTREAM_MODE=real", "HOME_GATES_VERIFIED", "JELLYFIN_", "AUDIOBOOKSHELF_",
                          "KOMGA_", "CALIBRE_WEB_", "HOME_JWT_SECRET="):
            self.assertNotIn(forbidden, c)

    def test_hardened_like_the_portal(self):
        c = code(COMPOSE)
        for line in ("read_only: true", "cap_drop: [ALL]", "security_opt: [no-new-privileges:true]",
                     "pids_limit:", "mem_limit:", "healthcheck:"):
            self.assertIn(line, c)

    def test_the_example_holds_placeholders_only(self):
        pairs = dict(ln.split("=", 1) for ln in EXAMPLE.splitlines() if ln and not ln.startswith("#") and "=" in ln)
        self.assertEqual({"HOME_JWT_ISSUER", "HOME_JWT_AUDIENCE", "HOME_ALLOWED_USERS"}, set(pairs))
        self.assertTrue(pairs["HOME_JWT_ISSUER"].startswith("<"))
        self.assertTrue(pairs["HOME_JWT_AUDIENCE"].startswith("<"))
        self.assertEqual("akadmin", pairs["HOME_ALLOWED_USERS"])

    def test_env_and_secret_are_gitignored(self):
        rules = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("*.env", rules)
        self.assertIn("**/secrets/", rules)


class Blueprint(unittest.TestCase):
    def test_never_auto_applied(self):
        self.assertIn('blueprints.goauthentik.io/instantiate: "false"', BLUEPRINT)
        self.assertNotEqual(BLUEPRINT_PATH.parent, REPO / "services" / "authentik" / "blueprints")
        self.assertFalse((REPO / "services" / "authentik" / "blueprints" / BLUEPRINT_PATH.name).exists())

    def test_its_own_provider_to_the_beta_container_bound_to_avrana_beta_only(self):
        self.assertIn("name: avrana-home-beta-proxy", BLUEPRINT)
        self.assertIn("internal_host: http://avrana-home-beta:8096", BLUEPRINT)
        self.assertNotIn("avrana-portal", BLUEPRINT)
        self.assertEqual(1, len(re.findall(r"authentik_policies\.policybinding", BLUEPRINT)))
        self.assertIn("group: !KeyOf beta-group", BLUEPRINT)
        self.assertIn("name: avrana-beta", BLUEPRINT)
        self.assertEqual(["akadmin"], re.findall(r"\[username, ([^\]]+)\]", BLUEPRINT))
        self.assertNotRegex(BLUEPRINT, r"(?i)client_secret|password")


if __name__ == "__main__":
    unittest.main()
