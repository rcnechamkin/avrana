---
bookstack_page_id: 33
title: "Ebook and Audiobook Matcher"
shelf: "Avrana Homelab"
book: "Pipelines"
chapter: ""
created: 2026-08-13 21:28:52
updated: 2026-08-21 00:15:48
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/pipelines/ebook-audiobook-matcher.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/pipelines/ebook-audiobook-matcher.md`.

# Ebook and Audiobook Matcher
# Ebook and Audiobook Matcher

`scripts/epub_audiobook_matcher.py` associates an owned EPUB with its audiobook so ABS shows a
**Read** button (ABS has no cross-folder matcher: upstream #3062). It **hard-links** the EPUB
from the Calibre library (`/mnt/avrana_media/calibre-library`) into the matching audiobook folder
(`/mnt/avrana_media/audiobooks`); both are on the same disk, so the link shares the canonical
file's inode: no copy, and the canonical is never moved or modified.

**Matching (most-authoritative first, only these auto-link):** shared identifier (ISBN/ASIN) →
exact normalized author+title → same-author + title **prefix** (covers the ": A Novel" / ": Book
N" / series suffix on audiobook titles). Fuzzy title, multiple candidates, or author-only become
**REVIEW** items: never auto-linked. EPUB-only titles (no audiobook) are ignored. Idempotent
(skips a folder that already has an .epub).

**Run:** `python3 scripts/epub_audiobook_matcher.py` (dry-run) → `--apply` to create links
(`--json` for machine output). 9 tests in `scripts/test_epub_audiobook_matcher.py`.

**ABS requirements for the Read button to appear** (both needed):
1. Library setting **`audiobooksOnly = false`**: it was `true`, silently blocking ALL ebook
   attachment (even the older manual Leviathan Wakes association). Now off.
2. A **per-item rescan** after the epub lands (`POST /api/items/{id}/scan`): a library-wide scan
   does not re-probe files in an already-known item folder. New audiobooks that arrive with an
   epub already present attach on first scan; the per-item rescan is only for retrofits.

**Applied 2026-08-15:** Cibola Burn + Anxious People linked and showing Read buttons; also fixed
the previously-broken manual Leviathan Wakes. Currently a manual script (2 EPUBs in the library
today); it will match more as the ebook library grows. Not a Whispersync clone.
