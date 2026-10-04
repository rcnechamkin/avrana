---
bookstack_page_id: 39
title: "2026-08-13: Initial Deployment"
shelf: "Avrana Homelab"
book: "Change Log (Archive)"
chapter: ""
created: 2026-08-13 21:28:54
updated: 2026-08-21 00:15:51
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Change log.

# 2026-08-13: Initial Deployment
# 2026-08-13: Initial Deployment

Host `avrana`, user `cody` = uid/gid 1000. Media root `/mnt/avrana_media` (7.3 T, `/dev/sdb1`, ~6.2 T free). `/mnt/media` is a stale root-owned rootfs dir: never point anything there. New services live at `/home/cody/avrana/services/<name>/` (gitignored). TZ `America/Los_Angeles`.

## What this session accomplished
All book pipelines wired end-to-end: Shelfmark grabs → audiobooks to Audiobookshelf, ebooks to a real library + Kindle.

1. **Hardcover metadata** wired into Shelfmark (Settings → Metadata Providers → Hardcover). Token from `hardcover.app/account/api`; the `HARDCOVER_API_KEY` field auto-strips a `Bearer ` prefix.
2. **Audiobook pipeline**: Shelfmark → SABnzbd → Audiobookshelf. Direct Download off; grabs route Prowlarr → SAB (usenet, :8080) → Shelfmark import. Mounted `incoming` (+`audiobooks`); `DESTINATION_AUDIOBOOK=/mnt/avrana_media/audiobooks` + `FILE_ORGANIZATION_AUDIOBOOK=organize`. `AA_CONTENT_TYPE_ROUTING` is a red herring for the Prowlarr path. `PROWLARR_USENET_ACTION=move` cleans up SAB after import; don't add SAB-side auto-delete.
3. **Ebook pipeline**: new Calibre-Web-Automated (`v4.0.6`, :8083, LAN). Watches `/books` inbox → imports into `/calibre-library`, deletes inbox copy.
4. **ABS ebook association** proven: epub beside the `.m4b` → "Read" button. No cross-folder matcher (#3062).
5. **Complete Series** (:8085, stateless): scans ABS for incomplete series + missing books.
6. **ABS CORS fix:** 2.36 `allowedOrigins` defaulted empty, blocking Complete Series login (looked like bad creds). Added `http://10.0.0.218:8085` to `allowedOrigins` in `absdatabase.sqlite` + restart. No UI toggle.

Compose files hardened afterward (`cap_drop`, limits, ports bound to `10.0.0.218`, Shelfmark `user: "1000:1000"`).

## Remaining
- CWA Send-to-Kindle (SMTP + `@kindle.com` + Amazon approved senders); change CWA default admin password.
- epub↔audiobook auto-matcher (fuzzy author+title, `[ASIN]` suffix, symlink + ABS scan). Storyteller rejected as overkill.
- Cosmetic: Shelfmark `SABNZBD_CATEGORY` mislabeled "Audiobooks" in `prowlarr_clients.json`.
- Run Complete Series; fill gaps.
- Pre-existing: ABS auto-backups disabled (highest value); Kavita compose points at rootfs; second Audible account not added; Plex→Jellyfin + -arr repair; mylar3 local patch re-apply after upgrades.
