#!/usr/bin/env python3
"""Build Authentik's Brand.branding_custom_css from avrana-brand-v1.src.css and the AVRANA brand package.

    python3 services/authentik/brand/build_brand_css.py PATH/TO/AVRANA-Brand          # write
    python3 services/authentik/brand/build_brand_css.py PATH/TO/AVRANA-Brand --check  # compare with the package
    python3 services/authentik/brand/build_brand_css.py --check                       # offline: pins and sync only

Writes avrana-brand-v1.css (for review) and the same text into the branding_custom_css block of
services/authentik/blueprints/avrana-landing.yaml, which is what Authentik applies. The package files are
embedded byte-exact as base64 and must match the SHA-256 in SOURCES.json. Media Home's Plus Jakarta Sans Latin face
(the file Home itself serves, services/avrana-home/avrana_home/app/brand/, 27 KB) is always embedded, so the sign-in
screens use Home's type (owner, 2026-10-28). Without a package folder the build reuses the wordmark already embedded
in avrana-brand-v1.css, after checking it against its pin.
Stdlib only. Nothing here talks to Authentik.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SRC = HERE / 'avrana-brand-v1.src.css'
OUT = HERE / 'avrana-brand-v1.css'
SOURCES = HERE / 'SOURCES.json'
BLUEPRINT = ROOT / 'services/authentik/blueprints/avrana-landing.yaml'
FONT_STACK = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
JAKARTA = ROOT / 'services/avrana-home/avrana_home/app/brand/PlusJakartaSans-Latin-Variable.woff2.b64'
# Home's own unicode-range for the Latin file (home.css), so Latin Extended text falls back to the system face.
JAKARTA_RANGE = ('U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, '
                 'U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD')
WORDMARK_TOKEN = '@@AVRANA_WORDMARK_CREAM@@'
BLOCK_KEY = '      branding_custom_css: |\n'
BLOCK_INDENT = ' ' * 8
DATA_URI = re.compile(r'url\("data:(image/svg\+xml|font/woff2);base64,([A-Za-z0-9+/=]+)"\)')


def sources() -> dict:
    return json.loads(SOURCES.read_text(encoding='utf-8'))['files']


def package_bytes(package: Path, entry: dict) -> bytes:
    data = (package / entry['package_path']).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != entry['bytes'] or digest != entry['sha256']:
        sys.exit(f"FAIL {entry['package_path']}: {len(data)} bytes, sha256 {digest}; SOURCES.json pins "
                 f"{entry['bytes']} bytes, {entry['sha256']}. Not the approved v1.0.0 file.")
    return data


def jakarta_bytes() -> bytes:
    data = base64.b64decode(''.join(JAKARTA.read_text(encoding='ascii').split()), validate=True)
    pin = sources()['plus_jakarta_latin']
    if len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
        sys.exit(f'FAIL {JAKARTA.name} does not match its pin in SOURCES.json')
    return data


def render(wordmark: bytes, font: bytes) -> str:
    css = SRC.read_text(encoding='utf-8')
    css = css.replace(WORDMARK_TOKEN, base64.b64encode(wordmark).decode('ascii'))
    css = css.replace('@@FONT_STACK@@', FONT_STACK)
    face = ('@font-face {\n  font-family: "Plus Jakarta Sans";\n  src: url("data:font/woff2;base64,'
            + base64.b64encode(font).decode('ascii')
            + '") format("woff2");\n  font-weight: 200 800;\n  font-display: swap;\n  unicode-range: '
            + JAKARTA_RANGE + ';\n}\n\n')
    marker = '\n:root,\n'
    css = css.replace(marker, '\n' + face + ':root,\n', 1)
    if '@@' in css:
        sys.exit('FAIL unreplaced @@ token in the source CSS')
    if any(ch in css for ch in '<>&'):
        sys.exit('FAIL the CSS contains < > or &, which Authentik rewrites (authentik/brands/utils.py:63)')
    if '\r' in css:
        sys.exit('FAIL the CSS contains a carriage return')
    return css.rstrip('\n') + '\n'


def blueprint_with(css: str, text: str) -> str:
    start = text.index(BLOCK_KEY) + len(BLOCK_KEY)
    end = start
    lines = text[start:].split('\n')
    consumed = 0
    for line in lines:
        if line and not line.startswith(BLOCK_INDENT):
            break
        consumed += len(line) + 1
    end = start + consumed
    body = ''.join((BLOCK_INDENT + line if line else '') + '\n' for line in css.rstrip('\n').split('\n'))
    return text[:start] + body + '\n' + text[end:].lstrip('\n')


def blueprint_css(text: str) -> str:
    """The branding_custom_css value as YAML's literal-block (clip) rules read it."""
    start = text.index(BLOCK_KEY) + len(BLOCK_KEY)
    out = []
    for line in text[start:].split('\n'):
        if line and not line.startswith(BLOCK_INDENT):
            break
        out.append(line[len(BLOCK_INDENT):])
    return '\n'.join(out).rstrip('\n') + '\n'


def embedded(css: str) -> dict[str, bytes]:
    found = {}
    for mime, b64 in DATA_URI.findall(css):
        found[mime] = base64.b64decode(b64, validate=True)
    return found


def check_offline(css: str) -> list[str]:
    problems = []
    pins = sources()
    found = embedded(css)
    wm = found.get('image/svg+xml')
    if wm is None or hashlib.sha256(wm).hexdigest() != pins['wordmark_cream']['sha256']:
        problems.append('embedded wordmark does not decode to the pinned package bytes')
    font = found.get('font/woff2')
    if font is None or hashlib.sha256(font).hexdigest() != pins['plus_jakarta_latin']['sha256']:
        problems.append('embedded Plus Jakarta Sans does not decode to the pinned file')
    expected = render(wm or b'', font or b'')
    if css != expected:
        problems.append('avrana-brand-v1.css is not the build of avrana-brand-v1.src.css; re-run the build')
    if blueprint_css(BLUEPRINT.read_text(encoding='utf-8')) != css:
        problems.append('avrana-landing.yaml branding_custom_css differs from avrana-brand-v1.css; re-run the build')
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='?', type=Path, help='local AVRANA-Brand folder (v1.0.0)')
    ap.add_argument('--check', action='store_true', help='compare instead of writing')
    args = ap.parse_args()
    if args.check:
        css = OUT.read_text(encoding='utf-8')
        problems = check_offline(css)
        if args.package is not None:
            pins = sources()
            wm = package_bytes(args.package, pins['wordmark_cream'])
            if render(wm, jakarta_bytes()) != css:
                problems.append('avrana-brand-v1.css does not match a fresh build from the package')
        for p in problems:
            print('FAIL', p)
        if not problems:
            print(f'OK {OUT.name} and avrana-landing.yaml match ({len(css.encode())} bytes of CSS)')
        return 1 if problems else 0
    pins = sources()
    if args.package is not None:
        wm = package_bytes(args.package, pins['wordmark_cream'])
    else:
        wm = embedded(OUT.read_text(encoding='utf-8')).get('image/svg+xml', b'')
        if hashlib.sha256(wm).hexdigest() != pins['wordmark_cream']['sha256']:
            sys.exit('FAIL no package folder given and the embedded wordmark does not match its pin')
    css = render(wm, jakarta_bytes())
    OUT.write_bytes(css.encode('utf-8'))
    BLUEPRINT.write_bytes(blueprint_with(css, BLUEPRINT.read_text(encoding='utf-8')).encode('utf-8'))
    print(f'wrote {OUT.relative_to(ROOT)} and {BLUEPRINT.relative_to(ROOT)}: {len(css.encode())} bytes of CSS'
          f" (wordmark {pins['wordmark_cream']['bytes']} B; Plus Jakarta Sans {pins['plus_jakarta_latin']['bytes']} B)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
