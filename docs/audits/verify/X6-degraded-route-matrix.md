# X6: independent verification of T-01 / T-02 / T-03 (degraded-route matrix)

Change under review: branch `test/rc2-degraded-route-matrix`, commit `c2178c3` on `2cb228f` (worktree `avrana.wt-rc2-t01`).
Verifier: an independent agent. It edited nothing in the change, ran no ssh or Docker, and committed nothing.
Scratch work (mutants, timing script): `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x6\`
(the mutated copy is `home-mut\services\avrana-home`, beside copies of `services\avrana-portal` and `tests\fixtures`, because `support.py` resolves them from the repo root).

## Verdict: ACCEPT, with one required follow-up (R1) before merge, or a corrected claim

The change is tests only, it is green, and it adds real route-level coverage: StrictUndefined is genuinely active,
the tile check parses real tiles, and the matrix catches a view-model crash and a template undefined. **But the
headline claim is wrong for the matrix.** The T-01 matrix does **not** catch the original #146 defect. When I put the
shadowing back, the matrix still passed. Only the new `Routes` class (T-02) catches it, and the older Tier A
`Fallback` and `Markup` tests caught it already. The module docstring and the PR text must not say the matrix pins the
#146 class until R1 lands.

## 1. Scope and baseline runs

`git diff --stat 2cb228f..HEAD` lists three files, all under `services/avrana-home/webtests/`: `plan_adapters.py`
(+107), `test_web_degraded_matrix.py` (+269) and `test_web_released_fallback.py` (+97/-2). No application code changed.

Runs used `python -B -m unittest discover -s services/avrana-home/webtests -t services/avrana-home -p <module>.py`:

| module | tests | result | time |
|---|---|---|---|
| test_web_degraded_matrix | 10 | OK (expected failures=2) | 79.2 s |
| test_web_released_fallback | 7 | OK | 9.8 s |
| test_web_library_k | 42 | OK | 43.4 s |
| test_web_sections | 31 | OK | 29.9 s |

These match the claimed counts. The matrix time falls inside the claimed 80–91 s range.

## 2. Would it have caught the original 500?

The fix is `96df80b` ("Listen and Read no longer answer 500 when nothing was added lately", part of #146, merge
`e62bb33`). It renamed the fallback local `released` (the name that holds All's New releases cards) to `newest`. On
`2cb228f` that local is now called `fallback` (`viewmodel.py` lines 1165–1186). **Mutant 1** renames it back to
`released` in both branches. Nothing else changes, and the CRLF line endings are kept.

- **`Routes` (T-02): fails, as it should.** `/?for=listen` and `/?for=read` return 500 (`200 != 500`), and the log shows
  the real `UndefinedError: 'RowVM object' has no attribute 'title'`. Of the 7 tests in the module, 4 fail and 1 errors.
  The older Tier A test `Fallback.test_a_filtered_home_with_nothing_new...` and the `Markup` render also fail, so this
  mutant was caught before T-02 too. T-02 adds the HTTP-level proof.
- **`DegradedMatrix` (T-01): passes (10 ran, OK, 2 expected failures).** It misses the defect for a structural reason.
  The defect needs Audiobooks or Comics with `recent` empty while `shelves` is ok. The 81 uniform scenarios set every
  section of a library to the same state, so "recent empty" always comes with "shelves empty", and an empty fallback
  never touches `released`. Each of the 8 seeded random scenarios had a 1-in-16 chance per library of producing the
  shape, about 12 % per scenario. None of the 8 drawn with seed 20261029 does. I checked all 8.
  `AdjacentStates` does not isolate the shape either.
- **One-hot deviations would catch it.** For every library and offered section, I set one section to
  empty / unavailable / not_linked with the rest ok, and asked for `/?for=listen` and `/?for=read`. That is 54
  scenarios and 108 requests. Against mutant 1 exactly two returned 500: `audiobookshelf recent empty /?for=listen`
  and `komga recent empty /?for=read`.
- **Mutant 2** adds `if focus == "listen" and not cont: raise RuntimeError` after `cont = cont_all[:limit]`. The matrix
  **fails**: 34 problems in 540 requests, the first being `[uniform:ok/empty/ok/ok] /?for=listen: status 500`. The
  comics-only sweep stays green, which is correct because Listen is not one of that member's places. Side effect: one
  `BareHeadingsUnderABanner` test turned into an *unexpected success* because a 500 error page has no headings. Its
  `get()` helper never checks the status (see F3).

## 3. Assertion quality

- **StrictUndefined is genuinely active.** I added `<span hidden>{{ home.x6_missing_attr }}</span>` to a scratch
  `_sections.html`. `Routes` failed 7 subtests and the matrix failed both sweeps with status 500: 377/540 requests for
  the member with every library, 107/138 for the comics-only member. **Control:** with the
  `env.undefined = StrictUndefined` line removed from scratch copies of both test files, the same template passed
  everything (6 ran, OK). So the swap on `app.state.env` is what catches it. It also takes effect even though the
  templates are compiled at startup.
- **The tile check parses real tiles.** The regex matches the real `<nav class="places" ...>` and
  `<nav class="places filters" ...>`. I removed the two `<span class="sr">, unavailable...</span>` reasons from a
  scratch `_parts.html`, and the matrix failed with 300/540 and 43/138 "struck tile without a reason". Weak spots:
  - `chips` in the regex matches no template. The New Releases chips are `<nav class="tabs">` and are not checked.
  - The "is a link" check flags only `<div>` and `<button>`. A bare `<span>` or `<s>` tile outside an `<a>` would pass.
  - The `tiles` / `kplaces` navs on other pages are not checked.
- **F1. The empty-heading check is off on most of the matrix.** `hard_bare` returns `[]` whenever main holds
  `class="banner"` or `class="k-warn`. Any unavailable library raises a banner, so the check is skipped in 65 of the
  81 uniform scenarios. It only applies in the 16 ok/empty combinations, in `uniform:not_linked` (which has a banner too,
  so it is also skipped), and in the random cases. The exemption `class="k-` anywhere in a section body is also broad.
  This is deliberate, because it tolerates the two pinned defects, but the module docstring should say so.
- **F2. The status and body checks are sound.** `<main` is counted exactly, and the bad words include the
  `error.html` text ("Something went wrong"). Any 500 is caught by the status code first.
- **F3. `get()` in the T-03 and defect classes ignores the status.** The `AdjacentStates` tests do assert 200, but the
  two `@expectedFailure` tests do not. A crash would turn them into "unexpected success". That is still a failed run
  on Python 3.12, but for the wrong reason. Assert 200 inside them.
- **Timing (`derive_hard_cap`).** The cap is `REQUEST_BUDGET` (2.0 s) + `HARD_CAP_MARGIN` (1.0 s) = **3.0 s** per
  request. The synthetic adapters answer instantly, so this measures render time only. It is a smoke budget, not a
  hard-cap test. Measured with an instrumented sweep (`timing.py` in scratch), 540 requests:
  - idle: max 0.83 s (a first `/` on a fresh client), p50 0.016 s.
  - 6 copies at once on 4 cores: maxima of 0.67–1.56 s.

  The worst case is about half the cap. Flake risk is low, but a slow or throttled 2-vCPU runner could approach it.
  Optional: skip the first request per client in the timing check, or warm the client before timing.

## 4. The two display defects (`BareHeadingsUnderABanner`)

I reproduced both by hand on the change's code via the fakes (`get()` with the tests' own plans, status 200 each time):

1. `/?for=read`. Komga continue is empty and Books continue/recent are unavailable (the other libraries' continue is
   empty). The banner reads "Books are unavailable right now." Below it:
   `<section class="shelf" aria-labelledby="h-continue">` / `<h2 id="h-continue">Continue</h2>` / `</section>`, with no
   card and no line. Cause, as the test says: `continue_said = None if (cont or cont_degraded)`.
   **Real.**
2. `/?for=listen`. Audiobooks continue is empty and recent/shelves are not_linked. The banner reads "Audiobooks are not
   set up for your account yet." Below it:
   `<section class="shelf shelf-new" aria-labelledby="h-new">` / `<h2 id="h-new">New to Avrana</h2>` / `</section>`,
   bare. **Real.**

Both are honest pins of display defects. They are not crashes, and the banner explains the library. Each needs a
Linear follow-up so the `expectedFailure` markers are removed when the defects are fixed.

## 5. CI cost

`offline-tests.yml` has `timeout-minutes: 20` and two full passes (normal, then no network). The job takes about
11 min, and the web suite is about 76 % of it, roughly 4.2 min per pass.

The change adds about 80 s locally per pass (matrix 79 s plus about 5 s for `Routes`). At 1.0–1.5x on the CI runner
that is **about 2.8–4.3 min per job**. The job grows to about 14–15 min, and headroom drops from about 45 % to about
25–30 %. That is a large increase for one module.

Where the time goes (all-library sweep: 90 scenarios, 60.8 s):
- About 30 s is building a client per scenario.
- About 30 s is requests.
- The comics-only sweep (23 scenarios) adds about 15–20 s.

**Trim recommendation** (also fixes R1):
- Replace the 3^4 = 81 uniform product with an L9 pairwise array (9 scenarios) plus `all-not_linked`.
- Add the 54 one-hot section deviations, asking only `/`, `/?for=listen`, `/?for=read`, `/library` (or just the two focus pages).
- Keep the 8 random cases.

Estimated net: about the same or less time (about 72 fewer scenarios against 54 cheap ones), and it actually catches
#146. Keep the comics-only sweep at every 4th scenario. It is the cheapest distinct branch.

## Required and suggested follow-ups

- **R1 (required before merge, or correct the claim).** Add one-hot per-section scenarios, or at minimum
  `{audiobookshelf: {recent: empty}}` and `{komga: {recent: empty}}` through `/?for=listen` and `/?for=read`, so the
  T-01 matrix itself fails on the #146 mutant. Until then the docstring and PR must credit `Routes` (T-02), not the
  matrix, with pinning the 500.
- S1: trim the uniform product to pairwise (section 5) to win back about 1–1.5 min per pass.
- S2: assert status 200 inside the two `expectedFailure` tests (F3).
- S3: drop the dead `chips` alternative or point it at `nav class="tabs"`, and flag any non-anchor child of a places
  nav, not only div/button.
- S4: document in the module that the empty-heading check is skipped on any page with a banner (F1).
- S5: file the two display defects (section 4) in Linear.
