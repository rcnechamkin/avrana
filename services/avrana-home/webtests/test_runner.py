"""Tier A: tests/run_web_tests.py honours AVRANA_REQUIRE_DEPS=1 and prints its summary lines."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import FRAMEWORK_MISSING

RUNNER = Path(__file__).resolve().parents[1] / "tests" / "run_web_tests.py"


def run(env_extra, *args, python_flags=("-B",)):
    env = dict(os.environ)
    env.pop("AVRANA_REQUIRE_DEPS", None)
    env.update(env_extra)
    return subprocess.run([sys.executable, *python_flags, str(RUNNER), *args], env=env,
                          capture_output=True, text=True, timeout=300)


def suite_dir(tmp, body):
    Path(tmp, "__init__.py").write_text("", encoding="utf-8")
    Path(tmp, "test_probe.py").write_text(body, encoding="utf-8")


class StrictMissingDependencyTests(unittest.TestCase):
    def test_missing_dependency_is_a_failure_only_when_required(self):
        # `-S` drops site-packages, so the pinned framework cannot be imported, whatever the machine.
        strict = run({"AVRANA_REQUIRE_DEPS": "1"}, python_flags=("-S", "-B"))
        self.assertEqual(2, strict.returncode)
        self.assertIn("AVRANA_REQUIRE_DEPS=1 and not installed", strict.stderr)
        self.assertIn("web tests: ran=0 skipped=0 failed=1", strict.stdout)


@unittest.skipIf(FRAMEWORK_MISSING, "needs the framework installed to reach the skip logic")
class StrictSkipTests(unittest.TestCase):
    PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n"
    SKIPPING = ("import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n"
                "    @unittest.skip('probe')\n    def test_b(self):\n        pass\n")
    FAILING = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('probe')\n"

    def runner(self, body, strict):
        with tempfile.TemporaryDirectory() as tmp:
            suite_dir(tmp, body)
            return run({"AVRANA_REQUIRE_DEPS": "1"} if strict else {}, "-s", tmp, "-t", tmp)

    def test_clean_run_prints_the_summary_and_exits_zero(self):
        r = self.runner(self.PASSING, strict=True)
        self.assertEqual(0, r.returncode, r.stderr[-400:])
        self.assertIn("web tests: ran=1 skipped=0 failed=0", r.stdout)
        self.assertRegex(r.stdout, r"adapter tests: ran=\d+ skipped=[01] failed=0")

    def test_any_skip_fails_when_required_but_not_otherwise(self):
        strict = self.runner(self.SKIPPING, strict=True)
        self.assertEqual(3, strict.returncode)
        self.assertIn("web tests: ran=2 skipped=1 failed=0", strict.stdout)
        relaxed = self.runner(self.SKIPPING, strict=False)
        self.assertEqual(0, relaxed.returncode)
        self.assertIn("skipped=1", relaxed.stdout)

    def test_a_failing_test_fails_either_way(self):
        r = self.runner(self.FAILING, strict=False)
        self.assertEqual(1, r.returncode)
        self.assertIn("web tests: ran=1 skipped=0 failed=1", r.stdout)


if __name__ == "__main__":
    unittest.main()
