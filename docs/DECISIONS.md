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
| **D-8b** (owner, 2026-10-26, AVR-757): pin and document the missing test dependencies properly; do not skip the affected tests | `.github/requirements-ci.txt` adds hash-pinned pure-Python wheels for pytest (with iniconfig, packaging, pluggy, pygments), itsdangerous and python-multipart, and includes `services/avrana-home/requirements.lock` (FastAPI, Starlette, pydantic, Jinja2, httpx, uvicorn) instead of pinning those twice. The single pip call is unchanged (`--require-hashes --only-binary=:all: --no-deps`), and it is also the documented local install (`docs/DEVELOPMENT.md`). `tests/test_ci_workflow.py` holds the exact package list; any other dependency still needs a new decision |
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
| **Artwork keeps its original colour** inside the monochrome interface | No greyscale treatment of library artwork. *Partly superseded 2026-10-25 (O2): on Home shell pages the interface is no longer monochrome; artwork still keeps its colour* |
| **Search gets a visible, labelled entry near the primary navigation** once search works | The Watch, Listen, Read, Request, Help order is kept. *On Home shell pages the entry is the Search tab (D1, 2026-10-26)* |
| **The 720px browsing column stays** for now, subject to a desktop review; **Kindle keeps its 640px form column** | Kindle's column becomes a named single-form variant, not drift |
| **The account menu stays native and script-free** at first | Keyboard, Escape, outside tap, focus and VoiceOver are checked in Safari; a script, if shown to be needed for accessibility, comes as a narrowly scoped CSP exception for separate review. *Superseded on Home shell pages 2026-10-26: the account menu is retired; the Me tab opens the Me hub (D1, MK-2/MK-5b), and the script rule is replaced by O1 (below)* |
| **The compact Home stays**: bounded Continue and New rows, browsing on `/new` | As approved in AVR-452. *Amended on Home shell pages 2026-10-26: the places bar stays (D16), a hero sits above Continue (D6), the New row is "Recently added" (memo section 4), and browsing is the Library tab (`/library`, D1); the rows stay bounded* |
| Earlier approved direction is preserved | These decisions are not blanket visual approval |
| **Visual approval of #23, #24, #26 and #27 is pending** (AVR-455): the direction is accepted | Reviewed on a real iPhone in Safari with VoiceOver from a private, fixture-only preview; no UI change that needs it merges before then |

## Owner decisions, 2026-10-18: AVRANA Brand v1.0.0 on Home (AVR-584, PR #62)

Recorded from the owner's direction of 2026-10-18. Neither decision approves the branded UI itself (that waits
on the iPhone Safari and VoiceOver review, AVR-455), a merge or a deployment.

| Decision | Consequence |
|---|---|
| **Brand binaries are stored as base64 text, in `services/avrana-home/avrana_home/app/brand/` only** | The PNG icons and the interface font's WOFF2 files (Geist then; Plus Jakarta Sans since AVR-715, from npm) are `*.b64` copies of the exact source bytes, each pinned by SHA-256 in `brand/SOURCES.json`; `brand.py` refuses to serve a file that does not match, and `brand/.gitattributes` (`* -text`) keeps every byte. The repository's binary policy and `scripts/review_git_content.py` are unchanged: no other folder gains this exception |
| **Shell pages alone get `font-src 'self'`**, beside their existing `manifest-src 'self'` | Only pages that wear the Home shell load the interface font (Geist from `/brand/geist.woff2` then; *superseded by AVR-715*: Plus Jakarta Sans from `/brand/plus-jakarta-sans-latin.woff2` and `-latin-ext.woff2`); every other response (portal, Kindle, errors, sections off) keeps the base CSP. No other source, and still no script. *"Still no script" superseded for shell pages 2026-10-26 by O1 (`script-src 'self'; worker-src 'self'`, section below)* |

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

Every Phase 1 recommendation, as decided on 2026-10-26, and where it took effect (all on draft branches; nothing
merged to `main` or deployed):

| # | Decision | Where |
|---|---|---|
| D1 | Tabs Home · Library · Search · Me (option B); Request and Contribute as a group on Library and in Search's no-results state | MK-2 (AVR-716), MK-5a/MK-5b (AVR-719) |
| D2 | Media yellow Butter-High `#EADA6E`, Yellow Deep `#776A00`, for selection and "yours" only; reverses the No Accent Rule and the 2026-10-15 monochrome line on shell pages | MK-1 (AVR-715) |
| D3 | Shell pages use the console warn `#F59E0B`; non-shell pages keep `#e8cf8a` until AVR-362; status always in words | MK-1 |
| D4 | The yellow is a Media-scoped token in `home.css`; repeated hex values are listed in FOUNDATION-MAPPING | MK-1, MK-7 (AVR-721) |
| D5 | L3 product lockup on Home; Spire-A micro cut in the glass Home button elsewhere | MK-2 |
| D6 | Hero: the poster on its own blurred art (CSS blur, contained, never cropped) and a no-art hero; the backdrop allow-list is a follow-up with its own security review | MK-4 (AVR-718); follow-up F-1 in `docs/design/CONCEPT-K-FOLLOW-UPS.md` |
| D7 | `apple-mobile-web-app-status-bar-style` stays `black`; translucent frames are Proposal | MK-2, MK-3 (unchanged) |
| D8 | Installed name "Avrana Media" | MK-3 (AVR-717) |
| D9 | Everything stays behind the Authentik outpost; no exempt paths | MK-3 |
| D10 | `GET /signout` with `Clear-Site-Data: "cache", "storage"`, ending at the outpost sign-out; copy never claims the Authentik session ended | MK-3, built as a 303 redirect carrying the header rather than the memo's 200 page; verified in Chromium only |
| D11 | No `Cache-Control` relaxation | MK-3 |
| D12 | One script and one worker as O1 decided: `script-src 'self'; worker-src 'self'` on shell pages, `connect-src 'self'` on `/sw.js` only | MK-3 (section below) |
| D13 | No expired-session heartbeat now | MK-3; follow-up F-6 |
| D14 | The foundation mirror stays untouched; DESIGN.md carries Concept K as the shell-page standard, with the Title Card kept for pages without the shell | MK-1, MK-7 |
| D15 | Frames and memo approved; Phase 2 draft PRs may start | 2026-10-26 |
| D16 | The Watch, Listen, Read, Request, Help bar stays on Home, under the lockup | MK-2 |
| D17 | The AVR-585 iPhone, Safari and VoiceOver review runs on the Concept K build | Not yet run |

### Questions for the owner (open, 2026-10-26)

Not decisions. Each build choice is the conservative one until the owner answers; details in
`docs/design/CONCEPT-K-FOLLOW-UPS.md` section 3.

- **The title page's button naming the app, and which surfaces name the upstream app:** "Resume in Jellyfin", as
  on the Home hero, or today's short verb ("Resume") with the library in member language in its accessible name?
  Today the hero, Library's "Open <app>" and "Browse everything in <app>", and the Watch interstitial name the app;
  everything else uses member language.
- **Library showing in-progress items:** should `/library` include the member's Continue items, or stay "recently
  added" only?
- **The ADMIN tag on Me:** it comes from the catalogue's Operations gate (`authentik Admins`), the only role signal
  Home has. Keep it, or no tag?
- **Request rows saying "Opens the request website"** rather than naming the product. Keep?
- **Contribute in Search's no-results group** (memo section 2). Keep it there, or offer only requests?
- **The sign-out hop as built (D10):** a 303 redirect carrying `Clear-Site-Data`, verified in Chromium only, instead
  of the memo's 200 page with a refresh. Accept it, or ask for the 200 page now?

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

## Owner decisions, 2026-10-26: Concept K, progressive-enhancement script and service worker (AVR-713, MK-3 AVR-717)

Quoted from the owner. O1 was given on 2026-10-25; the approval is of the Phase 1 design memo (2026-10-26). Neither approves a merge or a deployment, and MK-3 still needs its dedicated security review.

> **O1, 2026-10-25:** "JavaScript: progressive enhancement. Add one small first-party script and one service worker, served from Home's own origin, for the offline shell, the nav lens, inline previews and transitions. Every page must keep working with no JavaScript. This reverses part of HOME-APP.md ("no JavaScript") and changes the CSP (script-src 'self', worker-src 'self' on shell pages only), so the PR that does it needs a dedicated security review and a DECISIONS.md entry quoting this decision."

> **2026-10-26, on the Phase 1 memo:** "Perfect. Proceed working on this using the recommended choices."

| Decision | Consequence |
|---|---|
| **Home shell pages may run one first-party script and register one service worker.** This supersedes `install.py`'s "No service worker and no script" and the 2026-10-15 "script only if needed for accessibility" rule, **for Home shell pages only** | `script-src 'self'; worker-src 'self'` on the responses that already get `manifest-src 'self'; font-src 'self'`. No inline script, no `unsafe-inline` or `unsafe-eval` for script, no other host. Portal, Kindle, Audible, error pages without the shell and every non-page route keep their CSP and get no script |
| Every page keeps working with no JavaScript | The script is added on top: the nav lens slide, worker registration and update banner, and a reload when a page returns from the back/forward cache. Inline previews (MK-4) are not in this change |
| **D12:** `connect-src 'self'` is on the `/sw.js` response only | The worker takes its CSP from its own response; shell pages get no `connect-src`. `/offline`, which the worker stores and shows, gets `font-src 'self'` and nothing else (no script, no manifest) |
| **D9:** everything stays behind the Authentik outpost | No exempt paths, no `skip_path_regex` (G1 review F5). A signed-out worker update fails quietly and retries on the next signed-in load |
| **D11:** no `Cache-Control` relaxation | Every response stays `no-store` (`/art` stays `private, no-store`). The script path carries a content hash; the worker's own store serves the static files |
| **D13:** no session heartbeat | The script makes no request of its own |
| **D10:** `GET /signout` sends `Clear-Site-Data: "cache", "storage"` (never `"cookies"`), then redirects (303) to `/outpost.goauthentik.io/sign_out` | Account's Sign out points at it on shell pages. The copy says it signs you out of Avrana Media on this device; it does not claim the Authentik session ended |
| **D8:** the installed name is "Avrana Media" | Manifest `name` and `short_name`, `apple-mobile-web-app-title`; the manifest gains `id: "/"`, `description`, `lang` |
| Kill switch `HOME_PWA_SW=off` | `/sw.js` serves a worker that unregisters itself and deletes its caches; the script skips registration and unregisters any worker it finds |
| The worker caches only static, identical-for-everyone files | The page script, `/offline`, the brand font, lockup and favicon, the install icons. Never member HTML, `/art/*`, `/home.json`, search or any redirected, non-200, cross-origin or wrongly typed response. Navigations always go to the network; the offline page is shown only when the request itself fails. Navigations to `/signout` and `/outpost.goauthentik.io/` are not handled by the worker at all, so the hop and the outpost run as real navigations |

## Owner decisions, 2026-10-26: Media direction after M3 (AVR-505)

Recorded from the owner's "Personal Experience Specification v0.1" and dispositions of 2026-10-26. **Direction,
not implementation approval**: no merge, deployment or build of any item below is approved by this entry. The
tiers and issue IDs are in [`design/MEDIA-STATE-REGISTER.md`](design/MEDIA-STATE-REGISTER.md).

| Decision | Consequence |
|---|---|
| Post-M3 direction selected: featured-first Home hero (AVR-750), browser playback spike (AVR-751), native movie and TV requests through a server-side broker (AVR-390, AVR-393, AVR-726), in-app inbox (AVR-752), release tracking (AVR-753), phone-to-TV control later (AVR-754, AVR-724) | None of it is M3 scope; each needs its own design and approval. Never a Seerr admin or global key in the browser |
| Q1: no Jellyfin 12.x upgrade now | A future owner-controlled upgrade, with rollback and deployed-contract proof |
| Q2: M3 Seerr handoffs only where the URL, version and ID allowlist is proven | No request filing in M3 |
| Q3: Komga shared view unchanged; Q4: books and comics handoffs only | No member Komga API keys |
| Q5: minimal OpenAPI facts with hashes and provenance | Legal disposition still open |
| Q6: social deferred (AVR-749); AVR-723 NextUp not approved | No prototype |

## Owner decisions, 2026-10-27: Media security locks for the beta

Recorded from the owner's instruction of 2026-10-27 ("Lock security decisions: JWT-required for Audiobookshelf,
HTTPS across machines (isolated Docker networking exempt), and no username reuse"). Enforced in code where Home
can enforce it; the rest is operator policy.

| Decision | Consequence |
|---|---|
| **JWT required with the Audiobookshelf admin token** | Real mode with `AUDIOBOOKSHELF_BASE_URL` refuses to start unless `HOME_IDENTITY_MODE=jwt_required` (`settings.py`). Mock mode and the sealed owner preview are unaffected |
| **HTTPS across machines; Docker's isolated networking exempt** | In real mode every upstream URL is `https://`, or plain `http://` only to loopback, `host.docker.internal` or a single-label Docker service name (`settings.plain_http_allowed`). Every non-loopback IP literal and dotted name over http is refused. The owner preview's example moves to Docker names (`preview.env.example`, `docs/runbooks/home-owner-preview.md`) |
| **No username reuse** | An Authentik username, once used, is never given to another person. Offboarding deactivates (never deletes and recreates) and disables the member's Jellyfin and Audiobookshelf accounts (`scripts/offboard.py`), so the name maps to `disabled` in Home. Home has no stable account id (IDENTITY-MAPPING.md section 5.6), so this policy is what keeps a new person away from a former member's libraries. No link table |

## Owner decisions, 2026-10-27: G1 applied (D-2, AVR-356)

Owner approved the preflight, apply and validation in chat on 2026-10-27, window "now". Applied from `main`
5a2ddbf (PR #108: explicit subnets) at about 14:40 PDT; signed off 14:46 PDT. Evidence on the host in
`/mnt/avrana_media/.backups/batch7-20261027/` (rollback material with `SHA256SUMS`, state before and after).

| Decision / result | Consequence |
|---|---|
| **G1 applied**: `authentik_portal` 10.220.29.0/24, `authentik_kindle` 10.220.30.0/24, `authentik_olivetin` 10.220.31.0/24, each holding `authentik-server` and one backend; `authentik_frontend` holds server, worker, ldap only | Bridge siblings can no longer reach the portal, Kindle connector or OliveTin. `g1-applied` marker set, so "not applied" and "cannot check" are now health FAILs |
| Preflight 0 STOP / 0 VOID after the B2 off-host cap was raised (uploads had failed since 2026-10-10 with `storage_cap_exceeded`; alerts undelivered, AVR-346) | Off-host backups caught up the same day (13 runs remote) |
| Checks: namespace sharing none (41/41); A 6/6 `200` from `authentik-server`; C controls pass; B 6/6 blocked with forged headers (`curl_rc` 6 names, 28 IPs); E1 6/6 redirected; **E2 passed (owner, member session)**: forged groups gave no Operations tile and `/ops` 404, forged username on Kindle showed only the member's own data | Finding F3 (outpost overwrites client headers) verified on Authentik 2026.5.6 |
| Residuals unchanged | Host namespace (Jellyfin, Home Assistant, Beszel agent) and host shell still reach backend IPs (check D: `200`); D-3 remains the owner's decision. `avrana-boot-verify.service` failed unit since 2026-10-23 is unrelated and still open |

## Owner decisions, 2026-10-27: Media title sheet (live-beta review)

Recorded from the owner's chat of 2026-10-27, after reviewing a streaming app's details view: "1. Okay, do your best.
2. Yes that's fine." (1: the sheet's open and close may run longer than the 200 ms tier; 2: the page script may fetch
the title page from Home's own origin.)

| Decision | Consequence |
|---|---|
| **Title sheet** | On shell pages a title link opens the title page as a modal sheet over the page (`home.js` part 8): it grows out of the tapped art (380 ms open, 300 ms close, one iOS sheet curve), the URL becomes the title's own, Back, Escape, the close button, a press outside or a downward pull close it, and focus returns to the link. With Reduce Motion it opens and closes at once. Without script, or on anything unexpected, the link navigates as before. Page-to-page transitions stay tier 3 (200 ms). |
| **`connect-src 'self'` on shell pages** | Replaces D13's "no requests of its own" for one request: the same-origin title page the member opened, with the member's cookies, no redirect followed, parsed inert and stripped of script, frames, objects and forms. The worker's own `connect-src` (D12) is unchanged; other routes still have none. |
| **Recently added cards open the title page** | Where the library offers the permission-checked item lookup; Continue cards still open the item where it plays. |
| **Backdrop on the title page** | A Jellyfin item with a backdrop leads its title page (and the sheet) with it, full width. |

## Owner decisions, 2026-10-27: Media chrome pass (after streaming and community app reviews)

Recorded from the owner's chat of 2026-10-27 ("Perfect... the bottom should still shrink down and in some. Proceed").

| Decision | Consequence |
|---|---|
| **Glass only on floating chrome** | The tab bar, corner buttons, the sheet's close button and the scrolled header. Everything on the page itself is matte. |
| **Places are matte launch tiles** | Equal columns that share the row (a place a member cannot use is absent, so the others widen); an arrow, and words for assistive technology, on Watch, Listen and Read, which leave Avrana. |
| **Filters are a ledger** | Home's Recently added and the Library's libraries: words on one hairline, the chosen one Cream with a short yellow rule. Shown only with two or more libraries. |
| **Header and dock follow the scroll** | The header stays at the top; once scrolled, Home's lockup slims into a glass ceiling; on the way down the places (or the Library's filters) tuck under it and the tab bar shrinks down and in (icons only, still a full target). Scrolling up a little, either end, or focus brings everything back. Nothing changes size, so the page never jumps. |
| **The title's action stays pinned** | On the title page (above the tab bar) and at the foot of the sheet. |

## Owner decisions, 2026-10-27: Media Home filters, Up next and Library layouts

Recorded from the owner's chat of 2026-10-27 ("the top menu items ... should be filters, not links ... give the library
multiple options for views ... Go at it").

| Decision | Consequence |
|---|---|
| **The tuck is a slow glide** | "The slightest pan in and out": the header row, the Library's filters and the tab bar move over about half a second on one even ease-in-out curve (no spring), a short distance, fading as they go. |
| **The shrunk dock is centred** | With the labels faded, the icons settle to the middle of the bar. |
| **Home's top row is filters** | For a member with two library places or more, the row under the lockup is All, Watch, Listen, Read (each only if the member has it), a ledger like the Library's, via `/?for=<place>`; it narrows Home to that place's libraries and never leaves Avrana. The chosen place's own site is one link at the foot of the filtered Home. Request stays on the Library and Help under Me. A member with one place keeps the places bar. Replaces the places bar of D16 for those members. |
| **Watch has Up next, Movies and TV shows** | The Watch filter shows Continue, then Up next (the next unwatched episode of each series the member watches, from the library's own Next Up list, minus what Continue already shows), then Recently added split into Movies and TV shows. Up next is a new read-only, user-scoped Jellyfin route (`/Shows/NextUp`), added to the allow-list, the contract and the OpenAPI subset (regenerated from the same two spec files, hashes unchanged). It is asked for only on the Watch filter, after the other sections, so a member never holds more than two calls to that library at once. |
| **The Library has four layouts** | Large artwork (the default), small artwork, details (a small cover beside the words) and a plain list, chosen with `?view=` from four icon links; the chosen library and the chosen layout keep each other. Not remembered between visits (the page script stores nothing). |

## Owner decisions, 2026-10-27: Library layout menu, Listen shelves, comics and ebooks on the live beta

Recorded from the owner's chat of 2026-10-27 ("condensed into one small button ... more fluid ... reevaluate the
view types ... categories for Listen ... flip the switch for doing comics and ebooks now").

| Decision | Consequence |
|---|---|
| **One layout button** | The four layout icons become one small glass button beside Search ("Shelves ⌄") that opens a menu. With the page script, choosing a layout rearranges the cards in place, each gliding from its old place to its new one (about 0.4 s), and replaces the address; without it each choice is an ordinary link. |
| **Layouts reworked** | Shelves (rows that scroll sideways, the default; a page with one row shows it as a grid), Grid (large covers), Compact (a dense wall of small covers, one line of title) and List (a small cover beside its words). The text-only list was dropped: covers are how people find media. `large`, `small` and `details` still open the layouts that replaced them. Choosing one library now shows its own rows (Movies and TV shows; Audiobooks' Recently added and shelves). |
| **Audiobooks lead with what the library holds** | Audiobooks now has Recently added (it had none, so the Library said "Nothing recently added"), from each of the member's own libraries, every item checked against the member's own permissions exactly as search. Listen (Home) and the Audiobooks chip add four shelves: New releases (published this year or last), Classics (the library's own genres named "classic"), Short listens (30 minutes to 5 hours) and Epic listens (20 hours or more). No "trending" shelf: the upstream has no listening signal that is not another member's own history. Read shows one row per library (Comics, Books). |
| **Comics and ebooks on the live beta** | The live beta compose adds Komga (`http://komga:25600`) and Calibre-Web (`http://calibre-web-automated:8083`) as shared views with the owner preview's existing secret files, on the owner's no-restriction statement of 2026-10-15 (recorded here: no member is restricted in either). A member still needs `avrana-comics` or `avrana-books`. Runbook: `docs/runbooks/home-beta-live.md`. |

## Owner decisions, 2026-10-27: Recently added window, Library top right, artwork corners

Recorded from the owner's chat of 2026-10-27 ("don't add just any old recently added books ... 'Search' feels
redundant ... too rounded of corners ... a balance that's based on genuinely intelligent design principles").

| Decision | Consequence |
|---|---|
| **Recently added means the last two months** | Audiobooks' Recently added keeps only items added in the last 60 days (`RECENT_DAYS`), however few. When none were, Listen's first row is titled Recently released and shows the newest releases instead; the separate New releases row is then not repeated. |
| **Library top right is one icon button** | The Search utility is gone from the Library (Search is already a tab) and the layout button shows only the current layout's icon; its name stays for screen readers. The Library is otherwise left as it is for now. |
| **Artwork corners scale with the art** | Cover and poster corners are about 5% of the frame's width, clamped to 4–12px (a 180px cover gets 9px, a rail poster 6px, a list thumbnail 4px, wide backdrops 12px), replacing one 20px radius. Containers keep their larger radii, so an inner curve is always the tighter one. |

## Owner decision, 2026-10-28: comics Recently added

Recorded from the owner's chat of 2026-10-28 ("the 'recent comics added' ... are not accurate what so ever"; agreed
plan: "this works for now", may change later).

| Decision | Consequence |
|---|---|
| **Comics Recently added is by date added, one per series, last two months** | Komga's Recently added reads `GET /api/v1/books?sort=created,desc` instead of `/api/v1/books/latest`: live, that route orders by last modification, so one new issue lifted its whole series, and 1,214 of 1,788 books share the 2025-07-26 bulk-scan second. Only books added in the last 60 days count, one book (the newest) per series. |
| **Comics fall back to Recently released** | A New releases shelf (sorted by `metadata.releaseDate`, one per series; release dates more than 92 days ahead are ignored, since comics carry cover dates about two months ahead) follows Recently added on Comics. With nothing added in 60 days, Comics shows Recently released instead, and Read shows "Recently released comics" in the Comics row. The Library page is unchanged. |

## Owner decision, 2026-10-27: artwork may be revalidated from the browser cache

Recorded from the owner's chat of 2026-10-27 ("Do 3 and then 4", 4 being "artwork caching": artwork was
`private, no-store`, so the phone fetched every cover again on every page).

| Decision | Consequence |
|---|---|
| **`/art` is `private, no-cache` with an `ETag`** (amends D11 for `/art` only) | The browser may keep a cover but must ask before each use. The request runs the full check (group, then per-member visibility for Jellyfin and Audiobookshelf); only a member allowed to see it gets `304 Not Modified`, everyone else the same 404. No proxy may keep it (`private`). The ETag is a digest of the image bytes. Every other response stays `no-store` |
| **No `max-age`** | A `max-age` would let the browser show a cover without asking, past a removed group or a hidden item. Revalidation saves the bytes over the tunnel, not the round trip |
| Sign-out unchanged | `/signout`'s `Clear-Site-Data: "cache", "storage"` (D10) still clears the kept covers on that device |

## Proposed, 2026-10-28: Home asks Shelfarr for books on the member's behalf

Recorded from the owner's chat of 2026-10-27 ("Upgrade Shelfarr and proceed with implementing that part even").
Proposed in a draft PR; nothing is deployed and the switch is off by default.

| Decision | Consequence |
|---|---|
| **Shelfarr 2026.10.19.1 is the API** | The upgrade (PR #122) adds `/api/v1` with scoped tokens. Home holds ONE owner-minted token with `search:read requests:write requests:admin`; `requests:admin` is what lets it name the member. Members never mint keys. |
| **The member is the principal** | The request names the verified principal's username, lower-cased. A form never carries a person; a member Shelfarr does not know is "not set up" (sign in to the request website once), never a request as someone else. |
| **One signed form, no script** | Each format button is a small POST form whose fields Home signed for that member (HMAC, 15 minutes, per-process key), behind a same-origin check and a 4 KiB body limit. With "Sign in on a TV" (`/me/tv`), these are the only POSTs Home answers; every other path stays 501. |
| **Formats follow library groups** | Ask for the ebook needs `avrana-books`; Ask for the audiobook needs `avrana-audiobooks`. A member with neither gets the standard 404. |
| **Nothing is promised** | The words say a request was sent and where the book appears once it arrives; never that it has arrived, and never a queue position. |

## Decided by the delegate, 2026-10-28: request brokers, matching and forks

Recorded from the owner's chat of 2026-10-28 ("Proceed building this, make your own decisions, but do it
intelligently and weigh the scope and philosophy of the rest of the project"). Each is the delegate's call under that
instruction; the owner can reverse any of them.

| Decision | Consequence |
|---|---|
| **Brokers need verified identity in real mode (F-D5, extended)** | Seerr's global key is accepted for the beta, on the same terms as the Audiobookshelf admin token: real mode only with `HOME_IDENTITY_MODE=jwt_required`. The rule also covers Shelfarr, whose token can name any member. The Seerr fork (scoped keys) stays the long-term fix. |
| **Home never acts as an administrator** | Seerr user 1 and any user with ADMIN or MANAGE_* bits are refused; the owner asks in Seerr itself. |
| **No approval step in Shelfarr for now (F-D2)** | Members' book requests go straight through, behind Home's per-member guard (no repeat within a minute, at most 10 asks an hour across books and films). Seerr keeps its own per-user approval and quotas. Revisit if downloads become a problem. |
| **Exact matches only are claimed (M-3)** | "Already in Books / Audiobooks / Movies and TV" only from a shared id, and for per-member libraries only after the member's own lookup. A title-only match is a hint ("may already have this. Check") linking to Home's own search. |
| **The index reads the databases read-only now (M-2)** | `tools/build_catalogue_index.py` reads Calibre, Shelfarr, Omnibus and Komga databases with `mode=ro`; fork API routes can replace it later. |
| **Cap monitor installed (M-1)** | `api-caps-monitor.timer` runs on avrana from `~/.local/share/avrana-api-caps` (outside the canonical tree, so drift stays clean until #125 lands). Alert mail is not configured on the host (`services/backups/.env.alert` absent), so incidents go to the journal only. |
| **Forks are published to the owner's GitHub, not upstream (F-D1)** | The owner chose this on 2026-10-28: `rcnechamkin/shelfarr` (`avrana/2026.10.19.1`) and `rcnechamkin/omnibus` (`avrana/v1.4.4`) carry the patches and build images to GHCR; nothing is proposed upstream without the owner. |
| **Post-redirect-get for the ask pages** | A POST answers 303 to the page's fixed path; the outcome and search term ride a one-shot in-memory flash. No request input is ever in a `Location`, and a reload never re-asks. |
| **Form key from the JWT secret** | Open ask pages survive a Home restart; the key is labelled so it cannot be confused with any other use of the secret. |
| **Search cache and per-member allowance** | Shelfarr results are shared for ten minutes (Home's own account), Seerr results per member for two; 40 upstream searches per member per ten minutes. Protects Hardcover/Google Books caps behind Shelfarr and Seerr's TMDB quota. |
| **A stale index makes no claims** | Older than 36 hours or no build time: no "Already in" at all. |
| **Credentials left in place (F-D3, F-D4)** | The Omnibus `JobLog` row and Shelfarr's legacy `api_token` are not touched: deleting rows in a live database or clearing a token whose consumer is unknown could break something for little gain (both are visible only to the owner). The fork fixes the leak at its source. |

## Owner decisions, 2026-10-28: Home may create missing library accounts

Recorded from the owner's chat of 2026-10-28 ("Yes it should", on Home creating a member's library accounts).

| Decision | Consequence |
|---|---|
| **Home creates missing Jellyfin and Audiobookshelf accounts** | Direction approved; the how is the plan in `docs/design/ACCOUNT-PROVISIONING.md`. Built as `avrana_home/provision.py` (ADAPTER-CONTRACT 15), off until `HOME_PROVISION_ACCOUNTS` names a library. |
| **P1-P5 as recommended** ("Go with your recommendations") | P1: created on the member's first Home visit; a background sync from Authentik may come later. P2: Jellyfin accounts see all libraries, as the LDAP plugin gives. P3: Audiobookshelf accounts get the server's defaults for a new user, as OIDC auto-register gives. P4: beta members first: settings refuse it without `HOME_ALLOWED_USERS`. P5: at most 10 attempts per hour (`HOME_PROVISION_CAP_PER_HOUR`). |

## Owner decision, 2026-10-28: comics Continue reading with members' own Komga keys

Recorded from the owner's chat of 2026-10-28 (asked whether each member's Komga On Deck could be shown; agreed to a
temporary admin key for a one-time run: "Yes"; asked that new members be covered; chose to build the run, the
invite-time step and the fallback).

| Decision | Consequence |
|---|---|
| **Comics Continue reading is each member's own** | Home holds one Komga API key per member (`secrets/komga_member_keys`, KOMGA_MEMBER_KEYS_FILE, filed by signed email) and reads, with it alone, that member's in-progress books and then their On Deck. A separate two-route GET allow-list; the shared account (ADAPTER-CONTRACT 12.2) is never used for it and keeps its three routes. Needs real mode and `HOME_IDENTITY_MODE=jwt_required`. |
| **Keys are made by an owner-run tool with a temporary admin key** | Komga makes keys only for the signed-in account, so `tools/komga_member_keys.py` sets a random password for the member (one Komga sign-out), makes the `avrana-home` key as them and forgets the password. The admin key is typed at a hidden prompt and deleted afterwards; Home never holds it (decision of 2026-10-15 unchanged). ADMIN accounts are never touched. |
| **New members are covered at invite time** | `--member <email>` creates the Komga account by email with the Authentik first-sign-in defaults when none exists; Komga links the first Authentik sign-in to it by email. Runbook: docs/runbooks/komga-member-keys.md. |
| **No key, no change** | A member without a key sees the shared rows only, as before. A refused member key is an empty row and never counts against the shared circuit. |
| **Members never paste a key** | Owner, 2026-10-28: "I don't want people to have to copy and paste stuff as that would add friction." Keys come only from the owner-run tool; there is no paste-your-own-key option in Home. |

## Owner decision, 2026-10-28: Home makes members' Komga keys

Recorded from the owner's chat of 2026-10-28 (asked how to be sure every member gets their comics Continue
reading; chose "Home does it" over running the tool at each invite).

| Decision | Consequence |
|---|---|
| **Home holds a Komga admin key, for making members' keys only** | Replaces the decision of 2026-10-15 ("no admin key") for this one use, as Home already holds admin-level Jellyfin and Audiobookshelf credentials for #128. `secrets/komga_admin_token`, used only by provision.py (`KomgaKeyCreator`); the read adapters never see it. |
| **A member's first visit makes their key** | With `komga` in HOME_PROVISION_ACCOUNTS, a member with the comics group and an email but no key gets one on their first Home page (one Komga sign-out for an existing account; a new account gets Authentik sign-in defaults). The owner's own admin account gets its key without a password change; other admins are never touched. |
| **Keys live in Home's one writable folder and reload by themselves** | `state/komga_member_keys` (gitignored, uid 1000, 0700) is mounted read-write; Home re-reads it when it changes, so neither Home nor the owner's tool needs a restart. `tools/komga_member_keys.py --missing` checks coverage. |

## Proposed, 2026-10-28: Continue in the order you used things, and New for You

From the owner's request of 2026-10-28 ("If I haven't listened to an audiobook in a week, it shouldn't be at the front
of the line"; "I shouldn't have to go digging to find out that a new issue of Absolute Batman came out today if I'm
totally caught up"). Draft until the owner merges it.

| Decision | Consequence |
|---|---|
| **Continue is ordered by the member's own last activity** | Each Continue item carries `active` (contract `MediaItem.active`, UTC): Jellyfin `UserData.LastPlayedDate`, Audiobookshelf the progress entry's `lastUpdate`, Komga `readProgress.readDate`. Up next and On Deck items carry their series' last watch or read (one more member-scoped call each). Items without a date go last. The round-robin by library is gone. |
| **New for You sits under Continue** | A new optional section `for_you`, asked of Jellyfin, Audiobookshelf and Komga (Komga only with the member's own key). It holds what arrived in the last 30 days that is the NEXT episode, issue or book of a series the member is caught up on: Jellyfin Up next and Komga On Deck filtered by arrival date, Audiobookshelf finished-series arithmetic, and newly added films from a TMDb collection the member has watched. Each title appears once on the page: New for You wins over Continue, Up next and New Releases. |
| **No Trakt** | Every signal New for You needs (what the member watched, read, listened to, and what arrived) is already in Jellyfin, Komga and Audiobookshelf, per member. Trakt would add history from outside Avrana and recommendations, at the cost of a per-member OAuth link and a third-party copy of viewing history. Revisit for a "Coming soon" shelf or recommendations. |

## Owner decision, 2026-10-30: Komga member keys are minted where the password lives

Defect S-01 (RC2 security audit, docs/audits/2026-10-29-rc2-security-reliability-audit.md): Home made a member's
Komga key by resetting their Komga password with its admin key, which silently broke the OPDS password the
enrollment stage `avrana-komga-create` set on purpose. Phase 0 was applied live on 2026-10-30 (komga dropped from
HOME_PROVISION_ACCOUNTS, the admin token line commented out). The owner approved this design and rejected "members
paste their API key" (unchanged from 2026-10-28). Supersedes "Owner decision, 2026-10-28: Home makes members' Komga
keys". Runbook: docs/runbooks/komga-key-lifecycle.md; contract: ADAPTER-CONTRACT 15.1.

| Decision | Consequence |
|---|---|
| **Principle: enrollment owns the member's Komga credential lifecycle; Home only consumes keys** | Home never holds a Komga admin credential for keys and never sets or changes a member's Komga password. Checked against Komga's source (master, 2026-10-30; the deployed image is pinned by digest, earlier notes say 1.25, not tested live): keys are self-service only, `POST /api/v2/users/me/api-keys` as the signed-in account; no admin route mints another user's key; an API key may list and delete its own account's keys. |
| **Phase 1: Home's key intake** | `PUT /internal/komga-key/<subject>`, off unless `HOME_KEY_INTAKE_TOKEN[_FILE]` is set. Bearer token (constant time), peer in `HOME_INTERNAL_CIDR` (the `authentik_home_beta` subnet) and no outpost or proxy header, since public requests arrive from the same container through the embedded outpost (the /readyz pattern), JSON body of at most 512 bytes. The key is checked with Komga and filed under the email of the account it opens; idempotent; never echoed or logged. Subject = sha256 of the Authentik `sub` (the identity bindings digest; never an email in a URL). A subject not bound in the identity bindings file is accepted only with `source=enrollment`, which runs before the member's first sign-in. |
| **The intake token is the security control** | The subject/`source` rule is a consistency check only (it catches a misdirected call; `source` is the caller's claim). Cross-member injection is impossible because a key is always filed under the email of the Komga account it opens, never where the subject points; proved by `services/avrana-home/tests/test_komga_key_lifecycle.py` (`IntakeRuleTests.test_a_key_is_filed_under_its_own_account_whatever_the_subject_says`). |
| **Phase 1 and 4: the member controls it** | Me -> Comics shows Connected / Not connected to Comics members (`HOME_KOMGA_CONNECT=on`); Disconnect revokes the key in Komga with the key itself (`DELETE /api/v2/users/me/api-keys/{id}`, id kept in `<keys file>.ids`) and drops it. `scripts/offboard.py` does the same for a leaving member (dry run reports only). |
| **Phase 3 (shipped second): Connect comics, one time** | A Comics member with no key types their Avrana password once; Home signs in to Komga as them (login = their email, as `avrana-komga-create` creates the account), mints `avrana-home`, files it through the intake's code path and discards the password (body only; never logged, stored, in a URL or an exception). Five tries per 15 minutes. |
| **Phase 2: enrollment mints the key** | Additive policy `avrana-komga-key-mint` on the enrollment login stage, after `avrana-komga-create`: while the password is in the flow it signs in to Komga as the new member, makes the key and PUTs it to the intake with `AVRANA_HOME_KEY_INTAKE_TOKEN` (authentik-server environment, read at run time). It never fails enrollment. Applied by the owner by hand into the LIVE blueprint (repo and live blueprints differ, PR #167). |
| **Phase 4: the key factory is retired** | The admin-key branch of provision.py runs only with `HOME_KOMGA_LEGACY_PROVISION=on` (default off; settings refuse `HOME_PROVISION_ACCOUNTS=komga` and `KOMGA_ADMIN_TOKEN` without it). Deleted, with the admin-token setting, the `komga_admin_token` secret and the tool's password-resetting modes, once the owner confirms the enrollment stage works live. |
| **Open: members whose password the old path reset** | Their key works but their OPDS apps no longer sign in; members in `state/komga_member_keys.reset_failed` have neither. Repair needs a separate owner decision (runbook, section 4). |

## Owner-requested, 2026-10-30: a password reset also resets the Komga copy and renews Home's key

Pre-beta audit docs/audits/2026-10-30-komga-auth-cleanup-audit.md (brief: remove redundant Home <-> Komga
authentication without an auth rewrite; a member must never be asked for an obsolete password). Extends "Komga member
keys are minted where the password lives" to the one other place the password is in a flow. Runbook:
docs/runbooks/komga-password-sync.md. Draft until the owner merges and applies it.

| Decision | Consequence |
|---|---|
| **Komga's API cannot take Authentik tokens, so per-member keys and the Komga password copy stay** | Komga 1.25.0 has no OAuth2 resource server and mints keys for the signed-in account only. Home keeps consuming keys minted inside Authentik flows; no admin key returns to Home; members never paste keys (unchanged). |
| **The reset flow syncs Komga** | Additive policy `avrana-komga-password-sync` on `avrana-recovery`'s write binding (which must re-evaluate policies): for a Comics member, set the Komga password to the new one with the admin API key (create the account if missing, enrollment roles), then mint and file the `avrana-home` key exactly as enrollment does (`source=recovery`). Never fails the reset; nothing secret logged. The same binding is in the unapplied `avrana-account` password flow. |
| **Connect comics stays as the fallback and asks for the CURRENT password** | Copy no longer says "use the one you joined with"; a failing password points to the reset, which heals the account. Members damaged by the old provisioner (`reset_failed`) repair themselves with one reset: the "Open" row of the S-01 decision is answered this way, no owner-held password needed. |
| **Komga's web login: hide the form, let Authentik sign members in** | Owner setting (Komga Server settings -> UI): hide login fields; auto login only if the iPhone pass accepts its popup. Destination preservation across Komga's OAuth2 login is an upstream limit (first visit per 7-day session lands on the dashboard); not built around. |
| **Deferred** | Connected Apps UI, universal SSO, a "Connect via Avrana" flow that would retire Home's password form. |
