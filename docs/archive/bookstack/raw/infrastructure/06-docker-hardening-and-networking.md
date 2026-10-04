---
bookstack_page_id: 6
title: "Docker Hardening and Networking"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:43
updated: 2026-08-29 03:35:42
last_editor: "Cody"
revisions: 7
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified ARCHIVE. Hardening conventions as designed in August; not re-audited per service.

# Docker Hardening and Networking
# Docker Hardening and Networking

Applied incrementally on **2026-08-13** and validated per service.

## Baseline (all managed containers)
- `no-new-privileges`, TTY/stdin disabled, capability reduction.
- Workload-specific **CPU / memory / PID** limits.
- Per-container **json-file log rotation: 50 MiB × 5**.
- Size-limited tmpfs (`nosuid,nodev`; `noexec` where compatible).
- Read-only root fs and non-root operation where compatible; only required writable data paths retained.

## Intentional exceptions (do **not** "fix")
- **CWA** keeps root s6/Calibre setup helpers + a reduced cap set; web process runs as UID 1000.
- **BookStack** keeps `NET_BIND_SERVICE` (its nginx binds :80 in-container).
- **CompleteSeries** keeps CHOWN, NET_BIND_SERVICE, SETUID, SETGID for nginx.
- **Komga** and **Shelfmark** need an **executable** `/tmp` (SQLite JNI / Chromium+Selenium). CWA may execute Calibre conversion artifacts.
- **Jellyfin** adds render group 993 for HW accel. Its media mounts became **read-only on
  2026-08-16** (see *Media mount scoping*). That is safe only while nothing writes back: no
  subtitle-fetcher plugin is installed, `SaveLocalMetadata` is false, and trickplay extraction
  is off. **Installing a subtitle fetcher means making these writable again.**
- **Homepage** adds SETUID/SETGID (entrypoint drops to app user) and reaches Docker only via a **read-only, GET-only socket proxy**.
- **Radarr/Sonarr/Prowlarr** run non-root + read-only despite LinuxServer's warning; validated through migration/endpoint/restart tests.

## Network segmentation (published ports unchanged)
- `arr-core`: Prowlarr, Radarr, Sonarr.
- `request-backend`: Seerr, Radarr, Sonarr.
- Prowlarr and Seerr **cannot** resolve each other; each reaches its required Radarr/Sonarr.

## Media mount scoping (2026-08-16)

`radarr`, `sonarr` and `jellyfin` each bind-mounted the **array root** `/mnt/avrana_media`
read-write as **uid 1000, the same uid that owns `/mnt/avrana_media/.backups`**. File modes gave
zero protection (even the 0600 `bookstack.env`), so all three could read Authentik's full
`pg_dump` (every password hash and OIDC client secret), BookStack's `APP_KEY` and
`services/*/secrets`, and being rw could delete every backup. Komga could read them.

The fix differs per service, because the \*arr have a constraint the readers do not:

- **radarr / sonarr keep the single `/mnt/avrana_media:/data` mount** plus an empty **read-only
  tmpfs mounted over `/data/.backups`**, which hides it and cannot be unmounted (CAP_SYS_ADMIN is
  dropped).
- **jellyfin and komga were properly narrowed, read-only**: jellyfin to `/data/movies` and
  `/data/tv`, komga to the comics tree. **Destination paths are unchanged**, so no library records
  broke and no app needed reconfiguring.

> **Do not "simplify" this by narrowing `/data` to subdirs for the \*arr.** `link()` returns
> **EXDEV across two separate bind mounts even of the same filesystem** (the kernel compares
> mounts, not just superblocks). Verified empirically. Narrowing would silently downgrade every
> import from a hardlink to a full file copy. The single mount is load-bearing.

Verify with:

```bash
docker exec radarr sh -c 'ls -A /data/.backups'      # must be empty
docker exec jellyfin sh -c 'ls /data'                # must be movies + tv only
```

## Known gap
Global Docker daemon log rotation is **not** se: `/etc/docker/daemon.json` needs interactive sudo. Per-container rotation covers it for now.

## Address-pool exhaustion — measured 2026-08-28

**Docker is three networks from a collision with libvirt.** The `172.16–31` default pool is
**fully exhausted**: all 15 `/16` slots are allocated (`172.17` the default bridge,
`172.18`–`172.31` service networks). Docker has moved on to `192.168.0.0/16` in `/20` chunks,
where **13 of 16 slots are used**.

Of the three still free:

| Free `/20` | Safe? |
|---|---|
| `192.168.112.0/20` | ❌ **contains `192.168.122.0/24` — libvirt's `virbr0`** |
| `192.168.192.0/20` | ok |
| `192.168.240.0/20` | ok |

So the next `docker compose up` for a new service has a **1-in-3 chance of allocating a subnet
overlapping a running subsystem**, and the two after that exhaust the pool. This supersedes the
earlier "near the default address-pool limit" note on the roadmap: it is a live collision risk,
not a capacity nicety.

**Proposal, written and reviewed but NOT applied:** `deploy/docker/daemon.json.proposed` adds
`10.210.0.0/16` and `10.211.0.0/16` at `size: 24` — 512 networks, verified free against the LAN
(`10.0.0.218/24`), libvirt, every existing Docker subnet, and the absence of any VPN interface.
UniFi OS Server cannot collide: rootless Podman on **slirp4netns** is userspace networking and
allocates no host bridge subnet.

`default-address-pools` governs **new** networks only, so nothing is renumbered and no compose
file changes. The same file also adds the `50m × 5` log rotation the per-container standard
already specifies but `daemon.json` does not set globally — it currently contains **only**
`data-root`.

Not applied because it needs root and restarting `docker.service` restarts every container.
Exact apply/rollback commands are in `deploy/docker/README.md`. Best done in the same window as
the pending reboot.

## New service? Use the checklist

`docs/service-deployment-checklist.md` turns this page's baseline into a gate rather than a
one-time project. The four services added after the 2026-08-13 hardening pass — `tracearr`,
`shelfarr`, `beszel`, `home-assistant` — all run as **root** with no documented exception,
because nothing required them to pass through it.

### Revalidated and scripted, 2026-08-29 — still not applied

Ranges re-checked against the **live routing table**, not the earlier snapshot. Confirmed there
is **no VPN on this host**: no `tun*`/`wg*`/`tailscale*`/`zt*`/`ppp*`/`ipsec*` interface, no
`/etc/openvpn`, `/etc/wireguard` or `/etc/ppp/peers`, and no VPN-pushed routes. The default
gateway is `10.0.0.1` (answers HTTPS 200, consistent with the FortiGate). Its configuration
cannot be read from here, so the proposal was additionally checked against FortiGate's
**documented defaults**.

| Checked against | Overlap with 10.210/10.211? |
|---|---|
| home LAN `10.0.0.0/24` | none |
| libvirt `virbr0` `192.168.122.0/24` | none |
| FortiGate default SSL-VPN pool `10.212.134.0/24` | none |
| FortiGate default internal `192.168.1.0/24` | none |
| all 15 Docker `172.x/16` | none |
| all 13 Docker `192.168.x/20` | none |
| loopback `127.0.0.0/8` | none |

**`deploy/docker/apply-address-pools.sh`** applies it safely:

1. Records the exact pre-change running-container set.
2. Writes a timestamped rollback copy of `daemon.json`.
3. **Merges** with `python json` rather than overwriting — `data-root` survives, unrelated keys
   survive, and re-running does not duplicate pools (both verified against a copy).
4. Runs `dockerd --validate` **before** touching the service; restores and aborts if invalid.
5. Restarts docker, then waits up to 180 s for that exact container set to return `running` and
   not `unhealthy`.
6. **Automatically restores the rollback copy and restarts docker** if any container fails to
   come back.

```bash
sudo bash /home/cody/avrana/deploy/docker/apply-address-pools.sh
```

Still best done in the same window as the pending reboot, since it restarts every container.
