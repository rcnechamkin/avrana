---
bookstack_page_id: 80
title: "Incident 2026-08-29 — address-pool outage, reboot relapse, recovery"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-08-29 16:56:11
updated: 2026-08-30 02:24:24
last_editor: "Cody"
revisions: 3
tags: []
source_format: markdown
classification: DUPLICATE
destination: "docs/incidents/2026-08-29-docker-address-pools.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-30; exported 2026-10-04. Classified DUPLICATE; current information is in `docs/incidents/2026-08-29-docker-address-pools.md`. The incident report in Git is the fuller copy.

# Incident 2026-08-29 — address-pool outage, reboot relapse, recovery
# Incident 2026-08-29 — address-pool migration outage, reboot relapse, and recovery

**Impact.** Two separate outages in one day. Wave 1: 35 of 40 containers down for ~6 hours;
`avrana.net` and five other public hostnames served 502. Wave 2, after the planned reboot: 2
containers down, CWA dead, and Sonarr locked out of its indexers for a further ~7 hours.

**Resolved.** 40/40 containers Up, 26/26 reachability checks pass, 12/12 public hostnames healthy,
0 orphan bridges, 0 duplicate subnets, 0 stale network IDs, 0 failed systemd units.

**The address pools were never the fault.** They behaved exactly as designed, both times. Every
pre-existing network kept its subnet; nothing was renumbered; no bridge was orphaned by them. What
the pool work did was force two cold container restores, and *that* is what exposed four unrelated
latent faults. Three of them had been sitting in the stack for months.

---

## Timeline (all times PDT)

| Time | Event |
|---|---|
| 03:30 | `avrana-docker-address-pool.timer` fires: merges `default-address-pools` (10.210/10.211), validates with `dockerd --validate`, restarts Docker. |
| 03:31–03:34 | Waits `HEALTH_WAIT=180`s for the fleet. 35 containers do not return in time. |
| 03:34 | Auto-rollback restores `daemon.json`, restarts Docker, reports "post-rollback running: 8 (pre-change was 40)", exits 1. **Config restored, containers not.** |
| ~09:16 | 502 reported on `avrana.net`. |
| 09:20–10:00 | Wave-1 recovery (run as `cody`). Orphan bridges cleared, networks rebuilt with explicit subnets, containers recreated. Back to 40/40, 26/26. |
| 10:08 | IMAX/libvirt subnet collision fixed — `avrana-imax-verify_default` moved to `10.220.28.0/24`. |
| 10:09 | Snapshot `backups/docker-state-20260829T170942Z` taken. Git clean and pushed. |
| 10:14:54 | **Planned reboot** to activate the deferred pools. |
| 10:15:07 | dockerd starts. Pools active, `docker0 = 10.210.0.0/24`. |
| 10:15:34 | 6× `failed to register container name … error="name is reserved"` — jellyfin, prowlarr, sonarr, radarr, komga (×2). **Fault 2 fires.** |
| 10:15:47 | `avrana-kindle-connector` fails to start: `mounting …/app.db-shm to /cwa/app.db-shm: not a directory`. **Fault 3, first half.** |
| 10:17:01 | `Loading containers: done.` |
| ~10:17 | `post-change-verify.sh`: pools active, **nothing renumbered**, 0 orphan bridges, 0 duplicate subnets — but 1 container not Up and 12/26 reachability checks failing. |
| 10:18:53 | `rollback-docker-state.sh` stops Docker. CWA closes cleanly → **SQLite deletes `app.db-wal` and `app.db-shm`.** |
| 10:19:09 | dockerd restarts. Docker recreates those two missing bind sources as empty **directories**. CWA now cannot open its DB. **Fault 3, second half.** |
| 10:19:23 | prowlarr and komga fail: `failed to set up container networking: network <id> not found`. |
| 10:19–10:21 | Rollback's compose pass runs. **Every one of the 23 projects fails silently.** **Fault 1.** |
| 10:21 | Wave-2 recovery begins. 38/40 Up, 9/26 checks failing. |
| 10:26–10:28 | CWA repaired, connector recreated, komga and prowlarr recreated. 40/40, 26/26. |
| ~10:33 | All 12 public hostnames healthy. |
| 10:39–11:00 | **Fault 4** found: Sonarr had every indexer disabled with a 6-hour backoff. Cleared. |
| 19:16–19:20 | Reboot-safety work: CWA WAL race fixed permanently, rollback script rewritten, orphan-record cleanup prepared. |

---

## Root cause — four independent faults

### 1. Root cannot run `docker compose` — why the rollback did nothing

The Compose v2 plugin is installed **only** at `/home/cody/.docker/cli-plugins/docker-compose`.
There is no system-wide plugin; `/usr/libexec/docker/cli-plugins/` holds only `docker-trust`.
`rollback-docker-state.sh` hard-requires root, and root's `HOME` is `/root`:

```
# HOME=/root docker compose version
docker: unknown command: docker compose
```

So step 5 — "bring every compose project back up" — was a **no-op for all 23 projects**, and
`rollback-docker-state.sh:60` discarded the reason with `>/dev/null 2>&1`. The operator saw 23
bare `WARN: up failed` lines with no cause.

*Proof:* no container has a `Created` timestamp between 10:19 and the manual recreates at 10:27.
The 38 containers that came back were brought up entirely by `restart: unless-stopped`, not by the
rollback. `/usr/bin/docker-compose` exists but is Python Compose **v1.29.2** — a different tool
that cannot read these files.

This is also why the 03:34 auto-rollback "restored the config but never the containers". Same bug,
same script, six hours earlier.

### 2. Duplicate container-name records shadow good containers at boot

dockerd loads every directory under `<docker-root>/containers/` and registers each record's name.
When two records claim one name the **first wins** and the rest are dropped with `name is
reserved`. The loser stays on disk, invisible to the API, and re-collides at every daemon start.
Registration order is effectively readdir order, so **which record wins is arbitrary**.

Leftovers from the wave-1 recovery meant that at 10:15 the *stale* records won for komga and
prowlarr — resurrecting a komga spec last run 2026-05-03 and a prowlarr spec from 2025-08-17.
Both then failed with `network <id> not found`, because:

- komga's record referenced `komga_default` id `fe2fdac8d83f`; the live network is `620992f120b5`.
- prowlarr's record referenced `docker_default` id `9fb9b0255bdc` — a network that **no longer
  exists at all**, removed when the media compose was refactored to `arr-core` /
  `request-backend`. That container had never been recreated after the refactor; it survived only
  because it kept running. Its first cold start was always going to fail.

jellyfin, radarr and sonarr had duplicates too — they happened to win with the good record.

### 3. CWA's WAL sidecars became directories

`avrana-kindle-connector` bind-mounted three files individually — deliberately, to keep `.key`
(the Fernet key for CWA's SMTP password) out of the container:

```yaml
- …/config/app.db:/cwa/app.db:rw
- …/config/app.db-wal:/cwa/app.db-wal:rw
- …/config/app.db-shm:/cwa/app.db-shm:rw
```

SQLite **deletes** `-wal` and `-shm` on every clean close, and Docker **creates a missing bind
source as a directory**. So:

1. Some earlier stop left the two as directories → the connector's *rootfs* mountpoints were baked
   as directories, which is why at 10:15:47 it failed with `not a directory` even once the host
   paths were files again.
2. At 10:18:53 the rollback stopped Docker; CWA closed cleanly; SQLite removed both files.
3. At 10:19:09 Docker recreated them as empty **directories**, and CWA died with
   `sqlite3.OperationalError: unable to open database file`.

Not corruption. `app.db` integrity was `ok` and all 4 users intact throughout.

### 4. Radarr/Sonarr indexer backoff outlives the outage

Prowlarr was down 03:34 → 10:28. Both apps escalated each indexer's failure state the whole time.

| | EscalationLevel | DisabledTill | Effect |
|---|---|---|---|
| Sonarr | **7** | 2026-08-29 15:20 PDT | Locked out for ~5 more hours *after* Prowlarr was healthy |
| Radarr | 3 | *null* | Never locked out — kept working |

Sonarr's health showed `All indexers are unavailable due to failures for more than 6 hours`. That
asymmetry is why one app looked fine and the other looked dead, and why "Prowlarr lost its
indexers" was the natural but wrong reading — Prowlarr's config was never touched. Verified
against the pre-incident 02:34 backup: identical indexer set, identical IDs, `sqlite_sequence`
still 2, so nothing was ever deleted.

Anything **added during the outage** also silently got no search. `Whiplash (2014)`, added 09:50,
had zero history records because Radarr's search-on-add fired into a dead Prowlarr.

---

## Does `docker0 = 10.210.0.0/24` matter?

**No — cosmetic and self-correcting.** `daemon.json` has no pools now (`docker info` reports none).
At the 10:15 start the pools *were* live, so docker0 was created at `10.210.0.1/24`. The rollback
restored the pre-pool config at 10:18:53, but by 10:19 the `docker0` interface already existed
holding that address, and the bridge driver adopts an existing `docker0` rather than re-deriving
one. It has 0 containers, is `linkdown`, and collides with nothing (LAN `10.0.0.0/24`, virbr0
`192.168.122.0/24`, all service bridges accounted for). It reverts to `172.17.0.0/16` on the next
reboot on its own.

---

## Fixes applied

| # | Fix | Where |
|---|---|---|
| 1 | Rollback script rewritten (v3): runs Compose as `cody` via `runuser`, never suppresses compose output, collects per-project failures, waits for container restore before the compose pass, reports stale network IDs, and gates success on the **reachability probe** rather than `docker ps`. Refuses to run at all if `cody` cannot execute `docker compose`. | `deploy/docker/rollback-docker-state.sh` |
| 2 | `clean-orphan-container-records.sh` — dry-run by default; removes only records that are both absent from `docker ps -aq` **and** name-colliding with a registered container; tars each record first; auto-detects Docker's data-root; verifies fleet + probe + a zero `name is reserved` count afterwards. | `deploy/docker/clean-orphan-container-records.sh` |
| 3 | `app.db` relocated to `config/appdb/`, reached by the relative symlink `config/app.db -> appdb/app.db`. The connector now mounts that **directory** at `/cwa`. Docker never has to create a bind source, so the fault class is gone — and `.key`, `cwa.db` and `gdrive.db` remain invisible to the connector. | `services/avrana-kindle-connector/docker-compose.yml`, `README.md` |
| 4 | Sonarr backoff cleared via `indexer/testall` + real interactive searches. `Whiplash` searched and grabbed. | live |

### Verifying fix 3

SQLite resolves a symlinked main DB and places `-wal`/`-shm` next to the **target** — confirmed
empirically before the change. Three cycles were then run:

1. Clean CWA stop with the connector still running → sidecars stay files, CWA restarts 302.
2. Stop both, start the **connector first** (the exact outage race) → nothing created, CWA 302.
3. Delete both sidecars while stopped, start the connector first → **Docker created nothing**;
   CWA then recreated them as proper files on start.

Connector read *and* write paths retested inside the container; `journal_mode=wal`; `.key` not
present in `/cwa`.

---

## Still open

- **The 6 orphan container records have not been removed** — that needs root. Until they are, a
  reboot is a coin flip for komga, prowlarr, jellyfin, radarr and sonarr. Run:
  `sudo bash deploy/docker/clean-orphan-container-records.sh` (dry-run), then `--apply`.
- **Docker's data-root is `/mnt/avrana_media/docker`, not `/var/lib/docker`.** Any tooling that
  assumes the default path will silently find nothing.

## Before re-attempting the migration

- **`HEALTH_WAIT=180` is too short** for a 40-container fleet. It is the direct cause of wave 1.
- The rollback now probes reachability and runs compose as a user that has it — but it still
  cannot fix a stale container spec on its own, by design. It reports them instead.
- Clean orphaned bridges after any restart that recreates networks.
- After any Prowlarr outage, **clear the Radarr/Sonarr indexer backoff** — recovery of Prowlarr
  does not clear it, and Sonarr will stay dark for hours.
- The timer is **no longer armed**; nothing re-runs it unattended.

## Wave-1 detail (retained)

| Service | Cause | Fix |
|---|---|---|
| Sonarr | clean shutdown during the incident, never restarted | compose recreate |
| Komga | stale network ID, so no working egress and Spring aborted on OIDC discovery | compose recreate — no Komga or Authentik config touched |
| CompleteSeries | running with no networks attached and no published ports | compose recreate |
| CWA | `app.db-shm`/`app.db-wal` as empty directories | see fault 3 |

Orphaned bridge interfaces were the fault that outlasted the others in wave 1: ~27 `br-<id>` links
stayed in the kernel holding the old subnets, so recreating a network on the same subnet produced
**two interfaces with the same address** and host→container traffic blackholed. The tell was
container `Up (healthy)`, port bound in `ss`, and `curl` returning nothing. Cleared by
`clean-orphan-bridges.sh`.

`komf` and `kavita` (`profiles: ["legacy"]`) and `bazarr` (`profiles: ["optional"]`) had restarted
as fallout and were removed; they are not part of the default stack.
