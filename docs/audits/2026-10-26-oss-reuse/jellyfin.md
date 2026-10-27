# Jellyfin ecosystem — open-source reuse audit for Avrana Media

Researched 2026-10-26. Read-only. Avrana runs **Jellyfin 10.11.11**. Evidence comes from source at pinned SHAs (fetched via `gh api` / raw.githubusercontent.com) and from the published OpenAPI spec.
Labels: **CONFIRMED** means I saw it in source or docs. **HYPOTHESIS** means it is inferred or not verified.

> **Version context (CONFIRMED):** upstream has moved to a new major line. Releases are **v12.0 (2026-09-08), v12.1, v12.2 and v12.3 (2026-10-23)**. **v10.11.11 (2026-06-06) is the last 10.x release.** The TypeScript SDK 1.0.x targets 12.x, and 0.13.0 is the last SDK for 10.11.x. Avrana is on a now-superseded line, so plan a 12.x compatibility check. In v12.3 the legacy `/Users/{userId}/...` routes are still present in `Jellyfin.Api/Controllers/ItemsController.cs` (lines 721 and 1027).

## 1. Repositories

### jellyfin/jellyfin (server)
| Field | Value |
|---|---|
| URL | https://github.com/jellyfin/jellyfin |
| Latest release | v12.3, 2026-10-23 (tag commit 06de749d435e2d0be0c5119a41f2300fdd7143e5) |
| **Pinned / inspected** | **v10.11.11 → commit 1fbd8739292cce610231be93daf43368733edf63** (2026-06-06) |
| HEAD (master) | ed211765c2ebbb3f5093f67596c267058c6a4124 (2026-10-26) |
| Code license | GPL-2.0 (GitHub SPDX) |
| Brand/trademark | "Jellyfin" name and logo are trademarks of Jellyfin, Inc. (CA/US/EU/CN). Third parties may use "for Jellyfin" as a compatibility affix but may not imply an official client. The logo may not be used as another project's logo, but the colour gradient is allowed. Free-to-access servers have an implicit license. Source: https://jellyfin.org/docs/project/branding. Brand assets live in jellyfin/jellyfin-ux under **CC-BY-SA-4.0** (GitHub SPDX), and trademark limits still apply. |
| Activity | Very active: commits daily, 12.x point releases every ~2–3 weeks, 10.11.x point releases roughly monthly through 2026-06 |
| Maturity | Production, ~58.6k stars |

### jellyfin/jellyfin-web
| Field | Value |
|---|---|
| URL | https://github.com/jellyfin/jellyfin-web |
| Latest release | v12.3, 2026-10-23 |
| **Pinned / inspected** | **v10.11.11 → 35c0793ece3adbd247eab290ae1effab851f3d37** (router also checked at tag v12.3) |
| HEAD | 89c5bf33b60abc7a3ade3ca142e9410d252595c4 (2026-10-26) |
| License | GPL-2.0, with the brand terms above |
| Activity / maturity | Very active; the official client |

### jellyfin/jellyfin-vue
| Field | Value |
|---|---|
| URL | https://github.com/jellyfin/jellyfin-vue |
| Latest release | No GitHub Release objects. Latest tag 0.3.1 → 8dce0e2df3b11308e1674e31fd03625c0ed3139f (2023-04-03) |
| **Inspected** | HEAD aeee28fab7dbc558a3a328a5d57c63a24014f085 (2026-10-26) |
| License | **GPL-3.0** (LICENSE file verified) |
| Status | **Experimental, not archived.** README calls it an "experimental, alternative browser-based web client" and says there are no stable releases yet. Commits are active (mostly i18n). Uses `@jellyfin/sdk` 1.0.1 (the 12.x SDK), `blurhash` 2.0.5, Vue and Vuetify |

### jellyfin/jellyfin-sdk-typescript
| Field | Value |
|---|---|
| URL | https://github.com/jellyfin/jellyfin-sdk-typescript |
| Latest release | v1.0.2, 2026-10-23 (commit 780ffa49788bebf161e6aeba38712bab44a9bc7d, also HEAD) |
| License | MPL-2.0 |
| Version map (README) | 1.0.x → Jellyfin 12.x; **0.13.0 (2025-10-28) → 10.11.x**; 0.12.0 → 10.11.x |
| Generation | **CONFIRMED** generated from OpenAPI. `package.json` has `"build:generated-client": "rimraf src/generated-client && openapi-generator-cli generate"` (@openapitools/openapi-generator-cli 2.39.1) plus `fix-schema` (`scripts/modify-schema.mjs openapi.json`). README tells users to obtain `openapi.json` from the Jellyfin server repository. |
| Activity | Releases track server majors |

### jellyfin/jellyfin-apiclient-python
| Field | Value |
|---|---|
| URL | https://github.com/jellyfin/jellyfin-apiclient-python |
| Latest | tag v1.20.2 → commit f3fa567344fef606cc78c5abc2bdaadffc6a67e5 (2026-10-14). PyPI `jellyfin-apiclient-python` 1.20.2. No GitHub Release objects |
| HEAD | caf7ebb0d8a3a776d1a33bd6f6cf02556c083bee (2026-10-26) |
| License | **GPL-3.0** (GitHub SPDX and PyPI) |
| Nature | **Hand-written, not generated.** README says it is the API client extracted from Jellyfin Kodi and that it is not complete. Supports API-key auth. Recent PRs (2026-10-26) cover TLS verify default, playlists and server-id storage, so it is maintained |

### OpenAPI spec (official)
| Field | Value |
|---|---|
| Per-release files | **CONFIRMED** at https://repo.jellyfin.org/files/openapi/stable/jellyfin-openapi-10.11.11.json (redirects to a mirror, 2.08 MB, `openapi: 3.0.1`, `info.version` 10.11.11, 315 paths). Every 10.11.x and RC is listed |
| Rolling | https://repo.jellyfin.org/files/openapi/ has `stable/`, `unstable/`, `jellyfin-openapi-stable.json` and `_previous`. Also https://api.jellyfin.org/openapi/ |
| Runtime | HYPOTHESIS: also served live by the server (Swashbuckle `/api-docs/openapi.json`); not checked on Avrana's instance |
| Security scheme | `CustomAuthentication`: apiKey in the `Authorization` header |

## 2. Feature → endpoint table (10.11.11, SHA 1fbd873)

All non-legacy routes below are in the 10.11.11 spec with security `CustomAuthentication: DefaultAuthorization`, except where noted. Controller paths are relative to `Jellyfin.Api/Controllers/`.

| Feature | Current route (10.11) | Legacy route (Obsolete, `IgnoreApi`, so **absent from spec**) | Source | Key params / notes |
|---|---|---|---|---|
| Continue watching | `GET /UserItems/Resume` | `GET /Users/{userId}/Items/Resume` | `ItemsController.cs` L824 / L924 | `userId?`, `limit`, `parentId`, `mediaTypes`, `includeItemTypes`, `fields`, `enableUserData`, `enableImageTypes`, `imageTypeLimit`, `excludeActiveSessions`. Sorted by DatePlayed desc, `IsResumable=true`, honours the user's `LatestItemExcludes` |
| Next Up | `GET /Shows/NextUp` | — | `TvShowsController.cs` L76 | `userId?`, `seriesId`, `parentId`, `nextUpDateCutoff`, `enableResumable` (default true), `enableRewatching` (default false); `disableFirstEpisode` is `[ParameterObsolete]` |
| Latest | `GET /Items/Latest` | `GET /Users/{userId}/Items/Latest` | `UserLibraryController.cs` L521 / L604 | `parentId`, `includeItemTypes`, `isPlayed` (defaults to false), `limit` (default 20), `groupItems` (default true). HYPOTHESIS: returns a plain array rather than QueryResult (return type not inspected) |
| Browse / filter / search | `GET /Items` | `GET /Users/{userId}/Items` | `ItemsController.cs` L160 / L626 | `searchTerm`, `filters` (IsFavorite, IsResumable, IsPlayed, Likes…), `isFavorite`, `hasTmdbId`/`hasImdbId`/`hasTvdbId` (bool presence only), `ids`, `fields=ProviderIds,…` |
| Search hints | `GET /Search/Hints` | — | `SearchController.cs` L28/L79 | `searchTerm` (required), `includeItemTypes`, `mediaTypes`, `parentId`, `includePeople`/`Media`/`Genres`/`Studios`/`Artists` |
| Item detail | `GET /Items/{itemId}` | `GET /Users/{userId}/Items/{itemId}` | `UserLibraryController.cs` L74 / L109 | Uses `GetItemById<BaseItem>(itemId, user)`, which returns null (404) if the item is not visible to the user |
| Images | `GET`/`HEAD /Items/{itemId}/Images/{imageType}`, `/{imageIndex}`, and a long path form | — | `ImageController.cs` L546, L624, L702 | `tag`, `maxWidth`, `maxHeight`, `fillWidth`, `fillHeight`, `quality`, `format`, `blur`, `percentPlayed`, `unplayedCount`, `backgroundColor`, `foregroundLayer`. **No `[Authorize]`; the spec shows `security: null`, so images are anonymous** |
| Image tags / blurhash | in `BaseItemDto` | — | `MediaBrowser.Model/Dto/BaseItemDto.cs`: L487 `ImageTags`, L493 `BackdropImageTags`, L530 `ImageBlurHashes: Dictionary<ImageType, Dictionary<tag, hash>>`, L311 `ParentBackdropImageTags`, L443 `SeriesPrimaryImageTag` | Pass `tag` for cache-busting and long cache lifetimes |
| User data read/write | `GET`/`POST /UserItems/{itemId}/UserData` | `/Users/{userId}/Items/{itemId}/UserData` | `ItemsController.cs` L969, L1024 / L1005, L1064 | `UserItemDataDto` fields (`MediaBrowser.Model/Dto/UserItemDataDto.cs`): `Rating`, `PlayedPercentage`, `UnplayedItemCount`, `PlaybackPositionTicks`, `PlayCount`, `IsFavorite`, `Likes`, `LastPlayedDate`, `Played`, `Key`, `ItemId` |
| Favorite | `POST`/`DELETE /UserFavoriteItems/{itemId}` | `/Users/{userId}/FavoriteItems/{itemId}` | `UserLibraryController.cs` L212/L259 | |
| Like/dislike rating | `POST`/`DELETE /UserItems/{itemId}/Rating` | `/Users/{userId}/Items/{itemId}/Rating` | `UserLibraryController.cs` L354/L306 | |
| Mark played | `POST`/`DELETE /UserPlayedItems/{itemId}` | `/Users/{userId}/PlayedItems/{itemId}` | `PlaystateController.cs` L72/L138 | |
| Playback reporting | `POST /Sessions/Playing`, `/Progress`, `/Ping`, `/Stopped` | `/PlayingItems/...` (obsolete) | `PlaystateController.cs` L199–L245 | Not needed if playback is handed off |
| Quick Connect | `GET /QuickConnect/Enabled`, `POST /QuickConnect/Initiate`, `GET /QuickConnect/Connect`, `POST /QuickConnect/Authorize` (auth), `POST /Users/AuthenticateWithQuickConnect` | — | `QuickConnectController.cs` L40–L113; `UserController.cs` L244 | |
| Password auth | `POST /Users/AuthenticateByName` | — | `UserController.cs` L209 | |
| API keys | `GET`/`POST`/`DELETE /Auth/Keys` | — | `ApiKeyController.cs` L35–L68 | `RequiresElevation` (admin) |
| SyncPlay | `/SyncPlay/*` (New, Join, …) | — | `SyncPlayController.cs`; policy in `Jellyfin.Api/Auth/SyncPlayAccessPolicy/` | Spec security: `SyncPlayCreateGroup`, `SyncPlayHasAccess` |

### What changed in 10.9 → 10.11 (CONFIRMED)
- `HttpGet("UserItems/Resume")` is **absent at v10.8.13 and present at v10.9.0 and v10.10.0**. The userId-less routes arrived in 10.9: `/UserItems/*`, `/Items/{id}`, `/Items/Latest`, `/UserFavoriteItems/*` and `/UserPlayedItems/*`.
- The old `/Users/{userId}/...` routes are kept with `[Obsolete("Kept for backwards compatibility")]` and `[ApiExplorerSettings(IgnoreApi = true)]`. They still work in 10.11.11 and v12.3 but **do not appear in the OpenAPI spec**.
- Recommendation: use the userId-less routes and let the token determine the user.

### Per-user authorization (CONFIRMED)
- `Jellyfin.Api/Helpers/RequestHelpers.cs` `GetUserId()`: if `userId` is omitted, the authenticated user is used. A `userId` other than the caller's throws `SecurityException("Forbidden")` **unless the caller is in the Administrator role**.
- `Jellyfin.Api/Auth/CustomAuthenticationHandler.cs` L53–57: **an API key gets the Administrator role**. An API-key caller can therefore query any user's resume, next-up and latest lists by passing `userId`.
- `InternalItemsQuery(User)` calls `SetUser()` (`MediaBrowser.Controller/Entities/InternalItemsQuery.cs` L366+), which applies `MaxParentalRating`, `BlockUnratedItems`, `BlockedTags` and `AllowedTags`. Folder access is enforced via `GetChildren(user, …)` and `ItemIsVisible`. `LibraryManager.GetItemById<T>(id, user)` (`Emby.Server.Implementations/Library/LibraryManager.cs` L1401) returns null if the item is not visible.
- Result: Resume, NextUp, Latest, Items, Search/Hints and Items/{id} all honour library access and parental controls **for the resolved user**. This holds both with that user's token and with an admin or API key plus `userId=`.
- `/Items` called with an API key and **no** userId runs with `user = null` (ItemsController L250–260 comment), which is unfiltered. Never omit userId with an API key.
- **Images are anonymous.** Anyone who knows an item GUID can fetch its artwork. That is low risk, but a hub proxying images should not widen exposure.

## 3. ProviderIds (CONFIRMED)
- The enum is in `MediaBrowser.Model/Entities/MetadataProvider.cs`: Custom=0, Imdb=2, Tmdb=3, Tvdb=4, Tvcom=5, TmdbCollection=7, MusicBrainzAlbum=8, MusicBrainzAlbumArtist=9, MusicBrainzArtist=10, MusicBrainzReleaseGroup=11, Zap2It=12, TvRage=15, AudioDbArtist=16, AudioDbAlbum=17, MusicBrainzTrack=18, TvMaze=19, MusicBrainzRecording=20. Helpers are in `ProviderIdsExtensions.cs` and `IHasProviderIds.cs` in the same folder.
- Exposed as `BaseItemDto.ProviderIds: Dictionary<string,string>` (L255). You must request it with `fields=ProviderIds` on list endpoints, and the `fields` doc comment lists ProviderIds. Keys are the enum names as strings. HYPOTHESIS: plugins can add arbitrary keys (e.g. AniDB).
- **Querying by provider ID value is NOT exposed over HTTP in 10.11.11.** `InternalItemsQuery` has `HasAnyProviderId` (L338) and `ExcludeProviderIds` (L284). Code search on master finds `HasAnyProviderId` only in InternalItemsQuery, `BaseItemRepository.TranslateQuery.cs`, `SimilarItemsManager.cs` and `JellyfinQueryHelperExtensions.cs`, and in no controller. `GET /Items` only offers the presence booleans `hasTmdbId`, `hasImdbId` and `hasTvdbId`.
- For cross-service matching, Avrana must fetch with `fields=ProviderIds` and build its own index.

## 4. Deep links

### Jellyfin Web 10.11.11 (CONFIRMED)
- The router is a **hash router**: `src/RootAppRouter.tsx` uses `createHashRouter`. The same holds at v12.3.
- `src/components/router/appRouter.js` `getRouteUrl()` builds item URLs as `#/details?id={ItemId}&serverId={ServerId}` (L445/L462), with optional `&context=` (L448–451). Folders become `#/list?parentId=…&serverId=…`, genres `#/list?genreId=…`, and studios `#/list?studioId=…`.
- `src/controllers/itemDetails/index.js` L1923 does `params.serverId ? ServerConnections.getApiClient(params.serverId) : ApiClient`. **`serverId` is optional**, and the page falls back to the current server. The item is loaded with `apiClient.getItem(currentUserId, params.id)` (L61–65), so access is the logged-in web user's.
- Full working form (HYPOTHESIS for the base path; it depends on the reverse proxy and BaseUrl): `https://<jellyfin>/web/#/details?id=<itemId>[&serverId=<BaseItemDto.ServerId>]`.
- Search: `#/search?query=…` (`src/apps/stable/routes/search.tsx`, `QUERY_PARAM = 'query'`).
- `src/components/router/BangRedirect.tsx` rewrites old `#!/…` URLs and warns that the format is deprecated and will stop working in a future update.
- **No play/resume deep link.** The `video` and `queue` routes (`src/apps/stable/routes/legacyRoutes/user.ts` L71/L81) take no item parameter, and playback starts from playbackManager state. The best hand-off is the details page, which shows a Resume button. (Absence of any other mechanism is a HYPOTHESIS, but strongly supported.)
- **No officially documented or stable deep-link contract.** I found no jellyfin.org docs page, and the web search turned up only community threads. The `#/details?id=` form is stable in practice (unchanged from 10.11.11 to 12.3) but undocumented, so pin it with a test.

### Native apps
- **Swiftfin (iOS/tvOS), CONFIRMED on master 65bb6170a1209cb081bf07a97db313f2efdc144c:**
  - `Swiftfin/Resources/Info.plist` registers the URL schemes `swiftfin` and `jellyfin`.
  - `Shared/Services/DeepLink.swift` parses `^(swiftfin|jellyfin)://{serverID}/{userID}/(item|library)/{id}/?$` and routes to the item.
  - It switches or authenticates the user if needed (`Shared/Services/UserSession/UserSessionManager.swift` `handleOpenURL`).
  - Whether this is in a shipped App Store release is NOT verified.
- **jellyfin-android, CONFIRMED on master 07f1a283570d5536dc4b4b8bf88761d2abeea624:** `app/src/main/AndroidManifest.xml` has no custom scheme or http deep-link intent filter, only MAIN/LAUNCHER and MEDIA_PLAY_FROM_SEARCH. jellyfin-androidtv was not checked.
- **Findroid:** not verified because the manifest path was not found.

## 5. Jellyfin Vue
- GPL-3.0 and experimental with no stable release.
- Components of interest (all under `packages/frontend/src/`):
  - `components/Item/Card/ItemCard.vue` and `GenericItemCard.vue`
  - `components/Layout/Images/Blurhash/BlurhashCanvas.vue` and `BlurhashImage.vue`
  - `plugins/workers/blurhash-drawer.worker.ts`, a thin wrapper around npm `blurhash.decode()` with a pixel cache in a comlink worker
- Avrana is server-rendered Python. Vue SFCs do not transfer, and copying code would pull in GPL-3.0. **STUDY only** (card information hierarchy, blurhash placeholder pattern).
- For blurhash in the PWA, use the npm `blurhash` package directly in progressive JS, or render a placeholder colour server-side. HYPOTHESIS: npm `blurhash` is MIT; not re-verified here.

## 6. SDKs and OpenAPI use for Avrana
- The TypeScript SDK is OpenAPI-generated (CONFIRMED) and MPL-2.0. It is not usable from Python.
- The Python client is hand-written, incomplete, GPL-3.0 and Kodi-derived. Importing it brings GPL-3.0 obligations if Avrana is distributed, and its JellyfinClient/config-dict surface does not fit an httpx adapter.
- No official generated Python client exists in the jellyfin org repos inspected.
- **Recommendation:** keep the hand-written httpx adapter. Vendor `jellyfin-openapi-10.11.11.json`, or fetch it pinned by version, as a **contract fixture**:
  - Validate recorded responses against the `BaseItemDto`, `BaseItemDtoQueryResult` and `UserItemDataDto` schemas (e.g. `openapi-core` or jsonschema).
  - Assert that every route the adapter calls exists in the spec.
  - Caveat: the legacy `/Users/{userId}/...` routes are not in the spec, which is another reason to migrate off them.
  - Diff the 10.11.11 spec against `jellyfin-openapi-stable.json` (12.x) to scope the upgrade.
- HYPOTHESIS: the spec's license status (generated from GPL-2.0 code) is unclear, but using it as a test-only fixture is low risk.

## 7. Authentication for a per-member server-side aggregator
- **Accepted credentials (CONFIRMED):** the `Authorization` header (spec scheme), or the `ApiKey` query parameter. With `EnableLegacyAuthorization` on, the server also accepts `X-Emby-Token`, `X-MediaBrowser-Token` and the `api_key` query parameter (`Jellyfin.Server.Implementations/Security/AuthorizationContext.cs` L93–110). HYPOTHESIS: the header syntax is `MediaBrowser Client=…, Device=…, DeviceId=…, Version=…, Token=…`, the convention used by jellyfin-web and the SDK.
- **Option A: per-member user tokens (recommended).** Obtain them via `AuthenticateByName`, or via Quick Connect so Avrana never sees the password.
  - Avrana calls `POST /QuickConnect/Initiate` (anonymous) and receives a Code and a Secret.
  - The member approves the code inside Jellyfin (`POST /QuickConnect/Authorize`, authenticated as the member).
  - Avrana polls `GET /QuickConnect/Connect?secret=`.
  - Avrana then calls `POST /Users/AuthenticateWithQuickConnect {Secret}` and receives an AccessToken.
  - Limits: `QuickConnectManager.cs` sets `CodeLength = 6` and `Timeout = 10` (HYPOTHESIS: minutes). The admin must enable Quick Connect (check `/QuickConnect/Enabled`).
  - Tokens are device-session tokens. They appear under Devices and can be revoked per device.
  - Store tokens encrypted at rest: each one carries that user's full rights, including writing user data.
- **Option B: one admin API key plus `userId=`.** This works, because an API key holds the Administrator role (see `RequestHelpers.GetUserId`). The risks:
  - **One leaked key is full server admin**: it can delete items (`DELETE /Items`) and manage users, keys and plugins.
  - Omitting `userId` returns unfiltered results.
  - Avoid it, or confine it to admin-only jobs.
- **Session noise:** every authenticated request logs session activity (`LogSessionActivity`, via RequestHelpers). Use a stable Client/Device/DeviceId per member token (HYPOTHESIS: otherwise the Devices list grows).

## 8. Social and watch-party features
- **SyncPlay:** server-side group playback (`SyncPlayController.cs`, `Emby.Server.Implementations/SyncPlay/`). Per-user `SyncPlayAccess` is enforced by `SyncPlayAccessHandler`. It is driven by Jellyfin clients over WebSocket. A hub could at most list groups or link to them (HYPOTHESIS: a `GET /SyncPlay/List` route exists; not inspected). Not worth integrating for v1.
- **Per-user signals in `UserItemDataDto`:** `IsFavorite`, `Likes` (thumbs), `Rating`, `PlayCount`, `Played`, `LastPlayedDate`. These are writable via the `/UserFavoriteItems` and `/UserItems/{id}/Rating` routes.
- **Item-level ratings:** `BaseItemDto.CommunityRating` (L181), `CriticRating` (L127) and `OfficialRating` (L143, the parental rating string).
- `/Items` supports `filters=IsFavorite,Likes,IsFavoriteOrLikes` for building favorites rows.
- HYPOTHESIS: there is no per-user "friends watched" feed. Building one would need admin-level aggregation across users, which raises privacy concerns.

## 9. Recommendations
| Repo | Verdict | Why |
|---|---|---|
| jellyfin/jellyfin (server) | **RUN** (keep) + **INTEGRATE** via HTTP API | Integrate over HTTP only, so there is no GPL linkage. Use the userId-less 10.9+ routes. Plan for 12.x (10.11.11 is the last 10.x) |
| jellyfin/jellyfin-web | **RUN** as the playback hand-off target; **STUDY** the router | Deep link to `/web/#/details?id=…&serverId=…`. There is no play deep link and the contract is undocumented, so pin it with a test |
| jellyfin/jellyfin-vue | **STUDY** | GPL-3.0, experimental, Vue SFCs. Look at card and blurhash patterns only |
| jellyfin-sdk-typescript | **STUDY** (REJECT as a dependency) | TS only. Useful as an example of the spec-to-client pipeline and its spec fixes (`scripts/modify-schema.mjs`) |
| jellyfin-apiclient-python | **REJECT** (STUDY for edge cases) | GPL-3.0, incomplete, does not fit httpx |
| OpenAPI spec (per release) | **INTEGRATE** as test fixtures | Contract validation for the adapter, pinned to 10.11.11, plus a diff against 12.x |
| Swiftfin `jellyfin://` scheme | **STUDY** | Optional iOS hand-off, if confirmed released |
