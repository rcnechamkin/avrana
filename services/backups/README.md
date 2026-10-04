# Avrana stack backups

Automated nightly backup of the **non-recoverable state** of the Avrana stack — the
databases, config, and secrets that no media re-download could rebuild. Media itself is not
backed up (it is large and re-obtainable via Libation / the \*arr stack).

## What, where, when

- **Script:** `avrana-backup.sh` — one self-contained run per invocation.
- **Destination:** `/mnt/avrana_media/.backups/avrana/<UTC-timestamp>/` — the media array
  (`/dev/sdb1`), a **different physical disk** from the root LV where these databases live, so
  a root-disk failure or corruption is recoverable.
- **Schedule:** daily at 02:30 local via the user systemd timer `avrana-backup.timer`.
- **Retention:** 7 daily runs (`AVRANA_BACKUP_KEEP`).
- **Safety valve:** aborts before writing if the array has < 20 GB free
  (`AVRANA_BACKUP_MIN_FREE_GB`) and records the alarm in `LAST_RUN.json`.

Each run writes `MANIFEST.txt` (sha256 + size of every file) and updates
`../LAST_RUN.json` (machine-readable status the health check reads).

### Components captured

| Component | Artifact | Method |
|---|---|---|
| Audiobookshelf | `absdatabase.sqlite` + `metadata.tar.zst` | SQLite online `.backup` + tar of items/authors |
| Authentik | `authentik.pgdump.zst` | `pg_dump` inside the container |
| BookStack | `bookstack.sql.zst` + `bookstack.env` + `bookstack-uploads.tar.zst` | `mariadb-dump` + `.env` (`APP_KEY`) + uploaded images/files |
| Audible connector | `connector.db` | SQLite online `.backup` (**never** `profiles/` — live Audible tokens) |
| Komga | `database.sqlite` | SQLite online `.backup` |
| Beszel | `beszel-state.tar.zst` | Hub database/history, agent identity, and agent credentials |
| Calibre-Web | `app.db`, `cwa.db`, `calibre-metadata.db` | SQLite online `.backup` |
| Seerr | `db.sqlite3` + `settings.json` | SQLite online `.backup` + copy |
| Jellyfin | `jellyfin-config.tar.zst` | tar of config, excluding regenerable caches |
| Stack config | `stack-config.tar.zst` | allowlisted compose + `.env` + `secrets/` + Authentik blueprints + `deploy/` |

## Checking status

```bash
cat /mnt/avrana_media/.backups/avrana/LAST_RUN.json        # last run: ok / partial / aborted
systemctl --user list-timers avrana-backup.timer           # next scheduled run
journalctl --user -u avrana-backup.service -n 50           # last run log
```

The 15-minute `services-health.sh` check fails if `LAST_RUN.json` is missing, older than 26h
(a daily run was skipped), or not `ok` — so a silently-dead backup timer raises an alert.

## Is it actually restorable? (tested)

A backup you have never restored is a hypothesis. `restore-test.sh` verifies the manifest
checksums, reconstructs a config + metadata dir from the newest backup, boots a **throwaway**
Audiobookshelf on it (own port, own container, library mounted read-only — the live ABS is
never touched), and asserts it comes up `isInit=true` with the library items and users intact.

```bash
./services/backups/restore-test.sh            # newest backup
./services/backups/restore-test.sh /mnt/avrana_media/.backups/avrana/<ts>/   # a specific one
```

Run it after any change to the backup script. Last verified: 2026-08-14 (261 items, 4 users).

## Restore procedures

First: `cd <backup-dir> && sha256sum -c MANIFEST.txt` to confirm integrity.

**Audiobookshelf** — stop ABS, replace the DB, restore metadata, start:
```bash
docker compose -f services/audiobookshelf/docker-compose.yml down
cp <backup>/audiobookshelf/absdatabase.sqlite services/audiobookshelf/config/absdatabase.sqlite
zstd -dc <backup>/audiobookshelf/metadata.tar.zst | tar -C services/audiobookshelf/metadata -xf -
docker compose -f services/audiobookshelf/docker-compose.yml up -d
```

**Authentik** (Postgres) — into the running DB container:
```bash
zstd -dc <backup>/authentik/authentik.pgdump.zst \
  | docker exec -i authentik-postgresql sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker restart authentik-server authentik-worker
```
For a from-scratch rebuild, recreate an empty DB first, then pipe the dump in.

**BookStack** (MariaDB) — the `APP_KEY` in `bookstack.env` must match the DB or encrypted
fields are unreadable:
```bash
zstd -dc <backup>/bookstack/bookstack.sql.zst \
  | docker exec -i bookstack-mariadb sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
# ensure services/bookstack/.env carries the APP_KEY from <backup>/bookstack/bookstack.env
# restore uploaded page images/attachments:
zstd -dc <backup>/bookstack/bookstack-uploads.tar.zst | tar -C services/bookstack/config/www -xf -
```

**SQLite services** (connector, Komga, Calibre-Web, Seerr) — stop the container, drop the file
in, start. Example (connector):
```bash
docker compose -f services/avrana-audible-connector/docker-compose.yml stop connector
cp <backup>/avrana-audible-connector/connector.db services/avrana-audible-connector/data/connector.db
docker compose -f services/avrana-audible-connector/docker-compose.yml start connector
```

**Jellyfin** — stop, extract config over the config dir, start:
```bash
docker stop jellyfin
zstd -dc <backup>/jellyfin/jellyfin-config.tar.zst | tar -C /home/cody/docker/jellyfin/config -xf -
docker start jellyfin
```

**Stack config** — recover a lost compose file / secret / blueprint:
```bash
zstd -dc <backup>/stack-config/stack-config.tar.zst | tar -C /tmp/restore -xf -   # inspect first
```

## Limitations (known, documented)

- **Not off-host.** Backups live on the media array. That covers root-disk loss, but if the
  array itself dies, media *and* these backups are gone. True disaster recovery needs an
  off-host copy — the natural next step is an `rclone` sync of `/mnt/avrana_media/.backups/` to
  B2/R2 on its own timer (needs credentials). The tree is self-contained and ready for it.
- **Media is not backed up** — by design; it is re-obtainable via Libation / \*arr.
- **Audible `profiles/` are deliberately excluded** — they hold live Audible authorization;
  a user re-connects rather than restoring a credential.
