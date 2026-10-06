"""Offline tests for the backup verification tooling. No production access, no Docker, no zstd."""
import importlib.util
import json
import os
import pathlib
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
        self.assertEqual(24, len(restore.COMPONENT_DIRS))


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


if __name__ == "__main__":
    unittest.main()
