"""The ratchet: known findings may disappear from the baseline, never appear in it.

baseline.json holds two sections of `finding id -> Linear issue that will fix it`:

    "static"   ids produced by static_checks.py (run by tests/run_offline.py)
    "browser"  ids produced by check.mjs (run by run_ui.py, a development tool)

A finding that is in neither section is a regression and fails the run. A baseline entry that no
longer occurs is "stale": it is printed, and fails the run only in strict mode
(UI_HARNESS_STRICT_BASELINE=1 or `--strict`), which is how the baseline is emptied once fixes merge.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .pages import HARNESS_DIR, REPO_ROOT

BASELINE_PATH = HARNESS_DIR / "baseline.json"
SECTIONS = ("static", "browser")
ISSUE_RE = re.compile(r"^AVR-\d+$")

# Which issue fixes a finding. Service-wide by default; specific ids first.
SERVICE_ISSUE = {"portal": "AVR-357", "kindle": "AVR-358", "audible": "AVR-359"}


def assign_issue(fid: str) -> str:
    parts = fid.split("/", 4)
    service, page, _ident, rule = (parts + ["", "", "", ""])[:4]
    detail = parts[4] if len(parts) > 4 else ""
    if service == "portal" and page == "home" and rule == "leak" and detail.split("/")[0] in ("comics", "ebooks", "ebook"):
        return "AVR-430"            # the Read tile subtitle "Comics & ebooks"
    if service == "kindle" and page == "not-found" and rule in ("leak", "status"):
        return "AVR-353"            # 403 with the full page where the 404 doctrine says nothing
    return SERVICE_ISSUE.get(service, "UNASSIGNED")


def load(path: Path = BASELINE_PATH) -> dict:
    if not Path(path).is_file():
        return {s: {} for s in SECTIONS}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s: dict(data.get(s, {})) for s in SECTIONS}


def dump(data: dict, path: Path = BASELINE_PATH):
    out = {
        "_comment": "Known accessibility/leak findings, each with the issue that will fix it. "
                    "This file may only shrink: see tests/ui/README.md. Do not add entries to make a run pass.",
        "static": dict(sorted(data["static"].items())),
        "browser": dict(sorted(data["browser"].items())),
    }
    Path(path).write_text(json.dumps(out, indent=1, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")


def compare(ids, section: dict):
    """(new, stale): ids not in the baseline, and baseline ids that did not occur."""
    ids = set(ids)
    return sorted(ids - set(section)), sorted(set(section) - ids)


def validate(data: dict):
    """Problems with the baseline file itself (empty list when well formed)."""
    problems = []
    for sec in SECTIONS:
        for fid, issue in data[sec].items():
            if not ISSUE_RE.match(str(issue)):
                problems.append(f"{sec}: {fid!r} has no valid issue ({issue!r})")
            if fid.count("/") < 4:
                problems.append(f"{sec}: {fid!r} is not service/page/identity/rule/detail")
    return problems


def grown_since(ref: str, path: Path = BASELINE_PATH):
    """Ids present now but absent from baseline.json at git ref `ref`. Needs git; for review use."""
    rel = Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    res = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{ref}:{rel}"], capture_output=True, text=True)
    old = {s: {} for s in SECTIONS}
    if res.returncode == 0:
        raw = json.loads(res.stdout)
        old = {s: dict(raw.get(s, {})) for s in SECTIONS}
    now = load(path)
    return {s: sorted(set(now[s]) - set(old[s])) for s in SECTIONS}
