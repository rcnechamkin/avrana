# Open-source reuse audit for Avrana Media (R1, AVR-746)

Date: 2026-10-26. Status: **research and decisions proposed for owner review.** Documentation only: no code,
no service, no host access, no member data, no live upstream request. Base: `main` at `99f0d7c`.

Strategy this audit serves: Linear document *Avrana Media · Media-first OSS reuse and four-sprint plan
(2026-10-26)*. It does not change any earlier owner decision (`docs/DECISIONS.md`, especially 2026-10-11:
upstreams preserved and unmodified, one small custom application, no frames, proxy injection, upstream patches,
custom players or dedicated search engine; request filing through Avrana is out of M3).

Evidence appendices (upstream source read with `gh api` at the pinned commits; every claim labelled
CONFIRMED or HYPOTHESIS):

- [Jellyfin server, web, Vue, SDKs, OpenAPI](2026-10-26-oss-reuse/jellyfin.md)
- [Audiobookshelf, Komga, Calibre-Web(-Automated), Readium, Omnibus, CompleteSeries](2026-10-26-oss-reuse/books.md)
- [Seerr, Shelfmark, Shelfarr, Tracearr, Radarr/Sonarr](2026-10-26-oss-reuse/requests.md)
- [NeoDB, Floppy, NodeBB, identifiers, ActivityPub](2026-10-26-oss-reuse/social-ids.md)

Three claims were re-checked by hand in upstream source before writing this summary, and held: Jellyfin
`GetItemImage` carries no `[Authorize]` (`Jellyfin.Api/Controllers/ImageController.cs`, v10.11.11);
Audiobookshelf's auth middleware skips `/api/items/:id/cover` (`server/Auth.js` `ignorePatterns`, `edb1f7ef`);
Komga has an API-key test suite (`ApiKeyTest.kt`) and security wiring for it.

Labels used below: **KEEP** (Avrana code already adequate), **RUN** (keep the upstream service), **INTEGRATE**
(call a documented upstream API), **ADAPT** (reuse compatible source with provenance), **STUDY** (patterns only),
**BUILD**, **REJECT**.

## 1. Headline decisions

1. **Avrana Home stays the one custom application, and it is already the right shape.** The adapter contract,
   per-member cache, authorized search, title pages and hand-off allow-list on `main` match or exceed what the
   upstream clients do for a multi-service hub. No upstream client, SDK or framework would replace it more
   cheaply. KEEP.
2. **No upstream source code is copied into Avrana.** Every serious candidate client is GPL-2.0, GPL-3.0 or
   AGPL-3.0 (ledger, section 5). The reuse is RUN + INTEGRATE over HTTP, plus STUDY of interaction patterns.
   The only permissively licensed candidates with real fit are Komga (MIT), Seerr (MIT) and Readium (BSD-3), and
   none of their code is needed now.
3. **Universal media identity (R2) must be built in Avrana, from IDs the upstreams already hold.** Jellyfin
   exposes `ProviderIds` (Imdb, Tmdb, Tvdb, ...) but cannot be queried by them; Audiobookshelf items carry `isbn`
   and `asin`; Komga books carry `isbn`; Calibre-Web's OPDS exposes only a UUID. No upstream offers a cross-service
   identity, so this is a genuine BUILD, kept small, in memory and edition-aware (section 4, R2-B).
4. **Requests stay hand-offs to Seerr.** Seerr (MIT, v3.5.1) has one global, unscoped API key; `X-API-User` lets
   any key holder act as any user, admins included. Proxying requests would make Avrana the trust boundary for
   request rights. Reading availability with the key and deep-linking to Seerr's own `/movie/{tmdbId}` and
   `/tv/{tmdbId}` pages is the safe pattern, and it only becomes possible once R2 carries the TMDB id.
5. **Social is a thin optional Avrana module later, not NeoDB.** NeoDB (AGPL-3.0, ~11 containers, no OIDC so
   Authentik cannot be its identity provider) is too heavy for about 15 members and would hold a second account and
   a duplicate catalogue per member. Its data model and ActivityPub extensions are worth STUDYING so a native module
   can interoperate later. Floppy is a media tracker (Yamtrack fork) that imports playback history: REJECT as a
   dependency. NodeBB: REJECT for now. Detail: R4 (AVR-749).
6. **Jellyfin 10.11.11 is the last 10.x release; 12.x is current (12.3, 2026-10-23).** Avrana's adapter already
   uses the 10.9+ routes (`/UserItems/Resume`, `/Items/Latest`, `/Items`), which still exist in 12.3. The upgrade is
   an owner decision outside this sprint; R2-A below makes its API impact measurable offline.

## 2. What Avrana already has (inventory against `main` 99f0d7c and open PRs)

| Capability | Where | State |
|---|---|---|
| Member identity (Authentik JWT/headers), per-service account mapping | `principal.py`, `outpost_jwt.py`, `app/identity.py`, `IDENTITY-MAPPING.md` | On main, offline-proven; G1 live enforcement is owner-gated (AVR-356) |
| Read-only guarded adapters: Jellyfin, Audiobookshelf, Komga (shared view), Calibre-Web OPDS (shared view) | `adapters/*.py`, `ADAPTER-CONTRACT.md` 11-13 | On main, synthetic fixtures; no recorded live contract yet (owner-run capture tool exists) |
| Continue (Jellyfin Resume, Audiobookshelf progress), truthful Resume/Open rule | `adapters`, `viewmodel.continue_state`, `CONTINUE-AND-HANDOFF.md` | On main (AVR-381 In Review, AVR-504 In Progress) |
| Recently added (all four) | adapters `_recent_items` | On main (AVR-382 In Progress) |
| Authorized cross-library search, never cached | `aggregate.search`, `ADAPTER-CONTRACT.md` 14 | On main (AVR-383 Done) |
| Title pages, fresh permission-checked lookup | `/title/<service>/<id>`, 14.7 | On main (AVR-384 In Progress; no synopsis yet) |
| Fixed-host hand-off links, strict id patterns | `contract.HANDOFF_BASE`, `_HANDOFF_PATH` | On main; paths doc-verified, not device-verified (AVR-479) |
| Per-member in-memory cache, revocation on next request | `cache.py`, `CATALOG-CACHE-DECISION.md` | On main; no index needed (AVR-503 In Review) |
| Circuit breakers, deadlines, degradation | `resilience.py`, `aggregate.py` | On main |
| Server-side artwork proxy with per-member visibility check | `fetch_artwork`, `app/artwork.py` | On main |
| Concept K shell, four tabs, PWA, motion, Library, Search, Me | PRs #65-#71, integration #74 | Draft, owner-gated (AVR-713, AVR-585) |
| External media identifiers (TMDB, IMDb, ISBN, ...) | none | **Gap**: no adapter reads them |
| Next Up, synopsis, backdrops, request status, suggestions | Concept K follow-ups AVR-722..726, AVR-384 note | **Gap**, filed, not approved work |

Open PRs #65-#74 touch `app/main.py`, `app/viewmodel.py`, `app/routing.py`, templates and CSS. **None touches
`contract.py`, `aggregate.py`, `cache.py` or `adapters/`**, so R2 adapter work can go to `main` without colliding;
R3 UI work must stack on the Concept K integration branch (#74).

## 3. Feature reuse matrix

"Avrana today" is code on `main`. Pinned versions and file references are in the appendices.

| Feature | Avrana today | Best upstream source | Decision | Notes |
|---|---|---|---|---|
| Catalogue browse / Library | Recent rows; Library page in draft #70 | Jellyfin `/Items` (parentId, sort), ABS `/api/libraries/:id/items`, Komga `/api/v1/series` | KEEP + INTEGRATE incrementally | Through existing adapters only |
| Search | Fan-out, never cached | Jellyfin `/Items?searchTerm` (used), `/Search/Hints` (not needed), ABS library search (used), Komga `GET /books?search` (deprecated since 1.19, `POST /books/list` replaces it) | KEEP | Komga GET removal would show `unavailable`, never empty (already handled); watch 1.29.x |
| Title detail | Name, kind, year, creator, artwork, primary action | Jellyfin `Overview`, ABS `description`, Komga `summary`, `ProviderIds` | INTEGRATE (R2-C) | Synopsis is the missing piece of AVR-384 |
| Artwork | Per-member proxy, visibility re-check | Jellyfin `ImageTags`/`ImageBlurHashes` + `tag` param | KEEP; STUDY blurhash placeholders | Jellyfin and ABS images are anonymous upstream; Avrana never exposes upstream image URLs, so it does not widen that |
| Continue Watching | `/UserItems/Resume` | same, plus `/Shows/NextUp` | KEEP; INTEGRATE Next Up later (AVR-723) | Next Up has no position: must read "Open", never "Resume" |
| Continue Listening | ABS user record + item lookups | ABS `/api/me/items-in-progress` needs the member's own token (admin-created API keys, 2.26+) | KEEP | Per-member ABS keys would be "manual member keys", which AVR-504 rules out |
| Comics / books progress | Not offered (shared accounts) | Komga per-member API keys (1.20+, `X-API-Key`), `/books/ondeck`; Calibre-Web read status only | KEEP not-offered | Per-member Komga keys reverse the 2026-10-15 shared-view decision and need member action: owner question Q3 |
| Playback | Hand-off to service web apps | Jellyfin web `#/details?id=`; no play/resume deep link exists in jellyfin-web | KEEP | Avrana's "Resume" opens the details page; the member presses play (already worded so) |
| Native app hand-off | None | Swiftfin `jellyfin://{server}/{user}/item/{id}` (master; release unverified); Android app has no scheme | STUDY | Needs user id and a released app; not now |
| In-app readers | None (hand-off) | Readium ts-toolkit (BSD-3); Komga already serves Readium manifests | STUDY | A reader needs a same-origin proxy for media bytes, which the gateway rule forbids by default (AVR-370, M5) |
| Requests | Request chooser hands off to request sites | Seerr deep links `/movie/{tmdbId}`, `/tv/{tmdbId}`; availability via `mediaInfo.status` | INTEGRATE read-only later (R2-D) | No proxying of request writes |
| Book/comic requests | Hand-off | Shelfarr (GPL-3.0, scoped per-user tokens; deployed version unclear), Shelfmark (no API key, spoofable header auth) | STUDY Shelfarr; REJECT Shelfmark integration | Acquisition-source legality is an owner policy call |
| Availability | Implied by presence in a library | Seerr `mediaInfo.status` (1-5) | INTEGRATE later | Do not call Radarr/Sonarr from Home (more admin keys, less meaning) |
| Media identity across services | None | Upstream-held IDs only | BUILD small (R2-B) | Section 4 |
| Statistics / history | None, by design | Tracearr (AGPL-3.0, owner-role key reads every member's history and IP geolocation) | REJECT for Home | Fine as an owner-only tool; never a member data source |
| Recommendations | None | Jellyfin `/Items/{id}/Similar` (not checked), Seerr discover | STUDY | AVR-725 / AVR-460 stay gated |
| Social: ratings, reviews, lists | None | NeoDB model and AP extensions | STUDY; BUILD thin module only on owner go (R4) | Never automatic from viewing |
| Federation | None | ActivityPub (WebFinger, actor, inbox/outbox, HTTP signatures) | STUDY; defer | Phase B only |
| Client SDKs | Hand-written stdlib adapters | Jellyfin TS SDK (MPL-2.0, TS only), Python apiclient (GPL-3.0, incomplete) | REJECT as dependencies | |
| API contracts | Hand-written fixtures + owner capture tool | Jellyfin per-release OpenAPI spec (315 paths at 10.11.11); ABS `docs/openapi.json` (repo; api.audiobookshelf.org is stale since 2025-07); Seerr `seerr-api.yml` | INTEGRATE as offline contract checks (R2-A) | Route and parameter names only |

## 4. Ranked implementation backlog

Scored 1-5 (5 best) on member value, reuse efficiency, legal clarity, security risk (5 = lowest) and upgrade
burden (5 = lowest). All are fixture-only draft PRs; none needs a credential, a live request or a new store.

| Rank | Slice | Ticket | Value | Reuse | Legal | Security | Upgrade | Base |
|---|---|---|---|---|---|---|---|---|
| 1 | **R2-A** Jellyfin allow-list checked against the official 10.11.11 and 12.3 OpenAPI route/parameter tables | AVR-747, AVR-376 follow-up | 3 | 5 | 4 | 5 | 5 | main |
| 2 | **R2-B** Media identity: validated external IDs on `MediaItem` (Jellyfin `ProviderIds`; ABS `isbn`/`asin`; Komga `isbn`), work vs edition keys, exact-match only, never shown as text | AVR-747 | 4 | 4 | 5 | 4 | 4 | main |
| 3 | **R2-C** Synopsis on title pages (adapter field from `Overview`/`description`/`summary`, plain text, bounded) | AVR-384 | 5 | 5 | 5 | 4 | 4 | main (adapter), then #74 (template) |
| 4 | **R3-A** Title page shows the synopsis and work-level "also available as" links inside Concept K | AVR-748, AVR-719 | 5 | 4 | 5 | 4 | 4 | #74 |
| 5 | **R2-D** Seerr title deep link for a known TMDB id (no API call; owner wording decision) | AVR-747, AVR-726 | 3 | 5 | 5 | 5 | 4 | after R2-B |
| 6 | **R2-E** Jellyfin Next Up (`/Shows/NextUp`, `enableResumable=false`), Open-only | AVR-723 | 4 | 5 | 5 | 4 | 4 | main; UI needs owner decision |
| 7 | **R4-A** Social seam + "social off/down never changes core pages" tests, synthetic only | AVR-749 | 2 | 3 | 5 | 5 | 5 | after R3 |

Regression tests each slice must keep green: `tests/test_jellyfin_adapter.py`, `test_audiobookshelf.py`,
`test_komga.py`, `test_calibre_web.py`, `test_contract.py`, `test_boundary.py`, `test_api_contract.py`,
`test_search.py`, the webtests isolation suites, and the repository offline runner.

### R2-B identity rules (proposed contract, detailed in the R2 PR)

- **Only IDs an upstream already holds.** No outbound call to TMDB, TVDB, IMDb, Open Library, ComicVine or any
  other external service from Home. TMDB/TVDB/IMDb terms (non-commercial, attribution, paid TVDB) then never
  apply to Avrana itself (appendix social-ids.md, Part B).
- **Strict validation, allow-listed keys.** `tmdb` digits, `imdb` `tt` + digits, `tvdb` digits, ISBN-10/13 with
  check digit, ASIN `[A-Z0-9]{10}`. Anything else is dropped, never guessed or normalised beyond hyphens.
- **Work vs edition.** TMDB/IMDb/TVDB identify a work (movie or series) or an episode; ISBN and ASIN identify an
  edition and differ between ebook and audiobook. Two items are "the same title" only on an exact work-level key;
  two book items share an edition key only when the ISBN matches exactly. Title/author similarity never links.
- **Ambiguity is a state, not a guess.** One key matching several items of the same kind in one service is kept
  as ambiguous and not linked.
- **Per-member only.** Identity is derived from items the member's own adapters returned; no shared index, no
  persistence, nothing cached beyond the existing per-member TTLs.

## 5. License and provenance ledger

Integration over HTTP creates no copyleft obligation for Avrana. Copying source would. "Assets" means logos and
artwork shipped in the repo.

| Project | Version / commit read | Code license | Assets / marks | Allowed use by Avrana |
|---|---|---|---|---|
| Jellyfin server | v10.11.11 `1fbd8739`; latest v12.3 | GPL-2.0 | "Jellyfin" and logo are Jellyfin, Inc. trademarks; brand assets CC-BY-SA-4.0 (jellyfin-ux) | RUN, HTTP API. Name only as compatibility ("for Jellyfin"); never its logo as ours |
| jellyfin-web | v10.11.11 `35c0793e` | GPL-2.0 | as above | RUN as hand-off target; STUDY router |
| jellyfin-vue | HEAD `aeee28fa` (experimental, no stable release) | GPL-3.0 | as above | STUDY only |
| jellyfin-sdk-typescript | v1.0.2 `780ffa49` (12.x); 0.13.0 for 10.11 | MPL-2.0 | | STUDY |
| jellyfin-apiclient-python | v1.20.2 `f3fa5673` | GPL-3.0 | | REJECT |
| Jellyfin OpenAPI spec | `jellyfin-openapi-10.11.11.json` (repo.jellyfin.org) | generated from GPL-2.0 code; status unclear | | Use route and parameter **names** only as test data, with source URL and SHA-256; never vendor the full file (owner question Q5) |
| Audiobookshelf | v2.37.2 `edb1f7ef` | GPL-3.0 | no separate asset license found | RUN, HTTP API |
| Komga | 1.29.1 `023ec905` | MIT | no separate asset license found | RUN, HTTP API; code reusable with notice if ever needed |
| Calibre-Web | 0.6.27 `6e840acb` | GPL-3.0 | | RUN (via CWA), OPDS |
| Calibre-Web-Automated | v4.0.6 `1b80f9a7` (deployed fork); latest v4.0.8 | GPL-3.0 | | RUN; never read `metadata.db` (AGENTS.md, no upstream DB reads) |
| Readium ts-toolkit / Thorium Web / go-toolkit | navigator 2.14.0 `03ce8bbf` / v1.7.0 `8d49c2b1` / `28dc69c0` | BSD-3-Clause | | STUDY; ADAPT possible later with notice |
| Omnibus | v1.4.4 `6c63779c` (deployed); latest v1.4.9 | GPL-3.0 | | RUN as is |
| CompleteSeries | `59b200ed` | **no license** (all rights reserved) | | REJECT code reuse |
| Seerr | v3.5.1 `c167958a` | MIT | | RUN; read API + deep links |
| Shelfmark | v1.3.6 `0e8608c4` (deployed); latest v1.5.1 | MIT | | Owner tool only |
| Shelfarr | v0.1.0 `f69538ab` (label; deployed build unclear); HEAD `436642c7` | GPL-3.0 | | STUDY |
| Tracearr | v3.1.1 `9c625a9c` | AGPL-3.0 | | Owner tool only; REJECT for Home |
| Radarr / Sonarr | v6.4.4 / v4.0.20 | GPL-3.0 | | Not called from Home |
| NeoDB | 0.19.9.1 `e7020d2f` | AGPL-3.0 (network use: modified versions must offer source to users) | | STUDY data model and AP wire format (ideas, not code) |
| Floppy | v26.10.22 `52c17cdb` | AGPL-3.0 | | STUDY; REJECT as dependency |
| NodeBB | v4.16.4 `ce62dcd5` | GPL-3.0 | | REJECT for now |
| Wikidata / MusicBrainz core data | n/a | CC0 | | Possible optional cross-walk, off by default, owner decision |

## 6. Security findings for the owner (no change made)

1. **Upstream artwork is anonymous.** Jellyfin `GET /Items/{id}/Images/{type}` and Audiobookshelf
   `GET /api/items/:id/cover` need no login, so anyone who knows an item id can fetch its picture from the public
   service host. Avrana never exposes upstream ids in image URLs (opaque `/art/` refs), so it adds nothing; the
   exposure is the services' own. Low risk, recorded for completeness.
2. **Jellyfin API keys hold the Administrator role** (`CustomAuthenticationHandler.cs` L53-57). The adapter's
   always-send-`userId` rule (guard-enforced) is what keeps results member-scoped; a request without `userId` is
   unfiltered. The guard already refuses it; R2-A adds a check that every user-scoped route keeps `userId`.
3. **Seerr's single API key can act as any user, including admins.** If request integration is ever approved,
   the member-to-Seerr-id mapping must be server-side, admin ids refused and the endpoint list fixed (AVR-390/393).
4. **Shelfmark trusts a proxy header for identity** with no API key. It must stay reachable only behind
   Authentik forward-auth; never expose it to Home as an integration.

## 7. Owner questions raised by R1

- **Q1** Jellyfin 12.x upgrade: when? (10.11.11 gets no more releases.) R2-A will list the API differences that
  matter to Home.
- **Q2** Seerr title deep links on title pages ("Ask for more seasons" style) once TMDB ids are known: wanted?
- **Q3** Komga per-member progress would need each member to create a Komga API key, which reverses the
  2026-10-15 shared-view decision and AVR-504's "no manual member keys": keep comics progress not offered?
- **Q4** Book and comic requests: keep hand-offs only, or study Shelfarr (deployed build unclear; v0.1.0 has no
  API)? Shelfmark and Shelfarr default to shadow-library sources: a policy call, not a technical one.
- **Q5** May route and parameter names extracted from Jellyfin's published OpenAPI file be committed as test data
  (with source URL and hash), or should the check fetch the file at test time (needs network, so not offline)?
- **Q6** Social (R4): confirm the direction "thin native module modelled on NeoDB, no NeoDB deployment" before
  any prototype beyond fixtures.

## 8. Unknowns (stated, not resolved)

- Deployed versions of Audiobookshelf, Komga and Shelfarr are image digests in Git, not release numbers.
- Whether Calibre-Web-Automated v4.0.6 keeps upstream `/book/<n>` and OPDS search unchanged (owner capture run).
- Whether Swiftfin's `jellyfin://` scheme is in a shipped release.
- Jellyfin `Overview`, `ProviderIds`, ABS `description`/`isbn`/`asin` and Komga `summary`/`isbn` field shapes are
  doc-verified, not live-verified; R2 parsers must treat every one as optional and untrusted.
