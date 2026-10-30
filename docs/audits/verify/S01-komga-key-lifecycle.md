# S-01 Komga key lifecycle: independent verification

- Branch: `feat/komga-key-lifecycle` (worktree `avrana.wt-s01-keys`), 67cc2a9, 1463276, 2404dde, f6a8ae9 on top of
  origin/main 873ef80. Baseline for comparison: `avrana` (main, read-only).
- Verifier: independent agent, 2026-10-30. Nothing on the live host, live Authentik or live Komga was touched. All
  probes used synthetic data and the in-process fake Komga. No token or key value is printed here.
- Probe scripts (scratch, not committed):
  `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-s01\`
  (`probe_s01.py`, `settings_probe2.py`, `offboard_probe.py`, `serve_comics.py`).

## Verdict: ACCEPT-with-notes

The security design is implemented as approved, and I found no REJECT-level defect. I probed every lock on the intake
and on Connect/Disconnect myself. The key and the password never appear in a log line, a response body, a response
header or a Komga URL. That includes a Komga 500, a socket timeout and a failure to file after a mint. The
Authentik sandbox question comes out in the branch's favour: expression policies run under plain `exec`, so
`import os` and `os.environ` work.

One MEDIUM finding has to be fixed before the owner applies phase 2. As written, the runbook would leave the
enrollment stage silently disabled. The other findings are LOW or informational.

## Findings, ranked

### MEDIUM-1: the runbook sends the intake token to an env file that authentik-server never reads

`docs/runbooks/komga-key-lifecycle.md`, step 2.1: "in the `.env` the Authentik compose already reads for
`AVRANA_KOMGA_ADMIN_PASSWORD`".

- `AVRANA_KOMGA_ADMIN_PASSWORD` lives in `services/authentik/blueprints.env`, not `.env`.
  - `services/authentik/blueprints.env.example` lists it.
  - `docs/DECISIONS.md` line 38 and `docs/DEPLOYMENT.md` line 38 both say "loaded by the worker only".
- In `services/authentik/docker-compose.yml`, `server` has `env_file: [.env]` and `worker` has
  `env_file: [.env, blueprints.env]`.
- The new policy reads `os.environ` at run time. Flow policies run in the **server** process, so a token placed
  beside `AVRANA_KOMGA_ADMIN_PASSWORD` is invisible to it.
- Result: every enrollment logs `AVRANA_HOME_KEY_INTAKE_TOKEN not set, skipping`. This fails safe (enrollment still
  succeeds), but the phase 3 test would fail for a reason the runbook does not explain.
- Fix:
  - Name `services/authentik/.env` (the server's `env_file`) explicitly.
  - Say that putting it in `blueprints.env` alone does not work.
  - Add the new secret's location (`secrets/home_key_intake_token`; `AVRANA_HOME_KEY_INTAKE_TOKEN` in
    `services/authentik/.env`) to `docs/SECRETS.md`, which the branch leaves untouched.
- Context: this runtime-env approach differs from the repo convention (`!Env`/`!Format` resolved by the worker at
  apply time). The ADR does justify it: the same text can be pasted into the admin UI, and the token is never in the
  policy row.
- Probe: `grep -n env_file services/authentik/docker-compose.yml`; `grep -n "^[A-Z_]*=" services/authentik/blueprints.env.example`
  (names only).

### LOW-2: 411/413 on the intake prefix give away that the intake exists, before the peer/header check runs

`HygieneMiddleware` answers 411/413 for any PUT under `put_prefix` before the app runs. The peer-CIDR and
proxy-header checks are in the route handler, after that.

- Probe (`probe_s01.py::Intake.test_outside_peer_size_oracle`): from an outside peer, with `X-authentik-username` set:
  - PUT 600 B to `/internal/komga-key/<64hex>` → **413**.
  - The same PUT to `/internal/other/<64hex>` → **501**.
- Anyone on the public path can therefore tell whether `HOME_KEY_INTAKE_TOKEN` is set. They learn nothing else: the
  token, the subject rule and Komga's answers stay hidden, and the code is public anyway.
- Fix, either of:
  - In the middleware, answer 501 for an intake PUT that carries an `X-authentik-*`/`X-Forwarded-*`/`Forwarded`
    header or comes from a peer outside the CIDR, before the size checks.
  - Answer 501 instead of 411/413 on that prefix.

### LOW-3: the 403 subject rule is a consistency check, not a security control

`source` is chosen by the caller, so anyone holding the intake token passes `KeyIntake.allowed` by sending
`source=enrollment`. The subject never decides where a key is filed: `owner_of(key)` does.

- Probes (`probe_s01.py::Intake.test_subject_rules_and_cross_member`, `BoundSubject.test_bound_both_sources_and_mismatch`):
  - Unknown subject with `connect` → 403.
  - Unknown subject with `enrollment` → 204.
  - Subject `0`×64 carrying alice's key → filed under alice.
  - Subject bound to alice carrying bob's key with `source=connect` → filed under **bob**; alice's entry untouched.
- Cross-member injection: not possible. To write to member X's slot, a token holder needs a key that already opens
  X's Komga account, and with that key they have X's comics access anyway. They cannot put a key for account A under
  member B, because filing always uses the email of the account the key opens.
- Komga account emails are unique, and Home looks keys up by the Authentik email, so the mapping is only as good as
  "Komga email == Authentik email". `avrana-komga-create` sets the Komga email that way.
- Recommendation: say in the ADR/contract that the 403 only catches misdirected calls and that the token is the
  control. No code change needed.

### LOW-4: edge cases in the enrollment policy

`services/authentik/blueprints/avrana-enrollment.yaml`, `avrana-komga-key-mint`:

- **Lost response.** If Home files the key but the PUT's response is lost (a read timeout), the `finally` deletes the
  key in Komga. Home then holds a dead key and shows "Connected". The member would have to Disconnect and then
  Connect.
  - Safer: on an exception after the PUT was sent, do not delete. Or have Home treat a 401 from the member's key as
    "not connected".
- **Run time.** The worst case is about 60 s inside the member's enrollment submit, on top of `avrana-komga-create`'s
  own calls: 3 × 10 s GET + 2 s sleep, then 10 s each for POST, PUT and the cleanup DELETE.
  - In inline mode Authentik's 30 s per-binding timeout does not apply (`join` on a process that never started), so
    the request simply blocks.
  - Suggest a 5 s timeout per call.
- **Return values.** Every path returns True. An exception escaping before the `try` is very unlikely: it would need
  `plan.context["groups"]` to hold non-Group objects. Even then it would only give `failure_result` (False) for this
  one policy. The binding's mode is the default **Any**, and `jellyfin-create` and `komga-create` both return True, so
  the login stage still runs. Enrollment cannot be blocked.

### LOW-5: the owner tool writes the keys file without the cross-process lock

`member_keys.py` now says every write takes `file_lock(<file>)`. `services/avrana-home/tools/komga_member_keys.py`
(lines 157-174) still reads, then writes with `os.replace` and no lock. If the owner runs `--remove` while an intake
or Connect write is in flight, one of the two updates can be lost. The tool is legacy, and its password-resetting
modes are slated for deletion, but the runbook keeps `--list`/`--remove`.

- Fix: wrap the tool's write in `identity_bindings.file_lock`, or retire it as Phase 4 suggests.
- Probe: `grep -n "file_lock\|os.replace" services/avrana-home/tools/komga_member_keys.py`.

### LOW-6: offboarding's "Komga unreachable" sentence may point the owner at a screen that cannot do the job

`scripts/offboard.py` `act_komga_key` says "delete the member's avrana-home key in Komga (Users) by hand". The branch's
own reading of Komga's source says keys are self-service only: there is no admin route for another user's keys. The
owner probably cannot delete a member's key from Komga's Users screen. The realistic action is to delete or disable
the Komga user, or have the member do it.

- I have not checked this against the deployed Komga UI.
- Me → Comics' `disconnected_here` text is aimed at the member and is fine.
- Probe (`offboard_probe.py`):
  - Dry run: file unchanged, no Komga call.
  - Apply with Komga raising: the entry is dropped, the message says to finish by hand, and the key is not printed.

### INFO

- **Authentik expression sandbox.**
  - `authentik/lib/expression/evaluator.py` (main) runs `exec(ast_obj, self._globals, _locals)`. `_globals` sets no
    `__builtins__`, so builtins and `__import__` are unrestricted. The code comment says the trust model is "these
    policies can only be edited by admins".
  - The repo's live policies already `import base64`. `os.environ` is therefore readable.
  - The docs pages (customize/policies/expression, property-mappings/expression) do not mention imports or the
    environment either way. They document `ak_logger` and `requests` (a requests **Session**; `requests.get(...,
    auth=...)` works on it).
- **Policy order on one binding.**
  - docs.goauthentik.io/customize/policies/bindings: "Bindings are evaluated in ascending order". Default engine mode
    is Any; default per-binding timeout 30 s.
  - Source, `authentik/policies/engine.py`: bindings are ordered with `.order_by("order")`. Then
    `if not CURRENT_PROCESS._config.get("daemon"): task.run() else: task.start()`. Outside a daemon process they run
    inline, one after another, in order, so `komga-create` (1) finishes before `key-mint` (2). Inside a daemon process
    they run as parallel subprocesses; the two retries of a refused sign-in only partly cover that case.
  - Policy results are cached per binding + session + user (`process.py::cache_key`), so one enrollment cannot serve
    another a cached result.
- **The blueprint change is strictly additive.** It adds one expression policy entry and one `policybinding` (target
  `binding-user-login`, order 2). No existing stage, binding or attribute changed (`git diff 873ef80..f6a8ae9 --
  services/authentik/blueprints/avrana-enrollment.yaml`: additions only).
- **CI.**
  - `.github/workflows/enrollment-policy.yml` triggers on the blueprint and `tests/authentik_enrollment_live.py`. It
    runs the new real-Authentik checks: the policy is bound at order 2, and the policy test passes with no plan.
  - `tests/test_enrollment_komga_key.py` is not in that workflow. `tests/run_offline.py` discovers it, and
    `offline-tests.yml` runs that with `AVRANA_REQUIRE_YAML=1`, so it is covered.
- **Komga API.** The `/api/v2/users/me/api-keys` routes come from Komga master source, not from the deployed image
  (the implementer says so). The fake Komga copies that reading. Treat the first live enrollment test (runbook
  step 3) as the real check.
- **test_web_home flake.** `test_a_member_cannot_select_a_library_they_cannot_use` failed once in a whole-module run.
  It passed on its own, both on this branch and on main 873ef80. Not caused by this diff.

## What I checked, and how

1. **Diff hygiene.**
   - `git diff 873ef80..f6a8ae9 --stat` and the same with `--ignore-cr-at-eol` give identical totals: 28 files,
     +2011/−34. No file was rewritten wholesale and line endings are unchanged.
   - Only one existing test file changed (`tests/test_komga_member_reading.py`), and it only **adds** assertions.
   - `identity_bindings.py` adds only the read-only `knows_digest`. `file_lock` already existed.
   - `logsafe.py` adds the field `ref`, which is still bound by the 64-char identifier regex.
   - `middleware.py` adds a PUT branch reached only under `put_prefix`, which is empty unless the intake is on. Every
     other PUT or route behaves as before (also checked by `test_other_methods_and_paths_stay_501`).
2. **Intake** (`probe_s01.py::Intake` plus the implementer's `test_web_komga_keys`, through the TestClient with
   `PeerOverride`).
   - Token check: `hmac.compare_digest` (`intake.token_ok`). Wrong token → 401. Lower-case `bearer` → 401. Two
     `Authorization` headers → 401. Wrong token from outside → 501, so no token oracle.
   - Settings (`settings_probe2.py`, `probe_s01.py --settings`):
     - 31-character token refused; 32 accepted.
     - Missing CIDR refused.
     - `8.8.8.0/24`, `0.0.0.0/0` and `::/0` refused.
     - CIDR without a token refused.
   - Peer and headers: a peer outside the CIDR → 501. Each of `X-Authentik-Uid`, `x-forwarded-proto`,
     `X-Forwarded-Host`, `FORWARDED` and `X_Forwarded_For` → 501.
   - `serve.py` runs uvicorn with `proxy_headers=False`, so `client.host` is the real TCP peer.
   - Body size: exactly 513 B → 413, and the fake Komga recorded no call. 512 B → 204.
   - Subject rules: see LOW-3. The same key again → 204 with no write (mtime unchanged). A different key → replaced.
   - Four concurrent PUTs (2 accounts × 2) → all 204, both entries present. `put`/`remove` hold `self._lock` +
     `file_lock` and re-read the file under the lock.
   - Leaks: across these probes, neither key value, the token nor the subject appeared in captured logs, response
     bodies or response headers.
3. **Connect comics** (`probe_s01.py::Connect`, which subclasses the implementer's tests).
   - The password never appeared in logs, bodies, headers or any Komga request path on: Komga 500 on the key list, a
     socket timeout, or `/users/me` returning 500/503 after a successful mint. All of these → `komga_unavailable`.
   - A password sent in the query string is ignored (`no_password`).
   - Rate limit: the 6th try → `busy`, and Komga saw only 5 sign-ins.
   - A cross-site post → 403 with no Komga call. A bad form token → `expired`.
   - A filing failure after the mint deletes the new key: the fake Komga's call log has the DELETE, and only the
     member's own "phone" key remains.
   - The page is hidden without `HOME_KOMGA_CONNECT` or without the Comics group (404/501).
   - Disconnect with Komga down drops the key locally and shows the "delete the key named avrana-home" sentence.
   - The template uses only existing classes (`kgroup`, `kgroup-h`, `note`, `kbtn-quiet`, `srch`, `ask`, `ask-field`,
     `data-once`, `data-busy`) and the existing `comic` glyph. No CSS or font changes.
   - Rendered in a real browser at 320 px (dev server on 127.0.0.1:8496, stopped afterwards): `scrollWidth` 320, no
     element past the right edge, font Plus Jakarta Sans.
4. **Blueprint.** See INFO and LOW-4. `python -B -m unittest tests.test_enrollment_komga_key` (system Python with
   PyYAML): 7 OK. `tests.test_enrollment_username_available` OK.
5. **Phase 4** (`settings_probe2.py`).
   - Live-like `HOME_PROVISION_ACCOUNTS=jellyfin,audiobookshelf` with no legacy flag: settings load, and the
     provisioner has only Jellyfin and ABS creators.
   - `komga` without the flag: refused with "HOME_PROVISION_ACCOUNTS=komga is retired (S-01: …)".
   - The flag without `komga`: refused.
   - `KOMGA_ADMIN_TOKEN` without `komga`: refused.
   - `komga` with the flag: the Komga creator is built.
   - Intake + Connect on the live-like config: loads.
   - Compose: running `scripts/deploy-home-beta.sh`'s `active()` over the repo compose at 873ef80 and at f6a8ae9 gives
     identical active lines. Every line the branch added is commented, so the live file (admin-token line commented,
     the secret still listed) still passes `comm -23`.
6. **Docs.**
   - `tests.test_member_content` OK; `tests.test_home_static_export` OK (181 pages).
   - The ADR is in `docs/DECISIONS.md` ("Owner decision, 2026-10-30").
   - The runbook does not apply the whole repo blueprint (it says explicitly not to), and it has a rollback for both
     Authentik and Home.
   - Problems: the wrong env file (MEDIUM-1) and the offboard sentence (LOW-6).
7. **Test runs** (venv Python, one module at a time).
   - Adapter tier:
     - `test_komga_key_lifecycle`: 26 OK
     - `test_komga_member_reading`: 44 OK
     - `test_provision`: 22 OK
     - `test_identity_bindings`: 25 OK
   - Web tier:
     - `test_web_komga_keys`: 25 OK
     - `test_web_pilot`: 28 OK
     - `test_web_me_security`: 27 OK
     - `test_web_provision`: 3 OK
     - `test_settings`: 16 OK
     - `test_account_provisioning`: 8 OK
     - `test_viewmodel_logsafe`: 14 OK
     - `test_web_home`: 1 flaky failure (see INFO)
     - `test_web_me_profile`: import error (Pillow missing, known Windows failure)
   - My probes: 22 OK.
   - `python -B tests/run_offline.py` (venv, so no PyYAML and 41 repo skips):
     - Repository: 458 OK.
     - kindle, backups, assistant: all OK.
     - Home adapters: 1056 OK (6 skipped).
     - Home web: 1064 tests, with only the two known Windows failures: `test_web_me_profile` (Pillow import) and
       `test_runner` (skip count 6 against a regex that expects `[01]`).
     - This matches the implementer's claims exactly, and `test_web_home` passed in this run.

## Not checked

- Anything live: the deployed Komga's API version and behaviour, the live Authentik version's evaluator and daemon
  mode, whether `authentik_home_beta` really holds only authentik-server and Home, and the live blueprint's
  binding ids.
- A real Authentik run of the new policy. The CI workflow would do that on a PR; I did not run Docker.
- Komga's UI for deleting another user's API key (LOW-6).

## Phase 5 re-check (2026-10-30)

- **Delta reviewed:** `git diff c7b64ed..e23e95b`.
  - The commits were re-trailered, so the SHAs changed: b163df0, 1d1101e, 60838d4, c7b64ed, then e23e95b.
  - 15 files, +167/−40. The plain and `--ignore-cr-at-eol` stats are identical, so line endings are unchanged.
  - No existing assertion was weakened. The only test that changed meaning is the offboard test, which now expects
    the stricter keep-on-failure behaviour.
- **Scope:** read-only, apart from this section and scratch files. No stack was started this time.

| # | Original note | Result | Probe / evidence |
|---|---|---|---|
| 1 | MEDIUM-1: runbook names the wrong env file | **Fixed** | Runbook step 2.1 now names `/home/cody/avrana/services/authentik/.env` and explicitly forbids `blueprints.env` (worker only). The troubleshooting line maps `not set` to that cause. `docs/SECRETS.md` gains a row for `AVRANA_HOME_KEY_INTAKE_TOKEN` in `services/authentik/.env` and a row for `services/avrana-home/secrets/home_key_intake_token`, with rotation guidance. |
| 2 | LOW-4: policy timeouts and lost answer | **Fixed** | Every `requests` call uses `timeout=5` (comment gives a 32 s worst case). After a successful mint, the key is deleted again only after a definite non-2xx from Home, or after a failure before the PUT was sent. If the PUT raises, `made` is cleared, the warning logs `state="unknown"` and the policy returns True with no cleanup DELETE. Any 2xx counts as filed. Tests: `test_a_lost_answer_from_home_leaves_the_key_in_komga_and_logs_unknown` (TimeoutError, ConnectionError; asserts the last call is the PUT and the log carries `state: unknown`), `test_any_2xx_from_home_counts_as_filed`, and a timeout assertion `{5}`. The log-secret test also covers a PUT that raises with the key in the message. |
| 3 | LOW-2: the intake could be detected from outside | **Fixed** | `HygieneMiddleware` now takes `put_guard` (peer inside `HOME_INTERNAL_CIDR` and no outpost or proxy header) and applies the 411/413 rules only after it passes. Otherwise the request falls through to the generic 501. Re-ran my probe (`scratchpad/verify-s01/probe_p5.py`): PUT 600 B to `/internal/komga-key/<64hex>` against `/internal/other/<64hex>` gave **501 for both, with identical body and headers (Date excluded)** in all four cases: outside with `X-authentik-username`, outside with nothing, inside with `X-Forwarded-For`, inside with `Forwarded`. Outside chunked with no length: 501. Inside, clean: still 413. The route handler still re-checks peer and headers, so this is defence in depth. Implementer test: `test_a_size_probe_from_outside_cannot_tell_the_intake_exists`. |
| 4 | LOW-3: subject rule wording | **Fixed** | The ADR row "The intake token is the security control" and a new "Security model" paragraph in ADAPTER-CONTRACT §15.1 say the subject/`source` rule is a consistency check only. Both cite `IntakeRuleTests.test_a_key_is_filed_under_its_own_account_whatever_the_subject_says`, which exists. **Mutation check:** on a scratch `git archive` copy I changed `KeyIntake._file` to file under the member the subject is bound to (`self._store.put("alice@example.com" if self._known(subject) else email, ...)`). The cited test then **FAILS**. The two other errors in that run are scratch-copy artifacts (`HOME_CATALOGUE_PATH`: the portal was not archived), not caused by the mutation. |
| 5 | LOW-5: owner tool wrote without the lock | **Fixed** | `tools/komga_member_keys.py` now files and drops through `MemberKeyStore.put`/`remove` (`file_key`/`drop_key`), which take `file_lock`, re-read the file under the lock and change one entry. The whole-file `save_keys` calls in `run()` are gone. Test: `Tool.test_writes_take_the_shared_lock_and_keep_entries_another_writer_added` simulates Home writing carol in the middle of a run. carol survives both a key and a remove, and `.lock` exists. With the old whole-map save, carol would have been lost. |
| 6 | LOW-6: offboarding message and order | **Fixed** | `act_komga_key` now revokes first (`revoke(key, store.komga_id(email))`) and removes the entry only after that succeeds. If Komga is unreachable: "komga key NOT revoked … Home's entry is kept. Re-run offboard.py when Komga is back, or the member deletes the avrana-home key under their own Komga account". If the revoke succeeds but the remove fails, a separate "check by hand" line. The dry run is unchanged (no write, no Komga call). `offboarding.md` row updated; its `offboard.py:367-401` citation matches the function. Test `test_komga_down_keeps_the_entry_so_a_rerun_can_revoke_it` checks that the entry is kept, "Users" is not mentioned, the key is not printed, and a re-run with Komga back revokes and drops it. |

### Test runs on e23e95b

- Adapter tier (venv Python):
  - `test_komga_key_lifecycle`: 27 OK
  - `test_komga_member_reading`: 45 OK
- Web tier (venv Python): `test_web_komga_keys`: 26 OK
- Repo tests (venv Python):
  - `tests.test_offboard_retire`: 4 OK
  - `tests.test_member_content`: 41 OK
- System Python with PyYAML: `tests.test_enrollment_komga_key` + `tests.test_enrollment_username_available`: 17 OK

### Residual (informational, not blocking)

- Lost answer from Home: if Home never actually filed the key, a stray `avrana-home` key stays in the member's Komga
  account until their next Connect comics, which deletes older `avrana-home` keys. The runbook documents this. It is
  the right trade-off against filing a dead key.
- Unchanged from the first pass: none of this is verified live. That covers the deployed Komga's key API, the live
  Authentik process mode and network membership, and a real-Authentik run of the policy.

### Final verdict: ACCEPT

All six notes are resolved, with tests that would catch a regression. Mutation-checked for note 4; the
before/after behaviour is shown for notes 3, 5 and 6. Nothing blocks merge from the verification side. The owner
still has to apply phases 1-3 by hand, per the runbook.
