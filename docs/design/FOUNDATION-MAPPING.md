# Avrana Media and the Design Foundation

> **Status: proposed, 2026-10-11 (AVR-424).** A mapping of the Media design specification and
> today's source to the shared foundation's names. It changes no stylesheet, template, route or
> deployed service, and decides nothing that [Media 2.0](MEDIA-2.0.md) leaves to the owner.

The [Design Foundation](foundation/README.md) is shared with Avrana Party and mirrored here byte
for byte (the Party repository holds the source copy; `tests/test_design_foundation.py` checks the
mirror). It names roles and contracts. [DESIGN.md](DESIGN.md) remains the Media visual standard:
where the two disagree, DESIGN.md wins and the foundation is corrected.

## Architecture this foundation leaves alone

- Media 2.0 stays Python, FastAPI and Jinja, server-rendered with minimal JavaScript. No
  front-end framework, component library or build step is introduced by the foundation.
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
