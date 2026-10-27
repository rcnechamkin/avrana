# OliveTin - Avrana operations console

Admin-only, mobile-friendly buttons for the handful of operational tasks worth doing from a phone.
Pinned to **OliveTin 3000.19.0** by digest.

## Access

**https://ops.avrana.net** — one `sudo` restart from live; see *Pending*.

There is **no Caddy** in this stack. Public traffic terminates at cloudflared, and **Authentik's
embedded proxy outpost** is the authenticating reverse proxy, exactly as `avrana-portal` works.

```
cloudflared (ops.avrana.net)
  -> Authentik embedded outpost   [gated by the "authentik Admins" group]
    -> olivetin:1337              [X-authentik-username / X-authentik-groups injected]
```

OliveTin **publishes no host port**. Port 1337 is unreachable directly or anonymously; the only
route in is through the outpost, which strips client-supplied `X-authentik-*` headers and sets its
own, so the identity OliveTin trusts cannot be forged.

## Security model

**Default deny.** `defaultPermissions` is `view: false, exec: false, logs: false`, and
`defaultPolicy` disables diagnostics and the log list. One ACL (`avrana-admins`) grants
view/exec/logs, matching the **`authentik Admins`** group and the username `akadmin`. Every action
explicitly lists that ACL. An unexpected identity sees an empty console.

**No raw Docker socket.** OliveTin never sees `/var/run/docker.sock`. It talks to two
single-purpose [tecnativa](https://github.com/Tecnativa/docker-socket-proxy) proxies:

| Proxy | Purpose | Key settings |
|---|---|---|
| `olivetin-docker-ro` | inspection | `CONTAINERS=1 INFO=1 PING=1 VERSION=1`, **`POST=0`** |
| `olivetin-docker-restart` | restart only | `POST=1 ALLOW_RESTARTS=1`, **`CONTAINERS=0`** |

The split is the whole point. In that proxy, `ALLOW_RESTARTS` matches
`POST /containers/<name>/(stop|restart|kill)` **by path, independently of `CONTAINERS`**. Leaving
`CONTAINERS=0` on the restart proxy means `/containers/create` and `/exec` fall through to the
final deny, so a compromise of OliveTin **cannot** create a privileged container, bind-mount the
host, or exec into anything. This is not root-equivalent access.

> **Residual risk, stated plainly:** the restart proxy can stop/restart/kill *any* container by
> name, including Authentik. That is denial-of-service, not privilege escalation. The service
> allowlist is enforced above it (in `scripts/restart-service.sh` and OliveTin's fixed `choices`),
> never by free-form input.

**No free-form input anywhere.** The only parameters in the whole config are the service name and
the member notice ID; each is a fixed `choices` dropdown *and* re-validated against a hardcoded
allowlist in its script.
Verified refused: `olivetin`, `authentik-server`, `bookstack-mariadb`, `jellyfin; rm -rf /`,
`../../etc/passwd`, and empty.

**Hardening.** Non-root (`1000:1000`), `read_only: true`, `cap_drop: ALL`,
`no-new-privileges`, pids/memory/CPU limits, log rotation. Config and scripts are mounted
**read-only**, so OliveTin cannot rewrite its own ACLs. `/backups` is mounted read-only. The only
writable host path is `state/`, which holds one marker file.

## Actions

| Action | What it does | Confirm |
|---|---|---|
| **Avrana Health Report** | containers, storage, memory/load/temperature, backup freshness, internal + public endpoints, as PASS/WARN/FAIL | no (read-only) |
| **Restart a media service** | restarts one allowlisted service, then waits for it to come back healthy | yes |
| **Jellyfin library scan** | `POST /Library/Refresh` | no |
| **Audiobookshelf library scan** | `POST /api/libraries/{id}/scan` for each library | no |
| **Run stack backup now** | triggers the existing `avrana-backup.service` | yes |
| **Restart Cloudflare tunnel** | bounces `cloudflared-avrana.service` so a newly added hostname goes live | yes |
| **Member notice on Home** | sets or clears the one banner Avrana Home shows members (AVR-365); fixed choices, words live in Home | no |

Restart allowlist: jellyfin, audiobookshelf, komga, calibre-web-automated, seerr,
avrana-audible-connector, radarr, sonarr, prowlarr.

**Excluded on purpose:** Authentik, the socket proxies, OliveTin itself, BookStack + MariaDB,
Homepage and cloudflared. Restarting the thing that authenticates the button is how you lock
yourself out. **SABnzbd is a host systemd service, not a container**, so it cannot be restarted
here. **Bazarr is not deployed.**

### How the backup button works, and why

`avrana-backup.sh` runs on the host: it `pg_dump`s inside `authentik-postgresql`, `mariadb-dump`s
inside `bookstack-mariadb`, and reads `/home/cody/docker`. Reaching that from a container needs
either the host filesystem or Docker **exec** rights - and exec into a root container is root on
the host, which is exactly what this design refuses.

So OliveTin gets **one** capability instead: it writes a marker file to `state/`. A user-level
`systemd.path` unit notices it and starts `avrana-backup.service`. systemd will not run two
instances of that unit, so a manual run **cannot race the 02:30 timer** - it joins the run already
in progress. No socket, no exec, no host shell.

### How the member notice works

`scripts/home-notice.sh` writes `state/home-notice/current.json` (`{"id": ..., "set": ...}`) with an
atomic rename, or deletes it for *Clear*. Avrana Home mounts `state/home-notice/` **read-only** and
sets `HOME_NOTICE_FILE` to the file; it shows the fixed words it holds for that ID
(`services/avrana-home/avrana_home/app/notice.py`), re-checking at most every 5 seconds. The file
carries no words, markup or links, so this console cannot put arbitrary text on a member's screen,
and Home has no route that writes it. Library notices (video, audiobooks, comics, books) show only
to members who can open that library. Create the directory once: `mkdir -p state/home-notice`.
Home is not deployed yet, so nothing reads the file until the Home deployment mounts it.

**Restore is deliberately not a button.** It is destructive and needs judgement about which run and
which components; it belongs in a terminal with the runbook open.

### Restarting the tunnel, and why it needs one root unit

Adding a hostname to `~/.cloudflared/config.yml` does nothing until the tunnel restarts, and
`cloudflared-avrana.service` is a **host system unit**, not a container - the socket proxies
cannot see it, and restarting it needs root.

OliveTin does not get root. It drops a marker file, and a **root-level `systemd.path` unit**
watches for it. That unit **hardcodes the service name and takes no arguments**, so the capability
granted is exactly "restart the tunnel" - it cannot be turned into "run anything as root", which a
sudoers rule or a shell would risk.

Two details worth knowing:

- **You are restarting the thing carrying your request.** The trigger unit sleeps 3s first so the
  response reaches your browser before the tunnel drops. Every `avrana.net` page then blinks for
  roughly 5-15 seconds.
- **Verification uses a different hostname** (`listen.avrana.net`), because polling
  `ops.avrana.net` would mean asking the service that is answering you whether it is up.

If the root unit is not installed, the marker is never collected - the action detects that within
15s, says so plainly, cleans up the marker and exits non-zero rather than reporting a restart that
never happened.

## Setup

```bash
cp .env.example .env && chmod 600 .env    # fill in the two API keys
docker compose -p olivetin up -d
bash tests/test-olivetin.sh               # 27 non-destructive checks
```

Install the tunnel-restart trigger. **This is the one part that needs root**, once:

```bash
sudo ln -sf /home/cody/avrana/deploy/systemd/avrana-cloudflared-restart.path    /etc/systemd/system/
sudo ln -sf /home/cody/avrana/deploy/systemd/avrana-cloudflared-restart.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now avrana-cloudflared-restart.path
```

After that the button works forever with no further privilege.

Enable the backup trigger (user units, no sudo). **Already done on this host** and verified end to
end on 2026-08-17: the button started the real `avrana-backup.service`, which finished
`Result=success` with a 22-file manifest.

```bash
ln -sf /home/cody/avrana/deploy/systemd/avrana-backup-trigger.path    ~/.config/systemd/user/
ln -sf /home/cody/avrana/deploy/systemd/avrana-backup-trigger.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now avrana-backup-trigger.path
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Proxy container exits immediately | haproxy needs a writable `/run` for its pidfile. Under `read_only` it must have a `/run` tmpfs. |
| Console loads but is empty | Working as designed: default-deny. The account is not in `authentik Admins`. |
| Health check fails | `/healthz` is the 3000.x endpoint; `/api/ServerInfo` is not a route. The image ships `curl`, not `wget`. |
| Restart says "not an allowlisted service" | Intended. Edit `ALLOWED` in `scripts/restart-service.sh` **and** the `choices` block in `config/config.yaml`. |
| Backup button times out | The trigger `systemd.path` unit is not enabled. |
| Tunnel restart says "marker was never picked up" | `avrana-cloudflared-restart.path` is not installed. It is a **root** unit; see Setup. |

## Rollback

```bash
docker compose -p olivetin down                          # removes all three containers
systemctl --user disable --now avrana-backup-trigger.path
```

Nothing else is affected: no other service depends on OliveTin, it holds no data, and it has never
had write access to media or backups. To roll back fully, also remove the `ops.avrana.net` ingress
entry from `~/.cloudflared/config.yml` and the Authentik application, then delete the dedicated
Jellyfin API key named `olivetin`.

## Pending

**One command from live.** Done already: the Authentik application (`avrana-olivetin`, "Operations",
gated by `authentik Admins`), the proxy provider, its registration on the embedded outpost (the
outpost logs `Loaded application host=ops.avrana.net`), the DNS CNAME, and the ingress entry in
`~/.cloudflared/config.yml` ahead of the catch-all.

Remaining, and it needs a password:

```bash
sudo systemctl restart cloudflared-avrana.service
```

Until then `https://ops.avrana.net` returns the tunnel's catch-all 404, which is expected;
everything behind it is already verified.

Deferred on purpose, tracked in BookStack *Roadmap / Open TODOs*: media-permissions repair,
Wake-on-LAN, Audible import retry, SABnzbd restarts (a host systemd service, not a container), and
Bazarr (not deployed).
