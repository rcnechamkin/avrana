# Avrana Media: social reuse, identifiers, federation (r1)

Researched 2026-10-26. Read-only. Evidence: `gh api` on the upstream repos at the SHAs below, plus the official pages listed. "UNVERIFIED" marks claims I could not confirm from a primary source.

---

## Part A: social candidates

### A1. NeoDB

| Field | Finding |
|---|---|
| URL | https://github.com/neodb-social/neodb (docs: https://neodb.net, flagship https://neodb.social) |
| Latest release | `0.19.9.1`, published 2026-10-22 |
| SHA inspected | `e7020d2f2380f39d89b1d904a6679f33505d3ed4` (main, 2026-10-26) |
| License | AGPL-3.0 (LICENSE file). Assets: `docs/assets/logo.svg` and favicons sit in the tree with no separate asset license found, so treat them as NeoDB branding and don't reuse them. **AGPL s.13:** if you modify NeoDB and members use it over the network, you must offer them the modified source. That's easy (publish a fork), but it is a real obligation. Running it unmodified has no extra burden. |
| Stack | Python >=3.14,<3.15, Django 5.2, django-ninja. Takahē is now **vendored in-tree** (`takahe/` next to `neodb/`), not a separate repo. |
| Ops cost (compose.yml) | **Two PostgreSQL databases** (`neodb-db`, `takahe-db`), Redis (cache + RQ queue), Typesense (search), `neodb-web` (gunicorn, 8 workers default), `neodb-web-api` (4 workers), `neodb-worker` + `neodb-worker-extra` (rqworker-pool, 4 each: mastodon fetch ap crawl import export cron webhook), `takahe-web` (8 workers), `takahe-streaming` (uvicorn), `takahe-stator`, nginx, plus a migration job. About 11 containers. Worker counts can be tuned down by env var, but it is a heavy stack for about 15 users and a Pi. RAM figures: UNVERIFIED (install.md gives no hardware guidance). |
| API | NinjaAPI mounted at `/api/` with OAuth bearer auth (`read` / `write` scopes). Swagger at `/developer/`. A **subset of the Mastodon API** (from Takahē) is reachable with the same token. App registration is Mastodon-style: `POST /api/v1/apps`, then `/oauth/authorize`, then `/oauth/token`. |
| Catalog lookup by external ID | `GET /api/catalog/fetch?url=<external URL>` (auth=None). Returns 302 with the item's API URL if the item is cataloged, 202 if a fetch is queued (poll again after 15 s or more; some sites take about 90 s), 422 for an unsupported site, 429 when rate-limited. There is **no lookup by bare ID**: you build the provider URL (e.g. `https://www.imdb.com/title/tt…/`). Also: `GET /api/catalog/search`, `/api/{book,movie,tv,tv/season,…}/{uuid}`, `/api/book/{uuid}/sibling/`. Site adapters in `neodb/catalog/sites/` cover tmdb, imdb, tvdb, goodreads, openlibrary, google_books, musicbrainz, discogs, igdb, steam, bgg, wikidata, worldcat, anilist, myanimelist, spotify, bandcamp and others. `IdType` includes `imdb`, `tmdb_movie/tv/tvseason/tvepisode`, `isbn` (13), `isbn10`, `asin`, `goodreads`, `goodreads_work`, `openlibrary`, `wikidata`, `musicbrainz_release(group)`, `oclc`, `gtin`, `issn`. The book model separates `Edition` (isbn/asin primary lookup) from `Work` (goodreads_work). **Privacy note:** `fetch` makes the NeoDB server scrape or call third-party sites, and the downloader can use paid scraping proxies. |
| Marks / reviews / collections | Shelf (marks): `GET/POST/DELETE /api/me/shelf/item/{item_uuid}`, `GET /api/me/shelf/{type}`, plus progress and logs endpoints. Reviews: `GET /api/me/review/`, `GET/POST/DELETE /api/me/review/item/{item_uuid}`, `GET /api/review/{uuid}`. Collections: full CRUD under `/api/me/collection/…`, item add/reorder/remove, public `/api/collection/{uuid}`, `/api/item/{uuid}/collection/`. Also notes, tags, posts, user webhook (`/api/me/webhook`). The latest release adds a recommendation API. |
| ActivityPub | Yes, S2S via the vendored Takahē: WebFinger, HTTP Signatures (draft-cavage), NodeInfo (`protocols: ["activitypub","neodb"]`). A NeoDB post is a `Note` (or an `Article` for reviews) with extensions: `relatedWith[]` holding `Status` / `Rating` (1-10) / `Comment` / `Review` (markdown) / `Note` / `Shelf`, each with `withRegardTo` pointing at the item URL, and `tag[]` carrying item refs typed `Edition`, `Movie`, `TVShow`, `TVSeason`, `TVEpisode`, `Album`, `Game`, `Podcast`, etc. Lists federate as `type: "Shelf"`, with items as an `OrderedCollection`. Also does ATProto/Bluesky crossposting. |
| Privacy | `VisibilityType`: Public(0), Followers Only(1), "Mentioned Only"(2, labelled Private). Site settings: `NEODB_INVITE_ONLY`, `NEODB_ENABLE_LOCAL_ONLY` (local-only posting), `NEODB_DISABLE_DEFAULT_RELAY`, `NEODB_DISCOVER_SHOW_LOCAL_ONLY`, `NEODB_SEARCH_PEERS`. Whether NeoDB can be fully de-federated is UNVERIFIED; local-only plus no relay looks close. |
| Moderation | From Takahē: reports, blocks, domain blocks, invites, announcements, admin views (`takahe/users/models/{report,block,domain,invite}.py`). Basic, Mastodon-ish. |
| SSO / OIDC | **No OIDC.** Login types are `mastodon`, `email` (verification code, no passwords), `bluesky`, `threads` (docs/accounts.md, settings). The only "openid" match in the tree is a Steam OpenID test. **Authentik cannot be the IdP** without patching NeoDB. Forward-auth in front of it would gate access but would not map identities. |
| Export / delete | Self-service CSV, NDJSON and WordPress exports (`users/views/data.py`). Importers: Goodreads, Letterboxd, Trakt, StoryGraph, Steam, Hardcover, NDJSON and others. Self-service `clear_data` in `users/views/account.py`. Admin `neodb-manage user --delete`. |

### A2. "Floppy": identified, with low ambiguity

- **Identification:** `dannyvfilms/Floppy`, described as a "Self-hosted all-in-one media tracker and Trakt alternative for movies, TV, anime, books, games, music, and podcasts." Evidence: it's a GitHub fork of `FuzzyGrim/Yamtrack` (README: "Floppy started as a fork of Yamtrack"); third-party clients call it "the self-hosted **Floppy** media tracker" (`catadoxy/disketarr`, `nerdspar/seek`); and Unraid, ElfHosted and AlternativeTo list it. I found **no** federated forum or ActivityPub app named Floppy (web plus GitHub search), so this is very likely the intended project. **It is not a social or federated app.**
- URL https://github.com/dannyvfilms/Floppy. Latest release `v26.10.22` (2026-10-23). SHA inspected `52c17cdbfa1d42b215013102bab47e78d05a3a39` (default branch `latest`, 2026-10-26). About 920 stars.
- License: AGPL-3.0 (inherited from Yamtrack). Assets include Floppy logos and **third-party brand logos** (imdb, letterboxd, goodreads, komga, audiobookshelf and others under `src/static/img/`). Those are trademarks, so don't copy them.
- Stack: Python/Django, django-allauth (templates present), Celery with Redis required, SQLite by default or PostgreSQL. REST API at `/api/v1` with scoped app tokens (`lists:read`, `user:read`, `watchlist:read/write`…), plus an MCP server. The README mentions multi-user accounts and **OIDC sign-in** (via allauth; would work with Authentik, UNVERIFIED in practice).
- Relevant integrations (`src/integrations/imports/`): **audiobookshelf, komga, kavita, jellyfin_playback_reporting, plex**, sonarr, radarr, koreader, goodreads, trakt, imdb, storygraph, hardcover, mal, anilist, and more, plus Jellyfin/Plex/Emby webhooks. `external_references.py` and `title_matching.py` hold cross-ID matching logic.
- Social: per-user tracking. Custom lists have a public slug (migration `0009_add_customlist_public_slug`). No friends feed, no federation found.
- **Overlap warning:** Floppy ingests *playback history* from Jellyfin/ABS/Komga. That is exactly the data Avrana says must never leave the hub. If anyone ran it, keep it on the LAN with history ingestion disabled.

### A3. NodeBB

| Field | Finding |
|---|---|
| URL | https://github.com/NodeBB/NodeBB |
| Latest release | `v4.16.4`, 2026-10-23 |
| SHA inspected | `ce62dcd5a11bcf1274fe3653622ec08cc3c1a248` (master, 2026-10-25) |
| License | **GPL-3.0, not AGPL** (README; commercial sublicense available from NodeBB Inc.), so it carries no network-use clause. Themes and plugins are separate npm packages with their own licenses (e.g. `nodebb-plugin-sso-oauth2-multiple` is BSD-2-Clause). |
| Stack / ops | Node.js >=22. One of Redis >=7.2, MongoDB >=5, or PostgreSQL (README). Redis is required for clustering. A single process is fine at 15 users; it's lighter than NeoDB. |
| API | Read/write REST API (`/api/v3`, token-based), websockets. |
| ActivityPub | Since **v4.0.0** (docs.nodebb.org/activitypub). On by default for new installs, off on upgrades. Global toggle in ACP > Settings > Federation; per-category federation through privileges granted to the "fediverse" pseudo-user. Implementation in `src/activitypub/` (actors, inbox, out, signatures, relays, blocklists, feps…). |
| Privacy | Category privileges (groups, guests, fediverse pseudo-user). Nothing title-linked: it's a forum, not a catalog. Spoiler support relies on markdown/plugins (UNVERIFIED for a built-in spoiler tag). |
| Moderation | Mature: flags (`src/flags.js`), post queue (`src/posts/queue.js`), bans, per-category mods, `nodebb-plugin-spam-be-gone`, AP instance blocklists. |
| SSO / OIDC | Official `NodeBB/nodebb-plugin-sso-oauth2-multiple` (BSD-2, pushed 2026-10-18) configures generic OAuth2 endpoints, so **Authentik works as an OAuth2/OIDC provider** (discovery and PKCE support UNVERIFIED in its README). |
| Export / delete | `src/user/jobs/export-{profile,posts,uploads}.js`, `src/user/delete.js`. |
| Fit | Good for spoiler-safe discussion threads, but has no ratings or catalog concept. Linking topics to titles would need a custom plugin or a per-title topic created by Avrana. |

### A4. Run NeoDB isolated vs build a thin Avrana-native module

| | (1) NeoDB as optional companion | (2) Thin native module |
|---|---|---|
| Effort | Deploy: about 1-2 days. Real integration (OAuth per member, mapping Avrana titles to NeoDB item UUIDs via `catalog/fetch`, deep links, cross-display of ratings): about 1-2 weeks. Identity mapping is painful because there's **no OIDC**, so members get a second account (email-code login). | About 1-2 weeks for ratings (1-10 or 5-star), markdown reviews with spoiler flag/blur, shared lists, friends' recommendations, visibility (private / friends / members), and per-title threaded comments. Postgres/SQLite tables keyed to Avrana's canonical work ID. |
| Risk | Heavy footprint (2 PG + Redis + Typesense + ~8 app processes) on a homelab. Catalog duplication (NeoDB keeps its own item catalog and scrapes external sites). Federation-first defaults to audit. AGPL obligation if patched. A separate UI breaks the PWA experience. | Feature creep. You own moderation (tiny at 15 trusted members). No federation unless built later. |
| Upgrade burden | Fast-moving project (multiple releases a month, Python 3.14 pin, vendored Takahē). Two DB migrations per upgrade. | Only Avrana's own migrations. |
| Privacy | External fetches, AP fanout, Bluesky crosspost features all need disabling and verifying. | Nothing leaves the hub by default. |

**Recommendation: (2) thin native module.** STUDY NeoDB's data model (Edition vs Work, shelf statuses complete/progress/wishlist/dropped, Rating 1-10, Review markdown, Collection, `relatedWith`/`withRegardTo` wire format) and mirror it, so that later federation can interoperate with NeoDB peers. Keep "run NeoDB" as an optional sidecar only if members actually want public Fediverse presence, and then link out instead of integrating deeply.

---

## Part B: identifiers

| ID | Level | Terms / evidence | Use in Avrana |
|---|---|---|---|
| **TMDB** movie / tv / season / episode IDs | Work (movie, series); season and episode are sub-works | TMDB API Terms: licensed for **non-commercial** use, and TMDB decides what counts as commercial. Requires the TMDB logo (less prominent than yours) plus the disclaimer that the product "uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB". Cached content max **6 months**, delete on termination. No AI training. The terms don't address storing IDs. | Key, since Jellyfin already stores it (`MetadataProvider.Tmdb`). Store the ID only. If Avrana itself calls TMDB, show the attribution. |
| **TVDB** series / episode IDs | Work | v4 API: commercial license or a "user-supported key" where each end user pays about $12/yr for a PIN (TVDB support FAQ / GitHub, 2020-21). Third-party claim of a free Developer tier: UNVERIFIED. Attribution with a link is required for end users viewing metadata. | Read the ID from Jellyfin (`Tvdb`). Don't call the API. |
| **IMDb** `tt…` (tconst), `nm…` | Work (title) | The IDs are de facto universal keys, usable as opaque strings. **Datasets**: "available … for personal and non-commercial use", refreshed daily (data.imdb.com). No public API without a commercial agreement. | Key from Jellyfin (`Imdb`). Never scrape. A private, non-commercial hub using dataset lookups is arguably in scope, but don't redistribute. |
| **ISBN-10/13** | **Edition / product form**. ISBN agency: "each different product form (e.g. paperback, EPUB, .pdf) should be identified separately". ISBN-13 only since 2007-01-01. | No license issue (it's a number). | Edition-level only. Normalize ISBN-10 to ISBN-13. Never treat as a work key. Komga `BookMetadata.isbn`, ABS `Book.isbn`, Calibre identifiers. |
| **ASIN** | **Edition and marketplace-specific** (Amazon product; Audible ASINs differ per store/region; for books often equals the ISBN-10) | Amazon proprietary. Product Advertising API terms are restrictive (not reviewed). | ABS `Book.asin`. Edition-level, opaque, store with a region qualifier if known. |
| **Open Library** `OL…W` / `OL…M` / `OL…A` | W = work, M = edition (manifestation), A = author (OL convention; the API page shows `OL15626917W.json`) | Licensing page: the Internet Archive "does not assert any new copyright"; secondary sources disagree (CC0 vs CC-BY 4.0), so treat the exact license as UNVERIFIED. API: 1 req/s anonymous, 3 req/s with an identifying User-Agent; use the monthly dumps for bulk. | Best free **work** key for books. Map ISBN to an OL edition, then to its OL work. |
| **MusicBrainz** MBIDs | Release group = work-ish album; release = edition; recording / track; artist | Core data **CC0**; supplementary data CC BY-NC-SA 3.0. API about 1 req/s per IP, meaningful User-Agent **required**. | Jellyfin stores `MusicBrainzReleaseGroup/Album/Artist/Track/Recording`. Use the release-group as the work key. |
| **ComicVine** volume / issue IDs | Volume = series; issue = issue (edition-ish) | "strictly for non-commercial use only"; 200 requests per resource per hour; link back; unique key per site. | Optional. Komga `links` may carry it. Don't call. |
| **Wikidata QIDs** | Usually **work** (film, novel, series); separate items exist for editions in WikiProject Books | Main-namespace data **CC0**. | Cross-walk hub: a QID carries P345 (IMDb), P4947 (TMDB movie), P4983 (TMDB TV), P4835 (TVDB), P648 (OL), P436 (MB release group), P212 (ISBN-13), P5905 (ComicVine)… (property numbers from memory, verify before coding). NeoDB also uses Wikidata as a cross-walk (`docs/internals/wikidata.md`). |

What the upstream servers already give you, so Avrana never needs to call out:
- **Jellyfin** `ProviderIds`: Imdb, Tmdb, Tvdb, TmdbCollection, TvMaze, MusicBrainz* (verified in `MetadataProvider.cs`).
- **Audiobookshelf**: `isbn`, `asin` (verified in `server/models/Book.js`).
- **Komga**: `isbn`, `links[]` (verified in `BookMetadata.kt`).
- **Calibre-Web**: the Calibre `identifiers` table (isbn, amazon, goodreads, google…). From knowledge, UNVERIFIED here.

### Canonical-identity strategy (recommended)

1. **Internal canonical ID = an Avrana UUID per *work*** (`work_id`). It is never an external ID, because those are unstable, can collide and carry their own license terms.
2. **`work_external_id(work_id, scheme, value, level, source, confidence)`**, with `scheme` in {tmdb_movie, tmdb_tv, imdb, tvdb, ol_work, mb_release_group, wikidata, comicvine_volume, …} and `level` = work. **`edition` table** (`edition_id → work_id`) carrying ISBN-13, ASIN(+region), OL edition, MB release, Komga/ABS/Calibre/Jellyfin item IDs. Ratings, reviews and lists attach to `work_id`. Progress and "which copy" attach to the edition or upstream item.
3. **Prefer upstream-provided IDs.** Ingest only what Jellyfin/ABS/Komga/Calibre already store. No outbound API calls from the hub by default. An optional, admin-enabled "enrich" job may call OL or Wikidata (CC0, polite UA) to group editions into works.
4. **ISBN and ASIN are edition-level, always.** Two ISBNs never imply the same work unless an OL work, Wikidata or a manual merge links them.
5. **Ambiguity:** keep candidate links with `confidence` (exact-id / derived / title-match / manual) and `status` (proposed / confirmed / rejected). Allow one upstream item to be *unlinked* (a "provisional work"). Support merge/split with a redirect table (`work_alias old→new`) so reviews survive re-identification. Show "possibly the same as…" to admins instead of auto-merging on title alone. Anime and multi-season shows: the work is the series, seasons are child works (NeoDB models TVShow/TVSeason the same way).
6. For federation, publish only `work_id` URLs plus *public* external IDs (IMDb/TMDB/OL work/Wikidata) so peers can match without seeing inventories.

---

## Part C: ActivityPub feasibility

**Minimum for opt-in federation of reviews and recommendations:**
- WebFinger (`/.well-known/webfinger`) and NodeInfo.
- An **Actor** per opted-in member (`Person` with `inbox`, `outbox`, `followers`, `publicKey`). Possibly an instance `Application` actor for signed fetches.
- **Inbox** POST handling `Follow` / `Accept` / `Reject` / `Undo` / `Create` / `Update` / `Delete` / `Like`, with a delivery queue and retries for the outbox.
- **HTTP Signatures**: draft-cavage-12 is what Mastodon, Takahē and NeoDB speak; RFC 9421 adoption is partial. Verify `Digest` and the date window, cache remote keys, and use authorized fetch for non-public objects.
- **Objects**: `Note` for short recs and comments, `Article` for reviews (name, content HTML, `source` markdown, `summary` as the content-warning/spoiler field, which Mastodon renders as a CW). For NeoDB interop, add `relatedWith: [{type: "Review" | "Rating" | "Status", withRegardTo: <item URL>, …}]` and `tag: [{type: "Movie" | "Edition" | "TVShow"…, href}]` (see Part A1).
- Lists as `OrderedCollection` (NeoDB uses `type: "Shelf"`).
- Libraries: Python options include bovine / apkit / Takahē code (AGPL; study only). UNVERIFIED which is maintained enough. Realistic effort for a minimal, secure S2S implementation: weeks, not days.

**Privacy pitfalls:**
- **Followers-only is not enforced crypto-wise.** Once delivered, the remote server decides who sees it. Buggy or malicious software can leak it, and a follower's server admin can read it. Boosts of non-public posts depend on remote behaviour.
- **Deletes are best-effort.** `Delete`/`Tombstone` is a request that remote caches, relays, search indexers and archives may ignore. Edits (`Update`) behave the same way.
- Addressing errors (`to`/`cc` with `as:Public` or the followers collection) cause leaks. Mention-only posts leak through mentions in replies.
- Profile and outbox enumeration: an unauthenticated outbox exposes history. Require authorized fetch and paginate only public items.
- Activity metadata (timestamps of marks, "currently watching") is behavioural data. **Never federate shelf progress or watch status by default**, and never playback, inventory, or edition/file details. NeoDB federates `Status` (progress/complete) by default, which is exactly the kind of thing Avrana should not do.
- Relays and fanout: disable relays. Instance-level allowlist federation (only peer Avrana instances) is the safe default.
- Cover images: link to the external canonical page, never to the hub's media or cover URLs, because those reveal the instance's library.

**Verdict:** feasible but **defer**. Design the data model now (canonical work URLs, visibility enum {private, friends, members, federated}, per-item `federate` flag, public external IDs on works). Implement federation later as an allowlisted, Avrana-to-Avrana, reviews-and-recommendations-only feature with a NeoDB-compatible wire shape.

---

## Disposition

| Project | Verdict | Why |
|---|---|---|
| NeoDB | **STUDY** (optional RUN as an isolated sidecar only if members want public Fedi presence) | Best model and AP wire format for title-linked reviews. Too heavy, no OIDC, and too federation-forward to integrate. |
| Floppy (dannyvfilms/Floppy, a Yamtrack fork) | **STUDY** (REJECT as a dependency) | Not social or federated. Its ABS/Komga/Jellyfin importers and `external_references` / `title_matching` code are useful references for ID matching (AGPL, so study, don't copy). It ingests playback history, which conflicts with Avrana's privacy stance. |
| NodeBB | **REJECT** for now (STUDY if discussion outgrows comments) | GPL-3, AP since v4, OIDC via plugin, strong moderation. But it's a full forum with no title/catalog link, and a separate stack. |
| Thin Avrana-native social module | **BUILD (ADAPT NeoDB's schema ideas)** | Fits a 15-member hub, keeps data local, fewer upgrades. |
| Wikidata / OL / MusicBrainz | **INTEGRATE** (optional, CC0 cross-walk, off by default) | |
| TMDB / TVDB / IMDb / ComicVine | **KEEP IDs only** from upstream servers; don't call their APIs | |

Sources: GitHub repos above (gh api); docs.nodebb.org/activitypub; themoviedb.org/api-terms-of-use; thetvdb.com/api-information and support.thetvdb.com FAQ; data.imdb.com/non-commercial-datasets; openlibrary.org/developers/licensing and /developers/api; musicbrainz.org/doc/About/Data_License and /MusicBrainz_API/Rate_Limiting; comicvine.gamespot.com/api; wikidata.org/wiki/Wikidata:Licensing; isbn-international.org.
