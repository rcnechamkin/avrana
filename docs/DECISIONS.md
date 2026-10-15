# Decisions and unresolved conflicts

| Decision/evidence | Consequence |
|---|---|
| User direction, 2026-09-23: Git Markdown is the technical source of truth | BookStack remains archive/reference; no agent dependency or Git hook |
| Development and live trees are separate | No Git initialization or blanket import in production |
| Production preservation outranks easier API access | Existing offline wiki export used; no API repair |
| Recovery artifacts are immutable evidence | Analyze private disposable copies only; never clean contamination |
| Source migration is selective | Personal Kern code and runtime state are not imported wholesale |

| Conflict | Evidence / disposition |
|---|---|
| BookStack is described as the primary documentation home in old source/config | Superseded by the user-approved Git-first model; live compose left unchanged |
| Old handoff: 15 stale mounts/6 containers | Later ledger M5: 11/5 after worker maintenance; no fresh inode audit yet |
| Older summaries: Compose v1 limitation | Later ledger M0/M5 records v2.27.1 |
| Wiki: Kern HQ planned | Page 62 and current running Home Assistant demonstrate deployment; larger Kern control plane still not established |
| Wiki: Jellyfin media writable | Current Docker binds are read-only |
| Wiki: backup 10/11 components | Later recovery ledger records 24; old restoration claims remain historical |
| Jellyfin DB restored and healthy implies complete recovery | False for artwork: metadata excluded from backup and image refs/files diverge |
| Movies library `/mnt` path | Not backed by current container bind; do not silently remove before assessing item identity effects |
| Early address-pool document: collision still live | Later August 29 incident records its resolution |
| Firewall draft: existing bridges renumber | Later incident/design says existing networks retain subnets |
| Backup README only mentions free-space guard | Later incident records a mount guard; current coverage requires source review |
| Off-host setup built/tested versus off-host backup absent | Implementation and actual provisioning are different; no operational off-host copy established |

Do not resolve uncertainty by copying newer-looking text without evidence. Record observation date, source and whether the statement is live-verified, historical or proposed.

## Owner decisions, 2026-10-03 and 2026-10-04

| Decision | Consequence |
|---|---|
| `rcnechamkin/avrana` is canonical | Rebuilt from the live tree on 2026-10-04; `Kern-Ecosystem` is archived at tag `archive-2026-10-04` (`d0dc3c5`) with an inventory of what was not migrated |
| Off-host markers are never rewritten | The first upload's markers record a wrong file count; they stay as uploaded and the inaccuracy is documented in `services/backups/OFFHOST.md` |
| Batch 3 may proceed without per-change approval (2026-10-06) | The owner asked for everything that needs no owner input to be done and the rest staged; Jellyfin excluded while in use |
| Socket proxies: Unix sockets, no network | Chosen over a firewall rule because it removes the attack surface instead of filtering it; consumers mount the 0700 socket directory |
| Docker is not made to require `comics_merged` | A failed union mount should cost an empty Komga library (now monitored), not the whole stack |
| Kavita, the comics tunnel, nginx, libvirt, Plex and the Kern timers are retired | Kern timers removed on 2026-10-06; the rest is script 04/05, run by the owner |
| Authentik blueprints are tracked in Git; the values they need live in `services/authentik/blueprints.env` (2026-10-06) | Every embedded secret became an `!Env` reference (`!Format` for the two expression policies); only the worker loads the file; the applied policies, providers and e-mail stages were verified unchanged by digest before and after the re-apply |
| BookStack is retired, not repaired | Content extracted from a disposable restore into `docs/archive/bookstack/`; 31 pages promoted into `docs/`; containers stay until the owner approves removal |
| 1Password is the credential store | No secret in Git, chat, logs or shell history; owner-run scripts with hidden prompts |
| Backblaze B2 with rclone crypt is the off-host destination | Add-only uploader, retention by bucket lifecycle (`services/backups/OFFHOST.md`) |
| Sanitised strings in the development copy revert to production wording | The four files match production again |
| The September 27 and 28 power losses were a tripped breaker | Recorded in `docs/incidents/2026-09-27-power-loss.md`; a UPS is on the roadmap |
| Mylar3 authentication is approved but deferred | Roadmap item |
| Plex, the comics tunnel and the legacy Kern timers are to be retired later | Not tracked in this repository; documented in `Kern-Ecosystem` |
| The `avrana-agent` containment design is approved in principle | Not implemented yet |
| Kavita, Komf and Bazarr stay retired | Their compose definitions were not imported |

Conflicts in the table above that are now settled: the off-host backup exists; the backup has 24
components and a completeness gate; Compose v2 is the only supported version (v1 is still installed and
half the containers still carry its label).

## Owner decisions, 2026-10-11: Avrana Media 2.0

| Decision | Consequence |
|---|---|
| The member experience plan is formalised as **Avrana Media 2.0**, a product-experience milestone, not a backend rewrite | [`docs/design/MEDIA-2.0.md`](design/MEDIA-2.0.md) is the charter; production approval and rollback rules are unchanged |
| **M3 (the Avrana home) is the launch milestone**; M4 and M5 are post-launch, taken on only with usage evidence | Request filing through Avrana, request status, notifications and in-site players or readers are out of M3 |
| **Security first**: the identity-header boundary (forensic audit D4) is resolved before M3, with per-user authorization and isolation tests | D4 becomes gate G1; the portal and Kindle test suites become gate G2 |
| Target audience is about 15 members | Nothing is built for scale; quality, onboarding and follow-through are the bar |
| Upstream applications are preserved and unmodified; custom infrastructure is one small application | No frames, proxy injection, upstream patches, custom players or dedicated search engine |
| Real-member acceptance testing joins automated accessibility, security and API contract tests | Testers, tasks and pass criteria in Section 7 of the charter |
| Member and operator interfaces stay separate | Status reaches members only as an operator-set notice in plain language |

## Owner decisions, 2026-10-15: Media 2.0 review

Recorded from the owner's message of 2026-10-15. None of these authorises a production change: live
host access, deployment, restarts, Docker networking, Authentik configuration, credentials,
member-data inspection, G1 isolation, JWT enforcement, production validation and rollback each need
their own explicit approval.

| Decision | Consequence |
|---|---|
| **D-8a approved in principle** (PR #14): one hash-pinned PyYAML in CI so the required G1 security tests fail instead of skipping | Merged only after rebase onto main and independent review; no CI result is claimed while GitHub Actions billing is blocked |
| **D-3: verified Authentik JWT identity is the architecture** (PR #19), not plain identity headers | Offline implementation and independent security review proceed; enforcement in production needs separate approval |
| OliveTin: a dedicated, unambiguous authorisation group, not username lists | Compatibility, group mapping and migration are verified before any live change is proposed |
| Audible one-time mode: a GET never changes state | Finalisation moves to a CSRF-protected POST; an empty selection cannot finalise; the whole lifecycle is tested |
| PR #11 (shelves-first home) is closed as superseded by #23 | After checking that its still-relevant requirements are carried by the replacement |
| CI: offline verification stays required; missing GitHub Actions and axe-core results are stated, never assumed | Billing is an owner dependency, not permission to weaken a check |
| **Artwork keeps each library's natural shape** (posters, audiobook squares, books, comics, video stills) | DESIGN.md Shapes and Media components; replaces the one-square-crop rule for media artwork |
| **Artwork keeps its original colour** inside the monochrome interface | No greyscale treatment of library artwork |
| **Search gets a visible, labelled entry near the primary navigation** once search works | The Watch, Listen, Read, Request, Help order is kept |
| **The 720px browsing column stays** for now, subject to a desktop review; **Kindle keeps its 640px form column** | Kindle's column becomes a named single-form variant, not drift |
| **The account menu stays native and script-free** at first | Keyboard, Escape, outside tap, focus and VoiceOver are checked in Safari; a script, if shown to be needed for accessibility, comes as a narrowly scoped CSP exception for separate review |
| **The compact Home stays**: bounded Continue and New rows, browsing on `/new` | As approved in AVR-452 |
| Earlier approved direction is preserved | These decisions are not blanket visual approval |
| **Visual approval of #23, #24, #26 and #27 is pending** (AVR-455): the direction is accepted | Reviewed on a real iPhone in Safari with VoiceOver from a private, fixture-only preview; no UI change that needs it merges before then |
