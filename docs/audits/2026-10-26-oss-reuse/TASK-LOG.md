# R1-R4 task log (AVR-746..749)

Compact record of the open-source reuse sprints: base commits, overlap checks, PRs, tests and decisions. Newest
last. Local test runs are labelled local; GitHub Actions is not counted as passing while billing blocks it.

## 2026-10-26 R1 (AVR-746)

- Base: `main` `99f0d7c`. Branch `docs/avr-746-r1-oss-audit`.
- Overlap checked: open PRs #65-#71 and #74 (Concept K) touch `app/` and templates only; no PR touches
  `contract.py`, `aggregate.py`, `cache.py` or `adapters/`. Linear: AVR-375/381/383/384/503/504/479/585/505,
  Concept K follow-ups AVR-722..737, M4 AVR-480..482.
- Research: four read-only research passes over upstream source at pinned commits (appendices in this folder);
  three claims re-checked by hand (audit, header).
- Baseline tests on `main` (local, Windows 11, Python 3.12):
  - `python tests/run_offline.py`: root suite 415 tests, 1 failure
    (`test_ui_harness.RegistryTests.test_registry_builds_and_covers_both_services`, 4 pages unavailable on this
    machine), 40 skipped; the runner stops at that stage, so later stages did not run from it.
  - Home adapter suite with FastAPI/Jinja available (`.venv-media`): see the R2 entry for the full counts.
- Output: `docs/audits/2026-10-26-oss-reuse-audit.md` (matrix, inventory, ranked backlog, ledger, owner
  questions). Documentation only.

## 2026-10-26 R2 (AVR-747) and R2-C (AVR-384)

- R2-A `feat/avr-747-r2a-openapi-subset` (#76): Jellyfin allow-list vs official OpenAPI 10.11.11 and 12.3.0. Adapter
  suite 742 OK (baseline 730). Found the dead `UserData.UserId` tripwire.
- R2-B `feat/avr-747-r2b-media-identity` (#77): `media_ids.py`, `MEDIA-IDENTITY.md`. Independent review: 0 HIGH,
  0 MEDIUM, 6 LOW fixed. Adapter suite 751 OK; webtests 487, 1 failure (Windows strict-skip runner, also on main).
- R2-C `feat/avr-384-r2c-synopsis` (#78, stacked on #77): title-page synopsis. Independent security review: 0 HIGH,
  1 MEDIUM (stale JSON key-set test) and 1 LOW fixed. Adapter suite 763 OK; `test_web_sections` + `test_web_title`
  50 OK; axe: no new finding.

## 2026-10-26 R3 (AVR-748)

- R3-A `feat/avr-748-r3a-title-about`, based on the Concept K integration branch (#74) with R2-B/R2-C merged in:
  the synopsis as a Concept K "About" block. Screenshots 390/1280/JS-off before and after; axe no new finding.

## 2026-10-26 R4 (AVR-749)

- `docs/design/SOCIAL-FEASIBILITY.md`: NeoDB no-go as the social layer, thin native module modelled on its data
  model as a go for a fixture-only prototype **on owner approval**, federation deferred with a boundary and threat
  model. No prototype written (owner decision Q6a).
