# X13: independent verification of U-05, U-06 and U-08 (phone layout)

- Fix under review: branch `fix/rc2-phone-layout`, commit `57bbf0b` on `2cb228f` (worktree `avrana.wt-rc2-u05`, not modified)
- Baseline: `avrana` at `2cb228f` (read-only)
- Verifier: independent agent, 2026-10-30. Synthetic data, loopback only (baseline stack 8996/18996-18999, fix stack
  9096/19096-19099, both stopped afterwards). No commit, no ssh, no Docker, no real services.
- Scripts (scratchpad `verify-x13\`): `x13.mjs` (all measurements), `x13-nobanner.mjs` (U-06 with the dev identity
  banner removed), `x13-glass.mjs` (U-08 overflow screenshots), `pxdiff.mjs` + `pxshots.mjs` (pixel diff),
  `zoom.mjs`. Raw results `out\base.json`, `out\fix.json`, screenshots in `out\`.
  Full path: `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x13\`
- Method: Chromium (Playwright from `.ui-tooling`), member-b, dark, service workers blocked, touch + mobile below 768 px
  wide or 500 px tall. **200 % text = the harness's method** (`check_home_export.mjs:69`): `addStyleTag`
  `html{font-size:200%}` after load. Overlap = `.hero-facts` bottom minus `.hero-ctl` top (positive = overlap).
- **Verdict: ACCEPT-with-notes**

## 1. Diff and merge

- `git diff 2cb228f..57bbf0b --stat`: 2 files, 26 insertions, 0 deletions: `home.css` +11, `test_web_home_hero.py` +15.
- CRLF intact: every added `home.css` line ends `^M$` (checked with `cat -A`); no line-ending churn elsewhere.
- No change to `home.js`, templates, axe assertions, `baseline.json` or any existing test expectation. The two CSS
  inserts are new rules placed after the `@media (min-width:45rem)` hero rule (line 451) and after
  `.places.filters::-webkit-scrollbar` (line 1048). Nothing inside the hero `@keyframes`, reduced-motion,
  `prefers-contrast` or forced-colors blocks, nor any `.rail` rule, is edited.
- `git merge-tree --write-tree --quiet 57bbf0b fix/rc2-hero-reduced-motion-contrast` (dda4844): exit 0, clean.
- `git merge-tree --write-tree --quiet 57bbf0b fix/rc2-rail-focus-a11y1` (1d1d6e4): exit 0, clean.

## 2. Measurements (baseline -> fix)

### U-05 hero facts vs controls (px, positive = overlap)

| View | Baseline | Fix | Note |
|---|---|---|---|
| 320x568 @100 % | **7** | **-19** | fixed |
| 320x640 @200 % | **40** | **-18** | fixed |
| 195x422 (reflow) | **33** | **-9** | fixed |
| 360x780 @100 % | -14 | -14 | unchanged |
| 360x780 @200 % | **12** | **12** | **not fixed, pre-existing** (see notes) |
| 390x844 @100 % | -14 | -14 | unchanged |
| 390x844 @200 % | -16 | -16 | unchanged |
| 320x568 reduced motion | 7 | -19 | fixed; hero renders |
| 320x568 Increase Contrast (`contrast:'more'`) | 7 | -19 | fixed; controls inside the card |
| 320x640 @200 % + Increase Contrast | 40 | -18 | fixed |

In every view the controls stay inside `.hero-card`, the time row does not collide with Resume, and the document
does not scroll sideways. At 320x568 Resume is below the fold on both trees (unchanged; the hero is the same height).

### U-06 phone landscape

With the dev identity banner (36 px) as served by the dev stack:

| View | `.hero` height | Title in viewport | Resume in viewport | Tab bar intersects Resume |
|---|---|---|---|---|
| 844x390 | 488 -> **214** | no -> yes (but under the tab bar) | no -> yes | - -> **yes** |
| 667x375 | 452 -> **199** | no -> yes (under the tab bar) | no -> yes | - -> **yes** |
| 740x360 | 488 -> 192 | no -> yes | no -> **no** (bottom 367 > 360) | - -> yes |
| 844x390 reduced motion | 488 -> 214 | as 844x390 | as 844x390 | yes |
| 390x844, 1280x800 | unchanged (452, 488) | yes | yes | no |

Production-equivalent (banner removed, `x13-nobanner.mjs`):

| View | Title (top-bottom) | Resume (top-bottom) | Tab bar (top-bottom) | Title clear | Hit test at Resume centre |
|---|---|---|---|---|---|
| 844x390 | 250-283 | 321-353 | 302-366 | yes | tab bar |
| 667x375 | 227-260 | 298-330 | 287-351 | yes | tab bar |
| 740x360 | 228-261 | 299-331 | 272-336 | yes | tab bar |

So in production the title and the facts are on the first screen and clear of the tab bar; Resume is on the first
screen but entirely behind the floating tab bar (a tap lands on the bar). On baseline Resume and the title were 200+
px below the fold. The `9rem` floor is what holds at 360 px tall.

### U-08 `.places.filters`

| View | scrollWidth / clientWidth | scrollLeft after 400 px wheel | after 400 px touch drag | words visible after |
|---|---|---|---|---|
| 320 | 1,164 / 320 -> **320 / 320** | 400 -> **0** | 395 -> **0** | 0/4 -> 4/4 |
| 390 | 1,234 / 390 -> **390 / 390** | 400 -> **0** | 394 -> **0** | 0/4 -> 4/4 |
| 390 @200 % (genuine overflow) | 1,234 / 390 -> **581 / 390** | 400 -> 191 (the row's real end) | 395 -> 191 | 2/4 -> 3/4 |

Vertical overflow also drops (scrollHeight 54 -> 45 against clientHeight 44; the remaining 1 px is pre-existing
child geometry, not the ceiling).

Overflow-case look (`out\fix-glass-200-rowend.png`, `out\fix-glass-150-rowend.png`, page scrolled 650 px, chrome
untucked, row scrolled to its end): the glass ceiling now scrolls with the row, so the right 191 px (200 %) or 45 px
(150 %) of the row has no glass. A vertical seam is visible, and page content passing behind shows through unblurred
in that strip; in one capture a rail card's placeholder "S" sat right behind the "n" of "Listen". At rest (row at
scrollLeft 0) the look is identical to baseline. On baseline the same gesture leaves the row blank (the words at
x = -360), which is worse. While scrolling down (`data-chrome="tucked"`) the row is hidden anyway, so the seam shows
only when a large-text member scrolls back up and then swipes the filter row.

### Pixel diff baseline vs fix (dark, member-b)

| View | Rest | Scrolled 600 px |
|---|---|---|
| 390x844 | 0 px (second run 15 px, max delta 9, a 7 px tall strip: anti-aliasing) | 32k px, see below |
| 430x932 | 0 | 0 |
| 1280x800 | 0 | 0 (second run 12 px, max delta 17, one text row: anti-aliasing) |

The 390x844 scrolled difference is entirely the "Synthetic Fresh Release" card: its mock artwork loads in one capture
and falls back to the placeholder letter in the other. Which tree gets the placeholder flips between runs (run 1: the
baseline had the letter; run 2: the fix had it), so it is an image-load race in the mock, not the CSS. Layout is
otherwise identical (`out\sbs-390-s600.png`).

## 3. Reduced motion and Increase Contrast

Covered in the tables above: reduced motion at 320x568 (-19 px, hero renders, 379.5 px tall as without it) and 844x390
(as without it); Increase Contrast at 320x568 (-19 px) and 320x640 @200 % (-18 px). No new overlap.

## 4. Tests

Fix worktree, one module at a time, `.venv-media` Python:

| Module | Result |
|---|---|
| test_web_home_hero | 29 tests OK (includes the new pin) |
| test_web_pilot | 28 OK |
| test_web_pwa | 33 OK |
| test_web_home | 21 OK |
| test_web_shell_k | 12 OK |
| `tests.test_home_static_export tests.test_ui_harness` (worktree root) | 32 OK |

`check_home_export.mjs` (static export from each tree, 181 pages each, served on 8996 / 9096):

| Tree | Page views | Rail focus views | Findings | Exit |
|---|---|---|---|---|
| Baseline 2cb228f | 1,098 (183 pages x 3 sizes x light/dark) | 63 | 16 | 1 |
| Fix 57bbf0b | 1,098 | 63 | 16 | 1 |

All 16 findings are `FAIL focus 390@200% ...: focused card not fully visible` (U-03, the rail-focus branch). The
sorted `FAIL` lines of the two runs are byte-identical (`diff` empty), so the fix adds nothing. Logs:
`verify-x13\check-base.log`, `verify-x13\check-fix.log`.

## 5. Judgement

- **U-06 residual (Resume under the tab bar in landscape): acceptable, P2 -> P3, does not block.** The defect as
  audited (title, Resume and rails all below the fold, hero taller than the screen) is fixed: the hero is 192-214 px
  and the title is on the first screen and clear of the tab bar in production. Resume being behind the floating bar is
  the same class as the existing 360@200 % / 390@200 % case (tab bar covers Resume there too, on baseline). The whole
  hero card is still a link and a short scroll uncovers Resume. Track it as a follow-up (for example, shrink or hide
  the tab bar under `max-height:30rem`, or add bottom padding to the hero foot equal to the bar height there).
- **U-08 overflow limitation: a visible but minor cosmetic regression, not blocking.** A member at 150-200 % text who
  scrolls up and swipes the filter row to its end can notice the glass stopping part-way and content passing behind
  unblurred. It is strictly better than baseline, where the same swipe blanks the row. Suggested follow-up: put the
  glass on the scroller's own background (`background` + `backdrop-filter` on `.places.filters` when
  `html[data-scrolled]`), which does not scroll with the content, or draw the ceiling outside the scroller as the
  audit proposed.

## Notes (non-blocking)

1. **U-05 is not fixed at 360 px with 200 % text: 12 px overlap on both trees.** The fix keys on `max-width:359px`
   only; the audit's suggested large-text arm (a container query in `em`) was not implemented. 360@200 % was not in the
   audit's measured list, so this is a gap in scope, not a regression. The implementer's claim "360@100 % unchanged" is
   correct; 360@200 % was not claimed.
2. **740x360 landscape** (common Android size): Resume bottom 367 px in a 360 px viewport with the dev banner; in
   production it is on screen but behind the tab bar like the others.
3. Implementer's numbers reproduce exactly: 7 -> -19, 40 -> -18, 33 -> -9; 488 -> 214, 452 -> 199; scrollWidth 1,234 ->
   390; scrollLeft 394 -> 0.
