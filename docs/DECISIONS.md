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

## Owner decisions, 2026-10-14

| Decision | Consequence |
|---|---|
| **D-8a**: CI may install exactly one hash-pinned PyYAML wheel, in CI only | `.github/requirements-ci.txt` holds one `==` pin with one sha256; `pip` runs `--require-hashes --only-binary=:all: --no-deps`. No secrets, read-only permissions, no deployment and the no-network second run are unchanged. `AVRANA_REQUIRE_YAML=1` makes a missing PyYAML fail the G1 security tests instead of skipping them. Any other dependency needs a new decision |
## Owner decisions, 2026-10-15: Media 2.0 review

Recorded from the owner's message of 2026-10-15. None of these authorises a production change: live
host access, deployment, restarts, Docker networking, Authentik configuration, credentials,
member-data inspection, G1 isolation, JWT enforcement, production validation and rollback each need
their own explicit approval.

| Decision | Consequence |
|---|---|
| **D-8a approved in principle** (PR #14): one hash-pinned PyYAML in CI so the required G1 security tests fail instead of skipping | Merged on 2026-10-15 after the update from main and an independent security review; no CI result is claimed while GitHub Actions billing is blocked |
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

## Owner decisions, 2026-10-18: AVRANA Brand v1.0.0 on Home (AVR-584, PR #62)

Recorded from the owner's direction of 2026-10-18. Neither decision approves the branded UI itself (that waits
on the iPhone Safari and VoiceOver review, AVR-455), a merge or a deployment.

| Decision | Consequence |
|---|---|
| **Brand binaries are stored as base64 text, in `services/avrana-home/avrana_home/app/brand/` only** | The PNG icons and the interface font's WOFF2 files (Geist then; Plus Jakarta Sans since AVR-715, from npm) are `*.b64` copies of the exact source bytes, each pinned by SHA-256 in `brand/SOURCES.json`; `brand.py` refuses to serve a file that does not match, and `brand/.gitattributes` (`* -text`) keeps every byte. The repository's binary policy and `scripts/review_git_content.py` are unchanged: no other folder gains this exception |
| **Shell pages alone get `font-src 'self'`**, beside their existing `manifest-src 'self'` | Only pages that wear the Home shell load the interface font (Geist from `/brand/geist.woff2` then; *superseded by AVR-715*: Plus Jakarta Sans from `/brand/plus-jakarta-sans-latin.woff2` and `-latin-ext.woff2`); every other response (portal, Kindle, errors, sections off) keeps the base CSP. No other source, and still no script |

## Owner decisions, 2026-10-25 and 2026-10-26: Concept K · Avrana Console on Home shell pages (AVR-713)

Recorded from the owner's brief of 2026-10-25 and their approval of the Phase 1 frames and decision memo on
2026-10-26 ("Perfect. Proceed working on this using the recommended choices."), which makes every recommendation
D1 to D17 in that memo a decision. Figma: "Avrana Media — Console" (`OggTUO1p24pNYFI6iVlLWL`). None of this approves
a merge or a deployment; the device review below still applies.

| Decision | Consequence |
|---|---|
| **O2: "Full Concept K, with yellow in place of purple."** On shell pages the Title Card is retired: Concept K's type (Plus Jakarta Sans), radii, surfaces, shell and glass replace it; "Atomic Purple's role (selection, chosen option, focus/signal, product tags, the nav lens) goes to a Media yellow. Purple never appears in Media." | Reverses DESIGN.md's No Accent Rule and the 2026-10-15 "interface stays monochrome" line **on shell pages only**. The portal, Kindle, Audible and every page without the shell keep the Title Card, byte-identical (parity) |
| **Media yellow: Butter-High `#EADA6E`**, Yellow Deep `#776A00` (D2) | The only candidate a deuteranope can tell from a warning amber, and the only one that keeps 3:1 on glass over bright art. Used for selection and "yours" only, never as a large fill or inside a warning |
| **Shell pages use the console warn `#F59E0B`**, not Media's `#E8CF8A` (D3) | `#E8CF8A` is 1.07:1 against the yellow; status is always said in words as well |
| **The yellow is a Media-scoped token in `templates/home.css`** (D4) | Not in `avrana-brand` or the mirrored foundation; DESIGN.md says where it is used |
| **Plus Jakarta Sans replaces Geist on shell pages** (owner's standing rule, as in Party #185 and Games #93) | The Fontsource 5.3.0 files Party ships, base64 in `avrana_home/app/brand/` and SHA-256 pinned like the brand files (the 2026-10-18 folder exception, extended to this font); Geist leaves Home. The Authentik gate keeps the system font |
| **O1: progressive-enhancement JavaScript** (one first-party script, one service worker, shell pages only, every page works without it) | Recorded with its CSP and security review in the MK-3 change (AVR-717), which is where it takes effect |
| **Navigation** (D1, D16, D5): tabs Home · Library · Search · Me; the Watch, Listen, Read, Request, Help bar stays on Home; the L3 lockup stays on Home, the Spire-A micro cut is the Home button elsewhere | MK-2 (AVR-716). Keeps AVR-452's composition and the identity tests' bar |
| **Installed name "Avrana Media"** (D8); everything stays behind the Authentik outpost (D9); `/signout` clears this site's cache and storage (D10); no `Cache-Control` relaxation (D11) | MK-3 (AVR-717) |
| **The iPhone, Safari and VoiceOver review (AVR-585) runs on the Concept K build** (D17) | No UI change that needs visual approval merges before the owner has seen it on a device |

## Owner decisions, 2026-10-18: AVRANA Brand v1.0.0 on the Authentik gate

Relayed from the owner's chat on 2026-10-18. None of these approves the live change: applying the brand CSS to
auth.avrana.net still needs the owner's explicit approval for that step, after a backup, with the rollback ready
(`services/authentik/brand/README.md`).

| Decision | Consequence |
|---|---|
| **The gate shows the plain AVRANA wordmark** (cream, `02-Logo-Exports/RGB/svg-trimmed`), not the Media L3 lockup | Embedded byte-exact in `Brand.branding_custom_css`, SHA-256 pinned in `services/authentik/brand/SOURCES.json` |
| The gate work no longer waits on #62's iPhone review; the owner reports #62's branded UI approved | Timing of the live apply is the owner's call |
| **The gate work is part of AVR-362** (cross-surface convergence), not its own ticket | Tracked and reviewed under AVR-362 |
| **No rule under the wordmark**, on the gate and on Home | Removed from the gate's brand CSS; Home's masthead rule is removed in a separate Home change |
| The live apply needs explicit approval, a backup and a rollback; push and a draft PR are approved | `brand_css_change.py backup`, `apply`, `rollback`; each live step is approved one at a time, Git-only until then |
| **The gate uses the system font, not embedded Geist** (owner, 2026-10-18) | The staged stack stays: no font embedded in the brand CSS (16 KB, not 109 KB). Geist can come later from Home's own copy once Home is deployed, which needs CORS on the font |
