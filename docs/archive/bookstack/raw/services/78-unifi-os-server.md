---
bookstack_page_id: 78
title: "UniFi OS Server"
shelf: "Avrana Homelab"
book: "Services"
chapter: ""
created: 2026-08-28 23:36:34
updated: 2026-08-28 23:36:34
last_editor: "Cody"
revisions: 1
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/unifi-os-server.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-28; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/unifi-os-server.md`. UniFi is in no backup; see BOOTSTRAP.md.

# UniFi OS Server
# UniFi OS Server

Controller for Avrana's UniFi hardware. **Deployed 2026-08-28.** LAN-only, deliberately.

| | |
|---|---|
| **Management URL** | **`https://10.0.0.218:11443`** — *not* 443, *not* 8443 |
| Version | UniFi OS Server **5.1.37** (released 2026-08-20) |
| Service | `uosserver.service` — **enabled + active**, starts at boot |
| Runtime | **rootless Podman** as system user `uosserver` (uid 1001), ~18 processes |
| Exposure | **LAN only.** Not on the tunnel, no public DNS, no Caddy entry, no port-forward |

## Why the URL is :11443 and not :443

UniFi OS Server runs **rootless**, and rootless Podman **cannot bind ports below 1024**. It
therefore falls back to `11443`. Nothing is listening on 443 at all on this host. Ubiquiti's
generic "browse to `https://<ip>`" instruction lands on nothing here.

The installer's `--web-port` flag only accepts **1024–65535**, so 443 cannot be forced through it
either. This is inherent to the supported rootless install, not a misconfiguration.

## This replaced a Dockerised attempt — do not recreate it

An earlier, unfinished deployment used `lscr.io/linuxserver/unifi-network-application` 10.6.101
with MongoDB 7.0 in Compose at `services/unifi/`. **It was removed entirely on 2026-08-28**:
containers, the `unifi_unifi` network, one anonymous Mongo volume, both images, the repo directory
and its Mongo data. Verified safe first — **0 devices adopted**, one admin account, nothing
configured.

- **Do not** recreate the LinuxServer container. UniFi OS Server is the current, supported product.
- **Do not** install the legacy `unifi` APT package.
- **Do not** manage MongoDB by hand. UOS Server owns its own database inside Podman.
- The old `unifi_stat` / `unifi_audit` Mongo authentication problem is **irrelevant now** and
  should not be carried forward as active guidance.

## Ports

`uosserver` binds these on **all interfaces** (`0.0.0.0`/`*`), which **differs from the house
convention** of binding to `10.0.0.218`. Compose-style per-port binding is not available here; the
correct control is a host firewall rule, not fighting the installer.

| Port | Proto | Purpose |
|---|---|---|
| **11443** | TCP | Management UI |
| **8080** | TCP | **Device inform / adoption** — the reason SABnzbd moved |
| 3478 | UDP | STUN |
| 10001 | UDP | Device discovery |
| 6789 | TCP | Throughput test |
| 8880 / 8881 / 8882 / 8444 / 9543 / 28082 / 5671 / 18555 | TCP | Internal UniFi OS services |

**UDP 1900 (L2 broadcast discovery) is already held** by a DLNA service (Plex/Jellyfin). This
affects only broadcast "make/model" discovery; adoption itself uses UDP 10001 + TCP 8080 and is
unaffected.

## The SABnzbd port move

UniFi OS Server requires TCP 8080 and its standard ports are not meant to be customised. SABnzbd
owned 8080, so **SABnzbd moved to `:8082`** instead.

SABnzbd is **bare metal** (`sabnzbd.service`), not a container, so there was no port mapping to
edit — the change is in `~/.sabnzbd/sabnzbd.ini`. Re-pointed in Radarr, Sonarr, Prowlarr,
Shelfmark's `SABNZBD_URL` and Homepage. The API key was untouched, and SAB re-exec'd in place with
its queue intact. See *SABnzbd* and *Service and Port Map*.

## Operating it

```bash
sudo systemctl status uosserver
sudo systemctl restart uosserver
sudo journalctl -u uosserver -e
```

Prerequisites installed for it: `podman` (4.9.3), `slirp4netns` (1.2.1), `uidmap`. Both meet
Ubiquiti's floors (podman >= 4.9.3, slirp4netns >= 1.2).

## Backup and updates — GAP

**UniFi OS Server is NOT in the nightly backup.** Its state lives in `/var/lib/uosserver` (root
owned) and nothing captures it. Until that is closed, treat the controller as rebuildable-but-not-
restorable: a UniFi *site* backup exported from the UI is currently the only recovery artifact.

Updates are done by re-running a newer official installer, **not** by `apt` and not by pulling an
image. Verify any installer against Ubiquiti's published SHA-256 before running it — the 5.1.37
build was verified this way:

```bash
curl -s "https://fw-update.ui.com/api/firmware-latest?filter=eq~~product~~unifi-os-server"
# match sha256_checksum for platform linux-x64 against sha256sum of the download
```

## Next step: adopting the U7 Pro

**Not yet done — deliberately stopped here.** The controller is ready and waiting.

1. Open **`https://10.0.0.218:11443`** and complete first-run setup (accept the self-signed cert;
   create the local admin — a Ubiquiti SSO account is optional and not required for LAN use).
2. Launch the **UniFi Network** application from inside UniFi OS.
3. Power the U7 Pro on the same L2 network as the host. It should appear under **Devices** as
   *Pending Adoption* (discovery via UDP 10001, inform via TCP 8080).
4. Adopt it, then let it provision and take the firmware update.
5. If it does not appear, set the inform URL manually — SSH to the AP and
   `set-inform http://10.0.0.218:8080/inform`. Port **8080** is correct and is now UniFi's, not
   SABnzbd's.

## Cleanup note

The verified installer remains at `/mnt/avrana_media/tmp-uos/unifi-os-server-5.1.37-linux-x64.bin`
(750 MB). Safe to delete once adoption is confirmed.
