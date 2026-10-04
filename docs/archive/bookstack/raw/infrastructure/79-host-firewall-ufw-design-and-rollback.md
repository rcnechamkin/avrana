---
bookstack_page_id: 79
title: "Host firewall (ufw) — design and rollback"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-29 04:24:52
updated: 2026-08-29 04:42:14
last_editor: "Cody"
revisions: 2
tags: []
source_format: markdown
classification: DUPLICATE
destination: "deploy/ufw/README.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified DUPLICATE; current information is in `deploy/ufw/README.md`. The firewall is staged and has never been applied.

# Host firewall (ufw) — design and rollback
# Host firewall (ufw + DOCKER-USER) — design and rollback

> **Status: DESIGNED 2026-08-28, NOT APPLIED.** ufw is still inert and `DOCKER-USER` is
> still empty. Everything below lives in the repo under `deploy/ufw/` (commit `4db6c17`).
> Applying needs interactive sudo and Cody's sign-off.

Nothing here has been enabled. `ufw` is still inert (`/etc/ufw/ufw.conf` → `ENABLED=no`)
and `DOCKER-USER` is still empty. Applying needs interactive sudo and Cody's sign-off.

## Why this is two layers, not one

`ufw` filters the **INPUT** chain. Docker-published ports never reach INPUT: Docker DNATs
them in `nat/PREROUTING` and accepts them through its own chains in **FORWARD**. So a ufw
allow-list — however careful — has *no effect* on the ~22 container services on this host.
`/etc/docker/daemon.json` sets only `data-root`; there is no `"iptables": false`, so this
is stock behaviour.

| Layer | Chain | Covers | File |
|---|---|---|---|
| 1 | INPUT (ufw) | bare-metal host services | `rules-input.sh` |
| 2 | FORWARD (DOCKER-USER) | every Docker-published port | `rules-docker-user.sh` |

Both default to the trusted home subnet **`10.0.0.0/24`** (br0) rather than any-source.

## Layer 2 uses interfaces, not subnets — deliberately

The pending `deploy/docker/apply-address-pools.sh` renumbers **every** Docker bridge into
`10.210.0.0/16` and `10.211.0.0/16`. Rules keyed on today's bridge subnets
(`172.18…172.31`, `192.168.x`) would silently stop matching the moment it runs.
`rules-docker-user.sh` therefore matches on the **ingress interface** `br0`, which no
renumbering touches:

```
-A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
-A DOCKER-USER ! -i br0 -j RETURN          # container↔container, docker0, libvirt, loopback
-A DOCKER-USER -i br0 -s 10.0.0.0/24 -j RETURN
-A DOCKER-USER -i br0 -j DROP              # other VLANs / guest net / forwarded foreign sources
-A DOCKER-USER -j RETURN
```

Docker rebuilds its chains on every daemon start, discarding `DOCKER-USER`. That is what
`avrana-docker-user-rules.service` is for — `PartOf=docker.service`, so it re-applies on
every restart, including the one the address-pool migration performs.

## Resulting INPUT policy

Default **deny incoming**, **allow outgoing**. Allow, all from `10.0.0.0/24`:

| Port | Proto | Service |
|---|---|---|
| 22 | tcp | SSH |
| 8082 | tcp | SABnzbd (login required) |
| 8090 | tcp | Mylar3 (login required) |
| 8096 | tcp | Jellyfin |
| 8123 | tcp | Home Assistant / Kern HQ |
| 7359 | udp | Jellyfin client discovery |
| 1900 | udp | SSDP/DLNA |
| 5353 | udp | mDNS |
| 8080, 8444, 8880, 8881, 8882, 6789, 9543, 11443, 28082, 18555, 5671 | tcp | UniFi OS Server |
| 3478, 10001, 5514 | udp | UniFi OS Server |

**Cloudflare needs no inbound rule.** `cloudflared` dials *outbound*; `allow outgoing`
keeps every tunnelled hostname working behind a default-deny.

### Deliberately closed
- **`80/tcp` — host nginx.** Not UniFi. Its only enabled site, `homeassistant`, proxies to
  `http://192.168.122.108:8123`, a libvirt VM that no longer exists (`virsh list --all` is
  empty); it answers **502**. This is the "dead nginx site" the 2026-08-20 audit flagged.
  Home Assistant is a container on host networking at `:8123`, which *is* allowed.
  Recommend `systemctl disable --now nginx` separately.
- **Plex `32400/tcp`, `32410-32414/udp`** — untouched by instruction. Plex *will* lose LAN
  reach when ufw is enabled. Uncomment the rule in `rules-input.sh` if it must keep serving.
- **Loopback-only** (`2376`, `10200`, `10300`, `20241`, `20243`, `11002`, `11084`, `18554`,
  `32401`, `32600`, `36605`, `45355`) — unreachable off-host by binding. No rule needed.
- **Retired** — `8240` (Health API) and `5005` (whisper-flask) no longer listen.

## Ports whose purpose is still uncertain
Attributed to UniFi OS Server by co-location with the `uosserver`/`unifi-core`/
`unifi-directory`/`mongod` processes, but **not individually confirmed to a PID** — reading
another user's socket owners needs root:
`5671` (AMQP), `6789`, `9543`, `11443`, `28082`, `18555` (probably Protect RTSP) tcp;
`5514` (probably syslog), `10003` udp. `28082` and `11443` answer HTTP 400, consistent with
a TLS-expecting service. **`udp/1901`** and **`udp/4002`** are unattributed and are *not*
opened. Dynamic high UDP ports are ephemeral and not opened. If AP adoption or Protect
misbehaves after enabling, these are the first rules to inspect.

## Rollback — three independent nets

1. **Immediate verification.** `verify-firewall.sh` runs right after enabling; any failure
   rolls back at once. It probes via `10.0.0.218`, never loopback — a localhost probe would
   pass even with a completely broken firewall.
2. **Deadman.** `apply-firewall.sh` arms a transient timer *before touching anything* that
   restores the snapshot after `DEADMAN_MIN` (default 15) minutes unless
   `confirm-firewall.sh` is run from a **new SSH session**. This catches the failure
   verification cannot see: the host is fine, but *your* access is gone.
   The timer is armed with **`AccuracySec=1s`** — systemd's default of `1min` lets a timer
   fire up to a minute late, which was measured and is unacceptable slop here. The script
   also asserts the timer is genuinely active and aborts *before any change* if not.
3. **Snapshot.** `snapshot-firewall.sh` writes a verbatim `iptables-save`, `ip6tables-save`,
   `nft list ruleset`, `/etc/ufw`, `/etc/default/ufw` and the fleet state to
   `/home/cody/backups/firewall-<stamp>/`. Restorable by hand at the console:
   `sudo bash rollback-firewall.sh /home/cody/backups/firewall-<stamp>`

## What was actually tested (no root available this session)
| Test | Result |
|---|---|
| `verify-firewall.sh` against the live known-good host | **PASS — 26/26 checks** |
| Negative: simulated total lockout | **exit 1, 23/26 failed** |
| Negative: exactly one service blocked | **exit 1, 1/26 failed** |
| Deadman fires with `AccuracySec=1s` | **fired at 6s for a 5s timer** |
| Deadman does not fire after disarm | **correctly silent** |
| Preflight refuses while the migration is pending | **guard fires correctly** |
| `bash -n` on all 7 scripts, `systemd-analyze verify` on the unit | **clean** |

Not testable without root: the actual `iptables`/`ufw` mutations and a live rollback.

## Order of operations
1. **Let the 03:30 address-pool migration finish first.** `apply-firewall.sh` *refuses* to
   run before it (override: `ALLOW_PREMIGRATION=1`). Stacking two Docker-restarting changes
   makes any failure ambiguous.
2. Keep a second SSH session open.
3. `sudo bash deploy/ufw/apply-firewall.sh`
4. From a **new** SSH session, confirm your access, then
   `sudo bash deploy/ufw/confirm-firewall.sh`. Do nothing and it reverts.
5. Re-test from a second LAN host: SSH, Jellyfin playback, Home Assistant, the UniFi
   console **and AP adoption**, SABnzbd, Mylar3.

`DEFAULT_FORWARD_POLICY` is already `DROP` in `/etc/default/ufw`. Docker reasserts its own
FORWARD jumps on restart, which `apply-firewall.sh` triggers explicitly so ordering is
deterministic rather than depending on whether ufw or Docker touched the chain last.


## Files
`deploy/ufw/` — `rules-input.sh` (layer 1), `rules-docker-user.sh` +
`avrana-docker-user-rules.service` (layer 2), `snapshot-firewall.sh`,
`verify-firewall.sh`, `apply-firewall.sh`, `confirm-firewall.sh`,
`rollback-firewall.sh`.
