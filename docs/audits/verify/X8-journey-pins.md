# X8 - Independent verification: RC2 journey pins (T-05, T-07, T-09)

- Branch `test/rc2-journey-pins`, worktree `avrana.wt-rc2-t05`, commits 59d9699, 418975b, 1d9f6ef, 9d507a6 on baseline 2cb228f.
- Verified 2026-10-29 by an independent agent. Nothing in the worktree was edited, committed or pushed. No ssh, no Docker.

## Verdict: ACCEPT, with follow-ups

The three test groups use the real HTTP routes, and each one fails under the mutation it is meant to catch. One assertion block in T-09 never runs on its own (follow-up 1). The other notes are minor.

## 1. Scope and counts

`git diff --stat 2cb228f..HEAD` shows changes to three files, all under `services/avrana-home/webtests/`. No application code changed.

| Module | Claimed | Observed |
|---|---|---|
| test_comic_requests | 14/0 | 14 OK |
| test_my_requests | 21/0 | 21 OK |
| test_web_quick_connect | 21/0 | 21 OK |
| test_web_identity_bindings | 13/0 | 13 OK |
| test_web_jwt_identity | 41/0 | 41 OK |

Each new test, or new test class, also passes when run alone. They do not depend on test order. The thread test passed 5 out of 5 repeated runs.

## 2. Mutation results

The `webtests` resolve paths from the repository root: `REPO/services/avrana-portal`, `tests/fixtures`, and the catalogue source. So the scratch copy is the whole tree, without `.git`, at `scratchpad/verify-x8/repo/`. Mutations were made only in `repo/services/avrana-home`. The runner is `scratchpad/verify-x8/mutate.py`, and each run's output is in `out-<name>.txt`.

| # | Mutation (scratch only) | Result | Caught by |
|---|---|---|---|
| a1 | comic POST: `blocked = None` (no double-tap guard) | 4 FAIL | sequential double-tap, two-thread double-tap, timeout-after-send (2nd tap), plus one existing test |
| a2 | `RequestGuard.check` split into check / sleep / record outside the lock | **survived** | n/a. This race cannot happen here: `check` runs synchronously on the event loop, so the sleep blocks the loop and no second request can run in between. The mutation is unrealistic, and this is not a gap in the tests. |
| a2b | check (peek) before `omnibus.create`, record **after** the await (realistic check-then-act) | FAIL | `test_double_tap_from_two_threads_sends_once`. The barrier plus the 0.2 s `post_delay` does force two requests to run at once. |
| a3 | `OmnibusRequests.create` retries once on any non-CREATED result | FAIL | `test_timeout_after_send_is_never_retried_and_lists_once` |
| b1 | Authorize 404 -> `unavailable` | FAIL | redirect map [authorize 404], refused-code-not-remembered |
| b2 | `me_tv.html` "unavailable" sentence echoes "(Jellyfin said 403)" | FAIL | no-leak test [authorize 403], [users timeout] |
| b3 | Authorize timeout -> silently retried once | FAIL | redirect map [authorize timeout] (2 approvals), unknown-wording test |
| b4 | 401 -> `unavailable` instead of `off` | FAIL | redirect map [authorize 401] |
| c1 | `IdentityBindings.check` returns OK for any `sub` | FAIL | warm-cache test, on all 14 GETs + POST /request/watch + POST /me/tv; existing cold tests also fail |
| c2 | warm bypass: a username that once passed skips the binding check | FAIL | warm-cache test, same paths. A2 got A1's full pages (about 120 KB, against the 5.5 KB signed-out page). The mock recorded `/UserItems/Resume`, `/Shows/NextUp`, ... for A2. |

## 3. Diff review

**T-05 (comics)**
- Every request goes over HTTP through the real route, signer, guard and `OmnibusRequests`. Only the transport is faked.
- The thread test does force the race (shown by a2b). Its final message check accepts either "You just asked" or "Asked for", which is weak. The test's real strength is `len(posts) == 1`.
- "My requests lists the issue once" (`mine.count("Owned Series") == 1`) holds by construction: `_series()` groups rows by `volumeId`, so even two stored rows would show once. The single write is actually proven by `posts == 1` and `stored == 1`, and those assertions are present.
- The second tap after a timeout is answered by the guard ("You just asked for Owned Series."). This only holds inside the 60 s `DOUBLE_TAP_WINDOW`. After that, a manual retap does write again. Omnibus is documented as not duplicating an issue, but no test pins that.
- The test asserts the UNAVAILABLE copy "could not be reached right now". 9d507a6 removed the expected-failure test that recorded this copy as a defect: it invites a retry and never says the request may have gone through. Removing it from CI is reasonable, but the finding must not be lost (follow-up 2).

**T-07 (Quick Connect)**
- All 8 upstream scripts go through the real `QuickConnect` and the POST /me/tv route. The fake raises statuses through the real `classify_status`.
- For `off` and `unavailable` there is no form on the page, so the token is issued directly from `app.state.form_tokens`. The POST still uses the real route.
- Each approval is counted once. The redirect test, the double-submit test and the refused-code test (2 approvals for 2 tries) are a good pair.
- The sentence test covers 6 of the 10 `TV_RESULTS`. `bad_code`, `not_eligible`, `busy` and `expired` are not part of the distinctness check. The existing tests pin the redirects for `bad_code`, `not_eligible` and `expired`, but not their sentences. `busy` has neither.
- The leak check looks for status digits and `false` only inside the status region. This is fine, because the page legitimately contains digits.

**T-09 (warm cache)**
- A1 warms every listed route over HTTP, and the warm responses are checked: 200s, the avatar bytes, the name, titles in home.json, the watch form.
- For A2, the check is byte equality with the signed-out answer: `(status, content)`. This is the strongest possible assertion, and it caught c1 and c2.
- Step 4 checks that the mock paths, approvals and Seerr calls are all empty.
- Step 6 checks the `identity_changed` log reason, and that A1 is unharmed afterwards.
- **Step 5 (no A1 marks in any A2 body) never runs on its own.** `bodies.append` comes after the step 3 assertion inside the `subTest`. Whenever a route differs from the signed-out answer, its body is never collected. Under the c2 probe (step 4 removed), step 5 inspected only `POST /signout` and passed. When step 3 passes, step 5 adds nothing. Step 3 already gives the guarantee, so this is a dead assertion, not a hole (follow-up 1).
- Avatar fixture: the WebP-shaped byte string is served exactly as stored. The A1 warm run asserts `content == photo`, and the A2 run must equal the signed-out 404 byte for byte. So the test does prove the avatar is not served to A2. PIL re-encoding is not part of this route.
- `/request/mine` is only probed for A1, because the fake Seerr serves no list. It is still compared byte for byte for A2.

## 4. Secrets grep

`git diff 2cb228f..HEAD | grep -i -E "token|secret|password"` matches only the following:
- form-token handling code
- a `"token"` field-name assertion
- `jwt_secret=SECRET`, imported from `test_web_jwt_identity.py`, where it is `SYNTHETIC-FIXTURE-SECRET-not-real-0123456789`

No real-looking secrets.

## Follow-ups (none block merge)

1. T-09: move `bodies.append(...)` before the step 3 assertion, or drop step 5. Either way the test code should match what it claims.
2. Track the removed T-05 finding as an owner question. Today the copy after a timeout says "could not be reached ... Try again later". It should say the request may already have gone through, as Quick Connect's `unknown` does. This affects all three request brokers.
3. T-07: add `bad_code`, `not_eligible`, `busy` and `expired` to `SENTENCES` so that all 10 results are checked for distinct copy. `busy` has no route-level test at all.
4. Optional: pin that Omnibus does not duplicate an issue when it is retapped after the 60 s double-tap window.
