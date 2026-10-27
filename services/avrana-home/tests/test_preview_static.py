"""Static checks on the owner preview's container files (Dockerfile.preview, docker-compose.preview.yml,
.dockerignore, preview.env.example). Text only, standard library (PyYAML used when importable). No Docker:
these prove what the files SAY, not that an image builds or a container runs."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401
import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parents[1]
DOCKERFILE = HOME / "Dockerfile.preview"
COMPOSE = HOME / "docker-compose.preview.yml"
IGNORE = HOME / ".dockerignore"
EXAMPLE = HOME / "preview.env.example"
PORTAL_DOCKERFILE = REPO / "services" / "avrana-portal" / "Dockerfile"
CLOUDFLARED = REPO / "deploy" / "host" / "cloudflared" / "config.yml"
SECRETS = ("preview_password", "jellyfin_api_key", "audiobookshelf_token", "komga_token", "calibre_web_credential")


def instructions(text):
    """Dockerfile instructions with continuation lines joined, comments dropped."""
    out, buf = [], ""
    for line in text.splitlines():
        if line.strip().startswith("#") and not buf:
            continue
        buf += line.rstrip("\\").strip() + " " if line.rstrip().endswith("\\") else line.strip()
        if not line.rstrip().endswith("\\"):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    return out


class DockerfileTests(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")
        self.ins = instructions(self.text)

    def test_base_image_is_the_portals_pinned_digest(self):
        portal_from = [i for i in instructions(PORTAL_DOCKERFILE.read_text(encoding="utf-8")) if i.startswith("FROM ")]
        mine = [i for i in self.ins if i.startswith("FROM ")]
        self.assertEqual(1, len(mine))
        self.assertEqual(portal_from, mine)
        self.assertRegex(mine[0], r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$")

    def test_dependencies_are_hash_checked_without_a_cache(self):
        pip = [i for i in self.ins if i.startswith("RUN ") and "pip install" in i]
        self.assertEqual(1, len(pip))
        for flag in ("--no-cache-dir", "--require-hashes", "-r /app/requirements.lock"):
            self.assertIn(flag, pip[0])

    def test_copies_only_the_package_the_preview_and_the_portal_tables(self):
        copies = [i for i in self.ins if i.split()[0] in ("COPY", "ADD")]
        self.assertEqual(["COPY requirements.lock /app/requirements.lock",
                          "COPY avrana_home/ /app/avrana_home/",
                          "COPY preview/ /app/preview/",
                          "COPY --from=portal portal.py /app/catalogue/portal.py"], copies)
        self.assertNotRegex(self.text, r"(?m)^\s*(COPY|ADD)\s+\.\s")          # never the whole context

    def test_runs_unprivileged_on_8096_with_a_healthcheck_and_the_container_bind(self):
        self.assertIn("USER 1000:1000", self.ins)
        self.assertIn("EXPOSE 8096", self.ins)
        self.assertLess(self.ins.index("USER 1000:1000"), [n for n, i in enumerate(self.ins) if i.startswith("CMD")][0])
        health = [i for i in self.ins if i.startswith("HEALTHCHECK")]
        self.assertEqual(1, len(health))
        self.assertIn("http://127.0.0.1:8096/healthz", health[0])
        env = " ".join(i for i in self.ins if i.startswith("ENV "))
        for pair in ("HOME_HOST=0.0.0.0", "HOME_PORT=8096", "PREVIEW_IN_CONTAINER=yes",
                     "HOME_CATALOGUE_PATH=/app/catalogue/portal.py"):
            self.assertIn(pair, env)
        self.assertIn('CMD ["python3", "-m", "preview.run_preview"]', self.ins)
        self.assertNotIn("HOME_GATES_VERIFIED", self.text)

    def test_the_build_context_denies_everything_but_the_three_inputs(self):
        lines = [ln.strip() for ln in IGNORE.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        self.assertEqual("*", lines[0])
        self.assertEqual({"!requirements.lock", "!avrana_home/", "!preview/"}, {ln for ln in lines if ln.startswith("!")})
        for denied in ("dev/", "tests/", "webtests/", "secrets/", "*.env"):
            self.assertIn(denied, lines)


@unittest.skipIf(yaml is None, "PyYAML not importable: the compose structure checks need it")
class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.text = COMPOSE.read_text(encoding="utf-8")
        self.doc = yaml.safe_load(self.text)
        self.svc = self.doc["services"]["avrana-home-preview"]

    def test_one_service_with_the_expected_name_and_build(self):
        self.assertEqual(["avrana-home-preview"], list(self.doc["services"]))
        self.assertEqual("avrana-home-preview", self.svc["container_name"])
        self.assertEqual("Dockerfile.preview", self.svc["build"]["dockerfile"])
        self.assertEqual(".", self.svc["build"]["context"])
        self.assertEqual({"portal": "../avrana-portal"}, self.svc["build"]["additional_contexts"])

    def test_published_only_on_the_lan_address(self):
        self.assertEqual(["10.0.0.218:8197:8096"], self.svc["ports"])
        self.assertNotIn("expose", self.svc)
        self.assertNotIn("network_mode", self.svc)
        for bad in ("0.0.0.0:", "127.0.0.1:8197", '"8197:', "[::]"):
            self.assertNotIn(bad, self.text)

    def test_its_own_bridge_network_and_nothing_of_authentik_or_cloudflared(self):
        self.assertEqual(["preview"], self.svc["networks"])
        self.assertEqual({"preview": {"name": "avrana-home-preview", "driver": "bridge"}}, self.doc["networks"])
        code = "\n".join(ln for ln in self.text.splitlines() if not ln.lstrip().startswith("#"))
        for word in ("authentik_", "external:", "cloudflared", "tunnel", "traefik", "labels"):
            self.assertNotIn(word, code)

    def test_hardening_like_the_portal(self):
        self.assertIs(True, self.svc["read_only"])
        self.assertEqual(["no-new-privileges:true"], self.svc["security_opt"])
        self.assertEqual(["ALL"], self.svc["cap_drop"])
        self.assertNotIn("cap_add", self.svc)
        self.assertNotIn("privileged", self.svc)
        self.assertNotIn("volumes", self.svc)                        # no host path, no Docker socket
        self.assertEqual(128, self.svc["pids_limit"])
        self.assertIn(self.svc["mem_limit"], ("128m", "256m"))
        self.assertEqual(0.5, self.svc["cpus"])
        self.assertTrue(all(t.startswith("/tmp:") for t in self.svc["tmpfs"]))

    def test_secrets_are_files_under_secrets_and_env_is_the_gitignored_file(self):
        self.assertEqual(list(SECRETS), self.svc["secrets"])
        self.assertEqual({s: {"file": f"./secrets/{s}"} for s in SECRETS}, self.doc["secrets"])
        self.assertEqual(["preview.env"], self.svc["env_file"])
        env = dict(e.split("=", 1) for e in self.svc["environment"])
        self.assertEqual("yes", env["HOME_OWNER_PREVIEW"])
        self.assertEqual("/run/secrets/preview_password", env["PREVIEW_PASSWORD_FILE"])
        self.assertNotIn("HOME_GATES_VERIFIED", self.text)
        for name in env:
            self.assertFalse(re.search(r"(KEY|TOKEN|PASSWORD|CREDENTIAL)$", name), name)


class ExampleEnvAndIgnoreTests(unittest.TestCase):
    def test_the_example_holds_placeholders_and_file_paths_only(self):
        text = EXAMPLE.read_text(encoding="utf-8")
        pairs = dict(ln.split("=", 1) for ln in text.splitlines() if ln and not ln.startswith("#") and "=" in ln)
        for name, value in pairs.items():
            if re.search(r"(KEY|TOKEN|PASSWORD|CREDENTIAL)(_FILE)?$", name):
                self.assertTrue(name.endswith("_FILE"), name)
                self.assertRegex(value, r"^/run/secrets/[a-z_]+$", name)
        self.assertNotIn("HOME_GATES_VERIFIED=", text)
        self.assertEqual("real", pairs["HOME_UPSTREAM_MODE"])
        self.assertTrue(pairs["PREVIEW_OWNER_USERNAME"].startswith("<"))
        self.assertTrue(pairs["CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS"].startswith("<"))
        self.assertNotIn("KOMGA_BASE_URL", pairs)                    # to verify at deploy, not guessed
        # HTTPS across machines (owner decision 2026-10-27): every example upstream must pass the real-mode rule.
        from urllib.parse import urlsplit
        from avrana_home.app.settings import plain_http_allowed
        for name in ("JELLYFIN_BASE_URL", "AUDIOBOOKSHELF_BASE_URL", "CALIBRE_WEB_BASE_URL"):
            parts = urlsplit(pairs[name])
            self.assertTrue(parts.scheme == "https" or plain_http_allowed(parts.hostname or ""), name)
        self.assertNotIn("10.0.0.218", "".join(pairs.values()))

    def test_preview_env_and_secrets_are_gitignored(self):
        rules = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("*.env", rules)
        self.assertIn("**/secrets/", rules)
        self.assertIn("!*.env.example", rules)

    def test_the_preview_is_not_in_the_tunnel(self):
        text = CLOUDFLARED.read_text(encoding="utf-8")
        for word in ("8197", "preview", "avrana-home"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
