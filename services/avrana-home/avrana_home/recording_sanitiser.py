"""Turn an owner-captured Jellyfin response into a contract recording that carries no real data (AVR-376).

Status: OFFLINE TOOL. It reads a local file and writes a local file; it never contacts a server.
Capturing the raw response is a separate, owner-approved step (docs/runbooks/jellyfin-contract-recording.md).

What a recording is for: proving that the real server's response SHAPE (envelope, which declared fields
exist, their JSON types) matches contracts/jellyfin.json. Values are never needed for that, so none are kept:
  * only fields the contract declares are kept; the names (never the values) of the others are listed in
    `_undeclared_fields` so contract drift stays visible;
  * every kept value is replaced by a synthetic value of the type it ACTUALLY had (not the declared type),
    so a type change on the server still fails the contract gate;
  * lists are cut to MAX_ENTRIES entries; `TotalRecordCount` is replaced by the kept count;
  * finally every string of four or more characters in the raw input is searched for in the output, and
    the tool refuses to write anything if one is found (fail closed, without printing it).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import sys

VERSION = "avrana_home.recording_sanitiser 1"
MAX_ENTRIES = 3
HOME = Path(__file__).resolve().parents[1]
CONTRACT_PATH = HOME / "contracts/jellyfin.json"


class SanitiseError(Exception):
    """The input cannot be turned into a safe recording. The message never contains input values."""


class _Synth:
    def __init__(self):
        self.counts = {}

    def value(self, field, raw):
        n = self.counts[field] = self.counts.get(field, 0) + 1
        if raw is None:
            return None
        if isinstance(raw, bool):
            return n % 2 == 0
        if isinstance(raw, int):
            return 1000 + n
        if isinstance(raw, float):
            return n / 10
        if isinstance(raw, str):
            return f"synthetic-{field.lower()}-{n}"
        if isinstance(raw, list):
            return []
        if isinstance(raw, dict):
            return {}
        raise SanitiseError(f"{field}: unsupported JSON value")


def sanitise(route, raw_body, contract):
    """Return (sanitised body, sorted undeclared field names per entity). Pure; raises SanitiseError."""
    if route not in contract["routes"]:
        raise SanitiseError("unknown route")
    spec = contract["routes"][route]
    synth = _Synth()
    undeclared = {}
    if spec["envelope"] == "list":
        if not isinstance(raw_body, list):
            raise SanitiseError(f"{route}: body is not a list")
        entries = raw_body
    else:
        if not isinstance(raw_body, dict) or not isinstance(raw_body.get("Items"), list):
            raise SanitiseError(f"{route}: body has no Items list")
        entries = raw_body["Items"]
        undeclared.setdefault("(envelope)", set()).update(
            k for k in raw_body if k not in ("Items", "TotalRecordCount", "StartIndex"))
    kept = []
    for raw in entries[:MAX_ENTRIES]:
        if not isinstance(raw, dict):
            raise SanitiseError(f"{route}: entry is not an object")
        kept.append(_entity(spec["entity"], raw, contract, synth, undeclared))
    if spec["envelope"] == "list":
        body = kept
    else:
        body = {"Items": kept, "TotalRecordCount": len(kept)}
    _assert_no_raw_strings(raw_body, body)
    return body, {k: sorted(v) for k, v in sorted(undeclared.items()) if v}


def _entity(name, raw, contract, synth, undeclared):
    declared = contract["entities"][name]
    out = {}
    for field, value in raw.items():
        if field not in declared:
            undeclared.setdefault(name, set()).add(field)
            continue
        nested = f"{name}.{field}"
        if nested in contract["entities"] and isinstance(value, dict):
            out[field] = _entity(nested, value, contract, synth, undeclared)
        else:
            out[field] = synth.value(field, value)
    return out


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _assert_no_raw_strings(raw_body, body):
    # Output keys are contract field names, so only output VALUES are searched (a Type of "Series" must not
    # trip over the key "SeriesName").
    values = list(_strings(body))
    leaked = sum(1 for s in set(_strings(raw_body)) if len(s) >= 4 and any(s in v for v in values))
    if leaked:
        raise SanitiseError(f"refusing to write: {leaked} raw value(s) would appear in the output")


def build_recording(route, raw_body, server_version, contract, today=None):
    body, undeclared = sanitise(route, raw_body, contract)
    if not isinstance(server_version, str) or not server_version.replace(".", "").isdigit():
        raise SanitiseError("server version must look like 10.11.11")
    return {
        "_recorded": {"date": (today or datetime.date.today()).isoformat(), "server_version": server_version,
                      "note": "Shape only: every value is synthetic. See docs/runbooks/jellyfin-contract-recording.md"},
        "_sanitised_by": VERSION,
        "_undeclared_fields": undeclared,
        "route": route,
        "response": body,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--route", required=True)
    parser.add_argument("--server-version", required=True)
    parser.add_argument("raw", type=Path, help="raw JSON response captured by the owner (local file)")
    parser.add_argument("out", type=Path, help="recording to create (must not exist)")
    a = parser.parse_args(argv)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    try:
        raw = json.loads(a.raw.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("cannot read the raw file as JSON", file=sys.stderr)
        return 2
    try:
        recording = build_recording(a.route, raw, a.server_version, contract)
    except SanitiseError as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 1
    data = (json.dumps(recording, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        print("not written: the output file already exists", file=sys.stderr)
        return 1
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    kept = len(recording["response"] if isinstance(recording["response"], list) else recording["response"]["Items"])
    print(f"wrote {a.out.name}: route {a.route}, {kept} synthetic entr{'y' if kept == 1 else 'ies'}; "
          f"review _undeclared_fields before committing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
