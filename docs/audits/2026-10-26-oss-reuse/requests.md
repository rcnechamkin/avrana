# R1: Requests and monitoring tools (Seerr, Shelfmark, Shelfarr, Tracearr, arrs)

Research date: 2026-10-26. Read-only. Sources: `gh api` repo metadata plus partial clones at pinned SHAs (local, not committed).
Labels: **CONFIRMED** means read in source or docs at the pinned SHA. **HYPOTHESIS** means inferred or not verified.

---

## 1. Seerr

| Field | Value |
|---|---|
| URL | https://github.com/seerr-team/seerr (default branch `develop`) |
| Lineage | **CONFIRMED.** `Fallenbagel/jellyseerr` now redirects to `seerr-team/seerr` (GitHub API returns the same repo). `sct/overseerr` is **archived**, last release v1.35.0 on 2026-02-15. `docs/migration-guide.mdx` says Overseerr and Jellyseerr instances "will automatically be migrated to Seerr" on first start. |
| Latest release | v3.5.1, 2026-10-21 |
| Commit inspected | `c167958ad6f11b0f984dbc7b5938660c017d4c79` (develop, 2026-10-26) |
| License | MIT (code). No separate asset license in the repo. Logos are in `public/` under the repo LICENSE. **HYPOTHESIS:** treat the Seerr name and logo as trademarks anyway. |
| Activity | About 13k stars, 1.1k forks, pushed today, 45 GitHub releases. Very active. |
| Maturity | High. This is the de facto standard request manager for the Jellyfin and Plex ecosystem. |
| Stack | TypeScript, Next.js frontend, Express API, TypeORM with SQLite or Postgres. Docker image `seerr/seerr`. |
| OpenAPI | **CONFIRMED.** `seerr-api.yml` at the repo root (8,325 lines). The old name was `overseerr-api.yml`. It is served as Swagger UI at `/api-docs` (`server/index.ts:238`). Requests are validated against it with express-openapi-validator. |

### Feature to endpoint map (all under `/api/v1`, CONFIRMED in `seerr-api.yml` and `server/routes/*`)

| Feature | Endpoint | Notes |
|---|---|---|
| Search (TMDB multi) | `GET /search?query=&page=&language=` | Each result carries `mediaInfo` when Seerr already knows the title. |
| Movie detail and availability | `GET /movie/{tmdbId}` | The response includes `mediaInfo{status,status4k,jellyfinMediaId,mediaUrl,requests…}`. |
| TV detail and availability | `GET /tv/{tmdbId}`, `GET /tv/{tmdbId}/season/{n}` | TV is also keyed by tmdbId. `tvdbId` is a field on Media. |
| Create request | `POST /request` body `{mediaType, mediaId(tmdb), tvdbId?, seasons?, is4k?, serverId?, profileId?, rootFolder?, userId?}` | `userId` (request on behalf of another user) requires MANAGE_USERS or MANAGE_REQUESTS (`server/entity/MediaRequest.ts:60-100`, `server/routes/request.ts:512-525`). |
| List requests | `GET /request?take&skip&filter&sort&requestedBy`, `GET /user/{id}/requests`, `GET /request/count` | Non-managers only see their own requests unless they have REQUEST_VIEW (`request.ts:152`). |
| Recently added / library | `GET /media?filter=available\|allavailable\|partial\|processing\|pending&sort=added\|modified\|mediaAdded` | This is library state, not a per-user view. It needs only an authenticated user (`routes/index.ts:174`). |
| Discover sliders | `GET /discover/movies`, `/discover/tv`, `/discover/trending`, `/discover/*/upcoming`, `/discover/watchlist` | TMDB-driven. |
| Watchlist | `POST /watchlist`, `DELETE /watchlist/{tmdbId}?mediaType=`, `GET /user/{id}/watchlist`, `GET /discover/watchlist` | **CONFIRMED.** Non-Plex (Jellyfin) users get a local Seerr watchlist (`discover.ts:955`). Another user's list needs MANAGE_REQUESTS or WATCHLIST_VIEW (`user/index.ts:941`). |
| Quotas | `GET /user/{id}/quota` | Per-user `movieQuotaLimit/Days` and `tvQuotaLimit/Days` (`entity/User.ts:128-137`). Global defaults exist. |
| Permissions | `GET/POST /user/{id}/settings/permissions` | Bitmask in `server/lib/permissions.ts`: REQUEST=32, AUTO_APPROVE=128, REQUEST_MOVIE/TV, REQUEST_4K*, AUTO_APPROVE_*, RECENT_VIEW, WATCHLIST_VIEW, and so on. ADMIN=2 short-circuits every check. |
| Jellyfin user link | `GET /user/jellyfin/{jellyfinUserId}` | **CONFIRMED** (`user/index.ts:421`). It normalizes the GUID and maps a Jellyfin user id to a Seerr user. Full fields are returned only to MANAGE_USERS. The User entity has `jellyfinUserId` and `jellyfinUsername`. |
| User import | `POST /user/import-from-jellyfin` | Admin (MANAGE_USERS). |
| Per-user watch stats | `GET /user/{id}/watch_data` | **Tautulli (Plex) only.** Returns 404 if Tautulli is not configured (`user/index.ts:837-850`). There is nothing for Jellyfin. |
| Ratings, recommendations, similar | `/movie/{id}/recommendations`, `/similar`, `/ratingscombined`, `/tv/{id}/…` | TMDB recommendations, not personalised. |
| Deep links (UI) | `/movie/{tmdbId}`, `/tv/{tmdbId}` | **CONFIRMED** from Next pages `src/pages/movie/[movieId]` and `src/pages/tv/[tvId]`. |
| Jellyfin deep link | `mediaInfo.mediaUrl` | Built as `${jellyfinHost}/web/index.html#!/details?id=…&serverId=…` (`entity/Media.ts:302`). |

### MediaStatus codes (CONFIRMED in `server/constants/media.ts`)

`MediaStatus`: UNKNOWN=1, PENDING=2, PROCESSING=3, PARTIALLY_AVAILABLE=4, AVAILABLE=5, BLOCKLISTED=6, DELETED=7.
`MediaRequestStatus`: PENDING=1, APPROVED=2, DECLINED=3, FAILED=4, COMPLETED=5. `MediaType`: `movie` and `tv` only.

### Books and music support

**CONFIRMED:** no. `MediaType` contains only movie and tv, and the README lists only Sonarr and Radarr integration.

### Authentication: exact semantics (CONFIRMED in `server/middleware/auth.ts`)

```ts
if (req.header('X-API-Key') === settings.main.apiKey) {
  let userId = 1; // original administrator
  if (req.header('X-API-User')) userId = Number(req.header('X-API-User'));
  user = await userRepository.findOne({ where: { id: userId } });
} else if (req.session?.userId) { … }
```

- **API key (`X-Api-Key`).** There is one global key in settings, regenerated at `POST /settings/main/regenerate`. It has no scopes. Without `X-API-User`, the request runs as **user id 1, the original admin**.
- **`X-API-User: <seerrUserId>`.** Only takes effect together with a valid API key. The request then runs with **that user's own permissions, quotas and attribution**, because `isAuthenticated` checks `req.user.hasPermission`. Nothing restricts which ids can be impersonated: any holder of the key can act as **any** user, including id 1 or any other ADMIN. The header takes the numeric Seerr user id, not a Jellyfin id. Resolve that first with `GET /user/jellyfin/{jellyfinUserId}`.
- **Session cookie (`connect.sid`).** Obtained with `POST /auth/jellyfin {username,password}` (or plex, local, or Jellyfin QuickConnect). This needs the member's **Jellyfin password**. On first login the user is created with `settings.main.defaultPermissions` (`routes/auth.ts:198,489,806`). The spec text says "without any permissions", but the code applies the default permissions. CSRF protection is optional (`settings.network.csrfProtection`).
- **No other options.** There is no OIDC, no trusted-header proxy auth, and no per-user API tokens. **CONFIRMED** by grep over `server/`: no oidc, openid, or Remote-User.

**Security implications for a server-side aggregator (Avrana Home):**
1. With API key plus `X-API-User`, Avrana becomes the trust boundary. Seerr enforces each member's permissions and quotas correctly, but only if Avrana maps the logged-in member to the right Seerr id on the server. It must never accept that id from the client. The key is equivalent to full admin over Seerr, its settings, and the Radarr and Sonarr API keys stored there, so it must stay server-side only. A request or SSRF bug in Avrana that lets a member pick the id, or omit the header, escalates to admin.
2. Mitigations:
   - Build a hard-coded allowlist of `{avranaMember → seerrUserId}` and refuse any id whose Seerr permissions include ADMIN, MANAGE_*, or a value of 2.
   - Always send `X-API-User` so the call never falls back to id 1.
   - Proxy only a fixed allowlist of read and request endpoints, never `/settings/*`, `/user/*/settings/permissions`, or `/request/{id}/{status}`.
   - Keep Seerr LAN-only, and rotate the key if it leaks.
3. The session-cookie route would mean Avrana handles member Jellyfin passwords and per-member cookie jars. **Not recommended.** It is a worse credential surface than (1).
4. Simplest of all: deep-link members into Seerr's own UI (`/movie/{tmdbId}`), where they log in with Jellyfin themselves. Avrana then shows availability only (read with the API key, no `X-API-User` needed for non-sensitive reads, though passing a low-privilege user id is safer).

---

## 2. Shelfmark

| Field | Value |
|---|---|
| URL | https://github.com/calibrain/shelfmark |
| Latest release | v1.5.1, 2026-10-23. **Avrana runs v1.3.6** (released 2026-08-13, tag commit `0e8608c427cf8a584174005173a274b7f563dbac`). |
| Commits inspected | `0e8608c` (v1.3.6) and HEAD `72b094db7a01a40ab0f8bbf65ed92649cd467d51` (2026-10-26) |
| License | MIT ("Copyright (c) 2024 CaliBrain"). No separate asset license found. |
| Activity | About 4.1k stars, 49 releases since 2025-08. The v1.3.6 README says "stable … but is not under active maintenance". The HEAD README says "maintained on a best-effort basis … no roadmap for new features". |
| Stack | Python (Flask with websockets) plus a JS frontend. Single Docker container on port 8084. Optional Tor and WireGuard egress. |
| What it does | **CONFIRMED.** A "Book Search & Request Tool" for ebooks and audiobooks. Metadata comes from Hardcover, Open Library, and Google Books. Release sources are in `shelfmark/release_sources/`: `direct_download.py` ("Anna's Archive/Libgen with fallback cascade", also Z-Library and Welib, with Cloudflare bypass in `shelfmark/bypass/`), plus `prowlarr`, `newznab`, `irc`, and `audiobookbay`. It delivers into CWA, Calibre-Web, Grimmory, or Audiobookshelf ingest folders. |

| Feature | Endpoint (v1.3.6) | Evidence |
|---|---|---|
| Metadata search | `GET /api/metadata/search`, `GET /api/metadata/book/<provider>/<id>` | `shelfmark/main.py:2460,2671` |
| Release search | `GET /api/releases` | `main.py:2794` |
| Direct download | `POST /api/releases/download` | `main.py:1028` |
| Requests (user) | `POST /api/requests`, `POST /api/requests/batch`, `GET /api/requests`, `DELETE /api/requests/<id>` | `shelfmark/core/request_routes.py:639-850` |
| Requests (admin) | `GET /api/admin/requests`, `POST …/<id>/fulfil`, `POST …/<id>/reject` | `request_routes.py:904-1008` |
| Queue and status | `GET /api/status`, `/api/downloads/active`, `/api/queue/order` | `main.py` |
| Deep link | `/?q=…&author=…&isbn=…&content_type=ebook\|audiobook` | `docs/url-search-parameters.md` |
| Auth | Session login `POST /api/auth/login`. Modes: none, builtin, OIDC, **proxy** (header `X-Auth-User` by default, or `Remote-User`, with auto-provisioning and optional admin groups), and CWA DB. | `core/auth_modes.py`, `main.py:661-707`, `docs/users-and-requests.md` |
| API key | **None found.** There is no token or API-key auth in `main.py` or `core/`. | grep |

- **Request flow: CONFIRMED.** Per content type you choose a policy mode: Download, Request Release, Request Book, or Blocked. There are per-source rules, per-user overrides, and a maximum number of pending requests per user. Admins fulfil or reject. See `docs/users-and-requests.md`.
- **Integration fit.** Proxy auth would let a trusted Avrana reverse proxy inject the member's username, but only if Shelfmark is unreachable except through that proxy. Otherwise the header can be spoofed.
- **Acquisition sources (neutral note).** The default "direct" sources (Anna's Archive, Libgen, Z-Library, Welib) are shadow libraries. Much of what they host is distributed without rightsholder permission. Using them may infringe copyright depending on jurisdiction and title, and Shelfmark ships code to bypass Cloudflare protection for them. Usenet, torrent, and IRC sources carry similar content-dependent concerns.
- **Recommendation for Avrana:** do not surface these sources as a first-class product feature. If members request books, a link-out at most, with the admin-approval mode (Request Book) enforced in Shelfmark. This is a policy decision for the owner.

---

## 3. Shelfarr

| Field | Value |
|---|---|
| URL | https://github.com/Pedro-Revez-Silva/shelfarr. The site is shelfarr.org. |
| Latest release | v2026.10.26.1, 2026-10-26. Releases now use calendar versions; semver went up to v0.39.7. |
| Commits inspected | HEAD `436642c785420a2b88abce8b03884737e1010c91` (2026-10-24) and tag v0.1.0 at `f69538ab62add287759b5116ef544df3925f1a00` (2026-02-15) |
| License | GPL-3.0. No separate asset license found. |
| Activity | About 380 stars. Very active, with weekly releases. Created 2025-12-23. |
| Stack | Ruby on Rails, Docker on ghcr.io. Optional Libation companion. |
| What it is | **CONFIRMED.** "Think Jellyseerr, but for books." Users request ebooks and audiobooks. It searches Prowlarr, Jackett, or Newznab indexers plus direct sources (Anna's Archive, Z-Library, LibriVox), downloads, renames, and delivers to Audiobookshelf, BookOrbit, or Grimmory. It has TOTP and OIDC, notifications, beta third-party DRM-free store offers, and beta Audible backup. |

**Version caveat.** The `VERSION` file at HEAD still reads `0.1.0`. It has not changed since 2026-02-15, when the update checker moved to Release Please (commit `3de5f47`). **HYPOTHESIS:** "Avrana runs 0.1.0" may be the stale in-app VERSION file, not the real image version. Check the container image tag or digest. If the image really is v0.1.0 (Feb 2026), it has **no API**: `config/routes.rb` at v0.1.0 has no `namespace :api`. The API was added in #129 on 2026-02-16 and first shipped in v0.1.4.

| Feature | Endpoint (HEAD, `docs/api.md`, `config/routes.rb:87-98`) |
|---|---|
| Search | `GET /api/v1/search?q=&limit=`, which returns `work_id` |
| Requests | `GET/POST /api/v1/requests`, `GET/DELETE /api/v1/requests/:id`, `GET …/search_results`, `POST …/grab`, `POST …/blocklist_and_next`, `POST …/retry` |
| Users | `POST /api/v1/users` |
| Auth | `Authorization: Bearer shf_…`. Prefer **per-user scoped tokens**: `search:read`, `requests:read`, `requests:write`, `requests:admin`, `users:write`. There is also a legacy global token that acts as admin. Admin tokens can pass `username` or `user_id` to create a request on behalf of a user. |
| Request statuses | pending, searching, awaiting_purchase, not_found, downloading, processing, completed, failed |

**Maturity.** It moves fast and has had more than 40 releases in about 10 months. The API is documented and has a better auth model than Seerr's (scoped per-user tokens), but it is young. The acquisition-source concerns are the same as Shelfmark's.

---

## 4. Tracearr

| Field | Value |
|---|---|
| URL | https://github.com/connorgallopo/Tracearr. Docs are at docs.tracearr.com. |
| Latest release | v3.1.1, 2026-10-23 |
| Commit inspected | `9c625a9c112f772d57e3388ae0fd8edbdcaa0804` (2026-10-26) |
| License | **AGPL-3.0** (code). No separate asset license found. |
| Activity | About 2.75k stars, created 2025-11, more than 100 releases, very active. |
| Stack | TypeScript monorepo with a Fastify server, React web app, Postgres, Redis, Drizzle. Uses a Jellyfin/Emby SSE plugin. |
| What it is | **CONFIRMED** (README). Multi-server stream monitoring for Plex, Jellyfin, and Emby. It records session history with IP geolocation (ASN, postal code), detects account sharing (impossible travel, simultaneous locations), and keeps trust scores. It also has automations that can stop streams, newsletters, a cross-server media catalog, Seerr request analytics (`routes/requests.ts`, `services/requests/seerrClient.ts`), and imports from Tautulli and Jellystat. There is a member login with library views that are deliberately scoped (`routes/memberLibrary.security.test.ts`). |

| Feature | Public API endpoint (v2, `apps/server/src/routes/publicV2/*`) |
|---|---|
| History | `GET /api/v2/history` (filter by `user_id`), `GET /users/:id/history` |
| Per-user stats | `GET /users`, `GET /users/:id`, `GET /users/:id/stats` |
| Watched media | `GET /watched-media` |
| Media | `GET /media/:ref`, `/media/:ref/children`, `/stats`, `/watchers`, `/history` |
| Also | streams, servers, libraries, violations, events. v1 also exists (`routes/public.ts`). Docs are at `/api-docs` (Scalar). |
| Auth | **CONFIRMED** (`plugins/auth.ts:317-350`). `Authorization: Bearer trr_pub_…`. The key must belong to the **owner** role. One global key reads **all** users' data. The token is stored and compared in plaintext (`db/schema.ts:184`, `eq(users.apiToken, token)`). |

**Fit for "Continue" or recommendations.** It is technically possible: there is per-user history and stats keyed by Tracearr user, mapped to Jellyfin server users. But:
- The only API credential is owner-level and global. Avrana would hold a key that exposes every member's viewing history **and IP geolocation**.
- Its purpose is surveillance and enforcement (account-sharing detection, trust scores, stream killing), which conflicts with a friendly family hub.
- "Continue watching" is better sourced from Jellyfin itself (`/Users/{id}/Items/Resume` with a per-user token) and from Audiobookshelf and Komga progress APIs, which are already scoped per member. **HYPOTHESIS:** this is the R-track recommendation, not verified here.
- The AGPL license only matters if Avrana copies code, not if it calls the HTTP API.

---

## 5. Radarr and Sonarr v3: availability lookup

| | Radarr | Sonarr |
|---|---|---|
| Latest | v6.4.4.10685 (2026-09-16), develop `e77fd33e` | v4.0.20.3014 (2026-09-16), main `bc54afbd` |
| License | GPL-3.0 | GPL-3.0 |
| Lookup | `GET /api/v3/movie?tmdbId=X` (`src/Radarr.Api.V3/Movies/MovieController.cs:118-128`). Returns `hasFile`, `monitored`, `status`, `movieFile`. | `GET /api/v3/series?tvdbId=X` (`src/Sonarr.Api.V3/Series/SeriesController.cs:110-117`). Returns `statistics.episodeFileCount`, `percentOfEpisodes`, and per-season stats. |
| Auth | `X-Api-Key`. One global, full-admin key per instance. | same |

**Recommendation: ask Seerr, not the arrs.**
- Seerr already merges arr state with the Jellyfin library scan into `mediaInfo.status` (PENDING, PROCESSING, PARTIALLY_AVAILABLE, AVAILABLE). It keys everything by tmdbId, including TV, and it knows request state per user. That is what a member-facing "Requested / Downloading / Available" badge needs.
- Querying the arrs directly means handing Avrana more admin keys. The arrs know about files, not what Jellyfin can play, and Sonarr needs a tvdbId while TMDB-based search returns tmdbIds.
- Use the arrs only as an owner-side diagnostic. **HYPOTHESIS:** good enough for Avrana's scale.

---

## 6. Gap: requests for books, audiobooks and comics

| Project | Status (gh API) | Request flow? | Verdict |
|---|---|---|---|
| Readarr | **Archived** 2025-06-27 (GPL-3.0) | No (arr, single admin) | Dead |
| pennydreadful/bookshelf (Readarr fork) | Active (pushed 2026-09), GPL-3.0, about 800 stars, no GH releases | No | Readarr replacement, not a request UI |
| LazyLibrarian | GitHub mirror stale (2022). Primary is on GitLab, activity **UNVERIFIED**. | No multi-user requests (**HYPOTHESIS**) | n/a |
| Kapowarr | Active, V1.3.2 (2026-09-14), GPL-3.0 | No | Comic arr only |
| Mylar3 (Avrana runs it) | v0.8.3 (2025-08-17), pushed 2026-03 | No user-request UI (**HYPOTHESIS**) | Keep as backend |
| Omnibus (Avrana runs it) | Not researched | n/a | n/a |
| Shelfarr | Active, GPL-3.0 | **Yes.** Per-user, with scoped API tokens. | Closest to "Seerr for books and audiobooks" |
| Shelfmark | Best-effort maintenance, MIT | **Yes.** Policy modes plus admin approval. | Mature UI, no API token |

**Comics:** no open-source multi-user request tool for comics was found. **HYPOTHESIS:** the gap is real. The cheapest option is an Avrana "ask the owner" form (a note or notification) that the owner fulfils in Mylar3, Kapowarr, or Omnibus.

---

## 7. Verdicts

| Project | Verdict | Why |
|---|---|---|
| Seerr | **KEEP/RUN + INTEGRATE (read) + deep-link (write)** | Read availability with `GET /movie\|tv/{tmdbId}` server-side. Send members to Seerr's own UI to request (`/movie/{tmdbId}`), or use `POST /request` with `X-API-User` only behind a strict server-side mapping that refuses admin ids. |
| Shelfmark | **KEEP/RUN (owner tool), REJECT as a member-facing integration** | No API key. Proxy-header auth is spoofable unless isolated. Default sources raise legal concerns. Link-out at most. |
| Shelfarr | **STUDY → possible INTEGRATE** | Its scoped per-user token API is the right model. Verify the real deployed version first: v0.1.0 has no API. |
| Tracearr | **REJECT** for Avrana Home (fine as a separate owner-only admin tool) | Owner-only global key exposes all members' history and geolocation. Its surveillance purpose does not fit a member hub. AGPL. |
| Radarr/Sonarr | **Do not integrate directly** | Use Seerr's mediaInfo instead. |
| Readarr | REJECT | Archived. |
| Kapowarr / Mylar3 | KEEP as backends | No request flow. Cover comics with an Avrana "ask the owner" form. |
