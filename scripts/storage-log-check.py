#!/usr/bin/env python3
"""Classify storage events; retain alarms for new or unidentified failures."""
import argparse
import json
import os
import pathlib
import re
import sys

ERROR = re.compile(r"EXT4-fs error|Detected aborted journal|I/O error|Synchronize Cache.*failed|remounting filesystem read-only|reset SuperSpeed|device descriptor read", re.I)
SNAPSHOT_IO = re.compile(r"Buffer I/O error on dev (dm-\d+), logical block \d+, async page read$")
SNAPSHOT_NAME = "ubuntu--vg-root--recovery--snap"
ORIGIN_NAME = "ubuntu--vg-ubuntu--lv"
RETIREMENT = pathlib.Path("/home/cody/.local/state/avrana/retired-storage-event.json")

def classify(log, devices, retired_lines=()):
    retired = set(retired_lines) if SNAPSHOT_NAME not in devices.values() else set()
    lines = log.splitlines()
    invalid = any("Snapshot is marked invalid." in line and line not in retired for line in lines)
    array_errors = []
    snapshot_errors = []
    for line in lines:
        if not ERROR.search(line):
            continue
        match = SNAPSHOT_IO.search(line)
        known_retired = line in retired and match is not None
        known_active = invalid and match and devices.get(match[1]) == SNAPSHOT_NAME
        if known_retired or known_active:
            snapshot_errors.append(line)
        else:
            array_errors.append(line)
    return array_errors, snapshot_errors, invalid

def retirement_lines(state, boot_id, devices, uuids):
    if state["boot_id"] != boot_id:
        return []
    if SNAPSHOT_NAME in devices.values() or SNAPSHOT_NAME+"-cow" in devices.values():
        return []
    if state["snapshot_name"] != SNAPSHOT_NAME or uuids.get(ORIGIN_NAME) != state["origin_uuid"]:
        return []
    lines = state["kernel_lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 32:
        raise ValueError("invalid retirement event list")
    if not all(isinstance(line, str) and ("Snapshot is marked invalid." in line or SNAPSHOT_IO.search(line)) for line in lines):
        raise ValueError("unexpected retirement event type")
    return lines

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("array", "snapshot"), required=True)
    args = parser.parse_args()
    devices = {}
    uuids = {}
    for path in pathlib.Path("/sys/class/block").glob("dm-*/dm/name"):
        try:
            name = path.read_text().strip()
            devices[path.parent.parent.name] = name
            uuids[name] = (path.parent/"uuid").read_text().strip()
        except OSError:
            pass
    retired = []
    if RETIREMENT.exists():
        try:
            st = RETIREMENT.stat()
            if st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise ValueError("retirement receipt permissions")
            state = json.loads(RETIREMENT.read_text())
            boot = pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            retired = retirement_lines(state, boot, devices, uuids)
        except (OSError, ValueError, KeyError, TypeError):
            print("FAIL storage retirement receipt cannot be validated")
            return 1
    array, snapshot, invalid = classify(sys.stdin.read(), devices, retired)
    if args.mode == "array":
        if snapshot:
            context = "retired" if retired else "invalid"
            print(f"WARN {len(snapshot)} known {context} recovery-snapshot I/O events; active-array errors remain failures")
        if array:
            print(f"FAIL {len(array)} other storage/USB error lines this boot")
            return 1
        print("OK   no unclassified storage/USB errors this boot")
        return 0
    if invalid:
        print("FAIL LVM recovery snapshot is marked invalid; preserve evidence and inspect before any snapshot operation")
        return 1
    if retired:
        print("OK   invalid recovery snapshot retired; preserved historical events are documented")
    else:
        print("OK   no unresolved invalid-snapshot kernel event this boot")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
