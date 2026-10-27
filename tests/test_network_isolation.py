"""Gate G1 (AVR-355): the network-isolation decision and the Git-side compose declarations.

Offline: synthetic `docker network inspect` fixtures and the compose files in this repository. No
Docker, no network, no production access. The static compose tests need PyYAML and are skipped
(loudly) without it.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
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

    def test_applied_marker_turns_not_applied_into_a_fail(self):
        results = iso.evaluate(load("pre_apply"), applied=True)
        self.assertEqual(levels(results), ["FAIL"])
        self.assertIn("marked applied", text(results))

    def test_applied_marker_does_not_change_a_healthy_or_drifted_result(self):
        self.assertEqual(levels(iso.evaluate(load("post_apply_ok"), applied=True)), ["OK"])
        self.assertIn("FAIL", levels(iso.evaluate(load("stray_third_container"), applied=True)))

    def test_server_absent_from_a_private_network_fails(self):
        networks = load("post_apply_ok")
        olivetin = next(n for n in networks if n["Name"] == "authentik_olivetin")
        olivetin["Containers"] = {k: v for k, v in olivetin["Containers"].items() if v["Name"] != "authentik-server"}
        self.assertIn("absent authentik-server", text(iso.evaluate(networks)))

    def test_backend_on_frontend_fails_even_when_private_networks_are_correct(self):
        networks = load("post_apply_ok")
        next(n for n in networks if n["Name"] == "authentik_frontend")["Containers"]["b" * 64] = {"Name": "avrana-portal"}
        results = iso.evaluate(networks)
        self.assertIn("avrana-portal is attached to authentik_frontend", text(results))
        self.assertNotIn("OK", levels(results))

    def test_two_of_three_private_networks_is_a_fail(self):
        networks = [n for n in load("post_apply_ok") if n["Name"] != "authentik_kindle"]
        self.assertIn("missing: authentik_kindle", text(iso.evaluate(networks)))

    def test_pre_apply_with_backends_off_frontend_still_only_warns(self):
        networks = load("pre_apply")
        frontend = next(n for n in networks if n["Name"] == "authentik_frontend")
        frontend["Containers"] = {k: v for k, v in frontend["Containers"].items() if v["Name"] == "authentik-server"}
        self.assertEqual(levels(iso.evaluate(networks)), ["WARN"])

    def test_duplicate_network_names_fail(self):
        networks = load("post_apply_ok")
        networks.append(json.loads(json.dumps(next(n for n in networks if n["Name"] == "authentik_portal"))))
        self.assertEqual(levels(iso.evaluate(networks)), ["FAIL"])
        self.assertIn("duplicate network name", text(iso.evaluate(networks)))

    def test_odd_shapes_fail_and_never_raise(self):
        base = load("post_apply_ok")
        odd_containers = (["x"], 5, "s", {"c": "not-a-dict"}, {"c": {"Name": None}}, {"c": {"Name": 7}},
                          {"c": {"Name": ["olivetin"]}}, {"c": {}})
        for value in odd_containers:
            for target in ("authentik_portal", "komga_default"):
                networks = json.loads(json.dumps(base))
                next(n for n in networks if n["Name"] == target)["Containers"] = value
                self.assertIn("FAIL", levels(iso.evaluate(networks)), f"{target} {value!r}")
        for bad_name in (None, 5, ["authentik_frontend"], "", {"a": 1}):
            networks = json.loads(json.dumps(base))
            networks[0]["Name"] = bad_name
            self.assertEqual(levels(iso.evaluate(networks)), ["FAIL"], repr(bad_name))
        for bad_data in (None, {}, "x", 3):
            self.assertEqual(levels(iso.evaluate(bad_data)), ["FAIL"], repr(bad_data))
        self.assertEqual(levels(iso.evaluate([None])), ["FAIL"])

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

    def test_main_never_tracebacks_on_odd_json(self):
        shapes = ['[{"Name": ["a"], "Containers": []}]', '[{"Name": "authentik_portal", "Containers": [1]}]',
                  '[1, 2]', '{"Name": 5}', 'null']
        for shape in shapes:
            run = self.run_script(stdin=shape)
            self.assertEqual(run.returncode, 1, shape)
            self.assertNotIn("Traceback", run.stderr, shape)
            self.assertTrue(run.stderr.startswith("FAIL "), shape)

    def test_cli_applied_flag_in_either_position(self):
        pre = str(FIXTURES / "pre_apply.json")
        for args in (("--applied", pre), (pre, "--applied")):
            run = self.run_script(*args)
            self.assertEqual((run.returncode, run.stderr.startswith("FAIL ")), (1, True), args)


def find_bash():
    candidates = []
    if sys.platform == "win32":
        candidates += ["C:/Program Files/Git/bin/bash.exe", "C:/Program Files/Git/usr/bin/bash.exe"]
    found = shutil.which("bash")
    if found and not (sys.platform == "win32" and "system32" in found.lower()):
        candidates.append(found)
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


BASH = find_bash()
HEALTH = (ROOT / "scripts/services-health.sh").read_text(encoding="utf-8")
HOOK = HEALTH.split("# BEGIN g1-isolation-hook\n", 1)[1].split("# END g1-isolation-hook", 1)[0]


@unittest.skipIf(BASH is None, "bash not available: hook execution tests skipped")
class HealthHookTests(unittest.TestCase):
    """Runs the real hook block from scripts/services-health.sh under bash, with stub docker and
    python3 on PATH and the real checker beside it. No Docker, no network."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.scripts = root / "scripts"
        self.bin = root / "bin"
        self.state = root / "state"
        for directory in (self.scripts, self.bin, self.state, root / "home"):
            directory.mkdir()
        shutil.copy(SCRIPT, self.scripts / "check-network-isolation.py")
        self.wrapper = self.scripts / "wrap.sh"
        self.wrapper.write_text("failures=0\n" + HOOK + 'echo "failures=$failures"\n', encoding="utf-8", newline="\n")
        self.write_stub("python3", 'exec "' + Path(sys.executable).as_posix() + '" "$@"\n')

    def write_stub(self, name, body):
        (self.bin / name).write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
        (self.bin / name).chmod(0o755)

    def docker_stub(self, fixture):
        if fixture is None:   # docker present but unreadable: no output, non-zero exit
            self.write_stub("docker", "exit 1\n")
            return
        path = (FIXTURES / f"{fixture}.json").as_posix()
        self.write_stub("docker", 'case "$1 $2" in\n  "network ls") echo aaa; echo bbb ;;\n'
                                  '  "network inspect") cat "' + path + '" ;;\n  *) exit 1 ;;\nesac\n')

    def run_hook(self, fixture, marker=False, env=None):
        self.docker_stub(fixture)
        if marker:
            (self.state / "g1-applied").write_text("", encoding="utf-8")
        environ = {k: v for k, v in os.environ.items() if not k.startswith("AVRANA_")}
        environ.update({"PATH": self.bin.as_posix() + os.pathsep + os.environ["PATH"],
                        "HOME": (Path(self.tmp.name) / "home").as_posix(),
                        "AVRANA_STATE_DIR": self.state.as_posix()})
        environ.update(env or {})
        run = subprocess.run([BASH, self.wrapper.as_posix()], capture_output=True, text=True, env=environ, timeout=60)
        failures = re.search(r"^failures=(\d+)$", run.stdout, re.M)
        self.assertIsNotNone(failures, run.stdout + run.stderr)
        return int(failures.group(1)), run.stdout, run.stderr

    def test_pre_apply_warns_and_counts_no_failure(self):
        failures, out, err = self.run_hook("pre_apply")
        self.assertEqual(failures, 0)
        self.assertIn("WARN network isolation (G1): not applied", err)
        self.assertNotIn("FAIL", err)

    def test_applied_state_is_ok(self):
        failures, out, err = self.run_hook("post_apply_ok")
        self.assertEqual((failures, err), (0, ""))
        self.assertIn("OK   network isolation (G1)", out)
        self.assertEqual(self.run_hook("post_apply_ok", marker=True)[0], 0)

    def test_drift_counts_one_failure(self):
        for fixture in ("backend_rejoined_frontend", "stray_third_container", "missing_network"):
            failures, out, err = self.run_hook(fixture)
            self.assertEqual(failures, 1, fixture)
            self.assertIn("FAIL network isolation (G1)", err)

    def test_marker_turns_not_applied_into_a_failure(self):
        failures, out, err = self.run_hook("pre_apply", marker=True)
        self.assertEqual(failures, 1)
        self.assertIn("marked applied", err)

    def test_environment_variable_works_like_the_marker(self):
        self.assertEqual(self.run_hook("pre_apply", env={"AVRANA_G1_APPLIED": "1"})[0], 1)
        self.assertEqual(self.run_hook("pre_apply", env={"AVRANA_G1_APPLIED": "0"})[0], 0)

    def test_unreadable_docker_warns_before_and_fails_after_sign_off(self):
        failures, out, err = self.run_hook(None)
        self.assertEqual(failures, 0)
        self.assertIn("WARN network isolation (G1): could not read docker network data", err)
        failures, out, err = self.run_hook(None, marker=True)
        self.assertEqual(failures, 1)
        self.assertIn("FAIL network isolation (G1): could not read docker network data", err)

    def test_missing_python_warns_before_and_fails_after_sign_off(self):
        env = {"AVRANA_PYTHON": "python-that-does-not-exist"}
        failures, out, err = self.run_hook("post_apply_ok", env=env)
        self.assertEqual(failures, 0)
        self.assertIn("WARN network isolation (G1): python-that-does-not-exist not found", err)
        failures, out, err = self.run_hook("post_apply_ok", marker=True, env=env)
        self.assertEqual(failures, 1)
        self.assertIn("FAIL network isolation (G1)", err)

    def test_missing_checker_script_is_a_failure(self):
        (self.scripts / "check-network-isolation.py").unlink()
        self.assertEqual(self.run_hook("post_apply_ok")[0], 1)

    def test_whole_script_syntax(self):
        run = subprocess.run([BASH, "-n", (ROOT / "scripts/services-health.sh").as_posix()],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)


# With AVRANA_REQUIRE_YAML=1 (CI, decision D-8a) a missing PyYAML fails these tests instead of skipping them.
@unittest.skipIf(yaml is None and os.environ.get("AVRANA_REQUIRE_YAML", "") in ("", "0"),
                 "PyYAML not installed: compose declaration tests skipped")
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

    def test_private_networks_are_not_internal_or_attachable(self):
        networks = self.compose("authentik")["networks"]
        for key in ("portal", "kindle", "olivetin"):
            definition = networks[key]
            self.assertFalse(definition.get("internal"), f"{key}: backends need outbound access")
            self.assertFalse(definition.get("attachable"), f"{key}: must not be attachable")
            self.assertFalse(definition.get("external"), key)
        self.assertEqual(networks["backend"], {"internal": True})  # unchanged from before G1

    def test_private_networks_have_the_explicit_subnets_the_preflight_checks(self):
        # The host's default address pools are nearly full (AVR-356 preflight, 2026-10-27), so each
        # private network names its own /24, and scripts/g1-preflight.sh checks exactly these are free.
        networks = self.compose("authentik")["networks"]
        subnets = [networks[key]["ipam"]["config"][0]["subnet"] for key in ("portal", "kindle", "olivetin")]
        for key in ("portal", "kindle", "olivetin"):
            self.assertEqual(len(networks[key]["ipam"]["config"]), 1, key)
        self.assertEqual(len(set(subnets)), 3, subnets)
        script = (ROOT / "scripts/g1-preflight.sh").read_text(encoding="utf-8")
        listed = re.search(r'^G1_SUBNETS="([^"]+)"$', script, re.M)
        self.assertIsNotNone(listed, "G1_SUBNETS missing from g1-preflight.sh")
        self.assertEqual(listed.group(1).split(), subnets)

    def test_authentik_server_networks_are_exactly_the_expected_set(self):
        networks = self.compose("authentik")["services"]["server"]["networks"]
        self.assertEqual(sorted(networks), sorted(["frontend", "backend", "portal", "kindle", "olivetin"]))
        self.assertEqual(len(networks), len(set(networks)))

    def test_worker_ldap_and_postgresql_networks_are_unchanged(self):
        services = self.compose("authentik")["services"]
        self.assertEqual(sorted(services["worker"]["networks"]), ["backend", "frontend"])
        self.assertEqual(sorted(services["ldap"]["networks"]), ["avrana-ldap", "frontend"])
        self.assertEqual(services["postgresql"]["networks"], ["backend"])

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
