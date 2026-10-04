---
bookstack_page_id: 40
title: "2026-08-13: Documentation Deployment"
shelf: "Avrana Homelab"
book: "Change Log (Archive)"
chapter: ""
created: 2026-08-13 21:28:55
updated: 2026-08-21 00:15:51
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Change log.

# 2026-08-13: Documentation Deployment
# 2026-08-13: Documentation Deployment

## State
All managed containers running/healthy. Docker hardening implemented incrementally, validated after each service.
Compose: `services/media/docker-compose.yml`, `services/homepage/docker-compose.yml`, `deploy/compose/komga.yml`, and individual `services/`. Primary recovery archive: `/home/cody/backups/container-hardening-20260813/compose-and-daemon.tar.gz`.

## Hardening
no-new-privileges; per-workload CPU/RAM/PID limits; per-container log rotation 50m×5; size-limited tmpfs; cap reduction; non-root + read-only rootfs where compatible; writable media/config retained.
Exceptions: CWA root s6/setup helpers + reduced caps (web as UID 1000); CompleteSeries four nginx caps; Komga & Shelfmark need executable `/tmp`; Jellyfin media writable (subtitles); LinuxServer non-root+read-only warning but Radarr/Sonarr/Prowlarr validated.
Networks: `arr-core` (Prowlarr, Radarr, Sonarr); `request-backend` (Seerr, Radarr, Sonarr). Prowlarr and Seerr cannot resolve each other. Published ports unchanged.

## Shelfmark correction
Initial mount narrowing broke post-processing. Shelfmark also needed its destination: mounts now `incoming` + `audiobooks` + `books`, tested writable/readable. The failed "Thrawn" download may need a manual retry.

## Homepage
Running at `http://10.0.0.218:3000`. Native widgets for Seerr, Jellyfin, ABS, Komga, CWA, Radarr, Sonarr, Prowlarr, SABnzbd, Mylar3. Secrets in `services/homepage/widget-secrets.env` (600, gitignored). Dedicated creds: Jellyfin API key "Homepage"; Komga API key "Homepage" (guest user); CWA viewer account "Homepage" (first password leaked once in a tool error, immediately rotated → invalid). Layou: Shelfmark → Automation; Complete Series + Plex removed from Homepage only (services still run).

## Unfinished threads
1. Global Docker daemon log rotation not changed (needs interactive sudo). Per-container equivalent in place.
2. Plex still running (`plexmediaserver.service`); only references removed. Confirm authorization before stopping/disabling.
3. Complete Series still running; only removed from Homepage. Confirm whether it stays.
4. Stale doc: `docs/services-operations.md` said Shelfmark sees only `incoming`; now also `audiobooks` + `books`. **(Fixed 2026-08-13.)**
5. VLAN/DMZ / host firewall restructuring deliberately not applied; Jellyfin uses host networking.
6. No commit created; repo had unrelated dirty changes. Stage only intended Compose/Homepage/docs/health-script changes.
7. Homepage widgets validated at APIs; a final visual browser review of card sizing/order still worthwhile.

Other backups under `/home/cody/backups/`: services-hardening-*, homepage-widgets-*, homepage-mylar-widget-*, homepage-jellyfin-widget-*, homepage-books-widgets-*, homepage-layout-*, remove-plex-references-*.
