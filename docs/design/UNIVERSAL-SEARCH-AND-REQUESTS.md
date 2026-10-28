# Universal search and requests from the PWA: backend feasibility

Status: **research, 2026-10-27. Direction, not approval.** Source-checked against the versions Avrana runs;
nothing was called on a real service. UX is deliberately out of scope. Builds on
[`POST-M3-VALIDATION-PLANS.md`](POST-M3-VALIDATION-PLANS.md) section 3 (Seerr broker),
[`CATALOG-CACHE-DECISION.md`](CATALOG-CACHE-DECISION.md) (no index, AVR-503) and the R1 appendices
`docs/audits/2026-10-26-oss-reuse/requests.md` and `books.md`. Labels: **CONFIRMED** = read in source at the
pinned version; **HYPOTHESIS** = inferred.

## Summary

| | Movies and TV (Seerr) | Ebooks and audiobooks (Shelfarr) | Comics and manga (Omnibus) |
|---|---|---|---|
| Deployed version | **v3.4.1** (compose digest `f4768de5…` = GHCR tag v3.4.1, CONFIRMED) | **v0.1.0** (digest `61c38fc1…`, image revision `f69538a`, built 2026-02-15, CONFIRMED) | **v1.4.4** (compose tag and digest) |
| Server API for search | Yes, `GET /api/v1/search` | **None in v0.1.0.** Current releases: `GET /api/v1/search` | **No.** `/api/search` takes only a browser session |
| Request as the member | Yes: global API key plus `X-API-User: <seerr id>`; Seerr applies that user's permissions and quotas | After an upgrade: a scoped token with `requests:admin` plus `username` | **No.** `/api/request` reads only the NextAuth session cookie, also on `main` |
| Credential Avrana would hold | Full Seerr admin, including the Radarr and Sonarr keys inside it | A token limited to search and requests (no settings, no users) | n/a |
| Duplicate protection | Built in: 409 "Request for this media already exists" | Built in: `DuplicateDetectionService` | Built in, but unreachable |
| Shortest honest path | Broker (read, then gated write) | Upgrade Shelfarr, then a broker | Link out to Omnibus, or an upstream API change |

Universal search is a **federated query, not an index**: Home's existing library search plus three
"discovery" sources (Seerr for film and TV, Shelfarr for books and audiobooks, a comics source), merged and
labelled *In your library / Requested / Can be requested*. The hard parts are identity matching across
catalogues, third-party rate limits and slow metadata providers, not storage. No database is needed for the
first version.

## Part 1. Requesting as the member

### What every request path needs in Home (shared work)

Home today has no write path at all: every adapter route is GET on a fixed allow-list, the CSP has
`form-action 'none'` (only `/search` gets `'self'`), and nothing holds request state. A broker adds:

1. **`avrana_home/requests/`**, beside `adapters/`: one client per service on the same `GuardedTransport`
   pattern (fixed host, fixed route allow-list, method per route, response size and time bounds), with no
   upstream URL ever taken from input.
2. **Member mapping on the server**, from the verified principal only: never a user id from the browser.
   Cached like the adapters' mappings (60 s), refused when the mapped upstream user is an admin.
3. **A confirmation page and one POST.** `GET /request/<service>/<id>` renders what will be asked for (title,
   format, seasons) and a form; `POST` carries a CSRF token. Home keeps no session store, so the token can
   be stateless: an HMAC over (principal subject, service, id, expiry) with a server key, valid for a few
   minutes. The CSP of these two responses gains `form-action 'self'`. Works with JavaScript off.
4. **Idempotency without a store**: rely on each upstream's duplicate check (Seerr 409, Shelfarr duplicate
   detection), plus an in-memory per-member guard of a few seconds against double taps. No automatic retry
   of a write.
5. **One audit line per attempt** (member hash, service, upstream id, outcome class), never a title in the
   general log, matching `logsafe.py`.
6. **A per-member rate limit** (for example 10 requests per hour) and a per-service kill switch setting.
7. **Fakes and contract tests**: `tests/fake_seerr.py`, `tests/fake_shelfarr.py` in the style of
   `fake_jellyfin.py`, including hostile responses (another user's request, admin id, oversize body).
8. **Secrets**: the Seerr key and Shelfarr token in `services/avrana-home` env, listed in `docs/SECRETS.md`,
   never in the browser.

Owner gates (each separate): holding each credential; the first real write per service; AVR-348 (Seerr CSRF
and proxy trust) before anything writes to Seerr.

### Seerr v3.4.1: movies and TV

- **Auth (CONFIRMED, `server/middleware/auth.ts` 13-20 at v3.4.1).** `X-API-Key` equal to the one global key
  runs as user 1 (the original admin) unless `X-API-User: <numeric Seerr id>` is sent, which runs as that
  user with their permissions, quotas and auto-approve. There are no scoped or per-user keys, no OIDC, no
  trusted header (R1 `requests.md` §1).
- **Mapping.** Home already maps each member to their Jellyfin user (identity mapping in the Jellyfin
  adapter). Seerr users carry `jellyfinUserId`; with the key, `GET /api/v1/user` (paged) yields
  `{jellyfinUserId → seerr id, permissions}`. Refuse any id with ADMIN (2) or MANAGE_* bits. A member who has
  never signed in to Seerr has no Seerr user: either the owner imports them (`POST /user/import-from-jellyfin`)
  or Home shows "Open the request site" for that member (the current hand-off).
- **Calls (allow-list).** `GET /search?query=`, `GET /movie/{tmdbId}`, `GET /tv/{tmdbId}` (and
  `/season/{n}`), `GET /request?requestedBy={id}` for the member's own list, `POST /request`
  `{mediaType, mediaId, seasons?}` without `userId`. Never `/settings/*`, `/user/*/settings/*`,
  `/request/{id}/{status}`.
- **Results (CONFIRMED, `server/routes/request.ts` 315-330).** 201 created; 409 duplicate; 403 quota or
  permission; 202 "no seasons available". Each maps to one member sentence.
- **Status.** `mediaInfo.status` (PENDING 2, PROCESSING 3, PARTIALLY_AVAILABLE 4, AVAILABLE 5) and request
  status (PENDING, APPROVED, DECLINED, FAILED, COMPLETED). Show only the member's own requests; for others,
  at most "Already requested", never who (privacy decision for the owner).
- **Risk.** The key is full Seerr admin and exposes the Radarr and Sonarr keys stored in Seerr settings.
  A bug that lets a member choose the id, or drop the header, escalates to admin. Mitigations are the
  allow-list, the server-side mapping, refusing admin ids and always sending `X-API-User`.
- **Effort (HYPOTHESIS).** Read-only status: 2 to 3 days, fixture-only. Write path with confirmation, CSRF and
  tests: 2 to 3 more days. Then a gated live capture and a first real request.

### Shelfarr: ebooks and audiobooks

- **The deployed v0.1.0 has no API (CONFIRMED).** `org.opencontainers.image.revision` of the pinned image is
  `f69538ab…` (the v0.1.0 tag, 2026-02-15); R1 found no `namespace :api` in its routes. The API arrived in
  v0.1.4 (2026-02-16). **An upgrade is the first step**: current releases are calendar-versioned
  (v2026.10.26.1), eight months of migrations ahead of the pin. Owner task: back up `data/` with its key
  files (`docs/services/shelfarr.md`), pin the new tag and digest, check the `HealthCheckJob` duplication
  bug recorded there.
- **Auth (CONFIRMED at `main`).** Bearer tokens with scopes `search:read`, `requests:read`, `requests:write`,
  `requests:admin`, `users:write` (`app/models/api_token.rb` 5-7). Members can mint only the first three, for
  themselves (`profiles_controller.rb` 196-203); a per-member token would be a **manual member step**, which
  Media 2.0 rules out. So: the owner mints one token from an admin profile with
  `search:read requests:read requests:write requests:admin`, and Home passes `username` on create
  (`requests_controller.rb` 132-145). This token cannot change settings or create users, which makes it far
  narrower than Seerr's key. Note `Current.api_admin?` is also true for *any* token owned by an admin user,
  so a dedicated Shelfarr account for Avrana is cleaner than the owner's own.
- **Mapping.** Shelfarr OIDC users are named from `preferred_username` (fallback the e-mail prefix,
  `app/models/user.rb` 256-258), which is the Authentik username Home already has. A member exists only after
  their first Shelfarr sign-in, unless the token also gets `users:write` (not recommended).
- **Calls.** `GET /api/v1/search?q=&limit=&content_kind=` (returns `work_id`, `has_ebook`, `has_audiobook`,
  editions, series), `POST /api/v1/requests` `{work_id, book_type: ebook|audiobook, title, author}` +
  `username`, `GET /api/v1/requests?…` (admin tokens see everyone's: filter by user on the server),
  `DELETE /api/v1/requests/:id` for the member's own. Statuses: pending, searching, awaiting_purchase,
  not_found, downloading, processing, completed, failed.
- **Policy questions (owner).** No approval step was found in `RequestCreationService`: a request starts a
  search and download straight away (HYPOTHESIS, check after the upgrade). Shelfmark also writes into the same
  inboxes, so members should use one of the two, not both (`docs/services/shelfarr.md`). R1's note on
  shadow-library sources applies to which sources stay enabled.
- **Effort (HYPOTHESIS).** Upgrade and verification: owner, about an hour plus checks. Client, mapping and
  tests: 2 to 3 days once the shared request work exists.

### Omnibus v1.4.4: comics and manga

- **No server-to-server request path (CONFIRMED).** `/api/request` and `/api/search` call `getToken` from
  `next-auth/jwt` (session cookie) at v1.4.4 and on `main`; the middleware protects every `/api` path except
  a short list. API keys (`src/lib/api-auth.ts`) are accepted only by OPDS, cron, internal and `/api/v1/stats`.
  Sign-in itself is a same-origin POST with NextAuth CSRF (`sso-architecture.md`).
- **Do not** mint NextAuth tokens in Avrana: that needs `NEXTAUTH_SECRET`, which is also Omnibus's database
  encryption key (`docs/services/omnibus.md`).
- **Options, best first.**
  1. **Link out.** Omnibus has no search deep link (no `/search` page; the home page reads no `q`), so the
     link is to `requestacomic.avrana.net` itself. Zero risk, available now.
  2. **An upstream pull request** adding API-key auth with an on-behalf user to `/api/search` and
     `/api/request`. Omnibus already has an `ApiKey` model and an admin impersonation route, so the change is
     small, but the project is young and largely AI-written; it would need review and a version bump here.
  3. Shelfarr's current releases classify graphic novels and manga through ComicVine (`ContentKinds::GRAPHIC`),
     but as books, not as issues filed into Komga's publisher tree. Not a substitute for Omnibus (HYPOTHESIS).
- **Effort.** Option 1: half a day. Option 2: 2 to 4 days plus upstream review time.

## Part 2. One search for what is in the library and what is not

### What exists

`aggregate.search` already queries every library the member may use, concurrently, under one 2-second cap,
12 results per library, uncached, each adapter checking the member's group first: Jellyfin `/Items`,
Audiobookshelf library search, Komga `books/list`, Calibre-Web OPDS search. AVR-503 measured it and decided
no index is needed for library search.

### Discovery sources (things not on the server)

| Kind | Source | Notes |
|---|---|---|
| Movies, TV | Seerr `GET /search` (TMDB multi-search through Seerr's own TMDB access) | Each result carries `mediaInfo` (status, `jellyfinMediaId`) when Seerr knows it, so "already in the library" comes for free. Drop `person` results. TMDB attribution applies |
| Ebooks, audiobooks | Shelfarr `GET /api/v1/search` (Hardcover, Open Library, Google Books) | Needs the upgrade. Its Hardcover token is **shared with CWA and Shelfmark** and has hit rate limits before (`docs/services/shelfarr.md`) |
| Comics, manga | Not through Omnibus (session only). Options: Shelfarr `content_kind=graphic` (ComicVine through Shelfarr's key), or ComicVine or Metron directly with an Avrana key | ComicVine: per-resource hourly limits and non-commercial terms; Metron: free account, API |
| Podcasts | Audiobookshelf podcast search (iTunes) exists but adding a podcast is an admin action | Not proposed |
| Music | Nothing deployed (no Lidarr; Home does not show Jellyfin music) | Out of scope until a music service exists |

### What the backend needs

1. **A discovery contract** next to `contract.py`: `DiscoveryHit{kind, title, year, creator, series,
   ids{tmdb, tvdb, isbn13, asin, hardcover, openlibrary, comicvine}, request: {service, upstream id, formats}}`.
   Discovery adapters are separate from library adapters: they never see member data, and their results are
   the same for every member.
2. **Entitlement first.** A member sees discovery results only for kinds they could request (videos group →
   Seerr; books or audiobooks group → Shelfarr; comics group → comics source), the same 404-never-403 rule as
   today.
3. **Matching**, so a title already on the server shows as *In your library* and links to Home's title page
   instead of a request:
   - Film and TV: exact. Seerr's `mediaInfo.jellyfinMediaId`, or Jellyfin `ProviderIds.Tmdb`
     (`media_ids.py` already reads upstream ids).
   - Audiobooks: ISBN or ASIN from Audiobookshelf (`Book.isbn`, `Book.asin`) against Shelfarr editions.
   - Ebooks: Calibre-Web's OPDS carries no ISBN (R1 `books.md` §3), so title plus author, normalised; mark
     it as a likely match, never certain.
   - Comics: Omnibus records ComicVine ids, Komga rarely has ISBNs; title, year and issue number, likely only.
   - The match must use only the member's own library results, so a match never reveals a title the member
     cannot see.
4. **Request status overlay** per member (part 1): *Requested by you* with the upstream stage; *Already
   requested* for someone else's request, without names.
5. **Latency.** Metadata providers are slower than the libraries and outside the 2-second budget. Keep
   library results on `/search` as they are and put discovery on a second, server-rendered step
   (`/search/beyond?q=`, or a "Search beyond your library" link). That works without JavaScript; with
   JavaScript the page script can load it inline later (UX phase).
6. **Caching and limits.** Discovery results are not member data, so one shared in-memory cache per
   normalised query (10 to 60 minutes) is acceptable; member-specific overlays are never cached across
   members. A minimum query length, a per-member query rate and a per-source circuit breaker (reuse
   `resilience.py`) protect the shared Hardcover and ComicVine quotas.
7. **No store, no index** for the first version. A persistent title graph (ids across catalogues) would help
   matching, but it is a store decision (P-4 in POST-M3-VALIDATION-PLANS) and not needed to start.

### Effort (HYPOTHESIS)

| Step | Size | Gate |
|---|---|---|
| Discovery contract, Seerr discovery adapter, fakes, merge with library results (film and TV only) | 3 to 4 days | Holding the Seerr key; a read-only live capture |
| Matching and status overlay for film and TV | 2 days | none beyond the above |
| Shelfarr discovery (after the upgrade) with ISBN/ASIN and fuzzy matching | 3 days | Shelfarr upgrade, token |
| Comics discovery source | 2 days | Choice of source and its terms |
| Request brokers (part 1) | see part 1 | first write per service |

## Recommended order

1. Owner decisions: hold the Seerr key in Home (P-2/P-3); Shelfarr or Shelfmark for members; upgrade
   Shelfarr; comics: link out now, upstream API later.
2. Seerr read path: discovery and status for film and TV, fixture-only, then a read-only live capture.
3. Seerr write path behind the confirmation page, after AVR-348.
4. Shelfarr upgrade, then its discovery and write path.
5. Comics: keep the link-out; propose the Omnibus API change upstream if the owner wants in-app comic requests.

## Open owner decisions

| # | Decision |
|---|---|
| U-1 | Avrana holds Seerr's global key (full Seerr admin), behind the broker rules above |
| U-2 | Upgrade Shelfarr from v0.1.0 and choose it (or Shelfmark) as the members' book request tool |
| U-3 | Whether member book requests need approval (Shelfarr appears to have none) |
| U-4 | Comics: link out only, or pursue an upstream Omnibus API change |
| U-5 | What a member may learn about other members' requests ("Already requested", no names, recommended) |
| U-6 | Comics discovery source and its terms (ComicVine via Shelfarr, ComicVine direct or Metron) |
