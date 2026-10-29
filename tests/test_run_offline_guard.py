"""run_offline.py must not let the PyYAML-dependent G1 gates pass silently by skipping (AVR-386)."""
import importlib.util
import io
import os
from pathlib import Path
import unittest
from contextlib import redirect_stderr
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_offline_under_test", ROOT / "tests/run_offline.py")
run_offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_offline)


class YamlGuardTests(unittest.TestCase):
    def test_silent_when_yaml_is_present(self):
        with mock.patch.object(run_offline.importlib.util, "find_spec", return_value=object()), \
                redirect_stderr(io.StringIO()) as err:
            run_offline.yaml_guard()
        self.assertEqual(err.getvalue(), "")

    def test_warns_when_missing_and_not_required(self):
        with mock.patch.object(run_offline.importlib.util, "find_spec", return_value=None), \
                mock.patch.dict(os.environ, {"AVRANA_REQUIRE_YAML": "0"}), redirect_stderr(io.StringIO()) as err:
            run_offline.yaml_guard()
        self.assertIn("WARN PyYAML not importable", err.getvalue())

    def test_fails_when_missing_and_required(self):
        with mock.patch.object(run_offline.importlib.util, "find_spec", return_value=None), \
                mock.patch.dict(os.environ, {"AVRANA_REQUIRE_YAML": "1"}):
            with self.assertRaises(SystemExit) as caught:
                run_offline.yaml_guard()
        self.assertIn("FAIL", str(caught.exception.code))

    def test_unexpected_values_fail_closed(self):
        for value in ("true", "yes", " 1"):
            with self.subTest(value=value),                     mock.patch.object(run_offline.importlib.util, "find_spec", return_value=None),                     mock.patch.dict(os.environ, {"AVRANA_REQUIRE_YAML": value}), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    run_offline.yaml_guard()


class EverySuiteRunsTests(unittest.TestCase):
    """One failing suite must not hide the rest (RC1: from #155 a repository-test failure kept CI from ever running
    the Home suites), and the exit still fails."""

    def run_main(self, codes):
        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(cmd)
            return mock.Mock(returncode=codes.pop(0) if codes else 0)
        with mock.patch.object(run_offline, "yaml_guard"), \
                mock.patch.object(run_offline, "kindle_offline", side_effect=AssertionError("boom")), \
                mock.patch.object(run_offline.subprocess, "run", side_effect=fake_run), \
                redirect_stderr(io.StringIO()), mock.patch("sys.stdout", new=io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                run_offline.main()
        return calls, str(caught.exception.code)

    def test_a_failure_first_still_runs_the_home_suites_and_fails_at_the_end(self):
        calls, message = self.run_main([1])                       # the repository tests fail
        self.assertEqual(len(calls), 8)                            # every subprocess suite still ran
        self.assertTrue(any("webtests" in str(c) for c in calls))
        self.assertIn("repository tests", message)
        self.assertIn("kindle offline", message)                  # the in-process suite's failure is recorded too


if __name__ == "__main__":
    unittest.main()
