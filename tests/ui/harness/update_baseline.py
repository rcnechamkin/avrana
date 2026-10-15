#!/usr/bin/env python3
"""Check or rewrite tests/ui/harness/baseline.json. The baseline may only shrink.

    python -B tests/ui/harness/update_baseline.py --check            # exit 1 on a new finding
    python -B tests/ui/harness/update_baseline.py --check --strict   # also exit 1 on a stale entry
    python -B tests/ui/harness/update_baseline.py --write            # drop stale entries (shrink)
    python -B tests/ui/harness/update_baseline.py --write --add-new  # ONLY to create the file or
                                                                     # to record debt a reviewer approved
    python -B tests/ui/harness/update_baseline.py --vs origin/main   # fail if the file grew vs a ref
    ... --browser tests/ui/harness/out/report.json                   # the same for the browser section

--write never adds an entry on its own. --add-new assigns the fixing issue from ratchet.assign_issue
and refuses an id it cannot assign.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import pages, ratchet, static_checks  # noqa: E402


def current_ids(browser_report):
    reg = pages.build_registry()
    findings, _un = static_checks.run(reg)
    cur = {"static": {f.id for f in findings}, "browser": None}
    if browser_report:
        rep = json.loads(Path(browser_report).read_text(encoding="utf-8"))
        cur["browser"] = {f["id"] for f in rep["findings"]}
    return cur


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--vs", metavar="REF")
    ap.add_argument("--strict", action="store_true", help="stale entries fail --check")
    ap.add_argument("--add-new", action="store_true", help="with --write: record new findings (reviewer-approved only)")
    ap.add_argument("--browser", metavar="REPORT_JSON", help="also handle the browser section from a run_ui report")
    a = ap.parse_args(argv)

    if a.vs:
        grown = ratchet.grown_since(a.vs)
        n = sum(len(v) for v in grown.values())
        for sec, ids in grown.items():
            for i in ids:
                print(f"GREW {sec}: {i}")
        print(f"baseline grew by {n} entries against {a.vs}" if n else f"baseline did not grow against {a.vs}")
        return 1 if n else 0

    base = ratchet.load()
    problems = ratchet.validate(base)
    cur = current_ids(a.browser)
    sections = [s for s in ratchet.SECTIONS if cur[s] is not None]
    rc = 0
    for p in problems:
        print("BASELINE PROBLEM:", p)
        rc = 1
    for sec in sections:
        new, stale = ratchet.compare(cur[sec], base[sec])
        print(f"[{sec}] {len(cur[sec])} findings, {len(base[sec])} in baseline, {len(new)} new, {len(stale)} stale")
        if a.check:
            for i in new:
                print(f"  NEW   {i}")
            for i in stale:
                print(f"  STALE {i}")
            if new or (a.strict and stale):
                rc = 1
        else:
            for i in stale:
                del base[sec][i]
            if new:
                if not a.add_new:
                    print(f"  {len(new)} new findings are NOT recorded (the baseline may only shrink). Fix them, or see --add-new.")
                    rc = 1
                else:
                    for i in new:
                        issue = ratchet.assign_issue(i)
                        if issue == "UNASSIGNED":
                            print(f"  cannot assign an issue to {i}")
                            rc = 1
                        else:
                            base[sec][i] = issue
                    print(f"  WARNING: recorded {len(new)} new entries; a reviewer must approve this growth.")
    if a.write and rc == 0:
        ratchet.dump(base)
        print(f"wrote {ratchet.BASELINE_PATH}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
