# Member interfaces against the Design Foundation, 2026-10-11

A second pass over the custom member interfaces (portal, Kindle connector, Audible connector),
this time against the shared [Design Foundation](../design/foundation/README.md) and its
[Media mapping](../design/FOUNDATION-MAPPING.md). It builds on the same day's
[web interface audit](2026-10-11-web-interface-audit.md) and does not repeat it: findings already
there are sorted into the foundation's four classes and tied to their Linear issue, and only what
that audit did not cover is described in full.

**Method and limits.** Evidence is the code in Git at `eee6b79`. `git diff 9d8799d eee6b79 --
services deploy scripts` is empty, so every line reference in the first audit still holds. The
stylesheets were read in full (`services/avrana-portal/portal.py:359-409`,
`services/avrana-kindle-connector/kindle.py:131-160`,
`services/avrana-audible-connector/connector/app/static/style.css`) with the Audible templates.
Contrast figures were computed with the WCAG 2 formula. Nothing was rendered in a browser in this
pass, the live host was not reached, and nothing was changed, restarted or deployed. Authentik,
Homepage and the upstream applications were not re-examined.

## What already meets the foundation (keep unchanged)

| Kept | Evidence |
|---|---|
| One deliberate identity with no accent, no shadows, no icons | all three stylesheets share `--bg`, `--fg`, `--dim` and the serif stack |
| Text contrast | Paper 21:1, Ash 7.5:1, Ok and Warn 13.7:1, Err 9.3:1 on Ink; hovered tile description `#333333` on white 12.6:1 |
| Selection by inversion, with the two-ring focus on tiles | `portal.py:379-381` |
| Nothing moves | only colour transitions of 160ms; no animation, so reduced motion needs no override |
| Zoom is never disabled; sizes are relative on the portal and Kindle pages | no `user-scalable` or `maximum-scale` anywhere |
| No JavaScript on the portal and Kindle; no web fonts | first audit, "What works" |
| The 404-not-403 rule and the no-leak copy rule on the portal | `docs/services/avrana-portal.md` |
| One `h1` naming the page on every Audible page | `templates/*.html` |

## 1. Immediate, low risk

All CSS or attribute changes with no change to routes, gating, CSRF or meaning. Each already has
an issue except 1.7 and 1.8, which fit inside one.

| # | Finding | Foundation section | Tracked |
|---|---|---|---|
| 1.1 | Interactive edges drawn in the divider colour (2.3:1) | 2, 5 | AVR-357, AVR-358, AVR-359 |
| 1.2 | Missing or near-invisible focus indicators (Kindle Remove, portal text links, Kindle and Audible fields) | 5, 8 | AVR-357, AVR-358, AVR-359 |
| 1.3 | Status messages without `role="status"` or `role="alert"` | 6 | AVR-358, AVR-359 |
| 1.4 | No `color-scheme: dark`, so native controls draw light | 2 | AVR-357 to AVR-359 |
| 1.5 | Footer and store links 19 to 21px tall | 9 | AVR-357 |
| 1.6 | Help pages skip a heading level and do not name their topic | 3 | AVR-357 |
| 1.7 | **New.** The Audible stylesheet sets the root size in pixels (`font:17px/1.55`, `style.css:11`), so a member's browser text-size setting is ignored there; the portal and Kindle pages use relative sizes | 3 | fold into AVR-359: `1.0625rem` |
| 1.8 | **New.** The Audible progress page's per-row Retry is `ghost small` (`progress.html:29`; `.small{padding:6px 12px;font-size:.85rem}`, `style.css:44`), about 36px tall by its padding and line height, under the 44px target | 9 | fold into AVR-359 |
| 1.9 | Em dashes in member copy; font stack without metric twins or an Android serif | 3 | AVR-357 |

## 2. Needs a focused design review

| # | Finding | Evidence | Question | Tracked |
|---|---|---|---|---|
| 2.1 | The specification has no components for what the Media 2.0 home will show | DESIGN.md defines tile, button, field, banner, badge, list row, text link and help page; MEDIA-2.0 M3.2 to M3.5 need a row of titles with artwork, a Continue item with progress, a search field with results that say where each lives, a title page, and the "unavailable right now" section | design these in DESIGN.md before M3.2 starts, with every state in foundation section 7 (loading, empty, error, degraded) written for each | no issue yet; proposed below |
| 2.2 | Artwork shape | DESIGN.md, Shapes: "Cover art in lists is a square crop"; that fits audiobooks, while films and series are 2:3 posters and comics and books are portrait | one crop for all, or the artwork's own shape per library? | part of 2.1; AVR-382 builds the artwork cache |
| 2.3 | A row of titles on a phone | the foundation allows a list to scroll sideways inside itself, never the page; a horizontal row needs keyboard access and a visible way to reach the rest | sideways rail, or a wrapped grid with "See all"? | part of 2.1 |
| 2.4 | The space scale differs by one step | Media 44px, foundation 48px | recorded in the mapping as a Media value; confirm it stays | none needed |
| 2.5 | The progress page reloads itself every 10 seconds | first audit, P1 | manual Refresh now (AVR-359); in-place polling needs a small script and a live region, to be designed in M3 | AVR-359, then M3 |
| 2.6 | Audible library on a phone: three stacked buttons before the first book, no action after a long list | first audit, P2 | where does the main action sit on a long list? The foundation puts it within thumb reach and repeats it after the list | AVR-359 covers accessibility only |
| 2.7 | Three front doors with different names for the same things | first audit, A1 | one front door is an owner decision (Authentik post-login landing) | AVR-363 |

## 3. Future redesign

| # | Opportunity | Where it belongs |
|---|---|---|
| 3.1 | One canonical stylesheet with a drift test, generated from the token roles | AVR-362; the foundation's `tokens.json` Media theme is the source of names and values |
| 3.2 | Authentik brand CSS regenerated from the same tokens; its monospace mapping fixed | first audit phase 4; an owner-approved blueprint change |
| 3.3 | Help pages with a topic headline and platform jump links | AVR-357 does the heading; jump links with AVR-364 |
| 3.4 | Visual regression baselines for every page and state | AVR-360, then AVR-386 |
| 3.5 | Operator Homepage regrouped | AVR-366 |

## 4. Reject

| # | Idea | Why not |
|---|---|---|
| 4.1 | Adopt Material Web, Material Components Web or any component framework | Media 2.0 is server-rendered Jinja with no build step by owner decision; Material Web is in maintenance mode and Material Components Web is archived |
| 4.2 | Material's colour system, rounded shapes, elevation or icons | the No Accent Rule and the Title Card identity; the first audit's verdict was to codify and repair, not replace |
| 4.3 | Share Party's theme, or one theme across both products | two products, two identities; only names and contracts are shared |
| 4.4 | A dashboard layout for members (cards of counts, status widgets) | members browse films, series, books, comics and audiobooks; status reaches them only as one operator-set sentence (MEDIA-2.0 section 2) |
| 4.5 | Theme upstream applications by proxy injection or patches | DESIGN.md and AGENTS.md; only supported hooks |
| 4.6 | A client-side application for the home page | MEDIA-2.0 section 3: one small server-rendered application |
| 4.7 | A light theme or theme switch | one committed theme, as the stylesheets say |

## Proposed follow-up (one issue)

**Design the Media 2.0 home components and their states in DESIGN.md** (findings 2.1 to 2.3):
title row, Continue item, search and result, title page, unavailable section, empty states; each
with loading, empty, error and degraded written out, at 390px and 1280px, before AVR-381 starts.
Everything else above already has an issue.
