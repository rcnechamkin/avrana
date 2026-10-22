#!/usr/bin/env python3
"""Copy the approved AVRANA Brand v1.0.0 files that Home serves into avrana_home/app/brand/ (AVR-584).

Standard library only. Reads a local copy of the brand package (the `AVRANA-Brand/` folder, never the network),
copies each file below byte for byte, and records its package path and SHA-256 in `brand/SOURCES.json`.

The repository tracks no binary files (`scripts/review_git_content.py`), so the binary ones (PNG icons, the
Geist WOFF2) are stored as base64 text (`<name>.b64`); `avrana_home/app/brand.py` decodes them and refuses to
serve bytes whose SHA-256 differs from SOURCES.json. SVG and licence files are copied as they are.

    python services/avrana-home/tools/sync_brand_assets.py PATH/TO/AVRANA-Brand           # write
    python services/avrana-home/tools/sync_brand_assets.py PATH/TO/AVRANA-Brand --check   # compare only

Nothing here redraws, recolours or re-encodes artwork. To take a new brand version, point this at the new
package, review the diff, and update the version below.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

VERSION = "1.0.0"
OUT = Path(__file__).resolve().parents[1] / "avrana_home" / "app" / "brand"
MARKS = "AVRANA, all rights reserved (brand package README, Licences)"
OFL = "SIL Open Font License 1.1 (OFL.txt, kept beside it)"
# served name -> (path inside the package, stored as base64?, licence)
ASSETS = {
    "avrana-media-lockup-product_cream_trim.svg": (
        "02-Logo-Exports/Product-Lockups/RGB/svg-trimmed/avrana-media-lockup-product_cream_trim.svg", False, MARKS),
    "favicon.svg": ("04-Digital-Assets/Website/favicon/favicon.svg", False, MARKS),
    "apple-touch-icon.png": ("04-Digital-Assets/Website/favicon/apple-touch-icon.png", True, MARKS),
    "icon-192.png": ("04-Digital-Assets/Website/favicon/icon-192.png", True, MARKS),
    "icon-512.png": ("04-Digital-Assets/Website/favicon/icon-512.png", True, MARKS),
    "icon-maskable-512.png": ("04-Digital-Assets/Website/favicon/icon-maskable-512.png", True, MARKS),
    "Geist-Variable.woff2": ("03-Typography-and-Colors/fonts/Geist-Variable.woff2", True, OFL),
    "OFL.txt": ("03-Typography-and-Colors/fonts/OFL.txt", False, OFL),
}


def stored_name(name: str, b64: bool) -> str:
    return name + ".b64" if b64 else name


def encode(data: bytes, b64: bool) -> bytes:
    if not b64:
        return data
    text = base64.b64encode(data).decode("ascii")
    return ("\n".join(text[i:i + 76] for i in range(0, len(text), 76)) + "\n").encode("ascii")


def build(package: Path) -> tuple[dict, dict]:
    readme = (package / "README.md").read_text(encoding="utf-8")
    if f"v{VERSION}" not in readme.splitlines()[0]:
        raise SystemExit(f"{package}/README.md does not name brand package v{VERSION}")
    files, sources = {}, {}
    for name, (rel, b64, licence) in ASSETS.items():
        data = (package / rel).read_bytes()
        files[stored_name(name, b64)] = encode(data, b64)
        sources[name] = {"package_path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                         "stored_as": "base64" if b64 else "verbatim", "licence": licence}
    manifest = {"_comment": "Written by tools/sync_brand_assets.py; do not edit by hand. sha256 is of the ORIGINAL "
                            "package file; brand.py refuses to serve bytes that do not match.",
                "package": "AVRANA-Brand", "version": VERSION, "files": sources}
    files["SOURCES.json"] = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return files, manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", type=Path, help="the AVRANA-Brand folder of the brand package")
    ap.add_argument("--check", action="store_true", help="report differences, write nothing")
    args = ap.parse_args()
    files, _ = build(args.package)
    differ = [n for n, data in files.items() if not (OUT / n).is_file() or (OUT / n).read_bytes() != data]
    if args.check:
        for n in differ:
            print(f"DIFFERS {n}")
        print("brand assets match the package" if not differ else f"{len(differ)} file(s) differ")
        return 1 if differ else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n in differ:
        (OUT / n).write_bytes(files[n])
        print(f"wrote {n}")
    print(f"{len(files)} files, {len(differ)} written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
