# X3 — independent verification of F-03 (Seerr search timeout)

- Defect: F-03 (PROBABLE, P2). Seerr `search` and the show/season lookup used the 2.0 s page timeout, and timeouts there fed the one per-process breaker that also guards `create`.
- Fix under review: worktree `avrana.wt-rc2-f03`, branch `fix/rc2-seerr-search-timeout`, commit `85b2c81`, one commit on `2cb228f`.
- Verifier: independent agent, 2026-10-29. I edited no repo files, made no commits or pushes, and used no ssh, Docker or real services. Every check used fake transports.

## Verdict: ACCEPT

## 1. Original probe

| Run | Search timeout used | search state | create after 3 slow searches | Result |
|---|---|---|---|---|
| Baseline `avrana` @ 2cb228f | `[2.0]` | `unavailable` | `unavailable`, 0 calls sent (breaker open) | 2/2 FAIL (defect reproduced) |
| Fix `avrana.wt-rc2-f03` @ 85b2c81 | `[8.0]` | `empty` | `awaiting`, 1 call sent | 2/2 OK |

To run the probe against the fix, I copied it and changed only the import path: `scratchpad/verify-x3/probe_fix.py`.

## 2. Diff review (`git diff 2cb228f..85b2c81`)

- Scope: only `requests/seerr.py` (+21/-8 lines) and `webtests/test_web_watch_requests.py` (+64). `git diff --check` is clean.
- Pattern: matches `shelfarr.py` exactly. `SEARCH_TIMEOUT = 8.0`, `timeout=max(self._timeout, SEARCH_TIMEOUT)` at the call site, `_call(..., timeout=None)` passed through to `_send(..., timeout=None)`, and `timeout or self._timeout` at the transport call.
- Timeout at every call site (fix):

| Line | Call | Timeout |
|---|---|---|
| 272 | `GET /api/v1/user` (member map pages) | page (2.0) |
| 295 | `GET /api/v1/search` | max(page, 8.0) |
| 318 | `GET /api/v1/tv/<id>` (`show`, the season picker) | max(page, 8.0) |
| 363 | `POST /api/v1/request` (create) | page |
| 383 | `POST /api/v1/user/import-from-jellyfin` | page |
| 401 | `GET /api/v1/request` (`mine`) | page |
| 432 | `DELETE /api/v1/request/<id>` (cancel) | page |
| 448 | `GET /api/v1/{movie,tv}/<id>` (`_look_up`, My-requests titles) | page |

- The route allowlist (ROUTES/ID_PATH), the admin/act_as handling, MAX_JSON_BYTES, the redirect refusal, the breaker construction (threshold 3, cooloff 60, lease 30) and the neutral/failure accounting are all untouched. The only change inside `_send` is the timeout argument. The breaker lease (30 s) is longer than 8 s, so a half-open trial call cannot outlive its lease.
- Season picker path: `main.py:468` `run_in_threadpool(seerr.show, ...)`. Search path: `main.py:488` `cached_search(... seerr.search ...)`. Neither has an outer `wait_for` that would cut the call short.

## 3. Test runs (fix worktree root, one module at a time)

| Module | Result |
|---|---|
| test_web_watch_requests | 16 / OK |
| test_broker_hardening | 11 / OK |
| test_season_picker | 6 / OK |
| test_my_requests | 21 / OK |
| test_web_book_requests | 17 / OK |
| test_account_provisioning (references SeerrRequests) | 8 / OK |
| test_book_request_units (references SeerrRequests) | 13 / OK |

All six webtests modules that reference seerr were run, plus test_web_book_requests.

## 4. Do the new tests catch the old code?

I put the new test file into a scratch copy of the baseline tree. The only change was the `SEARCH_TIMEOUT` import, which I replaced with a local `8.0`.
- `test_a_slow_search_still_returns_results`: FAILS on old code. Good.
- `test_the_show_lookup_uses_the_search_timeout`: FAILS on old code. Good.
- `test_create_keeps_the_short_timeout`, `test_a_longer_client_timeout_is_not_shortened` and `test_a_search_timeout_still_counts_toward_the_breaker`: PASS on old code. These are regression guards, not defect detectors. They are worth keeping, since they pin the "do not over-apply" and "breaker unchanged" contract. The breaker test is the weak one the implementer flagged: it would also pass on old code and on a fix that left search at 2 s.

## 5. Neighbouring journeys (probe `scratchpad/verify-x3/probe_journeys.py`, upstream search/show takes 6 s)

- 5 slow-but-successful searches all returned `ok`, and 3 slow show lookups all returned `ok`. Afterwards the breaker shows `_failures=0, _opened=False`.
- A movie create from a different member in the same process returns `AWAITING`. A tv create with seasons [1,2] returns `AWAITING`. `mine` returns `ok`.
- Timeouts observed: search 8.0, tv/<id> 8.0, POST request 2.0, GET request 2.0, movie/<id> title lookup 2.0.

## Residual notes (not blocking)

1. `_look_up` (My-requests titles, `/movie|tv/<id>`) is also TMDB-backed and keeps 2 s. A timeout there still counts toward the shared breaker, but the per-page title lookups are capped by TITLE_BUDGET, and the brief kept it on the page timeout. If cold-cache My-requests pages are seen opening the breaker, consider a neutral outcome for title-lookup timeouts rather than a longer wait.
2. An 8 s search holds a threadpool worker for up to 8 s. This is the same exposure Shelfarr accepted in #144.
3. Optional: tighten the breaker test so it also asserts that the dead search was attempted with SEARCH_TIMEOUT. Then it can detect the defect as well as guard against regression.
