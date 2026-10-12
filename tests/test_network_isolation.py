"""Gate G1 (AVR-355): the network-isolation decision and the Git-side compose declarations.

Offline: synthetic `docker network inspect` fixtures and the compose files in this repository. No
Docker, no network, no production access. The static compose tests need PyYAML and are skipped
(loudly) without it.
"""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/network_inspect"
SCRIPT = ROOT / "scripts/check-network-isolation.py"

spec = importlib.util.spec_from_file_location("check_network_isolation", SCRIPT)
iso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iso)

BACKENDS = {
    # service dir -> (container, private network, blueprint, internal_host)
    "avrana-portal": ("avrana-portal", "authentik_portal", "avrana-portal.yaml", "http://avrana-portal:8095"),
    "avrana-kindle-connector": ("avrana-kindle-connector", "authentik_kindle", "avrana-kindle.yaml",
                                "http://avrana-kindle-connector:8096"),
    "olivetin": ("olivetin", "authentik_olivetin", "avrana-olivetin.yaml", "http://olivetin:1337"),
}


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def levels(results):
    return [level for level, _ in results]


def text(results):
    return "\n".join(message for _, message in results)


class DecisionTests(unittest.TestCase):
    def test_pre_apply_warns_and_does_not_fail(self):
        results = iso.evaluate(load("pre_apply"))
        self.assertEqual(levels(results), ["WARN"])
        self.assertIn("not applied", text(results))

    def test_correct_post_apply_state_is_ok(self):
        results = iso.evaluate(load("post_apply_ok"))
        self.assertEqual(levels(results), ["OK"])

    def test_backend_rejoined_frontend_fails(self):
        results = iso.evaluate(load("backend_rejoined_frontend"))
        self.assertIn("FAIL", levels(results))
        self.assertIn("olivetin is attached to authentik_frontend", text(results))
        self.assertNotIn("OK", levels(results))

    def test_stray_third_container_fails_and_is_named(self):
        results = iso.evaluate(load("stray_third_container"))
        self.assertIn("FAIL", levels(results))
        self.assertIn("authentik_kindle", text(results))
        self.assertIn("unexpected authentik-worker", text(results))

    def test_missing_network_fails_once_others_exist(self):
        results = iso.evaluate(load("missing_network"))
        self.assertIn("FAIL", levels(results))
        self.assertIn("missing: authentik_olivetin", text(results))

    def test_backend_on_two_networks_fails(self):
        results = iso.evaluate(load("backend_on_two_networks"))
        self.assertIn("FAIL", levels(results))
        self.assertIn("avrana-portal is also attached to komga_default", text(results))

    def test_backend_in_a_siblings_private_network_fails(self):
        networks = load("post_apply_ok")
        kindle = next(n for n in networks if n["Name"] == "authentik_kindle")
        kindle["Containers"]["a" * 64] = {"Name": "olivetin"}
        results = iso.evaluate(networks)
        self.assertIn("FAIL", levels(results))
        self.assertIn("olivetin is also attached to authentik_kindle", text(results))

    def test_missing_member_fails(self):
        networks = load("post_apply_ok")
        portal = next(n for n in networks if n["Name"] == "authentik_portal")
        portal["Containers"] = {k: v for k, v in portal["Containers"].items() if v["Name"] != "avrana-portal"}
        results = iso.evaluate(networks)
        self.assertIn("FAIL", levels(results))
        self.assertIn("absent avrana-portal", text(results))

    def test_empty_private_network_with_null_containers_fails_without_crashing(self):
        networks = load("post_apply_ok")
        next(n for n in networks if n["Name"] == "authentik_portal")["Containers"] = None
        self.assertIn("FAIL", levels(iso.evaluate(networks)))

    def test_frontend_absent_after_apply_fails(self):
        networks = [n for n in load("post_apply_ok") if n["Name"] != "authentik_frontend"]
        self.assertIn("FAIL", levels(iso.evaluate(networks)))

    def test_parse_rejects_malformed_and_empty_input(self):
        for bad in ((FIXTURES / "malformed.json").read_text(encoding="utf-8"), "", "[]", "3", '["x"]'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                iso.parse(bad)


class CommandLineTests(unittest.TestCase):
    def run_script(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], input=stdin,
                              capture_output=True, text=True, timeout=30)

    def test_exit_codes_and_streams(self):
        ok = self.run_script(str(FIXTURES / "post_apply_ok.json"))
        self.assertEqual((ok.returncode, ok.stdout.startswith("OK   "), ok.stderr), (0, True, ""))
        pre = self.run_script(str(FIXTURES / "pre_apply.json"))
        self.assertEqual((pre.returncode, pre.stdout, pre.stderr.startswith("WARN ")), (0, "", True))
        for name in ("backend_rejoined_frontend", "stray_third_container", "missing_network",
                     "backend_on_two_networks", "malformed"):
            bad = self.run_script(str(FIXTURES / f"{name}.json"))
            self.assertEqual(bad.returncode, 1, name)
            self.assertTrue(bad.stderr.startswith("FAIL "), name)
            self.assertEqual(bad.stdout, "", name)

    def test_reads_stdin(self):
        data = (FIXTURES / "post_apply_ok.json").read_text(encoding="utf-8")
        self.assertEqual(self.run_script(stdin=data).returncode, 0)
        self.assertEqual(self.run_script(stdin="").returncode, 1)

    def test_missing_file_fails(self):
        self.assertEqual(self.run_script(str(FIXTURES / "does-not-exist.json")).returncode, 1)

    def test_health_script_calls_the_checker(self):
        health = (ROOT / "scripts/services-health.sh").read_text(encoding="utf-8")
        self.assertIn("check-network-isolation.py", health)
        self.assertIn("failures=$((failures + 1))", health.split("check-network-isolation.py", 1)[1])


@unittest.skipIf(yaml is None, "PyYAML not installed: compose declaration tests skipped")
class ComposeDeclarationTests(unittest.TestCase):
    @staticmethod
    def compose(service_dir):
        return yaml.safe_load((ROOT / f"services/{service_dir}/docker-compose.yml").read_text(encoding="utf-8"))

    @staticmethod
    def resolved(compose, key):
        """Docker network name for a key under the file's top-level `networks`."""
        definition = (compose.get("networks") or {}).get(key) or {}
        return definition.get("name", key)

    def test_each_backend_declares_only_its_private_network(self):
        for service_dir, (container, private, _, _) in BACKENDS.items():
            compose = self.compose(service_dir)
            services = [s for s in compose["services"].values() if s.get("container_name") == container]
            self.assertEqual(len(services), 1, service_dir)
            self.assertEqual([self.resolved(compose, k) for k in services[0]["networks"]], [private], service_dir)
            definition = compose["networks"][private]
            self.assertTrue(definition.get("external"), f"{service_dir}: {private} must be external")
            self.assertEqual(list(compose["networks"]), [private], f"{service_dir}: no other network may be declared")

    def test_no_backend_service_uses_a_default_or_host_network(self):
        for service_dir, (container, _, _, _) in BACKENDS.items():
            service = next(s for s in self.compose(service_dir)["services"].values()
                           if s.get("container_name") == container)
            self.assertNotIn("network_mode", service, service_dir)
            self.assertNotIn("ports", service, f"{service_dir} must publish no host port")

    def test_authentik_server_joins_every_private_network_and_only_it(self):
        compose = self.compose("authentik")
        privates = {private for _, private, _, _ in BACKENDS.values()}
        server = compose["services"]["server"]
        joined = {self.resolved(compose, k) for k in server["networks"]}
        self.assertTrue(privates <= joined, f"server missing {privates - joined}")
        self.assertIn("frontend", server["networks"])  # project authentik -> authentik_frontend
        for name, service in compose["services"].items():
            if name == "server":
                continue
            overlap = {self.resolved(compose, k) for k in service.get("networks", [])} & privates
            self.assertFalse(overlap, f"authentik service {name} must not join {overlap}")
        for key, (_, private, _, _) in zip(("portal", "kindle", "olivetin"), BACKENDS.values()):
            self.assertEqual(self.resolved(compose, key), private)
            self.assertFalse(compose["networks"][key].get("external"))

    def test_no_other_compose_file_joins_an_authentik_network(self):
        allowed = {"authentik", *BACKENDS}
        pattern = re.compile(r"authentik_(frontend|backend|portal|kindle|olivetin)\b")
        for path in sorted((ROOT / "services").glob("*/docker-compose*.yml")):
            service_dir = path.parent.name
            if service_dir in allowed:
                continue
            body = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#"))
            self.assertIsNone(pattern.search(body), f"{path.relative_to(ROOT)} references an Authentik network")

    def test_no_backend_still_names_authentik_frontend(self):
        for service_dir in BACKENDS:
            body = "\n".join(line for line in
                             (ROOT / f"services/{service_dir}/docker-compose.yml").read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#"))
            self.assertNotIn("authentik_frontend", body, service_dir)

    def test_proxy_provider_internal_hosts_are_the_backend_container_names(self):
        for service_dir, (container, _, blueprint, internal_host) in BACKENDS.items():
            body = (ROOT / f"services/authentik/blueprints/{blueprint}").read_text(encoding="utf-8")
            match = re.search(r"^\s*internal_host:\s*(\S+)", body, re.M)
            self.assertIsNotNone(match, blueprint)
            self.assertEqual(match.group(1), internal_host, blueprint)
            self.assertEqual(internal_host.split("//")[1].split(":")[0], container)

    def test_every_proxy_provider_blueprint_is_covered(self):
        providers = sorted(p.name for p in (ROOT / "services/authentik/blueprints").glob("*.yaml")
                           if "authentik_providers_proxy.proxyprovider" in p.read_text(encoding="utf-8"))
        self.assertEqual(providers, sorted(b for _, _, b, _ in BACKENDS.values()),
                         "a new proxy provider needs its own private network and an entry in this test")

    def test_expected_containers_list_keeps_the_backends(self):
        names = {line.split("#")[0].strip() for line in
                 (ROOT / "deploy/docker/expected-containers.txt").read_text(encoding="utf-8").splitlines()}
        for container, _, _, _ in BACKENDS.values():
            self.assertIn(container, names)
        self.assertIn("authentik-server", names)

    def test_bootstrap_names_the_external_networks(self):
        guide = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8")
        for _, private, _, _ in BACKENDS.values():
            self.assertIn(private, guide, "services/backups/restore-test.py requires every external network here")


if __name__ == "__main__":
    unittest.main()
