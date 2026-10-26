#!/usr/bin/env python3
"""Extract the small, factual part of Jellyfin's published OpenAPI file that the Home adapter depends on.

    python -B tools/extract_openapi_subset.py SPEC.json --source-url URL [SPEC.json --source-url URL ...]

Writes `contracts/jellyfin-openapi-subset.json` (R2-A, AVR-747). Run by a person, offline, on spec files
downloaded by hand from https://repo.jellyfin.org/files/openapi/ ; nothing in the test suite downloads anything.

What is kept, per spec version: the version string, the source URL and SHA-256 of the file read, and for a
fixed list of paths only the GET query parameter NAMES, whether the route declares a security requirement, and
the response envelope (array of X, or X). For a fixed list of schemas only property NAMES and their JSON types,
and the members of four enums. No descriptions, examples or other text are copied: the subset records the
interface, not the upstream's documentation (docs/audits/2026-10-26-oss-reuse-audit.md, owner question Q5).
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
OUT = HOME / "contracts/jellyfin-openapi-subset.json"

# Paths the adapter calls today, plus two documented candidates named in the R1 backlog (Next Up, single item).
PATHS = ("/Users", "/UserItems/Resume", "/Items/Latest", "/Items", "/Items/{itemId}/Images/{imageType}",
         "/Shows/NextUp", "/Items/{itemId}")
SCHEMAS = ("BaseItemDto", "BaseItemDtoQueryResult", "UserItemDataDto", "UserDto", "UserPolicy")
ENUMS = ("ItemFields", "ImageType", "BaseItemKind", "MediaType")


def _ref_name(schema: dict) -> str:
    ref = schema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref else ""


def _type_of(prop: dict) -> str:
    if "$ref" in prop:
        return "ref:" + _ref_name(prop)
    if "allOf" in prop and len(prop["allOf"]) == 1:
        return "ref:" + _ref_name(prop["allOf"][0])
    if "enum" in prop:
        return "enum"
    return str(prop.get("type", "unknown"))


def _envelope(op: dict) -> str:
    content = op.get("responses", {}).get("200", {}).get("content", {})
    schema = (content.get("application/json") or next(iter(content.values()), {})).get("schema", {})
    if schema.get("type") == "array":
        return "array:" + _ref_name(schema.get("items", {}))
    return _ref_name(schema) or str(schema.get("type", "none"))


def subset(spec: dict, raw: bytes, source_url: str) -> dict:
    paths = {}
    for path in PATHS:
        op = spec["paths"].get(path, {}).get("get")
        if op is None:
            continue
        paths[path] = {
            "query": sorted(p["name"] for p in op.get("parameters", []) if p.get("in") == "query"),
            "authenticated": bool(op.get("security")),
            "deprecated": bool(op.get("deprecated")),
            "response": _envelope(op),
        }
    components = spec["components"]["schemas"]
    schemas = {name: {k: _type_of(v) for k, v in sorted(components[name].get("properties", {}).items())}
               for name in SCHEMAS if name in components}
    enums = {name: sorted(components[name]["enum"]) for name in ENUMS if name in components}
    return {"version": spec["info"]["version"], "source_url": source_url,
            "sha256": hashlib.sha256(raw).hexdigest(), "paths": paths, "schemas": schemas, "enums": enums}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", nargs="+", help="spec file, each followed by --source-url")
    parser.add_argument("--source-url", action="append", required=True)
    args = parser.parse_intermixed_args()
    if len(args.spec) != len(args.source_url):
        parser.error("give one --source-url per spec file")
    versions = []
    for path, url in zip(args.spec, args.source_url):
        raw = Path(path).read_bytes()
        versions.append(subset(json.loads(raw), raw, url))
    doc = {"_status": "Interface facts extracted from Jellyfin's published OpenAPI files by "
                      "tools/extract_openapi_subset.py (R2-A, AVR-747). Names and types only.",
           "versions": {v["version"]: v for v in versions}}
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(HOME).as_posix()}: " + ", ".join(v["version"] for v in versions))


if __name__ == "__main__":
    main()
