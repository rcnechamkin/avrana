---
bookstack_page_id: 4
title: "Compose Layout and Conventions"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:42
updated: 2026-08-21 00:15:45
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: DUPLICATE
destination: "BOOTSTRAP.md, docs/DEPLOYMENT.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified DUPLICATE; current information is in `BOOTSTRAP.md, docs/DEPLOYMENT.md`. Project names, profiles and Compose version are now recorded from the live host.

# Compose Layout and Conventions
# Compose Layout and Conventions

New services follow a house pattern. Learn it before adding one.

## Where things live (`/home/cody/avrana/`)
- `services/<name>/docker-compose.yml`: most services (one project each).
- `services/media/docker-compose.yml`: the `*arr` stack + Jellyfin + Seerr.
- `deploy/compose/komga.yml`, `deploy/compose/komf.yml`: Komga / Komf.
- `deploy/homepage/config/`: Homepage's live config (services.yaml, widgets.yaml, …).

## Git hygiene
- **Only `docker-compose.yml` files are versioned.** `.gitignore` ignores `services/*/*` with `!services/*/docker-compose.yml`; per-service `./config`, `./mariadb`, `.env` are never committed.
- **Secrets** live in gitignored `.env` / `*.env` files (mode 600). Compose interpolates `${VAR}` from them. Never inline secrets in a committed compose.

## Conventions
- **Pin image versions deliberately** (e.g. CWA `v4.0.6`, Shelfmark `1.3.6`, BookStack `26.05.3`). Never `:latest`; bump on purpose.
- **PUID/PGID = 1000, TZ = America/Los_Angeles** on LinuxServer-style images.
- **Hardening baseline** on every container: see *Docker Hardening & Networking*.
- **Bind published ports to `10.0.0.218`**, not `0.0.0.0`.
