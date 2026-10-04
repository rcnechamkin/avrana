---
bookstack_page_id: 2
title: "Host & Access"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:42
updated: 2026-08-29 04:24:51
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: DUPLICATE
destination: "BOOTSTRAP.md, docs/ARCHITECTURE.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified DUPLICATE; current information is in `BOOTSTRAP.md, docs/ARCHITECTURE.md`. Host facts re-verified 2026-10-04; page still lists the retired health API.

# Host & Access
# Host & Access

- **Host:** `avrana`: primary user `cody` = **uid/gid 1000**. Groups include `docker`, `sudo`, `libvirt`.
- **LAN IP:** `10.0.0.218`. Most containers bind to this address explicitly — but **not all**: SABnzbd (`0.0.0.0:8082`), mylar3 (`0.0.0.0:8090`), Jellyfin and Home Assistant listen on every interface. Do not assume an explicit bind.
- **Timezone:** `America/Los_Angeles`.
- **Total RAM:** ~31 GB (~27 GB free at last check).

## Exposure model
- **Public via Cloudflare Tunnel:** Jellyfin, Seerr, Komga, Audiobookshelf, Authentik, Calibre-Web, the Audible Connector and the Avrana Portal. See *Cloudflare and External Access*. *(The Health API was retired 2026-08-28.)*
- **LAN-only (`10.0.0.218` bindings):** Radarr, Sonarr, Prowlarr, Audiobookshelf, Shelfmark, CWA, Complete Series, **BookStack**, Homepage.
- **Bare-metal (not containers):** SABnzbd (`sabnzbd.service`, **:8082** — this page previously said :8080, which was wrong) and mylar3 (`services/mylar3/Mylar.py`, :8090). ~~Health API (uvicorn, :8240)~~ retired 2026-08-28. Plex is being retired.
- ✅ **Both bare-metal services now require a login** (2026-08-28, audit C1/C2 closed): SABnzbd has a username and password, mylar3 runs `authentication = 2`. Anonymous requests redirect to each app's login page. Their **API keys were not changed**, so every integration still authenticates as before. Credentials: `services/bare-metal-auth.env` (mode 600, gitignored).
- ⚠️ The host firewall is **not** filtering — `/etc/ufw/ufw.conf` has `ENABLED=no` even though the unit reads `active`. See *Host firewall (ufw) — inventory and proposal*.

> ⚠️ **Never** point anything at `/mnt/media`: it is a stale root-owned directory on the ~57 GB rootfs, **not** the media array. The array is `/mnt/avrana_media`.
