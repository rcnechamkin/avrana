# Library catalogue (Media 2.0 Library)

Status: **code only, 2026-10-30.** Branch stack `feat/library-catalog-*` from `main` 1da4e86, draft PRs, not merged, not deployed.
Behind `HOME_LIBRARY_CATALOG` (default off; the name awaits review). Proven against synthetic fixtures, upstream source, and a bounded read-only live check (below). Real devices are still
open.

`/library` stops being recent shelves and becomes everything a member can open, in bounded server-rendered pages. Home
stays personal and Search stays lookup and requests. No new service, database, framework or offline promise.

## Baseline found at HEAD

| Packet says | Found |
|---|---|
| Sources current to 2026-10-30 | `main` = 1da4e86. Open and touching the same files: #186 (Komga adapter, `main.py`, settings), #162 and #164 (Komga guard). Text conflicts possible, none in behaviour. |
| "Use member keys where available" | Stronger needed: Home's shared Komga token is the owner's ADMIN account (AVR-782, open), so the catalogue uses ONLY the member's own key and never that token. |
| `/opds/stats` may give a count | CWA 4.0.6 has no such route, and its feed has no count. Books counts stay unknown above one upstream window. |
| A single page-size setting across services | Each upstream pages differently; a plain `?page=N` is the one abstraction. |
| Opaque cursors | Rejected: a page number carries no authority, so there is nothing to sign, bind, expire or replay. Every page is authorized and scoped afresh. |
| `MEDIA-STATE-REGISTER.md` | Dated 2026-10-26, stale; not relied on. |

The deployed versions are taken from `docs/design/HANDOFF-SIGN-IN.md`, `docs/SERVICES.md` and the Compose pins, not
observed. Whether the host still matches is the first item of the owner check below.

## Adapter evidence

Source read at the tag named, 2026-10-30. "Live" is the only column that would prove the deployment, and it is empty.

| Service, version | Grouping | Endpoint | Auth | Pagination | Member scope | Exact count | Contract test | Live |
|---|---|---|---|---|---|---|---|---|
| Jellyfin 10.11.11 | Movies | `GET /Items` `includeItemTypes=Movie`, `recursive`, `sortBy=SortName` | service key plus `userId` | `startIndex`, `limit` | upstream, by `userId` | `TotalRecordCount`, scoped by the same query | `test_catalog_jellyfin`, OpenAPI subset gate | UNVERIFIED |
| Jellyfin 10.11.11 | Series | as above, `Series` | as above | as above | as above | as above | as above | UNVERIFIED |
| ABS 2.36.0 | Titles | `GET /api/libraries/{id}/items` `sort=media.metadata.title`, `minified=1` | admin-capable token | `limit`, `page` (`getLibraryItems`: offset = page × limit) | the adapter: member's libraries, then `_visible` on every entry | `total`, only with no tag or explicit rule on the member | `test_catalog_audio_comics` | UNVERIFIED |
| ABS 2.36.0 | Series, Authors | not offered | | | the routes filter by the token's user, and the series shape was not proven, so a restricted member could see names they may not | | | Deferred |
| Komga 1.25.0 | Series | `GET /api/v1/series` `sort=metadata.titleSort,asc` (deprecated since 1.19, present) | the MEMBER's own key | `page`, `size` | upstream, by that key | `totalElements` under that key | `test_catalog_audio_comics` | UNVERIFIED |
| CWA 4.0.6 | Titles | `GET /opds/books/letter/00` (the index's All, by `Books.sort`) | shared viewer, contract 13.2 | `offset`, multiples of `config_books_per_page` only | shared view invariant | none above one window | `test_catalog_books` | UNVERIFIED |

Two upstream facts that shaped the code:

- **CWA float offsets.** `cps/opds.py` passes `off / per_page + 1` and `cps/db.py` computes `int(pagesize * (page - 1))`, so
  offset 24 with 60 per page lands on 23. Only multiples of the upstream's page size are requested; a page here is cut
  from one or two of those windows, learned from page one's `rel="next"`. The link is matched whole against the one
  route it can be and must move forward.
- **Komga's GET listing is deprecated** and its successor is a POST, which the adapter's GET-only guard refuses on purpose.
  Removal would be `RouteMissing`: Comics unavailable, never empty. An upgrade past it needs a reviewed guard change.

Upstream calls for one page, excluding the cached 60 s mapping: Jellyfin 1; Audiobookshelf 2 plus one per other library;
Komga 1, or 2 with `HOME_KOMGA_BOOK_LIBRARIES`; CWA 1 to 3. None per card. Covers are lazy, through `/art`.

## Contract

`MediaAdapter.catalog(principal, group, page, size)` returns a `SectionResult` with section `catalog`, `total` (None when
not exact for this member) and `has_next` (never inferred from a full page). It runs the usual order: principal, group,
member-partitioned cache (120 s), caps, circuit, mapping, hook. `catalog_groups` lists only what really pages, so no
control is inert. `CatalogRequest` and `CatalogItem` from the packet were not added: `MediaItem` already fits and a
parallel type would be two ways to say one thing. Packet JSON routes were not added; the page is complete as HTML.

Komga differs in one way: `catalog` requires the member's key before the shared flow, and a missing or refused key is
`NOT_LINKED`, never the shared account and never a count against the circuit every member shares. A series is
`Kind.COMIC_SERIES`, id `komga:series:<id>`, so it can never be taken for a book's title page, and it hands off to
`https://read.avrana.net/series/<id>` (komga-webui router, unverified live).

## Pages

- `/library`: Overview. One card per library the member's groups open, with up to three decorative covers and a count only
  when exact. One small page per library, concurrently under the shared hard cap; a down library is labelled alone.
- `/library?lib=<service>[&group=][&view=][&page=]`: one page, Previous and Next as plain links, a header switcher as a
  native `<details>` of links. Foreign or malformed `lib` is the Overview, without an upstream call and without echo.
- `?view=` keeps `grid`, `compact`, `list` and the old aliases. `shelves` is the grid: it has no meaning for one page.
- Search and Request stay as one quiet line on the Overview. Contribute keeps its own route; moving its signpost to Me is
  left out, since the packet ties that to the Me workstream.
- New menus are matte. Tokens only, no new glass, no script required.

## Owner decisions and checks

1. **Flag name and default**: `HOME_LIBRARY_CATALOG`, off.
2. **`HOME_KOMGA_BOOK_LIBRARIES`** (owner decision 2026-10-30): exclude verified ebook libraries only. Komga's listing has
   no media-profile filter, so this is a setting rather than a guess. The verified id is below; applying it is a deploy step.
3. **Members without a working Komga key** (owner decision 2026-10-30): no key says "Connect comics", a refused key says "Reconnect comics", both linking to Me -> Comics (`/me/comics`) when that page is open to the member. Otherwise the neutral "Not set up yet" and Help. Comics never falls back to the shared account.
4. **Read-only live check**: done, see the evidence below.
5. **Phone acceptance**: the eight scripts of the packet on real devices.

## Evidence recorded 2026-10-30

**Live, read-only, host `avrana`, branch adapters in memory beside the running Home.** GET requests only, private cache,
no container, config or file change; output was counts and salted digests. Group gating was not under test here: every
probe held all four groups, so these rows show what each upstream returns for that member.

| Service | Result |
|---|---|
| Jellyfin | 8 linked members, each 69 movies (3 pages) and 15 shows, no repeats; identical sets; page 1 about 170 ms |
| Audiobookshelf | 8 linked members, each 288 titles (12 pages), identical sets; 1 member gets the count, 7 do not, because their account cannot see explicit titles; page 1 about 75 to 100 ms |
| Komga | 2 keyed members, each 118 series; last page exact; a page past the end is empty; a member with no key is `not_linked`; series covers load; a comma `library_id` is honoured |
| CWA | 91 books over 4 pages, no repeats, Next ended; 67 are outside `/opds/new`, so older books are reachable; one shared viewer account, so no per-member view exists |

Of 23 bound usernames, Jellyfin returned nothing for 10 unmapped and 5 disabled, Audiobookshelf nothing for 15 unmapped.
**No linked member is restricted today**, so a hidden title could not be probed live. That negative case stays proven
offline only, and needs a restricted test member to prove live. Service versions were not read by this check.

**Komga exclusion verified:** `HOME_KOMGA_BOOK_LIBRARIES=0S2D6Q6RKFBV1` ("Books (Trial)": 12 EPUB one-shots; the other five
libraries sampled as comics). With it, 118 series become 106. Not applied. It names a trial library: recheck the id if
that library is replaced.

**Fixture, Chromium, 320 px:** axe WCAG A and AA 0 violations on 6 pages; 34 keyboard stops, each with a visible ring and
none covered by the tab bar; no-JS Overview, category, Next, menu and Back work; at 200% root text overflow 0 and Next
clears the tab bar by 188 px; reduced motion gives no transition or animation.

**Not done:** real iPhone and Android, VoiceOver and TalkBack, Dynamic Type, safe areas, the installed PWA, WebKit. These
are the owner's device checks and the packet's eight scripts.

**Windows suite:** the one web failure was a local venv without the pinned PyYAML, which adds 5 skips; with it the test
passes. Not a code defect. **#186:** resolved in a local trial merge; `book_libraries` stays and `provisioning` goes, and
the catalog's reason no longer depends on a constant #186 deletes.

## Known limits

- A member with tag or explicit rules on Audiobookshelf gets no count, and a page can be short or empty with Next.
  Live, that is most members today: they see every title but get no number, because the rule alone decides.
- Sort is title only and unstable on equal sort keys upstream (Jellyfin and CWA offer no id tie-break), so a catalogue
  changing mid-walk can repeat or skip an entry. Accepted at this size; the page is complete again on reload.
- The tab bar's own labels collide at 200% root text at 320 px: existing shell, not changed here.

## Deployment and rollback (not applied)

Merge is owner-gated, then deploy as any Home change (`docs/DEPLOYMENT.md`), with a rollback tag and the flag still off.
Turning it on is one line in `beta-live.env` plus a recreate, each needing owner approval. Rollback is that line off:
`/library` is the old page, no data or schema changed. Verify after either: health, sign-in, `/library` for two members.
