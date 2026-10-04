---
bookstack_page_id: 48
title: "OliveTin Operations Console"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Platform"
created: 2026-08-17 06:56:44
updated: 2026-08-21 00:15:53
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: DUPLICATE
destination: "services/olivetin/README.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified DUPLICATE; current information is in `services/olivetin/README.md`. The service README is the maintained copy.

# OliveTin Operations Console
# OliveTin Operations Console

Admin-only, mobile-friendly buttons for the operational tasks worth doing from a phone.
**OliveTin 3000.19.0**, pinned by digest. Lives at `services/olivetin/`.

## Access and architecture

**https://ops.avrana.net** (see *Rollout status* below).

There is **no Caddy** in this stack. Public traffic terminates at cloudflared, and **Authentik's
embedded proxy outpost** is the authenticating reverse proxy - the same pattern *Avrana Portal*
uses.

```
cloudflared (ops.avrana.net)
  -> Authentik embedded outpost   [application "Operations", gated by "authentik Admins"]
    -> olivetin:1337              [X-authentik-username / X-authentik-groups injected]
```

OliveTin **publishes no host port**. Verified: nothing listens on 1337, `PortBindings` is empty,
and a direct connection to `10.0.0.218:1337` is refused. The only route in is the outpost, which
strips client-supplied `X-authentik-*` headers and sets its own - verified by replaying a request
with forged `X-authentik-groups: authentik Admins`, which was still challenged with a 302.

## Security decisions

### Two gates, not one

The Authentik application is gated by **`authentik Admins`**. Independently, OliveTin's own config
is **default-deny**: `defaultPermissions` is `view/exec/logs: false` and `defaultPolicy` hides
diagnostics and the log list. A single ACL grants access, matching the `authentik Admins` group and
the username `akadmin`. Every action lists that ACL explicitly. An unexpected identity that somehow
reached the app would see an empty console.

### No raw Docker socket - and why the usual proxy is not enough

OliveTin never sees `/var/run/docker.sock`. Two single-purpose tecnativa proxies sit in front:

| Proxy | Purpose | Settings |
|---|---|---|
| `olivetin-docker-ro` | inspection | `CONTAINERS=1 INFO=1 PING=1 VERSION=1`, **`POST=0`** |
| `olivetin-docker-restart` | restart only | `POST=1 ALLOW_RESTARTS=1`, **`CONTAINERS=0`** |

The naive configuration for restarts is `POST=1 CONTAINERS=1` - and that is **root-equivalent**,
because `/containers/create` lives in the `CONTAINERS` section, so it would allow creating a
privileged container with the host bind-mounted.

Reading the proxy's haproxy template shows a better path: **`ALLOW_RESTARTS` matches
`POST /containers/<name>/(stop|restart|kill)` by path, independently of `CONTAINERS`**. Leaving
`CONTAINERS=0` therefore permits restarts while `/containers/create` and `/exec` fall through to
the final deny. Verified live - both return **403**, as do `/images` and `/volumes`.

> **Residual risk, stated plainly.** The restart proxy can stop/restart/kill *any* container by
> name, including Authentik. That is **denial-of-service, not privilege escalation**. The service
> allowlist is enforced above it, in `scripts/restart-service.sh` and OliveTin's fixed `choices`,
> never by free-form input.

### The backup button is a file trigger, not exec

`avrana-backup.sh` runs on the host and dumps databases from *inside* `authentik-postgresql` and
`bookstack-mariadb`. Reaching that from a container needs either the host filesystem or Docker
**exec** rights - and exec into a container running as root is root on the host, which is exactly
what this design refuses.

So OliveTin gets one capability instead: it writes a marker file to `services/olivetin/state/`. The
user-level `avrana-backup-trigger.path` unit notices it and starts the existing
`avrana-backup.service`. **systemd will not run two instances of that unit, so a manual run cannot
race the 02:30 timer** - it joins the run already in progress. No socket, no exec, no host shell.

**Restore is deliberately not a button.** It is destructive and needs judgement about which run and
which components; it belongs in a terminal with the runbook open. See *Backups & Recovery*.

### Hardening

Non-root (`1000:1000`), `read_only: true`, `cap_drop: ALL`, `no-new-privileges`, pids/memory/CPU
limits, log rotation. Config and scripts are mounted **read-only**, so OliveTin cannot rewrite its
own ACLs. `/backups` is read-only. The only writable host path is `state/`, holding one marker file.
A **dedicated** Jellyfin API key (`olivetin`) was minted rather than reusing Authentik's admin key.

## Actions

| Action | What it does | Confirm |
|---|---|---|
| **Avrana Health Report** | containers, storage, memory/load/temperature, backup freshness, internal + public endpoints, as PASS/WARN/FAIL | no (read-only) |
| **Restart a media service** | restarts one allowlisted service, waits for it to come back healthy | yes |
| **Jellyfin library scan** | `POST /Library/Refresh` | no |
| **Audiobookshelf library scan** | `POST /api/libraries/{id}/scan` per library | no |
| **Run stack backup now** | triggers the existing `avrana-backup.service`; rate-limited 2/hour | yes |

Restart allowlis: `jellyfin`, `audiobookshelf`, `komga`, `calibre-web-automated`, `seerr`,
`avrana-audible-connector`, `radarr`, `sonarr`, `prowlarr`.

**Excluded on purpose:** Authentik, the socket proxies, OliveTin itself, BookStack + MariaDB,
Homepage, cloudflared. *Restarting the thing that authenticates the button is how you lock yourself
out.* **SABnzbd is a host systemd service, not a container**, so it cannot be restarted here.
**Bazarr is not deployed.**

## Live verification (2026-08-17)

`bash services/olivetin/tests/test-olivetin.sh` - **27/27 passed**, non-destructive and re-runnable:

- compose + YAML valid, all four scripts parse, all 5 actions ACL-gated
- no host port published, nothing listening on 1337
- restart proxy denies `/containers/create`, `/exec`, `/images`, `/volumes` (403); ro proxy denies POST restart (403)
- allowlist refused `olivetin`, `authentik-server`, `bookstack-mariadb`, `jellyfin; rm -rf /`, `../../etc/passwd`, empty
- restart plumbing proven against a **disposable** container, never a production service
- no key material in action output, container logs, or anything git tracks

Also verified live: health report **13 PASS / 1 WARN / 0 FAIL** against the real stack (the WARN is
off-host backup, correctly not configured yet); Jellyfin scan **HTTP 204**; Audiobookshelf scan
**HTTP 200**; unauthenticated request to the outpost **302** to sign-in; forged admin headers still
**302**; portal `/ops` **307** for an admin and **404** for an ordinary member.

Three real bugs were found by testing and fixed: haproxy needs a writable `/run` under `read_only`
or it exits fatally; `/healthz` is the 3000.x health endpoint (`/api/ServerInfo` is not a route) and
the image ships `curl`, not `wget`; and `nproc` reports the cgroup CPU limit, which would have made
every normal load look critical.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Proxy container exits immediately | haproxy needs a writable `/run` for its pidfile under `read_only`. |
| Console loads but is empty | Working as designed: default-deny. The account is not in `authentik Admins`. |
| Health check failing | `/healthz`, not `/api/ServerInfo`. The image has `curl`, not `wget`. |
| "not an allowlisted service" | Intended. Edit `ALLOWED` in `scripts/restart-service.sh` **and** `choices` in `config/config.yaml`. |
| Backup button times out | `avrana-backup-trigger.path` is not enabled. |
| `ops.avrana.net` returns 404 | cloudflared has not been restarted since the ingress entry was added. |

## Rollback

```bash
docker compose -p olivetin down                              # removes all three containers
systemctl --user disable --now avrana-backup-trigger.path
```

Then, to remove it entirely: delete the `ops.avrana.net` block from `~/.cloudflared/config.yml`
(a backup of the pre-change file was taken), delete the Authentik application `avrana-olivetin` and
provider `avrana-olivetin-proxy`, remove the `authentik Admins` entry from `SERVICES` in
`services/avrana-portal/portal.py`, and delete the Jellyfin API key named `olivetin`.

Nothing else depends on OliveTin. It holds no data and has never had write access to media or
backups.

## Rollout status

**Everything is built, deployed and verified except the tunnel restart.** DNS is done
(`ops.avrana.net` is a proxied CNAME resolving to Cloudflare), the ingress entry is in
`~/.cloudflared/config.yml` before the catch-all, and the Authentik application, provider and
outpost routing are live (the outpost logs `Loaded application host=ops.avrana.net`).

The **backup trigger path unit is enabled** (`avrana-backup-trigger.path`, active) and the button
was proven end to end on 2026-08-17: it started the real `avrana-backup.service`, which completed
with `Result=success` and wrote a 22-file manifest. systemd's single-instance guarantee is what
stops a manual press racing the 02:30 timer.

**Remaining, needs Cody:**

```bash
sudo systemctl restart cloudflared-avrana.service
```

Until then `https://ops.avrana.net` hits the tunnel's catch-all 404, which is expected. OliveTin
config and scripts are captured in `stack-config`, so this service is covered by the nightly backup.

### Deferred on purpose

Media-permissions repair (no safe existing script to wrap), Wake-on-LAN (no second node), Audible
import retry (the connector exposes no idempotent single-shot interface), SABnzbd restarts (a host
systemd service, not a container), and Bazarr (not deployed). Restore is deliberately never a
button. See *Roadmap / Open TODOs* for the tracked list.
