# Media 2.0 pre-closed-beta sprint: master defect inventory

Status: **adjudicated 2026-10-30 (early, Pacific) from four independent read-only audits of `2cb228f`
(functional, UX/UI, security & reliability, test coverage: `docs/audits/2026-10-29-rc2-*.md`) and the defects the
new regression tests surfaced. Dispositions are updated by the sprint as fixes are verified; the fix ledger is
[MEDIA-2.0-RC2-FIX-LEDGER.md](MEDIA-2.0-RC2-FIX-LEDGER.md).** Evidence for each row is in the source report under
its id; this page is the deduplicated, prioritised view. No production member names, titles or credentials appear in
any evidence artifact (synthetic fixtures only).

Classification: CONFIRMED (reproduced by a failing test, observable interaction or independently supported trace),
PROBABLE (strong code evidence, reproduction incomplete), UNVERIFIED, DESIGN QUESTION, KNOWN/DEFERRED. Severity per
the brief: P0 beta-blocking (disclosure, broken authz, unrecoverable access, entitled library unreachable without
fallback); P1 major; P2 polish/usability; P3 cosmetic.

## 0. The answer in one table

| | Count |
|---|---|
| **P0** | **0** |
| P1 | 3: S-01 (beta-blocking, owner decision), S-07/AVR-782 and S-17/AVR-348 (both cutover gates, known) |
| P2 | 22 (10 confirmed and fixed or in review; the rest polish, design questions or deferred) |
| P3 | 24 |
| Beta-blocking after adjudication | **S-01, U-01, U-02** (U-01/U-02 are two-line CSS faults, **fixed and verified: #178**) |

Duplicates merged: S-12 = T-20 (`test_hung` order dependence); S-13 = F-05 (local timing flakes, not product);
S-14 + U-22 + baseline §4 (stale docs); S-11 folded into the S-04 fix; U-20 is the performance baseline, not a defect.

## 1. Beta-blocking

| Id | Component | Class | Sev | Finding | Disposition |
|---|---|---|---|---|---|
| S-01 | `provision.py` Komga key creator vs enrollment `avrana-komga-create` | CONFIRMED (probe + trace; verified by the orchestrator in source) | P1 | Home's automatic Komga key provisioning resets an existing member's Komga password to a discarded one; the enrollment blueprint set that password on purpose so OPDS comic-reader apps work. A comics member who sets up a reader app and then opens Home loses that sign-in silently; already-keyed members from the first bulk run lost it the same way. | **OWNER DECISION** (asked 2026-10-29 evening): (a) drop `komga` from `HOME_PROVISION_ACCOUNTS` for the beta, or (b) code guard: never reset an existing account without an explicit opt-in flag. S-02 hardening (#172) is correct under either. |
| U-01 | Home hero, `prefers-reduced-motion` | CONFIRMED (screenshots, computed style) | P2 (a11y barrier) | The global reduce-motion rule removes the scroll-timeline animation that keeps `.hero-mini`/`.hero-play` hidden at rest, so the scrolled strip is drawn on top of the resting hero: title twice, progress words twice overlapping, play button over Resume. `home.css:100`, `:466`. | **FIXED, verified**: [#178](https://github.com/rcnechamkin/avrana/pull/178) |
| U-02 | Home hero, `prefers-contrast: more` / `forced-colors` | CONFIRMED (bounding boxes) | P2 (a11y barrier) | The overrides switch `.hero-stick` to `position:relative` but keep `top:var(--head-t)`, so the hero paints 58 px below its box and covers the "Continue" heading. `home.css:475`, `:479`. | **FIXED, verified**: [#178](https://github.com/rcnechamkin/avrana/pull/178) |

## 2. Confirmed P2, fixed or in review

| Id | Component | Finding | Disposition |
|---|---|---|---|
| F-01 | viewmodel: Komga EPUB classification | A Komga e-book is filed under Books for every member; a comics-only member sees a Books tab/chip/shelf for a library they lack; Search/Details label it Comics for a member who has both. | First fix REJECTED by the verifier (keyed on the `read` tile, which every comics member has); rework (`holds_books` from the `avrana-books` group) IN RE-VERIFICATION (X1) Rework **FIXED, verified**: [#174](https://github.com/rcnechamkin/avrana/pull/174) |
| F-02 | Home New Releases comics stack card | Card links to `?rel=comics` even when the Comics chip does not exist (released failed, or caught-up reader) → reloads All. | **FIXED, verified**: [#170](https://github.com/rcnechamkin/avrana/pull/170) |
| F-03 | Seerr broker timeout (PROBABLE) | Search/season lookups used the 2 s page timeout; three slow searches opened the shared breaker for every member. Mirrors #144's Shelfarr fix. Live latency unmeasured (0 searches in the live log). | **FIXED, verified**: [#168](https://github.com/rcnechamkin/avrana/pull/168) |
| S-02 | Komga key provisioning failure path | Destructive-first (reset then mint); failed mint retried hourly with another reset; absent keys file made every comics member a candidate. | **FIXED, verified** (one REJECT for an introduced lock race, fixed): [#172](https://github.com/rcnechamkin/avrana/pull/172) |
| S-04 (+S-11) | Backups / rebuild record | Home's `state/` (bindings, Komga keys) and the live compose were outside the backup allowlist; the bindings runbook pointed at a backup that did not exist; the repo compose alone starts a Home that refuses everyone. | **FIXED, verified**: [#171](https://github.com/rcnechamkin/avrana/pull/171). Effective only after the owner syncs the live backup script (PR body). |
| S-12 / T-20, T-22 | test reliability | `test_hung` order-dependent; N6 eviction bound by wall clock. | **FIXED, verified**: [#169](https://github.com/rcnechamkin/avrana/pull/169) |
| U-03 / A11Y-1 | Rails at 200 % text | Focused card 162 px off-screen at 390 and 430 px with 200 % text (`scroll-padding` calc goes negative). CSS-only region fix regresses 100 %. | FIXED (CSS only, 0 clipped stops at every size per the implementer; `home.js` untouched), **verification running (X10)** |
| U-07 | Home Listen view | Duplicate `id="h-new"`: screen readers announce New Releases as "New to Avrana" (`viewmodel.py:662` vs `:1178`). | **FIXED, verified**: [#176](https://github.com/rcnechamkin/avrana/pull/176) |
| D-01 | Home, degraded Continue | Bare "Continue" heading with no card or line when Continue is empty and any library's Continue is degraded (`continue_said` stays None; `viewmodel.py:1057`). Found by the new route matrix (X6). | **FIXED, verified**: [#176](https://github.com/rcnechamkin/avrana/pull/176) |
| D-02 | Home Listen, ABS not linked | Bare "New to Avrana" heading when Audiobooks recent and shelves are `not_linked`. | **FIXED, verified**: [#176](https://github.com/rcnechamkin/avrana/pull/176) |
| U-05 | Hero at 320 px / large text | Year/library line and progress row overlap. | IN PROGRESS (phone layout PR, `fix/rc2-phone-layout`) |
| U-06 | Hero, phone landscape | Hero taller than the screen (844×390, 667×375). | IN PROGRESS (phone layout PR, `fix/rc2-phone-layout`) |
| U-08 | Home filter row | Swipes sideways into 1,190 px of empty space in a 390 px row. | IN PROGRESS (phone layout PR, `fix/rc2-phone-layout`) |

## 3. P2 not fixed in this sprint (design questions, deferred, needs live evidence)

| Id | Finding | Why not now | Owner action |
|---|---|---|---|
| S-03 | Komga member key selected by e-mail claim, not the bound `sub`; offboarding leaves the keys-file entry | Needs two Authentik users sharing an e-mail (0 today); file-format change | cutover: key by `sha256(sub)`; add the keys file to offboarding (runbook) |
| S-05 | Library-group removal takes effect at token reissue (24 h), not within Home's cache TTL | Documented trade-off (D3 open question 3) | decide: shorter `access_token_validity` on the Home provider, or "end the member's sessions" in the group-removal runbook |
| S-06 | Enrollment blueprint drift (#167): repo behind live; a blind copy would revert the LDAP switch and the admin entry; `jellyfin-ldap.yaml`, `authentik-home-beta.yaml` live-only | PR #167 exists (CI green) | merge #167 (repo-only; never apply from Git); add the two live-only blueprints to Git |
| S-08 | Jellyfin provisioning: policy step failure leaves a locked account that later attempts call `exists` | PROBABLE (LDAP plugin behaviour unverified) | post-beta: distinct alertable reason + repair path |
| S-10 | Rolling back to `pre-2cb228f` silently drops S1; rollback docs call Home stateless | Design question for the rollback packet | record in the rollback runbook; while rolled back, `HOME_ALLOWED_USERS` = owner only |
| S-18 | Komga's replicated password outlives the Authentik account until deleted by hand | KNOWN (offboarding runbook) | offboarding step |
| F-04 | Book/comic request pages never say "Already in" on the live beta (`HOME_LIBRARY_IDS_FILE` off) | KNOWN/DEFERRED by owner decision | optional: build the index (rollout step 7) |
| F-05 / S-13 | Section budgets under heavy local CPU load show "unavailable"; four web modules flaked once under three concurrent suites | UNVERIFIED as product; test-environment timing | none (CI green; run suites one at a time) |
| D-03 | `/library?lib=audiobookshelf` with `recent` empty says "Nothing added recently" and hides the shelves the library holds (Home's Listen shows them) | observation from the route matrix, not yet reproduced by a failing test | small follow-up |
| D-04 | `/?for=comics` and `/?for=books` for an all-library member are not real filters (All chip current, fewer rows than `/`) | observation; design intent unclear | decide the filter semantics |
| D-05 | Timeout-after-send copy on all three request pages says "could not be reached … Try again later" and never "may have gone through" (Quick Connect's `unknown` does) | cross-broker copy question; Seerr dedupes, Shelfarr/Omnibus may not | decide the wording |
| T-09 gap | Identity-binding breadth with a warm cache was untested | **closed** by the journey-pin tests (X8) | — |

## 4. P3 (deferred unless trivially adjacent to a fix)

S-09 `member_busy` on rapid refresh during a slow upstream; S-14/U-22 stale status lines and DESIGN.md drift (**fixed: draft #175**; README,
HOME-APP.md, CONCEPT-K-FOLLOW-UPS.md, runbooks, module docstrings: fixed as part of the sprint packet where cheap);
S-15 previous JWT secret has no end date; S-16 keys file has no cross-process lock (owner tool vs Home); F-06 dev stack
`--mode wrong-user` crash with the extra mocks; U-04 focused cards partly under the tab bar / sticky header; U-09 filter
ledgers clip chips at 390; U-10 Library header sideways scroll at 320 px / 200 %; U-11 "Sign in on a TV" wording and
field style; U-16 hero repeats the first Continue card (owner choice AVR-735); U-17 404/error pages are the Title Card
look; U-18 outage notice and its Try again apart; U-19 copy defects; U-20 ~110 KB inline CSS on every page, blank Home
for 2.5 s on a slow upstream (performance baseline, section 6); U-21 focus after browser Back (UNVERIFIED); U-23 "All"
filter targets 18 px wide; X2 note: card says "6 new issues" while the chip lists 1 when one comic remains in the picked
list.

## 5. Known / deferred release gates (not defects of 2cb228f)

| Id | Gate | Linear | State |
|---|---|---|---|
| S-07 | Komga everyday key is the admin's; #162 guard fails closed if deployed first; non-admin read of `/api/v2/users/me` unverified | AVR-782 | owner key swap, then rebase/merge/deploy #162 |
| S-17 | Seerr CSRF protection and proxy trust | AVR-348 | owner, cutover |
| — | SMTP2GO proof, admin MFA, restore drill, device pass, two-member isolation, member rules | AVR-346/347/350/585/479/772/458 | owner (critical path §2) |

## 6. Performance baseline (loopback dev stack, synthetic data, Chromium, 390×844, member-b) [offline]

Warm Home: TTFB 35 ms, FCP 208 ms, LCP 270 ms, CLS ≤ 0.001; 24 requests, ~236 KB transferred of which ~109 KB is
the stylesheet inlined into every page (uncompressed, `no-store`); with a slow upstream Home shows nothing for 2.5 s
(the section deadline). No live-beta numbers exist; the live measurement belongs to the owner device pass.

## 7. Verified clean on fixtures (counts toward "critical synthetic journeys pass")

Route matrix 9,108 requests (22 failure modes × 9 identities × 46 routes) and the new degraded matrix (90 scenarios ×
6 routes under StrictUndefined): no non-200, no traceback; the Listen/Read 500 fix holds in every adjacent state.
Member partitioning (`/home.json` id sets, wrong-user data discarded, group check before any cache read), Continue
ordering by `active`, Library filters never echo input, Search unavailable-is-not-empty, hand-off only on fixed hosts,
request forms (signed, same-origin, double-tap guard, PRG), Me/TV/sign-out/offline/sw; #166 protections present
(25 unit + 12 web + 7 repository tests); token/header/cache/artwork/CSP/method/form protections traced
(security audit §c). axe: 0 serious/critical across 1,098 static views and 418 live views.
