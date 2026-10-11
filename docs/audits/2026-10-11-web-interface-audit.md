# Web interface audit, 2026-10-11

Visual, accessibility and architectural audit of every web interface on Avrana, with a proposed
design system ([`docs/design/DESIGN.md`](../design/DESIGN.md)) and an incremental plan.

**Method and limits.** Evidence is the code in Git at `9d8799d` plus local renders: the portal,
Kindle connector and Audible connector pages were rendered from their own templates with fixture
identities and data (no network, no database, nothing on the host), then screenshotted in
Chromium at 1280px and 390px. The live host was **not** reached from this session, so Authentik,
Homepage and the upstream applications were assessed from their committed configuration only.
Fonts in the renders are Liberation Serif, the Linux metric twin of Times New Roman. Nothing was
changed, restarted or deployed. Skills applied: Impeccable (audit, document), Anthropic
frontend-design, UIZZE ui-design and anti-ui-slop, Vercel web-design-guidelines. ui-radar was not
used: no open decision needed outside references, and it queries a third-party service.

## 1. Inventory

Two audiences: **members** (non-technical, mostly on phones and TVs, arrive through
`avrana.net`) and **the operator** (Cody, on the LAN, through Homepage, OliveTin and the admin UIs).

### Custom: source in this repo, safe to change through a PR

| Interface | Hostname | Audience | Source | Notes |
|---|---|---|---|---|
| Avrana portal | avrana.net | Members | `services/avrana-portal/portal.py` | Role-aware grid, choosers, account, help, interstitial. The reference implementation of the house style |
| Kindle connector | kindle.avrana.net | Members (`avrana-books`) | `services/avrana-kindle-connector/kindle.py` | One form; writes CWA and ABS. Own copy of the CSS |
| Audible connector | contribute.avrana.net | Members (`library-contributors`) | `services/avrana-audible-connector/connector/app/templates/`, `static/style.css` | Five-step flow. Third copy of the CSS, different header |
| libation-status, imax-verify, libation companion | LAN / none | Machines | `services/libation-status/`, `services/avrana-imax-verify/`, `services/avrana-audible-connector/companion/` | JSON only. No UI to design |

### Configurable: upstream application, theme only through its supported hook

| Interface | Hostname | Hook | Current state |
|---|---|---|---|
| Authentik flows and user library | auth.avrana.net | `Brand.branding_custom_css` and flow titles, in `services/authentik/blueprints/avrana-landing.yaml` and the database | House style applied (2026-08-21); wordmark drawn in CSS |
| Homepage | 10.0.0.218:3000 (LAN) | `deploy/homepage/config/*.yaml`, `custom.css` (empty) | Stock `slate` theme, operator dashboard |
| OliveTin | ops.avrana.net | `services/olivetin/config/config.yaml` | Stock look; admin only |
| Jellyfin | watch.avrana.net | Dashboard branding (custom CSS, login disclaimer), stored in Jellyfin's config | Unbranded. Optional, owner decision |

### Upstream: do not modify

Seerr, Audiobookshelf, Komga, Calibre-Web-Automated, Shelfarr, Shelfmark, Omnibus, Radarr, Sonarr,
Prowlarr, Bazarr, SABnzbd, Mylar3, Tracearr, Beszel, completeseries, Home Assistant, UniFi OS
Server, BookStack (retired in place; do not write to it). These keep their own design. Avrana's
job at their edge is a clean hand-off: the right link, the right sign-in instructions, nothing
injected through the proxy. CWA already carries a behavioural patch
(`services/calibre-web-automated/avrana-patch/`) that does not touch its UI; keep it that way.

## 2. Architectural findings

**A1. Three front doors with different names for the same things.** Members can land on
`avrana.net` (portal), `auth.avrana.net/if/user/` (Authentik's "My applications", branded and
role-aware) or a service hostname. The Authentik library labels Jellyfin "TV and Movies" in a
group called "Watch" and puts Seerr ("Requests") under Watch too; the portal says "Watch: Movies &
TV" and nests requests under "Request". Recommendation: make `avrana.net` the one member front door
and send Authentik's post-login landing there (brand default application or a redirect stage).
That is an Authentik change and an owner decision; the library can stay as a fallback.

**A2. The house style is copied, not shared.** The same tokens and components live in three
places that have already drifted: portal (`portal.py:361`), Kindle (`kindle.py:132`) and Audible
(`style.css`), plus a fourth translation in Authentik's brand CSS. The wordmark is drawn four ways:
portal clamp(2.6 to 4.4rem) at 0.34em, Kindle clamp(2 to 3rem) at 0.28em, Audible a 1.25rem
left-aligned topbar at 0.3em, Authentik 40px at 0.34em. Kindle's column is 640px, the others 720px.
Recommendation: one canonical stylesheet (Section 5, phase 2) with an offline test that fails when
a copy drifts, the same guard the komga mirror lacks.

**A3. Navigation dead ends.** The Audible connector has no link back to `avrana.net` at all; its
header is not a link. Help pages name no topic on the page itself. Everything else has a footer
"Back", which is the right pattern and should be universal.

**A4. Homepage reflects the estate of August, not October.** `deploy/homepage/config/services.yaml`:
the Libation tile links to Audiobookshelf (line 122), BookStack is still listed and monitored
although retired (line 236), "Homepage: This dashboard" links to itself, and there is no tile for
OliveTin, Authentik admin, Home Assistant, the portal or imax-verify. "Automation" holds ten tiles
mixing request front ends, acquisition, the arr stack and downloaders. Request Comics uses its
public hostname while every other tile uses a LAN address.

**A5. Kindle breaks the 404-not-403 doctrine.** A user without `avrana-books` gets a 403 with the
full Amazon instructions (`kindle.py:228`, `276`, `288`), where the portal would return a plain 404.

## 3. Technical audit (Impeccable scoring)

| # | Dimension | Score | Key finding |
|---|---|---|---|
| 1 | Accessibility | 2 | Control borders at 2.3:1; missing focus states on two element types; meta refresh |
| 2 | Performance | 4 | Inline CSS, no JS, no web fonts, lazy cover images. Nothing to fix |
| 3 | Theming | 2 | Tokens exist but are triplicated and drifting; Authentik CSS hard-codes hex |
| 4 | Responsive | 3 | No overflow at 390px; footer links and store links are 19 to 21px tall |
| 5 | Implementation integrity | 3 | A coherent, product-specific identity with copy drift between services |
| | **Total** | **14/20** | **Good: address accessibility and theming** |

**Integrity verdict: pass.** The surfaces express one deliberate identity (black, serif, tracked
wordmark, square rules, inversion on hover) that is nothing like a generic SaaS dashboard. The
work is to codify and repair it, not to replace it.

### P1 (WCAG AA failures)

- **Interactive borders fail non-text contrast.** `--line` is `rgba(255,255,255,0.28)`, which
  composites to #474747 on black: 2.3:1, under the 3:1 of WCAG 1.4.11. It is the only edge of every
  portal tile (`portal.py:374`), the Kindle field, Audible fields and every ghost button.
  Fix: a separate Control Rule token (#6e6e6e, 4.1:1) for interactive edges; keep #474747 for dividers.
- **Kindle "Remove" has no focus state.** `button.ghost` is declared after `button:focus-visible`
  at equal specificity (`kindle.py:151-153`), so a focused ghost button looks exactly like a resting
  one. WCAG 2.4.7.
- **Portal text links have a near-invisible focus state.** `a.account` and `a.store` set
  `outline:none` and only brighten the underline from 60% to 100% white (`portal.py:386`, `405`).
  WCAG 2.4.7. Fix: the shared two-ring focus indicator.
- **The import progress page reloads itself every 10 seconds.** `<meta http-equiv="refresh">`
  (`progress.html:12`) resets scroll and focus and interrupts screen readers mid-sentence, with no
  way to pause. WCAG 2.2.1. Fix: poll a small JSON endpoint and update the rows inside an
  `aria-live="polite"` region, or a manual "Refresh" button.
- **Status messages are not announced.** Kindle `.banner` and Audible `.alert` carry no
  `role="status"` or `role="alert"`, so the result of a save is silent to a screen reader. WCAG 4.1.3.
- **Help pages skip a heading level and never name their topic.** The page `<h1>` is the wordmark
  and platforms are `<h3>` with no `<h2>` (`portal.py:625`). A member who arrives from a link cannot
  tell which help page this is. WCAG 1.3.1, 2.4.6.

### P2

- **Help pages are long and linear.** Movies and TV has ten platforms; on a phone the Roku
  instructions are four screens down (screenshot `portal-help-movies-phone`). Add a row of
  platform jump links under a topic headline.
- **Native controls render light.** No page declares `color-scheme: dark`, so checkboxes, select
  menus and scrollbars draw in light mode (the white checkbox on the Audible library).
- **Small touch targets.** Footer links ("Back", "Account & sign-in") and store links measure 19 to
  21px tall at 390px. They pass the WCAG 2.5.8 spacing exception but are hard to hit on a phone;
  pad them to 44px. The Audible library checkbox is a 22px target in a row that is not a label.
- **Audible library on a phone.** Three full-width buttons stack before the first book, "Re-scan"
  sits in its own form above the action bar, and "Continue with selected" is not repeated after a
  long list.
- **Authentik maps monospace to Times** (`avrana-landing.yaml:34`). Recovery codes, TOTP secrets and
  tokens then render in a proportional serif where 0/O and 1/l are ambiguous.
- **Kindle 403 page** (A5) and **Homepage drift** (A4).

### P3

- Em dashes in member-visible copy, against house style: the account page note
  (`portal.py:575`, "settings — playback, reading position, notifications —").
- The font stack has no metric-compatible fallback (Liberation Serif, Tinos) and nothing for
  Android, which has no Times New Roman.
- Help store links are block-level, so their underline runs the full column width and reads as a
  divider.
- Kindle: two levels of uppercase tracked labels stack ("YOUR KINDLE ADDRESS" over "CALIBRE-WEB"),
  and on a phone the address pairs collapse with no space between them.

### What works and should be kept

- A distinct identity that survives the trip through Authentik's brand CSS.
- Role-aware rendering with the 404-not-403 rule and the no-leak copy rule (`docs/services/avrana-portal.md`).
- Inversion on hover is a strong, cheap state signal; tiles already have a correct two-ring focus.
- Plain, specific copy written for non-technical members, with every store link verified.
- Zero JavaScript on the portal and Kindle, inline CSS, no web fonts: instant on any connection.
- The Audible flow's honesty: what is stored, what is not, and how to disconnect.

## 4. Proposed design system

See [`docs/design/DESIGN.md`](../design/DESIGN.md). In short: **"The Title Card"**. Keep the black
ground, white Times, tracked wordmark, square 1px rules and inversion. Add what is missing: a
Control Rule colour for interactive edges, one focus ring, two wordmark sizes, a type scale and a
4px spacing scale, a monospace reserved for copyable strings, `color-scheme: dark`, banner roles,
and a universal footer. No accent colour, no shadows, no icons.

## 5. Incremental implementation plan

Each phase is one PR per service, verified offline (`python3 tests/run_offline.py` plus fixture
renders at 1280px and 390px), and deployed by the owner one service at a time per
`docs/DEPLOYMENT.md`. Authentication paths, routes, group gating, CSRF, redirects and copy meaning
do not change in any phase unless stated. Rollback for every custom service is the previous image.

| Phase | Scope | Touches production? | Risk |
|---|---|---|---|
| 0 | This audit and `DESIGN.md`. Optionally commit the fixture render harness under `tests/` | No | None |
| 1 | Accessibility fixes only, no visual redesign: Control Rule borders, focus ring everywhere, banner roles, `color-scheme: dark`, footer link padding, em dashes. Portal, Kindle, Audible as three PRs | Rebuild of three custom containers | Low: CSS and attributes only |
| 2 | Shared stylesheet: `deploy/design/avrana.css` as the single source, a sync script that copies it into each service's build context, an offline test that fails on drift. Portal and Kindle read the file instead of an inline string; Audible serves it as its static CSS. Wordmark converges on the two sizes | Rebuild of three containers | Low: visual change limited to wordmark size and Kindle width |
| 3 | Navigation and content structure: help topic headline, platform jump links, inline store links, mono server addresses; Audible header replaced by the shared wordmark header with a link home; Audible progress page polls instead of reloading; Audible library action bar; Kindle returns 404 to non-members | Rebuild of three containers | Medium: the progress change adds a small JSON route and some JavaScript, which needs its own test |
| 4 | Configurable surfaces: regenerate Authentik brand CSS from the tokens and fix its monospace mapping (blueprint change, back up the brand record first as on 2026-08-21); Homepage regrouped by pipeline (Video, Books and audio, Comics, Host), BookStack and the self tile removed, Libation link corrected, operator links added, optional house-style `custom.css` | Authentik blueprint apply; Homepage reload | Medium for Authentik (it is the sign-in path: test the login, enrollment and recovery flows in a private window before and after) |
| 5 | Owner decisions, not scheduled: one front door (Authentik post-login landing to `avrana.net`); Jellyfin login branding through its dashboard; OliveTin theming | Yes | Decide individually |

Phase 1 is independent of the rest and gives the biggest accessibility gain for the least change,
so it is the recommended start.
