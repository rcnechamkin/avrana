# Books / audiobooks / comics: open-source reuse audit (r1)

Researched 2026-10-26. Read-only. Source read with `gh api` at the pinned SHAs below. Labels: **CONFIRMED** means the file or release note was read at the pin. **HYPOTHESIS** means it's inferred and not verified.

## 0. Pinned inventory

| Project | URL | Latest release (date) | SHA inspected | Code license | Assets/logo license | Activity / maturity |
|---|---|---|---|---|---|---|
| Audiobookshelf | https://github.com/advplyr/audiobookshelf | v2.37.2 (2026-10-23) | `edb1f7efc92ecacdef51aafb4d9d5054ce10604f` (master, 2026-10-23) | GPL-3.0 | No separate asset license, so the repo GPL-3.0 applies to files. The name and logo have no trademark grant (unverified) | ~14.8k stars, pushed 2026-10-23, frequent releases. Mature |
| Komga | https://github.com/gotson/komga | 1.29.1 (2026-10-14) | `023ec905c10a35bbb8e29095420d266cd3adad60` (master, 2026-10-21) | MIT | Same as code (MIT). No separate logo terms found (unverified). Bundles a Readium CSS LICENSE at `komga-webui/src/styles/readium/LICENSE` | ~6.8k stars, pushed 2026-10-25. Mature, single main maintainer |
| Calibre-Web (upstream) | https://github.com/janeczku/calibre-web | 0.6.27 (2026-08-08) | `6e840acbda8d62fdd159bf3855c01872d629a914` (master, 2026-09-20) | GPL-3.0 | GPL-3.0 (repo) | ~18.5k stars. Mature, slow cadence |
| Calibre-Web-Automated | https://github.com/crocodilestick/Calibre-Web-Automated | v4.0.8 (2026-09-28). **Avrana runs v4.0.6** (released 2026-02-04, tag commit `1b80f9a74b3db1fe9b35978e38d2e62fcb6a7246`) | v4.0.6 tag `1b80f9a7…`; main head `4fc2c4459965efb1b8ff43ea7849c2f47a755d9c` (2026-10-01) | GPL-3.0 (headers say GPL-3.0-or-later) | GPL-3.0 (repo) | ~6.5k stars, pushed 2026-10-09. Active, fast-moving fork |
| Readium ts-toolkit ("Readium Web") | https://github.com/readium/ts-toolkit | tag `navigator/2.14.0` (2026-10-23) | `03ce8bbf1229515eab0f55f3ed1d48e95895af76` (develop) | BSD-3-Clause | BSD-3 | 158 stars. Active. Org-backed (Readium Foundation) |
| Thorium Web | https://github.com/edrlab/thorium-web | v1.7.0 (2026-10-07) | `8d49c2b116e93ca50d4ccfdcb3226efde7bc49c8` (develop) | BSD-3-Clause | BSD-3 (Thorium brand: unverified) | 112 stars. Active. EDRLab-backed |
| Readium go-toolkit (streamer) | https://github.com/readium/go-toolkit | no GitHub releases | `28dc69c0bab02beb94f1675970bc4b41eca856e9` (develop, 2026-09-29) | BSD-3-Clause | BSD-3 | 70 stars, active |
| Omnibus | https://github.com/hankscafe/omnibus | v1.4.9 (2026-10-21). **Avrana runs v1.4.4** (released 2026-08-13, tag commit `6c63779c7b7a8dc3f7400dc1ae5cbdbce7b8f8ec`) | v1.4.4 tag and main `6055d6ee34865852c801dced9540c270ab248d25` | GPL-3.0 (LICENSE at v1.4.4) | GPL-3.0 (repo) | 90 stars. Very active, mostly AI-assisted code ("vibe-coded", per the README). Young |
| CompleteSeries | https://github.com/xfriedspudx/completeseries | none | `59b200ed4e336de8d4ffd048b837bda9ae9e368a` (main, 2026-08-27) | **NONE**: no LICENSE file; `package.json` is `"private": true` with no license field, so all rights are reserved | none | 53 stars, small. V2 is a TS/React browser rewrite |

---

## 1. Audiobookshelf (ABS) @ `edb1f7ef`

Routes come from `server/routers/ApiRouter.js`. Everything is mounted under `/api` behind `auth.ifAuthNeeded(authMiddleware)` (`server/Server.js` L354).

### Feature to endpoint

| Feature | Endpoint | Evidence | Status |
|---|---|---|---|
| Current user | `GET /api/me` | ApiRouter L173 | CONFIRMED |
| Items in progress (continue listening/reading) | `GET /api/me/items-in-progress?limit=25` | ApiRouter L191. `MeController.getAllLibraryItemsInProgress` L485: filters `!isFinished && (currentTime>0 \|\| ebookProgress>0)`, sorts by `progressLastUpdate` desc, returns `{libraryItems:[…minified, progressLastUpdate]}` | CONFIRMED |
| All media progress | `GET /api/me/progress` | L176 | CONFIRMED |
| Single progress | `GET /api/me/progress/:id/:episodeId?` | L183 | CONFIRMED |
| Update progress | `PATCH /api/me/progress/:libraryItemId/:episodeId?`, `PATCH /api/me/progress/batch/update` | L184-185 | CONFIRMED |
| Hide from continue listening | `GET /api/me/progress/:id/remove-from-continue-listening` | L182 | CONFIRMED |
| Listening sessions (self) | `GET /api/me/listening-sessions`, `GET /api/me/item/listening-sessions/:libraryItemId/:episodeId?` | L179-180 | CONFIRMED |
| Listening sessions (admin, other user) | `GET /api/users/:id/listening-sessions`, `GET /api/sessions`, `GET /api/sessions/open` | L140, L234-236 | CONFIRMED |
| Personalized shelves | `GET /api/libraries/:id/personalized` | L82. Shelf ids in `server/models/LibraryItem.js` L360-544: `continue-listening`, `continue-reading`, `continue-series`, `recently-added`, `recent-series`, `discover`, `listen-again`, `read-again`, `newest-authors`, `newest-episodes` | CONFIRMED |
| Recently added | the `recently-added` shelf in `/personalized`. Podcasts also have `GET /api/libraries/:id/recent-episodes` (L92) | as above | CONFIRMED |
| Library search | `GET /api/libraries/:id/search?q=` | L84 | CONFIRMED |
| Cover | `GET /api/items/:id/cover?width=&height=&format=&raw=` | L112, `LibraryItemController.getCover` L401 | CONFIRMED |
| Author image | `GET /api/authors/:id/image` | Auth.js ignorePatterns | CONFIRMED |
| API keys | `GET/POST/PATCH/DELETE /api/api-keys` | L338-341 | CONFIRMED |

### Auth, tokens, scoping

- **Covers need no auth.** `server/Auth.js` L21 has `ignorePatterns` = `^(base/api)?/items/[^/]+/cover$` and `/authors/[^/]+/image$`. `authNotNeeded()` skips auth for GET on these. Avrana can hotlink covers by item UUID without a token. Privacy note: anyone who knows the UUID can fetch the cover. CONFIRMED.
- **JWT** comes from `Authorization: Bearer` or a `?token=` query parameter (Auth.js L126). CONFIRMED.
- **API keys (v2.26.0, 2025-07-12).** The release note reads "API Key config page for managing configurable API Keys that act on behalf of users"; v2.26.0 also brought "JWT authentication with refresh tokens". Model `server/models/ApiKey.js` has `userId`, `createdByUserId`, `expiresAt`, `permissions`, `isActive`. **Only admins can create or manage them**: `ApiKeyController.middleware` L196 returns 403 unless `isAdminOrUp`. A key acts as its `userId`, so it's per-user scoped, but an admin has to mint it (no self-service). Only root can mint keys for root (L68). CONFIRMED.
- **OIDC:** `OidcAuthStrategy` exists, plus `/auth/openid/config` (Auth.js L464). CONFIRMED (feature exists. Not exercised).
- **Library access enforcement:** user permissions (`server/models/User.js` L131-181) are `accessAllLibraries`, `librariesAccessible`, `accessAllTags`, `itemTagsSelected`, `selectedTagsNotAccessible` (tag denylist), and `accessExplicitContent`. `LibraryController.middleware` L1475 checks `checkCanAccessLibrary`. Item access goes through `checkCanAccessLibraryItem`. CONFIRMED.
  - HYPOTHESIS: `/api/me/items-in-progress` doesn't re-check library or tag access. It builds from the user's own progress rows (MeController L485-523), so an item the user lost access to could still appear. Low severity.

### Item metadata
- The book model has `isbn` and `asin` (`server/models/Book.js` L98-100, L155-156) and exposes them in JSON (L357-358, L564-565). CONFIRMED.

### Web client deep links
- Nuxt dynamic routes (`server/Server.js` L415-434) include `/item/:id`, `/library/:library`, `/library/:library/search`, `/library/:library/series/:id?`, `/collection/:id`, `/playlist/:id`, `/share/:slug`, and `/audiobook/:id/chapters`. CONFIRMED.
- **No autoplay deep link.** `client/pages/item/_id/index.vue` reads no `route.query` (the only `route` use is the login redirect, L151-153). Playback has to be started by the user in the ABS UI. The ebook reader is a modal with no own URL. CONFIRMED that no query parameter is read. "No autoplay anywhere" is a HYPOTHESIS (the React client wasn't checked).
- An `ABS_REACT_CLIENT_PATH`/Next.js experimental client exists (Server.js L438+). It could change routes later.

### Docs
- https://api.audiobookshelf.org comes from `audiobookshelf/audiobookshelf-api-docs`. Last commit `a62c7f9d` on **2025-07-08**, which is *before* v2.26.0 (API keys and JWT refresh) and ~11 minor versions behind v2.37.2. **Stale.** CONFIRMED.
- The main repo now has `docs/openapi.json`, `docs/root.yaml`, `docs/schemas.yaml`, `docs/controllers/`, and `docs/objects/` at the pin. That's the better source, though how complete it is wasn't checked. CONFIRMED that it exists.

### Progress truthfulness
- Progress is per user (`req.user.mediaProgresses`). It has `currentTime`, `isFinished`, `ebookProgress`/`ebookLocation`, and `lastUpdate`. It's accurate to the extent that clients sync it. The ABS web player and mobile apps write it. CONFIRMED (model). Sync cadence: HYPOTHESIS.

---

## 2. Komga @ `023ec905`

### Feature to endpoint

| Feature | Endpoint | Evidence | Status |
|---|---|---|---|
| Keep reading (in-progress books) | `POST /api/v1/books/list` with `ReadStatus IN_PROGRESS` condition, sort `readProgress.readDate,desc` | webui `komga-webui/src/views/DashboardView.vue` L424-426 | CONFIRMED |
| On deck (next unread in started series) | `GET /api/v1/books/ondeck?library_id=` | `BookController.kt` L232-245: per-user (`principal.user.id`), authorized libraries, restrictions | CONFIRMED |
| Latest books | `GET /api/v1/books/latest` | L205 | CONFIRMED |
| New / updated / latest series | `GET /api/v1/series/new`, `/series/updated`, `/series/latest` | `SeriesController.kt` L347, L386, L425 | CONFIRMED |
| Search | `POST /api/v1/books/list` (`fullTextSearch`), `POST /api/v1/series/list`. Deprecated `GET /api/v1/books?search=` | BookController L119-199 | CONFIRMED |
| Book detail (incl. `readProgress`, `metadata.isbn`) | `GET /api/v1/books/{bookId}` | L275. `rest/dto/BookDto.kt` L28 `readProgress`, L65 `isbn` | CONFIRMED |
| Mark progress | `PATCH /api/v1/books/{bookId}/read-progress` (page/completed), `DELETE …` | L694, L719 | CONFIRMED |
| Series progress | `POST/DELETE /api/v1/series/{id}/read-progress`, `GET/PUT /api/v2/series/{id}/read-progress/tachiyomi` | SeriesController L747-782 | CONFIRMED |
| Readium progression (locator) | `GET/PUT /api/v1/books/{id}/progression` (also `/opds/v2/books/{id}/progression`) | `interfaces/api/CommonBookController.kt` L371-408 | CONFIRMED |
| WebPub manifest | `GET /api/v1/books/{id}/manifest`, `/manifest/epub`, `/manifest/pdf`, `/manifest/divina`, and `/positions` | BookController L545-616 | CONFIRMED |
| Thumbnails | `GET /api/v1/books/{id}/thumbnail`, `/thumbnails/{tid}`, `GET /api/v1/series/{id}/thumbnail` | BookController L329-344, SeriesController L475 | CONFIRMED |
| OPDS | v1.2 at `/opds/v1.2/` (`opds/v1/OpdsController.kt` L79). v2 at `/opds/v2/` (`opds/v2/Opds2Controller.kt` L67) | | CONFIRMED |
| Kobo sync | `/kobo/{apiKey}/…` | SecurityConfiguration L170-225 (role `KOBO_SYNC`, key extracted from the URI) | CONFIRMED |
| KOReader sync | `/koreader/**`, `X-Auth-User` header = API key, role `KOREADER_SYNC` | SecurityConfiguration L198-230 | CONFIRMED |
| Per-user API keys | `GET/POST /api/v2/users/me/api-keys`, `DELETE /api/v2/users/me/api-keys/{keyId}` | `UserController.kt` L283-307 | CONFIRMED |

### Auth, scoping
- **REST API keys:** header `X-API-Key` (`SecurityConfiguration.kt` L235-238, added after BasicAuth L164). Added in **1.20.0** (2025-02-19), per the release note "REST API … supports using API keys … through a `X-API-Key` header". Keys first appeared in 1.12.0 for Kobo. `domain/model/ApiKey.kt` has `userId`, `key`, `comment`. **They're self-service and per user.** CONFIRMED.
- Other auth methods: session cookie, HTTP Basic, remember-me, and OAuth2/OIDC login (SecurityConfiguration L129-157). CONFIRMED.
- **Thumbnails need auth.** `/api/**` and `/opds/**` are `.authenticated()` (L103-108). Thumbnails aren't in the `permitAll` list (L85-100). The only anonymous paths are `/api/v1/books/{id}/resource/**` (EPUB resources, authorized inside the controller), fonts, claim, oauth2 providers, `/opds/v2/auth`, and `/koreader/users/create`. So Avrana must proxy covers server-side with the member's key, or rely on the browser's Komga cookie. CONFIRMED.
- **Per-user restrictions:** `KomgaUser.kt` L17-20 has `roles` (FILE_DOWNLOAD, PAGE_STREAMING, KOBO_SYNC, KOREADER_SYNC, ADMIN), `sharedLibrariesIds`, `sharedAllLibraries`, and `restrictions: ContentRestrictions`. `ContentRestrictions.kt` has `ageRestriction`, `labelsAllow`, `labelsExclude`. Controllers apply `getAuthorizedLibraryIds` plus `restrictions` (e.g. ondeck L240-243). CONFIRMED.

### Web reader deep links
- `komga-webui/src/router.ts`: `/book/:bookId` (L254) and `/series/:seriesId` (L248) are detail pages. `/oneshot/:seriesId` (L260) is for one-shots. `/book/:bookId/read` (L295) is the comic/divina/pdf reader and `/book/:bookId/read-epub` (L301) is the EPUB reader. CONFIRMED (route paths). Query parameters like `?page=` or `incognito`: unverified.
- The webui EPUB reader is `@d-i-t-a/reader` (R2D2BC fork `github:gotson/R2D2BC#fork`, `komga-webui/package.json`), not ts-toolkit. CONFIRMED.

### Identifiers
- `BookMetadata.isbn` (`domain/model/BookMetadata.kt` L16) is exposed in BookDto and in the WebPub manifest as `identifier = "urn:isbn:…"` (`interfaces/api/WebPubGenerator.kt` L221). The webui depends on `@w0s/isbn-verify`. No ASIN field. CONFIRMED.

### Progress truthfulness
- `ReadProgress.kt` holds `bookId, userId, page, completed, readDate, deviceId, deviceName, locator (R2Locator)`. It's per user and per device-tagged. It comes from the webui, Kobo sync, KOReader sync, OPDS-PSE, and Tachiyomi/Mihon. Per user and good quality. CONFIRMED (model).

---

## 3. Calibre-Web (upstream @ `6e840acb`) and CWA (v4.0.6 @ `1b80f9a7`)

### JSON API?
**There's no general JSON REST API.** CONFIRMED by reading `cps/web.py` and `cps/opds.py`. The JSON-ish endpoints are:
- `GET /ajax/listbooks` (`web.py` L837, `@user_login_required`, session). It feeds the bootstrap table. It's internal and not a contract.
- `/get_{authors,publishers,tags,series,languages}_json` (autocomplete, L262-286).
- `GET /ajax/book/<uuid>` (`opds.py` L445-457, basic auth). This is Calibre Companion metadata from template `cps/templates/json.txt`: title, authors, tags, formats, cover URL, download links. **No identifiers/ISBN.** HYPOTHESIS: it queries `calibre_db.session` directly with `uuid LIKE %uuid%` and *doesn't* use `get_filtered_book`, so per-user tag/language visibility restrictions may not apply here.
- POST `/ajax/toggleread/<id>` (L176), POST `/ajax/bookmark/<id>/<fmt>` (L156).

### OPDS
- Root at `/opds` (`opds.py` L46-48). Feeds include `/opds/new`, `/discover`, `/rated`, `/hot`, `/author`, `/series`, `/shelfindex`, `/shelf/<id>`, `/readbooks`, `/unreadbooks`, `/search/<q>`, `/search?query=`, `/cover/<id>`, and `/download/<id>/<fmt>/`. CONFIRMED.
- **Auth:** `@requires_basic_auth_if_no_ano` means **HTTP Basic** with the user's Calibre-Web password, or a trusted reverse-proxy header login if configured (`cps/usermanagement.py` L61-68, L117-150). It allows anonymous access if anonymous browsing is enabled. There are no API keys or tokens. CONFIRMED.
- Per-user feeds: `/opds/readbooks`, `/opds/unreadbooks`, and shelves follow the user's sidebar visibility (`check_visibility`). CONFIRMED.
- **Identifiers in OPDS:** `cps/templates/feed.xml` only emits `<id>urn:uuid:{{uuid}}</id>`, with no ISBN. Same in CWA v4.0.6 `feed.xml`. CONFIRMED. ISBNs live in Calibre `metadata.db` table `identifiers` (`cps/db.py` L98-178, default type `isbn`). Reaching them means reading `metadata.db` read-only, or scraping the HTML `/book/<id>`.

### Reader, covers, per-user state
- Reader: `GET /read/<int:book_id>/<book_format>` (`web.py` L1570; CWA L2783), e.g. `/read/42/epub`. It's `@login_required_if_no_ano` + `@viewer_required`. Book page: `/book/<id>` (L1628). CONFIRMED.
- Cover: `/cover/<id>[/<resolution>]` with `@login_required_if_no_ano` (session or anonymous) (L1156-1158). OPDS cover `/opds/cover/<id>` uses basic auth. CONFIRMED.
- Per-user state (`cps/ub.py`): `ReadBook.read_status` takes UNREAD=0, FINISHED=1, IN_PROGRESS=2 (L403-413). `Bookmark.bookmark_key` holds the in-browser reader position (CFI) (L425-432). `KoboReadingState` and `KoboBookmark.progress_percent` come from Kobo sync (L456-478). Shelves are per user (L362). CONFIRMED.
- Kobo sync: `cps/kobo.py` and `cps/kobo_auth.py` use a per-user auth token in the URL. CONFIRMED (files exist. Protocol detail not re-read).

### CWA-specific additions (v4.0.6 tree)
- KOReader sync server `/kosync`, `/kosync/users/auth`, `GET /kosync/syncs/progress/<document>`, `PUT /kosync/syncs/progress` (`cps/progress_syncing/protocols/kosync.py` L438-578), plus the bundled `koreader/plugins/cwasync.koplugin`. CONFIRMED.
- Magic shelves (`cps/magic_shelf.py`, `/opds/magicshelfindex`, `/opds/magicshelf/<id>`, `opds.py` L570-641). Hardcover metadata/ID (`cps/services/hardcover.py`, `cps/tasks/auto_hardcover_id.py`). Duplicates (`cps/duplicates.py`). Stats centre (`/cwa-stats-show`, `cwa_functions.py` L975+). OAuth (`cps/oauth.py`, `oauth_bb.py`). `cps/audio.py`. `/user_profiles.json`. CONFIRMED that the files and routes exist. None of these is a general JSON API for books or progress.

### Progress truthfulness
- Upstream: a 3-state read flag, plus a per-user web-reader CFI bookmark, plus a Kobo percent. There's no unified percent API. CWA adds KOSync percent/progress. A hub can show "in progress / finished" per user only via `/opds/readbooks` or by scraping. **Weak for a hub.** CONFIRMED (models). HYPOTHESIS: the IN_PROGRESS state is set only by Kobo sync or CWA KOSync, not by the web reader.

---

## 4. Readium Web (ts-toolkit plus Thorium Web)

- **"Readium Web" today** is `readium/ts-toolkit` (README title: "Readium Web, Next generation SDK for publications in Web Apps"). It publishes `@readium/shared`, `@readium/navigator-html-injectables`, and `@readium/navigator` (v2.14.0, BSD-3-Clause, `navigator/package.json`). Navigator modules at the pin include `epub`, `webpub`, `divina` (comics), `audio`, `readaloud`, `decorations`, `preferences`, and `protection` (`navigator/src/`). CONFIRMED. R2D2BC (Komga's reader) is the older community "Readium 2 Web" generation.
- **Thorium Web** (`edrlab/thorium-web` v1.7.0, BSD-3) is a Next.js 16 / React 19 reader app and also an npm package `@edrlab/thorium-web` (StatefulReader component). It depends on `@readium/navigator ^2.11.1` and friends. The README shows you hand it a fetched `rawManifest` plus `selfHref`. Its sample deployment uses "Go-Toolkit on Google Cloud Run" as the streamer. CONFIRMED.
- **What it needs:** a Readium Web Publication Manifest (RWPM) with resource URLs reachable by the iframe, and ideally positions and progression. A streamer such as `readium/go-toolkit` (BSD-3, no releases) can generate these from EPUB files. **Key finding: Komga already acts as a Readium streamer.** It serves `/api/v1/books/{id}/manifest[/epub|/pdf|/divina]`, `/positions`, and `/progression`, and its EPUB `resource/**` is anonymous-routable with in-controller authorization. CONFIRMED (endpoints). Calibre-Web has no manifest, so it would need go-toolkit pointed at the Calibre library (read-only mount).
- **Fit for an in-PWA reader (HYPOTHESIS, effort/risk):**
  - Pro: BSD-3 (compatible with anything). Covers EPUB, comics (DiViNa), and audiobooks (`audio` navigator) in one component. Komga's progression endpoint could keep progress truthful.
  - Con: Avrana is server-rendered Starlette with progressive JS. Thorium Web is a heavy React/Redux/react-aria bundle. ts-toolkit alone is lighter but needs custom UI. Cross-origin is a problem: navigator iframes load resources by URL and can't attach an `X-API-Key` header. So resources must be same-origin proxied through Avrana (or rely on Komga cookies on a shared parent domain). Progress written by an Avrana reader to Komga `/progression` must use the member's own key. A Calibre path needs a new go-toolkit service.
  - Estimate: Komga EPUB plus a same-origin proxy is about 1-2 weeks of prototype, medium risk. Generalizing to Calibre, ABS audio, and comics is several weeks, high risk. Recommendation: **STUDY**, and keep handing off to native readers for now.

---

## 5. Omnibus (v1.4.4 deployed; latest v1.4.9)

- **What it is:** a self-hosted **comic and manga manager**: requests, indexer search, downloading, metadata from ComicVine and Metron, library management, and a web reader. It's inspired by ReadMeABook. Next.js 15, Tailwind v4, Prisma, a Rust engine, and SQLite/Postgres. The author says it's AI-assisted ("vibe-coded"). GPL-3.0. CONFIRMED (README, LICENSE at v1.4.4).
- At v1.4.4 (`6c63779c`): `src/app/api/opds`, `src/app/api/koreader`, `src/app/api/user/api-keys/route.ts`, `src/app/api/admin/api-keys/route.ts`, and NextAuth `src/app/api/auth/[...nextauth]`. That means OPDS, KOReader sync, and per-user API keys already exist at v1.4.4. CONFIRMED (paths). Endpoint contracts weren't read.
- **Komga-compatible API (`src/app/komga/api/v1/...`, for Paperback) is NOT in v1.4.4.** It's present at v1.4.9 (`6055d6ee`). CONFIRMED by tree diff. HYPOTHESIS: after upgrading, Avrana's Komga adapter could partly talk to Omnibus, but only the subset Paperback needs (books, pages, search, catalog).
- Maturity: young, high churn (v1.4.4 to v1.4.9 in ~10 weeks, 792 to 1061 tree entries).

## 6. CompleteSeries

- **What it is:** a browser-only TS/React app (V2) that finds gaps in **Audiobookshelf** series. It talks to ABS directly from the browser and matches against Audible (the default) or experimental Apple Books, Google Books, and Open Library. Matching evidence uses ASIN, SKU, ISBN, title, author, narrator, series name, and position. CONFIRMED (README).
- **There's no license**, so its code can't be reused. The idea (ASIN/ISBN-first series-gap detection on top of ABS `/api` data) can be studied. CONFIRMED (no LICENSE in tree, `package.json` private).

---

## 7. Cross-cutting

### Identifiers (to link ebook and audiobook editions)

| Service | ISBN | ASIN | Other | Where |
|---|---|---|---|---|
| Audiobookshelf | yes | yes | ABS item UUID | `Book.js` isbn/asin in item JSON. CONFIRMED |
| Komga | yes (`metadata.isbn`, single) | no | `urn:isbn` in WebPub manifest, links | BookDto L65, WebPubGenerator L221. CONFIRMED |
| Calibre-Web / CWA | in `metadata.db` `identifiers` (isbn, amazon, goodreads, etc.) | as an `amazon` identifier type in Calibre (HYPOTHESIS: type naming) | uuid in OPDS | **Not in OPDS and not in the companion JSON.** You need a read-only `metadata.db` read or HTML scrape. CONFIRMED |
| Omnibus | GTIN per-issue field (README) | no | ComicVine/Metron ids | HYPOTHESIS (README only) |

Practical linking: ABS isbn/asin joined to Calibre `identifiers` (isbn, amazon) through a read-only SQLite read of CWA's `metadata.db`, with Komga isbn added for comics and light novels. ISBNs differ between editions (an audiobook ISBN differs from the ebook ISBN), so a work-level join needs title+author normalization, or a work id (Open Library / Hardcover; CWA already fetches Hardcover IDs). HYPOTHESIS.

### Truthful per-user progress

| Service | Per user? | Granularity | Hub-readable API | Verdict |
|---|---|---|---|---|
| ABS | yes | seconds, `isFinished`, ebook % / location, `lastUpdate` | `/api/me/items-in-progress`, `/api/me/progress[/:id]` with the member's token/API key | **Truthful, good** |
| Komga | yes | page, completed, R2 locator, device, readDate | `/books/list` IN_PROGRESS, `/books/ondeck`, `readProgress` in BookDto, `/progression` | **Truthful, good** |
| Calibre-Web / CWA | yes | 3-state flag, CFI bookmark, Kobo/KOSync % | only OPDS `/opds/readbooks`/`unreadbooks` (basic auth) or internal ajax | **Weak**. Shows only finished vs not, with no clean percent |
| Omnibus | yes (README: continue reading, on deck) | page | OPDS home "Continue Reading" (README, post-1.4.4 overhaul) | unverified |

## 8. Recommendations

| Project | Verdict | Why |
|---|---|---|
| Audiobookshelf | **KEEP / RUN + INTEGRATE** | Rich per-user API. Unauthenticated covers make cards easy. Admins mint per-member API keys. Hand off to `/item/:id` (no autoplay). Use in-repo `docs/openapi.json`, not the stale api.audiobookshelf.org |
| Komga | **KEEP / RUN + INTEGRATE** | Best API: self-service per-user `X-API-Key`, on-deck, IN_PROGRESS, ISBN. Proxy thumbnails (auth required). Deep link `/book/:id/read` or `/read-epub`. MIT |
| Calibre-Web-Automated (fork v4.0.6) | **KEEP / RUN, ADAPT integration** | No JSON API. Use OPDS (basic auth, per-member creds) for lists/read state. (A read-only `metadata.db` read for ISBN was considered and is NOT recommended: AGENTS.md forbids upstream DB reads; see the audit ledger.) Hand off to `/read/<id>/epub`. GPL-3.0: don't copy code into Avrana unless Avrana goes GPL. Note it's 2 patch releases behind v4.0.8 |
| Calibre-Web (upstream) | **STUDY** | Reference only. CWA supersedes it in this deployment |
| Readium ts-toolkit / Thorium Web | **STUDY** (possible later ADAPT) | BSD-3 and capable. Komga already serves RWPM, positions, and progression. In-PWA reading costs a same-origin proxy and a JS reader. Hand-off is cheaper now |
| Readium go-toolkit | **STUDY** | Needed only if Calibre books are read in-PWA |
| Omnibus | **RUN (as is), STUDY** | Comic manager GPL-3.0, young, AI-generated churn. v1.4.4 lacks the `/komga` compat API (added by v1.4.9). Integrate via OPDS or API keys only after reading its contracts |
| CompleteSeries | **REJECT for code reuse / STUDY idea** | No license (all rights reserved). The ASIN/ISBN series-gap idea is worth studying |
