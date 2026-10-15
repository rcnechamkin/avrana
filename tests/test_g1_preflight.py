"""scripts/g1-preflight.sh (AVR-356): read-only by construction, and every check fails closed.

Runs the real script under bash with stub `docker`, `curl` and `python3` on PATH, synthetic backup status
files and a synthetic rollback directory in a temporary directory. The docker stub records every call so
the tests can prove only list/inspect verbs were used. No Docker, no network, no production access.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g1-preflight.sh"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_network_isolation import BASH  # noqa: E402

STUB = r'''
import json, os, sys
s = json.load(open(os.environ["G1_SCENARIO"]))
with open(os.environ["G1_CALLS"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]
def out(text):
    if text is None:
        sys.exit(1)
    print(text)
    sys.exit(0)
if a[:1] == ["version"]:
    out(s.get("server"))
if a[:2] == ["network", "ls"]:
    out(s.get("net_ids"))
if a[:2] == ["network", "inspect"]:
    if a[2] == "--format":
        out(s.get("subnets"))
    if a[2] in s.get("existing_private", []):
        out("[]")
    if a[2] == "authentik_frontend":
        out(s.get("frontend"))
    sys.exit(1)
if a[:1] == ["ps"]:
    out(s.get("ps"))
if a[:1] == ["inspect"]:
    if a[1] == "--format":
        out(s.get("modes"))
    out(s.get("containers", {}).get(a[1]))
sys.exit(1)
'''

HEALTHY = {
    "server": "27.3.1",
    "net_ids": "\n".join(f"n{i:02d}" for i in range(20)),
    "subnets": "\n".join(f"net{i} 172.{16 + i}.0.0/16" for i in range(20)),
    "frontend": "authentik-server authentik-worker authentik-ldap avrana-portal avrana-kindle-connector olivetin",
    "ps": "c1\nc2\nc3",
    "modes": "/jellyfin net=host pid= ipc=private\n/avrana-portal net=authentik_frontend pid= ipc=private\n"
             "/olivetin-docker-ro net=none pid= ipc=private",
    "containers": {c: "running healthy 2026-10-01T00:00:00Z nets=authentik_frontend,"
                   for c in ("authentik-server", "avrana-portal", "avrana-kindle-connector", "olivetin")},
}
READ_ONLY_CALLS = {("version",), ("network", "ls"), ("network", "inspect"), ("ps",), ("inspect",)}
ROLLBACK_FILES = ["authentik/docker-compose.yml", "avrana-portal/docker-compose.yml",
                  "avrana-kindle-connector/docker-compose.yml", "olivetin/docker-compose.yml", "services-health.sh"]


@unittest.skipIf(BASH is None, "bash not available: preflight execution tests skipped")
class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "stub.py").write_text(STUB, encoding="utf-8")
        py = Path(sys.executable).as_posix()
        self.stub("docker", f'exec "{py}" "{(self.root / "stub.py").as_posix()}" "$@"\n')
        self.stub("python3", f'exec "{py}" "$@"\n')
        # Named curl-stub, passed via AVRANA_CURL: Git Bash puts /mingw64/bin (with a real curl) ahead of
        # PATH, so a stub merely named "curl" was bypassed once and real requests went out.
        self.curl_log = self.root / "curl.log"
        self.stub("curl-stub", f'echo "$@" >> "{self.curl_log.as_posix()}"\n'
                               'printf "%s" "${G1_CURL:-302 https://auth.avrana.net/application/o/authorize/}"\n')
        self.calls = self.root / "calls.log"
        self.backups = self.root / "backups"
        (self.backups / "avrana").mkdir(parents=True)
        self.status(self.backups / "avrana/LAST_RUN.json", "ok", 2)
        self.status(self.backups / "OFFHOST_LAST_RUN.json", "ok", 20)
        self.rollback = self.root / "rollback"
        sums = []
        for name in ROLLBACK_FILES:
            path = self.rollback / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"synthetic {name}\n", encoding="utf-8", newline="\n")
            sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
        (self.rollback / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    @staticmethod
    def status(path, value, age_hours):
        path.write_text(json.dumps({"status": value}), encoding="utf-8")
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))

    def run_preflight(self, scenario=None, args=("--rollback", None), env=None):
        scen = dict(HEALTHY, **(scenario or {}))
        (self.root / "scenario.json").write_text(json.dumps(scen), encoding="utf-8")
        argv = [a if a is not None else self.rollback.as_posix() for a in args]
        environ = {k: v for k, v in os.environ.items() if not k.startswith(("AVRANA_", "G1_"))}
        environ.update({"PATH": self.bin.as_posix() + os.pathsep + os.environ["PATH"],
                        "G1_SCENARIO": (self.root / "scenario.json").as_posix(), "G1_CALLS": self.calls.as_posix(),
                        "AVRANA_BACKUPS_DIR": self.backups.as_posix(),
                        "AVRANA_DOCKER_DAEMON_JSON": (self.root / "absent-daemon.json").as_posix(),
                        "AVRANA_CURL": (self.bin / "curl-stub").as_posix()})
        # Belt and braces: any real HTTP client that slips through goes to a dead local proxy.
        for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
            environ[var] = "http://127.0.0.1:9"
        environ.pop("NO_PROXY", None)
        environ.pop("no_proxy", None)
        environ.update(env or {})
        run = subprocess.run([BASH, SCRIPT.as_posix(), *argv], capture_output=True, text=True, env=environ, timeout=120)
        return run.returncode, run.stdout

    def lines(self, out, level):
        return [l for l in out.splitlines() if l.startswith(level)]

    def test_healthy_host_passes_with_no_stop_or_void(self):
        rc, out = self.run_preflight()
        self.assertEqual(rc, 0, out)
        self.assertIn("PREFLIGHT: 0 STOP, 0 VOID", out)
        for needle in ("address pool: 20 networks + 3 new <= 32", "not applied", "no net=container: among 3",
                       "rollback material: 5 files present", "local backup: ok", "off-host backup: ok"):
            self.assertIn(needle, out)
        self.assertIn("host-network containers (D-3 residual): /jellyfin", out)

    def test_docker_is_only_asked_to_list_and_inspect(self):
        self.run_preflight(args=("--rollback", None, "--e1"))
        calls = [json.loads(l) for l in self.calls.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(tuple(call[:1]) in READ_ONLY_CALLS or tuple(call[:2]) in READ_ONLY_CALLS, call)

    def test_pool_without_room_stops(self):
        rc, out = self.run_preflight({"net_ids": "\n".join(f"n{i}" for i in range(30))})
        self.assertEqual(rc, 1)
        self.assertTrue(any("address pool: 30 networks + 3 new exceeds 32" in l for l in self.lines(out, "STOP")), out)

    def test_network_namespace_borrower_stops_and_is_named(self):
        rc, out = self.run_preflight({"modes": HEALTHY["modes"] + "\n/evil net=container:abc123 pid= ipc=private"})
        self.assertEqual(rc, 1)
        self.assertIn("/evil net=container:abc123", out)
        self.assertTrue(any("namespace sharing" in l for l in self.lines(out, "STOP")))

    def test_pid_sharing_is_reported_but_is_not_a_network_stop(self):
        rc, out = self.run_preflight({"modes": HEALTHY["modes"] + "\n/p net=bridge pid=container:abc ipc=private"})
        self.assertEqual(rc, 0, out)
        self.assertIn("pid/ipc sharing", out)

    def test_unreadable_docker_is_void_never_pass(self):
        for broken in ({"ps": None}, {"modes": None}, {"net_ids": None}, {"subnets": None}, {"server": None},
                       {"frontend": None}):
            with self.subTest(broken=broken):
                rc, out = self.run_preflight(broken)
                self.assertEqual(rc, 1, out)
                self.assertTrue(self.lines(out, "VOID"), out)

    def test_already_existing_private_network_stops(self):
        rc, out = self.run_preflight({"existing_private": ["authentik_kindle"]})
        self.assertEqual(rc, 1)
        self.assertIn("already exist: authentik_kindle", out)

    def test_unhealthy_or_missing_container_stops(self):
        containers = dict(HEALTHY["containers"])
        containers["olivetin"] = "running unhealthy 2026-10-01T00:00:00Z nets=x,"
        del containers["avrana-portal"]
        rc, out = self.run_preflight({"containers": containers})
        self.assertEqual(rc, 1)
        stops = "\n".join(self.lines(out, "STOP"))
        self.assertIn("olivetin: running/unhealthy", stops)
        self.assertIn("avrana-portal: not found", stops)

    def test_backup_problems_stop(self):
        cases = [("avrana/LAST_RUN.json", "ok", 30, "stale"), ("avrana/LAST_RUN.json", "partial", 1, "status='partial'"),
                 ("OFFHOST_LAST_RUN.json", "ok", 60, "stale")]
        for rel, value, age, expect in cases:
            with self.subTest(file=rel, value=value, age=age):
                self.setUp()
                self.status(self.backups / rel, value, age)
                rc, out = self.run_preflight()
                self.assertEqual(rc, 1)
                self.assertTrue(any(expect in l for l in self.lines(out, "STOP")), out)
        self.setUp()
        (self.backups / "OFFHOST_LAST_RUN.json").unlink()
        rc, out = self.run_preflight()
        self.assertTrue(any("off-host backup: missing" in l for l in self.lines(out, "STOP")), out)

    def test_rollback_material_must_be_present_and_match(self):
        rc, out = self.run_preflight(args=())
        self.assertTrue(any("rollback material: not checked" in l for l in self.lines(out, "STOP")))
        (self.rollback / "olivetin/docker-compose.yml").write_text("tampered\n", encoding="utf-8", newline="\n")
        rc, out = self.run_preflight()
        self.assertTrue(any("SHA-256 mismatch" in l for l in self.lines(out, "STOP")), out)
        (self.rollback / "services-health.sh").unlink()
        rc, out = self.run_preflight()
        self.assertTrue(any("services-health.sh" in l for l in self.lines(out, "STOP")), out)

    def test_e1_passes_only_on_redirect_to_sign_in(self):
        rc, out = self.run_preflight(args=("--rollback", None, "--e1"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len([l for l in self.lines(out, "PASS") if l.startswith("PASS  E1 ")]), 6)
        self.assertEqual(len(self.curl_log.read_text(encoding="utf-8").splitlines()), 6, "the stub, not a real curl")
        rc, out = self.run_preflight(args=("--rollback", None, "--e1"), env={
            "G1_CURL": "302 https://avrana.net/outpost.goauthentik.io/start?rd=x"})
        self.assertEqual(len([l for l in self.lines(out, "PASS") if " E1 avrana.net" in l]), 2, out)
        for answer, level in (("200 ", "STOP"), ("404 ", "STOP"), ("302 https://evil.example/", "STOP"),
                              ("302 https://evil.example/outpost.goauthentik.io/start", "STOP"), ("000 ", "VOID")):
            with self.subTest(answer=answer):
                rc, out = self.run_preflight(args=("--rollback", None, "--e1"), env={"G1_CURL": answer})
                self.assertEqual(rc, 1)
                self.assertEqual(len([l for l in self.lines(out, level) if " E1 " in l]), 6, out)

    def test_bad_arguments_exit_2(self):
        for args in (("--rollback",), ("--apply",)):
            rc, _ = self.run_preflight(args=args)
            self.assertEqual(rc, 2, args)


class StaticReadOnlyTests(unittest.TestCase):
    def code(self):
        """Shell code only: comments and the embedded read-only Python heredoc (checked separately) removed."""
        text = re.sub(r"<<'PY'.*?\nPY\n", "<<'PY'\n", SCRIPT.read_text(encoding="utf-8"), flags=re.S)
        return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))

    def test_embedded_python_only_reads(self):
        body = re.search(r"<<'PY'.*?\nPY\n", SCRIPT.read_text(encoding="utf-8"), re.S).group(0)
        for word in (r"write", r"open\(", r"unlink", r"rename", r"subprocess", r"os\.system", r"mkdir"):
            self.assertNotRegex(body, word)

    def test_no_mutating_command_appears(self):
        code = self.code()
        for word in (r"docker\s+(run|rm|create|exec|start|stop|restart|kill|compose|system|volume|image|pull)",
                     r"docker\s+network\s+(create|rm|connect|disconnect|prune)", r"\bsystemctl\b", r"\bsudo\b",
                     r"\brm\b", r"\bmv\b", r"\bcp\b", r"\btee\b", r"\btouch\b", r"\bmkdir\b", r"\bchmod\b",
                     r"\bchown\b", r"\bkill\b", r"\bln\b", r"--data", r"-X\s*(POST|PUT|DELETE)"):
            with self.subTest(word=word):
                self.assertNotRegex(code, word)

    def test_redirections_only_to_dev_null_or_stderr(self):
        for target in re.findall(r"(?<![<0-9&])>{1,2}\s*([^\s;|)]+)", self.code()):
            self.assertIn(target, ("/dev/null", "&2"), target)

    def test_lf_line_endings_and_executable_shebang(self):
        data = SCRIPT.read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.startswith(b"#!/usr/bin/env bash\n"))


if __name__ == "__main__":
    unittest.main()
