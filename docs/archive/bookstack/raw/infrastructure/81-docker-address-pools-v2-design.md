---
bookstack_page_id: 81
title: "Docker address pools — v2 design"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-29 17:06:23
updated: 2026-08-29 17:06:23
last_editor: "Cody"
revisions: 1
tags: []
source_format: markdown
classification: STALE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified STALE. Address-pool design that was abandoned after the 2026-08-29 incident.

# Docker address pools — v2 design
# Docker address pools — v2 design

> **Status: DESIGNED 2026-08-29. NOT APPLIED, NOT SCHEDULED.** `daemon.json` still carries
> only `data-root`. Everything below is in the repo under `deploy/docker/` (commit `b527ac6`).
> Applying needs root and Cody's sign-off.

## The question that governs everything: does anything need renumbering?

**No.** `default-address-pools` governs **only the allocation of NEW networks**. Every
existing network keeps the subnet recorded in Docker's network store, across daemon restarts
and reboots. This is not an inference — the failed 2026-08-29 run demonstrated it: after it
set the pools and restarted Docker, the existing networks still held their `172.x` /
`192.168.x` subnets. The fleet broke for unrelated reasons (see `INCIDENT-2026-08-29.md`).

One network *is* re-derived from the pool on every daemon start: the default `bridge`
(`docker0`). That is expected and harmless here — **nothing on this host is attached to it**,
and the preflight asserts that before allowing the change.

So the strong preference in the brief is exactly what Docker already does. Existing networks
stay untouched; the pools apply to new networks going forward.

### One exception, and it is not caused by this change
`avrana-imax-verify_default` is on **192.168.112.0/20**, which spans
192.168.112.0–192.168.127.255 and therefore **contains libvirt's `virbr0` (192.168.122.0/24)**.
This is precisely the hazard the pool change exists to prevent, and it was introduced by the
2026-08-29 recovery, which hand-assigned subnets from the crowded 192.168 space. Nothing is
broken today only because `virbr0` is DOWN — but libvirt's `default` network is active with
`autostart=yes`, so the first VM to start makes host routing for that /24 ambiguous.

Fix it separately with `fix-imax-libvirt-collision.sh`: one network, one container, no daemon
restart, no root. It moves to `10.220.28.0/24` and refuses if that would overlap any host
interface.

## Recommended strategy: `--defer`

`apply-address-pools-v2.sh --defer` (the default) writes and validates the config and then
**stops**. No daemon restart, so no container restart, no network recreation, and none of the
failure modes that caused the outage. The pools take effect at the next daemon start.

**A reboot is already pending** (`/var/run/reboot-required`: `libc6`,
`linux-image-6.8.0-137/138`; running 6.8.0-136 on 32 days uptime). That reboot is the ideal
vehicle — the fleet comes up once, cleanly, instead of being restarted twice in one day for
two separate reasons. Verify afterwards with `post-change-verify.sh`.

`--now` exists for the case where a reboot is not an acceptable vehicle. It is attended-only.

## What the new script actually changes

Only `/etc/docker/daemon.json`, and only by **adding** keys — the merge preserves everything
already present (`data-root` and anything else):

```json
"default-address-pools": [ {"base":"10.210.0.0/16","size":24},
                           {"base":"10.211.0.0/16","size":24} ],
"log-driver": "json-file",
"log-opts": { "max-size": "50m", "max-file": "5" }
```

512 available /24 networks. No compose file is edited, no network is recreated, no container
is recreated, and `avrana-ldap` and the other external networks are never touched.

## Why v1 failed, and what is different

| v1 | v2 |
|---|---|
| Waited **180s** for 40 containers | **900s**, adaptive — tracks progress and only gives up after `STALL_LIMIT` (180s) with no improvement |
| Judged success by `docker ps` | Judged by the **26-check application probe**. A container can be `Up (healthy)` and completely unreachable — that is exactly what happened |
| Never checked for network damage | Explicitly detects **stale network IDs**, **orphan bridges** and **duplicate subnets**, and rolls back on any of them |
| Rollback restored `daemon.json` and stopped | Rollback **restores service**: rebuilds every network from the snapshot with its original subnet and internal flag, deletes orphan bridges, brings all 23 compose projects up, and re-probes. It does not report success until the probe passes |
| No preflight | Refuses to start from a degraded fleet, an already-failing probe, existing network damage, or a pool that overlaps the LAN, libvirt or any existing docker subnet |
| Ran unattended from a timer at 03:30 | **Not scheduled.** Attended only |

## Files
| File | Role |
|---|---|
| `preflight-address-pools.sh` | read-only; safe any time; 6 sections |
| `snapshot-docker-state.sh` | networks (replayable create lines), container→project map, iptables, bridges, probe baseline |
| `apply-address-pools-v2.sh` | `--defer` (default) or `--now` |
| `rollback-docker-state.sh` | restores **service**, not just config |
| `post-change-verify.sh` | run after the reboot; asserts nothing was renumbered |
| `fix-imax-libvirt-collision.sh` | the separate, targeted libvirt fix |
| `apply-address-pools.v1-DO-NOT-RUN.sh` | historical record; exits 1 immediately |

## Residual risks
- **The `--now` path still restarts every container.** That is unavoidable for a daemon
  config change; `--defer` removes it entirely by riding the pending reboot.
- **`docker0` moves into the pool** on the first restart after the change. Harmless while
  nothing is attached — preflight enforces that, but a future container placed on the default
  bridge would inherit a pool address.
- **Rollback depends on compose files matching the running fleet.** All 23 projects currently
  resolve to real directories; a project whose compose file drifted from its running container
  would come back as the compose file describes, not as it was.
- **Rollback cannot undo a `data-root` or storage-driver change.** It is scoped to networking
  and daemon config.
- **The libvirt collision is live now**, independent of any of this.
