# Media 2.0 Release Candidate 1: state, evidence and go/no-go

Status: **engineering RC1 review packet, 2026-10-29; security closure update the same day (S1, section 5a).** Prepared by an agent under the RC1 sprint brief (feature
freeze). Nothing here was merged, deployed, rotated or changed on the host. Read-only observation on avrana: `docker inspect`
for the running revision, and for S1 an `ak shell` query and a Home-container query that printed booleans and counts only. Every claim is tagged with its evidence type:

- **[offline]**: tests in this repository with fixtures and fakes. Proves code behaviour, not live behaviour.
- **[host-read]**: read-only observation on avrana.
- **[recorded]**: an earlier deployment or owner report (PR body, runbook record, Linear). Not re-verified here.
- **[not run]**: nobody has checked it.

The member checklist is [../acceptance/MEDIA-2.0-RC1-CHECKLIST.md](../acceptance/MEDIA-2.0-RC1-CHECKLIST.md).

## 1. Go/no-go (three separate decisions)

| Decision | Verdict | Why |
|---|---|---|
| **RC1 engineering acceptance** | **GO once #161, #163 and #166 merge** (#162 may merge with them; deploy it only after the Komga key swap) | Main 50a8761 + #161, #162, #163, #166 passes every CI suite in both passes (draft #164, run 40952029300: 2,707 tests per pass). S1 is resolved in code (section 5a). Main's own CI stays cancelled at the time cap until #161 merges. |
| **Controlled 3 to 5 member beta** | **NO-GO** until the owner steps in section 6, items 1 to 7, are done | S1 fix deployed and enrollment policy applied (with the two leftover Jellyfin accounts handled); invite and reset e-mail proven (AVR-346); akadmin MFA (AVR-347); one restore drill (AVR-350); owner device pass. |
| **UX/UI smoothness sprint** | **GO to start after the RC1 merges**, on branches, with nothing deployed to the beta during member acceptance without owner approval | Backlog ready: rail focus at 200% text (A11Y-1, section 4.1), Concept K owner choices (AVR-727 to 735), Home audit items. |
| Private production cutover | NO | Needs the member beta (AVR-387), Seerr CSRF/proxy (AVR-348), old-portal rollback rehearsal and sign-off (AVR-389). |

## 2. Codebase and deployment state (Deliverable A)

| Item | Value | Evidence |
|---|---|---|
| `origin/main` at sprint start | **0e8c330** (merge of #158, 2026-10-29 17:18Z) | [offline] `git log` |
| `origin/main` now | **50a8761**: #160 "quiet cards" (838fa70) and #159 "hero R10" (50a8761, which also fixed the static export) were merged **during the freeze** by another session or the owner | [offline] |
| Running Home beta (media-beta.avrana.net) | at sprint start **0e8c330**; at the end of the sprint **50a8761** (#159 deployed during the freeze), healthy | [host-read] container label `com.docker.compose.project.working_dir`, read twice |
| Previous exports kept on host | home-981357f, home-9eacec2, home-df5757d (rollback tags `avrana-home-live:pre-<sha>`) | [host-read] |
| Open PRs at sprint start | **none** | [offline] `gh pr list` |
| CI `offline-tests` on main | **failed** from #155 (5227ac1) to 838fa70; **cancelled** (10-min cap) on 50a8761. Last green: 8aaa1b1 (#148). | [offline] GitHub Actions |
| CI `beta-image` on main | green on 0e8c330 | [offline] run 40920026323 |

Live = main, so there is no code drift between Git and the beta. Configuration drift is by design: `~/avrana`'s
`docker-compose.beta-live.yml` is the record of what is switched on (requests, provisioning, member keys).

### 2.1 October 27 to 29 work, classified

All of #128 to #158 are **merged**. None is open, stacked or conflicting.

| PRs | Classification | Note |
|---|---|---|
| #128 provisioning, #130/#134/#135/#138 Komga member keys, #131/#144 requests, #132/#146/#149/#152/#154/#156/#157/#158 Home shelves, #133, #136, #139/#142 deploy script, #141/#143/#145, #148 | Merged and deployed (running 0e8c330) | [host-read] |
| #150 Me identity, #151 Authentik flows, #153 Customize | Merged and deployed, **dormant**: `HOME_SECURITY_FLOWS` and `HOME_MEMBER_STORE` unset, #151 blueprints not applied | [recorded] |
| #155 H3 hero | Merged, deployed; **broke CI** (static export) | fixed on main by f764b1f (#159) |
| #137 requests runbook, #140 CWA charset, #129 | Merged; host-side steps recorded in #137 | [recorded] |
| #147 | Closed, superseded by #146 (fix) + #148 (test) | — |

The **Listen/Read HTTP 500 of 2026-10-29** is fixed on main (#146 renamed the shadowing local; #148's
`webtests/test_web_released_fallback.py` fails on the old code). That test had **not run in CI** since #155 because
the repository suite failed first; it passes locally on the RC1 tree [offline].

### 2.2 Should anything recent be backed out for RC1?

No. #160 and #159 are presentation changes merged (and #159 deployed) during the freeze; they are in the RC1 tree. The freeze should hold from here: no more UI merges until the member beta. Features that are on are stable in the offline suites; the dormant Me features cost nothing while their
switches are unset. Two recent additions are **not RC1 scope and should stay off**: Customize/profile photos
(member store, needs a writable state volume) and the Authentik Avrana-styled flows (#151). Turning them on is a
post-RC1 decision.

## 3. RC1 engineering changes

| PR | Purpose | Severity | Depends on | Tests | Recommendation |
|---|---|---|---|---|---|
| **#161** `fix/rc1-ci-gate` | `run_offline.py` runs every suite and fails at the end; job timeout 10 → 20 min | P1 (CI gate integrity) | none | new `EverySuiteRunsTests`; `test_ci_workflow` | **Merge first.** Main's CI is cancelled at the cap until then. |
| **#162** `fix/avr-782-komga-admin-guard` | Real mode refuses an ADMIN everyday Komga key (Comics unavailable, logged) | P1 (least privilege) | **Owner key swap first** (O6) | `tests/test_komga.py` 58/58 incl. 4 new | Merge any time; **deploy only after** `secrets/komga_token` is a regular account's key. |
| **#163** `fix/rc1-deploy-dry-run` | Dry run no longer leaves `avrana-home-live:local` on an untested build; a plan touching another container stops; prints running revision | P1 (rollback safety) | none | new `tests/test_deploy_home_beta.py` 3/3 (stub docker) | Merge; first real use is a dry run on avrana. |
| #164 `rc1/integration` | CI evidence for the three together on 838fa70 | — | #161–#163 | full CI | **Do not merge**; close after the three merge. |
| **#166** `fix/s1-identity-binding` | S1: username bound to its Authentik user (`sub`); enrollment refuses names Jellyfin already has | **P1 authorization** | none (deploy: owner adopts one compose line; blueprint applied on the host) | 8 web + 9 unit + 5 blueprint tests | **Merge third**, then deploy with #161/#163. |
| #165 | RC1 packet (this file and the checklist) | — | — | docs | Merge last. |

### 3.1 Safe merge order

1. **#161** CI: main's `offline-tests` is cancelled at the 10-minute cap until this lands.
2. **#163** deploy script: the next deploy (S1) should use the fixed dry run.
3. **#166** S1. Then deploy (owner): add the `HOME_IDENTITY_BINDINGS_FILE` line to `~/avrana`'s compose (the script stops
   with exit 3 until you do), dry run, `--apply`.
4. **#162** Komga guard: merge any time, but the first deploy that contains it must come **after** the AVR-782 key swap,
   or Comics go unavailable. Simplest: swap the key, then merge and deploy #162 on its own.
5. **#165** this packet. 6. Close draft **#164** (evidence only).

All of them merged together in #164 without conflicts.

## 4. Test evidence (Deliverable C)

Revision: `rc1/integration` = `origin/main` plus #161, #162, #163 (d3ed4e4 on 838fa70; re-run as cff913f on 50a8761). Windows 11, Python 3.12.3, the CI
versions from `.github/requirements-ci.txt` and `services/avrana-home/requirements.lock` installed without hashes
(the hashes are for the Linux wheels CI uses).

```sh
AVRANA_REQUIRE_YAML=1 python -B tests/run_offline.py
# or each suite:
python -B -m unittest discover -s tests -p "test_*.py"
python -B -m unittest discover -s services/avrana-home/tests -t services/avrana-home -p "test_*.py"
python -B -m unittest discover -s services/avrana-home/webtests -t services/avrana-home -p "test_*.py"
```

**Linux CI, `rc1/integration` d3ed4e4** (draft #164, run 40937036543, 19:06 to 19:17Z): `offline-tests` **success**,
`beta-image` **success**. **Re-run on main 50a8761 as cff913f** (run 40939721479): success, identical except Home
web 982 tests (two new from #159). The job runs every suite twice, the second time inside `unshare --net` with
`AVRANA_REQUIRE_YAML=1`; both passes identical:

| Suite | Tests | Result |
|---|---|---|
| repository tests (`tests/`) | 436 | OK |
| imax-verify | script | OK |
| Kindle offline / authz / a11y | 4 / 92 / 44 | OK (1 expected failure in authz, by design) |
| backups | 30 | OK |
| assistant | 93 | OK |
| Home adapters (`services/avrana-home/tests`) | 997 | OK |
| Home web (`services/avrana-home/webtests`) | 980 | OK |
| **Total per pass** | **2,679** | **all 9 suites passed** |

**Windows, local** (same tree minus #160 for the first run): repository tests 432 OK (25 min; the G1 stub tests are
slow on Windows), Home adapters 997 OK (1 skip), Home web 980 with **2 failures that this sprint introduced and
fixed** (the owner preview runs real mode against the mock Komga, which did not answer `/api/v2/users/me`; fixed
in #162 8c08e89). On d3ed4e4, Home adapters 997 OK and Home web 979/980; the one failure
(`test_web_sections` markup) came from merging main into that worktree while the suite ran, and passes (31/31) on
the settled tree cff913f. Running suites that start mock servers concurrently on one machine gives port clashes; run them
one at a time.

**Before RC1**: main 0e8c330 failed `repository tests` (4 failures, static export) and never ran the Home suites
in CI; the last fully green main run was 8aaa1b1 (#148), which took 8 min 22 s of the 10-minute job cap.

What the suites cover, by the brief's reliability list [offline]:

| Condition | Covered by |
|---|---|
| One service unavailable / one request hangs | `test_resilience`, `test_hung`, `test_slowdrip`, `test_abs_slow_fanout`, `webtests/test_web_isolation_h2` (one failing upstream never breaks the page) |
| Authentication expired / bad token | `webtests/test_web_jwt_identity` (bad tokens = no principal, never 403 or redirect) |
| Member with no library access | static export state `member-none/no-library`, `test_web_sections` |
| Library with no recent content | `test_web_released_fallback` (the Oct 29 500) |
| Oversized search reply | `test_search`, #133 ABS size cap tests |
| Malformed upstream results | `test_contract`, adapter `_parse_many` tests, `test_review2/3` |
| Concurrent Home requests | `test_section_queue`, `test_transport_cost`, `test_aggregate` |
| Access revoked during cache lifetime | `webtests/test_bench_cache_revocation` |
| Deployment validation | `beta-image` workflow (refuses header identity and real upstreams), `test_beta_live_static`, `test_deploy_home_beta` |

**Limitations.** Every adapter test uses hand-written fixtures; live upstream shapes are recorded as UNVERIFIED in
ADAPTER-CONTRACT (AVR-772). No browser/axe run was done in this sprint (`tests/ui` harness exists; last recorded
axe pass is from the Concept K work). No performance numbers were taken against the live beta. The deploy-script
test uses canned Compose output.

### 4.1 Security closure re-run (with #166)

| Run | Result |
|---|---|
| Linux CI, `rc1/integration` f436f01 = 50a8761 + #161 #162 #163 #166 (run 40952029300) | **success**, both passes: repository 441, Home adapters 1007, Home web 990, Kindle 4/92/44, backups 30, assistant 93, imax OK. 1 expected failure (Kindle authz, by design). |
| Windows, `fix/s1-identity-binding` | Home web 990 OK. Home adapters 1003: **1 failure**, `test_phase1.N6EvictionIsNotQuadratic` (asserts 300 evictions finish in under 10 s wall-clock; took 13.3 s while three suites and Chromium ran; passed alone 2 of 3 times under the same load, and passes in CI). Classified test-environment timing, not a defect (P2: bound it by operation count). |
| Browser (Chromium via Playwright, axe-core 4.10.3), static export of the RC1 tree, 183 pages x 390/1280/844x390 x light/dark (1,098 views) | **0 serious or critical axe violations, no sideways scroll.** 16 keyboard findings, one kind (**A11Y-1**): at 390 px with 200% text a focused rail card is not wholly in view (card 308 to 548 px in a 390 px viewport). **Present on 0e8c330 too**, so not caused by #159/#160. P2, UX sprint. |

Suites that exist but CI does not run (P2, recorded): `scripts/test_offboard.py` (runs the real script at
`/home/cody/avrana`: host-only), `scripts/test_epub_audiobook_matcher.py` (one Windows path failure), the Audible connector's
tests (6 failures and 9 errors on Windows; not Media scope), `services/calibre-web-automated/tests` (needs Calibre-Web's
`cps`), imax `test_server.py`. None is a Media Home suite.

## 5a. Finding S1: member identity mapping (closed in code by #166)

**How members map** [offline, code]: Home reads `preferred_username`, `email` and now `sub` from the signed outpost token.
Jellyfin and Audiobookshelf: exact username; loose (case/Unicode) look-alikes refused as `case_or_unicode_mismatch` or
`ambiguous`; disabled/inactive accounts refused. Seerr requests: through the member's Jellyfin id (admins refused).
Shelfarr and Omnibus requests: the username. Komga: shared account for the catalogue; the member's own key by **verified**
e-mail. Member store, cache, Customize: the username.

**What Authentik allows** [host-read 2026-10-29, counts only]: Authentik 2026.5.6; `default_user_change_username=False`,
`default_user_change_email=False` (`change_name=True`, display only); enforced by `default-user-settings-authorization` on the
brand's `default-user-settings-flow`; 0 groups carry the `can-change-username/email` attributes; 0 usernames collide by case;
0 e-mails shared by two users; 19 users (16 active). Enrollment verifies the e-mail before any upstream account is made.
All Home proxy providers use `sub_mode=hashed_user_id` (stable per user, new for a recreated user).

| Scenario | Before #166 | After #166 |
|---|---|---|
| Member renames self or changes e-mail | **Not possible** (settings off, policy enforced) | same; and a rename would not carry the old name's data (binding) |
| Case or Unicode look-alike of another name | refused by Home's matcher | same |
| Two Authentik users with one e-mail (Komga key) | not possible today (0 shared; e-mail verified at enrollment) | same |
| **Recycled name**: a former member's username given to a new Authentik user (invitation, or admin rename) | **Exposed**: the new user got the old name's Shelfarr/Omnibus requests, Home profile and cache; Jellyfin/ABS too unless offboarding disabled them | **Refused**: a different `sub` gets the signed-out page and nothing is read; the owner releases the name deliberately (offboarding Step 4b) |
| **Enrollment collision**: an invitee picks the name of a Jellyfin account with no Authentik user | **Exposed** (live: 3 such Jellyfin accounts, 2 enabled, 0 admin; jellyfin-create treats "exists" as success) | **Refused at sign-up** once the blueprint is applied; the 2 enabled leftovers should be disabled or renamed first |

Proof [offline]: `webtests/test_web_identity_bindings.py` (a recreated `member-a` with a new `sub` sees exactly the
signed-out page on `/`, `/library`, `/continue`, `/me`, `/account` and search, and the mock Jellyfin receives zero requests;
`member-b` unaffected; release; a broken bindings file refuses everyone and recovers), `tests/test_identity_bindings.py`,
`tests/test_enrollment_username_available.py`. Existing members keep everything: no upstream change, and each name binds to
its current owner at the next sign-in.

**Remaining risk.** (1) Until #166 is deployed and the blueprint applied, both exposed paths stay open; each needs an
owner-issued invitation or an admin rename, so the practical risk today is low but real. (2) The binding is trust on first
use: a name first seen after deployment binds to whoever signs in with it first, which after the enrollment check is the
person the account was made for. (3) Upstream accounts an admin creates by hand outside enrollment are not checked: do not
create Jellyfin/ABS accounts by hand for members. (4) Shelfarr/Omnibus offboarding is still manual (offboarding Step 4).

## 5. Security findings matrix (Deliverable B)

| # | Finding | Sev. | Evidence | Remediation | Automated check | Remaining owner check |
|---|---|---|---|---|---|---|
| S1 | Member identity mapping by username/e-mail (section 5a) | P1 | [host-read] + [offline] | #166 binding + enrollment policy | yes (section 5a) | deploy #166; apply the blueprint; handle 2 leftover Jellyfin accounts |
| S2 | Everyday Komga key belongs to an ADMIN account | P1 | [recorded] AVR-782 | #162 guard + owner key swap | `AdminKeyRefused` tests | **O6** |
| S3 | Enrollment collision with a leftover upstream account | P1 | [host-read] 3 Jellyfin accounts without an Authentik user | #166 enrollment policy | `test_enrollment_username_available` | as S1 |
| S4 | Forged identity headers, duplicate/oversized/non-ASCII tokens, header smuggling | closed [offline] | `test_web_jwt_identity` (41), `test_web_identity`, `test_verified_identity` (43), wire tests over real sockets | — | yes | G1 production proof recorded 2026-10-27 [recorded] |
| S5 | Cross-member leakage of titles, progress, covers, cached pages; revocation during cache lifetime | closed [offline] | `test_web_isolation_h2`, `test_bench_cache_revocation`, `test_artwork_gateway` | — | yes | two-member live check (AVR-772) **not run** |
| S6 | Request brokers act as the member upstream, refuse admins, PRG without term in URL | closed [offline] | `test_broker_hardening`, `test_my_requests` | — | yes | first live check passed for watch requests [recorded] |
| S7 | Profile photo `/me/avatar` | closed [offline] | keyed by principal username, private no-cache + ETag | — | yes | inherits S1 |
| S8 | Home also holds a Komga **admin** key (provisioning, #134) and an ABS admin-capable token | accepted risk | owner decisions 2026-10-28 | keep; document | — | revisit post-launch |
| S9 | Seerr: CSRF protection and proxy trust | P1 for cutover | runbook only | AVR-348 | — | **O7** |

AVR-345 (independent identity-boundary review): offline evidence complete; production evidence = the
2026-10-27 G1 apply and owner E2 pass [recorded], plus the S1 read-only checks above. Closes when #166 is deployed.

## 6. Owner action list (Deliverable F)

In dependency order. "Prepared" = done by the agent; "You" = needs your hands or your approval.

| # | Action | Prepared | You | Done when |
|---|---|---|---|---|
| 1 | **Merge #161, #163, #166** | PRs, CI evidence (#164) | Approve the merges | main CI green |
| 2 | **Deploy S1** | compose line, fixed deploy script | Add `- HOME_IDENTITY_BINDINGS_FILE=/var/lib/avrana-home/identity_bindings.json` under `environment:` in `~/avrana/services/avrana-home/docker-compose.beta-live.yml`; run `scripts/deploy-home-beta.sh` (dry run), then `--apply` | `docker logs avrana-home-beta` shows `identity_bindings state=bound` after your first visit; Home works for you |
| 3 | **Leftover Jellyfin accounts, then the enrollment policy** | blueprint and test (#166) | In Jellyfin Dashboard, Users: find the accounts whose names are not Authentik users (3; one already disabled). Disable or rename the 2 enabled ones unless they are knowingly shared. Then copy `services/authentik/blueprints/avrana-enrollment.yaml` to the host's `~/avrana/services/authentik/blueprints/` (the worker applies it) | an invitation used with an existing Jellyfin name says "That username is taken" |
| 4 | **AVR-346 SMTP2GO**: rotate, then send yourself an invitation, a password reset and an alert | runbook `m0-smtp2go-email.md` | Rotate in SMTP2GO, enter at the hidden prompt, approve the worker recreate | three arrival timestamps |
| 5 | **AVR-347 akadmin MFA**: enrol two factors, store recovery codes | runbook `m0-authentik-admin-mfa.md`; username/e-mail change already verified off (nothing to do there) | Enrol, store, test a recovery sign-in | MFA prompt on akadmin sign-in |
| 6 | **AVR-350 restore drill** | runbook `m0-offhost-backup-restore.md` | Run `restore-test.py` against one representative backup | a restored file opens; times recorded |
| 7 | **Owner device pass** (journeys A to F) | checklist `docs/acceptance/MEDIA-2.0-RC1-CHECKLIST.md` | iPhone Safari, installed app and one TV, as a non-admin tester; two-member isolation check | no S0/S1 in the results template |
| 8 | **AVR-782 Komga viewer key**, then merge and deploy #162 | #162; owner steps in the issue | Create the non-admin Komga user and key, write `secrets/komga_token` at the hidden prompt; approve the deploy | Comics rows load; no `SharedKeyIsAdmin` in the log |
| 9 | **AVR-348 Seerr** CSRF and proxy trust | runbook `m0-seerr-csrf-proxy-trust.md` | Toggle in Seerr settings; test web, Pocket for Seerr and Home "Ask for a show" with the tester | all three still work, or a recorded exception |

Items 1 to 7 gate the member beta. 8 and 9 gate cutover, not the beta (8 shrinks blast radius; Home also holds the
provisioning admin key by decision). Optional: restart or remove `avrana-home-preview` (`avrana-boot-verify.service`).

## 7. Deployment and rollback packet (Deliverable D)

Tool: `scripts/deploy-home-beta.sh` (from #139/#142; #163 fixes). What it provides, checked against the brief:

| Requirement | Status |
|---|---|
| Deploy from a known Git revision | yes: `git archive <sha>` to `~/avrana-deploy/home-<sha>` [offline] |
| Preserve configuration and secrets | yes: symlinks `beta-live.env`, `secrets/`, `state/`; copies `~/avrana`'s compose; stops if the repo enables something new (exit 3) |
| Compose validation first | yes: `config -q`, `build`, `up -d --dry-run` |
| No unexpected network/volume change | yes (exit 5); **#163** adds "no other container" |
| Health verification | yes: waits up to 120 s for `healthy`, shows log errors, prints switches (never values) |
| Recoverable previous image | yes: `avrana-home-live:pre-<sha>`; **#163** stops a dry run from moving `:local` |
| Rollback commands | printed at the end (`docker tag … :local` then `up -d --no-build` in the previous export) |
| Evidence of running revision | container label `working_dir` = `home-<sha>`; **#163** prints it before and after |
| Another operator can follow it | yes, with `home-beta-live.md` "Routine deploys" |

Tested here: the remote half under a stub `docker` (dry run, apply, three refused plans) [offline]. **Not tested
here:** a real dry run on avrana, real Compose dry-run wording, the health wait against a slow start, rollback on
the host. The rollback was exercised for real on 2026-10-29 deploys [recorded], and
`home-rollback-rehearsal.md` (AVR-388) is the rehearsal script.

Owner-approved steps (each needs a yes at the time): `--apply`; any rollback; the AVR-782 key swap and restart.

## 8. Linear reconciliation proposal (not applied)

| Issue | Now | Proposed | Why |
|---|---|---|---|
| AVR-782 | Backlog | In Review, link #162 | guard written; owner key swap remains |
| AVR-386 | In Review | stay In Review; comment: CI red since #155, fixed by #161 | gate was hiding Home suites |
| AVR-587 | In Review | Done after #161 merges and main is green | web-tier deps are installed; suites now run |
| AVR-345 | In Progress | In Review with #166; Done after the S1 deploy and blueprint apply | S1 investigated and fixed (section 5a) |
| AVR-356 | Done | keep Done | G1 applied and signed off 2026-10-27 |
| AVR-772 | Backlog | Todo, M2; first item: two-member live leakage check after O3 | still no live two-member proof |
| AVR-381, AVR-382, AVR-378, AVR-379 | In Progress / In Review | Done (shipped and running on the beta) | live since 10-28/29; acceptance wording is "built", not "member-accepted" |
| AVR-380 Calibre-Web adapter | In Progress | keep; not RC1 scope unless Books uses it on the beta | — |
| AVR-388 | Backlog | In Progress with #163 | deploy/rollback tooling hardened |
| AVR-346, 347, 348, 350 | Todo/Backlog | priority Urgent, milestone M3, label owner | launch blockers O1, O2, O7, O4 |
| AVR-387 | Backlog | Todo after O1 to O5 | member beta |
| AVR-727, 728, 729, 730, 731, 735 (Concept K F-*) | Backlog, M1 | move to M4 | design choices, frozen for RC1 |
| AVR-781 | Backlog | do (cleanup) | — |
| AVR-375 | (trusted member identity) | link #166; acceptance now includes the `sub` binding | stable identity binding implemented |
| New | — | "A11Y-1: focused rail card not wholly visible at 390 px with 200% text" (UX sprint, P2) | pre-existing, section 4.1 |
| New | — | "N6 cache eviction test: bound by operations, not wall-clock" (P2) | flaky under load |
| New | — | "Offboarding: Shelfarr and Omnibus accounts" (M3, P2) | requests keyed by username |

## 9. Explicitly deferred beyond Media 2.0

Profile photos and Customize going live; Authentik Avrana-styled flows (#151); new shelves and discovery
(New for You tuning, comic logos from Komga covers); paste-your-own Komga key (rejected by owner); Trakt;
Omnibus per-member `canRequest` fork change; search index (AVR-503 unless
measurements say otherwise); every Concept K F-* owner choice.
