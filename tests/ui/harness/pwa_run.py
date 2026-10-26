#!/usr/bin/env python3
"""Run the checks for Home's first-party script and service worker (MK-3, AVR-717). Development tool.

    python -B tests/ui/harness/pwa_run.py [--tree PATH] [--no-browser]

Two parts, both loopback only and synthetic:

  1. pwa_sw_check.mjs: the worker Home serves at /sw.js (and the kill-switch worker) run in a Node `vm` with fake caches
     and fetch, and every handler is driven: install all-or-nothing, the poisoning guard (redirected, non-200, wrong
     type, opaque, Vary: *, size), navigations to the network untouched, the offline page only for a network
     TypeError, /signout and the outpost left to the browser, nothing but the allow-list stored. Needs only Node 18+.
  2. pwa_check.mjs: Chromium against the avrana-home dev stack (started and stopped by the script): worker
     registration, what the cache holds, the lens with 4 and 2 tabs, reduced motion, pagehide, pageshow, offline,
     the update banner, sign-out clearing the worker, the kill switch, JavaScript off. Needs PLAYWRIGHT_FROM (see
     README.md); skipped with --no-browser.

Uses the interpreter running this script for the dev stack (it needs the pinned requirements: fastapi, uvicorn, jinja2).
Exit 0: all passed. Exit 1: a check failed. Exit 2: Node or the browser tooling is missing (nothing is claimed).
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=str(ROOT))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    tree = Path(a.tree).resolve()
    node = shutil.which("node")
    if node is None:
        print("node is not installed; nothing was checked", file=sys.stderr)
        return 2
    sys.path.insert(0, str(tree / "services" / "avrana-home"))
    from avrana_home.app import pwa                      # standard library only
    out = Path(tempfile.mkdtemp(prefix="avr-pwa-run-"))
    try:
        (out / "sw.js").write_bytes(pwa.worker_bytes(b"<p>offline</p>"))
        (out / "self-destruct.js").write_bytes(pwa.SELF_DESTRUCT)
        code = subprocess.call([node, str(HERE / "pwa_sw_check.mjs"), "--worker", str(out / "sw.js"),
                                "--self-destruct", str(out / "self-destruct.js")])
        if code or a.no_browser:
            return code
        env = dict(os.environ)
        env.setdefault("PLAYWRIGHT_FROM", str(ROOT.parent / ".ui-tooling"))
        if not (Path(env["PLAYWRIGHT_FROM"]) / "node_modules" / "@playwright" / "test").is_dir():
            print(f"browser tooling not found at {env['PLAYWRIGHT_FROM']} (set PLAYWRIGHT_FROM); browser checks NOT run",
                  file=sys.stderr)
            return 2
        return subprocess.call([node, str(HERE / "pwa_check.mjs"), "--tree", str(tree), "--python", sys.executable,
                                "--port", str(free_port()), "--mock-port", str(free_port())], env=env)
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
