# AVRANA Brand v1.0.0 on Authentik (staged, not applied)

> **Status: prepared in Git only. Not applied, not deployed, not approved.** auth.avrana.net still wears the
> 2026-08-21 black/white Times house style. Applying this needs the owner's explicit approval for that step
> (`AGENTS.md`), after a backup, with the rollback below ready. Converging every surface is AVR-362's job; this
> covers only Authentik's flow pages and user library, through Authentik's supported hook
> (`Brand.branding_custom_css`), per DESIGN.md's "configurable tier".

> **Revision 2026-10-28 — Media Home's Concept K dress.** Owner: "If we have to send people to Authentik, they at
> least shouldn't even know that it's Authentik. Keep it visually consistent." The sign-in screens now take Home's
> Concept K tokens (home.css): Surface panels with 1rem corners and a hairline edge, 0.75rem fields on a Spire Ink well,
> 0.875rem buttons (the primary is Home's Continue: Cream, 52px, an inset ring on hover, a small press), the Media yellow
> `#EADA6E` for focus rings and the chosen checkbox, and **Plus Jakarta Sans embedded** (Home's own Latin file, 27,348
> bytes, pinned in `SOURCES.json`) instead of Geist-or-system. The footer, language picker and flow-inspector button are
> hidden so nothing names the service. Size: 54,904 bytes of CSS (sha256 `9b10e8b1…`). Where members meet these
> screens, and the owner steps: `../README-member-surfaces.md`. The sections below describe v1 and still hold for
> the wordmark, the escaping rules and the apply/rollback tool; the type and corner notes are superseded.

| File | What it is |
|---|---|
| `avrana-brand-v1.src.css` | The hand-written CSS. Edit this one |
| `avrana-brand-v1.css` | Generated: the source with the package wordmark embedded. What Authentik will hold (16,266 bytes, sha256 `153f3461…d51b4f`) |
| `../blueprints/avrana-landing.yaml` | Generated block: the same CSS as `branding_custom_css`; the rest of the blueprint is unchanged |
| `SOURCES.json` | Package path, byte count and SHA-256 of every embedded package file |
| `build_brand_css.py` | Builds both outputs from the source and a local copy of the package; `--check` compares |
| `brand_css_change.py` | Owner-run on the host: `backup`, `apply`, `verify`, `rollback` |
| `mock/index.html` | Local static mock of the login page (not Authentik) |
| `../../../tests/test_authentik_brand.py` | Offline tests, including apply and rollback against a fake host |

## What changes

- **Tokens** on Authentik's PatternFly and `--ak-*` variables: Spire Ink `#121214` ground, Cream `#EDEAE4` type,
  Stone `#AEABA7` secondary text (8.2:1), Control `#6E6C72` field and secondary-button edges (3.6:1), Ash `#8F8C89`
  link underlines, Graphite `#5E5B57` card edge (decorative). Error text `#FF8B8B` (8.3:1, DESIGN.md
  Err). No Atomic Purple. Square corners, no shadows, the two-ring focus indicator on every control.
- **Type**: the package stack `"Geist", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
  sans-serif`. Geist is **not embedded** by default (see the decision below), so members see their system UI
  face (San Francisco on an iPhone). Monospace is now the platform monospace and only on `code`, `pre`, `kbd`,
  `samp`, which fixes the audit finding that recovery codes rendered in Times.
- **Mark**: the package's **plain cream wordmark**, `02-Logo-Exports/RGB/svg-trimmed/avrana-wordmark_cream_trim.svg`
  (5,327 bytes, sha256 `295e520a836d9687aae85ef78ecd843a2fefaf5ba153044cb1bafbf04d9d80c9`), embedded byte-exact
  as base64 once and reused through `--avr-wordmark`. 200px wide on flow pages (package minimum 120px), with no
  rule beneath it (owner, 2026-10-18); 120px in the user-library header. Never retyped or redrawn: the Times
  `content: "AVRANA"` wordmark goes away. In forced colours the artwork keeps its own Spire Ink patch.
- The stock logo stays in `branding_logo` and is hidden, as today. In the user library the image is hidden only
  visually, so its alt text ("Avrana") still names the home link (today it is `display: none`, which leaves an
  unnamed link).

## Why CSS, and what Authentik 2026.5.6 allows (checked against tag `version/2026.5.6`, commit 0c67ea4)

- **No CSP on flow pages.** No Content-Security-Policy is set by Django settings or middleware
  (`authentik/root/settings.py:280-296`) and the templates carry inline scripts (`flows/templates/if/flow.html:15-31`,
  `core/templates/base/theme.html:12-47`). The only CSP in the server is on uploaded media,
  `default-src 'none'; style-src 'unsafe-inline'; sandbox` (`internal/web/static.go:142`). So `data:` images and
  fonts in the brand CSS load. Our own Caddy or Cloudflare could add one; nothing in this repository does for
  auth.avrana.net, but check the live response headers before applying.
- **`branding_logo` and `branding_favicon` cannot hold a data URI.** Both are `FileField`s
  (`brands/models.py:50-51`) validated by `validate_file_name` (`admin/files/fields.py:7`), which accepts an
  `http:`/`https://` or `fa://` value or a `/static` path as is (`admin/files/validation.py:18-21`,
  `backends/passthrough.py:8-35`, `backends/static.py:98-100`) and otherwise only `[a-zA-Z0-9._/-]`
  (`validation.py:48`). Anything else is served from media as `/files/media/public/<name>?token=…`
  (`backends/file.py:59-100`), which is what broke on 2026-08-21. An absolute `https://` URL would pass through;
  that is an option once avrana.net serves the package files (#62), not today.
- **How the CSS reaches the page.** It is printed in a document `<style data-id="brand-css">` after `<`, `>`
  and `&` are replaced with JSON escapes (`brands/utils.py:63`, `core/templates/base/skeleton.html:30`), and it is
  parsed again into every component's shadow root (`web/src/elements/Base.ts:113-116`). Hence no `<`, `>` or `&`
  anywhere (a test enforces it), and selectors that work in both places.
- **Why the blueprint.** `avrana-landing.yaml` already declares `branding_custom_css`. The worker applies a
  blueprint when its file changes (`blueprints/v1/tasks.py:99-108`) and hourly only if its hash differs
  (`tasks.py:185`). A database-only edit therefore survives until someone next edits that file, and then
  silently reverts. That is the state today: the 2026-08-21 wordmark rules are in the database but not in this
  file, so the next change to this blueprint would drop them. Keeping the CSS in the blueprint removes that trap.

## Size

| Variant | CSS | gzip | Per flow page |
|---|---|---|---|
| Today (Git copy of the house style; the 2026-08-21 edit added wordmark rules in the database only) | 2,014 B | | |
| **Proposed, Geist not embedded** | 16,266 B | 6,611 B | about twice: the `<style>` and the brand JSON (`header_js.html:10`), plus one parse per component |
| Geist embedded (`--embed-geist`) | 109,279 B | 77,808 B | same, so roughly 220 KB more HTML per page before compression, re-parsed by every component |

Geist adds 69,652 bytes of WOFF2, 92,872 as base64. A `@font-face` in a shadow root is not used by Chromium, but
the document copy registers the face for the whole page.

## Owner decisions

Relayed from the owner's chat on 2026-10-18 (first answers: "1. Avrana wordmark  2. sure, and it's approved
3. yep  4. sounds good"; second: "1. the latter  2. What's the difference?  3. Remove the rule from there and Home
for that matter  4. sounds good. proceed"). Also in `docs/DECISIONS.md`.

| Question | State |
|---|---|
| Lockup: plain wordmark or the Media L3 lockup | **Decided: the plain AVRANA wordmark**, cream, `02-Logo-Exports/RGB/svg-trimmed` (as staged) |
| Timing relative to #62's iPhone review | **No longer waiting**: the owner reports #62's branded UI approved |
| Ownership: its own change or under AVR-362 | **Decided: part of AVR-362** (cross-surface convergence) |
| Live apply | Agreed it needs the owner's explicit approval, a backup and a rollback; push and a draft PR approved. **Not an approval of any live step**: each is approved one at a time |
| Geist: system fallback (staged) or embedded (cost above) | **Decided 2026-10-18: system font**, not embedded. Loading it from avrana.net would need #62 deployed plus CORS on the font, so it is not offered |
| The rule under the mark | **Decided: removed** here (and from Home, in a separate Home change) |

## Live steps (each needs the owner's approval; run as cody on host avrana)

1. Look first, read-only: `curl -sI https://auth.avrana.net/if/flow/default-authentication-flow/` for any
   Content-Security-Policy header, and `python3 scripts/drift-check.py` for blueprint drift.
2. Back up (read-only): `python3 services/authentik/brand/brand_css_change.py backup` writes
   `/mnt/avrana_media/.backups/authentik-branding-<UTC>/` (record JSON, exact CSS bytes, the production
   blueprint, a manifest of hashes) and prints `BACKUP_DIR`. It warns if any brand other than
   `authentik-default` exists.
3. Apply: `python3 services/authentik/brand/brand_css_change.py apply BACKUP_DIR
   <reviewed checkout>/services/authentik/blueprints/avrana-landing.yaml --expect-sha256
   b881f0fbae2d5ad0bbdff52d3cca5274f5cb3c7cbc8128a2ef82c209474be102`. It refuses if the file is not that one, if
   the production blueprint is not Git main's (`87b08d4b…`), or if the live CSS changed since the backup. It
   writes the blueprint in place, waits up to 180 s for the worker to record that file's SHA-512 with status
   `successful`, then checks the database value and the served `brand-css` block. The same apply re-asserts the
   blueprint's two link-only applications and their bindings, unchanged.
4. Check in a private window on a phone and a desktop: login, password, a wrong password, the invite flow's
   passkey offer, recovery, and the user library. Hard refresh first.
5. Roll back if anything is wrong: `python3 services/authentik/brand/brand_css_change.py rollback BACKUP_DIR`
   restores the production blueprint, waits for its apply, then writes the backed-up CSS bytes back if they still
   differ (they will: the 2026-08-21 rules are database-only), and checks both the database and the page.

No restart, container recreate, compose change or proxy change is involved.

## Not verified

- The real Authentik page: the mock imitates its markup and applies the CSS the way Authentik does, but its base
  styles are a stand-in. Spacing, the identification stage's own layout, the recovery and enrollment stages, the
  user library's header colour and the admin interface are unchecked until step 4.
- Safari, VoiceOver and forced colours (Chromium only, in the mock).
- The live brand record: whether the 2026-08-21 rules are still there after the September recovery re-applied
  the blueprints. The backup step records it.

Rebuild after editing the source (from the repository root):

```sh
python services/authentik/brand/build_brand_css.py PATH/TO/AVRANA-Brand
python services/authentik/brand/build_brand_css.py PATH/TO/AVRANA-Brand --check
python -m unittest tests.test_authentik_brand
```

The mock: `python -m http.server 8765 --directory services/authentik/brand`, then
`http://localhost:8765/mock/?view=login` (also `password`, `error`, `passkey`, `library`).
