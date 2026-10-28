"""Tests for api-caps-monitor.py (standard library). Run: python3 scripts/test_api_caps_monitor.py"""
import datetime as dt
import importlib.util
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("caps", pathlib.Path(__file__).with_name("api-caps-monitor.py"))
caps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(caps)

NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.timezone.utc)


class Classify(unittest.TestCase):
    def test_timestamps_are_not_signals(self):
        # Real lines from avrana, 2026-10-28: "429" only inside the millisecond stamp.
        for line in ("2026-10-28T04:55:05.429Z [debug][Jellyfin Sync]: Updating existing title: Ted Lasso",
                     '{"time":"2026-10-27T23:01:41.762881429-07:00","msg":"Request","path":"/up","status":200}'):
            self.assertEqual([], caps.classify(line, ("tmdb", "hardcover")))

    def test_rate_auth_down(self):
        self.assertEqual([("tmdb", "rate")], caps.classify(
            "[error][TMDB API]: Request failed with status code 429", ("tmdb",)))
        self.assertEqual([("comicvine", "rate")], caps.classify(
            "ERROR metadata] ComicVine returned HTTP 420 (velocity)", ("comicvine", "metron")))
        self.assertEqual([("hardcover", "auth")], caps.classify(
            "E, Hardcover search failed: 401 Unauthorized (jwt expired)", ("hardcover",)))
        self.assertEqual([("comicvine", "down")], caps.classify(
            "Discover sync failed: HTTP status server error (502 Bad Gateway) for url "
            "(https://comicvine.gamespot.com/api/issues/?api_key=abc", ("comicvine",)))

    def test_self_throttling_and_success_are_quiet(self):
        for line in ("INFO rate_limiter] [Rate Limiter] Globally throttling getcomics for 3738ms to prevent IP bans",
                     "INFO metadata] Successfully synced 39 ComicVine issues for The Department of Truth.",
                     "INFO Syncing metadata for: Star Wars (COMICVINE ID: 1234)"):
            self.assertEqual([], caps.classify(line, ("comicvine", "metron")))

    def test_only_the_containers_own_providers(self):
        self.assertEqual([], caps.classify("ComicVine 429 Too Many Requests", ("tmdb",)))


class Redact(unittest.TestCase):
    def test_no_key_survives(self):
        key = "0123456789abcdef0123456789abcdef01234567"
        for line in (f"failed for url (https://comicvine.gamespot.com/api/issues/?api_key={key}&format=json)",
                     f"Authorization: Bearer {key}", f'token="{key}"', f"apikey={key}"):
            out = caps.redact(line)
            self.assertNotIn(key, out, line)
            self.assertNotIn(key[:16], out, line)

    def test_bounded(self):
        self.assertLessEqual(len(caps.redact("x " * 500)), 200)


class Decide(unittest.TestCase):
    E = {"count": 3, "services": ["seerr"], "sample": "s"}

    def test_new_then_quiet_then_reminder_then_recovered(self):
        alert, rec, state = caps.decide({("tmdb", "rate"): self.E}, {}, NOW)
        self.assertEqual(["tmdb:rate"], [a[0] for a in alert])
        alert, rec, state = caps.decide({("tmdb", "rate"): self.E}, state, NOW + dt.timedelta(minutes=15))
        self.assertEqual([], alert)
        alert, rec, state = caps.decide({("tmdb", "rate"): self.E}, state, NOW + dt.timedelta(hours=25))
        self.assertEqual([("tmdb:rate", self.E, True)], alert)
        self.assertIn("STILL tmdb is rate limited", caps.report(alert, rec))
        alert, rec, state = caps.decide({}, state, NOW + dt.timedelta(hours=26))
        self.assertEqual(([], ["tmdb:rate"]), (alert, rec))
        self.assertEqual({}, state["open"])


class Sources(unittest.TestCase):
    def test_shelfarr_provider_table(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "p.sqlite3"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE metadata_provider_statuses (provider, status, rate_limited_until, last_error, "
                       "failure_count)")
            db.executemany("INSERT INTO metadata_provider_statuses VALUES (?,?,?,?,?)", [
                ("hardcover", "healthy", None, None, 0),
                ("google_books", "healthy", "2026-10-28 13:00:00", "429", 2),
                ("openlibrary", "degraded", None, "connection refused", 5)])
            db.commit()
            db.close()
            out = caps.shelfarr_status(path, now=NOW)
        self.assertEqual({("google_books", "rate"), ("openlibrary", "down")}, set(out))

    def test_omnibus_jobs_since(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "o.db"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE JobLog (jobType, status, message, createdAt)")
            old = int((NOW - dt.timedelta(days=2)).timestamp() * 1000)
            new = int(NOW.timestamp() * 1000)
            db.executemany("INSERT INTO JobLog VALUES (?,?,?,?)", [
                ("DISCOVER_SYNC", "FAILED", "ComicVine HTTP 420 velocity ?api_key=secretsecret", new),
                ("DISCOVER_SYNC", "FAILED", "ComicVine 502 Bad Gateway error", old),
                ("LIBRARY_SCAN", "COMPLETED", "ComicVine 429", new)])
            db.commit()
            db.close()
            out = caps.omnibus_jobs(NOW - dt.timedelta(hours=1), path)
        self.assertEqual({("comicvine", "rate")}, set(out))
        self.assertNotIn("secretsecret", out[("comicvine", "rate")]["sample"])

    def test_logs_missing_container_is_not_unreadable(self):
        def run(cmd, **kw):
            name = cmd[-1]
            if name == "seerr":
                return subprocess.CompletedProcess(cmd, 0, "[error][TMDB API]: status code 429\n", "")
            if name == "shelfmark":
                return subprocess.CompletedProcess(cmd, 1, "", "Error: No such container: shelfmark")
            if name == "omnibus":
                return subprocess.CompletedProcess(cmd, 1, "", "permission denied")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        found, unreadable = caps.scan_logs(NOW, run=run)
        self.assertEqual({("tmdb", "rate")}, set(found))
        self.assertEqual(["omnibus"], unreadable)


if __name__ == "__main__":
    unittest.main()
