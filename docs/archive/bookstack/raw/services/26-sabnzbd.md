---
bookstack_page_id: 26
title: "SABnzbd"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Video and Requests"
created: 2026-08-13 21:28:50
updated: 2026-08-28 23:35:00
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/sabnzbd.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-28; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/sabnzbd.md`.

# SABnzbd
# SABnzbd: 8082 (LAN, bare-metal)
Usenet downloader (`sabnzbd.service`, not a container). Writes completed downloads to `/mnt/avrana_media/incoming`. Container paths in Shelfmark/*arr must match these host paths exactly (identity mounts) so imports are same-mount renames with no Remote Path Mapping.
