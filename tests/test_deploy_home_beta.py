"""scripts/deploy-home-beta.sh, the half that runs on avrana (RC1): a dry run leaves nothing behind, and a plan that
reaches beyond Home stops before anything is recreated.

Runs the script's REMOTE block under bash with a stub `docker` on PATH in a temporary directory. The stub records
every call and prints a canned `up -d --dry-run` plan. No Docker, no ssh, no network, no production access. The
canned plan wording is the Compose v2 dry-run format as far as known; it is not checked against the host's Compose.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts/deploy-home-beta.sh").read_text(encoding="utf-8")
REMOTE = SCRIPT.split("<<'REMOTE'\n", 1)[1].split("\nREMOTE\n", 1)[0]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_network_isolation import BASH  # noqa: E402

RUNNING = "sha256:1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"
STUB = """#!/usr/bin/env bash
echo "$*" >> "$SIM/calls"
if [ "$1" = inspect ]; then
  case "$3" in
    *Image*) echo %s ;;
    *Health*) echo healthy ;;
    *working_dir*) echo "$SIM/root/home-old0000/services/avrana-home" ;;
  esac
fi
if [ "$1" = compose ]; then case "$*" in *--dry-run*) cat "$SIM/plan" ;; esac; fi
exit 0
""" % RUNNING
HOME_ONLY = "DRY-RUN MODE -  Container avrana-home-beta  Recreate\nDRY-RUN MODE -  Container avrana-home-beta  Recreated\n"


@unittest.skipIf(BASH is None, "bash not available: deploy script tests skipped")
class DeployRemoteHalf(unittest.TestCase):
    def run_remote(self, apply, plan):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Path(tmp)
            (sim / "bin").mkdir()
            live = sim / "live"
            for d in (live / "secrets", live / "state", sim / "root/home-new1234/services/avrana-home"):
                d.mkdir(parents=True)
            for f in ("beta-live.env", "docker-compose.beta-live.yml"):
                (live / f).write_text("x\n")
            (sim / "plan").write_text(plan)
            stub = sim / "bin/docker"
            stub.write_bytes(STUB.encode())
            stub.chmod(0o755)
            env = dict(os.environ, SIM=sim.as_posix(), APPLY=apply, SHA="new1234",
                       DIR=(sim / "root/home-new1234").as_posix(), LIVE=live.as_posix(), ROOT=(sim / "root").as_posix(),
                       PROJECT="avrana-home-beta", COMPOSE="docker-compose.beta-live.yml")
            env["PATH"] = (sim / "bin").as_posix() + os.pathsep + env["PATH"]
            done = subprocess.run([BASH, "-c", 'export PATH="$SIM/bin:$PATH"; ' + REMOTE], env=env,
                                  capture_output=True, text=True, timeout=60)
            calls = (sim / "calls").read_text().splitlines()
        return done, calls

    def test_a_dry_run_puts_the_local_tag_back_on_the_running_image(self):
        done, calls = self.run_remote("no", HOME_ONLY)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"tag {RUNNING} avrana-home-live:local", calls)
        self.assertFalse([c for c in calls if c.endswith(" up -d")])          # nothing recreated
        self.assertLess(calls.index(next(c for c in calls if c.endswith("build -q"))),
                        calls.index(f"tag {RUNNING} avrana-home-live:local"))

    def test_apply_keeps_a_rollback_tag_recreates_and_reports_the_revision(self):
        done, calls = self.run_remote("yes", HOME_ONLY)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"tag {RUNNING} avrana-home-live:pre-new1234", calls)
        self.assertTrue([c for c in calls if c.endswith(" up -d")])
        self.assertNotIn(f"tag {RUNNING} avrana-home-live:local", calls)     # the new image keeps :local
        self.assertIn("running revision:", done.stdout)
        self.assertIn("rollback: docker tag avrana-home-live:pre-new1234 avrana-home-live:local", done.stdout)

    def test_a_plan_touching_another_container_network_or_volume_stops_before_up(self):
        for plan in (HOME_ONLY + "DRY-RUN MODE -  Container jellyfin  Recreate\n",
                     "DRY-RUN MODE -  Network avrana_x  Creating\n",
                     "DRY-RUN MODE -  Volume avrana_y  Removing\n"):
            with self.subTest(plan=plan):
                done, calls = self.run_remote("yes", plan)
                self.assertEqual(done.returncode, 5, done.stdout + done.stderr)
                self.assertFalse([c for c in calls if c.endswith(" up -d")])
                self.assertFalse([c for c in calls if "pre-new1234" in c])
                self.assertIn(f"tag {RUNNING} avrana-home-live:local", calls)


if __name__ == "__main__":
    unittest.main()
