---
bookstack_page_id: 32
title: "Ebook Pipeline"
shelf: "Avrana Homelab"
book: "Pipelines"
chapter: ""
created: 2026-08-13 21:28:52
updated: 2026-08-18 01:09:58
last_editor: "Cody"
revisions: 2
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/pipelines/ebook.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-18; exported 2026-10-04. Classified PROMOTE; current information is in `docs/pipelines/ebook.md`.

# Ebook Pipeline
# Ebook Pipeline
**Shelfmark → Calibre-Web-Automated → (Kindle).**
1. Shelfmark writes epubs to `/mnt/avrana_media/books` (transient inbox).
2. CWA watches that inbox, imports into `/mnt/avrana_media/calibre-library`, deletes the inbox copy.
3. CWA's Send-to-Kindle emails the book to your `@kindle.com` (SMTP setup pending).

Verified: auto-import works.

## Library-wide epub sweep (2026-08-17)

Every ABS title was checked against Shelfmark for a matching epub, then grabbed.

| Outcome | Count |
|---|---|
| In ABS + CWA (Read button live) | 66 |
| In CWA only (no confident audiobook match) | 41 |
| No epub found | 164 |
| Other format only (mobi/azw3) | 10 |
| Unidentified by Hardcover | 10 |
| Had a PDF already | 2 |

105 epubs were queued through Shelfmark. Calibre went 2 -> 122 books, then down to **104**
after duplicate and junk cleanup.

### Release counts are meaningless without validation

Searching *Thrawn: Treason* returns ~99 releases, and essentially none are the book -- they are
keyword hits on "Treason" by Orson Scott Card, Vince Flynn, Tom Clancy. **Never trust a release
count as an availability signal.** Every candidate must be validated against author AND title.

**Matching must be bidirectional.** A one-directional check (does the release contain the wanted
title?) accepts *God Emperor of Dune* for *Dune*, and *The Sandman: Book of Dreams* for
*The Sandman*, because a short title is fully contained by a longer, different one. The working
rule is recall >= 0.6 AND precision >= 0.6, where precision is measured after stripping the
author, bracketed series/version tags and format words from the release name.

Even so, ~12 study guides and summaries got through ("Summary Of Demon Copperhead",
BookRags "Lesson Plan" titles, a SparkNotes *Brothers Karamazov*) because "Summary" is only one
extra token. Those were removed by hand.

### Two traps that cost real time

**metadata.db is in WAL mode.** Copying `metadata.db` alone gives a stale snapshot -- it reported
1 book when the library really had 122, which looked exactly like a failed CWA import. Always
copy `metadata.db`, `metadata.db-wal` and `metadata.db-shm` together, or query through CWA.

**ABS reports container paths.** `/api/items` returns `path` as `/audiobooks/...`, not
`/mnt/avrana_media/audiobooks/...`. Any host-side file check must translate the prefix first,
otherwise every lookup silently finds nothing.

### Deleting a Calibre copy does NOT break ABS

The epubs in audiobook folders are **hard links** (`links=2`). Removing the Calibre book drops
the link count to 1; the audiobook-folder file survives and the Read button keeps working.
Confirmed after 18 duplicate deletions: still 66/66 attached in ABS.
