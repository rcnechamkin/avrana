#!/usr/bin/env python3
"""Extract the minimal interface facts the Home Jellyfin adapter depends on from Jellyfin's published OpenAPI file.

    python -B tools/extract_openapi_subset.py SPEC.json --source-url URL --retrieved YYYY-MM-DD [SPEC.json ...]

Writes `contracts/jellyfin-openapi-subset.json` (R2-A, AVR-747). Run by a person, offline, on spec files
downloaded by hand from https://repo.jellyfin.org/files/openapi/ ; nothing in the test suite downloads anything.
`--source-url` must be the clean URL the file was downloaded from; `--retrieved` the ISO date it was downloaded.

Minimal by construction (owner question Q5): only what the adapter actually calls, sends or reads is kept, using
the fixed allow-lists below, which mirror `avrana_home/adapters/jellyfin.py` exactly (the test checks this):
  * the routes it calls, and of each route's GET query parameters only the NAMES it sends, plus whether the route
    declares a security requirement, whether it is deprecated, and its response envelope (array of X, or X);
  * of the schemas it parses, only the NAMES and JSON types of the properties it reads (plus `UserItemDataDto.
    UserId`, kept so the test can prove it is still absent upstream: the KNOWN_ABSENT tripwire);
  * of five enums, only the members it sends or matches on.
No descriptions, examples or other upstream text are copied and the full spec is never vendored. Whether even this
extraction is free of the server's GPL-2.0 licence is UNRESOLVED (see LICENCE below). Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
OUT = HOME / "contracts/jellyfin-openapi-subset.json"

# spec path -> the query keys the adapter sends there (= ALLOWED_ROUTES in avrana_home/adapters/jellyfin.py)
PATHS = {
    "/Users": (),
    "/UserItems/Resume": ("userId", "limit", "mediaTypes", "fields", "enableUserData", "enableImageTypes",
                          "enableTotalRecordCount"),
    "/Items/Latest": ("userId", "limit", "includeItemTypes", "groupItems", "fields", "enableImageTypes",
                      "enableUserData"),
    "/Shows/NextUp": ("userId", "limit", "fields", "enableUserData", "enableImageTypes", "enableTotalRecordCount"),
    "/Items": ("userId", "ids", "fields", "enableUserData", "enableImageTypes", "searchTerm", "includeItemTypes",
               "recursive", "limit", "sortBy", "sortOrder", "maxPremiereDate", "isMissing"),
    "/Items/{itemId}/Images/{imageType}": ("maxWidth", "quality"),
}
# schema -> the properties the adapter reads
SCHEMAS = {
    "BaseItemDto": ("Id", "Name", "Type", "SeriesName", "ParentIndexNumber", "IndexNumber", "ProductionYear",
                    "RunTimeTicks", "UserData", "ImageTags", "Overview", "ProviderIds",
                    "BackdropImageTags", "ParentBackdropItemId", "ParentBackdropImageTags", "PremiereDate",
                    "SeriesId", "SeriesPrimaryImageTag", "People", "Genres", "Tags"),
    # one entry of BaseItemDto.People (title page only: richer Details, 2026-10-28)
    "BaseItemPerson": ("Name", "Type"),
    "BaseItemDtoQueryResult": ("Items",),
    # UserId is read only if present and is absent upstream; kept here so its absence is checked, not assumed
    "UserItemDataDto": ("PlaybackPositionTicks", "PlayedPercentage", "Played", "ItemId", "UserId"),
    "UserDto": ("Id", "Name", "Policy"),
    "UserPolicy": ("IsDisabled",),
}
# enum -> the members the adapter sends (fields, enableImageTypes, includeItemTypes, mediaTypes) or matches on
ENUMS = {
    "ItemFields": ("Genres", "Overview", "People", "PrimaryImageAspectRatio", "ProviderIds", "Tags"),
    "ImageType": ("Backdrop", "Primary"),
    "BaseItemKind": ("Episode", "Movie", "Series"),
    "MediaType": ("Video",),
    "PersonKind": ("Actor", "Director", "Writer"),     # matched on only (BaseItemPerson.Type), never sent
}

STATUS = ("Minimal interface facts (names and types only) extracted from Jellyfin's published OpenAPI files by "
          "tools/extract_openapi_subset.py (R2-A, AVR-747): only the routes, query keys, schema properties and "
          "enum members the Home adapter calls, sends or reads. The full spec is not vendored.")
LICENCE = {
    "upstream_code": "GPL-2.0 (Jellyfin server, jellyfin/jellyfin; the OpenAPI document is generated from it)",
    "openapi_document": "no separate licence statement was found for the published OpenAPI document",
    "status": "UNRESOLVED: whether extracting interface names and types from it is free of the GPL-2.0 (or any "
              "other) licence has not been determined; awaits owner/legal disposition (owner question Q5). No "
              "clearance is asserted.",
    "kept": "route paths, query-parameter names, schema-property names with JSON types, enum-member names, "
            "response envelope names, authenticated/deprecated flags, and source provenance; no descriptions, "
            "examples or other prose",
}
COMPARISON_NOTE = ("Entries other than the deployed 10.11.11 are a published-interface comparison only: they imply "
                   "no compatibility guarantee and no upgrade is authorised (owner question Q1).")


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


def version_entry(version: str, source_url: str, sha256: str, retrieved: str, paths: dict, schemas: dict,
                  enums: dict) -> dict:
    entry = {"version": version, "source_url": source_url, "sha256": sha256, "retrieved": retrieved,
             "paths": paths, "schemas": schemas, "enums": enums}
    if version not in source_url:
        entry["source_note"] = ("source_url is a moving alias (it now serves whatever is current), so the "
                                "sha256 is what pins the file that was read")
    return entry


def document(versions: dict) -> dict:
    return {"_status": STATUS, "_licence": LICENCE, "_comparison": COMPARISON_NOTE, "versions": versions}


def subset(spec: dict, raw: bytes, source_url: str, retrieved: str) -> dict:
    paths = {}
    for path, keys in PATHS.items():
        op = spec["paths"].get(path, {}).get("get")
        if op is None:
            continue
        paths[path] = {
            "query": sorted(p["name"] for p in op.get("parameters", [])
                            if p.get("in") == "query" and p["name"] in keys),
            "authenticated": bool(op.get("security")),
            "deprecated": bool(op.get("deprecated")),
            "response": _envelope(op),
        }
    components = spec["components"]["schemas"]
    schemas = {name: {k: _type_of(v) for k, v in sorted(components[name].get("properties", {}).items())
                      if k in props}
               for name, props in SCHEMAS.items() if name in components}
    enums = {name: sorted(m for m in components[name]["enum"] if m in members)
             for name, members in ENUMS.items() if name in components}
    return version_entry(spec["info"]["version"], source_url, hashlib.sha256(raw).hexdigest(), retrieved,
                         paths, schemas, enums)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", nargs="+", help="spec file, each followed by --source-url and --retrieved")
    parser.add_argument("--source-url", action="append", required=True)
    parser.add_argument("--retrieved", action="append", required=True, help="ISO date the file was downloaded")
    args = parser.parse_intermixed_args()
    if not len(args.spec) == len(args.source_url) == len(args.retrieved):
        parser.error("give one --source-url and one --retrieved per spec file")
    versions = []
    for path, url, retrieved in zip(args.spec, args.source_url, args.retrieved):
        raw = Path(path).read_bytes()
        versions.append(subset(json.loads(raw), raw, url, retrieved))
    doc = document({v["version"]: v for v in versions})
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(HOME).as_posix()}: " + ", ".join(v["version"] for v in versions))


if __name__ == "__main__":
    main()
