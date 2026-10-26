# Home 2.0 sprint: from owner preview to member beta candidate (2026-10-16)

Integration branch: `feat/home-2.0`, cut from `feat/lan-demo` (PR #53) at `2e01518`, which is what the LAN
owner preview runs. `feat/lan-demo` stays as deployed, so the preview keeps a rollback point. Workstream
branches are cut from `feat/home-2.0` and come back to it through reviewed PRs; the orchestrator integrates.

Nothing in this sprint deploys, restarts a service, changes Authentik, Cloudflare, DNS, firewall or Docker
networking, or reads real member data. Fixtures are synthetic. The LAN owner preview proves the owner's own
data renders; it does not prove Authentik integration, multi-member isolation or production readiness.

## Workstreams and file ownership

| Lane | Owns | Linear |
|---|---|---|
| A, mobile UI | `templates/home.css`, the `card`/`frame`/`mast` macros in `_parts.html`, `base.html`, `_sections.html` markup, synthetic long-title fixtures for the export | AVR-452, AVR-426, AVR-478 |
| B, Continue and handoff | `build_home` and Continue semantics in `viewmodel.py`, handoff paths in `contract.py`, the Jellyfin and Audiobookshelf continue parsing, `routing.py`/`catalogue` navigation pages | AVR-381, AVR-479, AVR-504 |
| C, Search and title pages | `build_search`, `search.html`, a new title page, `aggregate.search`, the adapters' search parsing and `creator`/`year` population | AVR-383, AVR-384, AVR-503 |
| D, security and member readiness | `artwork.py`, `cache.py`, `middleware.py`, identity mapping, isolation tests, installable Home (manifest), Help accuracy | AVR-375, AVR-364, AVR-386, AVR-387 |

A lane that needs a change in a file another lane owns makes the smallest change and says so in its PR.

## Shared contract (added at the start of the sprint)

- `contract.MediaItem.creator` (author or creator, display text) and `MediaItem.year` (int), both optional,
  both in `to_dict()`. An adapter fills them only from a field it already reads and validates.
- `viewmodel.ItemVM.creator`, `ItemVM.year`.
- `viewmodel.CardVM.kind_label` (member language), `CardVM.action` (`"Resume"` only when the upstream gave a
  trustworthy saved position for this member, otherwise `"Open"`), `CardVM.action_label` (accessible name).

## Rules every lane keeps

- One primary action per card or result. Resume never claims playback started; it opens the upstream app
  at the item. A failure to open is the upstream's to report, and Help says what to do next.
- Libraries the member cannot use stay absent: never named, never counted, never "unavailable".
- Unavailable is not empty: if no eligible library could answer, say so; never "no matches".
- Monochrome editorial design (DESIGN.md). No new design system, no heavy rounded cards, no imitation of a
  streaming service. Artwork keeps its natural shape and colour.
- No script on member pages; CSP stays as strict as today unless a reviewed, narrow exception is needed.
- *Superseded on Home shell pages after this sprint (2026-10-25/26, DECISIONS.md): Concept K replaces the
  monochrome editorial design there (O2), and one first-party script and a service worker are allowed there (O1,
  MK-3). Pages without the shell keep both rules above.*
- Verified sizes: 360px, 390px, desktop, and 200% text. Screenshots use synthetic data and are not committed.
- Before committing: `python scripts/review_git_content.py --staged`. Tests: `tests/run_web_tests.py` in
  `services/avrana-home` and `python -B tests/run_offline.py` at the repository root.

## States kept apart in every report

Implemented and locally verified; independently reviewed; merged; deployed to owner preview; physically
verified; ready for member beta. One is never evidence of another.
