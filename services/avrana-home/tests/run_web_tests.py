#!/usr/bin/env python3
"""Run the Avrana home WEB suite, Tier A and Tier B, and refuse to pass if Tier B cannot run.

    pip install -r services/avrana-home/requirements.txt      # in the CI job's virtualenv
    python -B services/avrana-home/tests/run_web_tests.py

`tests/run_offline.py` runs the same directory on a machine without the framework and SKIPS
Tier B with an explicit line. This runner is for CI: a missing framework is a failure (exit 2),
never a silent skip, and any skipped test is reported as a failure of the job.
Extra arguments are passed to unittest (for example `-v` or a module name).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
NEEDED = ("fastapi", "starlette", "uvicorn", "jinja2", "httpx")


def main() -> int:
    missing = [m for m in NEEDED if importlib.util.find_spec(m) is None]
    if missing:
        print("FAIL avrana-home web suite: not installed: " + ", ".join(missing)
              + " (pip install -r services/avrana-home/requirements.txt)", file=sys.stderr)
        return 2
    cmd = [sys.executable, "-B", "-W", "ignore::DeprecationWarning", "-m", "unittest", "discover",
           "-s", str(HOME / "webtests"), "-t", str(HOME), "-p", "test_*.py"] + sys.argv[1:]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode == 0 and "skipped" in proc.stderr.splitlines()[-1]:
        print("FAIL avrana-home web suite: tests were skipped although the framework is installed",
              file=sys.stderr)
        return 3
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
