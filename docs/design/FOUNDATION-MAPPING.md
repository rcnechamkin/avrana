# Avrana Media and the Design Foundation

> **Status: proposed, 2026-10-11 (AVR-424).** A mapping of the Media design specification and
> today's source to the shared foundation's names. It changes no stylesheet, template, route or
> deployed service, and decides nothing that [Media 2.0](MEDIA-2.0.md) leaves to the owner.
> **2026-10-26 (MK-7, AVR-721):** the tables below describe the Title Card (pages without the Home shell). Home
> shell pages follow Concept K; its mapping is the last section, "Concept K on Home shell pages".

The [Design Foundation](foundation/README.md) is shared with Avrana Party and mirrored here byte
for byte (the Party repository holds the source copy; `tests/test_design_foundation.py` checks the
mirror). It names roles and contracts. [DESIGN.md](DESIGN.md) remains the Media visual standard:
where the two disagree, DESIGN.md wins and the foundation is corrected.

## Architecture this foundation leaves alone

- Media 2.0 stays Python, FastAPI and Jinja, server-rendered. No front-end framework, component
  library or build step is introduced by the foundation. (Home shell pages since gained one optional
  first-party script and a service worker, owner decision O1; every page works without them.)
- Upstream applications are themed only through hooks they support, or not at all. Nothing is
  injected through the proxy or patched into them.
- Sign-in, the Authentik outpost, group gating, the 404-not-403 rule and the deployment process are
  untouched. No change here needs, or implies, a deployment.

## Colour roles

| Foundation role | DESIGN.md | Value | In source today (`--` variables) |
|---|---|---|---|
| `surface` | Ink | `#000000` | `--bg` |
| `on_surface` | Paper | `#ffffff` | `--fg` |
| `on_surface_muted` | Ash | `#9a9a9a` | `--dim` |
| `outline_quiet` | Quiet Rule | `#474747` | `--line`, written `rgba(255,255,255,0.28)` |
| `outline_control` | Control Rule | `#6e6e6e` | not in source yet (AVR-357, AVR-358, AVR-359) |
| `outline_strong` | Strong Rule | `#999999` | `--line-strong`, written `rgba(255,255,255,0.6)` |
| `action` / `on_action` | primary button | `#ffffff` / `#000000` | `.primary`, `button` |
| `selected` | inversion | white ground, black text | `a.tile:hover`, `.ghost:hover` |
| `focus_ring` | the Focus Ring Rule | 2px black then 2px white | tiles and Audible buttons only, until AVR-357 to AVR-359 |
| `status_ok` / `warn` / `error` | Ok / Warn / Err | `#8fe3a6` / `#e8cf8a` / `#ff8b8b` | `--ok`, `--warn`, `--err` |
| `accent`, `surface_low`, `surface_raised`, `on_surface_faint`, `status_info`, `scrim` | none | none | none |

Roles Media leaves empty are empty on purpose: the No Accent Rule, a flat page with no raised
surfaces, and no modal surfaces today.

## Type, space, shape

| Foundation | Media (DESIGN.md) |
|---|---|
| brand | Wordmark and Wordmark compact, the only two sizes |
| headline | Headline, the page's one `h1` |
| title | Title (tile labels) |
| section | Subtitle; Label is the one uppercase tracked level |
| body, field | Body, 1.0625rem |
| supporting | Small, 0.92rem |
| caption | Label, 0.9rem; nothing smaller |
| code | Copyable Mono only |
| space scale | 4, 8, 12, 16, 24, 32, **44**, 64. Media keeps 44 where the foundation lists 48: it is the column gap the pages are built on |
| compact window | one column; tiles collapse under 560px; the column caps at 720px (640px for single forms) |
| shape | square, 1px rules, no shadow |
| motion | 160ms colour transition only; nothing moves, so reduced motion needs no override |

## Contracts

| Foundation section | Media |
|---|---|
| Navigation: a small set of member pages | the wordmark links home on every inner page; the Footer Is Navigation Rule |
| Buttons | one Primary per form; Ghost; Danger behind a confirmation |
| Fields | visible label, hint with `aria-describedby`, `aria-invalid` |
| Notice | Banner, with `role="status"` or `role="alert"` |
| Dialog, sheet, drawer, menu | none today. A confirmation is its own page, which needs no script. If Media 2.0 adds one, the foundation's dialog contract applies |
| Loading | pages are server-rendered; each Media 2.0 home section loads on its own with a timeout (MEDIA-2.0 section 5) |
| Empty | to be written for the Media 2.0 home (see the audit) |
| Error and degraded | MEDIA-2.0's degradation matrix: the section is replaced by one sentence saying what is unavailable; everything else still works |
| Disconnected | does not apply as it does on Party: Media needs the network. A failed section is the degraded case |
| Touch targets | 44px buttons, 48px fields; footer and store links padded to 44px (AVR-357) |
| Validation | fixture renders, axe-core and screenshots at 390px and 1280px (AVR-360); real-member acceptance (MEDIA-2.0 section 7) |

Findings against these contracts are in the
[2026-10-11 foundation audit](../audits/2026-10-11-design-foundation-audit.md).

## Concept K on Home shell pages (AVR-713, documented 2026-10-26)

> Owner decision D14 (Phase 1 approval, 2026-10-26): **the foundation mirror stays untouched**. This section only
> documents how the Concept K tokens in `services/avrana-home/avrana_home/app/templates/home.css` map onto the
> brand package and the foundation's names. Nothing in `foundation/` or `MIRROR.sha256` changes here, and the Media
> yellow is not a brand or foundation colour (D4). DESIGN.md's Concept K section is the standard.

Two standards apply, by page. The tables above ("Colour roles", "Type, space, shape", "Contracts") describe **the
Title Card**, which still governs the portal, Kindle, Audible and every Home page without the shell, and which the
foundation's `themes.media` records (`tests/test_design_foundation.py` checks those colours against DESIGN.md's
front matter). **Home shell pages** use Concept K, mapped below. The foundation has no theme for Concept K on Home;
the nearest is `themes.party`, which Concept K shares except for the accent, the status colours and the radii.

**Mirror state.** On this branch the mirror is the 2026-10-11 copy (Party surface `#0d0d0f`, interface font Geist).
MK-0 (AVR-714, rcnechamkin/avrana#65, a draft) re-syncs it byte for byte from Party (surface `#121214`, Plus
Jakarta Sans; the Media theme block unchanged). Neither copy names a Media yellow.

### Colours

| `home.css` token | Value | Brand v1.0.0 (`avrana-colors.json`, `--avr-*`) | Foundation role (`themes.party` after MK-0) |
|---|---|---|---|
| `--ink` | `#121214` | Spire Ink, `--avr-ink` | `surface` |
| `--depth` | `#0d0d0f` | Depth, `--avr-depth` | `surface` before MK-0 |
| `--surface` | `#161618` | Surface, `--avr-surface` | `surface_low` |
| `--raised` | `#1e1e21` | Raised, `--avr-raised` | `surface_raised` |
| `--cream` | `#edeae4` | Cream, `--avr-cream` | `on_surface`, `action` |
| `--stone` | `#aeaba7` | Stone, `--avr-stone` | `on_surface_muted` |
| `--ash` | `#8f8c89` | Ash, `--avr-ash` | `on_surface_faint`; also Concept K's strong rule |
| `--graphite` | `#5e5b57` | Graphite, `--avr-graphite` (secondary text on light) | none; decorative only on ink (2.8:1) |
| `--control` | `#6e6c72` | Control, `--avr-control` | `outline_control` |
| `--line` | `rgb(255 255 255 / 0.09)` | `--avr-line` | `outline_quiet` |
| `--line-strong` | `rgb(255 255 255 / 0.18)` | `--avr-line-strong` | `outline_strong` |
| `--ink` on the primary action | `#121214` | Spire Ink | `on_action`, `on_accent` |
| `--accent` | `#eada6e` | **none** (Media-scoped, D2, D4) | `accent` (Party: Atomic Purple `#b9a9e8`, `--avr-purple`) |
| `--accent-deep` | `#776a00` | **none** (Party's counterpart: Purple Deep `#5a439d`) | none |
| `--accent-selected` | yellow at 22 % | none | `selected` (Party: purple at 16 %) |
| `--accent-lens` | yellow at 24 % | none | none (Party's lens) |
| `--focus` | `var(--accent)` | none | `focus_ring` |
| `--ready` | `#34d399` | none (console status) | `status_ok` (Party foundation: `#70c696`) |
| `--warn` | `#f59e0b` | none (console status, D3) | `status_warn` (Party foundation: `#e6b862`) |
| `--danger` | `#ef4444` | none (console status) | `status_error` (Party foundation: `#f08a7e`) |
| none | | | `status_info`, `scrim`, `material*`: not used on Home |

The Title Card names in `home.css` are aliases on shell pages: `--bg` is `--ink`, `--fg` is `--cream`, `--dim` is
`--stone`, `--rule-quiet` is `--graphite`, `--rule-control` is `--control`, `--rule-strong` is `--ash`, `--dim-on-fg`
is `--graphite`. Brand v1.0.0 (AVR-584) first mapped them, before Concept K; the values are unchanged:

| Variable | Title Card value | Brand token | On Spire Ink |
|---|---|---|---|
| `--bg` | `#000000` | Spire Ink `#121214` | |
| `--fg` | `#ffffff` | Cream `#EDEAE4` | 15.6:1 |
| `--dim` | `#9a9a9a` | Stone `#AEABA7` | 8.2:1 |
| `--rule-strong` | `#999999` | Ash `#8F8C89` | 5.6:1 |
| `--rule-control` | `#6e6e6e` | Control `#6E6C72` | 3.6:1 (clears 1.4.11) |
| `--rule-quiet` | `#474747` | Graphite `#5E5B57` | 2.8:1, decorative only |
| `--dim-on-fg` | `#333333` | Graphite `#5E5B57` | 5.6:1 on Cream |

**Repeated hex values** (D4: listed here so a token change finds them): Spire Ink `#121214` is also
`install.THEME` (the manifest's `background_color` and `theme_color`) and the `theme-color` meta in `base.html`. The
yellow's channels `234 218 110` are repeated in two lens rims in `home.css` (the tab lens, and the current tab's
capsule at very large text). Nothing else repeats a Concept K colour.

### Type, space, shape, motion

| Foundation | Concept K on Home (`home.css`) | Brand v1.0.0 |
|---|---|---|
| interface type | Plus Jakarta Sans, variable 200 to 800 (`--font-sans`) | `--avr-font` still names Geist; the brand package has no Plus Jakarta Sans yet (owner's standing rule; the same files as Party #185) |
| brand | the L3 Media lockup on Home, the Spire-A 24px micro cut in the Home button | package SVGs, SHA-pinned in `brand/SOURCES.json` |
| headline | Page, 28px (`--text-page`) | `--avr-text-headline` 1.75rem |
| title | Shelf, 20px (`--text-shelf`) | `--avr-text-title` 1.375rem (differs) |
| display (no foundation role) | Display, 48px Light (`--text-display`) | `--avr-text-display` 3rem |
| body | 15px (`--text-body`) | `--avr-text-body` 0.9375rem |
| supporting | Secondary, 14px (`--text-secondary`) | `--avr-text-supporting` 0.8125rem (differs) |
| caption | Eyebrow, 12px Medium caps (`--text-eyebrow`) | `--avr-text-label` 0.6875rem (differs) |
| field | 17px in the search field | |
| `control_radius_rem` | 0.75 (control), 0.875 (button) | |
| `mark_radius_rem` | 0.5 (chip) | |
| `sheet_radius_rem` | 1 (panel), 1.25 (preview) | |
| elevation | opaque surfaces; glass on exactly three shell controls (tab bar, Home button, Library's utility); shadows only on glass and the update prompt | |
| motion `short`, `medium`, `long` | 150, 300 and 200 ms tiers (tier 3 capped at 200 ms; 600 ms only as a labelled Proposal); a 480 ms spring for the lens | `--avr-duration-quick` 150ms, `-standard` 240ms, `-reveal` 600ms |
| motion `reduced` | Reduce Motion stops every animation and transition | |
| target | 44px minimum everywhere (tabs 52px tall) | |
| space scale | gutters `max(1.25rem, safe area)`; the 720px browse column | `--avr-space-*` |

### Contracts that change on shell pages

| Foundation section | Concept K on Home |
|---|---|
| Navigation | One four-tab glass bar (Home, Library, Search, Me; two tabs without a library), the places bar on Home, the Home button on pages that are not tabs |
| Selected | Yellow lens, chosen chip (tint, rim, check glyph), always with a second cue |
| Focus ring | Yellow ring with an offset; drawn inside glass hosts |
| Notice | The warning: glyph, words, `--warn` edge, opaque rectangle; never the yellow |
| Disconnected | Now applies: `/offline` (service worker) on a failed navigation |
| Loading | Unchanged: server-rendered, per-section timeouts, Try again |
