---
bookstack_page_id: 9
title: "Upgrade Procedure"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:44
updated: 2026-08-21 00:15:00
last_editor: "Cody"
revisions: 3
tags: []
source_format: markdown
classification: STALE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified STALE. Upgrade steps written for the pre-recovery layout (Compose v1, Kavita).

# Upgrade Procedure
# Upgrade Procedure

Production images are pinned to the exact tested version/digest. To upgrade **one** service:

1. Read its release notes; identify DB migrations.
2. Stop the service; back up its compose file + config/database directory.
3. Pull the chosen release, resolve its immutable digest, update **only** that service's `image`.
4. `docker compose config -q`, recreate the one service, wait for health.
5. Test login, library access, integrations, and one representative workflow.
6. Record the new digest in version control. Restore the pre-upgrade backup if validation fails: **never run an older image against a migrated database.**

Bazarr and legacy Kavita definitions remain tag-based (no tested local image to pin); pin before activation. Locally built Komf can't use a registry digest.
