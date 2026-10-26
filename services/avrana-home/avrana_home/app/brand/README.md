# Approved brand files and the interface font for Home (AVR-584, AVR-715)

Copied from the **AVRANA brand package v1.0.0** (`AVRANA-Brand/`, approved 2026-10-17) by
`tools/sync_brand_assets.py`. Do not edit, redraw, recolour or re-encode them here; change the brand package and
re-run the tool. `SOURCES.json` records each file's package path (for the fonts, their npm `source`), byte count and
the SHA-256 of the original bytes,
and `avrana_home/app/brand.py` refuses to serve a file that does not match it.

| Served at | File | Package source | Licence |
|---|---|---|---|
| `/brand/avrana-media-l3.svg` | `avrana-media-lockup-product_cream_trim.svg` | `02-Logo-Exports/Product-Lockups/RGB/svg-trimmed/` (L3, in-product) | AVRANA, all rights reserved |
| `/brand/favicon.svg` | `favicon.svg` | `04-Digital-Assets/Website/favicon/` (micro cut 16, built by the package) | AVRANA, all rights reserved |
| `/icons/avrana-180.png` | `apple-touch-icon.png.b64` | `04-Digital-Assets/Website/favicon/` | AVRANA, all rights reserved |
| `/icons/avrana-192.png` | `icon-192.png.b64` | same | AVRANA, all rights reserved |
| `/icons/avrana-512.png` | `icon-512.png.b64` | same | AVRANA, all rights reserved |
| `/icons/avrana-maskable-512.png` | `icon-maskable-512.png.b64` | same | AVRANA, all rights reserved |
| `/brand/plus-jakarta-sans-latin.woff2` | `PlusJakartaSans-Latin-Variable.woff2.b64` | not in the brand package: npm `@fontsource-variable/plus-jakarta-sans` 5.3.0, `files/plus-jakarta-sans-latin-wght-normal.woff2` (the copy Avrana Party ships), SHA-256 pinned in the sync tool | SIL OFL 1.1, `OFL-PlusJakartaSans.txt` |
| `/brand/plus-jakarta-sans-latin-ext.woff2` | `PlusJakartaSans-LatinExt-Variable.woff2.b64` | same package, `files/plus-jakarta-sans-latin-ext-wght-normal.woff2` | SIL OFL 1.1, `OFL-PlusJakartaSans.txt` |

**Why base64.** This repository tracks no binary files, and `scripts/review_git_content.py` refuses PNG and NUL
bytes. The PNG icons and the WOFF2 fonts are therefore stored as base64 text of the exact package bytes (`*.b64`); the
SVGs and the licence text are verbatim. The owner accepted this packaging for brand v1.0 on 2026-10-18, for this folder
only, because every file is hash-verified and self-contained; it does not broaden the repository's binary policy.

**Colours** are not copied from the package as a file (the fonts are, from npm, above): the Home shell maps the package tokens
(`03-Typography-and-Colors/tokens/avrana-tokens.css`: Spire Ink `#121214`, Cream `#EDEAE4`, Stone, Ash, Graphite,
Control) onto its variables in `templates/home.css`. Atomic Purple is Party only and is not used; the Media yellow
(Concept K, AVR-715) is a Media-scoped token there, not a brand file. See DESIGN.md, "Brand v1.0.0 on Home shell pages".

Check against a local copy of the package (run from the repository root):

```sh
python services/avrana-home/tools/sync_brand_assets.py PATH/TO/AVRANA-Brand --fonts PATH/TO/FONTS --check
```
