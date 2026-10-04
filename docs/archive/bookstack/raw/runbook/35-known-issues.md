---
bookstack_page_id: 35
title: "Known Issues"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-08-13 21:28:53
updated: 2026-09-09 02:25:36
last_editor: "Cody"
revisions: 14
tags: []
source_format: markdown
classification: STALE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-09; exported 2026-10-04. Classified STALE. Issue list frozen on 2026-09-09; superseded by the Phase 1 and Phase 2 reports.

# Known Issues
# Known Issues
- **ABS `allowedOrigins` (2.36):** empty CORS whitelist → clients fail *looking like bad creds*. Fix in `absdatabase.sqlite`, restart. No UI toggle.
- **ABS SSO redirect scheme:** the mobile app must use `https://listen.avrana.net`; over `http`, ABS builds an `http` OIDC `redirect_uri` that Authentik rejects with **"Redirect URI Error"**. Cloudflare does not auto-upgrade here.
- **ABS mobile redirect URIs are case-sensitive:** the AudioBooth app sends lowercase `audiobooth://oauth`; a camelCase `AudioBooth://oauth` alone won't match.
- **Restart ABS after SSO changes** to apply them.
- **Libation OOM on big books:** `InProgress` on a tmpfs vs `mem_limit` → exit 137. Stage on disk (see *Libation*).
- **libvirt subnet collision — RESOLVED 2026-08-29.** `avrana-imax-verify_default` was on
  `192.168.112.0/20`, which contains libvirt's `virbr0` (`192.168.122.0/24`). Moved to
  `10.220.28.0/24` by `deploy/docker/fix-imax-libvirt-collision.sh`. Verified: 0 duplicate
  subnets, `virbr0` unchanged.
- **Docker address-pool migration FAILED 2026-08-29 03:30 and caused a ~6h outage.** Full
  write-up: *Runbook → Incident 2026-08-29*. Three faults: stale network IDs on stopped
  containers, a wedged Docker address allocator ("all predefined address pools have been fully
  subnetted"), and ~27 orphaned `br-*` interfaces holding duplicate subnets that blackholed
  host→container traffic. Recovered; all 40 containers Up and 26/26 checks pass. **The timer is
  no longer armed.** Do not re-attempt until `HEALTH_WAIT` is raised well above 180s and the
  script's rollback learns to restore *containers* and probe reachability, not just
  `daemon.json` + `docker ps`.
- **`avrana-docker-address-pool.service` still holds a failed state** from that run. Its timer
  is gone so it cannot re-run, but `services-health.sh` correctly flags it as a NEW failed unit
  on every pass while every other check is green. Clear with
  `sudo systemctl reset-failed avrana-docker-address-pool.service`.
- **CWA gotcha discovered 2026-08-29:** if `config/app.db-shm` or `config/app.db-wal` ever exist
  as **directories**, SQLite cannot open `app.db` and CWA loops on "unable to open database
  file". Check with `ls -la config/app.db-*`; if they are dirs and empty, stop CWA, back up
  `app.db`, `rmdir` them, and restart — SQLite recreates them as files.

- **mylar3 local patch:** re-apply after every upgrade.
- **`/mnt/media` is a trap:** stale root-owned rootfs dir; use `/mnt/avrana_media`.
- **Shelfmark mounts:** needs `incoming` + `audiobooks` + `books`; `AA_CONTENT_TYPE_ROUTING` is a red herring for the Prowlarr path.
- **Hardcover token:** the field auto-strips a `Bearer ` prefix.
- **Default creds:** CWA `admin`/`admin123` (change); BookStack `admin@admin.com`/`password` (changed).

## Corrections and additions, 2026-08-28

- **SABnzbd now listens on `:8082`, not `:8080`.** Moved so UniFi OS Server could take TCP 8080,
  which it requires for device adoption and does not expect to have customised. Changed in
  `~/.sabnzbd/sabnzbd.ini` (SAB is bare metal, so there is no port mapping) and re-pointed in
  Radarr, Sonarr, Prowlarr, Shelfmark's `SABNZBD_URL` and Homepage. The API key is unchanged.
- **13 systemd units are in a failed state, not 2.** This page and the roadmap track only the two
  `cloudflared` ones. The rest have been failing unnoticed because `services-health.sh` does not
  check `systemctl --failed`:
  - **System, failed since the last boot (2026-07-27):** `avrana.service` (legacy FastAPI app,
    superseded by the user-unit health API), `comic-watcher` (script file missing),
    `jdownloader2` (working directory missing), `remote-faster-whisper` (superseded by the
    wyoming containers), `sonarr.service` (**stale enabled symlink for the bare-metal Sonarr the
    container replaced — the unit file no longer exists**), `summarize_lastfm`.
  - **User, failing on a live schedule right now:** `tag_all` (**hourly**, its Python file does not
    exist), `lastfm_fetcher` (daily, mangled path `media/usic/`), `strava_fetch` (daily, token
    expired), `blackbox` (weekly, missing `google` module), `summarize_lastfm` (daily,
    **OpenAI 429 `credit_balance_exhausted`**).
- **The `haos` libvirt VM has been deleted** (2026-08-28, ~12 GB reclaimed). Home Assistant runs
  as the `home-assistant` **container**; the VM was dormant and superseded. Consequence: the
  nginx vhost `/etc/nginx/sites-enabled/homeassistant`, which proxies `haos.local` to
  `192.168.122.108:8123`, now has a **definitively** dead upstream rather than a merely broken
  one. nginx still holds `0.0.0.0:80`.
- **`whisper-flask` is undocumented and listening** on `0.0.0.0:5005` as `cody`
  (`/home/cody/whisper-flask`, 510 MB). Recorded as finding M7 in the security audit and still
  absent from the service map.

## Remediation pass, 2026-08-28 — systemd debt classified

All 14 failed units were investigated. **Correction to the note above:** `lastfm_fetcher`'s
real target is `filing_cabinet/media/music/fetchers/`, not `media_sync/music/` — the
reorganisation was `media_sync/` → `media/`. Every "missing file" unit turned out to be **path
drift, not abandonment**: the script still exists at a new path in all four cases.

`scripts/known-failed-units.txt` is the machine-readable version of this table, and
`services-health.sh` now alerts on anything failing that is *not* on it.

### SUPERSEDED — something else already does the job (needs sudo to disable)
| Unit | Evidence |
|---|---|
| `cloudflared-comics.service` | duplicate of `cloudflared.service`, which runs `config-comics.yml` |
| `cloudflared-health.service` | duplicate of the **active user unit** of the same name |
| `summarize_lastfm.service` (system) | duplicate of the user unit |
| `sonarr.service` | **unit file no longer exists**; the sonarr *container* replaced it |

### ABANDONED — target physically absent, can never start (needs sudo)
| Unit | Evidence |
|---|---|
| `comic-watcher.service` | `/home/cody/scripts` does not exist at all |
| `remote-faster-whisper.service` | `/etc/remote-faster-whisper` does not exist; the wyoming containers replaced it |
| `jdownloader2.service` | `WorkingDirectory=/home/cody/.jdownloader` does not exist (the app dirs under `~/JDownloader` remain — **do not delete those**, only the unit is dead) |

### ACTIVE/FIX — one-line `ExecStart` path corrections, deliberately NOT auto-applied
| Unit | Cadence | Wants | Real path |
|---|---|---|---|
| `parse_health_export` | **every 60 s** | `health/parse_new_export.py` | `health/parsers/parse_new_export.py` |
| `tag_all` | hourly | `taggers/tag_all.py` | `utils/tag_all.py` |
| `lastfm_fetcher` | daily | `media/usic/fetchers/…` | `media/music/fetchers/…` |
| `summarize_lastfm` (user) | daily | `media_sync/music/summarizers/…` | `media/music/summarizers/…` |

~~`parse_health_export` is the loudest thing on the host~~ — **resolved 2026-08-28.** The timer
was retired in the 2026-08-28 pass, and the pipeline it fed was retired with the Health API on
2026-08-28 (**H1 closed**). Worth recording *why* it failed 1,440 times a day: the module it
invoked, `filing_cabinet.health.parse_health_export`, never existed under that name — the file on
disk is `parsers/parse_healt_export.py`, misspelt. The same missing module is why every
`POST /api/health` had returned `{"status": "error"}` since the rename. See *Services → Health API*.

### AMBIGUOUS — preserved deliberately
| Unit | Why |
|---|---|
| `avrana.service` | **RECOMMEND RETIRE (2026-08-28).** The legacy Kern Prime / AIRIK FastAPI app on :8000. It has **never started successfully** — zero success markers in its journal — and the reason is structural, not a regression: `api/start_api.py` calls `app.include_router(health.router)`, but `api/health.py` has never exported a `router` in any commit since 2025-06-23. All **11 other** route modules (cbt, habits, activity, sleep, moods, recap, journal, schedule, ping, journals, llm_chat) import cleanly and do export routers, so the import is a one-line fix — **but that is not the whole repair**: `main.py` builds `app` and exits without ever calling uvicorn, so with `Restart=always` a successful import would only produce a restart loop. Repair means inventing an ExecStart *and* deciding auth for 11 unauthenticated personal-data endpoints. Nothing depends on it (the only `:8000` references are its own print statement and a README example). **Recommendation: `systemctl disable avrana.service` to stop it boot-looping, and keep the source** so Kern Prime can be revived deliberately later. Needs interactive sudo. |
| `strava_fetch` | script exists; fails on an expired token — a credential decision |
| `blackbox` | script exists; missing the `google` python module |

### Acted on
- ~~**`whisper.service` / whisper-flask on `0.0.0.0:5005`**~~ **DONE — disabled and inactive**
  (verified 2026-08-28 21:30; nothing listens on 5005).
- ~~**`avrana.service`**~~ **DONE — disabled and inactive** (verified 2026-08-28 21:30).
- **Dead nginx on `:80` — recommended for retirement (found 2026-08-28).** `nginx.service` is
  enabled and active; its **only** enabled site, `homeassistant`, proxies to
  `http://192.168.122.108:8123` — a libvirt VM that no longer exists (`virsh list --all` is
  empty). It answers **502** to anyone on the LAN. Home Assistant runs as a container on host
  networking at `:8123`. This is the "remove the dead nginx site" item from the 2026-08-20
  audit, now identified precisely. The firewall design deliberately does **not** open 80.
  Suggested: `sudo systemctl disable --now nginx`. Awaiting approval.
- **SABnzbd requires a login; mylar3 no longer does.** (2026-08-28, audit C1/C2 closed — **the mylar3 half was reversed 2026-09-05** at the operator's request: `authentication = 0`, credentials set to `None`. SABnzbd unchanged.) API keys unchanged in both cases. Re-enabling mylar3 auth requires setting `http_username`/`http_password` as well as `authentication` — see *Runbook → Verification pass, 2026-09-08* for the coercion trap at `mylar/config.py:1442`.
  Credentials in `services/bare-metal-auth.env`, mode 600, gitignored.

- **`mylar.service` (user) disabled.** It was *enabled* and pointed at
  `services/mylar3/venv/bin/python` — and that interpreter **exists**, so at the next user-session
  start it would have launched a **second Mylar3** against the same SQLite database and port 8090.
  The system unit `mylar3.service` owns the live process. Unit file preserved, not deleted.
  Verified afterwards: `mylar3.service` still active, `:8090` still answering.

## Remediation pass 2 — 2026-08-29

**`parse_health_export` DISABLED — the Apple Health pipeline is obsolete.** It was failing
**1,440 times a day**. Evidence: `logs/health_requests.log` holds **20 requests across its entire
life**, the last genuine phone POST was **2025-09-18**, and the only 2026 entry is the security
audit's own test from `127.0.0.1`. `raw_exports/` and `runs/` agree — nothing real since
September 2025. Timer stopped and disabled; **unit files preserved, not deleted**.

The one-line `ExecStart` path fix was deliberately **not** applied. Fixing the path would
*reactivate* an ingest pipeline that is the subject of security finding **H1**.

> **Moot as of 2026-08-28 — the Health API was retired rather than secured (H1 closed).** There is
> no longer anything listening on 8240 and no `health.avrana.media` connector. The bar below stands
> as the condition for ever rebuilding this ingest path: authentication on the POST route, a real
> secret from the environment (not a literal), and a bind to `127.0.0.1` rather than all
> interfaces. Historical text follows.
>
> ~~the health API listens on `0.0.0.0:8240` as `cody`, `POST /api/health` has **no authentication
> at all** and spawns a subprocess, and `SECRET_KEY` is a hardcoded literal guarding only
> `/logs`. `cody` holds `docker`, `lxd` and `libvirt`, each root-equivalent. Reactivation would
> need, at minimum: authentication on the POST route, a real secret from the environment, and a
> bind to `127.0.0.1` rather than all interfaces. The `health.avrana.media` tunnel is still
> **running** and one DNS record away from making that endpoint public.

**Note the API itself is untouched and still listening.** Disabling the parser stopped the noise;
it did **not** close H1.

## Failed-unit baseline after pass 2

| Scope | Count | Note |
|---|---|---|
| system | **8** | unchanged — all 8 need root to clear (see below) |
| user | **5** | was 6; `parse_health_export` retired from the baseline |

`scripts/known-failed-units.txt` is the machine-readable baseline and is now tracked in Git —
`services-health.sh` depends on it, and without it every acknowledged unit reports as NEW.

## Root-gated work, prepared and not yet applied

This session has no passwordless sudo, so both remaining items are written as **self-verifying
scripts** rather than left as instructions:

- **`deploy/systemd/cleanup-obsolete-units.sh`** — disables the 4 SUPERSEDED + 3 ABANDONED system
  units. Every precondition is **re-confirmed at run time** (it will not disable `comic-watcher`
  if `/home/cody/scripts` has reappeared), unit files are backed up first, and it targets
  `summarize_lastfm.timer` because the service is `static` and cannot be disabled directly.
  Expected remaining failed system unit afterwards: **`avrana.service` only** (ambiguous,
  preserved on purpose).
- **`deploy/docker/apply-address-pools.sh`** — see *Docker Hardening and Networking*.

All three abandoned targets were re-confirmed still absent on 2026-08-29:
`/home/cody/scripts`, `/etc/remote-faster-whisper`, `/home/cody/.jdownloader`.
Both `.media` hostnames re-confirmed **NXDOMAIN**.

- **6 orphan Docker container records — OPEN, needs root; a reboot is a coin flip until fixed.**
  Duplicate records under Docker's container store (komga ×2, jellyfin, prowlarr, radarr, sonarr)
  collide on name at every daemon start (`journalctl -u docker | grep 'name is reserved'`). The
  first record to register wins and the rest are dropped, so a reboot can resurrect a months-old
  container spec and make the good one vanish — this is what took komga and prowlarr down on
  2026-08-29. Fix: `sudo bash deploy/docker/clean-orphan-container-records.sh` (dry-run first,
  then `--apply`). See *Runbook → Incident 2026-08-29*.
- **Docker's data-root is `/mnt/avrana_media/docker`, NOT `/var/lib/docker`.** Any tooling or
  command that assumes the default path silently finds nothing.
- **Root cannot run `docker compose` on this host.** The Compose v2 plugin exists only at
  `~cody/.docker/cli-plugins/docker-compose`; `sudo docker compose ...` fails with
  `docker: unknown command: docker compose`, and `/usr/bin/docker-compose` is Compose **v1.29.2**,
  a different tool. Any root-run script must drop to `cody` (`runuser -u cody -- docker compose`).
  This silently no-opped the whole rollback on 2026-08-29.
- **After any Prowlarr outage, clear the Radarr/Sonarr indexer backoff.** Fixing Prowlarr does not
  clear it: Sonarr escalates to a multi-hour `DisabledTill` and stays dark long after Prowlarr is
  healthy (it reached level 7 / +6h on 2026-08-29, while Radarr never locked out — which is why
  only one of them looked broken). Clear with `POST /api/v3/indexer/testall` plus a real
  interactive search. Also re-search anything **added during** the outage: its search-on-add found
  nothing and it will sit monitored with zero history.
- **Never bind-mount SQLite `-wal`/`-shm` files individually.** SQLite deletes them on clean close
  and Docker recreates a missing bind source as a **directory**, which then makes the app fail with
  `unable to open database file`. Mount the containing directory instead — see
  `services/avrana-kindle-connector/` for the pattern (`config/appdb/` + a relative symlink).
