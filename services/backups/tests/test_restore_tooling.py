"""Offline tests for the backup verification tooling. No production access, no Docker, no zstd."""
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
