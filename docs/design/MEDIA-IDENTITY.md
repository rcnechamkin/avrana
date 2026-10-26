# Media identity: when two upstream records are the same title (R2-B, AVR-747)

Status: **proposed, 2026-10-26.** Implemented in `services/avrana-home/avrana_home/media_ids.py` and the three
adapters below, proven against synthetic fixtures only. Not deployed. Evidence for every upstream field is in
`docs/audits/2026-10-26-oss-reuse-audit.md` and its appendices.

## Why Avrana builds this itself

No upstream offers a cross-service identity. Jellyfin exposes `ProviderIds` on an item but cannot be queried by
them over HTTP (10.11.11 and 12.3 only have the presence filters `hasTmdbId`, `hasImdbId`, `hasTvdbId`).
Audiobookshelf and Komga store ISBNs (and Audiobookshelf ASINs) per item. Calibre-Web's OPDS feed exposes only a
UUID. So the identity layer is a small, pure function inside Home, over items a member's own adapters already
returned. It is not a catalogue, an index or a store (owner decision 2026-10-11; AVR-503 found no index needed).

## Identifiers and where they come from

| Scheme | Level | Source (field) | Validation |
|---|---|---|---|
| `tmdb` | work: movie, series or episode | Jellyfin `ProviderIds.Tmdb` | `[1-9][0-9]{0,9}` |
| `imdb` | work | Jellyfin `ProviderIds.Imdb` | `tt[0-9]{7,10}` |
| `tvdb` | work | Jellyfin `ProviderIds.Tvdb` | `[1-9][0-9]{0,9}` |
| `isbn13` | edition | Audiobookshelf `media.metadata.isbn`, Komga `metadata.isbn` | ISBN-10 or ISBN-13 with a correct check digit; hyphens and spaces removed; ISBN-10 rewritten as ISBN-13; a body of one repeated digit (placeholders such as `0000000000`) refused |
| `asin` | edition | Audiobookshelf `media.metadata.asin` | `[A-Z0-9]{10}`; a valid ISBN-10 given as an ASIN counts as that ISBN |

Rules:

1. **Upstream-held only.** Home never calls TMDB, TVDB, IMDb, Open Library, ComicVine or any other outside
   service, so their API terms (non-commercial use, attribution, TVDB's paid tier) never apply to Home.
2. **Validate, never repair.** A value that does not match is dropped (surrounding whitespace is ignored; the value itself is never changed). One upstream giving two different valid
   values for one scheme is a contradiction: that scheme is dropped for the item.
3. **Work keys carry the kind.** TMDB numbers movies and TV separately, and an episode is not its series, so a
   key is `movie:tmdb:603`, `series:tmdb:1399`, `episode:tvdb:...`. Edition keys are `isbn13:...` and `asin:...`
   whatever the kind, because an ISBN names one edition in every service that holds it.
4. **Exact keys only.** Two items are the same title only when they share a key. Title, creator and year never
   link anything. An ebook and its audiobook have different ISBNs and are therefore **not** linked: linking
   formats of one work needs a work-level book identifier that none of the upstreams holds today.
5. **Ambiguity is a state.** If one service gives the same key to two different items (a duplicate import, two
   files of one edition), that key is ambiguous and links nothing. If different keys would chain two items of one
   service into one title, the whole chain is dropped as ambiguous.
6. **Per member, per request, internal.** `link()` sees only the items one member's own adapters returned, so
   it cannot reveal another member's library. The identifiers are on `MediaItem.external_ids`, are not in
   `to_dict()` (the public JSON view), are never rendered, and are left out of `repr(MediaItem)` so a stray log
   line cannot carry them. Like the rest of the item they sit in the member's own in-memory cache for its TTL.

## Missing and partial data

| Case | Behaviour |
|---|---|
| No identifier at all (common: hand-added files, Calibre-Web) | The item works exactly as before; it simply links to nothing |
| Malformed or hostile value (wrong pattern, bad check digit, non-string, nested object, over 32 characters) | Dropped |
| Plugin keys in Jellyfin `ProviderIds` (AniDB, TvMaze, ...) | Ignored until a scheme is added here on purpose |
| Same TMDB number on a movie and a series | Different keys (kind), not linked |
| Same ISBN in Komga and Audiobookshelf (one edition held twice; Calibre-Web exposes no ISBN) | Linked |
| Two Komga books with one ISBN | Ambiguous, not linked |
| Upstream changes or removes an identifier | Takes effect when the item is next fetched (existing cache TTLs) |

## What uses it next

Nothing renders a link yet. Planned consumers, each its own reviewed slice: a title page "also in" link
between the same edition in two libraries (R3; today only Komga and Audiobookshelf can share an ISBN); a Seerr title deep link `/movie/{tmdb}` or `/tv/{tmdb}` (owner
question Q2 in the R1 audit); title-linked social records keyed by work identity (R4, AVR-749).

## Verification status

Field names are doc-verified against upstream source (Jellyfin `BaseItemDto.ProviderIds` and the `ProviderIds`
item field in the 10.11.11 and 12.3.0 OpenAPI files; Audiobookshelf book metadata `isbn`/`asin` at `edb1f7ef`;
Komga `BookMetadataDto.isbn` at `023ec905`). None is live-verified. The owner's capture tool drops provider ids
unless run with `--keep-provider-ids` (`tools/capture_upstreams.py`); a recorded check with that flag is the way
to verify the Jellyfin shape on the real server.
