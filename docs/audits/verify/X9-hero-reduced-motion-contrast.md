# X9: hero under Reduce Motion and Increase Contrast (U-01, U-02)

Independent verification of `fix/rc2-hero-reduced-motion-contrast` @ `1ef239e` against baseline `2cb228f`.
Verifier did not write the fix; no files in either tree were edited. Date 2026-10-29.

## Verdict: REJECT (as committed). Behaviour ACCEPTED; one mechanical fix needed before merge

The CSS change is correct and does what it claims. The commit is not mergeable as is, because it changes
`home.css` from CRLF to LF line endings. That rewrites all 1,226 lines, and it conflicts with another RC2 branch.

- `git diff 2cb228f..1ef239e --stat` shows `home.css | 2455 +++---` (1244+/1226-) for a 5-line change.
  `git diff --ignore-cr-at-eol` shows the real change: 3 lines added, 2 changed.
- Baseline blob: `i/crlf`, 1,226 CRs. Fix blob: `i/lf`, 0 CRs. The repo has no `.gitattributes`, and `core.autocrlf=false`.
  Other templates (`_sections.html`, `continue.html`, ...) are still CRLF.
- `git merge-tree fix/rc2-hero-reduced-motion-contrast fix/rc2-rail-focus-a11y1` reports
  **CONFLICT (content) in home.css**. The rail-focus branch keeps CRLF (1,236 CRs) and adds one hunk at line 504.
  The U-01 hunks are at lines 470-486. With CRLF kept, the hunks are 18 lines apart, so the merge would be clean.
  The conflict comes only from the line-ending churn. The whole-file diff also hides the real change from PR
  review and wipes `git blame` for the file.

**Required:** recommit the same edit with CRLF kept in `home.css`. One way: re-apply the 5-line edit on a CRLF
checkout, or run `unix2dos` on the file and amend. Then confirm `git diff --stat 2cb228f` shows about 5 lines in home.css.
Nothing else needs to change. Once that diff is right, the behavioural results below still hold.

## 1. Diff review (CR-insensitive)

- CSS only in the two named places. (a) Line 475, after the `@supports (animation-timeline:view())` block:
  `@media (prefers-reduced-motion:reduce){.hero-mini,.hero-play{display:none;}}`.
  (b) `top:auto` added to `.hero-stick` in both the `prefers-contrast:more` override (479) and the
  `forced-colors:active` override (483). The test file adds one source-level test. Nothing else changed.
- **Cascade:** `@supports` and `@media` add no specificity. Both selectors are the same (`.hero-mini,.hero-play`, 0-1-0).
  The new rule comes later in the source, so it wins in every engine that applies both rules.
- **Engines without scroll timelines** (Firefox by default; any Safari that fails `animation-timeline:view()`):
  the `@supports` block never applies. The base rule `.hero-mini,.hero-play{display:none;}` (line 438) hides the strip.
  `.hero-stick` stays `position:relative`, so the hero just scrolls away. Reduce Motion makes no visible difference
  there, and the new rule is redundant but harmless. This default path was already correct, and the fix leaves it untouched.
- **Engines that pass the `@supports` test** (Chromium; Safari 26 if it does): this is the path the fix changes. See 2 below.

## 2. Behaviour (Chromium, Playwright 390x844 and 1280x800, dev stacks on 8996 (fix) and 9096 (baseline))

Implementer's `u01.mjs` re-run (copy at `scratchpad/verify-x9/u01.mjs`): **fix 40/40 PASS, baseline 0/40**.
Baseline fails as reported. At rest with Reduce Motion, `mini:true, play:true, plates=2`.
Contrast and forced colours: card bottom below the heading top. The script's visibility test is meaningful:
it checks computed display, visibility, opacity and box width. But the heading check only compares the card's box
bottom with the heading's top, and it only checks the rest state. Default mode makes no assertions; it only takes screenshots.

Own checks (`scratchpad/verify-x9/x9.mjs`):

| Check | Baseline | Fix |
|---|---|---|
| Reduce Motion, rest: strip and play button | shown over the hero | hidden; one title, one Resume |
| Reduce Motion, scrolled 600 px: hero box (390) | 452 px tall, bottom 646 -> 46 | same: 452 px, bottom 646 -> 46 |
| Reduce Motion, scrolled 600 px: hero box (1280) | 488 px, bottom 671 -> 71 | same |
| Reduce Motion, scrolled: hero pinned? content under it? | no; scrolls away | no; scrolls away (heading at y=74/99 unobstructed) |
| Contrast/forced, rest: elementFromPoint at 9 points on "Continue" | hero-card / hero-foot hit at every point | heading at every point |
| Contrast/forced, Tab to `.hero-go`: focus ring | visible | visible: forced = 2px solid system colour (rgb(26,235,255) dark, rgb(55,0,110) light); contrast = two-ring box-shadow; in view |
| Contrast/forced, focused: heading clear | covered | clear |

Full-height sticky hero under Reduce Motion: no pinning problem. `.hero` and `.hero-stick` have the same height
(`art-h + band`), and only the disabled `hero-shrink` animation would give the sticky box room to move. So the hero
scrolls off exactly like a static block, on both baseline and fix. The fix does not change this.

Note: at 1280 after a 300 px scroll, contrast/forced on the fix flags 3 points at the top of the heading. The element
there is the sticky masthead (`header > .mast > h1 > a > img.lockup`), not the hero (hero bottom 17, heading top 45).
The page scrolled under the header as designed, so this is a false positive in the probe. On baseline at the same
scroll the hero box still overlaps the heading (hero bottom 75 > heading top 45).

## 3. Default-mode regression (pixel diff, in-browser canvas compare; `scratchpad/verify-x9/px.mjs`)

Two baseline captures were compared with each other to measure noise (late image loads). For each of 390x844 and
1280x800, dark and light, viewport and full page, at least one baseline-vs-fix pair differs by **0 px**. The one
exception is full-page dark 390, which differs by **1 px**; there, two baseline captures differ from each other by 63,299 px.
Wherever the first baseline capture differs from the fix, it differs from the second baseline capture by the same
amount (31 px, 15,823 px), so those differences are noise, not the fix. Verdict: default rendering unchanged.
With no scroll and no media overrides, the fix applies no new rules, as the cascade reasoning predicts.

## 4. Tests (fix worktree)

- `webtests.test_web_home_hero test_web_motion_k test_web_shell_k test_web_home test_web_pages_k`: **104 OK**.
- `tests.test_home_static_export tests.test_ui_harness`: **32 OK**.
- "Continue" appears 0 times in `home.css`. The existing pin (test_web_home_hero.py:199) passes.
- The new test, run with `TEMPLATES` pointed at the baseline tree, **fails** (reduced-motion rule not found). On the fix it passes.
  It is a source-level string pin only, as its docstring says. The behavioural proof lives in scratch scripts,
  not in CI. That is acceptable for RC2 but worth an AVR follow-up: a Playwright webtest for the three media modes.

Both dev stacks were stopped after the run; all ten ports are free.

## Re-check of dda4844 (CRLF restored)

- `git diff --stat 2cb228f dda4844`: home.css 5+/2-, test_web_home_hero.py +15. Nothing else changed.
- home.css at dda4844: `file` reports "with CRLF line terminators". It has 1,229 CRs over 1,229 lines, and `git ls-files --eol` shows `i/crlf w/crlf`.
- The CSS is byte-identical to the 1ef239e version I verified once CRs are stripped (`cmp` clean). `git diff 1ef239e dda4844 --ignore-cr-at-eol` is empty, so the test file is unchanged too.
- `git merge-tree --write-tree --quiet dda4844 fix/rc2-rail-focus-a11y1` exits 0: no conflict.
- `webtests.test_web_home_hero`: 29 OK.

**Final verdict: ACCEPT.** dda4844 keeps the CRLF line endings, so the only blocker is gone. The CSS content is byte-identical to the version verified above, so the behavioural, pixel and test results in sections 1-4 still apply.
