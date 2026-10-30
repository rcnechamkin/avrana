# X4: independent verification of S-02 (Komga key provisioning hardening)

* Fix under review: branch `fix/rc2-komga-provision-hardening`, commit `29f98a0` on `2cb228f`
  (worktree `avrana.wt-rc2-s02`). Baseline: `avrana` at `2cb228f`.
* Verifier: independent agent, 2026-10-29. Nothing edited, committed, pushed or deployed. No ssh, Docker or real
  services.
* **Verdict: REJECT.** One required change, small. The fence itself works. But the commit splits
  `Provisioner._attempt`'s single critical section into two, which brings back a check-then-act race the baseline
  did not have: two concurrent requests from one member can both reset that member's password.

## 1. Probe results

Probe: `scratchpad/security/probe_komga_provision.py`, copied to `scratchpad/verify-x4/`. It takes the repo path as
its argument, so pointing it at a tree needed no edit. The unmodified probe CRASHES on the fix
(`ProvisionFailed: keys_file_unusable`) because it uses keys files that do not exist. That is the new refusal doing
its job, and it is correct. `probe_fix.py` is the same probe with the files created as `{}` beforehand, plus extra
checks. `edges.py` adds the edge and concurrency checks.

| Check | Baseline 2cb228f | Fix 29f98a0 |
|---|---|---|
| S-01: existing non-admin account's password PATCHed | True | True (unchanged, as required) |
| S-01: key filed | True | True |
| S-02: password replaced, then key step failed | True | True (the reset itself is S-01) |
| S-02: retried an hour later, password replaced again | **True** | **False** |
| S-02: logged | `failed:http_500` x2 | `failed:failed_after_reset` x1 |
| S-02: same process, 2 h later | 4 Komga calls | 0 calls, silent |
| S-02: after a restart (new store + Provisioner) | 5 calls, `provisioned` (re-reset) | 0 Komga calls, `failed:failed_after_reset` once, 1 cap slot |
| Keys file configured but absent | 5 calls, `provisioned` | 0 calls, `refused:keys_file_unusable` once, 0 cap slots |
| Keys file malformed | 5 calls, `provisioned` | 0 calls, `refused:keys_file_unusable` |
| S-03: two usernames, one e-mail, one key | True | True (unchanged) |
| PATCH times out (`unreachable`), 2 h | 2 PATCHes | 2 PATCHes (implementer's caveat, see section 3) |
| Key filing fails after reset AND sidecar unwritable | `failed:PermissionError` | `failed:failed_after_reset`. Blocked in memory. **1 PATCH after a restart** |
| **Race: two `_attempt`s interleaved between lock sections** | **1 PATCH, 1 cap slot** | **2 PATCHes, 2 cap slots, both `provisioned`** |

## 2. Diff review

The diff covers `provision.py`, `member_keys.py`, the 10 new tests, `ADAPTER-CONTRACT.md` section 15 and the
runbook.

**Required: concurrency regression in `Provisioner._attempt`.** On the baseline, one `with self._lock:` block checks
`_busy` and `_last` AND sets `_busy`, `_last` and `_made`. On the fix, the first block checks `_terminal`, `_busy`,
`_last` and runs `preflight`, then releases the lock. The second block takes the cap slot and sets `_busy` and
`_last` without re-checking them. `provision` runs through `run_in_threadpool` (`app/main.py:1201`), so two page
loads from the same member, or a reload, can both get past the first block. `edges.py` forces that interleaving
with a stepping lock. The fix then performs two attempts. The baseline performs one.

With a real Komga there are three likely outcomes:
* (a) The second PATCH invalidates the first attempt's password. Attempt A gets a 401 and is wrongly marked
  `failed_after_reset`, terminal, and written to the sidecar.
* (b) Both attempts sign in. B's `_new_key` deletes A's `avrana-home` key, then A's `put` lands last. A REVOKED key
  is filed, the member's Continue row fails, and the `exists` check means Home never repairs it.
* (c) For Jellyfin and Audiobookshelf, a double create plus an extra cap slot.

The window is small: between releasing the lock and taking it again. But this is the exact harm S-02 is meant to
prevent, and the baseline closed it. Fix: keep one critical section. Inside it, on a preflight refusal set
`_last[key]` and record the reason, otherwise do the cap and `_busy` bookkeeping. After the block, return
`_done(refused, reason)`. Alternatively, re-check `_terminal`, `_busy` and `_last` at the top of the second block.
Add a test, for example the stepping-lock interleaving in `scratchpad/verify-x4/edges.py`.

**Required: runbook and contract correction.** The runbook says to "delete the member's line from the
`.reset_failed` file to let Home try again". That does not work without a restart: `MemberKeyStore._failed` (memory)
is checked before the file, and `Provisioner._terminal` holds the member until restart. Either say "then restart
Home", or make `reset_failed` consult the file only. The second option weakens the unwritable-sidecar case.
Filing a key through the owner tool does end the block without a restart, because `exists` is checked first. That
part of the doc is correct.

**Checked and acceptable:**
* **Sidecar location.** It is `<keys file>.reset_failed`, which is `/var/lib/avrana-home/komga_member_keys.reset_failed`,
  inside `./state`. That is the only writable mount: `read_only: true` with `./state` uid 1000, mode 0700, per the
  `docker-compose.beta-live.yml` comment. It is written with `open(..., "a")`: an append, not atomic, but a
  one-line append is fine for this format.
* **Sidecar permissions.** The mode is umask-default (typically 0644), not 0600. The contents are e-mail addresses
  only, never credentials, and the 0700 directory protects them. Optional follow-up: create the file 0600 for
  consistency with the keys file.
* **Sidecar unwritable.** This fails safe for the process: the member is blocked in memory, the request does not
  crash, and the reason is logged. After a restart the member gets ONE more reset. This needs both the keys write
  and the sidecar write to fail on the same volume, and in that case `preflight` would usually refuse anyway. Accept.
* **Sidecar unreadable.** If `reset_failed` hits a permission error it returns False, so this fails open. That is
  minor, because the same volume holds the keys file that `preflight` must read. Optional follow-up: treat any
  `OSError` other than `FileNotFoundError` as "blocked".
* **Owner tool.** `tools/komga_member_keys.py` is untouched. It does not read the sidecar, and `--missing` correctly
  still lists blocked members, who do need repair. Its `save_keys` uses mkstemp, chmod 0600 and `os.replace`, the
  same as `write_keys`.
* **`keys_file_unusable` and a concurrent `put`.** Both writers replace the file atomically with `os.replace`. A
  reader sees either the old or the new inode, so `isfile` and the parse cannot catch a half-written file on Linux.
  Even if it did happen, the result is a refusal: no Komga request, retried an hour later. That is the safe side.
* **Cap and restart.** A sidecar-blocked member costs one cap slot and logs one `failed_after_reset` line per
  restart, then goes quiet. The contract's "logged once" holds per process. A preflight refusal costs no cap slot
  and logs once per member per hour (it sets `_last`). A restart within the hour cannot re-reset a member who was
  marked, because the sidecar is consulted before any Komga call.
* **Read adapters.** The read adapters, `MEMBER_ROUTES` and the shared-account allow-list are unchanged. No adapter
  file is in the diff. `MemberKeyStore.get`, `_refresh` and `read_keys` are unchanged, so an absent file still means
  "no keys". The test `test_the_read_adapters_still_treat_an_absent_file_as_no_keys` covers this.
* **Logging.** There are no new log calls. Every outcome goes through `Provisioner._done(service, state, reason)` with
  fixed strings (`failed_after_reset`, `keys_file_unusable`). The exception is raised `from None`, and no e-mail,
  username or password reaches a log line. `logsafe.log_event` is the sink, as before.
* **The `terminal` flag.** It defaults to False. Only `KomgaKeyCreator` sets it, so it has no effect on
  `JellyfinCreator` or `AudiobookshelfCreator`. `keys_file_unusable` joins the "refused" list and only Komga raises it.
* **S-01 untouched.** The PATCH is still made for existing non-admin accounts. The admin key's own-account path
  (`_new_key(self._send)`, then `put`) is unfenced and unchanged. The brand-new-account path is unfenced, which is
  correct: that password was never anyone's.

## 3. Implementer's caveat: a PATCH that times out

`http_sender` turns a timeout into `ProvisionFailed("unreachable")`, raised by the PATCH itself, which is outside
the fence. If Komga applied the PATCH before the timeout, the member has lost their password and has no key, and an
hour later Home resets again (reproduced: 2 PATCHes in 2 h).

Judgement: **acceptable as a documented residual, not a blocker.** The member's original password is already gone
after the first apply, so a re-reset loses nothing more unless someone set a new password in the meantime. The retry
is also the only automatic path to the desired end state, a key on file. A timeout after Komga applied the change on
a local-network PATCH is rare.

Optional follow-up (P3): treat a non-HTTP failure of the PATCH (`unreachable`, `malformed`) as terminal under a
distinct reason, for example `reset_unknown`, while keeping a clean 4xx retryable. Add one sentence to section 15
naming this residual.

## 4. Test runs (fix worktree, `python -B -m unittest discover`)

| Module | Result |
|---|---|
| tests/test_provision | 22 OK |
| tests/test_komga_member_reading | 43 OK |
| tests/test_komga | 54 OK |
| tests/test_resilience | 10 OK |
| tests/test_phase1 | 48 OK |
| webtests/test_web_provision | 3 OK |
| webtests/test_account_provisioning | 8 OK |
| webtests/test_web_komga | 14 OK |
| webtests/test_web_home | 21 OK |
| webtests/test_web_komga_books | 5 OK (real runs, 5 ms) |

The implementer's six counts are confirmed.

**New tests against the baseline.** The fix's `test_komga_member_reading.py` was run against a `git archive` of
`2cb228f` in a scratch directory. 6 of the 10 new `HomeMakesKeys` tests fail there, including both headline tests:
`..._not_retried_and_logs_its_own_reason` and `..._missing_keys_file_refuses_before_any_komga_request`. The same
holds for `_block_survives_a_restart`, `_filing_failure_after_the_reset_is_also_terminal`,
`_does_not_use_up_the_hourly_cap` and `_unreadable_keys_file_refuses_too`. The other 4 pass on the baseline because
they are regression guards: the before-reset failure is retryable, the admin's own account is not a reset failure,
an empty file is a normal start, and the read adapters still treat an absent file as no keys. That is the right
split.

Three `SettingsFile` tests also fail in the scratch copy with the baseline's OWN test file (HOME_CATALOGUE_PATH:
the portal tables are absent from the archive). That is an environmental artifact, not related to this change. No
new test covers concurrency.

## 5. Deploy impact (for the PR body, once the required change lands)

With `komga` in `HOME_PROVISION_ACCOUNTS`, Home refuses to make Komga keys until the configured keys file EXISTS and
parses. It logs `provision service=komga state=refused reason=keys_file_unusable`, sends no Komga request and uses
no cap slot. On the live host the file exists today (125 bytes), so nothing changes there. If a key step fails after
a password reset, a `komga_member_keys.reset_failed` sidecar (one e-mail per line) appears in `state/`. Nothing else
changes: no new environment variable, mount, image dependency or read-path behaviour. Repairs still go through
`tools/komga_member_keys.py --member`.

## 6. Required before ACCEPT

1. Restore a single critical section in `Provisioner._attempt`, or re-check `_terminal`, `_busy` and `_last` before
   taking the cap slot. Add a concurrency test. Re-run `scratchpad/verify-x4/edges.py`: the race check must show 1
   PATCH.
2. Correct the runbook (and section 15 if it repeats the claim): removing a `.reset_failed` line takes effect only
   after a Home restart.

Optional: PATCH-timeout residual (section 3), sidecar mode 0600, fail closed on an unreadable sidecar.

## Re-verification (e1ee2a6 on 29f98a0)

**Verdict: ACCEPT.** Both required changes from section 6 have landed. One test-quality follow-up is recommended
but does not block.

**Lock scope (`Provisioner._attempt`).** One `with self._lock:` hold now covers all of the following:
* the `_terminal`, `_busy` and hourly-retry checks;
* the preflight;
* the cap check;
* the slot claim (`_busy`, `_last`, `_made`).

No Komga or other network I/O runs inside the lock. `create()` and every `_done()` log call run after it is
released.

Holding the lock over the preflight is acceptable:
* `MemberKeyStore.usable()` costs one `stat` plus one read and parse of a JSON file of at most 500 entries, on the
  local `state/` volume.
* It runs only for a member who is already a Komga candidate and is past the busy and hourly gates.
* It serialises only other provisioning decisions, never page reads.

**No new deadlock path.** `usable()` takes no lock. `MemberKeyStore._lock` is never taken while
`Provisioner._lock` is held, and the store never calls back into the Provisioner, so there is no lock ordering.

**Probes against the worktree at e1ee2a6:**
* `edges.py` race check: **1 PATCH, 1 cap slot, one `provisioned`**. At 29f98a0 the same check gave 2 PATCHes.
  The stepping lock forces the interleaving, so this check is deterministic for both versions.
* PATCH timeout: 2 resets in 2 h. This is now recorded as an accepted risk in ADAPTER-CONTRACT section 15.
* Sidecar unwritable: 1 reset after a restart, unchanged and accepted.
* `probe_fix.py`: identical to section 1. S-02 is fenced, absent or malformed files are refused with no Komga
  call, S-01 is unchanged and S-03 is unchanged.

**Docs.**
* The runbook now says that removing a `.reset_failed` line requires a Home restart, and that a key in the keys
  file ends the block at once. Both statements are correct.
* Section 15 now records the PATCH-timeout re-reset as an accepted risk. Its first line is over-long, which is
  cosmetic only.

**Suites (fix worktree):**

| Module | Result |
|---|---|
| test_provision | 22 OK |
| test_komga_member_reading | 44 OK (+1 new) |
| test_komga | 54 OK |
| webtests/test_web_provision | 3 OK |
| webtests/test_account_provisioning | 8 OK |
| webtests/test_web_komga | 14 OK |

**The new test, `test_two_page_loads_of_one_member_make_exactly_one_reset`.**
* On e1ee2a6 it passed 30 of 30 runs. Its pass is deterministic: whichever thread takes the lock first claims the
  slot, and the other sees `_busy`.
* Run against the 29f98a0 code (e1ee2a6's test file over a `git archive` of 29f98a0), it **failed only 7 of 30
  runs**. As a regression guard it is therefore weak, which matches the implementer's own admission.

Keep it, but make it deterministic (recommended follow-up, about 15 lines). Replace the Barrier clock with a lock
proxy that parks the first thread at its first lock release until the second thread has completed one locked
section. The steps:

1. Build the Provisioner with `clock=lambda: 0.0`. Keep `self.fake.send` holding the first PATCH open, as now.
2. Install the proxy with `real = prov._lock; prov._lock = Stepper()`. `Stepper.__enter__` calls `real.acquire()`.
   `Stepper.__exit__` calls `real.release()` and then:
   * if the current thread is named "A" and this is its first exit, set `a_left` and wait up to 5 s on `b_done`;
   * if the current thread is named "B" and this is its first exit, set `b_done`.
3. Start `Thread(name="A", target=prov.provision, ...)`. Start
   `Thread(name="B", target=lambda: (a_left.wait(5), prov.provision(...)))`.
4. Assert one reset and `["provisioned"]`, as now.

Expected results:
* On e1ee2a6, A's first exit comes after the claim. B finds `_busy` and returns, so there is 1 reset.
* On the two-section code, A's first exit comes before the claim. B passes the checks and both threads claim, so
  there are 2 resets every time.

This is the `SteppingLock` in `scratchpad/verify-x4/edges.py`. Keep the 5 s timeouts so that a regression fails
the test rather than hanging it.

**Deploy impact:** unchanged from section 5.
