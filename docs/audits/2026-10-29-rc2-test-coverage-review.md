# Media 2.0 RC2 quality sprint: test coverage and test quality review

Date: 2026-10-29 (evening Pacific) / 2026-10-30 UTC. Reviewer: test coverage agent. Read-only: no repository file was
edited, nothing was committed, no ssh, no Docker, no real service, no package installed.
Baseline: `origin/main` `2cb228fbfdae596ef3da1754afe88e48b1556552` (checkout at
`C:\Users\cnech\Projects\avrana-homelab\avrana`, `git status` clean apart from `.claude/`).

Evidence tags: **[CI]** GitHub Actions run 40973080456 (offline-tests) or 40973080451 (beta-image) at 2cb228f;
**[read]** read from the tree; **[measured]** run here on Windows 11 / Python 3.12.3 with one test module at a time;
**[probe]** a throwaway script under the scratchpad that imports the app and drives it with synthetic adapters;
**[inferred]** derived from timestamps or code, not observed directly.

## 0. Summary

1. The tests that exist are mostly meaningful. Isolation, identity, header, breaker and cache-revocation tests assert
   behaviour with fakes (not mocks of the thing under test). Of 2,440 `test*` methods (AST scan), none is vacuous; 32
   have no direct `assert` call but delegate to a helper that asserts (six checked by hand); 41 assert only a status
   code and nearly all of those are deliberate "standard 404/501" security cases.
2. The weakness is **where** the assertions sit, not how many. Home is tested almost entirely at the view-model
   (`build_home(...)`) and template-render level, and the only layers that would catch a wrong-looking phone page
   (Playwright + axe, `pwa_sw_check.mjs`, `pwa_check.mjs`) never run in CI. Service-worker policy, rail focus (A11Y-1)
   and CSS rules are asserted as **source substrings**.
3. Every adapter fixture is hand-written and says so (19 of 19 files carry "Hand-written SYNTHETIC fixture ...
   unverified against the deployed version"). No recorded live shape is committed (AVR-772 still open). The 29 Oct
   Listen/Read 500 was a data-shape condition (nothing added in two months) that no fixture modelled.
4. **Measured finding, reproducible today:** `tests/test_hung.py` fails 2 of 4 tests **deterministically when run on
   its own** (`12 not less than or equal to 4`, `32 not less than or equal to 8`), and passes in CI only because
   earlier alphabetical modules have already created the process-wide 48-thread section pool. Order dependence.
5. **Measured finding:** with one other Python process running, 7 of 67 web modules and 1 adapter module failed on
   wall-clock-bound assertions; all passed again on an idle machine (section 4).
6. **Probe result:** 181 degraded-state scenarios x 14 routes (2,534 requests, section 2.4) produced **zero**
   non-200 responses and no `Traceback`/`UndefinedError`. The Listen/Read 500 does not reproduce today in any
   ok/empty/unavailable combination; the finding is that nothing in the repository would catch it if it came back
   through the route layer.
7. CI: green, 11 min 10 s of a 20-minute cap (8 min 50 s headroom, 44 %), two identical passes, **no required status
   check or ruleset exists** on `main`. `test_runner.py` re-runs the whole adapter suite four times inside the web
   suite and costs roughly 97 s of every 247 s web pass **[inferred]**.
8. Twenty-three missing regression tests are listed in section 6 (T-01 to T-23); eight are P1.

## 1. Method

- Read: `tests/run_offline.py`, `services/avrana-home/tests/run_web_tests.py`, the three workflows,
  `.github/requirements-ci.txt`, `services/avrana-home/README.md` "Run the tests", `tests/ui/README.md`,
  `webtests/__init__.py`, `webtests/support.py`, `tests/_netguard.py`, `tests/helpers.py`, the baseline
  `docs/release/MEDIA-2.0-RC2-STATE.md`, RC1 report section 4 (`git show origin/docs/media-2.0-rc1:docs/release/MEDIA-2.0-RC1.md`),
  ADAPTER-CONTRACT, and the test modules cited below.
- CI numbers: `gh run view 40973080456 --log` (suite counts and `Ran N tests in X s` lines, both passes), step
  timestamps, and `gh run view 40973080451 --json jobs`. Two further read-only `gh api` GETs (branch protection,
  rulesets) and `gh run list` for the last 30 offline-tests runs.
- Static scan: an AST pass over `webtests/`, `services/avrana-home/tests/` and `tests/` for methods with no assert
  call and methods whose only asserts compare a status code (script: `scratchpad\coverage\weak.py`).
- Index: unittest discovery (import only) to number every web and adapter test, then mapped CI dot-progress
  timestamps to test indices to find where the 247 s of the web suite goes (`web_index.txt`, section 5).
- Measured: every web and adapter module run once by itself (`times.txt`), failures re-run on an idle machine;
  `test_phase1.N6EvictionIsNotQuadratic` timed directly (`n6.py`).
- Probes: `probe_degraded.py` (121 scenarios) and `probe_sparse.py` (60 scenarios with optional fields dropped and
  Komga mixing comic and ebook items) drive `create_app` through `webtests.support.make_client` with synthetic
  `MediaAdapter` subclasses, no sockets.
- `coverage` is **not installed** in `.venv-media` (checked, not installed), so there is no line-coverage figure. All
  "covered / not covered" statements are by named test, with the gap shown by grep.
- Local environment limits: `.venv-media` has no Pillow (so `test_web_me_profile` errors at import; CI has it, the
  lock lists it) and no PyYAML. Local per-module times are inflated by a concurrent probe and are only used for
  relative ordering. CI times are authoritative.

## 2. Journey to tests matrix

Legend: **S** strong (behaviour asserted through the route or adapter with a realistic fake), **V** view-model or
template level only, **W** wording/source only, **-** none.

| # | Journey | Tests that cover it | Strength | Gaps |
|---|---|---|---|---|
| J1 | Sign in and understand where you are | `webtests/test_web_jwt_identity.py` (41, e.g. :254 bad tokens), `test_web_identity.py` (24), `test_web_identity_bindings.py` (12; :116 recreated user), `tests/test_outpost_jwt.py` (32), `tests/test_verified_identity.py` (43); shell and places: `test_navigation.py:47`, `test_web_pilot.py` NavigationTests, `test_web_shell_k.py`, `test_web_pages_k.py`; no-library and one-library: `test_web_home.py:224`, `test_navigation.py:154` | S for identity; V for the shell | No assertion says what a **signed-out** visitor sees or is told (bad tokens are compared to the "nobody" page, `test_web_jwt_identity.py:254-268`). Bindings tested on 6 page URLs only (T-09, T-10). |
| J2 | Discover (rails, hero, New for you, Library) | `test_web_home.py` (21), `test_web_home_hero.py` (28), `test_web_home_shelves.py` (27), `test_web_new_for_you.py` (11), `test_web_library_k.py` (42), `test_web_comics_week.py`, `test_web_released_*.py`, `test_bench_cache_revocation.py` | V (view-model + `template.render(home=...)`) with some S in `test_web_library_k.py:584-638` (`/?for=` through the client) | No route-level test of any focus/rel/more/new chip with an empty or unavailable section (T-01 to T-03). Visual quality, phone layout and A11Y-1 not tested in CI (T-04, T-23). |
| J3 | Continue with correct ordering and progress | progress words: `tests/test_continue_semantics.py` (:154 state table), `test_polish_h2.py:92-128`; ordering: `test_web_new_for_you.py:62-98` (`by_activity`), `test_web_home.py:70` (merge); upstream: `test_web_continue.py` (mock Jellyfin + ABS), `tests/test_audiobookshelf.py:78` (one `active` value), `test_komga_member_reading.py` | V for ordering (items built with hand-set `active`), S for progress arithmetic | No end-to-end ordering across the three real adapters from their fixtures; no timezone/epoch-unit cases (T-17). |
| J4 | Cross-library search | `test_web_search.py` (19; :122 one down, :136 all down), `tests/test_search.py`, `tests/test_title_and_search_states.py`, `test_web_title.py` SearchLinks | S | Calibre OPDS and ABS multi-library shapes are doc-verified only (ADAPTER-CONTRACT:1001-1013). |
| J5 | Request film/TV/book/comic, season picker, My requests | film/TV `test_web_watch_requests.py` (11; :186 outcomes, :205 double tap), `test_season_picker.py` (6), book `test_web_book_requests.py` (17; :193 double tap), `test_book_request_units.py` (13), comic `test_comic_requests.py` (11), `test_my_requests.py` (21), `test_broker_hardening.py` (11), `test_owned_index.py` (11) | S (signed, same-origin, token-bound, as-the-member) | Comics have no double-tap test (T-05). No timeout-after-send wording test for Seerr/Shelfarr at the web layer (T-05, T-06). Seerr/Shelfarr/Omnibus shapes are inline fakes (`test_web_watch_requests.py:41-54`). Cap monitor tests not in CI (T-16). |
| J6 | Open the correct media handoff | `tests/test_contract.py:16-29` (valid ids to fixed hosts), `test_web_continue.py` (prefix asserts), title pages `test_web_title.py` | V | Path templates are "unverified against the live apps" (ADAPTER-CONTRACT:209); no test links item kind to the right app (Komga ebooks vs Calibre-Web) (T-18). Needs the owner device pass (O5). |
| J7 | TV Quick Connect | adapter `tests/test_quickconnect.py` (:108 answers map to fixed outcomes, :115 never retried), web `test_web_quick_connect.py` (15) | S for the approval and its guards | Web layer asserts **only** `?r=approved` wording (`:136-142`) and its fake always answers 200 `true` (`:37-49`). No page-level test of `not_found`, `unknown`, `off`, `busy`, `unavailable`, `not_accepted` copy (T-07, T-08). |
| J8 | Account, recovery, expired session, sign-out | `test_web_me_security.py` (27), `test_web_me_profile.py` (14), `test_web_customize.py` (19), `test_web_pwa.py` Signout (:375-420), help topics `test_navigation.py:140` | S for forms; W for sign-out cache clearing | Expired JWT on a POST is only the generic 501 (`test_web_quick_connect.py:70`); form-token `expired` words exist (`test_web_customize.py:206`) but JWT expiry mid-form is untested (T-12). Recovery flows live in Authentik (blueprints #151 not applied). |
| J9 | Errors and degraded libraries | `tests/test_resilience.py`, `test_hung.py`, `test_slowdrip.py`, `test_abs_slow_fanout.py`, `test_breaker_policy.py`, `test_review3.py:147` (AVR-756), `test_web_sections.py` DegradationTests (:317-470), `test_web_pilot.py:346` FailureRecoveryTests, `test_web_isolation_h2.py:166`, `test_web_released_fallback.py` | S for upstream failure modes on Home; V for the fallback rows | See section 2.3 and T-01 to T-03. |
| J10 | Phone layout | CSS/markup substring tests (`test_web_pilot.py:324`, `test_web_shell_k.py`, `test_web_motion_k.py`, `test_web_brand.py:115`); static layer of `tests/test_ui_harness.py` (HTML rules, computed contrast) | W | Rendered layout, focus visibility, 390 px and 200 % text are checked only by the manual Playwright layer (183 pages x 6 views, RC1) which is not in CI. |

### 2.1 Where the layers stop

- `tests/test_ui_harness.py:316-319` only runs `node --check` on `check.mjs`, and skips without Node. No `.mjs` file
  is executed by any CI step. [read]
- `home.js` behaviour (rail buttons, `data-once` busy state, lens, `pagehide`) is asserted by reading its source
  (`test_web_pwa.py:95-125`). [read]
- `scripts/` and connector suites: section 5.4.

### 2.2 What is genuinely strong (keep)

`test_bench_cache_revocation.py:55-100` (a revoked group hides Library, Home and cached art with zero upstream calls),
`test_web_sections.py:484` (group removal with a warm cache), `test_web_isolation_h2.py:85-166`,
`test_web_identity.py` (real-socket header cases), `test_web_jwt_identity.py` (alg confusion, duplicates, smuggling),
`tests/test_review3.py:147-200` (AVR-756, event-ordered, no sleeps), `test_web_sections.py:397` (AVR-733 made
deterministic with events), `tests/test_quickconnect.py`, `tests/test_identity_bindings.py` (including 5- and
6-process races).

### 2.3 The Listen/Read 500 class (PRs #146, #148)

- The regression test is `webtests/test_web_released_fallback.py` (commit 000bbd0). Its Tier B class `Markup`
  (`:60-69`) renders `_sections.html` from a hand-built `HomeVM`; it never requests a route, so a failure in the route
  assembling the page, the shell template, `/library`, `/continue`, or the `rel`/`more`/`new` chips would not be seen.
- The hand-built `VIEW` (`:32-38`) models exactly one combination (ABS and Komga `recent` empty, shelves present,
  Calibre `recent` present). No test varies which of the sections is empty or unavailable.
- Route-level tests of filters (`test_web_library_k.py:584-638`) use fixtures where **every library has recent
  items**, so they never reach the fallback branch.

### 2.4 Probe: degraded-state matrix through the real app [probe]

`probe_degraded.py`: four synthetic adapters (Jellyfin, Audiobookshelf, Komga, Calibre-Web) with per-section state
`ok | empty | unavailable` for `continue, recent, next_up, shelves, released, for_you, week`; 81 uniform combinations
plus 40 seeded random ones; 14 routes each (`/`, `/library`, `/search?q=`, `/?for=` x5, `/continue?for=listen`,
`/library?lib=audiobookshelf|komga`, `/?rel=books`, `/?more=released`, `/?more=new`). 121 x 14 = 1,694 requests, all
200. `probe_sparse.py`: 60 random scenarios with optional fields (`released`, `active`, artwork, shelf, progress)
randomly absent and Komga alternating comic and ebook: 840 requests, all 200. No `Traceback` or `UndefinedError` in
any body. Not covered by the probe: `not_linked`, hostile titles, `view=` layouts, the `/title/` pages.

## 3. Superficial, snapshot-like, over-mocked or unrealistic tests

Ordered by risk of passing on wrong behaviour.

| ID | Where | What it asserts | Why it can pass on wrong behaviour |
|---|---|---|---|
| S-1 | `webtests/test_web_pwa.py:281-304` `test_the_policy_in_the_worker_source` | 20+ substrings of `sw.js` (`"response.redirected"`, `"ALLOW[path]"`, `"cache: 'reload'"` ...) and ordering by `str.index` | A worker with those strings in dead code, or a logic error between them, passes. The docstring says "the behaviour itself is run in a browser, see the PR"; `pwa_sw_check.mjs` (a Node `vm`, no browser) does run the handlers but is not in CI. |
| S-2 | `webtests/test_web_pilot.py:324-340` (A11Y-1 related) | exact CSS strings incl. `scroll-padding-inline:var(--pad) max(var(--pad),calc(100% - var(--pad) - max(var(--cw),var(--wide-max)) - 0.5rem))` (`:336`) | It pins the implementation text. A11Y-1 (focused rail card not wholly visible at 390 px / 200 % text, RC1 section 4.1) is open **with this test green**. |
| S-3 | `webtests/test_web_released_fallback.py:60-69` | renders `_sections.html` from a hand-built `HomeVM` (section 2.3) | Passes if the route 500s for any reason other than the one template variable it was written for. |
| S-4 | `services/avrana-home/beta/smoke.py:62-70` and `webtests/test_beta_image.py:147-150` | "verified token: member view" = HTTP 200 only; the unit twin asserts `assertTrue(r.json())` | A member view that is empty or the wrong member's passes. This is the only check run against the built image in `beta-image`. |
| S-5 | `webtests/test_web_quick_connect.py:37-49` `FakeJellyfin` | always `Enabled` true, `Users` fixed list, `Authorize` 200 `true` | Cannot reveal any wrong handling of a real Jellyfin refusal at the page level; adapter-level mapping is covered separately (`tests/test_quickconnect.py:108`). |
| S-6 | `webtests/test_web_watch_requests.py:41-54` `FakeSeerr`, `webtests/test_comic_requests.py`, `test_book_request_units.py` `Recorder` | inline minimal shapes (`results`, `mediaInfo.status`) | Seerr, Shelfarr and Omnibus shapes are not recorded anywhere; a renamed field returns an empty list that still satisfies "no crash". |
| S-7 | All 19 JSON files under `services/avrana-home/tests/fixtures/` | each opens with "Hand-written SYNTHETIC fixture ... unverified against the deployed version" | Self-declared; every adapter parse test proves the parser matches the author's memory of the API (ADAPTER-CONTRACT:570, 763, 850). Mitigation that does exist: `tests/test_openapi_subset.py` checks allow-lists against recorded OpenAPI versions (Jellyfin 10.11.11 and 12.3.0). |
| S-8 | Copy negatives: `test_web_search.py:134,142-143` (`assertNotIn("unavailable"|"No results"|"No matches", r.text)`), `test_web_continue.py:82`, `test_web_home.py:242` (`"Traceback"`) | a word is absent from the whole page | If the copy is reworded the negative passes while the state is wrong. Paired with a positive assertion in most places (checked), but not all. |
| S-9 | `webtests/test_web_audiobooks.py:92-104`, `test_web_identity.py:96` | `assertIn("Continue", text)` / `assertIn(" left", text)` on the whole page | "Continue" is present on any Home with the shell; `" left"` matches any substring. The title assertions beside them carry the weight. |
| S-10 | `webtests/test_web_sections.py:385,405`, `:397-427` | sets `adapter.breaker._open_until = 0.0` and replaces `acquire`, `recent_items`, `continue_items` on the instance | White-box: it replaces the objects whose interleaving it claims to test. Acceptable for AVR-733 determinism; the real race is only exercised by `test_recovery_after_the_cool_off_needs_no_restart` (`:377`), which tolerates either winner by design. Same pattern in `tests/test_review3.py:155-173`. |
| S-11 | `webtests/test_web_motion_k.py:96-210`, `test_web_brand.py:115-118`, `test_web_shell_k.py` | CSS/JS text matches (durations, `@media` guards, names) | Assert that the rule text exists, not that it applies. Useful as a ratchet, not as proof of the experience. |
| S-12 | `webtests/test_route_layer_source.py` (9 tests) | greps the app source for forbidden patterns | Architecture guard; passes on any behaviour that avoids the pattern. Appropriate, but should not be counted as coverage. |

Status-code-only tests (41 by AST): `test_web_identity.py:312-366` (real-socket header cases), `test_web_artwork.py:150,249`,
`test_web_book_requests.py:94-187`, `test_web_ops.py:98,105`, `test_my_requests.py:186`, `test_web_quick_connect.py:99`,
`tests/test_portal_authz.py:596-756,1194,1420,1438` and others. Reviewed: these are standard-404/501/403/400 negative
cases and are correct to assert on the code alone, provided a **control** with a good header exists in the same module
(it does in `test_web_identity.py:95-97` and `test_web_jwt_identity.py:239`).

## 4. Reliability

### 4.1 Measured

| ID | Test | Evidence | Verdict |
|---|---|---|---|
| R-1 | `tests/test_hung.py:49-62` `test_in_flight_cap_bounds_hung_calls` and `test_repeated_gathers_do_not_grow_threads_without_limit` | `python -B -m unittest discover -s tests -t . -p test_hung.py`, idle machine, run 3 times and each test alone: `AssertionError: 12 not less than or equal to 4` and `32` (or `48`) `not less than or equal to 8`. The test takes `before = threading.active_count()` then triggers `gather`, which lazily creates the process-wide `_DaemonPool(POOL_WORKERS=48)` (`avrana_home/aggregate.py:31,76-82`). In CI the pool already exists from `test_abs_slow_fanout` / `test_aggregate`. | **Order dependent, deterministic when isolated.** Fix by creating the pool in `setUp` before sampling, or asserting growth after a warm-up gather. |
| R-2 | Wall-clock bounds on a busy machine | With a second Python process running (my probe plus the sequential timing loop): `test_preview` 2 failures, `test_web_audiobooks` 1 failure + 1 error (`'ok' != 'unavailable'` at `:110`, and `ConnectionAbortedError` tracebacks from the mock), `test_web_home` 1, `test_web_home_hero` 2 (`:349` hero not found), `test_web_jwt_identity` 1, `test_web_library_k` 1, plus `test_hung`. Re-run idle: `test_web_home` 21 OK (6.0 s), `test_web_home_hero` 28 OK (4.6 s), `test_web_audiobooks` 17 OK (21 s), `test_web_jwt_identity` 41 OK, `test_web_library_k` 42 OK, `test_preview` 11 OK. | 7 of 67 web modules (10 %) are sensitive to CPU contention because they run real loopback mocks under 0.3 to 1.0 s request timeouts. CI passes (17 of the last 17 completed successes), but a slower runner or two jobs on one machine would trip them. Matches RC1's note that suites must be run one at a time. |
| R-3 | `test_phase1.N6EvictionIsNotQuadratic` (`:476-487`, bound 10 s for 300 evictions into a 2048-entry cache) | Timed directly: 1.6, 2.3, 2.7 s idle; 3.5, 3.6, 4.0 s under contention; RC1 recorded 13.3 s under three suites plus Chromium. | The bound is a wall-clock proxy for "not quadratic" with 4x idle headroom and 0.75x loaded headroom. Replace with an operation count (`:489-497` has a second 5 s bound). |
| R-4 | `webtests/test_web_me_profile.py:25` | `ModuleNotFoundError: No module named 'PIL'` in `.venv-media`; counted as 1 error (a `_FailedTest`), not a skip. | Good: a missing dependency fails loudly here. But it shows the documented local venv is incomplete (CI pins Pillow in the lock, `test_ci_workflow.py:158`). |
| R-5 | Skips on this Windows machine | `tests/test_cache.py` (permission check prints "permissions check ran on nt", `:392-398`) and `tests/test_preview_static.py:92` (no PyYAML) | `test_cache.py:392` and `test_identity_bindings.py:88`, `test_komga_member_reading.py:436` skip their `0o600` assertion with an `if os.name`, **not** `skipIf`, so Windows reports pass without asserting. CI (Linux) does assert. |

### 4.2 From the code and the CI log

| ID | Item | Evidence | Verdict |
|---|---|---|---|
| R-6 | `tests/test_section_queue.py:36,51,58,65,72,100` and `test_hung.py:69` | "immediate" refusals asserted `< 0.05` s of real `time.monotonic()`; `:44-47` asserts the wait lies in `[SECTION_SLOT_WAIT - 0.05, +0.25]` | 50 ms on a shared runner or a Windows 15 ms timer is tight. Passed in CI so far. P3. |
| R-7 | `tests/test_slowdrip.py:20-48` | `setUpClass` runs a subprocess probe (timeout 120 s, 7 s measured); asserts `elapsed < DEADLINE + 0.4` | Real sockets and real deadlines; acceptable, but one more wall-clock sensitive module (7.0 s locally). |
| R-8 | Real-time bounds in web tests | `test_web_ops.py:60` (< 0.5 s), `test_web_pilot.py:382,391`, `test_web_sections.py:328` (< 2.5 s), `test_mock_upstream.py:130` (< 1.2 s), `tests/test_portal_authz.py:1318` (< 4 s), Kindle `test_authz.py:1130,1154` (< 3 s) | Same class as R-2. |
| R-9 | Free-port helpers | `test_beta_image.py:26-33`, `test_preview.py:36-40`, `test_web_dev_stack.py:15-21` bind port 0, close, and reuse the number later | Classic time-of-check/time-of-use window. Low odds with ephemeral ports; the README already warns about TIME_WAIT under parallel suites. |
| R-10 | Log noise hiding signal | CI web pass: 53 `ResourceWarning: unclosed <socket.socket ...>` and 7 `Exception occurred during processing of request ... BrokenPipeError` tracebacks per pass (both passes). | Real leaks (catalogue.py:39/41, jinja nodes) and mock-server resets drown any new warning. P3: close sockets in tests, silence the mock's `handle_error`. |
| R-11 | Shared global state | `webtests/__init__.py` patches `socket.socket.connect/bind/...` and `getaddrinfo` at import (process-wide, intended); `aggregate._pool` (R-1); 51 `setUpClass` mock servers reused across tests with `set_mode` reset in `setUp` | Order dependence found only in R-1. All other 47 adapter modules and all 67 web modules passed when run alone (apart from R-2 contention failures and R-4), which is the strongest available evidence of independence. |
| R-12 | Clock | `viewmodel.py:1047` and `main.py:969` use `dt.date.today()` (local) against UTC `active` strings; tests pass `today=` almost everywhere, `test_web_released_fallback.py:62-63` does not (it does not depend on the date) | The baseline was taken at 16:00-17:00 Pacific = after midnight UTC. A local-vs-UTC day skew is plausible in "today/yesterday" labels (T-19). |
| R-13 | AVR-733 | `test_web_sections.py:377-395` is race-tolerant by design (either request may win the half-open trial, then asserts state `ok` and the page shows the film on the second request); `:397-427` is the deterministic form | Fixed. Residual: both depend on `Event.wait(5)`; if the event is never set the failure is a timeout, not a clear message. |
| R-14 | AVR-756 | `test_review3.py:147-200`: event-ordered, no sleeps | Fixed and well formed. (The `/readyz` tests, `test_web_ops.py:64-103`, are a different item: deterministic, one 0.5 s bound at `:60`.) |
| R-15 | `AVRANA_REQUIRE_DEPS=1` | Used only by `tests/run_web_tests.py:64-69`; **CI never runs that script** (`run_offline.py` calls `unittest discover` directly and sets only `AVRANA_REQUIRE_YAML`). In CI both passes finished with no `skipped=` in any summary line, so nothing was skipped. | What it hides: nothing in CI today. What it would reveal: any silent skip (FastAPI absent turns 994 web tests, `test_home_preview.py`, `test_home_static_export.py` and the UI-harness page tests into skips with exit 0). The only protection is `pip --require-hashes` plus the exact-set test at `tests/test_ci_workflow.py:158-165`. |
| R-16 | Windows vs Linux | Repository tests take ~25 min locally on Windows vs 51 s in CI (RC1), G1 stub tests. Windows: 1 adapter skip (POSIX mode check), `test_preview_static` needs PyYAML. Linux: no skips. | RC2 local evidence will not equal CI; keep CI the arbiter. |
| R-17 | Kindle expected failure | `services/avrana-kindle-connector/tests/test_authz.py:481` `@unittest.expectedFailure`: a group named `x,avrana-books` grants access ("needs an owner decision") | CI is green over a recorded open authorisation finding. Not Media Home, but it lives in the same gate. |

## 5. CI quality

### 5.1 Numbers [CI]

Job `python tests/run_offline.py`: 23:26:05Z to 23:37:15Z = **11 min 10 s** (install 6.6 s; pass 1 333 s; pass 2 324 s).
Cap `timeout-minutes: 20` (`.github/workflows/offline-tests.yml:41`): **headroom 8 min 50 s (44 %)**. Last 30
`offline-tests` runs: 17 success (7 min 34 s to 11 min 30 s including queue time), 10 cancelled (superseded by
`cancel-in-progress`), 3 failures at 61 to 63 s (early, not timeout).

| Suite | Tests | Pass 1 | Pass 2 (`unshare --net`) | Share of pass 1 |
|---|---|---|---|---|
| repository (`tests/`) | 451 | 51.2 s | 50.3 s | 15.7 % |
| imax-verify (script) | script | < 0.1 s | < 0.1 s | 0 |
| Kindle offline / authz / a11y | 4 / 92 / 44 | 0.06 / 3.4 / 0.7 s | 0.06 / 3.3 / 0.7 s | 1.3 % |
| backups | 30 | 2.2 s | 2.1 s | 0.7 % |
| assistant | 93 | 1.1 s | 1.0 s | 0.3 % |
| Home adapters (`services/avrana-home/tests`) | 1,018 | 20.6 s | 20.1 s | 6.3 % |
| Home web (`services/avrana-home/webtests`) | 994 | **247.2 s** | **240.3 s** | **75.8 %** |
| **Total tests per pass** | **2,726** | 326 s of suite time | 318 s | |

Growth: RC1 recorded 2,679 tests on d3ed4e4 and 8 min 22 s of a 10-minute cap on 8aaa1b1; the job is now 11 min 10 s
with the cap doubled. Another +33 % would still fit in 20 minutes.

Where the 247 s goes [inferred from the dot-progress timestamps against the unittest index]: one 97 s stretch with no
test completing sits between test 202 and test 280, which contains `webtests/test_runner.py` (tests 254-257). That
module's `StrictSkipTests` shell out to `tests/run_web_tests.py` four times, and each call runs the **whole adapter
suite** (20 s) plus a throwaway web suite. So `test_runner.py` is about 97 s, 39 % of the web pass and 30 % of each
pass, and it runs twice per job (about 195 s of the 666 s of test time, 29 %). The next gaps are 21.7 s
(tests 678-768: `test_web_me_security` to `test_web_pages_k`, locally the motion/pwa/library modules) and 16.8 s
(tests 73-171: `test_capture_upstreams`, `test_comic_requests`, `test_dev_covers`). Locally the slowest web modules by
unittest time (contended) were `test_web_motion_k` 105 s, `test_web_isolation_h2` 91 s, `test_web_library_k` 83 s,
`test_web_audiobooks` 64 s, `test_web_continue` 57 s.

### 5.2 What the workflows gate

- **No gate exists on `main`.** `gh api repos/rcnechamkin/avrana/branches/main/protection` returns 404 "Branch not
  protected" and `gh api repos/rcnechamkin/avrana/rulesets` returns `[]`. A pull request with a failing
  `offline-tests`, `beta-image` or `enrollment-policy` run can be merged. [CI] (See section 7 for what this cannot
  show.)
- `offline-tests.yml`: triggers `pull_request` and `push` to `main` only (no `schedule`, no `workflow_dispatch`).
  Job 1: both passes; job 2 `content-gate` (`scripts/review_git_content.py --staged`, 10 s). `test_ci_workflow.py`
  guards the workflow itself (pinned SHAs, no secrets, read-only permissions, the requirements set, the second-pass
  command, `AVRANA_REQUIRE_YAML` appearing exactly twice).
- The second pass (`unshare --net`, user dropped with `setpriv`) proves nothing needs a network; it costs 324 s, 49 %
  of the job, and re-runs every suite although only the socket-opening ones (repository tests, Home web) could differ.
  It could be a parallel second job (wall time 5.6 min instead of 11.2) or limited to those two suites.
- `beta-image.yml` (run 40973080451, **49 s**): path-filtered to `services/avrana-home/**`,
  `services/avrana-portal/portal.py` and itself; builds `Dockerfile.beta`, checks the image refuses
  `HOME_IDENTITY_MODE=headers` and a real upstream variable (exit 2), runs it and calls `beta/smoke.py` (7 status-only
  checks, S-4) and `beta/rehearse_degraded.py` (Jellyfin mock down, the others stay ok, recovery within 150 s, 32 s in
  this run). Nothing about content, ordering, handoff links or phone layout.
- `enrollment-policy.yml`: **pull requests only, path-filtered** to `avrana-enrollment.yaml`, the Authentik
  `docker-compose.yml`, its two test files and itself; 30-minute cap; real Authentik 2026.5.6 in an `--internal`
  network. It does not run on `push` to `main`, on a schedule, or when any of the other 13 blueprints changes
  (`avrana-account`, `avrana-recovery`, `avrana-session-tuning`, `calibre-web-ldap`, ...). The latest runs on the open
  PRs: success 0593910, **failure ddde2e7**, success 458946a, 25916c8, f456dc9.

### 5.3 Why `AVRANA_REQUIRE_DEPS=1` and the strict checks matter

CI relies on the install step (`--require-hashes`, exact-set assertions in `test_ci_workflow.py:140-166`) for the
Home dependencies and on `AVRANA_REQUIRE_YAML=1` for PyYAML. There is no equivalent for "no test was skipped": a
future change that makes `import fastapi` fail would still show the job green with 0 web tests run, unless the exact
set test caught it first (T-21).

### 5.4 Suites that exist but never run in CI

| Suite | Tests (`def test_`) | Why it matters for Media 2.0 |
|---|---|---|
| `tests/ui` browser layer: `harness/run_ui.py`, `check_home_export.mjs`, `pwa_sw_check.mjs`, `pwa_check.mjs`, `motion_check.mjs`, `skip_link.mjs`, `home_preview/check.mjs` | 6 `.mjs` + harness | Only automated check of phone layout, A11Y-1, focus, axe, the service worker and sign-out cache clearing. |
| `scripts/test_api_caps_monitor.py` | 10 | Request-cap monitor (#125); **not in the RC2 baseline's list**. |
| `scripts/test_offboard.py` | 7 | Host-only (runs the real script at `/home/cody/avrana`); offboarding a tester. |
| `scripts/test_epub_audiobook_matcher.py` | 9 | One Windows path failure (RC1). |
| `scripts/test-storage-log-check.py` | script | Referenced from `drift-check.py:51`, never executed by CI. |
| Audible connector `services/avrana-audible-connector/connector/tests/` | about 123 across 14 files | Pytest; 6 failures and 9 errors on Windows (RC1). Only `tests/test_audible_schema.py` runs. |
| `services/calibre-web-automated/tests/test_attachment_filename.py` | 7 | Needs Calibre-Web's `cps`. |
| `services/avrana-imax-verify/tests/test_server.py` | 6 | Only `test_classify.py` runs. |
| Kindle `test_kindle.py` live tests | 6 of 10 | `run_offline.py:28-34` excludes anything using `curl(` (needs Docker). Four run. |

## 6. Prioritised missing regression tests

P1 = could put a visible defect or a cross-member leak in front of closed-beta members and nothing would fail;
P2 = important, partly mitigated; P3 = hygiene.

| ID | Pri | Module (new or extended) | Scenario | Assertion | Why it matters |
|---|---|---|---|---|---|
| T-01 | P1 | new `webtests/test_web_degraded_matrix.py` (use `support.make_client`, a configurable synthetic `MediaAdapter` as in `probe_degraded.py`) | 4 libraries x per-section state `ok/empty/unavailable/not_linked` (81 uniform + seeded random) x routes `/`, `/?for=` (5), `/?rel=`, `/?new=`, `/?more=`, `/continue[?for=]`, `/library[?lib=&view=]`, `/search?q=`, `/home.json` | every response 200 (json valid), exactly one `<main`, no `Traceback`/`UndefinedError`/"Something went wrong", every place tile either a link or struck with a reason, finished inside the hard cap; render with `StrictUndefined` in this test so any missing context variable raises | The 29 Oct Listen/Read 500 class. Today it is pinned only through a hand-built view model (S-3). The probe shows it passes now, so this is a pure regression pin. |
| T-02 | P1 | extend `webtests/test_web_released_fallback.py` with a Tier B route test | Exact #146 shape through HTTP: ABS and Komga `recent` and `continue` EMPTY, shelves and released OK; request `/?for=listen`, `/?for=read`, `/?for=comics`, `/?for=books`, `/library?lib=audiobookshelf` | 200 and the `EXPECTED` headings (`:41-42`) present in `<main>`; `id="h-released"` absent on the filtered pages; ids of the shelf cards appear once | The test that exists renders a template only. |
| T-03 | P1 | extend T-01 or `test_web_library_k.py` `HomeFilters` | Adjacent states: `read` with Komga ok and Calibre unavailable (and the reverse); `recent` ok but `released` unavailable; chips (`rel=books`, `new=komga`) for a library the member does not hold or that is down; `more=released` with nothing released | 200; the unavailable library named exactly once, in place, with its reason; no chip for a library the member does not hold; no empty rail heading | These are the neighbouring states of the 500 and are asserted nowhere. |
| T-04 | P2 | CI job running `tests/ui/check_home_export.mjs` (Node 22 + Playwright Chromium, axe-core), plus a Python wrapper that fails if Node is absent when `AVRANA_REQUIRE_NODE=1` | Static export at 390 px and 200 % text, Tab through every rail | each focused rail card's bounding box is wholly inside the viewport (the A11Y-1 ratchet), 0 serious/critical axe violations, no sideways scroll | A11Y-1 is open while `test_web_pilot.py:336` is green (S-2). Needs a decision from the owner on adding browser tooling to CI (D-8 style). |
| T-05 | P1 | `webtests/test_comic_requests.py` | Same signed form posted twice (sequentially, then from two threads), and a fresh token after a timeout-after-send (Omnibus `UpstreamTimeout`) | exactly one Omnibus write for the repeated token; the second response reads "just asked" like `test_web_watch_requests.py:205`; the timeout page says the request may have gone through and never auto-retries (one write per submit); My requests lists the issue once | Watch (`test_web_watch_requests.py:205`) and books (`test_web_book_requests.py:193`) have double-tap tests; comics do not. |
| T-06 | P2 | `webtests/test_season_picker.py` and `test_web_watch_requests.py:186` | (a) a season becomes requested between page load and submit (Seerr 409 for the posted seasons); (b) `UpstreamTimeout` after send; (c) show with every season already requested/in library | (a) DUPLICATE words, one POST, no error page; (b) wording does not claim "not asked"; (c) no form is offered and the page says why | `test_outcomes` covers 409, 403, 500 only; timeouts and partial seasons are unmodelled. |
| T-07 | P1 | `webtests/test_web_quick_connect.py` (parametrised `FakeJellyfin`) | Jellyfin answers: `Enabled` false, `Authorize` 404 / 401 / 403 / 500 / `false` / timeout, `Users` timeout | POST redirects to `?r=off`, `not_found`, `off`, `unavailable`, `not_accepted`, `not_accepted`, `unknown`, `unavailable`; `GET /me/tv?r=<each>` renders a distinct fixed sentence in `role="status"`, `unknown` says it may have worked and to look at the TV before trying again, no upstream text or code in the page; every approval counted once | Only `approved` wording is asserted (`:136-142`); the other eight outcomes (`quickconnect.py` OUTCOMES) have no page-level test. A Jellyfin 12 upgrade (beta audit) may change these answers. |
| T-08 | P2 | `webtests/test_web_quick_connect.py` | Six wrong codes within the window by one member; 31 attempts overall | 6th POST redirects `?r=busy` with zero upstream calls; another member still gets through until the overall cap; the busy sentence tells the member when to retry | Rate limit tested only at adapter level (`tests/test_quickconnect.py:127-146`). |
| T-09 | P1 | `webtests/test_web_identity_bindings.py` | Warm the cache as the real member-a (A1), then present the recreated user (A2, same name, different `sub`) on `/art/jellyfin/...`, `/title/jellyfin/<id>`, `/search?q=`, `/continue`, `/home.json`, POST `/request/watch`, `/me/tv`, `/me/profile`, `/me/avatar`, `/signout` | signed-out outcomes (404 or 501 as the catalogue defines), mock `paths()` empty, A1's avatar bytes, prefs and titles absent | The existing test (`:116-129`) is **cold** (no prior sign-in by A1) and checks six page URLs. S1 is the closed-beta blocker; breadth matters. |
| T-10 | P2 | `tests/test_identity_bindings.py` | (a) Authentik rename: same `sub`, new username; (b) `MAX_BINDINGS` (5,000) boundary; (c) username at 150 characters and invalid names (`_valid_name`); (d) file replaced with equal size and mtime; (e) release then rebind by the same `sub`; (f) clock moving backwards across `released` stamps | (a) new name binds, old name stays bound and a stranger taking it gets `identity_changed`; (b) 5,001st name returns UNAVAILABLE while known names stay OK; (c) boundaries refused without writing; (d) change still detected or documented; (e) allowed; (f) no loss of the shrink guard | Grep for `MAX_BINDINGS`, `rename`, `150` in the test file returns nothing. |
| T-11 | P2 | `webtests/test_bench_cache_revocation.py` | Warm Home, then remove one group, then request `/continue`, `/continue?for=`, `/?for=<lost>`, request pages and `/me/tv`; and, with `FakeClock`, an **upstream** change (Jellyfin policy hides a folder) inside the 30 s / 120 s cache lifetime | 404/501 standard, zero upstream calls, no `/art/` of the lost library; for the upstream case: stale at 119 s is documented and gone at 121 s | Revocation by header group is well covered for Home, Library and art (`:55-100`); the cache-lifetime staleness bound for upstream changes is not asserted anywhere. |
| T-12 | P2 | `webtests/test_web_jwt_identity.py` | Valid form token minted for the member, then POST to `/request/watch`, `/me/tv`, `/me/profile`, `/me/customize` with an **expired** or wrong-key JWT (and with none) | no upstream write, no store write, a recoverable standard response (decide: today a bare 501), form token not consumed | Session expiry while a form is open is the realistic "expired session" case; only GET is tested (`:254`). |
| T-13 | P2 | `webtests/test_web_home.py` | Signed-out visitor on `/` (no principal, expired token) | asserts what the page says and offers (or documents that the outpost handles sign-in and the page must not show member navigation) | Journey "sign in and understand where you are": the only assertion is "equals the nobody page" (`test_web_jwt_identity.py:254-268`). |
| T-14 | P1 | new CI step + Python wrapper test around `tests/ui/harness/pwa_sw_check.mjs` (Node `vm`, no browser) | Run the real `/sw.js` and kill-switch worker handlers with fake `caches`/`fetch` | only the allow-listed static shell is stored; 302/401/403/404/5xx navigations returned untouched and never cached; `/signout` and `/outpost.goauthentik.io/` not handled; offline page identical for all members; `message` clears caches | A service worker that stored a personalised page would leak across members on a shared device; today `test_web_pwa.py:281` only greps source (S-1). Needs Node in the CI runner (already present on `ubuntu-latest`). |
| T-15 | P2 | `tests/test_jellyfin_adapter.py`, `test_audiobookshelf.py`, `test_komga.py`, `test_calibre_web.py` | (a) mutation fixtures: ABS `libraryItem` without `addedAt`/`media.metadata`, Komga `metadata.releaseDate` null, Jellyfin item without `UserData`, OPDS entry without `<updated>`; (b) when the AVR-772 capture exists, load the sanitised recording and assert each parser yields items with the expected fields | (a) item dropped or defaulted, section state EMPTY or OK, never an exception and never a 500 at the route; (b) parity with the recorded shape | All fixtures are hand-written (S-7); the 29 Oct failure was a real-data shape. |
| T-16 | P2 | `tests/run_offline.py` (add suites) | Run `scripts/test_api_caps_monitor.py` (10), `scripts/test_epub_audiobook_matcher.py` (9, fix the Windows path), and `imax-verify/tests/test_server.py` (6) | included in the suite list and green | The cap monitor protects the request brokers (#125) and its tests never run. |
| T-17 | P2 | `tests/test_aggregate.py` or a new `webtests/test_web_continue_order.py` | Real Jellyfin, Audiobookshelf and Komga adapters over their fixtures with `LastPlayedDate` / `lastUpdate` (ms) / `readDate` at the same minute across libraries, with `+14:00` offsets, a missing date and a bad date | merged Continue newest first in UTC, missing and bad dates last, equal instants keep the library round-robin order, ABS milliseconds never read as seconds | `by_activity` is tested with hand-set `active` strings (`test_web_new_for_you.py:62-98`); adapter-to-order is not tested together. |
| T-18 | P2 | `tests/test_contract.py` + `webtests/test_web_title.py` | For every item kind (movie, episode, series, audiobook, comic, Komga ebook, Calibre ebook) check the `handoff_url` host and path and the title page "Open" link | Komga ebooks open on `read.avrana.net/book/`, Calibre on `books.avrana.net/book/`, an episode opens the episode and a series opens the series; the primary action label matches the kind | Templates are unverified against the live apps (ADAPTER-CONTRACT:209); only prefixes are asserted today. Needs the owner device pass for the live half. |
| T-19 | P3 | `webtests/test_web_new_for_you.py` | Run `build_home` and the week window with `TZ=America/Los_Angeles` at 17:30 local on a day where UTC has rolled over | "today", "yesterday" and "this week" agree with the UTC `active` strings | `viewmodel.py:1047` and `main.py:969` use the local date. |
| T-20 | P3 | `tests/test_hung.py` (R-1) | Warm the pool in `setUp` before sampling `threading.active_count()` | tests pass when run alone and in any order | Fixes a deterministic isolated failure. |
| T-21 | P2 | `tests/run_offline.py` | When `CI=true`, run every suite with skips counted | exit non-zero if any suite reports `skipped=` (matching `AVRANA_REQUIRE_DEPS=1` in `run_web_tests.py:64-69`) | CI can currently go green with the web suite skipped (R-15). |
| T-22 | P3 | `tests/test_phase1.py:476-497` | Replace the 10 s and 5 s wall-clock bounds with an operation count (comparisons or list scans per eviction) | bound on counted operations, deterministic | R-3. |
| T-23 | P2 | CI job for the Playwright layer on the static export (see T-04) | 390 px and 844x390 landscape, light and dark, 183 pages | 0 serious/critical axe violations, no sideways scroll, rail focus visible | Phone layout (journey J10) has no automated gate. Owner decision required to add Chromium to CI. |

## 7. What this review could not determine

- **Line coverage.** `coverage` is not installed and I was told not to install packages; all coverage statements are by
  named test and grep. Branches that no test names (for example the `Recently released` fallback in non-listed
  combinations) cannot be ruled in or out except by the probes.
- **Whether branch protection is truly absent.** The two API reads returned 404 and `[]`. A private repository on a
  plan without protection features also returns 404; an organisation-level ruleset or a required check configured in
  another way would not show. The owner should confirm in the repository settings.
- **Real-runner variance.** I have 30 recent run durations but not the runner CPU mix; the headroom figure is one
  run plus the range of 17 successes.
- **The 97 s attributed to `test_runner.py`** is inferred from timestamps and the code, not measured, because the
  brief forbids running `run_web_tests.py` (which that test invokes).
- **Local flake rate.** Seven web modules and one adapter module failed under a second Python process; I did not
  repeat the contention experiment, so the rate is one observation, not a statistic. Whether a hosted runner ever sees
  similar contention is unknown.
- **Live shapes and behaviour.** Any claim about Jellyfin 10.11 / 12, Audiobookshelf, Komga, Calibre-Web, Seerr,
  Shelfarr, Omnibus or Quick Connect against the real services is outside what offline tests (and this review) can
  show. Handoff correctness (J6), the iPhone check, Safari/VoiceOver and the installed PWA remain owner device gates.
- **Probe coverage.** The probe drove 14 routes with synthetic adapters; it did not cover `not_linked`, hostile
  titles, `view=` layouts, `/title/` pages, or timing, so "no 500 today" applies to those routes only.
- **Windows-only results.** `test_hung` was run on Windows; the reason (lazy pool created on first `gather`) is read
  from the code and would apply on Linux when the module is run alone, but I did not run it on Linux.
- **Audible, Kindle live, Calibre-Web-Automated, offboarding.** Counted from the source, not run.

## 8. Artifacts

Scratch files (not in the repository): `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\coverage\`:
`times.txt` (per-module results), `web_index.txt`, `adapter_index.txt`, `weak.py`, `probe_degraded.py`,
`probe_sparse.py`, `probe_out.txt`, `probe_sparse_out.txt`, `n6.py`, `agg.py`; CI log
`scratchpad\ci.log`.
