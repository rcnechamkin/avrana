---
bookstack_page_id: 5
title: "Service and Port Map"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:43
updated: 2026-08-29 04:24:52
last_editor: "Cody"
revisions: 10
tags: []
source_format: markdown
classification: DUPLICATE
destination: "docs/SERVICES.md, deploy/host/cloudflared/config.yml"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified DUPLICATE; current information is in `docs/SERVICES.md, deploy/host/cloudflared/config.yml`. Port map replaced by one generated from the compose files.

# Service and Port Map
# Service and Port Map

| Port | Service | Container | Exposure |
|---|---|---|---|
| 3000 | Homepage | `homepage` | LAN |
| 5055 | Seerr (media requests) | `seerr` | Tunnel + loopback (`request.avrana.net`) |
| 5056 | Shelfarr (book requests) | `shelfarr` | **Tunnel** (`requestabook.avrana.net`) |
| 5057 | Tracearr (Jellyfin analytics) | `tracearr` | LAN only |
| 5058 | Omnibus (comic requests) | `omnibus` | **Tunnel** (`requestacomic.avrana.net`) |
| 6875 | BookStack (this wiki) | `bookstack` | LAN |
| 7878 | Radarr | `radarr` | LAN |
| 8082 | SABnzbd | *bare-metal* | LAN, **login required** (2026-08-28) |
| 8083 | Calibre-Web-Automated | `calibre-web-automated` | LAN |
| 8084 | Shelfmark | `shelfmark` | LAN |
| 8085 | Complete Series | `completeseries` | LAN |
| 8086 | Komf (legacy profile) | `komf` | LAN |
| 8087 | libation-status | `libation-status` | LAN |
| 8090 | mylar3 | *bare-metal* | LAN, **login required** (2026-08-28) |
| 8096 | Jellyfin | `jellyfin` | **Tunnel** (host networking) |
| 8123 | Home Assistant (Kern HQ) | `home-assistant` | LAN only (host networking) |
| 8989 | Sonarr | `sonarr` | LAN |
| 9000 | Authentik (SSO/OIDC) | `authentik-server` | LAN + **Tunnel** (`auth.avrana.net`) |
| 9696 | Prowlarr | `prowlarr` | LAN |
| 13378 | Audiobookshelf | `audiobookshelf` | LAN + **Tunnel** (`listen.avrana.net`) |
| 25600 | Komga | `komga` | **Tunnel** (comics) |
| 10200 | Piper (local TTS) | `wyoming-piper` | loopback only |
| 10300 | Speech-to-Phrase (local STT) | `speech-to-phrase` | loopback only |

*Note: `mylar3` and SABnzbd are bare-metal, not containers — `docker ps | grep mylar` finds
nothing.*

> **Corrected 2026-08-28.** This page previously said mylar3 runs under the systemd **user**
> unit. It does **not**. The live process is the **system** unit `mylar3.service`
> (enabled + active). `~/.config/systemd/user/mylar.service` is enabled but **inactive** and
> points at a stale venv path (`venv/` instead of `.venv/`). Restart with
> `sudo systemctl restart mylar3`, not `systemctl --user`.
| 32400 | Plex (*retiring*) | `plexmediaserver.service` |: |

No published port (private): `bookstack-mariadb`, `authentik-postgresql`, `authentik-worker`.

## Comic storage mounts

| Path | Owner | Notes |
|---|---|---|
| `/mnt/avrana_media/comics` | **Mylar3** (writes) | `destination_dir`, `$Publisher/$Series ($Year)` |
| `/mnt/avrana_media/comics_omnibus/library` | **Omnibus** (writes) | same folder convention |
| `/mnt/avrana_media/comics_merged` | **mergerfs**, read-only | union of the two above; the ONLY tree Komga reads |

Komga's bind mount is `comics_merged -> /avrana_media/avrana_media/comics:ro`, so its library
roots are unchanged from before the union existed. The mount is in `/etc/fstab` with
`x-systemd.before=docker.service`; it must be root-mounted because unprivileged FUSE is blocked
on this host (AppArmor, and `user_allow_other` is commented out in `/etc/fuse.conf`).

Omnibus separately mounts `comics` at `/mylar-library:ro` for "already own this" awareness —
that is independent of the Komga union, and is the source of the recurring
`metadata_writer ... Read-only file system` errors in its log.

> **8240 is free as of 2026-08-28.** The legacy Health API was retired (audit H1); see *Services → Health API*.
