#!/usr/bin/env python3
"""One command for the whole UI harness, end to end. Development tool; never run against production.

    python -B tests/ui/harness/run_ui.py [--only portal/home] [--no-browser] [--strict] [--out DIR]

1. renders every registry page offline and runs the static checks (the same ones run_offline.py runs);
2. serves the pages from 127.0.0.1 on an ephemeral port (serve.py);
3. runs check.mjs (Playwright + axe-core, Chromium) over them at 390x844 and 1280x800;
4. stops the server and applies the baseline ratchet to both sections.

Exits 1 on any finding that is not in tests/ui/harness/baseline.json, 2 when the browser tooling is
missing (set PLAYWRIGHT_FROM to a folder whose node_modules has @playwright/test and axe-core; the
default is ../.ui-tooling next to the repository), 3 on a page error. --strict also fails on stale
baseline entries. Output (screenshots, report.json) goes to tests/ui/harness/out (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import pages, ratchet, static_checks  # noqa: E402

HERE = Path(__file__).resolve().parent


def tooling_dir():
    env = os.environ.get("PLAYWRIGHT_FROM")
    cands = [Path(env)] if env else [pages.REPO_ROOT.parent / ".ui-tooling", pages.REPO_ROOT / ".ui-tooling"]
    for c in cands:
        if (c / "node_modules" / "@playwright" / "test").is_dir() and (c / "node_modules" / "axe-core").is_dir():
            return c.resolve()
    return None


def report_section(label, ids, base, strict, partial=False):
    new, stale = ratchet.compare(ids, base)
    if partial:
        stale = []
    print(f"[{label}] {len(ids)} findings; {len(new)} new; {len(stale)} stale baseline entries")
    for i in new:
        print(f"  NEW   {i}")
    for i in stale[:20]:
        print(f"  stale {i}")
    return bool(new or (strict and stale))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="only pages whose key contains this text (browser layer)")
    ap.add_argument("--no-browser", action="store_true", help="static layer only")
    ap.add_argument("--strict", action="store_true", help="stale baseline entries fail")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args(argv)
    strict = a.strict or os.environ.get("UI_HARNESS_STRICT_BASELINE", "") not in ("", "0")
    base = ratchet.load()
    failed = False

    reg = pages.build_registry()
    findings, unavailable = static_checks.run(reg)
    print(f"registry: {len(reg.pages())} pages, {len(unavailable)} unavailable")
    for key, why in unavailable:
        print(f"  unavailable {key}: {why}")
    failed |= report_section("static", {f.id for f in findings}, base["static"], strict)
    if a.no_browser:
        return 1 if failed else 0

    tools = tooling_dir()
    node = shutil.which("node")
    if not tools or not node:
        print("browser layer NOT run: " + ("node is not on PATH" if not node else
              "no Playwright + axe-core install found (set PLAYWRIGHT_FROM; see tests/ui/README.md)"))
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-B", str(HERE / "serve.py"), "--port", "0"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = server.stdout.readline().strip()
        if not line.startswith("LISTENING "):
            print("server did not start:", line)
            return 3
        url = line.split()[1]
        print(f"serving {url} (loopback only)")
        env = dict(os.environ, PLAYWRIGHT_FROM=str(tools))
        cmd = [node, str(HERE / "check.mjs"), "--base", url, "--out", str(out), "--report-only"]
        if a.only:
            cmd += ["--only", a.only]
        t0 = time.time()
        res = subprocess.run(cmd, env=env)
        print(f"browser layer finished in {time.time() - t0:.0f}s (exit {res.returncode})")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    if res.returncode not in (0, 1):
        return res.returncode
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    print("tool versions:", rep["versions"])
    print("summary:", json.dumps(rep["summary"]))
    ids = {f["id"] for f in rep["findings"]}
    failed |= report_section("browser" + (" (partial run)" if a.only else ""), ids, base["browser"], strict, partial=bool(a.only))
    print("FAILED: new findings" if failed else "ok: nothing outside the baseline")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
