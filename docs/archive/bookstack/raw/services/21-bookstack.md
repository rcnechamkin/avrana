---
bookstack_page_id: 21
title: "BookStack"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Books and Audio"
created: 2026-08-13 21:28:48
updated: 2026-08-21 00:15:03
last_editor: "Cody"
revisions: 3
tags: []
source_format: markdown
classification: DUPLICATE
destination: "docs/archive/bookstack/README.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified DUPLICATE; current information is in `docs/archive/bookstack/README.md`. BookStack itself is being retired.

# BookStack
# BookStack: 6875 (LAN)
This wiki. Containers `bookstack` (LinuxServer, `26.05.3`) + private `bookstack-mariadb` (`11.8.8`, no published port).
- Secrets (DB passwords, `APP_KEY`, `APP_URL`) in gitignored `services/bookstack/.env`. API token in `services/bookstack/.bookstack-api.env`.
- **Backup = `./mariadb` + `./config` + `APP_KEY` together** (see *Backups & Recovery*).
- To expose later: set `APP_URL` to the public https hostname and recreate the container.
