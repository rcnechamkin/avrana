#!/usr/bin/env python3
"""Completeness gate for one Avrana backup run (remediation Batch 1, finding A4).

avrana-backup.sh builds several components from globs and from tar of whole directories. Those
succeed when anything at all matches, so a deleted .env, tunnel credential or unit file used to
shrink the archive while the run still reported "ok" -- which is how missing files went unnoticed
in September 2026. This script checks a finished run directory against an explicit list.

  verify-required.py <run-dir> <required-artifacts.txt>

List format, one requirement per line, fields separated by "|" ("#" starts a comment):
  <component>|file|<path>                         regular file, non-empty
  <component>|member|<archive.tar.zst>|<name>     archive contains this exact member
  <component>|mincount|<archive.tar.zst>|<prefix>|<n>   at least n members start with prefix

Output: one "MISSING|<component>|<what>" line per unmet requirement, then a summary line.
Exit: 0 all present, 1 something missing, 2 the list itself is unusable.
Reads only. Archive member names are compared with any leading "./" removed.
"""
import pathlib
import subprocess
import sys


def archive_names(path):
    zstd = subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    tar = subprocess.run(["tar", "-tf", "-"], stdin=zstd.stdout, capture_output=True, text=True)
    zstd.stdout.close()
    if zstd.wait() != 0 or tar.returncode != 0:
        raise RuntimeError("archive unreadable")
    return [n[2:] if n.startswith("./") else n for n in tar.stdout.splitlines()]


def main():
    if len(sys.argv) != 3:
        print("usage: verify-required.py <run-dir> <required-artifacts.txt>", file=sys.stderr)
        return 2
    run = pathlib.Path(sys.argv[1])
    try:
        lines = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"cannot read requirement list: {exc}", file=sys.stderr)
        return 2

    reqs = []
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        kind = parts[1] if len(parts) > 1 else ""
        if (kind, len(parts)) not in (("file", 3), ("member", 4), ("mincount", 5)):
            print(f"requirement list line {number} is malformed", file=sys.stderr)
            return 2
        if kind == "mincount" and not parts[4].isdigit():
            print(f"requirement list line {number}: count is not a number", file=sys.stderr)
            return 2
        reqs.append(parts)
    if not reqs:
        print("requirement list is empty", file=sys.stderr)
        return 2

    names = {}       # archive path -> list of member names, or None when unreadable
    missing = []
    for parts in reqs:
        component, kind, rel = parts[0], parts[1], parts[2]
        target = run / rel
        if kind == "file":
            if not (target.is_file() and target.stat().st_size > 0):
                missing.append((component, f"{rel} (absent or empty)"))
            continue
        if rel not in names:
            try:
                names[rel] = archive_names(target) if target.is_file() else None
            except (RuntimeError, OSError):
                names[rel] = None
        members = names[rel]
        if members is None:
            missing.append((component, f"{rel} (archive absent or unreadable)"))
            continue
        if kind == "member":
            if parts[3] not in members:
                missing.append((component, f"{parts[3]} (not in {rel})"))
        else:
            have = sum(1 for n in members if n.startswith(parts[3]))
            if have < int(parts[4]):
                missing.append((component, f"{parts[3]}* in {rel}: {have} entries, need {parts[4]}"))

    seen = set()
    for component, what in missing:
        if (component, what) not in seen:
            seen.add((component, what))
            print(f"MISSING|{component}|{what}")
    if missing:
        print(f"completeness: {len(seen)} of {len(reqs)} requirements unmet")
        return 1
    print(f"completeness: all {len(reqs)} requirements present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
