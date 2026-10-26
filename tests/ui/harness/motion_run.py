#!/usr/bin/env python3
"""Run the browser checks for Home's page-to-page motion (MK-6, AVR-720). Development tool.

    python -B tests/ui/harness/motion_run.py [--tree PATH]

motion_check.mjs drives Chromium against the avrana-home dev stack (started and stopped by the script, loopback only,
synthetic identities): with reduced motion = no-preference, Home -> title page through the hero's Details starts a
cross-document view transition (seen through the browser's `pageswap` and `pagereveal` events), the art carries one
unique name and moves, the lens has its own group, every animation is at most 200 ms, nothing flies back to Home,
a search result's art flies into its title page, and a tap or a key during a held transition reaches the new page at
once; with reduced motion = reduce, no transition runs and nothing is named; HOME_MOTION_PROPOSAL=on gives 600 ms.

Uses the interpreter running this script for the dev stack (it needs the pinned requirements: fastapi, uvicorn, jinja2)
and PLAYWRIGHT_FROM for the browser tooling (see README.md).
Exit 0: all passed. Exit 1: a check failed. Exit 2: Node or the browser tooling is missing (nothing is claimed).
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
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
    a = ap.parse_args()
    tree = Path(a.tree).resolve()
    node = shutil.which("node")
    if node is None:
        print("node is not installed; nothing was checked", file=sys.stderr)
        return 2
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_FROM", str(ROOT.parent / ".ui-tooling"))
    if not (Path(env["PLAYWRIGHT_FROM"]) / "node_modules" / "@playwright" / "test").is_dir():
        print(f"browser tooling not found at {env['PLAYWRIGHT_FROM']} (set PLAYWRIGHT_FROM); motion checks NOT run",
              file=sys.stderr)
        return 2
    return subprocess.call([node, str(HERE / "motion_check.mjs"), "--tree", str(tree), "--python", sys.executable,
                            "--port", str(free_port()), "--mock-port", str(free_port())], env=env)


if __name__ == "__main__":
    sys.exit(main())
