# X2: independent verification of F-02 fix ("This week in comics" card links to a chip that exists)

- Defect: F-02 (P2, confirmed). Baseline 2cb228f (read-only checkout `avrana`).
- Fix: worktree `avrana.wt-rc2-f02`, branch `fix/rc2-comics-stack-chip`, commit 31982f9 on 2cb228f.
- Verifier: independent agent, 2026-10-29. No files in either tree edited; no ssh, Docker or real services.

## Verdict: ACCEPT

The fix closes F-02 in both reported shapes (Komga `released` failed; caught-up reader whose released comics are all in
Continue / New for You). The chip set still derives only from libraries the member can see, `rel` is still never
echoed, and the normal case and the All rail are unchanged. Three non-blocking notes below (test gap, dedupe
exception, a pre-existing count/list mismatch).

## 1. Probe (original, `functional/probe_comics_stack_link.py`)

| Tree | Result |
|---|---|
| Baseline 2cb228f | FAILED (2/2). Card href `/?rel=comics#h-released`, chips `['all','watch','listen']`; following the card shows All. |
| Worktree 31982f9 (copy in `scratchpad/verify-x2/`, path repointed) | OK (2/2). Chips `['all','watch','listen','comics']`; following the card makes Comics current. |

Note: the first attempt to repoint the copy with `sed` silently left the main-checkout path in place (backslashes), so
it re-ran the baseline; caught by checking `sys.path.insert` and redone with a Python string replace. The OK result
above is from the copy that imports the worktree.

## 2. Diff review (`git diff 2cb228f..31982f9`)

Scope: 2 files. `viewmodel.py` +7/-2, confined to `build_home`'s New Releases block (`week = items_of(...)` hoisted
above the chips, one extra chip condition, one fallback line). `test_web_comics_week.py` +28 (class
`CardLinkGoesSomewhere`). home.css and templates untouched.

- **Chip set still derives from what the member may see.** The new condition is
  `k == "comics" and focus is None and len(week) >= WEEK_MIN`. `week` comes from `_items_of`, which reads only
  `state == "ok"` sections of `held`; `_sections_by_service` drops `not_permitted` sections; Customize-hidden places
  remove Komga from `held` (when no other shown place needs it); Komga-sourced e-books are moved to Books before this
  point, so `week` holds comics only. Probe: Komga `not_permitted` on every section gives no card and no chip, also
  with `?rel=comics` (same as baseline). Komga entirely unavailable: no card, no chip.
- **`rel` never echoed.** Unchanged: `rel` is set only if it is a key of the computed chips; `?rel=<script>` falls back
  to All (probe f).
- **Normal case unchanged.** When `picked` holds comics, the fallback does not run; `?rel=comics` lists the released
  comics as before (unit test `test_normal_case_is_unchanged`, live dev stack below).
- **All rail and #157 one-third balance.** The stack/balance block is textually unchanged; only the `week` assignment
  moved up. `test_web_released_balance` 4/4. In the shapes where the fix adds the Comics chip, `len(chips) > 1` now
  holds, so the card and `balanced()` run where previously the rail had one kind; with comics folded into the card
  the rail is one kind and `balanced()` is a no-op.

### The implementer's caveat, examined precisely

Claim: "a member whose only other kinds are not comics now gets the Comics chip, and the card, whenever the week has
two or more issues; previously that case had a single chip and no card."

Confirmed by probe (fixture: Movies and TV + Comics only):

| Case | Baseline | Fix |
|---|---|---|
| one other kind, Komga `released` unavailable, week 6 | no card, no chips; `?rel=comics` shows All rail, no tabs | card drawn; chips All/Movies and TV/Comics; `?rel=comics` lists Issue 10-15, Comics current |
| one other kind, released comics all in New for You | no card, no chips | same as above |

So the baseline did NOT draw the card in that case (it is gated on `len(chips) > 1`); there was no dead link there,
but a comics member silently lost all comics from New Releases. The new behaviour matches the owner rule ("on All
comics ALWAYS fold into one card when there are at least WEEK_MIN") and gives that member a working card and chip.
I judge it correct. A comics-only member still gets one chip, no tabs and no card (unchanged). A member without the
comics library never sees the chip or the card (not_permitted path above; live `member-a` below).

### Dedupe ("each title appears once on the page", DECISIONS 2026-10-28)

When `?rel=comics` falls back to `week`, issues already in Continue / New for You are listed again (probe d: Issue 10
and 11 in Continue and in the Comics chip). Decision: **acceptable, intended exception**, because the card itself
already counts those issues ("N from your series" is computed from exactly that overlap), so the chip the card opens
must list what the card counted; filtering by `seen` would reproduce the empty-list contradiction in the caught-up
case. It applies only on the chosen Comics chip, never on All. Recommend one line in DECISIONS or a code comment that
names this as an exception.

### Non-blocking notes

1. **Test gap.** The 2 new tests that fail at baseline fail on the precondition `"the card is drawn"`: the fixture
   has only Movies and TV + Comics, so at baseline there is no card. They guard the caveat shape, not the reported
   F-02 shape (card drawn with >= 2 other kinds, link reloads All). They do catch a revert of either changed line,
   but a fixture with a second non-comic kind (e.g. an audiobook) would pin the exact reported defect. The original
   probe covers it.
2. **Partial caught-up (pre-existing, not F-02).** If `picked` keeps 1 comic and `week` has 6, the card says
   "6 new issues" and the Comics chip lists 1 (probe c; identical at baseline). The fallback is all-or-nothing on
   "no comic in picked". In the normal fixture too, the card counts `week` while the chip lists `released`. Worth a
   follow-up if card count and chip list are meant to agree.
3. **Flaky runs.** `test_web_home` (2 failures) and `test_web_library_k` (1 failure) failed once under machine load,
   then passed on 2 and 1 reruns respectively; failure text was not captured on the first run. Both modules exercise
   rendered pages with timing; nothing in this diff touches them.

## 3. Test modules (worktree, one at a time, `python -B`)

| Module | Result |
|---|---|
| test_web_comics_week | 11 OK |
| test_web_released_balance | 4 OK |
| test_web_release_order | 5 OK |
| test_web_new_rows | 9 OK |
| test_web_released_fallback | 3 OK |
| test_web_home | 21 OK on rerun x2 (first run 2 failures, see note 3) |
| test_web_home_shelves | 27 OK |
| tests.test_home_static_export | 8 OK |
| test_web_sections | 31 OK |
| test_web_library_k | 42 OK on rerun (first run 1 failure, see note 3) |
| test_web_new_for_you | 11 OK |

`CardLinkGoesSomewhere` run against baseline code: 2 of 3 fail (claim confirmed), both on the precondition.

## 4. Live dev stack (worktree, ports 8396 / 18396-18399, synthetic data)

- `member-b` GET `/`: chips All (current), Movies and TV, Audiobooks, Comics, Books; stack card
  `href="/?rel=comics#h-released"` "This week in comics".
- `member-b` GET `/?rel=comics`: Comics chip `aria-current="true"`, no card, 5 comics listed (Synthetic Teen One,
  Kids One, Mature One, Manga One, Comic Two).
- Komga mock `POST /__mock/mode/down`: immediately after, cached sections still served; card and Comics chip both
  present and the chip still lists the comics (consistent, nothing dead). After the cache window (~130 s): "Comics are
  unavailable right now.", no card, no Comics chip, `rel=comics` appears nowhere; `?rel=comics` falls back to All.
- `member-a` (no comics group) GET `/` and `/?rel=comics`: chips All / Movies and TV / Audiobooks only, no card,
  `rel=comics` occurs 0 times.
- Stack stopped; ports freed. The mock cannot fail only Komga's `released` while `week` answers, so the F-02 shapes
  themselves were verified by the view-model probes, not live.

## Artefacts

`C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x2\`:
`probe_comics_stack_link.py` (repointed copy), `edge_probe.py` (cases a-h, run on both trees),
`new_tests_on_baseline.py`, `x2_page_inspect.py`, saved pages `*.html`, `devstack.log`.
