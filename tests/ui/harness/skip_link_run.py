#!/usr/bin/env python3
"""Run skip_link.mjs against the portal page server and the Home dev stack. Development tool.

    python -B tests/ui/harness/skip_link_run.py [--tree PATH] [--out DIR] [--label NAME]

Starts serve.py and avrana-home/dev/run_dev.py (both loopback only, synthetic data) from --tree
(default: this checkout; pass another checkout of main to get a baseline), runs the browser checks
and stops only the two processes it started. Needs PLAYWRIGHT_FROM (see README.md); defaults to
.ui-tooling next to the repository root.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url: str, secs: float = 60) -> None:
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"server did not come up: {url}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=str(ROOT))
    ap.add_argument("--out", default=str(HERE / "out" / "skip-link"))
    ap.add_argument("--label", default="run")
    ap.add_argument("--axe-only", action="store_true", help="baseline on a tree without the skip link")
    a = ap.parse_args()
    tree = Path(a.tree).resolve()
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_FROM", str(ROOT.parent / ".ui-tooling"))
    pp, hp, mp = free_port(), free_port(), free_port()
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, "-B", str(tree / "tests/ui/harness/serve.py"), "--port", str(pp)],
                                      cwd=tree, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        procs.append(subprocess.Popen([sys.executable, "-B", str(tree / "services/avrana-home/dev/run_dev.py"), "--dev-identity",
                                       "--port", str(hp), "--mock-port", str(mp)],
                                      cwd=tree, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait(f"http://127.0.0.1:{pp}/manifest.json")
        wait(f"http://127.0.0.1:{hp}/_dev/identity")
        return subprocess.call(["node", str(HERE / "skip_link.mjs"), "--portal", f"http://127.0.0.1:{pp}/p/portal/home/multi",
                                "--home", f"http://127.0.0.1:{hp}/", "--out", a.out, "--label", a.label] + (["--axe-only"] if a.axe_only else []), env=env)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
