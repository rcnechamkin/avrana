# Universal search, part 2: API caps and exact matching for books and comics

Status: proposal, 2026-10-28. Follows the owner's chat of 2026-10-27 ("put a monitor in place to see when the API
breaks for things that can hit an actual cap. For lack of accuracy for ebooks and comics, come up with a clever way
to fix this problem too"). Extends `UNIVERSAL-SEARCH-AND-REQUESTS.md` part 2, which planned title-and-author
guessing for ebooks and comics. This document replaces that guess with an exact join.

Evidence: read-only queries on host `avrana`, 2026-10-28 (`sqlite3 -readonly`, `docker exec … grep`). No member data
was read: only catalogue identifiers, counts and schema.

## 1. The cap monitor (built, not installed)

`scripts/api-caps-monitor.py` (branch `feat/api-caps-monitor`) with user units `api-caps-monitor.{service,timer}`
running every 30 minutes.

| Provider | Who calls it | Cap (published, HYPOTHESIS until seen) | What the monitor reads |
|---|---|---|---|
| Hardcover | Shelfarr, Shelfmark, CWA (one shared token) | about 60 requests a minute per token; tokens expire | Shelfarr's `metadata_provider_statuses` (status, `rate_limited_until`, failures) and all three logs |
| ComicVine | Omnibus web app and engine | 200 requests per resource per hour, plus "velocity" refusals (HTTP 420) | Omnibus logs and failed `JobLog` rows |
| Metron | Omnibus (not used yet: 0 of 120 series carry a Metron id) | 30 a minute, 10,000 a day | same |
| TMDB | Seerr's built-in key | about 50 a second, shared with every Seerr install | Seerr log |
| Google Books | Shelfarr, CWA | 1,000 a day without a key | logs, Shelfarr's provider table |
| Open Library | Shelfarr | none published (polite use) | logs, Shelfarr's provider table |

Design points:

- **Passive.** It reads what the services already record and spends no quota. An active probe would use up the
  budget it is watching, and would need Avrana to hold every provider's key.
- **Three signals.** `rate` (429/420, "too many requests", quota, velocity), `auth` (401/403 next to the provider
  name, or "token expired": the shared Hardcover token running out is the likeliest real break) and `down` (5xx,
  timeouts). A bare number never matches: on `avrana` every "429" in seven days of logs was inside a timestamp.
- **Quiet by default.** A new incident mails once through `avrana-alert.py`, reminds every 24 hours while it lasts,
  and reports its recovery. The services' own deliberate throttling (Omnibus engine "Globally throttling getcomics")
  is ignored.
- **No key leaves the host in an alert.** URL query strings and token-looking values are replaced in the one sample
  line. That matters: Omnibus stores failing ComicVine URLs **with the key** in `JobLog` (one row today; see
  `REQUEST-FORKS-PLAN.md`, O-S1).
- **Dry run on `avrana`**, from `/tmp`, nothing installed or written: the last 30 days are clean; over 120 days it
  reports the August ComicVine 502 from Omnibus's job log, with the key redacted.

Owner step to switch it on: install the two units in `~/.config/systemd/user/` and `systemctl --user enable --now
api-caps-monitor.timer`. Rollback: disable the timer and delete `~/.local/state/avrana/api-caps.json`.

## 2. Exact matching: use the ids the acquisition tools already stamp

### The problem

To show "In your library" next to a discovery result, the result must be matched to what is on the server. Film
and TV match exactly (TMDB ids in Jellyfin and Seerr). Books and comics looked like guesswork because the reading
apps' APIs (Calibre-Web's OPDS, Komga) carry no ISBN or ComicVine id.

### The idea

The ids are not missing. They live **one layer down, in the tools that fetched the files**, and they are the
**same id spaces the request tools search with**:

| Kind | What the request tool returns | Where the same id already sits on the server (CONFIRMED on `avrana`) |
|---|---|---|
| Ebooks | Shelfarr `work_id` = `hardcover:<Hardcover book id>` (`app/services/hardcover/api.rb`) | Calibre `metadata.db` `identifiers`: **92 of 92 books** carry `hardcover-id` (and `hardcover-slug`); 39 an ISBN. CWA stamps it on import |
| Audiobooks | Shelfarr `work_id` (Hardcover); editions with ISBN/ASIN (HYPOTHESIS) | Audiobookshelf items carry `asin` and `isbn`; Shelfarr's own `library_items` mirror 293 ABS items with ISBN |
| Comics | Shelfarr `comic_vine:<id>` for graphic novels; Omnibus/ComicVine volume ids | Omnibus `Series.cvId`: **101 of 120** series matched, each with its `folderPath` |

So matching is a **join on ids**, not a guess:

- **Ebooks:** `hardcover:<id>` from Shelfarr → Calibre `identifiers(type='hardcover-id', val=<id>)` → Calibre book
  id → the Calibre-Web title (the OPDS id is the Calibre id). ISBN-13 is the fallback key.
- **Audiobooks:** ASIN or ISBN of a Shelfarr edition → the ABS item with that ASIN or ISBN. Until Shelfarr exposes
  edition ids in search (Shelfarr fork F-3), use Hardcover id → Shelfarr `books.hardcover_id` → `library_items.isbn`.
- **Comics:** ComicVine volume id → Omnibus `Series.cvId` → `folderPath` → the Komga series with the same path.
  Komga's series `url` is the filesystem path; all three tools use one layout (`<Publisher>/<Series> (<Year>)`), so
  the join is on the path relative to each tool's mount (Omnibus `/mylar-library` or `/data`, Komga
  `/avrana_media/avrana_media/comics`).

### The index

A small **catalogue-id index**, built on the host by a timer every 15 minutes, read by Home read-only (like the
operator notice file):

```json
{"built": "…", "ebook": {"hardcover:123": "calibre-web:45", "isbn:978…": "calibre-web:45"},
 "audiobook": {"asin:B0…": "audiobookshelf:li_…", "isbn:978…": "audiobookshelf:li_…"},
 "comic": {"comicvine:156647": "komga:0MEC…"}}
```

- **Sources:** Calibre `metadata.db`, Omnibus `omnibus.db` (`Series`), Shelfarr `production.sqlite3`
  (`library_items`, `books`) opened `mode=ro`; Komga and ABS through Home's existing service accounts (series paths,
  item ASIN/ISBN). No users, no progress, no requests: **catalogue identifiers only**, so it is not member data.
- **Privacy rule kept:** an index hit is shown as "In your library" only after Home's existing permission-checked
  lookup (`adapter.item(principal, id)`) confirms this member can open that title. Calibre-Web and Komga are shared
  views, so that is the library group; Audiobookshelf checks per member. A miss is never shown as "not on the
  server".
- **Confidence:** exact id → "In Books" with the title link. No id → the existing title-and-author comparison may
  say "Might already be in Books", never certain. No match → the request button.
- **Freshness:** a newly imported file appears within one rebuild. A failed rebuild keeps the previous index and is
  reported by Home's health line, not shown to members.
- **Size:** a few thousand entries; under 1 MB.

### Why not fuzzy matching or a store

- Title-and-author matching misfires on omnibus editions, translations, subtitles and series numbering. Ids are what
  CWA and Omnibus already used to fetch the files, so they are right by construction.
- No database is added: the index is a derived file, rebuilt from sources that are already backed up. Deleting it
  loses nothing (POST-M3 store decision P-4 stays open).

### Gaps and the fixes that close them

| Gap | Size today | Fix |
|---|---|---|
| Comics series Omnibus has not matched | 19 of 120 | Omnibus's own matcher; the index skips them (no false "in library") |
| Comic **issues** (not series) | issue-level ids only in Mylar/Omnibus | Series-level first ("Batman (2016) is in Comics"); issue level later from Omnibus's issue table |
| Omnibus cannot write ComicInfo into the comics library | 445+ "Read-only file system" errors a month for one series alone | Intended (the Mylar library is mounted read-only into Omnibus). Leave it; the index reads ids from Omnibus's database instead of from the files |
| Audiobooks without ASIN/ISBN in ABS | not counted yet | ABS's own "match" fills them; count them in the first index build |
| Calibre books without a Hardcover id | 0 of 92 | CWA keeps stamping them; ISBN fallback |

### Effort (HYPOTHESIS)

| Step | Size |
|---|---|
| Index builder script + tests over synthetic copies of the three schemas | 1 day |
| Home reads the index; "In your library" on the book-request page and on search's discovery step | 1 day |
| Komga path join + comic series overlay | 1 day |
| Audiobook join via ASIN/ISBN | half a day |

## Open owner decisions

| # | Decision |
|---|---|
| M-1 | Install the cap monitor timer on `avrana` |
| M-2 | The index builder reads Calibre, Omnibus and Shelfarr databases read-only from the host (proposed), or waits for API routes from the forks (Omnibus O-F4, Shelfarr F-3) |
| M-3 | Whether "Might already be in your library" (likely, not exact) is shown at all, or only exact matches |
