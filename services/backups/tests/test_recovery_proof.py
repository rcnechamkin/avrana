"""AVR-792 / AVR-350 / AVR-388: backups and failure alerts, proved on a disposable host (recovery_fixture.py).

Each failure path runs the real script against a fixture tree and a real SMTP conversation on loopback. No production
access, no Docker, no rclone, no cloud credential. A POSIX host with bash and tar is required: Windows skips this module
and CI runs it twice, in offline-tests and in backup-recovery-proof.yml, the latter with real zstd and openssl.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import recovery_fixture as fixture  # noqa: E402

POSIX = os.name == "posix" and shutil.which("bash") and shutil.which("tar")
REAL = os.environ.get("AVRANA_REQUIRE_REAL_TOOLS") == "1"
RUN = "2026-10-30T09-33-24Z"
STATE_MEMBERS = ("identity_bindings.json", "komga_member_keys", "komga_member_keys.ids")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        if REAL:
            self.assertTrue(shutil.which("zstd") and shutil.which("openssl"), "real zstd and openssl are required here")
        if not POSIX or not shutil.which("openssl"):
            self.skipTest("needs bash, tar and openssl on a POSIX host (CI runs this)")
        self.directory = tempfile.TemporaryDirectory(prefix="avrana-recovery-")
        self.addCleanup(self.directory.cleanup)
        self.host = fixture.Host(pathlib.Path(self.directory.name) / "host")
        self.sink = fixture.SmtpSink(self.directory.name)
        self.addCleanup(self.sink.close)
        os.environ["SSL_CERT_FILE"] = str(self.sink.certificate)
        self.addCleanup(os.environ.pop, "SSL_CERT_FILE", None)
        self.host.configure_alerts(self.sink)
        self.keep = self.host.backups / "2026-10-20T09-30-00Z"      # an older good run that must survive every failure
        self.keep.mkdir()

    def mails(self):
        return "\n".join(self.sink.messages)

    def assert_no_data_in_mail(self):
        text = self.mails()
        for secret in (fixture.SMTP_PASSWORD, *fixture.MEMBER_KEYS.values(), *fixture.MEMBER_KEYS, "member-a"):
            self.assertNotIn(secret, text)


class CleanRun(Base):
    def test_a_clean_run_exits_zero_and_mails_nothing(self):
        done = self.host.backup()
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        last = self.host.last_run()
        self.assertEqual(("ok", [], []), (last["status"], last["failed"], last["guard"]))
        self.assertEqual([], self.sink.messages)
        self.assertEqual("ok", self.host.transport()["status"])
        self.assertEqual(0, self.host.script(fixture.BACKUPS / "verify-required.py", last["dest"],
                                             self.host.repo / "services/backups/required-artifacts.txt").returncode)


class SourceFailures(Base):
    def assert_failed(self, done, component):
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)
        last = self.host.last_run()
        self.assertEqual("partial", last["status"])
        self.assertIn(component, last["failed"])
        self.assertTrue(last["dest"].endswith(".partial-failed"))
        self.assertTrue(self.keep.is_dir())
        self.assertEqual(1, len(self.sink.messages))
        self.assertIn(component, self.mails())
        self.assert_no_data_in_mail()

    def test_a_missing_source_fails_the_run_and_mails(self):
        (self.host.repo / "services/komga/config/database.sqlite").unlink()
        self.assert_failed(self.host.backup(), "komga")

    def test_a_failed_database_dump_fails_the_run(self):
        (self.host.root / "fail-exec-authentik-postgresql").write_text("")
        self.assert_failed(self.host.backup(), "authentik")

    def test_missing_home_state_fails_verification(self):
        for name in STATE_MEMBERS:
            with self.subTest(name):
                path = self.host.repo / "services/avrana-home/state" / name
                saved = path.read_bytes()
                path.unlink()
                self.sink.messages.clear()
                self.assert_failed(self.host.backup(), "stack-config")
                self.assertIn(name, self.mails())
                path.write_bytes(saved)

    def test_an_emptied_bindings_file_fails_verification(self):
        path = self.host.repo / "services/avrana-home/state/identity_bindings.json"
        path.write_text("")
        self.assert_failed(self.host.backup(), "stack-config")

    def test_missing_home_folder_fails(self):
        shutil.rmtree(self.host.repo / "services/avrana-home/state")
        self.assert_failed(self.host.backup(), "stack-config")


class DiskAndAbort(Base):
    def test_low_disk_aborts_and_mails(self):
        done = self.host.backup(AVRANA_BACKUP_MIN_FREE_GB="999999")
        self.assertEqual(3, done.returncode)
        self.assertEqual("aborted", self.host.last_run()["status"])
        self.assertIn("free on the backup volume", self.mails())

    def test_array_not_mounted_aborts_mails_and_writes_nothing(self):
        (self.host.root / "array-unmounted").write_text("")
        before = sorted(p.name for p in self.host.backups.iterdir())
        done = self.host.backup()
        self.assertEqual(4, done.returncode)
        self.assertEqual(before, sorted(p.name for p in self.host.backups.iterdir()))
        self.assertIn("not a mount point", self.mails())

    def test_a_disk_that_fills_while_writing_the_manifest_fails_the_run(self):
        self.host.tool("sha256sum", 'echo "No space left on device" >&2; exit 1')
        done = self.host.backup()
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertEqual("partial", self.host.last_run()["status"])
        self.assertIn("manifest", self.host.last_run()["failed"])

    def test_a_result_file_that_cannot_be_written_fails_the_run(self):
        (self.host.backups / "LAST_RUN.json").mkdir()
        done = self.host.backup()
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertIn("last-run", self.mails())

    def test_a_run_stopped_by_systemd_still_mails(self):
        (self.host.root / "hang").write_text("")
        process = subprocess.Popen(["bash", str(self.host.repo / "services/backups/avrana-backup.sh")],
                                   env=self.host.env(), start_new_session=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 30
        while time.time() < deadline and not list(self.host.backups.glob("*.partial")):
            time.sleep(0.1)
        time.sleep(1)
        os.killpg(process.pid, signal.SIGTERM)                # systemd signals the whole control group
        self.assertEqual(143, process.wait(timeout=30))
        self.assertIn("stopped by a signal", self.mails())


class AlertTransport(Base):
    def test_absent_transport_is_a_loud_failure_of_a_good_run(self):
        self.host.alert_env.unlink()
        done = self.host.backup()
        self.assertEqual(6, done.returncode, done.stdout + done.stderr)
        last = self.host.last_run()
        self.assertEqual("ok", last["status"])                 # the data is good: it rotates and goes off-host
        self.assertFalse(last["dest"].endswith(".partial-failed"))
        self.assertIn("alert transport", " ".join(last["guard"]))
        marker = self.host.transport()
        self.assertEqual(("not_configured", 3), (marker["status"], marker["rc"]))
        self.assertIn("ERROR", done.stdout)
        self.assertIn("ALERT NOT DELIVERED", done.stdout)
        self.assertIn(".env.alert absent", done.stdout + done.stderr)

    def test_a_rejected_login_is_a_loud_failure(self):
        self.host.configure_alerts(self.sink, password="a-retired-password")
        done = self.host.backup()
        self.assertEqual(6, done.returncode, done.stdout)
        self.assertEqual(("undeliverable", 5), (self.host.transport()["status"], self.host.transport()["rc"]))
        self.assertIn(False, self.sink.logins)
        self.assertNotIn("a-retired-password", done.stdout + done.stderr)

    def test_an_unsafe_settings_file_is_a_loud_failure(self):
        os.chmod(self.host.alert_env, 0o644)
        self.assertEqual(6, self.host.backup().returncode)
        self.assertEqual(("rejected", 4), (self.host.transport()["status"], self.host.transport()["rc"]))

    def test_a_missing_alert_script_is_a_loud_failure(self):
        (self.host.repo / "scripts/avrana-alert.py").unlink()
        done = self.host.backup()
        self.assertEqual(6, done.returncode, done.stdout)
        self.assertEqual("undeliverable", self.host.transport()["status"])

    def test_failed_run_with_no_transport_reports_both(self):
        self.host.alert_env.unlink()
        (self.host.repo / "services/komga/config/database.sqlite").unlink()
        done = self.host.backup()
        self.assertEqual(1, done.returncode)
        self.assertIn("ALERT NOT DELIVERED", done.stdout)
        self.assertEqual("partial", self.host.last_run()["status"])
        self.assertEqual("not_configured", self.host.transport()["status"])

    def alert(self, *arguments, stdin=""):
        return self.host.script(self.host.repo / "scripts/avrana-alert.py", *arguments, stdin=stdin)

    def test_self_test_delivers_one_fixed_message_over_tls_and_ignores_stdin(self):
        done = self.alert("--self-test", stdin="password=should-not-appear\n")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(1, len(self.sink.messages))
        self.assertEqual([True], self.sink.logins)
        self.assertIn("alert self-test", self.mails())
        self.assertIn("carries no data", self.mails())
        self.assertNotIn("should-not-appear", self.mails())
        self.assertEqual("self-test", self.host.transport()["mode"])
        self.assertTrue(self.host.transport()["last_ok_at"])

    def test_self_test_reports_an_absent_transport(self):
        self.host.alert_env.unlink()
        self.assertEqual(3, self.alert("--self-test").returncode)
        self.assertEqual(3, self.host.transport()["rc"])

    def test_last_success_survives_a_later_failure(self):
        self.alert("--self-test")
        worked = self.host.transport()["last_ok_at"]
        self.host.alert_env.unlink()
        self.alert("--self-test")
        self.assertEqual(worked, self.host.transport()["last_ok_at"])

    def test_secrets_never_reach_the_message(self):
        body = (f"tool said password={fixture.SMTP_PASSWORD} token: abc123 Authorization: Bearer abc.def\n"
                "https://user:hunter2@b2.example/x?sig=abc\nkey 0123456789abcdef0123456789abcdef for a@fixture.test\n")
        self.assertEqual(0, self.alert("--subject", "api_key=zzz failed", stdin=body).returncode)
        text = self.mails()
        for secret in (fixture.SMTP_PASSWORD, "abc123", "abc.def", "hunter2", "sig=abc", "zzz",
                       "0123456789abcdef0123456789abcdef", "a@fixture.test"):
            self.assertNotIn(secret, text)
        self.assertIn("tool said", text)


class Drift(Base):
    def test_an_edited_script_fails_the_run_and_names_only_the_file(self):
        script = self.host.repo / "services/backups/verify-required.py"
        script.write_text(script.read_text() + "# hand edit\n")
        done = self.host.backup()
        self.assertEqual(6, done.returncode, done.stdout)
        self.assertIn("verify-required.py", " ".join(self.host.last_run()["guard"]))
        self.assertIn("verify-required.py", self.mails())
        self.assertNotIn("hand edit", self.mails())

    def behind_git(self):
        """The 2026-10-30 failure: the tree agrees with its own list, and Git has moved on."""
        export = self.host.deploy / "home-1da4e86/services/backups/INSTALLED-FILES.sha256"
        export.parent.mkdir(parents=True)
        lines = (self.host.repo / "services/backups/INSTALLED-FILES.sha256").read_text().splitlines()
        lines[1] = "0" * 64 + lines[1][64:]
        export.write_text("\n".join(lines) + "\n")

    def test_a_tree_behind_git_is_caught_by_the_deployed_baseline(self):
        self.assertEqual(0, self.host.backup().returncode)
        self.sink.messages.clear()
        self.behind_git()
        done = self.host.backup()
        self.assertEqual(6, done.returncode, done.stdout)
        self.assertIn("avrana-backup.sh", self.mails())

    def test_summary_names_a_missing_git_baseline(self):
        done = self.host.script(self.host.repo / "services/backups/backup-guard.py", "drift")
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertIn("no deployed Git baseline yet", done.stdout)

    def test_a_missing_hash_list_is_drift(self):
        (self.host.repo / "services/backups/INSTALLED-FILES.sha256").unlink()
        self.assertEqual(6, self.host.backup().returncode)

    def test_preinstall_names_a_required_file_the_host_lacks(self):
        source = self.host.root / "source"
        (source / "services/backups").mkdir(parents=True)
        shutil.copy(self.host.repo / "services/backups/required-artifacts.txt", source / "services/backups")
        shutil.copy(self.host.repo / "services/backups/INSTALLED-FILES.sha256", source / "services/backups")
        lines = (source / "services/backups/INSTALLED-FILES.sha256").read_text().splitlines()
        keep = [line for line in lines if line.endswith("required-artifacts.txt")]
        (source / "services/backups/INSTALLED-FILES.sha256").write_text("\n".join(keep) + "\n")
        guard = self.host.repo / "services/backups/backup-guard.py"
        self.assertEqual(0, self.host.script(guard, "preinstall", "--source", source).returncode)
        (self.host.repo / "services/avrana-home/state/komga_member_keys.ids").write_text("")
        done = self.host.script(guard, "preinstall", "--source", source)
        self.assertEqual(1, done.returncode)
        self.assertIn("MISSING|services/avrana-home/state/komga_member_keys.ids", done.stdout)
        (source / "services/backups/required-artifacts.txt").write_text("changed\n")
        self.assertIn("SOURCE|", self.host.script(guard, "preinstall", "--source", source).stdout)


class Offhost(Base):
    def prepare(self):
        self.assertEqual(0, self.host.backup().returncode)
        shutil.rmtree(self.keep)
        conf = self.host.root / "rclone.conf"
        conf.write_text("[fixture]\n")
        os.chmod(conf, 0o600)
        self.sink.messages.clear()

    def upload(self):
        return self.host.script(self.host.repo / "services/backups/offhost-backup.py")

    def state(self):
        return json.loads(self.host.offhost_state.read_text())

    def test_a_good_upload_is_marked_complete(self):
        self.prepare()
        done = self.upload()
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual("ok", self.state()["status"])
        self.assertEqual(1, len(list((self.host.remote / "daily").rglob("OFFHOST-COMPLETE.json"))))

    def test_rclone_failure_marks_nothing_and_mails(self):
        self.prepare()
        (self.host.root / "fail-rclone").write_text("copy")
        self.assertEqual(1, self.upload().returncode)
        self.assertEqual("failed", self.state()["status"])
        self.assertEqual([], list(self.host.remote.rglob("OFFHOST-COMPLETE.json")))
        self.assertIn("off-host backup FAILED", self.mails())

    def test_encryption_check_failure_marks_nothing_and_mails_no_secret(self):
        self.prepare()
        (self.host.root / "fail-rclone").write_text("cryptcheck")
        self.assertEqual(1, self.upload().returncode)
        self.assertEqual([], list(self.host.remote.rglob("OFFHOST-COMPLETE.json")))
        self.assertIn("off-host backup FAILED", self.mails())
        self.assertNotIn("should-not-reach-mail", self.mails())

    def test_failure_with_no_transport_is_loud(self):
        self.prepare()
        (self.host.root / "fail-rclone").write_text("copy")
        self.host.alert_env.unlink()
        done = self.upload()
        self.assertEqual(1, done.returncode)
        self.assertIn("ALERT NOT DELIVERED", done.stdout)


class Watchdog(Base):
    def healthy(self):
        self.assertEqual(0, self.host.backup().returncode)
        now = self.utc(0)
        self.host.offhost_state.write_text(json.dumps({"status": "ok", "at": now}))
        (self.host.backups / "RESTORE_TEST_LAST.json").write_text(json.dumps({"status": "ok", "at": now}))
        self.sink.messages.clear()

    def utc(self, hours_ago):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours_ago * 3600))

    def run_name(self, hours_ago):
        return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime(time.time() - hours_ago * 3600))

    def watchdog(self, *flags):
        return self.host.script(self.host.repo / "services/backups/backup-guard.py", "watchdog", *flags)

    def age_everything(self, hours):
        """What a dead timer looks like after `hours`: nothing new appeared, the last run simply got old."""
        last = self.host.last_run()
        run = pathlib.Path(last["dest"])
        run.rename(run.with_name(self.run_name(hours)))
        last["at"] = self.utc(hours)
        (self.host.backups / "LAST_RUN.json").write_text(json.dumps(last))

    def test_a_healthy_chain_passes_silently(self):
        self.healthy()
        done = self.watchdog()
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertEqual([], self.sink.messages)

    def test_a_dead_timer_is_detected_with_no_failure_from_the_job(self):
        self.healthy()
        (self.host.root / "dead-timers").write_text("avrana-backup.timer\n")
        self.age_everything(30)
        done = self.watchdog()
        self.assertEqual(1, done.returncode, done.stdout)
        self.assertIn("avrana-backup.timer is inactive", done.stdout)
        self.assertIn("stale", done.stdout)
        self.assertIn("newest complete run is 30 h old", self.mails())

    def test_a_stopped_offhost_copy_is_detected(self):
        self.healthy()
        self.host.offhost_state.write_text(json.dumps({"status": "ok", "at": self.utc(60)}))
        self.assertIn("off-host: stale", self.watchdog().stdout)

    def test_no_result_at_all_is_detected(self):
        self.healthy()
        (self.host.backups / "LAST_RUN.json").unlink()
        self.assertIn("backup: no result file", self.watchdog().stdout)

    def test_a_good_last_run_file_does_not_hide_a_week_of_partial_runs(self):
        self.healthy()
        last = self.host.last_run()
        run = pathlib.Path(last["dest"])
        run.rename(run.with_name(self.run_name(100) + ".partial-failed"))
        self.assertEqual(1, self.watchdog().returncode)
        self.assertIn("no complete run", self.mails() + self.watchdog("--no-alert").stdout)

    def test_same_problem_mails_once_and_recovery_mails_once(self):
        self.healthy()
        (self.host.root / "dead-timers").write_text("avrana-backup.timer\n")
        self.watchdog()
        self.watchdog()
        self.assertEqual(1, len(self.sink.messages))
        (self.host.root / "dead-timers").unlink()
        self.assertEqual(0, self.watchdog().returncode)
        self.assertEqual(0, self.watchdog().returncode)
        self.assertEqual(2, len(self.sink.messages))
        self.assertIn("RECOVERED", self.sink.messages[1])

    def test_undeliverable_alert_is_its_own_exit_code(self):
        self.healthy()
        self.host.alert_env.unlink()
        self.host.script(self.host.repo / "scripts/avrana-alert.py", "--check")
        done = self.watchdog()
        self.assertEqual(3, done.returncode, done.stdout)
        self.assertIn("alert transport: last attempt failed", done.stdout)
        self.assertIn("ALERT NOT DELIVERED", done.stdout)

    def test_a_guard_failure_recorded_by_the_run_is_reported(self):
        self.healthy()
        last = self.host.last_run()
        last["guard"] = ["installed scripts differ from Git: 1 file(s)"]
        (self.host.backups / "LAST_RUN.json").write_text(json.dumps(last))
        self.assertIn("backup guard: installed scripts", self.watchdog().stdout)


class EncryptedRestore(Base):
    """Backup run -> encrypted archive -> decrypt into scratch -> Home state recreated, compared byte for byte.

    The stand-in for rclone crypt is `openssl enc`: this proves the chain and the restore logic, not rclone's format,
    which only the owner's drill can (rc3-backup-restore-proof.md).
    """

    def complete_run(self):
        self.assertEqual(0, self.host.backup().returncode)
        return pathlib.Path(self.host.last_run()["dest"])

    def encrypt(self, run):
        self.key = pathlib.Path(self.directory.name) / "crypt.key"
        self.key.write_text(hashlib.sha256(os.urandom(32)).hexdigest())
        clear = pathlib.Path(self.directory.name) / "run.tar"
        with tarfile.open(clear, "w") as archive:
            archive.add(run, arcname=run.name)
        sealed = pathlib.Path(self.directory.name) / "run.tar.enc"
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", str(clear), "-out", str(sealed),
                        "-pass", f"file:{self.key}"], check=True, capture_output=True)
        clear.unlink()
        return sealed

    def decrypt(self, sealed, into, key=None):
        into.mkdir()
        clear = into / "run.tar"
        done = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", str(sealed), "-out", str(clear),
                               "-pass", f"file:{key or self.key}"], capture_output=True)
        if done.returncode != 0:
            return None
        with tarfile.open(clear) as archive:
            archive.extractall(into, filter="data")
        clear.unlink()
        return next(path for path in into.iterdir() if path.is_dir())

    def restore(self, run, dest):
        return self.host.script(self.host.repo / "services/backups/restore-home-state.py", run, "--dest", dest)

    def test_home_state_comes_back_intact_from_an_encrypted_copy(self):
        run = self.complete_run()
        sealed = self.encrypt(run)
        for secret in (b"identity_bindings", fixture.MEMBER_KEYS["a@fixture.test"].encode()):
            self.assertNotIn(secret, sealed.read_bytes())
        scratch = pathlib.Path(self.directory.name) / "download"
        copy = self.decrypt(sealed, scratch)
        dest = scratch / "home-state"
        done = self.restore(copy, dest)
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertIn("2 bindings, 2 member keys, 2 key ids", done.stdout)
        live = self.host.repo / "services/avrana-home/state"
        for name in STATE_MEMBERS:
            self.assertEqual((live / name).read_bytes(), (dest / name).read_bytes(), name)
            self.assertEqual(0o600, (dest / name).stat().st_mode & 0o777)
        self.assertEqual(0o700, dest.stat().st_mode & 0o777)
        for secret in (fixture.MEMBER_KEYS["a@fixture.test"], "a@fixture.test", "member-a", "a" * 64):
            self.assertNotIn(secret, done.stdout)

    def test_the_wrong_key_opens_nothing(self):
        sealed = self.encrypt(self.complete_run())
        wrong = pathlib.Path(self.directory.name) / "wrong.key"
        wrong.write_text("wrong")
        self.assertIsNone(self.decrypt(sealed, pathlib.Path(self.directory.name) / "bad", key=wrong))

    def test_it_never_overwrites(self):
        run = self.complete_run()
        taken = pathlib.Path(self.directory.name) / "taken"
        taken.mkdir()
        (taken / "keep").write_text("mine")
        self.assertEqual(2, self.restore(run, taken).returncode)
        self.assertEqual(["keep"], [p.name for p in taken.iterdir()])

    def test_it_refuses_production_and_the_run_itself(self):
        run = self.complete_run()
        for dest in ("/home/cody/avrana/services/avrana-home/state", "/home/cody/docker/x", run / "x",
                     pathlib.Path(self.directory.name) / "services/avrana-home/state"):
            with self.subTest(str(dest)):
                done = self.restore(run, dest)
                self.assertEqual(2, done.returncode, done.stdout)
                self.assertFalse(os.path.lexists(dest))

    def rewrite(self, run, change):
        """Replace the run's archive with a hostile or damaged one, and fix its manifest so only `change` is tested."""
        archive = run / "stack-config/stack-config.tar.zst"
        work = pathlib.Path(self.directory.name) / "hostile"
        work.mkdir()
        (work / "services/avrana-home/state").mkdir(parents=True)
        change(work)
        raw = work.parent / "hostile.tar"
        with tarfile.open(raw, "w") as tar:
            tar.add(work / "services", arcname="services")
            if (work / "extra.tar").exists():
                with tarfile.open(work / "extra.tar") as extra:
                    for member in extra:
                        tar.addfile(member)
        subprocess.run(f'zstd -q -f -o "{archive}" < "{raw}"', shell=True, check=True, env=self.host.env())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = run / "MANIFEST.txt"
        lines = [digest + "  ./stack-config/stack-config.tar.zst" if line.endswith("stack-config.tar.zst") else line
                 for line in manifest.read_text().splitlines()]
        manifest.write_text("\n".join(lines) + "\n")

    def test_a_link_or_a_climbing_path_stops_the_restore(self):
        run = self.complete_run()

        def hostile(work):
            with tarfile.open(work / "extra.tar", "w") as tar:
                link = tarfile.TarInfo("services/avrana-home/state/../../../../escape")
                link.size = 0
                tar.addfile(link)
        self.rewrite(run, hostile)
        dest = pathlib.Path(self.directory.name) / "out"
        self.assertEqual(1, self.restore(run, dest).returncode)
        self.assertFalse(dest.exists())

    def test_a_tampered_archive_is_refused_by_the_manifest(self):
        run = self.complete_run()
        with open(run / "stack-config/stack-config.tar.zst", "ab") as handle:
            handle.write(b"tampered")
        done = self.restore(run, pathlib.Path(self.directory.name) / "out")
        self.assertEqual(1, done.returncode)
        self.assertIn("does not match MANIFEST", done.stdout)

    def test_truncated_state_fails_verification(self):
        run = self.complete_run()

        def damaged(work):
            state = work / "services/avrana-home/state"
            (state / "identity_bindings.json").write_text(json.dumps(fixture.BINDINGS))
            (state / "komga_member_keys").write_text('{"a@fixture.test": "not-a-key"}')
            (state / "komga_member_keys.ids").write_text("{}")
        self.rewrite(run, damaged)
        dest = pathlib.Path(self.directory.name) / "out"
        self.assertEqual(1, self.restore(run, dest).returncode)
        self.assertFalse(dest.exists())

    def test_the_restore_test_proves_home_state(self):
        restore = load("restore_test_proof", self.host.repo / "services/backups/restore-test.py")
        report = restore.Report()
        work = pathlib.Path(self.directory.name) / "work"
        work.mkdir()
        run = self.complete_run()
        environment = dict(os.environ)
        os.environ.update(PATH=self.host.env()["PATH"])
        try:
            restore.check_home_state(run, work, report)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        self.assertEqual([], report.failed)
        self.assertIn("2 bindings", report.passed[0])


class Repository(unittest.TestCase):
    """Checks on what the repository ships. These need no POSIX host."""

    def test_hash_list_is_current_and_covers_every_guarded_file(self):
        guard = load("backup_guard_repo", fixture.BACKUPS / "backup-guard.py")
        self.assertEqual(0, guard.hashes(False))
        listed = guard.read_list(fixture.BACKUPS / "INSTALLED-FILES.sha256")
        self.assertEqual(set(guard.INSTALLED), set(listed))

    def test_alert_path_no_longer_discards_the_failure(self):
        text = (fixture.BACKUPS / "avrana-backup.sh").read_text(encoding="utf-8")
        body = text.split("alert_on_exit() {", 1)[1].split("\n}", 1)[0]
        self.assertNotIn("2>&1", body)
        self.assertIn("exit 6", text)

    def test_the_deploy_carries_the_git_baseline(self):
        text = (fixture.ROOT / "scripts/deploy-home-beta.sh").read_text(encoding="utf-8")
        self.assertIn("services/backups/INSTALLED-FILES.sha256", text)

    def test_owner_scripts_are_wrapped_and_parse(self):
        for name in ("10-rc3-backup-install.sh", "11-rc3-backup-proof.sh"):
            path = fixture.ROOT / "deploy/host/owner-scripts" / name
            text = path.read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertIn("\nmain() {", text)
                self.assertEqual('main "$@"', text.rstrip().splitlines()[-2 if text.rstrip().endswith("exit") else -1])
                self.assertNotIn("\r", text)
                if shutil.which("bash"):
                    self.assertEqual(0, subprocess.run(["bash", "-n", str(path)]).returncode)

    def test_watchdog_runs_from_a_system_timer_as_the_backup_user(self):
        folder = fixture.ROOT / "deploy/host/systemd"
        service = (folder / "avrana-backup-watchdog.service").read_text(encoding="utf-8")
        timer = (folder / "avrana-backup-watchdog.timer").read_text(encoding="utf-8")
        self.assertIn("User=cody", service)
        self.assertIn("backup-guard.py watchdog", service)
        self.assertIn("XDG_RUNTIME_DIR=/run/user/1000", service)
        self.assertIn("Persistent=true", timer)

    def test_proof_packet_names_the_rules_that_bind_it(self):
        text = (fixture.ROOT / "docs/runbooks/rc3-backup-restore-proof.md").read_text(encoding="utf-8")
        for needed in ("Do not open SQLite", "immutable", "hidden prompt", "RPO", "RTO", "Rollback",
                       "main() wrapper", "no overwrite"):
            self.assertIn(needed, text)


if __name__ == "__main__":
    unittest.main()
