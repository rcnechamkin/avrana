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
