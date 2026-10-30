# Media 2.0 pre-closed-beta quality sprint: release candidate state report

Status: **baseline taken 2026-10-29 (evening, Pacific); updated as the sprint runs.** Prepared under the
"Pre-Closed-Beta Quality, Reliability & UX/UI Polish Sprint" brief (feature freeze; owner-gated merges, deploys
and live changes). Nothing here was merged, deployed, rotated or changed on the host. Evidence tags as in
[MEDIA-2.0-RC1.md](MEDIA-2.0-RC1.md) (draft PR #165): **[offline]** fixtures and fakes, **[host-read]** read-only
observation on avrana, **[recorded]** an earlier report, **[not run]**.

## 1. Exact starting revision

| Item | Value | Evidence |
|---|---|---|
| `origin/main` at sprint start | **`2cb228fbfdae596ef3da1754afe88e48b1556552`** (merge of #166, 2026-10-29) | [offline] `git fetch; git rev-parse origin/main` |
| Running Home beta (`avrana-home-beta`, media-beta.avrana.net) | image `avrana-home-live:local` (id 6ec60b41, built 2026-10-29 17:31 PDT) from export `/home/cody/avrana-deploy/home-2cb228f`; container created 2026-10-30T00:31Z, healthy | [host-read] `docker inspect` labels `com.docker.compose.project.working_dir`; `docker ps` |
| Rollback images kept on host | `pre-2cb228f`, `pre-50a8761`, `pre-838fa70`, `pre-0e8c330`, `pre-981357f`, `pre-9eacec2`, `pre-df5757d`, `pre-c15176b`, `pre-902790e` | [host-read] `docker images avrana-home-live` |
| CI on `2cb228f` | `offline-tests` **success** (run 40973080456); `beta-image` **success** (run 40973080451) | [offline] GitHub Actions |
| CI history before that | 838fa70 offline-tests **failure** (static export, from #155); 50a8761 and 385f227 **cancelled** at the 10-minute cap; 11fc711 (#161) success | [offline] |
| Local toolchain for this sprint | Windows 11, Python 3.12.3 (`../.venv-media`: fastapi 0.115.6, starlette 0.41.3, uvicorn 0.34.0, Jinja2 3.1.5, httpx 0.28.1), Node 22.22.2, `../.ui-tooling` (@playwright/test, axe-core), Playwright Chromium builds present | [offline] |

**Live = main.** There is no code drift between Git and the beta at the start of this sprint.

## 2. Recent RC1 work, by state

The five states are distinct: **source** (exists on a branch), **main** (merged), **deployed** (in the running
`2cb228f` image), **enabled** (its switch is on in the live compose/env), **verified** (someone checked the member
behaviour, on fixtures or live).

| PR | What | Source | Main | Deployed | Enabled | Verified |
|---|---|---|---|---|---|---|
| #159 Round 10 Home hero | framed living window, scrolled strip | yes | 50a8761 | yes | always on with `HOME_SECTIONS` | [offline] web tests; axe pass on the static export [recorded]; **no phone check** |
| #160 Quiet cards | title + glance line only | yes | 838fa70 | yes | always | [offline] |
| #161 CI gate | every suite runs, 20-min timeout | yes | 11fc711 | n/a (CI) | n/a | main CI green at 2cb228f |
| #162 Komga admin-key guard (AVR-782) | ADMIN everyday key → Comics unavailable | draft, head 8c08e89 | **no** | **no** | n/a | [offline] 58 Komga tests on the branch; CI state `UNSTABLE` on the PR (re-check) |
| #163 Deploy dry-run safety | dry run keeps the running tag; plan beyond Home stops | yes | 385f227 | script on host side only; used for the 2cb228f deploy [recorded] | n/a | [offline] `test_deploy_home_beta` |
| #164 Integration evidence | main + #161 #162 #163 #166 | draft, 25916c8 | never (by design) | — | — | CI green on the branch [recorded] |
| #165 RC1 docs | report + member checklist | draft, 2ba44ca | **no** (`docs/release/`, `docs/acceptance/MEDIA-2.0-RC1-CHECKLIST.md` do not exist on main) | — | — | docs |
| #166 Seeded identity bindings, retired names | S1 closure | yes | 2cb228f | **yes** | **yes**: `HOME_IDENTITY_BINDINGS_FILE` set; `state/identity_bindings.json` (2,179 bytes) and `.lock` present; blueprint applied [recorded 2026-10-29] | [offline] 25 unit + 12 web + real-Authentik workflow 17/17 [recorded]; owner sign-in verified [recorded]; **two-member isolation not run** |
| #167 Enrollment blueprint drift | repo file brought to the live file | draft, 0593910 | **no** | the *live* file is ahead of the repo | n/a | documented in the PR; `jellyfin-ldap.yaml`, `authentik-home-beta.yaml` still live-only |

## 3. What is switched on in the live beta (names only, read 2026-10-29) [host-read]

Compose: `HOME_UPSTREAM_MODE=real`, `HOME_GATES_VERIFIED`, `HOME_IDENTITY_MODE=jwt_required`, `HOME_JWT_SECRET_FILE`,
`HOME_IDENTITY_BINDINGS_FILE`, `HOME_HEALTH_DETAIL=off`, `HOME_SECTIONS=on`, Jellyfin / Audiobookshelf / Komga /
Calibre-Web base URLs and credential files, `KOMGA_MEMBER_KEYS_FILE` (file present, 125 bytes), `KOMGA_ADMIN_TOKEN_FILE`
(provisioning), both `*_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS`, `HOME_BOOK_REQUESTS=on` + Shelfarr, `HOME_WATCH_REQUESTS=on`
+ Seerr, `HOME_COMIC_REQUESTS=on` + Omnibus; `./state` mounted read-write; networks include `shelfarr_default`, `omnibus`,
`docker_request-backend`. Env file: `HOME_JWT_ISSUER`, `HOME_JWT_AUDIENCE`, `HOME_ALLOWED_USERS`, `HOME_PROVISION_ACCOUNTS`.

**Dormant (merged, deployed, switched off):** `HOME_MEMBER_STORE` (Me → My profile, Customize persistence, #150/#153),
`HOME_SECURITY_FLOWS` and the #151 Authentik flows (blueprints not applied), `HOME_SHELFARR_PROVISION`, `HOME_SEERR_PROVISION`,
`HOME_LIBRARY_IDS_FILE` (catalogue index "Already in" claims), `HOME_MOTION_PROPOSAL`. The sprint audits their code for
regressions only; none is enabled.

The repository's `docker-compose.beta-live.yml` and `beta-live.env.example` describe these switches as commented-out
options; the live file has them on. That is configuration drift by design (the live compose is the record), not
code drift.

## 4. Stale documentation and misleading statuses found at baseline

| Where | Says | Actually |
|---|---|---|
| `services/avrana-home/README.md` | "not built into an image, not deployed, synthetic data only … nothing here may read real member data" | Deployed as the live-data beta since AVR-771; reads the allowed testers' real libraries |
| `docs/design/HOME-APP.md` header | "proposed, not built into an image, not deployed, 2026-10-12" | as above |
| `docs/design/CONCEPT-K-FOLLOW-UPS.md` | "Nothing here is merged to main, deployed, or tested on a phone" | Concept K merged (AVR-713 Done) and deployed; phone test still open |
| Linear AVR-479 "validate media handoff and recovery across real client workflows" | **Done** | memory and the RC1 packet record no device acceptance; AVR-585 (device/a11y acceptance) also **Done** while the owner device pass (O5) is listed as not run. Treat both as documentation-only closures until the owner confirms |
| Linear AVR-378/379/380/382 adapters | In Progress | merged and deployed; statuses stale |
| Linear AVR-386 CI gates | In Review | the gates run in CI since #161; browser/axe layer still manual |
| Linear AVR-782 | Backlog | PR #162 drafted; owner key swap pending |
| Linear M1 milestone 42 %, M2 42 % | — | both include issues closed by documents, not devices |

## 5. Known limitations at baseline

- No owner device pass, no two-member isolation run, no member beta (RC1 O1–O7 open).
- Browser checks are Chromium on a static export of synthetic data; Safari, VoiceOver, installed PWA, TV clients are
  physical gates.
- A11Y-1 (focused rail card not wholly visible at 390 px / 200 % text) is open, P2.
- Komga everyday key is still the admin account's (AVR-782); #162 not merged, swap not done.
- Suites CI does not run: `scripts/test_offboard.py` (host-only), `scripts/test_epub_audiobook_matcher.py`, Audible
  connector tests, `services/calibre-web-automated/tests`, imax `test_server.py`.

## 6. Sprint outcome (2026-10-30)

- **Audits:** functional, UX/UI, security & reliability, test coverage, all read-only on `2cb228f`
  (`docs/audits/2026-10-29-rc2-*.md`). **0 P0.** P1: S-01 (beta-blocking, owner decision), S-07/AVR-782 and
  S-17/AVR-348 (known deferred gates). Adjudicated inventory: [MEDIA-2.0-RC2-DEFECT-INVENTORY.md](MEDIA-2.0-RC2-DEFECT-INVENTORY.md).
- **Fixes:** 13 ledger rows, each implemented in its own worktree and verified by a separate Opus agent that
  reproduced the defect on `2cb228f` first ([MEDIA-2.0-RC2-FIX-LEDGER.md](MEDIA-2.0-RC2-FIX-LEDGER.md)). Draft PRs
  #168–#181. Two first versions were rejected and reworked
  (X1 keyed on the wrong tile; X4 took the lock twice); one for line endings (X9).
- **Five states after the sprint:** every fix is *implemented* and *verified* on synthetic stacks; all 13 are *merged*
  (owner-authorised train 2026-10-30, `main` = `305964a`); none is *deployed* or *enabled*: the live beta is still
  exactly `2cb228f`.
- **Verdict:** CONDITIONAL GO, [MEDIA-2.0-RC2-READINESS.md](MEDIA-2.0-RC2-READINESS.md); the conditions are the
  owner's acceptance tasks O1–O5 plus the S-01 decision.

