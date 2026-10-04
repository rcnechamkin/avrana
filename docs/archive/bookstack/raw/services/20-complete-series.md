---
bookstack_page_id: 20
title: "Complete Series"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Books and Audio"
created: 2026-08-13 21:28:48
updated: 2026-08-21 00:15:03
last_editor: "Cody"
revisions: 3
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/completeseries.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/completeseries.md`.

# Complete Series
# Complete Series: 8085 (LAN)
Stateless tool that scans Audiobookshelf for **incomplete series + missing books**. Container `completeseries`.
- Login needs the ABS `allowedOrigins` CORS fix (add `http://10.0.0.218:8085`): otherwise it looks like bad creds. See the ABS page.
- Open decision: keep it deployed? (It was removed from Homepage but still runs.)
