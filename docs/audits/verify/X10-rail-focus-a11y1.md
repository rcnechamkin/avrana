# X10: independent verification of U-03 (RC1 A11Y-1) rail focus fix

- **Verdict: ACCEPT with notes.** Verified against `c76634f`, which is `1d1d6e4` plus a citation fix.
- **Branch:** `fix/rc2-rail-focus-a11y1` in the worktree `avrana.wt-rc2-u03`.
- **Baseline:** `2cb228f` from the main checkout, read only.
- **Verifier:** an independent agent that did not write the fix. Work stopped early at the owner's request (2026-10-30); every item that was not finished is listed under "Not measured" below.
- **Data:** synthetic dev stacks only (`--dev-identity`, member-a and member-b, mock services).
- **Ports:** baseline stack on 8596 and 18596-18599, fix stack on 8696 and 18696-18699. Both stacks have been stopped and none of these ports has a listener.
- **200 % text:** every measurement below injects `html{font-size:200%}` after load, the same method as layer 2 and the harness. This is not a page zoom and not the browser's default font-size setting, so media-query breakpoints stay at 16px rem.

## 1. Diff review

The 2cb228f..1d1d6e4 diff touches exactly the five files that were claimed:

- `home.css`: +10 lines, all inside a new `@media (max-width:44.99rem)` block. It holds the two rules quoted in the claim plus a comment. The base rule and the `min-width:45rem` rule are unchanged.
- `test_web_pilot.py`: +8 lines, a new pin. The existing assertions are unchanged, including the original `scroll-padding-inline` pin. The new pin also asserts that no `scroll-margin-inline-start` or similar property appears anywhere in the CSS.
- `tests/ui/README.md`: +18 lines.
- `tests/ui/harness/rail_focus_check.mjs`: new file.
- `docs/design/DESIGN.md`: +7 and -1.

These files are not touched by the diff:

- `home.js`
- `tests/ui/check_home_export.mjs`
- `tests/ui/harness/baseline.json`
- `tests/ui/baselines/`
- any axe assertion

The fix adds no script.

`1d1d6e4..c76634f --stat` shows `docs/member/help.md` only, one line changed: the citation `DESIGN.md:651` becomes `:679`.

- The citation was already stale on main. At `2cb228f` the 404-not-403 doctrine is at DESIGN.md line 673, not 651.
- On the branch the doctrine is at line 679, so the new citation is correct.
- `python -B -m unittest tests.test_member_content` on the branch: 41 tests, OK.

## 2. The implementer's harness against both stacks

I ran a scratch copy of `rail_focus_check.mjs`, unmodified, with no `--css` option. The harness always emulates reduced motion. Its widths are 320, 360, 390 and 430; it has no 375. Each size covers 292 focus stops: member-a and member-b on `/`, `/?for=watch`, `/?for=listen` and `/library`, with Tab and then Shift+Tab.

Clipped focused stops:

| Size | Baseline 2cb228f | Fix 1d1d6e4 |
|---|---|---|
| 320@100 % | 9 | 0 |
| 320@200 % | 0 | 0 |
| 360@100 % | 0 | 0 |
| 360@200 % | **76** | 0 |
| 390@100 % | 0 | 0 |
| 390@200 % | **76** | 0 |
| 430@100 % | 0 | 0 |
| 430@200 % | **78** | 0 |

- The typical baseline failure is the second card of rail 0, focused at 308..548 px in a rail box of 0..390 px, which matches the U-03 audit entry.
- Pointer click: on both stacks, a click on a peeking card moved the rail in 0 of 16 cases.
- Snap: after a wheel turn and after an arrow key, 0 of 32 cases came to rest off a card start, on both stacks.
- axe at 390 and 1280: 0 serious or critical violations, on both stacks.
- One finding remains on both stacks: `/library` at 320@200 % scrolls the page 8 px sideways (U-10, also on main). It is not a rail finding.
- Total findings: baseline 28, fix 2. The 2 on the fix are that `/library` sideways scroll, once for each member.
- Raw output: `h-base.json`, `h-fix.json`, `h-base.log` and `h-fix.log` in the scratch folder below.

All numbers match what the implementer claimed.

## 3. Own script (independent), fix stack

The script is `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x10\x10_verify.mjs` and its results are in `v-fix.json` in the same folder. By default it does not emulate reduced motion, and after each key press it waits for every rail's `scrollLeft` to stop changing. For each focused element inside a rail it checks:

- the element's bounding rectangle lies within [0, innerWidth];
- there is 3.5 px of ring room inside the rail box.

It makes 400 Tab presses per page. Focus wraps around the page during those presses, so the stop counts include repeats.

**Sweep.** member-a and member-b on `/`, `/?for=watch`, `/?for=listen` and `/library`, at 320, 360, **375**, 390 and 430, each at 100 % and 200 %:

- Each size had 1536 stops, repeats included.
- Not in view: **0 at all 10 sizes**.
- No ring room: **0 at all 10 sizes**.

**First rail on `/`, at 390@200 % and 430@200 %, for both members.**

- Cards 1, 2 and 3 each come to rest at 40..280 px when focused, so each is wholly in view.
- After the 3rd card is focused, Shift+Tab moves focus to the 2nd card. It lands at 40..280 px, wholly in view, with ring room.

**Wheel, then scrollend, on the first overflowing rail of `/`.**

- 390@100 %: `scrollLeft` goes from 0 to 134, the next card starts exactly at the start edge (offset 0), and `scrollend` fired.
- 390@200 % and 430@200 %: a 130 px wheel turn snapped back to `scrollLeft` 0, with offset 0. That is still card-aligned, but the turn was too small to reach the next card.

**Reduced motion emulated, 390@200 %, all four pages, both members:** 0 not in view and 0 without ring room. Stop counts per page ranged from 108 to 247.

**Desktop and tablet**, 768 and 1280, each at 100 % and 200 %, on `/`, both members:

- 0 not in view and 0 without ring room, over 246 stops for member-a and 224 for member-b.
- Resting first card, left edge: 44 px at 768@100 %, 300 px at 1280@100 %, and 40 px at 200 % for both widths. Every rail had `scrollLeft` 0.
- The rails used the desktop scroll-padding (6 px, and 12 px at 200 %). This confirms the `min-width:45rem` rules applied, and the new phone block sits outside that range.

## 4. Tests on c76634f

Each module was run on its own from the worktree.

| Run | Result |
|---|---|
| `test_web_pilot` | 28 OK, including the new pin |
| `test_web_pwa` | 33 OK |
| `test_web_home` | 21 OK |
| `test_web_home_hero` | 28 OK |
| `test_web_shell_k` | 12 OK |
| `test_web_library_k` | 42 tests; see the note below |
| `tests.test_home_static_export` + `tests.test_ui_harness` | 32 OK |
| `tests.test_member_content` | 41 OK |

`test_web_library_k` had one failure on its first run, while both harness runs were loading the machine. The failing test's name was not captured. It then passed 3 times in a row, so I treat it as flaky under load. The fix changes only CSS inside the phone block and does not touch Library code.

## 5. DESIGN.md wording

This is acceptable: the change is a note pending owner acknowledgement, not a silent rule change.

- The Rail Focus Rule paragraph gains a block labelled *"RC2 change (U-03, RC1 A11Y-1), pending owner acknowledgement:"*.
- The block says why the old region failed: at 200 % text the region collapsed to the whole rail.
- It says what changed: on phones the region is one `--cw` wide, and a card wider than that carries a negative end scroll-margin.
- It says what did not change: the start edge, the snap, the resting alignment, everything from 45rem, and "Still no script".
- It names the new harness next to `check_home_export.mjs`.

The original rule text is kept, not rewritten.

## Not measured

- **`check_home_export.mjs --focus-only`.** Static exports of both trees were written to the scratch folder (181 pages each), but they were never served or checked. I cannot confirm the implementer's claim of 0 findings over 63 views. For context, the U-03 audit reports this check failing on 16 exported Home pages on main.
- **My own script against the baseline stack.** It was stopped before finishing. As a result:
  - The baseline at **375** px was not measured by either tool.
  - My own wheel-snap and desktop resting-offset numbers have no baseline counterpart. The comparison rests on the harness snap results (0 misaligned on both stacks) and on the diff, which leaves the desktop rules untouched.
- **A larger wheel turn at 200 %.** The script `x10_wheel.mjs` (60, 200 and 420 px turns) was written but not run on either stack.
- **My own axe run.** The axe results above come only from the implementer's harness.
- **Real browser text scaling** (Chrome default font size or page zoom), Safari and VoiceOver. Those belong to the device review (AVR-585).

## Residual risk

- The negative `scroll-margin-inline-end` relies on Chromium's focus-scroll rule: it scrolls only when the margin box falls outside the scroll-padding region. WebKit's handling is unverified.
- 200 % text was simulated by changing the root font size. A real OS or browser text-size setting could also move the 45rem breakpoint; that was not tested.
- The `/library` page at 320@200 % still scrolls 8 px sideways (U-10). It is not caused by this fix.
