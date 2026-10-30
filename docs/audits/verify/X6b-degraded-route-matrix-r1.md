# X6b: re-verification of X6 R1 (degraded-route matrix reaches the #146 shape)

Change under review: `5e09641` on `c2178c3`, branch `test/rc2-degraded-route-matrix` (worktree `avrana.wt-rc2-t01`).
Verifier: an independent agent. It edited no worktree, committed nothing, ran no ssh or Docker and started no dev stack.
Each unittest module ran on its own. Scratch: `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x6b\`.
`mut\` is a copy of t01 at `5e09641`; `mut2\` is the same copy with `17b78bb`'s application changes applied.

## Verdict: ACCEPT. R1 is closed. One small follow-up (F1) on the S2 change.

## 1. Claims checked

| # | Claim | Result |
|---|---|---|
| 1 | L9 + all-not_linked + 12 seeded + 54 one-section deviations on `/`, `/?for=listen`, `/?for=read` | **Confirmed** by reading. One-section count: 5+5+5+3 sections x 3 states = 54. |
| 2 | Both `@expectedFailure` tests assert 200 first | **Confirmed**, but see F1: inside an expected-failure test, that assert hides a crash. |
| 3 | Tile check covers Library chips and the New Releases / New to Avrana tabs, flags loose children; heading exemption narrowed | **Confirmed.** `library.html:41` really is `<nav class="chips">`, and the tabs are `<nav class="tabs">` (`_parts.html:121`). Anchors are removed before tags are scanned, so a loose `span/s/div/button/p/strong/em` is flagged. A nav with no link is flagged. `hard_bare` now excuses only `Continue` and `New to Avrana`, and only when main carries "are unavailable right now" or "are not set up for your account yet". Every other bare heading fails even beside a banner. This is stricter than `c2178c3`. |
| 4 | #146 mutant gives exactly 2 problems | **Confirmed independently.** In scratch `mut\`, `fallback` became `released` on `viewmodel.py` lines 1160–1190 (6 lines changed, CRLF kept). Result: `FAILED (failures=1, expected failures=2)`: `[one:audiobookshelf.recent=empty] /?for=listen: status 500` and `[one:komga.recent=empty] /?for=read: status 500`, "2 problems in 294 requests". |
| 5 | Green unmutated, ~75 s | **Green**: `Ran 10 tests ... OK (expected failures=2)`. Took **56.6 s** here, faster than claimed. Under mutants it took 62–66 s. `test_web_released_fallback` stays 7 OK. |

The comics-only member is not a gap. Under the #146 mutant it gets 200 on `/`, `/?for=read`, `/?for=comics` and `/library?lib=komga`, because with one place it never reaches the multi-library fallback.

## 2. Weakened assertions

- **Scenario set.** It drops from 81 uniform to 9 pairwise, plus 12 random and 54 one-section scenarios. Every pair of
  libraries still meets every pair of ok/empty/unavailable, and the one-section set adds the shapes that matter. The
  combinations of 3 or 4 libraries in particular states are lost; I see no defect class that depends on them. Acceptable.
- **The one-section set asks only `/`, `/?for=listen`, `/?for=read`.** One-section shapes are never requested on
  `/library`, `/continue` or `/search`; only the mixed scenarios rotate through those. This is a minor gap and is
  acceptable for cost.
- **The request floor dropped from `> 100` to `> 50`.** The real counts are 294 (member with every library) and about
  111 (comics-only), so the floor is loose but harmless.
- **F1 (follow-up, not blocking).** `assertEqual(200, ...)` inside an `@expectedFailure` test turns a crash into an
  *expected failure*, which is green. Before, a crash showed as an unexpected success, which is red. I proved it with
  mutant 3: raise when focus is Listen and Audiobooks has `continue` empty with `recent` not_linked (the second xfail
  test's shape). A direct request returns 500, and that xfail test passes as an "expected failure". The module still
  failed, but only because `random#0` (seed 20261029) happens to have the same Audiobooks shape. Fix: put the 200 check
  (and `hard_bare`) for both plans in an ordinary test, for example in `AdjacentStates`, and keep only the heading
  assertion under `expectedFailure`.
- **Line endings.** `5e09641` converts `test_web_degraded_matrix.py` from CRLF (as committed in `c2178c3`) to LF.
  That makes the raw diff show 309/269 lines; with `--ignore-cr-at-eol` it is +67/-27. LF matches `plan_adapters.py`.
  Reviewers should read the diff with `--ignore-cr-at-eol`.

## 3. CI minutes

| commit | matrix module (local) | requests (all-library sweep) |
|---|---|---|
| `c2178c3` | 79.2 s | 540 |
| `5e09641` | 56.6 s | 294 |

R1 saves about 22 s per pass, about 45 s per two-pass job. Compared with `2cb228f`, the branch now adds about 62 s
per pass locally (matrix plus `Routes`). At 1.0–1.5x on the runner, that is about **2.1–3.1 min per `offline-tests`
job**, down from 2.8–4.3. The job goes from about 11 min to about 13–14 min of its 20-min timeout, about 30–35 %
headroom. No further trimming is needed.

## 4. Interaction with the X11 headings fix (`17b78bb`, `fix/rc2-bare-rail-headings`)

I applied `17b78bb`'s `_sections.html` and `viewmodel.py` hunks to scratch `mut2\` (CRLF needed `git apply
--ignore-whitespace`). The fix:
- hides the Continue section unless it has items or a line;
- hides New to Avrana unless it has items or a line;
- gives New Releases rows the key `released`.

Then I ran the matrix:

```
UNEXPECTED SUCCESS: ...BareHeadingsUnderABanner.test_continue_has_a_line_when_komga_has_nothing_in_progress_and_books_are_down
UNEXPECTED SUCCESS: ...BareHeadingsUnderABanner.test_new_to_avrana_has_a_line_when_audiobooks_are_not_set_up
Ran 10 tests in 57.208s
FAILED (unexpected successes=2)
```

**Confirmed: the two branches together turn the module red.** Whichever branch merges second must remove both
`@unittest.expectedFailure` markers. Once X11 lands, `DEGRADED_RAILS` can also be emptied, which makes the
empty-heading check unconditional. No other conflict:
- `test_web_released_fallback` is 7 OK on the combined copy, so the `h-released` id change does not touch the
  `Routes` assertions.
- Both branches add `webtests/plan_adapters.py` with the identical blob (`4c3b3ad`), so that file will not conflict.

Not fixed here, as instructed.
