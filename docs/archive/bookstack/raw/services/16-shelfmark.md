---
bookstack_page_id: 16
title: "Shelfmark"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Books and Audio"
created: 2026-08-13 21:28:46
updated: 2026-08-21 00:15:01
last_editor: "Cody"
revisions: 3
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/shelfmark.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/shelfmark.md`.

# Shelfmark
# Shelfmark: 8084 (LAN)
Manual book/audiobook search + request frontend (not a library manager). Container `shelfmark`, pinned `1.3.6`, runs `user: "1000:1000"`.
- Routes **Prowlarr → SABnzbd (usenet) → Shelfmark import**. Direct Download is off.
- **Mounts (scoped, not the whole array):** `incoming` + `audiobooks` + `books`. Narrowing to `incoming` alone breaks post-processing → imports fail "path not accessible".
- `downloads.json`: `DESTINATION_AUDIOBOOK=/mnt/avrana_media/audiobooks` + `FILE_ORGANIZATION_AUDIOBOOK=organize`. **`AA_CONTENT_TYPE_ROUTING` is a red herring** for the Prowlarr path.
- SAB cleanup via `PROWLARR_USENET_ACTION=move`; don't add SAB-side auto-delete (races the importer).
- **Metadata:** Hardcover provider wired in; the `HARDCOVER_API_KEY` field auto-strips a `Bearer ` prefix.
