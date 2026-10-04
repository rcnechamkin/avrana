---
bookstack_page_id: 31
title: "Audiobook Pipeline"
shelf: "Avrana Homelab"
book: "Pipelines"
chapter: ""
created: 2026-08-13 21:28:52
updated: 2026-08-13 21:28:52
last_editor: "Cody"
revisions: 1
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/pipelines/audiobook.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-13; exported 2026-10-04. Classified PROMOTE; current information is in `docs/pipelines/audiobook.md`.

# Audiobook Pipeline
# Audiobook Pipeline
**Shelfmark → SABnzbd → Audiobookshelf.**
1. Shelfmark searches via Prowlarr, sends the grab to SABnzbd (usenet, :8080).
2. SAB writes to `/mnt/avrana_media/incoming`.
3. Shelfmark imports → `DESTINATION_AUDIOBOOK=/mnt/avrana_media/audiobooks`, `FILE_ORGANIZATION_AUDIOBOOK=organize`.
4. `PROWLARR_USENET_ACTION=move` cleans up the SAB job after a successful import.
5. Audiobookshelf serves from `/audiobooks`.

Also fed by **Libation** (Audible) writing to `/audiobooks` directly.
Verified: audiobooks land correctly in ABS.
