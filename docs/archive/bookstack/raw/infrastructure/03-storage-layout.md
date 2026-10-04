---
bookstack_page_id: 3
title: "Storage Layout"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:42
updated: 2026-08-28 23:35:00
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: DUPLICATE
destination: "docs/STORAGE.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-28; exported 2026-10-04. Classified DUPLICATE; current information is in `docs/STORAGE.md`. Paths current; capacity figures and Kavita reference are old.

# Storage Layout
# Storage Layout

Large media lives on the array; application config/SQLite state lives under `/home/cody/avrana/services` (and some legacy paths under `/home/cody/docker`).

- **Array:** `/mnt/avrana_media`: 7.3 TB, `/dev/sdb1` (ext4), **~4.5 TB free** (2.5 TB used,
  measured 2026-08-28). The disk is a **spinning drive in a USB 3.0 enclosure** (`uas` driver),
  not an internal disk — see *Backups and Recovery* for why that matters to recovery.
- **Internal SSD:** `/dev/sda`, 119 GB Samsung SATA. `sda3` is a 116 GB LVM PV but the only
  logical volume is **58.1 GB**, so roughly **58 GB of the SSD is unallocated** while `/` runs
  at 59%. Extending it is on the roadmap.
- **Rootfs trap:** `/mnt/media` is a stale root-owned dir on the small rootfs. Do not use it. Kavita's legacy compose historically pointed there.

## Subtrees & who writes them
| Path | Purpose | Writer → consumer |
|---|---|---|
| `incoming/` | SABnzbd completed downloads | SAB → Radarr/Sonarr/Shelfmark import |
| `movies/`, `tv/` | Video libraries | Radarr/Sonarr atomic import → Jellyfin |
| `books/` | **Transient** ebook inbox | Shelfmark writes → CWA imports & deletes |
| `calibre-library/` | Durable ebook library (`metadata.db`) | CWA owns |
| `audiobooks/` | Audiobook library | Libation / Shelfmark → Audiobookshelf |
| (comics/manga) | Comics | mylar3 → Komga (read-only mount) |

Komga sees `/mnt/avrana_media` **read-only** at the legacy container path its library records expect.
