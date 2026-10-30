# Media 2.0 pre-closed-beta sprint: UX/UI quality report

Status: **written 2026-10-30 from the read-only UX audit of `2cb228f`
([2026-10-29-rc2-ux-audit.md](../audits/2026-10-29-rc2-ux-audit.md)) and the independently verified fixes in
[MEDIA-2.0-RC2-FIX-LEDGER.md](MEDIA-2.0-RC2-FIX-LEDGER.md).** Everything here was measured on a loopback dev stack with
synthetic members and fixtures (Chromium, Playwright, axe-core), and on the static export CI uses. Nothing was
measured on a phone, in Safari, with VoiceOver or on the installed PWA: those remain the owner's physical checks
(acceptance packet, section F). Screenshots live in the session scratchpad; the repo tracks no binaries.

Concept K, Plus Jakarta Sans, Butter-High `#EADA6E` and the Round 10 framed hero are unchanged by every fix below.
No fix changed an axe assertion, a snapshot or `baseline.json`.

## 1. Verdict

The shell is coherent and, in the default mode, clean: **0 serious or critical axe findings across 1,675 views**
(static export, nine widths, light and dark, degraded modes, 200 % text, 195 px reflow), no sideways page scroll at
any of the nine widths in the normal state, CLS 0, focus ring visible on every stop, a title sheet that returns focus
to its opener. The defects were in the **non-default modes** (Reduce Motion, Increase Contrast, forced colours, 200 %
text) and in degraded library states. Those are exactly the modes a member with an accessibility need turns on, so
they were treated as beta-relevant rather than cosmetic. Two were adjudicated beta-blocking (U-01, U-02); both are
fixed and verified on draft branches. The RC1 A11Y-1 focus defect (U-03) is fixed in CSS alone, verification running.

| Class | Found | Fixed + verified (draft PR) | Owner decision | Deferred (P3) |
|---|---|---|---|---|
| Beta-blocking (non-default modes) | 2 (U-01, U-02) | 2 → [#178](https://github.com/rcnechamkin/avrana/pull/178) | — | — |
| Accessibility on the phone journey | 2 (U-03, U-07) | U-07 → [#176](https://github.com/rcnechamkin/avrana/pull/176); U-03 → [#181](https://github.com/rcnechamkin/avrana/pull/181) | — | U-04 |
| Degraded-state display | 2 (D-01, D-02) | 2 → #176 | — | — |
| Phone layout at 320 px / large text / landscape | 4 (U-05, U-06, U-08, U-10) | 3 → [#180](https://github.com/rcnechamkin/avrana/pull/180) (U-06 partial) | — | U-09, U-10, U-23 |
| Design questions | 4 (U-12..U-15) | — | 4 | — |
| Copy, seams, pages | 7 (U-11, U-16..U-21) | 0 | — | 7 |
| Stale design doc | 1 (U-22) | → [#175](https://github.com/rcnechamkin/avrana/pull/175) | — | — |

## 2. Screen by screen

Evidence tags: [measured] = numbers from the audit scripts; [verified] = independent verifier reproduced defect and fix.

### Home (`/`, `/?for=watch|listen|read`)

| Finding | Severity | Before | After | State |
|---|---|---|---|---|
| U-01 Reduce Motion: the compact strip and play button render on top of the resting hero (the global reduced-motion rule removes the scroll animation that kept them at opacity 0) | P1 | strip overlaps hero at every width [measured, 0/40 checks pass] | `.hero-mini,.hero-play{display:none}` under `prefers-reduced-motion` ; 40/40; default-mode pixel diff 0 px [verified] | #178 |
| U-02 Increase Contrast / forced colours: `.hero-stick` goes `position:relative` but keeps `top`, pushing the hero card over the "Continue" heading | P1 | 9 of 9 sample points on the heading hit the hero card [verified] | `top:auto` in both overrides; 9 of 9 hit the heading; focus ring on Resume visible in both modes [verified] | #178 |
| U-03 = RC1 A11Y-1: at 200 % text a focused rail card is not wholly in view (also 9 clipped stops at 320 px / 100 %) | P2 | clipped stops 360/390/430 @ 200 %: 76 / 76 / 78; 320 @ 100 %: 9 [verified] | CSS-only one-card scroll-padding region + end margin on wider cards: 0 at every size; snap unchanged; `home.js` untouched, DESIGN.md "No script" rule holds | #181 |
| U-07 duplicate `id="h-new"` on Listen: New Releases announced as "New to Avrana"; `landmark-unique` on 11 views | P2 | duplicate ids on `/?for=listen` and `/?more=released&for=listen` [verified] | New Releases row keyed `released`; unique-id sweep over 8 routes [verified] | #176 |
| D-01 / D-02 bare "Continue" / "New to Avrana" heading beside an outage banner | P2 | heading over nothing in 2 of 294 degraded requests [verified] | heading only with cards or a line; empty Continue with nothing down keeps "Nothing in progress." [verified] | #176 |
| U-04 focused card partly under the tab bar or sticky header | P3 | — | — | deferred; `scroll-padding-bottom` exists, the sticky header case needs a measured top padding |
| U-05 hero facts and controls overlap at 320 px and large text | P2 | 7 / 40 / 33 px at 320, 320 @ 200 %, 195 reflow [verified] | −19 / −18 / −9 px; 360+ unchanged [verified]; 12 px at 360 @ 200 % remains (main too) | #180 |
| U-06 landscape 844×390: hero taller than the screen | P2 → P3 residual | hero 488 / 452 px in a 390 / 375 px viewport, Resume 200 px below the fold [verified] | 214 / 199 px, title on the first screen; Resume on screen but behind the tab bar (header + bar leave ~119 px) [verified] | #180; follow-up: shrink/hide the bar under `max-height:30rem` |
| U-08 header filter row swipes into empty space | P2 | scrollWidth 1,234 vs 390; blank row after a 400 px swipe [verified] | 390 vs 390; swipe stays at 0 [verified]; at 200 % text the glass now scrolls with an overflowing row (main blanked it) | #180 |
| U-16 hero repeats the first Continue card | P3 (DESIGN, F-14) | — | — | owner |

### Library (`/library`, `?lib=`)

| Finding | Severity | State |
|---|---|---|
| U-09 ledger chips hidden off screen at narrow widths | P3 / design question 6 | owner: wrap vs scroll-into-view |
| U-10 header pushes the page 8 px sideways at 320 px with 200 % text (layout button + chips; confirmed again during X10 on main) | P3 | AVR-786 |
| U-23 "All" filter target 18 px wide | P3 | deferred |
| Layout button, chips, grids, native art shapes | clean [measured] | — |

### Search (`/search`)

All specified states clean [measured]: empty, results grouped per library with row-wide links, no results with
"Ask for it" rows, invalid query, one library unavailable (warning inside the page), none answering ("Not searched").
Functional: F-03 slow Seerr searches no longer trip the shared breaker ([#168](https://github.com/rcnechamkin/avrana/pull/168), verified).

### Title and sheet (`/title/*`)

Clean [measured]: Cream action, "Opens in" panel, About; focus to Close on open and back to the opener on Escape,
close button and browser Back. F-01 (Komga e-book called "Books" for a member without Books) fixed and verified
([#174](https://github.com/rcnechamkin/avrana/pull/174)). Owner question carried: Q1/F-9 action wording naming the app.

### Requests (`/request/*`, My requests)

Not rendered in the audit (brokers off on the dev stack; on live). Journey pins added at the HTTP level
([#173](https://github.com/rcnechamkin/avrana/pull/173): double-submit idempotency, Quick Connect outcomes). The
"may have gone through" timeout copy is owner question D-05. U-15 (where Request and Help live for a member whose
places row became filters) is design question 4.

### Me, Account, Help, TV sign-in, offline, errors

Grouped rows and panels consistent [measured]. U-11 TV page wording and field style, U-17 404/error pages rendered
as the Title Card (AVR-362), U-18 outage notice and Try again apart, U-19 copy list, U-21 focus after browser Back:
all P3, deferred with the inventory. Offline page and update banner were not exercised in a real offline state (g).

## 3. Accessibility summary

| Check | Result |
|---|---|
| axe-core, 1,675 views (export + live modes + 200 % + reflow) | 0 serious / critical; the only moderate finding (`landmark-unique`, U-07) is fixed in #176 |
| Focus visibility | yellow two-ring mark 13.1:1 against ink on every stop of Home's first 22 Tabs; none covered at rest |
| Keyboard | skip link first Tab; sheet traps and returns focus; Escape/back restore the opener |
| 200 % text | sideways scroll only on `/library*` at 320 px (U-10); rail focus fixed in #181 |
| Reduce Motion | hero strip defect fixed (#178); bottom nav switches state instantly as designed |
| Increase Contrast / forced colours | hero overlap fixed (#178); screenshots only, axe does not model these modes |
| Reflow 195×422 | 2 px sideways on `/me/tv` only (U-11) |
| Not tested | Safari / iOS WebKit, VoiceOver, TalkBack, real Dynamic Type, installed PWA, TVs → acceptance packet F1–F6 |

## 4. Performance (loopback floor, synthetic data, 390×844)

Home warm: TTFB 35 ms, FCP 208 ms, LCP 270 ms (art), CLS 0, 136 KB HTML, 236 KB / 24 requests. Slow-4G profile:
FCP 1.0–1.7 s, LCP 1.2–2.2 s. Cold cache first view 2.2 s to load. A `slow` upstream is capped at 2.5 s by the
page cap (F-03 moves Seerr search to its own 8 s timeout so it no longer counts against that cap's breaker). Real
TLS, upstreams and the phone radio add to all of these; the acceptance packet's S2 threshold is 3 s to a usable Home
on phone Wi-Fi.

## 5. Design questions for the owner (unchanged from the audit)

1. **U-12** MK-8 chrome (520–560 ms) and sheet (380/300 ms) timings as approved exceptions to the 200 ms tier?
2. **U-13** Hero progress line: yellow (Round 10) or Cream (the Yellow Rule)?
3. **U-14** "Watch · Listen · Read" header filters vs library names elsewhere; keep both submenus?
4. **U-15** Where do Request and Help live for members whose places row became filters?
5. **U-09** Ledger chips: wrap at narrow widths, or scroll the chosen chip into view?
6. **U-03** The question "accept a focus handler in `home.js`?" is **withdrawn**: the CSS-only fix holds at 100 % and
   200 % (#181, verified ACCEPT with notes). DESIGN.md's Rail Focus Rule carries a note for acknowledgement, not a rule change.
7. Carried: Q1/F-9 title action wording, F-14 (U-16), AVR-362 (U-17), D-05 request timeout copy.

## 6. What this report cannot say

Whether any of it holds on an iPhone. Every number above is Chromium on Windows against synthetic data. The
acceptance packet's F1–F6 and the two-member isolation test are the only evidence that counts for the release rule.
