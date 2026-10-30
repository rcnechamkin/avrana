# What, precisely, prevents Avrana Media 2.0 from entering closed beta

Status: **final, 2026-10-30; audit results folded in. The verdict is in
[MEDIA-2.0-RC2-READINESS.md](MEDIA-2.0-RC2-READINESS.md).** Baseline `2cb228f` = main = live beta.

"Closed beta" means: 3 to 5 consenting, non-admin members, invited by e-mail, using the live beta at
media-beta.avrana.net on their own phones and TVs, unaided (Linear AVR-387). Everything below is sorted by who
can remove it. An item is a **blocker** only if inviting a member without it would expose someone's data, strand a
member with no way back, or make the invitation itself impossible.

## 1. Engineering deficiencies (removable in this sprint, on draft branches)

| # | Item | Evidence today | Blocker? | Sprint action |
|---|---|---|---|---|
| E1 | Confirmed P0/P1 defects in enabled member journeys | audits done: **0 P0**; P1 = S-01 (Komga password reset on first sign-in; owner decision pending), S-07/AVR-782, S-17/AVR-348 (known gates) | S-01 yes | S-01 awaits the owner's (a)/(b); every adjudicated P2 on a member journey is fixed + verified (#168–#178) |
| E2 | A11Y-1: a focused rail card is not wholly visible at 390 px with 200 % text | reproduced (U-03): 76–78 clipped stops at 360/390/430 @ 200 %, 9 at 320 @ 100 % | P2 accessibility; fixed because it is on the phone journey every member takes | CSS-only fix, 0 clipped stops at every size, `home.js` untouched; verification X10 running |
| E3 | #162 Komga admin-key guard is unmerged; the everyday key is still the admin's | PR #162 (head 8c08e89); its red CI is the pre-#161 static-export failure, merges cleanly with main | not a beta blocker (RC1: shrinks blast radius; S8 accepted risk) but must be merge-ready the day the owner swaps the key | verify the guard, get the PR green, leave merge+deploy owner-gated |
| E4 | #167 enrollment-blueprint drift: the repo file would, if applied blindly, undo the LDAP switch and the admin membership | PR #167 (0593910, CI clean) | not a member blocker, but a latent operational hazard | document in the state report; recommend merging #167 (repo-only) so Git matches live; never apply from Git |
| E5 | Stale status headers claim Home is "not deployed, synthetic only" (`services/avrana-home/README.md`, `docs/design/HOME-APP.md`, `CONCEPT-K-FOLLOW-UPS.md`) | baseline §4 | no | fixed: draft #175 (14 files, + S-10 rollback caveat) |
| E6 | RC1 packet (#165) is unmerged; this sprint's packet supersedes it | PR #165 | no | fold into this packet; propose closing #165 or merging it first |
| E7 | Regression coverage for the beta journeys (Listen/Read 500 class in degraded states, request idempotency, rail focus, revocation at page level, Quick Connect errors) | coverage review done; no branch protection or required checks on `main` | no, but each fix in E1 ships with its test | added: #177 degraded matrix (catches the #146 mutant), #173 journey pins, #169 order/wall-clock, plus a test in every fix PR |

## 2. Owner-controlled acceptance tasks (the agent prepares; only the owner can produce the evidence)

Dependency order follows `docs/runbooks/README.md` and RC1 §6.

| # | Task | Linear | Runbook / packet | Why it gates the member beta | Evidence that exists | Evidence missing |
|---|---|---|---|---|---|---|
| O1 | SMTP2GO rotation; one real invitation, one password reset, one alert arrive | AVR-346 (Todo) | `docs/runbooks/m0-smtp2go-email.md` | An invitation **is** the beta; recovery (journey D) needs the reset mail | none recorded | three arrival timestamps |
| O2 | akadmin MFA enrolled, recovery codes stored, recovery sign-in tested | AVR-347 (Backlog) | `m0-authentik-admin-mfa.md` | The admin account that can read every member's identity must not be password-only once outsiders sign in | username/e-mail self-service verified off 2026-10-29 | MFA prompt on akadmin |
| O3 | Off-host restore drill | AVR-350 (Backlog) | `m0-offhost-backup-restore.md` | Member state now exists (bindings file, Komga member keys): a restore must be known to work before it holds strangers' data | backup tooling tests [offline] | one restored file opens; times recorded |
| O4 | Non-admin tester signs in to the deployed 2cb228f; owner device pass, journeys A–F; **two-member isolation check** | AVR-585 (In Review since 2026-10-30 04:15Z), AVR-479 (In Review since 2026-10-30 04:15Z), AVR-772 (Backlog) | `docs/acceptance/MEDIA-2.0-RC2-ACCEPTANCE.md` (this sprint) | The only proof that real sign-in, real libraries, real handoffs and real isolation work; S1 bindings deployed but **no second member has signed in since** | owner's own sign-in after the S1 deploy [recorded] | the filled results template |
| O5 | Member-facing rules: support contact, privacy/house rules, welcome text, consent | AVR-458 (Todo, High), AVR-361 (In Review), AVR-363 (Backlog) | `docs/member/*` drafts | Cannot invite anyone without telling them where help is and what is collected | drafts exist | owner decisions and the chosen contact |
| O6 | Komga viewer key swap, then merge+deploy #162 | AVR-782 (Backlog) | issue + PR #162 | RC1 classed it as cutover, not beta; recommended before beta because Comics is on for members | guard code [offline] | key swapped; no `SharedKeyIsAdmin` in the log |
| O7 | Seerr CSRF protection and proxy trust | AVR-348 (Backlog) | `m0-seerr-csrf-proxy-trust.md` | Cutover prerequisite; watch requests are already on in the beta | none | the three-client matrix |
| O8 | Rollback rehearsal of the Home beta | AVR-388 (Backlog) | `home-rollback-rehearsal.md`; rollback exercised for real on 2026-10-29 deploys [recorded] | Cutover; for the beta the `pre-2cb228f` image and printed commands exist | deploy records | a timed rehearsal |

**Member-beta prerequisites:** E1, E2, O1, O2, O3, O4, O5 (O6 strongly recommended).
**Production-cutover prerequisites (later):** O6, O7, O8, AVR-389, plus the member results (AVR-387).

## 3. Linear statuses that do not match the evidence (reconciled, not yet applied)

| Issue | Linear | Evidence | Proposed |
|---|---|---|---|
| AVR-479 handoff validation | In Review (was Done 2026-10-28 → 04:15Z today) | no device evidence in repo or Linear | keep In Review; closes with O4 |
| AVR-585 device/a11y acceptance | In Review (was Done) | same | keep In Review; closes with O4 |
| AVR-378/379/381/382 adapters, Continue, Recent | In Progress / In Review | merged, deployed, enabled | Done (built), with the note that member acceptance is AVR-387 |
| AVR-386 CI gates | In Review | offline gates run in CI since #161; browser/axe layer manual | stay In Review until the browser layer or its waiver is recorded |
| AVR-587 web-tier deps in CI | In Review | fixed by #161; main green | Done |
| AVR-345 identity boundary review | In Progress | S1 closed in code and deployed; two-member live proof missing | In Review; Done with O4 |
| AVR-782 | Backlog | #162 drafted | In Review, link #162 |
| AVR-388 | Backlog | #163 merged; rollback exercised | In Progress |
| AVR-346/347/348/350 | Todo/Backlog, High | launch blockers | Urgent, owner label |
| M1 42 %, M2 42 %, M3 14 % | — | M1/M2 count document closures | leave; the percentages are not evidence |

No Linear state is changed by this sprint without the owner's word; the agent may add evidence comments and create
issues for new confirmed defects.
