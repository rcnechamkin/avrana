# Approved brand files for Home (AVR-584)

Copied from the **AVRANA brand package v1.0.0** (`AVRANA-Brand/`, approved 2026-10-17) by
`tools/sync_brand_assets.py`. Do not edit, redraw, recolour or re-encode them here; change the brand package and
re-run the tool. `SOURCES.json` records each file's package path, byte count and the SHA-256 of the original bytes,
and `avrana_home/app/brand.py` refuses to serve a file that does not match it.

| Served at | File | Package source | Licence |
|---|---|---|---|
| `/brand/avrana-media-l3.svg` | `avrana-media-lockup-product_cream_trim.svg` | `02-Logo-Exports/Product-Lockups/RGB/svg-trimmed/` (L3, in-product) | AVRANA, all rights reserved |
| `/brand/favicon.svg` | `favicon.svg` | `04-Digital-Assets/Website/favicon/` (micro cut 16, built by the package) | AVRANA, all rights reserved |
| `/icons/avrana-180.png` | `apple-touch-icon.png.b64` | `04-Digital-Assets/Website/favicon/` | AVRANA, all rights reserved |
| `/icons/avrana-192.png` | `icon-192.png.b64` | same | AVRANA, all rights reserved |
| `/icons/avrana-512.png` | `icon-512.png.b64` | same | AVRANA, all rights reserved |
| `/icons/avrana-maskable-512.png` | `icon-maskable-512.png.b64` | same | AVRANA, all rights reserved |
| `/brand/geist.woff2` | `Geist-Variable.woff2.b64` | `03-Typography-and-Colors/fonts/` (Geist 1.800, variable 100 to 900) | SIL OFL 1.1, `OFL.txt` |

**Why base64.** This repository tracks no binary files, and `scripts/review_git_content.py` refuses PNG and NUL
bytes. The PNG icons and the WOFF2 are therefore stored as base64 text of the exact package bytes (`*.b64`); the
SVGs and `OFL.txt` are verbatim. Storing them this way is an owner decision recorded in the AVR-584 pull request.

**Colours and type** are not copied from the package as a file: the Home shell maps the package tokens
(`03-Typography-and-Colors/tokens/avrana-tokens.css`: Spire Ink `#121214`, Cream `#EDEAE4`, Stone, Ash, Graphite,
Control and the Geist stack) onto its existing variables in `templates/home.css`. Atomic Purple is Party only and is
not used. See DESIGN.md, "Approved brand on Home shell pages".

Check against a local copy of the package (run from the repository root):

```sh
python services/avrana-home/tools/sync_brand_assets.py PATH/TO/AVRANA-Brand --check
```
