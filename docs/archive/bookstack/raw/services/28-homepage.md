---
bookstack_page_id: 28
title: "Homepage"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Platform"
created: 2026-08-13 21:28:51
updated: 2026-08-21 00:15:06
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/homepage.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/homepage.md`.

# Homepage
# Homepage: 3000 (LAN)
Dashboard. Container `homepage` + `homepage-dockerproxy` (read-only, GET-only Docker socket proxy). Config in `deploy/homepage/config/`.
- Groups: **Media · Books & Comics · Automation · Server**. Native widgets for Seerr, Jellyfin, ABS, Komga, CWA, Radarr, Sonarr, Prowlarr, SABnzbd, Mylar3.
- **Libation** uses a `customapi` widget (via libation-status:8087) under *Automation*. **BookStack** is a plain tile (gethomepage has no native bookstack widget). The legacy **Health API tile was removed** 2026-08-13 (the service still runs).
- Widget secrets: `services/homepage/widget-secrets.env` (mode 600, gitignored). Dedicated read-only creds per service (Jellyfin/Komga API keys, CWA viewer account).
