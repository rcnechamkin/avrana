# Media 2.0 RC2: security and reliability audit (2026-10-29)

Read-only audit for the pre-closed-beta quality sprint. Baseline: `origin/main` **2cb228f** (the revision the live
beta runs, per [MEDIA-2.0-RC2-STATE.md](../release/MEDIA-2.0-RC2-STATE.md)). Nothing was edited in the repository,
nothing was merged, deployed or applied, no host was contacted, no live configuration, member data or credential
was read. Every probe used synthetic fixtures on loopback. Evidence tags: **[offline]** test or probe run here,
**[trace]** read in code (file:line), **[recorded]** taken from an earlier report, **[not run]**.

## IMMEDIATE

**No CONFIRMED P0.** No cross-member disclosure, broken authorization or unrecoverable account access was found in
2cb228f. One finding is **beta-blocking** and needs an owner decision before members are invited:
**S-01**: Home's automatic Komga key provisioning (live, `komga` in `HOME_PROVISION_ACCOUNTS`) replaces the Komga
password that the enrollment blueprint set on purpose so comic reader apps (OPDS, HTTP Basic) work. A new comics
member who sets up a reader app and then opens Home loses that app's sign-in, silently.

---

## (a) Method and what was executed

1. Read: AGENTS.md, docs/SECURITY.md, HOME-APP.md (identity, real mode), ADAPTER-CONTRACT (12.2, 13.2, 15),
   IDENTITY-MAPPING, MEDIA-IDENTITY, the runbooks named in the brief, MEMBER-BETA-READINESS, BETA-CHECKLIST,
   DECISIONS (tail), RC1 report sections 5, 5a, 6 (`origin/docs/media-2.0-rc1`), and the RC2 baseline.
2. Code read line by line: `principal.py`, `outpost_jwt.py`, `identity_bindings.py`, `member_keys.py`,
   `provision.py`, `app/identity.py`, `app/middleware.py`, `app/artwork.py`, `app/pwa.py` + `assets/sw.js`,
   `app/security.py`, `app/forms.py`, `aggregate.py`, `contract.py` (artwork, mapping single-flight, slots, section
   cache), `adapters/komga.py` (member keys), `requests/seerr.py` (admin refusal); `scripts/deploy-home-beta.sh`,
   `scripts/offboard.py` (Komga/retire paths), `services/authentik/blueprints/avrana-enrollment.yaml`,
   `services/avrana-home/Dockerfile.live`, `services/avrana-home/docker-compose.beta-live.yml`,
   `services/backups/avrana-backup.sh` (stack-config allowlist).
3. PRs read with `gh pr view` / `gh pr diff`: **#162** (head 8c08e89) and **#167** (head 0593910). Diffs saved under
   the scratchpad (`pr162.diff`, `pr167.diff`).
4. Tests, one module at a time (results in section c). Never `tests/run_offline.py` or `run_web_tests.py`.
5. One new probe: `scratchpad/security/probe_komga_provision.py` (synthetic Komga fake, no network), output
   `probe_komga_provision.out`. Scratchpad: `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\security\`.
6. No dev stack was started (the probes needed only library code).

Local-environment notes (not product findings, see S-13): the venv lacks Pillow and PyYAML, and Windows loopback is
slow enough that one web test's positive sanity check times out.

## (b) Findings

| ID | Component | Class | Sev | Beta-blocking | One line |
|---|---|---|---|---|---|
| S-01 | provision.py Komga key creator vs enrollment `avrana-komga-create` | CONFIRMED | **P1** | **yes** | Home resets the member's Komga password; OPDS reader apps stop working |
| S-02 | provision.py Komga partial failure; missing keys file | CONFIRMED | P2 | no | Password replaced, no key filed, repeated hourly; a lost keys file re-runs it for everyone |
| S-03 | member_keys.py / komga.py | DESIGN QUESTION | P2 | no | Komga member key is chosen by e-mail only, not by the bound `sub`; offboarding leaves the entry |
| S-04 | services/backups/avrana-backup.sh | CONFIRMED (repo) / UNVERIFIED (live) | P2 | no | Home's `state/` (identity bindings, Komga keys) and the live compose are not in the backup allowlist |
| S-05 | identity (JWT groups) | DESIGN QUESTION | P2 | no | A removed library group stops only when the token is reissued (24 h), not within Home's cache TTL |
| S-06 | Authentik enrollment blueprint (#167) | CONFIRMED | P2 | no | Repo is behind live; a blind copy would revert Jellyfin to password copying and retarget the admin entry |
| S-07 | Komga everyday key (AVR-782) and guard #162 | KNOWN-DEFERRED (key) / guard reviewed | P1 (cutover) | no | Guard is correct; deploy-order and an unverified `/api/v2/users/me` read are its failure modes; PR CI red (stale base) |
| S-08 | provision.py Jellyfin creator | PROBABLE | P2 | no | Policy step failure leaves a locked account that Home never repairs (`exists`) |
| S-09 | contract.py per-member slots | PROBABLE | P3 | no | Rapid refresh while an upstream is slow shows sections "unavailable" (`member_busy`) |
| S-10 | rollback design | DESIGN QUESTION | P2 | no | Rolling back to `pre-2cb228f` silently drops S1 protection; rollback docs still call Home stateless |
| S-11 | docker-compose.beta-live.yml (repo) | CONFIRMED | P3 | no | Repo compose turns bindings on with no state volume; not a usable rebuild record |
| S-12 | tests/test_hung.py | CONFIRMED | P3 | no | Thread-count assertions depend on test order; 2/4 fail when run alone |
| S-13 | local test environment | CONFIRMED (env) | P3 | no | Windows-only sanity timeout, missing Pillow/PyYAML: evidence gaps, not product defects |
| S-14 | docs | CONFIRMED | P3 | no | Runbooks and docstrings still say "not deployed / nothing applied" |
| S-15 | outpost_jwt / settings | DESIGN QUESTION | P3 | no | The previous JWT secret is accepted with no end date |
| S-16 | member_keys.py | PROBABLE | P3 | no | Keys file has no cross-process lock; owner tool and Home can lose an update |
| S-17 | Seerr CSRF / proxy trust (AVR-348) | KNOWN-DEFERRED | P1 (cutover) | no | Runbook only; gates cutover |
| S-18 | Komga replicated password at offboarding | KNOWN-DEFERRED | P2 | no | Komga keeps its own password; OPDS works after Authentik deactivation until the account is deleted by hand |

Counts: **P0 0, P1 3** (S-01, S-07, S-17), **P2 8**, **P3 7**. Beta-blocking: **S-01 only**.

---

### S-01: Home's Komga key provisioning replaces the member's OPDS password

- **Component:** `avrana_home/provision.py` `KomgaKeyCreator.create`; `services/authentik/blueprints/avrana-enrollment.yaml` `avrana-komga-create`.
- **Classification:** CONFIRMED [offline probe + trace]. **Severity:** P1 (an essential workflow, reading comics in a
  reader app, breaks for every comics member who opens Home).
- **Beta-blocking: yes.** Every invited comics member gets a Komga password at enrollment for their reader app, and
  their first Home visit replaces it with a discarded random one, with no message to them or the owner.
- **Impact:** comic reader apps (OPDS over HTTP Basic) fail with 401 after the member's first Home visit. Members
  never learn why; recovery needs the owner to reset the Komga password. Already-keyed members (the `--all` first
  run) lost it the same way.
- **Reproduction:** `probe_komga_provision.py` → `S-01 existing non-admin account password PATCHed: True`.
  Trace: enrollment `avrana-enrollment.yaml:357-399` creates the Komga account "with the SAME email and password
  they just chose" so OPDS works (`docs/services/komga.md:15-27`) → member opens Home → Komga Continue returns
  `EMPTY/no_member_key` (`adapters/komga.py:268-274`) → `Provisioner.candidates` (`provision.py:268-269`) →
  `KomgaKeyCreator.create` finds the account by e-mail (`provision.py:204-213`), it is not ADMIN, so
  `PATCH /api/v2/users/{id}/password` with `_discarded_password()` (`provision.py:219-230`).
- **Expected vs actual:** expected the member's chosen Komga password to survive (the enrollment's stated purpose);
  actual it is replaced. `docs/runbooks/komga-member-keys.md:44` says "an account that uses a real local Komga
  password (not Authentik) would lose that password" but treats that as an exception; enrollment makes it the rule.
- **Baseline 2cb228f:** present; live switch named in the baseline (`HOME_PROVISION_ACCOUNTS`, `KOMGA_ADMIN_TOKEN_FILE`).
- **Root cause:** two owner decisions (2026-08 OPDS password replication, 2026-10-28 "Home does it") conflict; Komga
  makes keys only for a signed-in account, so Home signs in by resetting the password.
- **Minimum correction (owner decision first):** either drop `komga` from `HOME_PROVISION_ACCOUNTS` for the beta (Continue
  reading on Comics then needs the owner tool at invitation, which has the same cost) or change the creator to make
  keys only for accounts Home itself creates and refuse (`has_local_password`) any existing account, and tell members
  in the invitation that Continue reading on Comics is not available yet. A real fix needs a Komga route that mints a
  key for another user (the existing forks pattern) or the member typing their password once.
- **Regression risk:** low for the switch-off; the creator change touches 22 provision tests.
- **PR/Linear:** none found. Related: AVR-782 (#162) is a different key.

### S-02: Komga provisioning partial failure, and a lost keys file

- **Class:** CONFIRMED [offline probe]. **Sev:** P2. **Beta-blocking: no** (contained by S-01's decision; on its own
  it repeats S-01's damage, it discloses nothing).
- **Impact:** if the password PATCH succeeds and the key step fails (Komga 5xx, timeout, or `store.put` failing on a
  read-only or unmounted `state/`), the password is already gone, no key is filed, and the same member is reset again
  an hour later. `MemberKeyStore` treats an absent file as "no keys" (`member_keys.py:55-56`), so a lost or unmounted
  keys file makes every comics member a provisioning candidate (10/hour cap), each losing their Komga password again.
  Contrast: the identity bindings fail closed on a missing file.
- **Reproduction:** probe → `S-02 password replaced although key creation failed: True`, `retried an hour later,
  password replaced again: True`, log `failed:http_500` twice. Trace `provision.py:227-232`, `provision.py:295-305`.
- **Expected:** a failed attempt leaves the account as it was, or is not retried blindly. **Actual:** destructive
  step first, verification later, retried hourly.
- **Root cause:** no compensation step; absent keys file is a valid empty state.
- **Minimum correction:** after a failed key step, stop retrying for that member (record a terminal `failed_after_reset`)
  and refuse to provision while the keys file is absent but `KOMGA_MEMBER_KEYS_FILE` is configured.
- **Regression risk:** low. **PR/Linear:** none.

### S-03: Komga member key selected by e-mail, not by the bound identity

- **Class:** DESIGN QUESTION (mechanism CONFIRMED by probe; exploitation precondition UNVERIFIED). **Sev:** P2.
  **Beta-blocking: no.** It needs two Authentik users with one e-mail address, which is 0 today [recorded RC1 5a] and
  needs inbox control through enrollment (the e-mail stage precedes login, `avrana-enrollment.yaml` bindings order 30/40).
- **Impact:** the S1 binding protects username → `sub`; Komga Continue/New for You select the key by the token's
  `email` claim only (`adapters/komga.py:374-385`, `member_keys.py:116-122`). A second Authentik user carrying the same
  e-mail (admin-created, or re-invited departed member under a new username) reads the first person's Komga reading
  progress. The enrollment flow has no e-mail uniqueness policy (only username, `avrana-enrollment.yaml:111-146`).
  Offboarding never removes the `state/komga_member_keys` entry (`scripts/offboard.py:142-144` handles Komga "manually";
  `docs/runbooks/offboarding.md:177-183` does not mention the keys file); the key stays valid until the Komga account
  is deleted by hand.
- **Reproduction:** probe → `S-03 two usernames, one e-mail -> same member key: True`.
- **Minimum correction:** file keys by `sha256(sub)` (or by bound username) and keep e-mail only for finding the Komga
  account; add the keys file to the offboarding checklist; optionally an e-mail-uniqueness check in the enrollment policy.
- **Regression risk:** medium (file format change). **PR/Linear:** none.

### S-04: Home's state and live compose are outside the stack backup

- **Class:** CONFIRMED in the repo copy; live script UNVERIFIED (the host copy may differ). **Sev:** P2.
  **Beta-blocking: no**, but the AVR-350 restore drill (a beta gate) should include it.
- **Impact:** `backup_stack_config` (`services/backups/avrana-backup.sh:444-463`) allowlists `services/*/docker-compose.yml`,
  `services/*/*.env` and `services/*/secrets`. Home's files are `services/avrana-home/docker-compose.beta-live.yml`
  (not matched) and `services/avrana-home/state/` (not matched): `identity_bindings.json` and `komga_member_keys`.
  `docs/runbooks/identity-bindings.md:97` tells the owner to "restore `./state/identity_bindings.json` from the latest
  backup of `./state`", which does not exist. After host loss, bindings must be re-seeded from Authentik (works, but the
  release history and post-seed first-sight bindings are lost), the Komga keys are re-provisioned (S-01 again for every
  member) and the switches (the live compose is "the record", RC2 baseline section 3) are rebuilt by memory.
- **Minimum correction:** add `services/avrana-home/state` and `services/avrana-home/docker-compose.beta-live.yml` to the
  allowlist and to `required-artifacts.txt`; restore-test the bindings file in the AVR-350 drill.
- **Regression risk:** low. **PR/Linear:** AVR-350 (drill), none for the allowlist.

### S-05: Library-group removal takes effect at token reissue, not within the cache TTL

- **Class:** DESIGN QUESTION. **Sev:** P2. **Beta-blocking: no** (documented trade-off, small group of testers).
- **Impact:** Home checks the group before every cache read (`contract.py:1031-1033`, `contract.py:698-699`), which
  `test_bench_cache_revocation` proves, but the group comes from the signed token, whose lifetime is 24 h
  (`docs/design/D3-outpost-identity-proof.md:74`; `outpost_jwt.py:51` max lifetime). Removing a member from
  `avrana-comics` in Authentik therefore stops Home only when the outpost session's token is reissued.
  Whether user deactivation ends the outpost session at once is UNVERIFIED (section e).
- **Minimum correction:** decide the window: shorten `access_token_validity` on the Home proxy provider, or add "end
  the member's sessions" to the group-removal and offboarding runbooks.
- **PR/Linear:** D3 open question 3.

### S-06: Enrollment blueprint drift (#167)

- **Class:** CONFIRMED [trace of `gh pr diff 167`]. **Sev:** P2. **Beta-blocking: no**, provided nobody applies the repo
  file to live.
- **What differs (main vs live, per #167):** (1) the admin entry targets `akadmin` in main, `Cody` live, and live adds
  `library-contributors` and `Avrana Home (Beta)`; (2) `avrana-jellyfin-create` in main copies the enrollee's password
  into Jellyfin's local provider (`"Password": password`); live creates a random password and switches the account to the
  LDAP provider. S1 entries are identical.
- **Risk of a blind overwrite:** new members would again get a frozen local Jellyfin password that survives Authentik
  password resets and deactivation (direct Jellyfin and TV sign-ins after offboarding, until the Jellyfin account is
  disabled), undoing the LDAP switch; the blueprint's first entry is a full group assignment for the named admin, so the
  group membership of the admin account(s) changes (the PR describes the live effect; the exact Authentik m2m semantics
  are UNVERIFIED here). Two more live blueprints, `jellyfin-ldap.yaml` and `authentik-home-beta.yaml`, are not in Git at
  all: no review, no CI, not rebuildable from the repository.
- **Second observation in #167's live version:** the LDAP switch's policy POST is not read back (unlike
  `provision.py:140-144`); a failed POST leaves a password-locked, non-LDAP account (see S-08 for the same failure in Home).
- **Also unchanged in both:** `avrana-komga-create` replicates the password into Komga (the root of S-01 and S-18).
- **Minimum correction:** merge #167 (repo catches up to live, nothing applied); add the two live-only blueprints to Git
  as files only; keep "never copy the repo file over live" in the runbook until `scripts/drift-check.py` shows no diff.
- **PR/Linear:** #167 (draft).

### S-07: Komga everyday key is an ADMIN key (AVR-782); guard #162 review

- **Class:** KNOWN-DEFERRED for the key (RC1 S2); the guard itself was reviewed [trace]. **Sev:** P1 for cutover (RC1
  section 6 item 8). **Beta-blocking: no** (RC1: gates cutover; members see everything anyway by owner decision and the
  shared transport is GET-only with a four-route allow-list, `adapters/komga.py:93-102`).
- **Guard correctness (#162 at 8c08e89):** the check sits in `_resolve_user` and runs before any shared read: a section
  cache hit is possible only after a mapping that passed the check, mappings are cached only after `_resolve_user`
  returns (`contract.py:913-930`), member-scoped caches are memory-only (`cache.py:78` persists only `catalogue`), and the
  artwork path goes through `_call` → `_mapped` too. A malformed or failed answer refuses that call and is asked again;
  an ADMIN answer is memoised for the process. Mock and injected adapters never ask. This is correct.
- **Failure modes:** (1) deploy order: merged and deployed before the owner's key swap, every Comics row, Continue
  reading and comics search go unavailable for everyone (fails closed, the intent; the PR states it). (2) Whether a
  non-admin Komga **API key** may read `GET /api/v2/users/me` on the deployed Komga is UNVERIFIED; if it answers 401/403,
  Comics stay unavailable after the swap and the check repeats on every call (counted by the breaker, so 60 s cool-offs).
  (3) After the swap, a restart is needed (the memo and the key file are read once); the deploy recreate does that.
  (4) `SharedKeyIsAdmin` subclasses `UpstreamMisbehaved`, so it opens the circuit; logs show it once per cool-off, by class.
  (5) The PR's CI is red: `run_offline.py` fails in `test_home_static_export` (the pre-#161 static export issue), not in
  the Komga change; it needs a rebase onto 2cb228f before review.
- **Minimum correction:** none to the code; rebase, then the owner verifies the new viewer key's `/api/v2/users/me`
  roles before deploying (section e). The swap itself is owner-gated and not proposed here.
- **PR/Linear:** #162, AVR-782.

### S-08: Jellyfin provisioning that fails after creating the account

- **Class:** PROBABLE (Jellyfin LDAP plugin behaviour for a non-LDAP account is unverified). **Sev:** P2. **Beta-blocking: no**
  (provisioning only runs for an unmapped name; enrollment creates the account first).
- **Impact:** `POST /Users/New` succeeds, then `POST /Users/{id}/Policy` fails or does not verify (`provision.py:130-144`):
  the account keeps a discarded password and the default provider, so it is locked (safe), but the next attempt answers
  `exists` (`provision.py:128-129`) forever and Home maps the name as linked, so Home's own rows work while the member's
  Jellyfin app and TV sign-in fail with no hint. Only the owner can repair it.
- **Minimum correction:** on `policy_unverified`, log a distinct `provision` reason the operator dashboards alert on, and
  let a later attempt re-apply the policy to an account whose provider is not LDAP and that Home created (record the id).
- **PR/Linear:** none.

### S-09: Rapid refresh during a slow upstream shows sections unavailable

- **Class:** PROBABLE [trace]. **Sev:** P3. **Beta-blocking: no** (self-heals on the next load).
- **Trace:** a member may hold 2 calls per library and the per-member cap never waits (`contract.py:756-762`,
  `contract.py:50`); calls of an abandoned page keep running until their 2 s budget ends (`aggregate.py:180-183` cancels
  only queued work). A phone on 4G that refreshes while one library takes 1-2 s gets that library's uncached sections as
  `UNAVAILABLE/member_busy`. Cached sections are unaffected.
- **Numbers vs a phone on 4G:** the budgets are server-side and LAN-bound (2 s per request, 3 s page hard cap, 60 s
  cool-off after 3 consecutive counted failures, `resilience.py:27-30`, `resilience.py:492`), so radio latency does not
  open circuits; the member pays RTT plus at most ~3 s. That is acceptable for a beta. No phone measurement exists.
- **Minimum correction:** let a `member_busy` call wait briefly (as the service cap does) or serve the stale section.

### S-10: Rollback drops S1, and the rollback docs assume a stateless Home

- **Class:** DESIGN QUESTION. **Sev:** P2. **Beta-blocking: no**, but the AVR-388 rehearsal must know it.
- **Impact:** `docs/runbooks/identity-bindings.md:61` "the previous image ignores the file"; `home-rollback-rehearsal.md:5`
  and `MEDIA-2.0.md:175` call Home stateless. Rolling back to `pre-2cb228f` (the documented rollback, RC1 6 item 2) runs
  without seeded bindings: the recycled-name exposure (RC1 5a) returns for the duration, silently. Home now also holds
  `state/` (bindings, Komga keys) that a rebuild-from-image recovery must keep.
- **Minimum correction:** state in the rollback packet that rolling back past 2cb228f re-opens S1 (and requires
  `HOME_ALLOWED_USERS` to be the owner only while rolled back); update the "stateless" lines.

### S-11: Repo compose is not a usable rebuild record

- **Class:** CONFIRMED [trace]. **Sev:** P3. **Beta-blocking: no.**
- `services/avrana-home/docker-compose.beta-live.yml` sets `HOME_IDENTITY_BINDINGS_FILE=/var/lib/avrana-home/...` with
  `read_only: true` and no volume, so the repo file alone starts a Home that refuses everyone; it also lacks the broker
  networks and Komga key lines the baseline lists as on. `deploy-home-beta.sh:48-85` copies the live compose and refuses
  repo-only active lines, so deploys are safe; disaster recovery from Git is not (with S-04).
- **Minimum correction:** add the `./state:/var/lib/avrana-home` volume line (commented or active) beside the bindings line.

### S-12: test_hung thread-count assertions depend on test order

- **Class:** CONFIRMED [offline]: `test_hung` alone, 4 run, **2 fail** (`12 not <= 4`, `32 not <= 8`), twice.
- **Root cause:** `_DaemonPool.submit` starts a new thread per submit until 48 (`aggregate.py:47-55`), so a cold pool adds
  threads; the assertions hold only after an earlier test warmed the shared pool. Threads are bounded at 48 (no product
  defect). **Sev:** P3. **Minimum correction:** warm the pool in `setUpClass`, or assert `<= POOL_WORKERS`.

### S-13: Evidence gaps from the local environment

- `test_web_isolation_h2` alone on Windows: 5 run, 1 fail. Every cross-member assertion ran and passed in all rounds
  (they precede it); the failing line is the positive sanity check `Synthetic Audiobook` in member A's page, which showed
  "Audiobooks are unavailable right now" (mock ABS slower than the test's timeout on Windows loopback). CI (Linux) is
  green at 2cb228f [recorded]. `test_web_me_profile`: import error, Pillow not in the venv (dormant feature).
  `tests.test_enrollment_username_available`: 8 skipped, PyYAML not in the venv. **Sev:** P3, not product defects.

### S-14: Stale status lines

- `docs/runbooks/identity-bindings.md:3` "proposed, not deployed"; `home-beta-live.md:3`, `home-beta-deploy.md:3`
  "nothing applied"; `home-degraded-library.md:3` "not deployed"; `MEMBER-BETA-READINESS.md:29` "PR #52 not merged";
  module docstrings `provision.py:3`, `member_keys.py:3`, `outpost_jwt.py:3` ("NOT WIRED IN"), `principal.py:3`. RC2
  baseline section 4 lists others. **Sev:** P3. Misleading for the owner during an incident.

### S-15: The previous JWT secret has no end date

- `IdentityResolver.from_settings` accepts `jwt_secret_previous` for as long as it is configured (`app/identity.py:111`);
  D3 says "keep both pinned for one token lifetime (24 h), then remove". Nothing reminds or enforces it.
  **Class:** DESIGN QUESTION, **Sev:** P3. Correction: log a daily `identity_jwt reason=previous_secret_in_use` when a
  token verifies only under the previous secret.

### S-16: Komga keys file has no cross-process lock

- `MemberKeyStore.put` does read-modify-write under a thread lock only (`member_keys.py:129-139`); the owner tool
  `tools/komga_member_keys.py` writes the same file. Home is one process (`app/serve.py`, single uvicorn), so the race
  is owner tool vs Home: a key written by one can be lost. Consequence: the member is re-provisioned (S-01 again).
  **Class:** PROBABLE, **Sev:** P3. Correction: reuse `identity_bindings.file_lock`.

### S-17: Seerr CSRF protection and proxy trust (AVR-348)

- KNOWN-DEFERRED (RC1 S9). Runbook `m0-seerr-csrf-proxy-trust.md` only. Home's own broker acts as a non-admin member
  (`requests/seerr.py:276-280` refuses ADMIN/MANAGE_* bits and user 1, verified by `test_broker_hardening`). **Sev:** P1
  for cutover, not the beta.

### S-18: Komga replicated password outlives the Authentik account

- KNOWN-DEFERRED (offboarding runbook `offboarding.md:177-183`, U-17). The enrollment copies the password into Komga;
  deactivating the Authentik user does not stop OPDS until the Komga account is deleted by hand. **Sev:** P2.

---

## (c) Protections verified present at 2cb228f

### #166 (S1) is in main, by code and tests

- Bindings checked for every verified principal, fixed reason codes only: `app/identity.py:137-142`.
- No `sub` → refused (`identity_bindings.py:282-283`); missing, unreadable, malformed or shrunk file → `bindings_unavailable`
  (`identity_bindings.py:264-279`, `254-262`); Home never creates the file (`read_state` has no default, `125-144`);
  writes under `flock` with re-read, fsync, atomic replace (`186-212`, `295-306`, `160-182`); letter-case/Unicode twins
  refused (`215-223`, `118-121`); `init` merges and refuses conflicts (`340-356`, `474-477`); `release` refuses while an
  upstream holds the name or cannot be asked (`391-398`, `494-499`).
- Deploy refuses with the switch on and no file: `scripts/deploy-home-beta.sh:80-84` (exit 7).
- Retired names: enrollment policy `avrana-enrollment.yaml:111-146`; offboarding retires before delete
  (`scripts/offboard.py:194-202`, `348-356`).

### Tests run here (each module alone; all OK unless stated)

Unit (`services/avrana-home/tests`): `test_identity_bindings` 25, `test_outpost_jwt` 32, `test_verified_identity` 43,
`test_principal` 17, `test_provision` 22, `test_komga_member_reading` 33, `test_komga` 54, `test_resilience` 10,
`test_breaker_policy` 14, `test_cache` 56 (1 skipped), `test_h2_security` 32, `test_boundary` 9, `test_quickconnect` 15,
`test_slowdrip` 9, `test_section_queue` 8, `test_aggregate` 9, `test_hung` 4 (**2 failed**, S-12).
Total: 392 run, 389 passed, 2 failed, 1 skipped.

Web (`services/avrana-home/webtests`): `test_web_identity_bindings` 12, `test_web_jwt_identity` 41, `test_web_identity` 24,
`test_web_isolation_h2` 5 (**1 failed**, positive sanity only, S-13), `test_bench_cache_revocation` 4,
`test_artwork_gateway` 3, `test_web_artwork` 16, `test_broker_hardening` 11, `test_my_requests` 21,
`test_account_provisioning` 8, `test_web_provision` 3, `test_web_quick_connect` 15, `test_web_pwa` 33,
`test_dev_isolation` 3, `test_route_layer_source` 9, `test_web_customize` 19, `test_web_watch_requests` 11,
`test_web_book_requests` 17, `test_comic_requests` 11, `test_web_ops` 15, `test_transport_no_proxy` 1, `test_web_komga` 14;
`test_web_me_profile` import error (Pillow). Total: 296 run, 295 passed, 1 failed (+1 module not importable).

Repository (`python -B -m unittest`): `tests.test_offboard_retire` 4, `tests.test_deploy_home_beta_bindings` 3,
`tests.test_portal_jwt` 24, `tests.test_deploy_home_beta` 3; `tests.test_enrollment_username_available` 8 **skipped**
(PyYAML). Total: 34 passed, 8 skipped.

New probe: `probe_komga_provision.py`, 4 checks, all reproduce (S-01, S-02, S-03).

### Protections confirmed by trace (and covered by the tests above)

| Area | Protection | Where |
|---|---|---|
| Token | alg fixed by config (no alg confusion), `crit/jku/jwk/x5u/x5c` refused, canonical base64url, duplicate JSON keys refused, iss/aud exact, exp required, iat required, nbf/iat future-dated beyond 60 s leeway refused, lifetime ≤ 24 h, ≤ 16 KiB, ASCII | `outpost_jwt.py:273-321` |
| Token | rotation overlap: every secret tried, constant time | `outpost_jwt.py:251-258` |
| Headers | duplicates, non-ASCII, oversized, look-alike names refused; plain headers must equal claims in `jwt_required`; JWT header > 8 KiB dropped; header block > 16 KiB → 431 | `principal.py:303-337`, `app/identity.py:57-85`, `328-351`, `middleware.py:138-140` |
| Allowlist | `HOME_ALLOWED_USERS` after verification, before bindings | `app/identity.py:134-136` |
| Groups | checked before any cache read or upstream call, every section and artwork | `contract.py:1031-1033`, `698-699` |
| Cache | per-member partitions; only `catalogue` persisted | `contract.py:703`, `cache.py:76-78` |
| Artwork | ref shape allow-list, raster types only (no SVG), size bound, `private, no-cache`, 304 only after the member's own permission check passes | `app/artwork.py:35-91`, `middleware.py:82-97` |
| Headers out | `no-store`, `no-referrer`, `nosniff`, CSP `default-src 'none'`, no inline script, `frame-ancestors 'none'` | `middleware.py:39-62` |
| Methods | non-GET/HEAD → 501 except listed form paths; length required and bounded | `middleware.py:141-153` |
| Forms | same-origin (Sec-Fetch-Site / Origin = Host), HMAC token bound to member and fields, exact fields, double-tap guard | `app/forms.py:1-60`, `app/identity.py:226-264`, `requests/forms.py` |
| Sign-out | `Clear-Site-Data: "cache", "storage"` then fixed outpost target; the worker never intercepts it | `app/pwa.py:39`, `55-58`, `assets/sw.js:87-96` |
| Worker | navigations network-first, offline page only on network failure; caches only an exact static allow-list | `assets/sw.js:22-35`, `93-107` |
| Seerr | admin, MANAGE_* and user 1 refused; acts as member | `requests/seerr.py:276-280`, `465-483` |
| Provisioning | group required, ≤ 1 attempt per member/library/hour, cap 10/hour, no redirect, no proxy, bounded body | `provision.py:76-105`, `284-319` |
| Process | `proxy_headers=False`, no access log of query strings, `server_header=False`; container read-only, non-root, caps dropped | `app/serve.py`, compose |

## (d) Critical path to inviting 3-5 closed-beta members

Dependency order, top to bottom. "Beta" = member-beta prerequisite; "Cutover" = production-cutover prerequisite.

### Engineering deficiencies (code, tests, docs we can fix now)

| # | Item | Evidence now | Missing | Who | Gate |
|---|---|---|---|---|---|
| E1 | **S-01/S-02** Komga provisioning resets OPDS passwords | probe, trace | owner decision (switch off for beta, or creator change) then fix + tests | owner decides; agent implements | **Beta** |
| E2 | **S-04** add Home `state/` and live compose to the backup allowlist | repo trace | change + one backup run listing them | agent (PR), owner (deploy script on host) | Beta (feeds O3) |
| E3 | **S-10/S-14** rollback packet: rolling back past 2cb228f re-opens S1; fix "stateless" and "not deployed" lines | trace | doc PR | agent | Beta (feeds O6) |
| E4 | **S-08** Jellyfin policy-failure repair path and alertable reason | trace | change + test | agent | Beta (nice), Cutover |
| E5 | **S-12** `test_hung` order independence | offline failure | 3-line test fix | agent | Beta (CI trust) |
| E6 | #165 RC1 docs and member checklist merged (`docs/acceptance/MEDIA-2.0-RC1-CHECKLIST.md` is not on main) | draft PR | merge | owner | Beta (O5 needs the checklist) |
| E7 | #167 merged (repo = live); `jellyfin-ldap.yaml`, `authentik-home-beta.yaml` into Git | PR diff | merge + two files | agent + owner merge | Cutover |
| E8 | #162 rebased (CI red on stale base) | PR checks | rebase | agent | Cutover (after O7) |
| E9 | **S-03** key by `sub`; keys file in offboarding | probe | change | agent | Cutover |
| E10 | **S-09**, **S-15**, **S-16** | trace | small changes | agent | after beta |

### Owner-controlled acceptance tasks

| # | Task (Linear) | Evidence now | Missing | Who | Gate |
|---|---|---|---|---|---|
| O1 | **SMTP2GO rotate + proof** (AVR-346), `m0-smtp2go-email.md` | runbook only | three arrival timestamps (invite, reset, alert) | owner | **Beta**: invitations need mail; the enrollment e-mail stage blocks sign-up without it |
| O2 | **akadmin MFA + break-glass** (AVR-347), `m0-authentik-admin-mfa.md` | change-username/e-mail off verified [recorded] | MFA prompt on akadmin, recovery sign-in tested | owner | **Beta** |
| O3 | **Off-host restore drill** (AVR-350), `m0-offhost-backup-restore.md` | historical 2026-09-23 verification only | one representative restore with times; include `state/identity_bindings.json` (after E2) | owner | **Beta** |
| O4 | **Two-member isolation run** (AVR-772) | offline isolation suites pass (section c) | owner + one non-admin tester on live: each sees only own Continue, covers, requests; one refused name check | owner + tester | **Beta** |
| O5 | **Non-admin device pass** (AVR-585; AVR-479 marked Done without device evidence) | Chromium on static export [recorded]; none on devices | iPhone Safari, installed PWA, one TV, journeys A-F, results template with no S0/S1 | owner + tester | **Beta** |
| O6 | **Rollback rehearsal parts B-D** (AVR-388), `home-rollback-rehearsal.md` | part A in CI | B (beta container), C (one degraded library), D (provider round-trip on the beta hostname); record that rollback re-opens S1 | owner | **Beta** (B, C); D before cutover |
| O7 | **Komga viewer key swap** (AVR-782), then #162 | #162 tests | owner-made non-admin key; roles check of `/users/me` (section e); then deploy #162 | owner | Cutover |
| O8 | **Seerr CSRF and proxy trust** (AVR-348) | runbook | toggles + three request paths tested, or a recorded exception | owner + tester | Cutover |
| O9 | **Decide S-01** (Komga provisioning on or off for the beta) | this report | decision | owner | **Beta** |
| O10 | Add 3-5 testers to `HOME_ALLOWED_USERS` and invite (AVR-387) | allowlist on [recorded] | names added, restart, invitations sent | owner | Beta (last step) |
| O11 | AVR-345 identity-boundary review close-out | offline + G1 [recorded] + #166 seeded [recorded] | owner sign-off that the seed/deploy/blueprint apply is the evidence | owner | Beta |

Order to the first invitation: O9 → E1 → E2/E3/E5 → O1, O2 → O3 → O6 (B, C) → O4 → O5 → O11 → O10.
AVR-386 (CI gates): every suite runs since #161; browser/axe layer stays manual (counts for cutover).

### Later production-cutover prerequisites (AVR-389)

O7 + #162 (E8), O8, O6 part D, E7 (blueprint parity and live-only blueprints in Git), E9, S-05 decision (token
lifetime or session-ending in offboarding), S-18 (Komga account removal in offboarding), S-11 (compose rebuild record),
AVR-386 browser/axe gate automated, and the RC1 "suites CI does not run" list.

## (e) What could not be verified without live access

Each command is read-only and prints counts, names or roles, never a credential or member data. The owner or the
orchestrator runs it; this audit ran none.

| Question | Command (on `avrana`, owner) |
|---|---|
| Is Komga auto-provisioning on, and has it reset anyone (S-01)? | `docker logs avrana-home-beta 2>&1 \| grep '"provision"' \| grep -c '"komga"'` and `grep -c komga ~/avrana/services/avrana-home/beta-live.env` |
| Do any members rely on OPDS (S-01 impact)? | Komga UI → Users → per-user "last activity" for OPDS, or ask testers; no command reads it without credentials |
| Does the live backup include Home state (S-04)? | `zstd -dc "$(ls -d /mnt/avrana_media/.backups/avrana/*/ \| tail -1)stack-config/stack-config.tar.zst" \| tar -t \| grep -c 'services/avrana-home/state'` |
| Live backup script equals repo (S-04)? | `cd ~/avrana && git diff --stat -- services/backups/avrana-backup.sh` |
| Any two Authentik users sharing an e-mail (S-03)? | in the Authentik worker `ak shell`: `from django.db.models import Count; from authentik.core.models import User; print(User.objects.values('email').annotate(n=Count('id')).filter(n__gt=1).count())` |
| Does deactivating a user end the outpost session at once (S-05)? | owner test with a throwaway user: sign in to media-beta, deactivate in Authentik, reload; record whether Home shows signed-out |
| Provider token validity (S-05) | `ak shell`: `from authentik.providers.proxy.models import ProxyProvider; print([(p.name, p.access_token_validity) for p in ProxyProvider.objects.all()])` |
| Does a non-admin Komga API key read `/api/v2/users/me` (S-07)? | after the swap, inside Home: `docker exec avrana-home-beta python3 -c "import json,os,urllib.request as u; k=open('/run/secrets/komga_token').read().strip(); r=u.urlopen(u.Request(os.environ['KOMGA_BASE_URL']+'/api/v2/users/me',headers={'X-API-Key':k}),timeout=5); print(r.status, sorted(json.load(r).get('roles',[])))"` (prints status and roles only) |
| Blueprint drift today (S-06) | `cd ~/avrana && git diff --stat -- services/authentik/blueprints/` and `ls services/authentik/blueprints/` vs `git ls-files services/authentik/blueprints/` |
| Jellyfin accounts with a non-LDAP provider (S-08) | `docker exec avrana-home-beta python3 -c "import json,os,urllib.request as u; k=open('/run/secrets/jellyfin_api_key').read().strip(); r=u.urlopen(u.Request(os.environ['JELLYFIN_BASE_URL']+'/Users',headers={'X-MediaBrowser-Token':k}),timeout=5); print(sum(1 for x in json.load(r) if 'LDAP' not in x['Policy'].get('AuthenticationProviderId','')))"` (prints one count; the key never leaves the container or reaches a command line) |
| Bindings healthy | `docker exec avrana-home-beta python3 -m avrana_home.identity_bindings count` and `docker logs avrana-home-beta 2>&1 \| grep -c bindings_unavailable` |
