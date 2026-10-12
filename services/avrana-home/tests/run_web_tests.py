#!/usr/bin/env python3
"""Run the Avrana home suites under THIS interpreter: the web suite (Tier A + B) and the adapter tests.

    python -m pip install --require-hashes --only-binary=:all: -r services/avrana-home/requirements.lock
    AVRANA_REQUIRE_DEPS=1 python -B services/avrana-home/tests/run_web_tests.py

With AVRANA_REQUIRE_DEPS=1 (what CI sets) a missing dependency or ANY skipped test is a failure
(exit 2 and 3; the one POSIX-only adapter test may skip on Windows). Without it, a missing framework is reported and the web suite is skipped, like
`tests/run_offline.py` does. The last lines are machine-readable:

    adapter tests: ran=N skipped=0 failed=0
    web tests: ran=N skipped=0 failed=0

Works from the repository root or anywhere. Needs only loopback: the web tests bind and connect to
127.0.0.1 only and resolve no names (webtests/__init__.py refuses anything else). Extra arguments
are passed to the web suite's `unittest discover` (used by the runner's own test).
"""
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
NEEDED = ("fastapi", "starlette", "uvicorn", "jinja2", "httpx")


def counts(stderr: str):
    """(ran, skipped, failed) from unittest's summary."""
    ran = re.search(r"Ran (\d+) tests?", stderr)
    ran = int(ran.group(1)) if ran else 0
    tail = stderr.strip().splitlines()[-1] if stderr.strip() else ""
    skipped = sum(int(n) for n in re.findall(r"skipped=(\d+)", tail))
    failed = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", tail))
    if "FAILED" in tail and failed == 0:
        failed = 1
    return ran, skipped, failed


def run_suite(label, start, extra=()):
    cmd = [sys.executable, "-B", "-W", "ignore::DeprecationWarning", "-m", "unittest", "discover",
           "-s", str(start), "-t", str(HOME), "-p", "test_*.py", *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(HOME))
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    ran, skipped, failed = counts(proc.stderr)
    if proc.returncode != 0 and failed == 0:
        failed = 1
    print(f"{label}: ran={ran} skipped={skipped} failed={failed}", flush=True)
    return ran, skipped, failed


def main() -> int:
    strict = os.environ.get("AVRANA_REQUIRE_DEPS") == "1"
    missing = [m for m in NEEDED if importlib.util.find_spec(m) is None]
    if missing and strict:
        print("FAIL: AVRANA_REQUIRE_DEPS=1 and not installed: " + ", ".join(missing)
              + " (pip install -r services/avrana-home/requirements.lock)", file=sys.stderr)
        print("web tests: ran=0 skipped=0 failed=1")
        return 2
    code = 0
    _r, a_skipped, a_failed = run_suite("adapter tests", HOME / "tests")
    _r, w_skipped, w_failed = run_suite("web tests", HOME / "webtests", sys.argv[1:])
    if a_failed or w_failed:
        code = 1
    elif strict and (w_skipped or (a_skipped and os.name != "nt")):   # one adapter test is POSIX-only
        print("FAIL: AVRANA_REQUIRE_DEPS=1 and tests were skipped", file=sys.stderr)
        code = 3
    return code


if __name__ == "__main__":
    sys.exit(main())
