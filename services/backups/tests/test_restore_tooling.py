"""Offline tests for the backup verification tooling. No production access, no Docker, no zstd."""
import fnmatch
import glob
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

BACKUPS = pathlib.Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BACKUPS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


restore = load("restore_test", "restore-test.py")
offhost = load("offhost", "offhost-backup.py")


def required_components():
    names = set()
    for raw in (BACKUPS / "required-artifacts.txt").read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.startswith("#"):
            names.add(raw.split("|")[0].strip())
    return names


class RestoreMapTests(unittest.TestCase):
    def test_every_component_has_a_restore_path(self):
        rows = restore.read_restore_map(BACKUPS.parents[1])
        covered = {component for component, _, _, _ in rows}
        self.assertEqual(set(), set(restore.COMPONENT_DIRS.values()) - covered)

    def test_methods_are_known(self):
        known = {"copy", "copy-as", "untar", "psql", "mariadb", "reference"}
        for _, artifact, _, method in restore.read_restore_map(BACKUPS.parents[1]):
            self.assertIn(method, known, artifact)

    def test_cwa_key_is_renamed_on_restore(self):
        rows = {a: (d, m) for _, a, d, m in restore.read_restore_map(BACKUPS.parents[1])}
        destination, method = rows["calibre-web-automated/cwa.key"]
        self.assertEqual("copy-as", method)
        self.assertTrue(destination.endswith("/config/.key"))

    def test_components_match_the_required_artifact_list(self):
        listed = required_components() - {"completeness"}
        self.assertEqual(set(), listed - set(restore.COMPONENT_DIRS.values()))
        self.assertEqual(23, len(restore.COMPONENT_DIRS))


class RunSelectionTests(unittest.TestCase):
    def test_incomplete_runs_are_never_chosen(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("2026-10-01T09-00-00Z", "2026-10-02T09-00-00Z",
                         "2026-10-03T09-00-00Z.partial-failed", "2026-10-04T09-00-00Z.partial"):
                os.mkdir(os.path.join(root, name))
            self.assertEqual("2026-10-02T09-00-00Z", restore.newest_complete_run(root).name)
            self.assertEqual(["2026-10-01T09-00-00Z", "2026-10-02T09-00-00Z"],
                             [p.name for p in offhost.complete_runs(pathlib.Path(root))])

    def test_empty_root(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(restore.newest_complete_run(root))


class FingerprintTests(unittest.TestCase):
    def test_detects_a_sidecar_file(self):
        with tempfile.TemporaryDirectory() as root:
            run = pathlib.Path(root)
            (run / "a").mkdir()
            (run / "a/app.db").write_bytes(b"x" * 64)
            before = restore.fingerprint(run)
            self.assertEqual(before, restore.fingerprint(run))
            (run / "a/app.db-shm").write_bytes(b"")
            self.assertNotEqual(before, restore.fingerprint(run))


class SqliteCheckTests(unittest.TestCase):
    def make(self, directory, rows):
        path = pathlib.Path(directory) / "t.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE users (id INTEGER)")
        connection.executemany("INSERT INTO users VALUES (?)", [(i,) for i in range(rows)])
        connection.commit()
        connection.close()
        return path

    def test_populated_table_passes_and_empty_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            report = restore.Report()
            restore.sqlite_check(self.make(directory, 2), "t.db", ["users"], report)
            self.assertEqual([], report.failed)
        with tempfile.TemporaryDirectory() as directory:
            report = restore.Report()
            restore.sqlite_check(self.make(directory, 0), "t.db", ["users"], report)
            self.assertEqual(1, len(report.failed))

    def test_missing_table_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            report = restore.Report()
            restore.sqlite_check(self.make(directory, 1), "t.db", ["libraries"], report)
            self.assertEqual(1, len(report.failed))


class VerifyRequiredTests(unittest.TestCase):
    def run_verifier(self, run, listing):
        return subprocess.run([sys.executable, str(BACKUPS / "verify-required.py"), str(run), str(listing)],
                              capture_output=True, text=True)

    def test_missing_file_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            run = pathlib.Path(root) / "run"
            (run / "seerr").mkdir(parents=True)
            (run / "seerr/settings.json").write_text("{}")
            listing = pathlib.Path(root) / "list.txt"
            listing.write_text("seerr|file|seerr/settings.json\nseerr|file|seerr/db.sqlite3\n")
            result = self.run_verifier(run, listing)
            self.assertEqual(1, result.returncode)
            self.assertIn("MISSING|seerr|", result.stdout)
            (run / "seerr/db.sqlite3").write_text("x")
            self.assertEqual(0, self.run_verifier(run, listing).returncode)


class OffhostPolicyTests(unittest.TestCase):
    def test_run_must_be_ok_and_recent_enough_to_upload(self):
        self.assertTrue(offhost.eligible("2026-10-04T09-33-09Z", {"status": "ok", "dest": "/x/2026-10-04T09-33-09Z"}))
        self.assertFalse(offhost.eligible("2026-10-04T09-33-09Z", {"status": "partial", "dest": "/x/2026-10-04T09-33-09Z"}))
        self.assertFalse(offhost.eligible("2026-10-04T09-33-09Z.partial-failed", {"status": "ok"}))

    def test_monthly_name(self):
        self.assertEqual("2026-10", offhost.month_of("2026-10-04T09-33-09Z"))

    def test_remote_paths_never_use_sync_or_delete(self):
        source = (BACKUPS / "offhost-backup.py").read_text(encoding="utf-8")
        for forbidden in ('"sync"', '"delete"', '"purge"', '"move"', '"cleanup"', "--b2-hard-delete"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_marker_counts_regular_files_only(self):
        with tempfile.TemporaryDirectory() as root:
            run = pathlib.Path(root) / "2026-10-04T09-00-00Z"
            (run / "systemd/user/timers.target.wants").mkdir(parents=True)
            (run / "MANIFEST.txt").write_bytes(b"m" * 10)
            (run / "systemd/user/a.timer").write_bytes(b"t" * 5)
            try:
                os.symlink(run / "systemd/user/a.timer", run / "systemd/user/timers.target.wants/a.timer")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available here")
            self.assertEqual((2, 15, 1), offhost.inventory(run))
            marker = offhost.marker_document(run.name, offhost.inventory(run), "0" * 64)
            self.assertEqual((2, 2, 15, 1), (marker["marker_version"], marker["files"], marker["bytes"],
                                             marker["symlinks_skipped"]))


class RemoteRunsTests(unittest.TestCase):
    """The marker is found by listing the run directory; a failed check is an error, not absence."""

    def fake(self, responses):
        def rclone(arguments, **_):
            key = arguments[-1]
            code, out, err = responses[key]
            return subprocess.CompletedProcess(arguments, code, out, err)
        return rclone

    def run_with(self, responses):
        original = offhost.rclone
        offhost.rclone = self.fake(responses)
        try:
            return offhost.remote_runs("tier:")
        finally:
            offhost.rclone = original

    def test_marker_seen_in_directory_listing(self):
        runs = self.run_with({"tier:": (0, "2026-10-04T20-52-13Z/\n2026-10-05T09-31-09Z/\nstray/\n", ""),
                              "tier:2026-10-04T20-52-13Z/": (0, "MANIFEST.txt\nOFFHOST-COMPLETE.json\n", ""),
                              "tier:2026-10-05T09-31-09Z/": (0, "MANIFEST.txt\n", "")})
        self.assertEqual({"2026-10-04T20-52-13Z": True, "2026-10-05T09-31-09Z": False}, runs)

    def test_failed_check_is_an_error_not_absence(self):
        with self.assertRaises(RuntimeError):
            self.run_with({"tier:": (0, "2026-10-04T20-52-13Z/\n", ""),
                           "tier:2026-10-04T20-52-13Z/": (1, "", "403 download_cap_exceeded")})

    def test_empty_tier(self):
        self.assertEqual({}, self.run_with({"tier:": (3, "", "directory not found")}))


class BootTestHelpers(unittest.TestCase):
    def test_boot_tests_are_registered_and_ports_private(self):
        self.assertEqual({"abs", "komga", "jellyfin", "authentik"}, set(restore.BOOT_TESTS))
        self.assertEqual(2, len(set(restore.BOOT_PORTS.values())))   # Authentik stays on its internal network
        self.assertTrue(all(name.startswith("avrana-restore-test-") for name in
                            (restore.BOOT_PREFIX + "x", restore.BOOT_NETWORK)))

    def test_compose_image_parser(self):
        text = """services:
  postgresql:
    image: docker.io/library/postgres@sha256:aaaa  # 16
  server:
    container_name: authentik-server
    image: "ghcr.io/goauthentik/server@sha256:bbbb"
    command: server
  worker:
    image: ghcr.io/goauthentik/server@sha256:bbbb
"""
        original = restore.run_from_zstd
        restore.run_from_zstd = lambda path, command, **k: subprocess.CompletedProcess(command, 0, text, "")
        try:
            self.assertEqual("docker.io/library/postgres@sha256:aaaa", restore.compose_image(pathlib.Path("."), "m", "postgresql"))
            self.assertEqual("ghcr.io/goauthentik/server@sha256:bbbb", restore.compose_image(pathlib.Path("."), "m", "server"))
            self.assertIsNone(restore.compose_image(pathlib.Path("."), "m", "redis"))
        finally:
            restore.run_from_zstd = original

    def fake_producer(self, size):
        """Stands in for zstd: a process that writes `size` bytes to a pipe."""
        return subprocess.Popen([sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'x' * {size})"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def test_run_from_zstd_survives_a_consumer_that_exits_early(self):
        # 2026-10-06: psql exited on an error and zstd sat blocked on a full pipe for ever
        original = restore.zstd_stream
        restore.zstd_stream = lambda path: self.fake_producer(8 << 20)
        try:
            done = restore.run_from_zstd("x", [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1); sys.exit(3)"],
                                         timeout=60)
        finally:
            restore.zstd_stream = original
        self.assertEqual(3, done.returncode)

    def test_run_from_zstd_timeout_kills_both_sides(self):
        original = restore.zstd_stream
        restore.zstd_stream = lambda path: self.fake_producer(16)
        try:
            done = restore.run_from_zstd("x", [sys.executable, "-c", "import time; time.sleep(30)"], timeout=2)
        finally:
            restore.zstd_stream = original
        self.assertEqual(-1, done.returncode)

    def test_run_from_zstd_passes_the_stream_through(self):
        original = restore.zstd_stream
        restore.zstd_stream = lambda path: self.fake_producer(1000)
        try:
            done = restore.run_from_zstd("x", [sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
                                         text=True, timeout=60)
        finally:
            restore.zstd_stream = original
        self.assertEqual((0, "1000"), (done.returncode, done.stdout.strip()))


class OffhostMarkerTests(unittest.TestCase):
    """restore-test.py must verify the marker a downloaded run carries, not skip it."""

    MANIFEST = b"0" * 64 + b"  seerr/settings.json\n"
    SIZE = len(b"{}") + len(MANIFEST)

    def make_run(self, root, marker):
        run = pathlib.Path(root) / "2026-10-04T09-00-00Z"
        (run / "seerr").mkdir(parents=True)
        (run / "seerr/settings.json").write_bytes(b"{}")
        (run / "MANIFEST.txt").write_bytes(self.MANIFEST)
        if marker is not None:
            document = {"run": run.name, "manifest_sha256": restore.sha256_file(run / "MANIFEST.txt")}
            document.update(marker)
            (run / restore.OFFHOST_MARKER).write_text(json.dumps(document))
        return run

    def check(self, marker):
        with tempfile.TemporaryDirectory() as root:
            report = restore.Report()
            restore.check_offhost_marker(self.make_run(root, marker), report)
            return report

    def test_local_run_without_marker_is_not_checked(self):
        report = self.check(None)
        self.assertEqual(([], [], []), (report.passed, report.failed, report.warned))

    def test_version_2_marker_passes_when_hash_and_counts_match(self):
        report = self.check({"marker_version": 2, "files": 2, "bytes": self.SIZE})
        self.assertEqual([], report.failed)
        self.assertEqual(2, len(report.passed))

    def test_wrong_manifest_hash_fails(self):
        report = self.check({"marker_version": 2, "files": 2, "bytes": self.SIZE, "manifest_sha256": "f" * 64})
        self.assertEqual(1, len(report.failed))
        self.assertIn("hash mismatch", report.failed[0])

    def test_version_2_count_mismatch_fails(self):
        report = self.check({"marker_version": 2, "files": 3, "bytes": self.SIZE})
        self.assertEqual(1, len(report.failed))

    def test_version_1_count_mismatch_warns_but_hash_is_still_enforced(self):
        report = self.check({"files": 15, "bytes": 9999})
        self.assertEqual(([], 1), (report.failed, len(report.warned)))
        report = self.check({"files": 15, "bytes": 9999, "manifest_sha256": "f" * 64})
        self.assertEqual(1, len(report.failed))

    def test_unreadable_marker_fails(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.make_run(root, None)
            (run / restore.OFFHOST_MARKER).write_text("{not json")
            report = restore.Report()
            restore.check_offhost_marker(run, report)
            self.assertEqual(1, len(report.failed))

    def test_retired_component_in_an_older_run_is_tolerated(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.make_run(root, None)
            (run / "kavita").mkdir()
            (run / "kavita/kavita.db").write_bytes(b"x")
            report = restore.Report()
            restore.check_restore_map(run, BACKUPS.parents[1], report)
            self.assertFalse([line for line in report.failed if "kavita" in line])
            report = restore.Report()
            restore.check_components(run, report)
            self.assertFalse([line for line in report.failed if "kavita" in line])

    def test_marker_is_not_an_undocumented_restore_payload(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.make_run(root, {"marker_version": 2, "files": 2, "bytes": self.SIZE})
            report = restore.Report()
            restore.check_restore_map(run, BACKUPS.parents[1], report)
            self.assertFalse([line for line in report.failed if restore.OFFHOST_MARKER in line])
            (run / "stray.bin").write_bytes(b"x")
            report = restore.Report()
            restore.check_restore_map(run, BACKUPS.parents[1], report)
            self.assertTrue([line for line in report.failed if "stray.bin" in line])


class StackConfigAllowlistTests(unittest.TestCase):
    """S-04: Home's deployment record and member state must be in the stack-config allowlist and proven by the
    restore verifier. The allowlist is read from avrana-backup.sh and matched against a temporary tree."""

    ARCHIVE = "stack-config/stack-config.tar.zst"

    def allowlist(self):
        text = (BACKUPS / "avrana-backup.sh").read_text(encoding="utf-8")
        body = text.split("backup_stack_config() {", 1)[1].split(chr(10) + "}", 1)[0]
        loop = body.split("for p in", 1)[1].split("; do", 1)[0]
        return [m.group(1) for m in re.finditer(r'"\$REPO"/([^ "]+)', loop)]

    def covered(self, relpath):
        for root in self.allowlist():
            if fnmatch.fnmatchcase(relpath, root) or fnmatch.fnmatchcase(relpath, root + "/*"):
                return True
        return False

    def test_home_compose_record_and_state_are_collected(self):
        with tempfile.TemporaryDirectory() as repo:
            tree = pathlib.Path(repo) / "services/avrana-home"
            (tree / "state").mkdir(parents=True)
            for name in ("docker-compose.beta-live.yml", "state/identity_bindings.json", "state/.lock",
                         "state/komga_member_keys"):
                (tree / name).write_text("x", encoding="utf-8")
            matched = set()
            for pattern in self.allowlist():
                for hit in glob.glob(os.path.join(repo, pattern)):
                    matched.add(pathlib.Path(hit).relative_to(repo).as_posix())
            self.assertIn("services/avrana-home/docker-compose.beta-live.yml", matched)
            self.assertIn("services/avrana-home/state", matched)

    def collect(self, repo):
        """Run the real collection loop from avrana-backup.sh under bash against a temp tree."""
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not available")
        text = (BACKUPS / "avrana-backup.sh").read_text(encoding="utf-8")
        body = text.split("backup_stack_config() {", 1)[1].split(chr(10) + "}", 1)[0]
        loop = "for p in" + body.split("for p in", 1)[1].split("shopt -u nullglob", 1)[0]
        script = "REPO=" + pathlib.Path(repo).as_posix() + "; paths=(); shopt -s nullglob" + chr(10) + loop + (
            chr(10) + 'printf "%s\n" "${paths[@]}"')
        done = subprocess.run([bash, "-c", script], capture_output=True, text=True, check=True)
        return done.stdout.split()

    def test_absent_home_paths_are_skipped_not_passed_to_tar(self):
        with tempfile.TemporaryDirectory() as repo:
            root = pathlib.Path(repo)
            (root / "scripts").mkdir()
            (root / "scripts" / "a.sh").write_text("x", encoding="utf-8")
            paths = self.collect(repo)
            self.assertIn("scripts", paths)
            self.assertNotIn("services/avrana-home/state", paths)
            self.assertNotIn("services/avrana-home/docker-compose.beta-live.yml", paths)
            # Only the two Home paths are optional: a missing mandatory path stays listed so tar fails loudly.
            for mandatory in ("kern_secrets", "services/recyclarr/config/state", ".env"):
                self.assertIn(mandatory, paths)

    def test_present_home_paths_are_listed(self):
        with tempfile.TemporaryDirectory() as repo:
            home = pathlib.Path(repo) / "services/avrana-home"
            (home / "state").mkdir(parents=True)
            (home / "docker-compose.beta-live.yml").write_text("x", encoding="utf-8")
            paths = self.collect(repo)
            self.assertIn("services/avrana-home/state", paths)
            self.assertIn("services/avrana-home/docker-compose.beta-live.yml", paths)

    def test_required_home_members_are_covered_by_the_allowlist(self):
        members = []
        for raw in (BACKUPS / "required-artifacts.txt").read_text(encoding="utf-8").splitlines():
            parts = raw.strip().split("|")
            if len(parts) == 4 and parts[1] == "member" and parts[2] == self.ARCHIVE:
                members.append(parts[3])
        for needed in ("services/avrana-home/docker-compose.beta-live.yml",
                       "services/avrana-home/state/identity_bindings.json"):
            self.assertIn(needed, members)
        for member in members:
            if member.startswith("services/avrana-home/"):
                self.assertTrue(self.covered(member), member)


if __name__ == "__main__":
    unittest.main()
