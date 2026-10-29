# Media 2.0 Release Candidate 1: state, evidence and go/no-go

Status: **engineering RC1 review packet, 2026-10-29.** Prepared by an agent under the RC1 sprint brief (feature
freeze). Nothing here was merged, deployed, rotated or changed on the host. One read-only `docker inspect` on
avrana established the running revision. Every claim is tagged with its evidence type:

- **[offline]**: tests in this repository with fixtures and fakes. Proves code behaviour, not live behaviour.
- **[host-read]**: read-only observation on avrana.
- **[recorded]**: an earlier deployment or owner report (PR body, runbook record, Linear). Not re-verified here.
- **[not run]**: nobody has checked it.

The member checklist is [../acceptance/MEDIA-2.0-RC1-CHECKLIST.md](../acceptance/MEDIA-2.0-RC1-CHECKLIST.md).

## 1. Go/no-go (three separate decisions)

| Decision | Verdict | Why |
|---|---|---|
| **Ready for engineering RC1 review** | **READY once the three RC1 PRs are merged** (proposed RC1 = `origin/main` 838fa70 + #161, #162, #163; checked together in draft #164) | Every offline suite passes on the integrated tree (section 4). CI on main has been red since #155 and has not run the Home suites since then; #161 fixes both. |
| **Ready for controlled member beta (3 to 5 people)** | **BLOCKED** | Owner blockers O1 to O5 (section 6): invite/reset e-mail never proven (AVR-346), Authentik admin MFA (AVR-347), username/e-mail change in Authentik unverified (finding S1), no restore drill (AVR-350), no real-device pass of the journeys. |
| **Ready for private production cutover** | **NO** | Needs the member beta itself (AVR-387), Seerr CSRF/proxy trust (AVR-348), an old-portal rollback rehearsal and owner sign-off (AVR-389). |

## 2. Codebase and deployment state (Deliverable A)

| Item | Value | Evidence |
|---|---|---|
| `origin/main` at sprint start | **0e8c330** (merge of #158, 2026-10-29 17:18Z) | [offline] `git log` |
| `origin/main` now | **838fa70**: #160 "quiet cards" (card markup and copy) was merged **during the freeze**, by another session or the owner | [offline] |
| Running Home beta (media-beta.avrana.net) | **0e8c330**, healthy, started 2026-10-29 17:18:30Z, from `~/avrana-deploy/home-0e8c330` | [host-read] container label `com.docker.compose.project.working_dir` |
| Previous exports kept on host | home-981357f, home-9eacec2, home-df5757d (rollback tags `avrana-home-live:pre-<sha>`) | [host-read] |
| Open PRs at sprint start | **none** | [offline] `gh pr list` |
| CI `offline-tests` on main | **failing since #155** (5227ac1, 08:28Z). Last green: 8aaa1b1 (#148). | [offline] GitHub Actions runs 40842428344 … 40920026425 |
| CI `beta-image` on main | green on 0e8c330 | [offline] run 40920026323 |

Live = main, so there is no code drift between Git and the beta. Configuration drift is by design: `~/avrana`'s
`docker-compose.beta-live.yml` is the record of what is switched on (requests, provisioning, member keys).

### 2.1 October 27 to 29 work, classified

All of #128 to #158 are **merged**. None is open, stacked or conflicting.

| PRs | Classification | Note |
|---|---|---|
| #128 provisioning, #130/#134/#135/#138 Komga member keys, #131/#144 requests, #132/#146/#149/#152/#154/#156/#157/#158 Home shelves, #133, #136, #139/#142 deploy script, #141/#143/#145, #148 | Merged and deployed (running 0e8c330) | [host-read] |
| #150 Me identity, #151 Authentik flows, #153 Customize | Merged and deployed, **dormant**: `HOME_SECURITY_FLOWS` and `HOME_MEMBER_STORE` unset, #151 blueprints not applied | [recorded] |
| #155 H3 hero | Merged, deployed; **broke CI** (static export) | fixed by #161 |
| #137 requests runbook, #140 CWA charset, #129 | Merged; host-side steps recorded in #137 | [recorded] |
| #147 | Closed, superseded by #146 (fix) + #148 (test) | — |

The **Listen/Read HTTP 500 of 2026-10-29** is fixed on main (#146 renamed the shadowing local; #148's
`webtests/test_web_released_fallback.py` fails on the old code). That test had **not run in CI** since #155 because
the repository suite failed first; it passes locally on the RC1 tree [offline].

### 2.2 Should anything recent be backed out for RC1?

No. #160 is a presentation change merged during the freeze; it is in the RC1 tree and its suites pass, but whether it is deployed was not checked after it merged, and the freeze should hold from here. Features that are on are stable in the offline suites; the dormant Me features cost nothing while their
switches are unset. Two recent additions are **not RC1 scope and should stay off**: Customize/profile photos
(member store, needs a writable state volume) and the Authentik Avrana-styled flows (#151). Turning them on is a
post-RC1 decision.

## 3. RC1 engineering changes

| PR | Purpose | Severity | Depends on | Tests | Recommendation |
|---|---|---|---|---|---|
| **#161** `fix/rc1-ci-gate` | Static export rewrites the H3 hero logo; `run_offline.py` runs every suite and fails at the end | P1 (CI gate integrity) | none | `test_home_static_export` 8/8, new `EverySuiteRunsTests` | **Merge first.** Then CI shows the true state of the Home suites again. |
| **#162** `fix/avr-782-komga-admin-guard` | Real mode refuses an ADMIN everyday Komga key (Comics unavailable, logged) | P1 (least privilege) | **Owner key swap first** (O6) | `tests/test_komga.py` 58/58 incl. 4 new | Merge any time; **deploy only after** `secrets/komga_token` is a regular account's key. |
| **#163** `fix/rc1-deploy-dry-run` | Dry run no longer leaves `avrana-home-live:local` on an untested build; a plan touching another container stops; prints running revision | P1 (rollback safety) | none | new `tests/test_deploy_home_beta.py` 3/3 (stub docker) | Merge; first real use is a dry run on avrana. |
| #164 `rc1/integration` | CI evidence for the three together on 838fa70 | — | #161–#163 | full CI | **Do not merge**; close after the three merge. |
| #165 | RC1 packet (this file and the checklist) | — | — | docs | Merge after review. |

## 4. Test evidence (Deliverable C)

Revision: `rc1/integration` = `origin/main` 838fa70 plus #161, #162, #163. Windows 11, Python 3.12.3, the CI
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
`beta-image` **success**. The job runs every suite twice, the second time inside `unshare --net` with
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
in #162 8c08e89). Running suites that start mock servers concurrently on one machine gives port clashes; run them
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

## 5. Security findings matrix (Deliverable B)

| # | Finding | Sev. | Evidence | Remediation | Automated check | Remaining owner check |
|---|---|---|---|---|---|---|
| S1 | Home maps members to Jellyfin/ABS by the Authentik **username** and to their own Komga key by **e-mail** (both from the signed JWT). If members can change their own username or e-mail in Authentik's user settings, one member could take another's mapping and read their Continue, Komga On Deck, requests and profile. The repo has no record that self-service username/e-mail change is off. | **P0 if enabled**, else closed | [offline] `principal.py:330`, `member_keys.py` | Owner: Authentik Admin → System → Settings: "Allow users to change username" and "…change e-mail" **off**; confirm the user-settings flow's prompt has no username/e-mail field. Post-RC1: map by the stable `sub` claim. | Not automatable offline | **O3**: screenshot or boolean evidence |
| S2 | Everyday Komga key belongs to an ADMIN account | P1 | [recorded] AVR-782 | #162 guard + owner key swap | `AdminKeyRefused` tests | **O6** |
| S3 | Invitee could register an Authentik username equal to an existing Jellyfin/ABS account that is not theirs (exact-name mapping) | P1 | [offline] mapping rule | Owner: before each invite, list upstream usernames without an Authentik match; reserve or rename them | — | part of **O4** |
| S4 | Forged identity headers, duplicate/oversized/non-ASCII tokens, header smuggling | closed [offline] | `test_web_jwt_identity` (41), `test_web_identity`, `test_verified_identity` (43), wire tests over real sockets | — | yes | G1 production proof recorded 2026-10-27 [recorded] |
| S5 | Cross-member leakage of titles, progress, covers, cached pages; revocation during cache lifetime | closed [offline] | `test_web_isolation_h2`, `test_bench_cache_revocation`, `test_artwork_gateway` | — | yes | two-member live check (AVR-772) **not run** |
| S6 | Request brokers act as the member upstream, refuse admins, PRG without term in URL | closed [offline] | `test_broker_hardening`, `test_my_requests` | — | yes | first live check passed for watch requests [recorded] |
| S7 | Profile photo `/me/avatar` | closed [offline] | keyed by principal username, private no-cache + ETag | — | yes | inherits S1 |
| S8 | Home also holds a Komga **admin** key (provisioning, #134) and an ABS admin-capable token | accepted risk | owner decisions 2026-10-28 | keep; document | — | revisit post-launch |
| S9 | Seerr: CSRF protection and proxy trust | P1 for cutover | runbook only | AVR-348 | — | **O7** |

AVR-345 (independent identity-boundary review): offline evidence complete; production evidence = the
2026-10-27 G1 apply and owner E2 pass [recorded]. Remaining: S1 and S3 are identity questions the earlier review
did not cover.

## 6. Owner action list (Deliverable F)

Mandatory before the member beta, in order:

1. **O1 · AVR-346 SMTP2GO**: rotate, then prove invite, reset and alert e-mail arrive (runbook
   `m0-smtp2go-email.md`). Evidence: three timestamps. Blocks invites and recovery (journeys A, D).
2. **O2 · AVR-347 akadmin MFA**: enrol two factors, store recovery codes, decide P1 to P6 (`m0-authentik-admin-mfa.md`).
3. **O3 · S1 username/e-mail change**: in Authentik check the two settings above are off and the user-settings
   flow cannot write `username` or `email`. Five minutes. Rollback: re-enable.
4. **O4 · AVR-350 restore drill**: B2 catch-up ran 2026-10-27 [recorded]; still needed: one representative
   restore (`m0-offhost-backup-restore.md`). Plus S3: compare upstream usernames to Authentik users before inviting.
5. **O5 · Device pass**: run journeys A to F on your iPhone (Safari and installed PWA) and one TV client with a
   non-admin tester (checklist, section "Owner physical-device tests").

Required before cutover, not before the beta:

6. **O6 · AVR-782** Komga viewer account and key (owner steps in the issue), then deploy #162.
7. **O7 · AVR-348** Seerr CSRF/proxy trust with an iPhone.
8. **O8 · AVR-363** invite onboarding end to end (depends on O1).
9. **O9 · AVR-389** cutover plan with old-portal rollback, after AVR-387.

Optional hardening: restart or remove `avrana-home-preview` so `avrana-boot-verify.service` stops failing
[recorded 2026-10-27]; alert mail (`services/backups/.env.alert`) after O1.

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
| AVR-345 | In Progress | stay; add S1/S3 as remaining scope | identity questions not in the 10-14 review |
| AVR-356 | Done | keep Done | G1 applied and signed off 2026-10-27 |
| AVR-772 | Backlog | Todo, M2; first item: two-member live leakage check after O3 | still no live two-member proof |
| AVR-381, AVR-382, AVR-378, AVR-379 | In Progress / In Review | Done (shipped and running on the beta) | live since 10-28/29; acceptance wording is "built", not "member-accepted" |
| AVR-380 Calibre-Web adapter | In Progress | keep; not RC1 scope unless Books uses it on the beta | — |
| AVR-388 | Backlog | In Progress with #163 | deploy/rollback tooling hardened |
| AVR-346, 347, 348, 350 | Todo/Backlog | priority Urgent, milestone M3, label owner | launch blockers O1, O2, O7, O4 |
| AVR-387 | Backlog | Todo after O1 to O5 | member beta |
| AVR-727, 728, 729, 730, 731, 735 (Concept K F-*) | Backlog, M1 | move to M4 | design choices, frozen for RC1 |
| AVR-781 | Backlog | do (cleanup) | — |
| New | — | "Map members by `sub`, not username/e-mail" (M4, P2) | defence in depth for S1 |

## 9. Explicitly deferred beyond Media 2.0

Profile photos and Customize going live; Authentik Avrana-styled flows (#151); new shelves and discovery
(New for You tuning, comic logos from Komga covers); paste-your-own Komga key (rejected by owner); Trakt;
Omnibus per-member `canRequest` fork change; mapping by `sub` (post-RC1); search index (AVR-503 unless
measurements say otherwise); every Concept K F-* owner choice.
