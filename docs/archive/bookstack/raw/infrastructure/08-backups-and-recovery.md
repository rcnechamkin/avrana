---
bookstack_page_id: 8
title: "Backups and Recovery"
shelf: "Avrana Homelab"
book: "Infrastructure"
chapter: ""
created: 2026-08-13 21:28:44
updated: 2026-08-29 03:35:23
last_editor: "Cody"
revisions: 10
tags: []
source_format: markdown
classification: DUPLICATE
destination: "services/backups/README.md, docs/BACKUPS.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified DUPLICATE; current information is in `services/backups/README.md, docs/BACKUPS.md`. Describes 10 components and the old restore test; superseded.

# Backups and Recovery
# Backups and Recovery

## Automated stack backups (nightly)
Since **2026-08-14** the whole stack is backed up nightly by **`services/backups/avrana-backup.sh`** (user systemd timer `avrana-backup.timer`, daily **02:30**). Output → `/mnt/avrana_media/.backups/avrana/<UTC-timestamp>/`: the **media array (`/dev/sdb1`), a different physical disk** from the root LV where the databases actually live, so a root-disk failure or corruption is recoverable. Retention **7** daily runs. Aborts (and records the alarm in `LAST_RUN.json`) if the array has **< 20 GB** free.

### What is captured (10 components)
| Component | Artifact | Method |
|---|---|---|
| Audiobookshelf | `absdatabase.sqlite` + `metadata.tar.zst` | SQLite online `.backup` + tar of items/authors |
| Authentik | `authentik.pgdump.zst` | `pg_dump` in-container |
| BookStack | `bookstack.sql.zst` + `bookstack.env` + `bookstack-uploads.tar.zst` | `mariadb-dump` + `.env` (`APP_KEY`) + uploaded images/files |
| Audible connector | `connector.db` | SQLite online `.backup` (**never** `profiles/`: live Audible tokens) |
| Komga | `database.sqlite` | SQLite online `.backup` |
| Calibre-Web | `app.db`, `cwa.db`, `calibre-metadata.db` | SQLite online `.backup` |
| Seerr | `db.sqlite3` + `settings.json` | SQLite online `.backup` + copy |
| Jellyfin | `jellyfin-config.tar.zst` | tar of config (regenerable caches excluded) |
| Stack config | `stack-config.tar.zst` | allowlisted compose + `.env` + `secrets/` + Authentik blueprints + `deploy/` |
| Cloudflared | `cloudflared-config.tar.zst` | `~/.cloudflared/*.yml` + tunnel credentials + `cert.pem` (added 2026-08-16) |

SQLite databases are always copied with the **online `.backup` API, never a raw `cp`**, so a copy taken mid-write stays consistent (Seerr and others run in WAL mode). Each component fails independently; the run exits non-zero if **any** fail. Every run writes `MANIFEST.txt` (sha256 of every file) and updates `../LAST_RUN.json`.

> **`stack-config` is an allowlist, not an exclude-list.** The `services/<name>/` dirs also hold cloned source trees, live DB data dirs, venvs, and: critically: the connector's `profiles/` with **live Audible tokens**. Only the deployment artifacts are enumerated, so none of that is ever swept into a backup.

### The restore is tested
A backup you have never restored is a hypothesis. **`services/backups/restore-test.sh`** verifies the manifest checksums, reconstructs a config + metadata dir from the newest backup, boots a **throwaway** Audiobookshelf on it (its own port/container, the library mounted read-only, the live ABS never touched) and asserts it comes up `isInit=true` with the library items and users intact. **Last verified 2026-08-16: 277 items, 5 users, clean boot.** Re-run it after any change to the backup script.

### Monitoring / alerting
`scripts/services-health.sh` (15-min `services-health.timer`) already alerts on disk **≥90%** for `/` and the array, and now **also fails if the backup is missing, stale (>26 h), or not clean**: so a silently-dead backup timer raises an alert instead of rotting.
```bash
cat /mnt/avrana_media/.backups/avrana/LAST_RUN.json     # last run: ok / partial / aborted
systemctl --user list-timers avrana-backup.timer        # next scheduled run
journalctl --user -u avrana-backup.service -n 50        # last run log
```

### Restore procedures
Full per-component steps are in **`services/backups/README.md`**. Always `sha256sum -c MANIFEST.txt` first. Quick reference:
- **Audiobookshelf**: stop ABS → `cp` the DB into `services/audiobookshelf/config/` → extract `metadata.tar.zst` into `.../metadata` → start.
- **Authentik / BookStack**: pipe the dump into `psql` / `mariadb` inside the running DB container. BookStack also needs the matching `APP_KEY` from `bookstack.env` **and** the uploads tar extracted into `config/www`.
- **SQLite services** (connector, Komga, Calibre-Web, Seerr): stop the container → drop the `.db` in → start.

### Radarr / Sonarr / Prowlarr (added 2026-08-16, now 11 components)

They were absent from this script entirely, so their only copies were each service's own
scheduled backups in `/config/Backups` **on the root LV** - exactly the disk this script exists to
survive. Radarr had just gained 62 custom formats and two TRaSH profiles, none of it backed up
anywhere durable.

`backup_arr` captures, per service: the main SQLite DB via the online `.backup` API, plus
**`config.xml`**, which holds the API key and bind settings and **cannot be rebuilt from the DB**.
`config.xml` is written **0600** inside the backup. `logs.db` is skipped on purpose.

`restore-test.sh` now verifies them **without touching the live services**: restores each into the
throwaway work dir, runs **`PRAGMA integrity_check`** (the real test of a copied SQLite file), asserts
the tables a restore depends on are present and populated, and validates `config.xml` parses as XML
with the required elements and a plausible `ApiKey`. **No secret value is ever printed** - the check
asserts on length only. Throwaway \*arr instances are deliberately not booted: each would need its
own port and would try to reach indexers.

**Verified 2026-08-16:** 11/11 components green (`arr` = 13 MB); restore test PASSED with radarr
`QualityProfiles=9 CustomFormats=62 Movies=26`, sonarr `QualityProfiles=6 Series=3`, prowlarr
`Indexers=1`, all three `config.xml` valid.

### The backup tree is no longer readable by the media containers (fixed 2026-08-16)

Until 2026-08-16, `radarr`, `sonarr` and `jellyfin` bind-mounted the array root read-write as
**uid 1000, the same uid that owns the backups**, so every one of them could read Authentik's full
`pg_dump` and delete the entire backup tree. Fixed in *Docker Hardening & Networking* (a tmpfs
shadow for the \*arr, narrowed read-only mounts for jellyfin and komga). The cloudflared **tunnel
credentials are only in this backup because of that fix**: if any container is ever given the array
root again, the backup starts leaking the tunnel's identity. Re-check with:

```bash
docker exec radarr sh -c 'ls -A /data/.backups'   # must be empty
```

### Backup coverage, corrected and closed 2026-08-28

**Correction to the earlier note on this page.** It previously claimed, citing an extraction of
`stack-config.tar.zst`, that Home Assistant and Tracearr were absent from the backup entirely.
**That was wrong** — the check used the wrong path (`<run>/stack-config.tar.zst` instead of
`<run>/stack-config/stack-config.tar.zst`) and so listed an empty archive. `stack-config`
globs `services/*/docker-compose.yml` and `services/*/.env`, and both services' compose and env
files **were** captured all along.

The real gap was narrower but still serious: their **runtime state** was uncaptured. That is
now closed. The script writes **17 components**; this page previously described 10, then 11.

| Added | Artifact | Method |
|---|---|---|
| **Home Assistant** | `ha-config.tar.zst` + `home-assistant_v2.db` | tar **inside the container** + SQLite online `.backup` |
| **Tracearr** | `tracearr.pgdump.zst` | `pg_dump` inside the `tracearr` container |
| **systemd** | `system/`, `user/`, `fstab`, enablement state | file copies |

**Why the Home Assistant archive is built inside the container.** `config/.storage/auth`,
`core.config`, `http`, `onboarding` and `auth_provider.homeassistant` are **root-owned 0600**,
and HA runs as root. A host-side `tar` as `cody` exits 2 on exactly those files — the auth store
and the **ESPHome pairing keys** — while still producing a plausible, non-empty archive. That
failure mode is silent, which is why `restore-test.sh` now asserts those specific paths are
present rather than just checking the archive is non-empty.

**Why Tracearr needs an in-container dump.** The `supervised` image runs Postgres on
`127.0.0.1:5432` *inside the app container*; `/data/postgres` is root-owned on the host. A tar
of `services/tracearr/` captures nothing. `redisdata/` is skipped as cache; `appdata/` and
`backupdata/` are empty.

**Why the systemd layer is now captured.** `deploy/systemd/` tracks 11 units in Git, but the
host runs **51** custom units. The unrepresented ones include SABnzbd, mylar3, Plex, the health
API and all three cloudflared tunnels, plus the `/etc/fstab` line for the mergerfs union Komga
depends on. Without them a restore rebuilds every container and still does not bring the host
back.

**A reporting bug fixed at the same time.** `backup_omnibus` reported through an *undefined*
`warn` and a return value nothing read, so omnibus appeared in neither `ok[]` nor `failed[]`:
a broken omnibus backup left `status: "ok"` and the health check saw nothing. It now uses
`good`/`fail` like every other component.

**Verified end to end** against a throwaway `AVRANA_BACKUP_ROOT` (production untouched):
17/17 components `ok`, and `restore-test.sh` PASSED including the new assertions —
HA archive carrying auth store + ESPHome keys (680 entries), recorder `integrity_check` ok,
Tracearr dump complete with 934 tables, systemd layer 26 system + 25 user units + fstab.

### Which disk is actually fragile

The design assumes the root SSD is the part that fails. The hardware says otherwise: the SSD is
an internal Samsung SATA SSD, while `/dev/sdb` — holding the media **and** `.backups` **and**
Docker's `data-root` — is a **spinning disk in a USB enclosure**.

- **SSD dies:** recoverable. Every database and all stack config survive on the array.
- **Array dies:** **not** recoverable. Media, every backup, all Docker images/volumes and every
  container writable layer are lost together.

That asymmetry is the argument for the off-host copy below, independent of the media.

### Known limitation: not yet off-host
Backups live on the media array; if the **array itself** dies, media *and* these backups are gone together. True disaster recovery needs an off-host copy: the next step is an `rclone` sync of `/mnt/avrana_media/.backups/` to B2/R2 on its own timer (needs credentials); the tree is self-contained and ready for it. Media itself is intentionally **not** backed up (re-obtainable via Libation / the \\*arr stack).

## Rollback archives (`/home/cody/backups/`)
- **Authoritative (post/pre hardening):** `container-hardening-20260813/compose-and-daemon.tar.gz`: verify with the adjacent SHA-256 before restoring.
- **Pre-hardening config+manifests:** `services-hardening-20260813/config-and-manifests.tar.gz`: **contains secrets and databases; keep private.** Restore individual files, don't blindly extract over live services.
- Narrower per-change snapshots: `homepage-widgets-*`, `homepage-*-widget-*`, `homepage-layout-*`, `remove-plex-references-*`.

## Health check
`scripts/services-health.sh` (systemd `services-health.timer`) checks HTTP readiness, container health/restarts, disk usage, backup freshness, Libation presence, Cloudflare units, and interrupted ABS embed files. Run it after changes.

## Verified in production, 2026-08-29

The extended script has now run through its **own systemd unit** (not by hand) against the real
backup root, and the restore test passes on the resulting run:

- `LAST_RUN.json`: `status: ok`, **17 components, 0 failed**, 162 MB, retention still 7.
- New components present and non-empty: `home-assistant`, `tracearr`, `systemd`, plus `omnibus`
  now reporting for the first time.
- `restore-test.sh` **PASSED** on that run, including all four new assertions.

> **One operational consequence.** The new assertions mean `restore-test.sh` **fails against any
> backup taken before 2026-08-29**, because those runs genuinely lack the components. That is the
> check working, not a regression — but do not be alarmed by it when testing an older retained
> run. All 7 retained runs will satisfy it once a week of nightlies has rotated through.
