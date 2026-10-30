# X11 verification: bare rail headings and duplicate New Releases id (D-01, D-02, U-07)

- **Verdict: ACCEPT**
- Fix: branch `fix/rc2-bare-rail-headings`, commit `17b78bb` on baseline `2cb228f` (worktree `avrana.wt-rc2-f07`).
- Verifier: independent agent, 2026-10-29. Read-only on the fix worktree and the main checkout; synthetic fixtures
  only (the module's own `plan_adapters`), no dev stack started, no live host touched.

## 1. Reproduction on baseline, pass on fix

Baseline = `git archive 2cb228f` of the main checkout into a scratch directory, plus only
`webtests/test_web_bare_headings.py` and `webtests/plan_adapters.py` copied from the fix.

Invocation (the repo's own, README line 72 and `tests/run_offline.py`; without `-t` the package-relative imports
fail to load):
`python -B -m unittest discover -s services/avrana-home/webtests -t services/avrana-home -p test_web_bare_headings.py -v`

| Test | Baseline 2cb228f | Fix 17b78bb |
|---|---|---|
| D-01 Continue empty + Books unavailable: no bare Continue | FAIL (`['Continue']` heading with no content) | ok |
| D-01 control: empty Continue, nothing down, keeps heading + "Nothing in progress." | ok | ok |
| D-02 Audiobooks not set up on Listen: no bare New to Avrana | FAIL (`['New to Avrana']`) | ok |
| U-07 Listen: `h-released` New Releases and `h-new` New to Avrana | FAIL (dup `h-new`, `rail-new`) | ok |
| Unique ids on 8 routes | FAIL on `/?for=listen` and `/?more=released&for=listen` (dup `h-new`, `rail-new`) | ok |
| Show more anchors resolve to an id on the page | ok | ok |

5 of 6 fail on baseline, as claimed; all 6 pass on the fix (Ran 6, OK).

## 2. Diff review (`git diff 2cb228f..17b78bb`)

Four files: `_sections.html` (+2/-1 guards and one comment), `viewmodel.py` (one line in `shelf_rows`), two new test
files. No existing test or assertion changed; `home.css` and `home.js` untouched. No scope creep.

- Continue guard `show_continue and (continue_items or continue_said)`: `continue_said` is `NOTHING_IN_PROGRESS`
  whenever Continue is empty and no Continue section is unavailable/not_linked (`viewmodel.py:1058`), so the
  DESIGN.md "Nothing to show" rule (empty Continue keeps its heading and line) still holds; the heading is dropped
  only in the degraded case, where the notice explains it (DESIGN.md "One library down"). Continue with items is
  unchanged.
- New to Avrana guard `show_new and (new_items or new_said)`: a non-All tab always gets a line when empty
  (`viewmodel.py:1095`); the All tab gets `NOTHING_NEW` unless a notice is present (`:1091`). The section therefore
  disappears only when it is empty and a notice is up, which is the D-02 class.
- `shelf_rows` key: `"released"` only when the heading is `NEW_RELEASES`. The fallback rows ("Recently released",
  `viewmodel.py:1167`, `:1184`) are re-keyed by their callers and keep their existing keys; `SHELF_ROWS` itself and
  `shelf` item validation (`:240`) are unchanged. The Library page path (`:1399`) also benefits (its ids are
  `l-<index>-<key>`, unique either way).

## 3. Selector and anchor check for the `released` key

`grep h-new|rail-new|h-released|rail-released|more=new` across `home.css`, `home.js`, templates, DESIGN.md and
webtests: no CSS or JS selector targets `h-new`/`rail-new`; every `#h-new` link and `?more=new` belongs to New to
Avrana (`viewmodel.py:1098`, `:1216`); shelf rows carry no `more_href`. The skip link targets `#main`, not a shelf.
The only test reading row keys for New Releases (`test_web_new_rows.py:107`) already expected `"released"`.

## 4. Neighbouring modules on the fix (one module at a time)

All OK, no timing reruns needed: test_web_bare_headings 6, test_web_home 21, test_web_sections 31,
test_web_new_rows 9, test_web_released_fallback 3, test_web_home_shelves 27, test_web_continue 5,
test_web_home_hero 28, test_web_library_k 42, test_web_calibre 14, test_web_komga 14, test_web_customize 19,
test_web_comics_week 8, test_web_new_for_you 11; `python -B -m unittest tests.test_home_static_export` from the
repo root 8.

## 5. plan_adapters.py

`git diff --no-index` against `avrana.wt-rc2-t01/services/avrana-home/webtests/plan_adapters.py`: no output; SHA-256
identical (`f5342444…062f`).

## Residual risk (low, not blocking)

- New to Avrana on the All tab with two or more libraries that answer but hold nothing recent, while a third library
  is down: before, heading + library tab nav with no line; now the whole section (tab nav included) is left out. The
  tabs only led to "Nothing added to … recently.", and the notice is shown, so this matches the rule, but it is
  untested.
- Continue empty where a Continue section is `not_linked` but no notice is raised for that library would now show
  nothing at all instead of a bare heading. Not worse than baseline; not covered by a test.
- Whole-suite run (`tests/run_offline.py`) not done; only the listed and related modules.
- `plan_adapters.py` now exists on two branches (t01 and f07); whichever merges second should see a no-op for that
  file only if both stay byte-identical.
