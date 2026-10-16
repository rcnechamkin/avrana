# Continue and hand-off: capability matrix, recovery matrix and physical test script

Status: Home 2.0 sprint, Lane B, 2026-10-16. Implemented and locally verified against **synthetic fixtures and
loopback mocks only**. Nothing here has been run against a real service or a real device. Covers AVR-504
(progress capability), AVR-479 (hand-off and recovery) and the Continue rules of AVR-381.

Every upstream claim is labelled:

- **verified-by-doc**: read in the upstream's published source or documentation at the version and URL given,
  on 2026-10-16. That proves what the upstream code says, not what the deployed instance does.
- **UNVERIFIED**: recalled, inferred, or only exercised by our own hand-written fixtures. Needs the owner's
  capture run (REAL-SERVICES-PATH.md, step 1) or a physical test below.

Deployed versions as recorded in this repository: Jellyfin **10.11.11** (docs/SERVICES.md, public information
endpoint). Audiobookshelf **2.36** is the fixtures' `_target_version`, not confirmed. Komga and
Calibre-Web-Automated: no version recorded (UNVERIFIED).

## 1. What a Continue card does (AVR-381)

| Rule | Where | Test |
|---|---|---|
| The verb is **Resume** only when the upstream gave this member a saved position of at least one whole second, believable (0 to 1,000 hours) and not finished. Otherwise **Open**. New this week is always Open. | `viewmodel.continue_state`, `action_of` | `tests/test_continue_semantics.py` |
| Remaining time is the upstream's own numbers: Jellyfin `RunTimeTicks - PlaybackPositionTicks` (10,000,000 ticks per second), Audiobookshelf `duration - currentTime` (seconds, float, truncated). Minutes are rounded up; under a minute is "less than a minute left". | adapters, `progress_words` | same |
| A percent only when there are no seconds to subtract ("42 percent listened"). 0 percent reads "just started", 100 "nearly finished". | `progress_words` | same |
| Finished items never appear: Jellyfin `UserData.Played`, position at or past the run time; Audiobookshelf `isFinished`, `progress >= 1`, position at or past the duration. | adapters, `build_home` | same, `test_audiobookshelf.py` |
| Negative, NaN, non-integer, boolean or huge numbers are unknown: no time is made up. Audiobookshelf `duration <= 0` falls back to the item's own duration. | `_seconds`, `bounded_int` | same |
| Accessible name (`CardVM.action_label`): "Resume *title* in Movies and TV, 1 hour 10 minutes left" / "Open *title* in Comics". Member language only: never Jellyfin, Audiobookshelf, Komga or Calibre-Web. Titles are escaped by the template. | `action_of` | `test_continue_semantics`, `webtests/test_web_continue.py` |
| `CardVM.kind_label`: Movie, Episode, Series, Audiobook, Comic, Book. | `KIND_LABEL` | same |
| Episode secondary line: "Series · S1 E3" when the upstream gives series, season and episode. | Jellyfin adapter, `_item_vm` | same |
| At most four cards on Home, round-robin across services. | `RAIL_MOST` | `test_web_home.py` |
| Comics and books never offer Continue (no member progress, see section 2). | adapters' `not_offered` | `test_komga.py`, `test_calibre_web.py` |
| One failing service costs only its own section; another member's data is discarded. | base class, `aggregate.gather` | `webtests/test_web_continue.py`, `test_web_sections.py`, `test_web_audiobooks.py` |
| Avrana never claims playback started and never copies progress between services. | wording; no write route exists | route allow-lists (`test_*_adapter.py`) |

Card markup (the visible 44 px Resume/Open control and its use of `action_label`) belongs to Lane A's `card`
macro; this lane only sets the fields.

## 2. Progress capability matrix (AVR-504)

| | Jellyfin | Audiobookshelf | Komga | Calibre-Web (CWA) |
|---|---|---|---|---|
| **Endpoint used** | `GET /UserItems/Resume?userId=` (10.9+; `Users/{id}/Items/Resume` kept as obsolete) **verified-by-doc**: `Jellyfin.Api/Controllers/ItemsController.cs`, branch `release-10.11.z` | `GET /api/users/{id}` and its `mediaProgress` list, then `GET /api/items/{id}?expanded=1` per entry. Field set **verified-by-doc**: `server/models/MediaProgress.js` `getOldMediaProgress()`, branch `master`. That `/api/users/{id}` embeds `mediaProgress` for an admin token: **UNVERIFIED** | none (not offered) | none (not offered) |
| **User scope** | The mapped member's user id in the query; the response's `UserData.UserId`/`ItemId` are checked when present (**UNVERIFIED** whether real responses carry them) | The member's own user id in the path; every entry's `userId` must equal it, else the section is discarded. Admin-capable token (ADAPTER-CONTRACT 11.1) | The shared regular account. Its read progress is the shared account's, not the member's, so it is never read | The shared viewer account. Per-member read state would need each member's own password |
| **Granularity** | Ticks (1/10,000,000 s) and `PlayedPercentage`; `Played` flag. Resume list filters `IsResumable = true` (**verified-by-doc**, same file); whether that excludes played items is not visible there (**UNVERIFIED**), so the adapter drops `Played: true` itself | `currentTime` and `duration` in seconds (float), `progress` 0 to 1 stored as sent by the client (1 when marked finished), `isFinished`, `hideFromContinueListening`, `lastUpdate` in ms (**verified-by-doc**). Ebook progress (`ebookProgress`) is not read: an ebook-only item with no audio position is not shown | n/a | n/a |
| **Refresh** | Section cache 30 s per member (`MediaAdapter.cache_ttl`), mapping 60 s | same | n/a | n/a |
| **Hand-off** | `https://watch.avrana.net/web/#/details?id=<32 hex>` (section 3) | `https://listen.avrana.net/item/<id>` | `https://read.avrana.net/book/<id>` | `https://books.avrana.net/book/<n>` |
| **Fallback** | No saved position: Open; no run time: percent or "*N* in"; failure: "Movies and TV are unavailable right now." | No `currentTime`: Open with a percent; failure: "Audiobooks are unavailable right now." | Open from New this week only | Open from New this week only |
| **Button** | **Resume** when position >= 1 s, else Open | **Resume** when `currentTime` >= 1 s, else Open | **Open** only | **Open** only |
| **Does Resume actually resume?** | The details page opens; the member presses play. Whether Jellyfin web then offers "Resume from *time*" for this member: **UNVERIFIED** (physical test P2) | The item page opens; whether the player starts at `currentTime`: **UNVERIFIED** (P3) | n/a | n/a |

Avrana never moves progress between services, never writes progress, and keeps no history: every adapter route
is GET on a fixed allow-list (`ALLOWED_ROUTES`).

## 3. Hand-off paths

Built only from `contract.HANDOFF_BASE` (fixed host per service) plus an id that fully matches a strict pattern;
an upstream-supplied URL is never used. Home renders a card only when its link starts with one of the four
fixed hosts followed by `/` (`viewmodel.HANDOFF_ALLOWED`, second check). There is no configurable hand-off host.

| Service | Path | Evidence |
|---|---|---|
| Jellyfin | `/web/#/details?id=<id>` | **verified-by-doc** for 10.10 and 10.11: jellyfin-web uses `createHashRouter` (`src/RootAppRouter.tsx`), has a `details` route (`src/apps/stable/routes/legacyRoutes/user.ts`), and the details controller reads `params.id`; `serverId` is optional and falls back to the current `ApiClient` (`src/controllers/itemDetails/index.js`), branches `release-10.10.z` and `release-10.11.z`. So no `serverId` is needed for a single-server web client. That the web client is served under `/web/` on watch.avrana.net: **UNVERIFIED** here (the Jellyfin default) |
| Audiobookshelf | `/item/<id>` | **verified-by-doc** (branch `master`): the client page `client/pages/item/_id/index.vue` exists; the server's default `ROUTER_BASE_PATH` is `/audiobookshelf` (`index.js`), and `server/Server.js` rewrites any URL without that prefix to include it (no redirect), so `/item/<id>` reaches the same handler. Whether the single-page client then renders the item at the un-prefixed address, and which version the deployed server runs: **UNVERIFIED** (P3). If it fails, the fix is the one path template in `contract._HANDOFF_PATH` (`/audiobookshelf/item/{id}`), not a new setting |
| Komga | `/book/<id>` | **verified-by-doc** (branch `master`): `komga-webui/src/router.ts` has `/book/:bookId` (history mode, base from `urls.base`). Deployed base path: **UNVERIFIED** |
| Calibre-Web | `/book/<n>` | **verified-by-doc** for upstream Calibre-Web (`cps/web.py`, `@web.route("/book/<int:book_id>")`, `login_required_if_no_ano`, branch `master`). The deployed app is Calibre-Web-Automated, a fork: **UNVERIFIED** that it keeps the route |

**LAN owner preview.** The preview (`docs/runbooks/home-owner-preview.md`) serves Home on
`http://10.0.0.218:8197`, but there is no hand-off host override: links still go to the public
`*.avrana.net` hosts through Cloudflare. An iPhone on the home Wi-Fi with internet reaches them like any
other device. A LAN-only hand-off host is deliberately not added: a configurable host would be an open-redirect
risk and would bypass Authentik on the way to the service. If the owner wants LAN hand-offs, it needs a reviewed,
allow-listed change, not a setting.

## 4. Hand-off and recovery matrix (AVR-479)

"Target" is what a Home card opens. Avrana never claims that playback started; a failure to open is the
upstream's to report, and `/help/trouble` ("If something doesn't open") says what to do next.

| Situation | iPhone/iPad Safari | iPhone home-screen app (standalone web app) | Android browser | Desktop browser | TV / native player |
|---|---|---|---|---|---|
| **Expected target** | The library's website at the item, same tab | The library's website; iOS may open an out-of-scope origin in an in-app browser sheet with a Done button (**UNVERIFIED**) | The library's website, same tab | Same tab | Not reachable: Avrana links do not open TV apps. Find the item by name in the app |
| **Identity boundary** | Avrana Home (Authentik in production; one password in the preview) → library's own sign-in. Jellyfin and Calibre-Web: Avrana username and password; Audiobookshelf and Komga: the Avrana sign-in button (portal HELP table, live configuration) | same, but its cookie jar may be separate from Safari's (**UNVERIFIED**) | as Safari | as Safari | the app's own sign-in |
| **Login reuse** | A library session in Safari is reused (cookie per host). Authentik session reused by Audiobookshelf/Komga SSO (**UNVERIFIED** for the item path) | may need a fresh sign-in once (**UNVERIFIED**) | as Safari | as Safari | n/a |
| **No-app fallback** | Always the website; Avrana never deep-links into Swiftfin, AudioBooth, Panels etc. | same | same | same | Help topics list the apps |
| **Login prompt** | Library's login page. After sign-in it may land on its start page, not the item (Jellyfin hash route: **UNVERIFIED**). Help: come back and choose the item again | same | same | same | n/a |
| **Missing item** | Library's own "not found" or empty page (**UNVERIFIED** wording). Home drops the item within 30 s (cache) if the upstream no longer lists it | same | same | same | n/a |
| **Expired session / second sign-in elsewhere** | Library asks to sign in again (Help: "If you are asked to sign in") | same | same | same | app asks |
| **Library unavailable** | Home: "Movies and TV are unavailable right now.", Try again, the place struck through and linked to `/help/trouble#unavailable`. Other libraries unaffected | same | same | same | n/a |
| **Not linked** (no matching upstream account) | Home: "Movies and TV are not set up for your account yet." Help: ask the person who invited you | same | same | same | n/a |
| **Way back to Avrana** | Back button; AVRANA at the top of every Avrana page; footer "Back to home" on every shell page except Home | Close the sheet (Done) or swipe back (**UNVERIFIED**) | Back button | Back button | n/a |

**Allowlist proof (fixtures).** `tests/test_continue_semantics.py::HandoffTests` proves each service builds its
one fixed host and path, that hostile ids (`../`, `//host`, `@host`, `?`, `#`, backslashes, over-long, wrong
case for Jellyfin, non-strings) never become links, and that a card whose link is on any other host (look-alike
suffix, userinfo, `http:`, upper-case host, leading space, `javascript:`) is not rendered. Links are member-scoped
because they come only from that member's own section (isolation suites: `test_web_sections.IsolationTests`,
`test_web_audiobooks`). No route builds a redirect from request input (`test_route_layer_source`).

## 5. Navigation decisions

- Every shell page (Home, Search, Account, Help, help topics, `/help/trouble`, Read, Request, the Watch
  interstitial) shows the masthead with AVRANA linking to Home. Every one except Home has a footer
  "Back to home"; the bare "Back" stays only on pages without the shell (sections off: byte-identical to the
  portal; the 404 page).
- The account menu holds "Account and security" only; Help is the masthead link beside it, so it is no longer
  listed twice. Home's footer keeps "Account and security" and "Help" (Home has no "back").
- Read and Request (with the shell) say what they are before the tiles. Request: "Ask for something that is
  missing from a library. Each place below opens a separate request website, where you sign in and search for
  the title." and "Asking does not add it straight away, and not every request can be filled." No library is
  named in either intro.
- The Watch interstitial (with the shell) says it opens a separate website with its own sign-in, that Avrana
  does not start anything there, and how to come back; it offers "If something doesn't open" beside
  "Set up the app".
- **Unavailable place**: instead of a dead struck-through span, the struck place is a link to
  `/help/trouble#unavailable` (accessible name "Watch, unavailable"), which says what happened, that other
  libraries keep working, to choose Try again, that the library itself can still be tried, and links to it.
  Chosen over linking the place itself because the member asked "why is this struck", and over plain text
  because a link is the next useful action.
- `/help/trouble` exists only with the shell; with sections off it is the standard 404 (portal parity). It names
  only the member's own libraries; a member with none is told only that.

## 6. Physical test script (owner)

Run on the LAN owner preview after it is redeployed with this change, with synthetic or the owner's own items.
Record each as **PASS**, **FAIL** (what happened instead) or **N/A**, with device, OS and browser version, date,
and service version, in a dated file under `docs/findings/`. No screenshots of real titles are committed.
Nothing below has been run.

Preparation: one movie partly watched (Jellyfin), one episode partly watched, one audiobook partly listened
(Audiobookshelf), one comic and one book visible in New this week.

| # | Device | Steps | Expected |
|---|---|---|---|
| P1 | iPhone Safari | Open Home. Read the Continue cards with VoiceOver | Each card is announced with its title, then "Resume … in Movies and TV, *N* left" or "Open …"; no upstream product names; at most four cards |
| P2 | iPhone Safari | Tap the movie's Resume | watch.avrana.net opens at that movie's details page (not the Jellyfin home). Pressing play offers or starts from the saved time. Record which. Avrana itself never said it was playing |
| P3 | iPhone Safari | Tap the audiobook's Resume | listen.avrana.net opens that book's page (check the address: `/item/<id>` or `/audiobookshelf/item/<id>`). Record whether play continues from the saved time |
| P4 | iPhone Safari | Tap a comic and a book in New this week | read.avrana.net and books.avrana.net open the item page, possibly after their sign-in |
| P5 | iPhone Safari | Sign out of watch.avrana.net (or use a private tab), then tap the movie | Jellyfin's sign-in appears. After signing in, record whether it lands on the movie or its home page. Help's "If you are asked to sign in" matches what happened |
| P6 | iPhone Safari | After each hand-off, press Back | Returns to Avrana Home with the same cards |
| P7 | iPhone home-screen app | Add Home to the Home Screen, open it, repeat P2, P3 and P6 | Record whether the library opens inside the app's window, in a sheet with Done, or in Safari, and whether a fresh sign-in is needed. Help's "If it opens in the browser instead of the app" matches |
| P8 | Android Chrome | Repeat P1 (TalkBack), P2, P3, P6 | As iPhone Safari |
| P9 | Desktop browser | Repeat P2, P3, P6; keyboard only (Tab to a card, Enter) | Focus is visible; Enter opens the item; Back returns |
| P10 | TV (Roku/Fire/Apple TV app) | Find the Continue movie by name in the TV app | The TV app's own resume point; Avrana does not claim to reach the TV |
| P11 | Any | Stop Audiobookshelf briefly (owner's choice) or block it, load Home | Movies still show; "Audiobooks are unavailable right now."; Listen struck through and linking to the help section; Try again works once it is back |
| P12 | Any | Remove or hide a Continue item upstream, wait 30 s, reload Home; tap an old link if still open | The card is gone after reload; the old link shows the library's own not-found page (record its wording) |
| P13 | Any | Open Read, Request, the Watch interstitial, Help, a help topic, `/help/trouble`, Account | Each has AVRANA at the top and "Back to home" in the footer; Request explains what requesting does; nothing says "success" or "playing" |

## 7. Not done here

- The visible Resume/Open control and its 44 px target (Lane A renders `CardVM.action`/`action_label`).
- Any real-service capture or real-device test (owner).
- Audiobookshelf ebook progress and podcast episodes (not offered).
- Komga/Calibre-Web per-member progress: impossible with a shared account by design (ADAPTER-CONTRACT 12.2, 13.2).
