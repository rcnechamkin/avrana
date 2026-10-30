# Media 2.0 closed-beta release readiness recommendation

Status: **written 2026-10-30 at the end of the pre-closed-beta quality sprint. Verdict for the build on the live
beta, `2cb228f`, with the sprint's verified fixes on draft branches, none merged, none deployed.**
Companion documents: [state report](MEDIA-2.0-RC2-STATE.md), [critical path](MEDIA-2.0-CLOSED-BETA-CRITICAL-PATH.md),
[defect inventory](MEDIA-2.0-RC2-DEFECT-INVENTORY.md), [fix ledger](MEDIA-2.0-RC2-FIX-LEDGER.md),
[UX/UI quality report](MEDIA-2.0-RC2-UX-QUALITY.md), [acceptance packet](../acceptance/MEDIA-2.0-RC2-ACCEPTANCE.md),
the four audits in `docs/audits/2026-10-29-rc2-*.md` and the verifier verdicts in `docs/audits/verify/`.

## 1. Verdict: **CONDITIONAL GO** for a 3–5 member closed beta

Conditional on the items in section 3, every one of which is either a one-line owner decision, an owner-run
physical check, or the merge-and-deploy of fixes that have already been independently verified. **No engineering
unknown remains between the live build and a member beta.** What remains is evidence only the owner can produce
(e-mail arrives, MFA prompts, a restore opens, two phones see two different libraries) and one policy decision
(S-01).

It is **not a GO** today because:
- **S-01** (P1, beta-blocking): Home's Komga key provisioning resets an existing member's Komga password to a
  discarded value the first time Home sees them, and the enrollment flow set that password on purpose for OPDS
  reader apps (`provision.py:219-230` vs `avrana-enrollment.yaml:356-399`). A member who followed the OPDS
  instructions would be locked out of their reader app without explanation. Zero members have hit it yet (0 komga
  provision lines in 72 h of the live log, read-only), because no non-admin member has signed in since the switch
  went on. Fix is trivial either way; the choice is the owner's: (a) switch Komga key provisioning off for the beta
  (drop `komga` from `HOME_PROVISION_ACCOUNTS`; per-member On Deck falls back to the shared key), or (b) a code guard
  that never resets an existing account's password without an explicit opt-in flag.
- The **two-member isolation test** (acceptance §3, I1–I6) has never been run on the deployed build. The S1 seeded
  bindings fix (#166) is deployed and its protections are present in the code (security audit, S-01..S-18 trace),
  but no second member has signed in since, so the live evidence does not exist.
- **O1–O3** (SMTP2GO rotation, akadmin MFA, off-host restore drill) have no recorded evidence. An invitation *is*
  the beta; the admin that can read every member's identity must not be password-only once outsiders sign in; member
  state (bindings file, Komga member keys) now exists on the host and a restore has never been proved.

It is **not a NO-GO** because the audits found **no P0**, no cross-member data exposure in code or fixtures, no
journey that strands a member, 0 serious/critical axe findings across 1,675 views, and every defect adjudicated as
beta-relevant has a verified fix on a draft branch.

## 2. What precisely prevents closed beta, and what we eliminated

| # | Blocker | Who removes it | State at sprint end |
|---|---|---|---|
| B1 | S-01 Komga password reset on first sign-in | owner decision (a)/(b), then a ≤10-line change | **open: awaiting the decision** (both options prepared in the ledger) |
| B2 | Two-member isolation never run on the live build | owner (acceptance §3) | packet written; needs T1/T2 non-admin accounts |
| B3 | E-mail path unproven (O1, AVR-346) | owner | runbook exists; three timestamps missing |
| B4 | akadmin without MFA (O2, AVR-347) | owner | runbook exists |
| B5 | Restore never drilled with member state present (O3, AVR-350) | owner | #171 adds Home `state/` + live compose to the backup allowlist (verified); the live backup script must be synced first |
| B6 | Member rules: support contact, what is collected, welcome text (O5, AVR-458/361/363) | owner | drafts exist in `docs/member/` |
| B7 | Owner device pass A–F on a real phone / PWA / TV (O4, AVR-585/479) | owner | packet written with expectations per step; Linear shows In Review, no evidence attached |
| — | U-01/U-02 hero under Reduce Motion / contrast (was beta-blocking) | **eliminated** | #178 verified |
| — | RC1 A11Y-1 rail focus at 200 % text | **eliminated pending X10 verdict** | CSS-only, implementer 0 clipped stops at every size |
| — | Listen/Read 500 class regression coverage | **eliminated** | #177 catches the #146 mutant |
| — | S-02 destructive-first Komga provisioning, hourly retries, race | **eliminated** | #172 verified (single lock hold, terminal `failed_after_reset`) |
| — | S-04/S-11 Home state absent from backups | **eliminated** | #171 verified |
| — | F-01/F-02/F-03 member-visible library/label/search faults | **eliminated** | #174, #170, #168 verified |
| — | Degraded-state bare headings, duplicate heading id | **eliminated** | #176 verified |
| — | Stale "not deployed" docs that would mislead the owner during an incident | **eliminated** | #175 |

## 3. Conditions, in dependency order

**Before any invitation**
1. Decide S-01 (a) or (b); the agent implements the chosen one within the hour, verified, as a draft PR.
2. Merge the verified drafts in the order in section 4 and deploy one image with `scripts/deploy-home-beta.sh`
   (rollback tag `pre-<sha>` is printed; never roll back past `pre-2cb228f`, see the S-10 caveat in #175).
3. O1 SMTP2GO: one invitation, one reset, one alert arrive (three timestamps in `docs/findings/`).
4. O2 akadmin MFA on, recovery code tested.
5. O3 restore drill after syncing the live backup script with #171 (one restored file opens).
6. O5 member rules decided (support contact, collected data sentence, welcome text).
7. O4 acceptance packet 0.1–0.5, journeys A–F on the owner's phone and TV, **two-member isolation I1–I6** with
   two non-admin accounts, R1–R3. Release rule: no S0, no S1 on A/B/C/D/F; I1–I6 all pass.

**Strongly recommended before any invitation, not strictly blocking**
8. O6 Komga viewer key swap, then merge + deploy #162 (AVR-782): Comics is on for members and the everyday key is
   still the admin's. RC1 classed it as cutover; the security audit (S-07) keeps that classification but notes the
   blast radius shrinks to nothing with a ten-minute owner task.
9. Merge #167 (enrollment blueprint drift, repo-only, never apply from Git) so Git matches live before anyone
   debugs enrollment under pressure.

**Before production cutover (later, AVR-389)**
10. O7 Seerr CSRF/proxy trust (AVR-348), O8 timed rollback rehearsal (AVR-388), member results (AVR-387).

## 4. Recommended merge order for the verified drafts

All are off `2cb228f`; the orchestrator checked `git merge-tree` where two branches touch one file.

1. #175 docs (no code) · 2. #169 tests · 3. #173 tests · 4. #168 Seerr timeout · 5. #170 comics chip ·
6. #174 Komga e-book library · 7. #172 provisioning hardening · 8. #171 backups + compose ·
9. #178 hero modes (CRLF-clean) · 10. X10 rail focus (after verification) · 11. #176 headings ·
12. #177 degraded matrix — **when #177 merges after #176, remove its two `@expectedFailure` markers and the
`DEGRADED_RAILS` excuse; `webtests/plan_adapters.py` is identical on both** · 13. phone layout (U-05/06/08, in progress)
· 14. the S-01 change.

An integration worktree with all of them, the full offline suite and the web tier (`run_offline.py`,
`run_web_tests.py` with `AVRANA_REQUIRE_DEPS=1`) is section 5's open item; the per-PR GitHub Actions runs are the
evidence until then.

## 5. Evidence quality and what was not done

- **Confirmed in code and on synthetic stacks, verified by an agent that did not write the fix:** every row in the
  ledger marked ACCEPT. Each verifier reproduced the defect on `2cb228f` first.
- **Read-only on the live host:** container revision and switch names, 72 h of logs for Komga provisioning and watch
  searches (0 and 0). No live member data, credentials or blueprint were touched; the Komga key swap and the
  blueprint apply were reviewed, not performed.
- **Not done:** integration run of all branches together (open); the full offline suite on every branch (verifiers
  ran the neighbouring modules, CI runs the suite per PR); Safari / VoiceOver / installed PWA / TV (physical, O4);
  request ask pages on the dev stack (brokers off); Linear status changes (none made; reconciliation table in the
  critical path for the owner to apply).
- **Linear is tracking, not proof:** AVR-479 and AVR-585 moved Done → In Review during the sprint (not by the
  agent) with no device evidence attached; the critical path §3 lists every mismatch.

## 6. Owner decisions outstanding (one line each)

S-01 (a)/(b) · S-03 Komga key by e-mail vs username · S-05 token lifetime vs revocation latency · D-05 request
timeout copy · U-12/U-13/U-14/U-15 design questions · U-09 chip wrap vs scroll · Q1/F-9 title action wording ·
"Home is stateless" wording now that `state/` holds bindings and keys · close or merge RC1 packet #165.
