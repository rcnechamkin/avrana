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


if __name__ == "__main__":
    unittest.main()
