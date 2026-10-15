# Rebuilding Avrana from bare metal

For an administrator who has never seen this system. It assumes the old host is gone.
Every fact here was read from the running host on 2026-10-04. `services/backups/restore-test.py`
fails if this file stops matching the compose files (external networks) or the backup layout.

You need three things:

1. **This repository** (`rcnechamkin/avrana`, private).
2. **One backup run**, 1.1 GB. Local: `/mnt/avrana_media/.backups/avrana/<timestamp>/` if the media array
   survived. Off-host: Backblaze B2, encrypted (section 6).
3. **Secrets from 1Password** that are not in any backup you can open without them: the B2 key, the
   rclone crypt password and salt, the `cody` login password. See `docs/SECRETS.md`.

Do the sections in order. Commands are run as `cody` unless they start with `sudo`.

## 1. What the host is

| Item | Value |
|---|---|
| OS | Ubuntu Server 24.04 LTS, x86-64. Kernel 6.8. Hostname `avrana`. Timezone `America/Los_Angeles`. |
| User | `cody`, **uid 1000, gid 1000**. Containers and bind mounts assume 1000:1000. Member of `docker`, `sudo`, `adm`. |
| Address | **10.0.0.218/24**, gateway 10.0.0.1, obtained by **DHCP reservation on the router** for bridge `br0`. Compose files bind to this address literally; a different address means editing every port mapping. |
| Network config | netplan: `eno1` enslaved to bridge `br0`, DHCP on `br0`. `deploy/host/netplan-br0.example.yaml` is a reconstruction; the original is root-only and in no backup. |
| OS disk | 120 GB SSD, LVM. Root LV 58 GB, 58 GB left free in the VG. All application state lives under `/home/cody`. |
| Media array | One 8 TB ext4 filesystem mounted at **`/mnt/avrana_media`**, UUID `f2276a43-a56c-4e18-80a1-1845918243d4`, in a USB enclosure. It holds the media, **Docker's data-root**, and the local backups. A replacement disk has a new UUID: update `/etc/fstab` and `AVRANA_ARRAY_UUID` in `scripts/services-health.sh` and `deploy/storage/verify-array.sh`. |
| Docker | Ubuntu package `docker.io` 29.1.3. `/etc/docker/daemon.json` is exactly `deploy/host/daemon.json` (`data-root` = `/mnt/avrana_media/docker`). |
| Compose | **v2 only**: the plugin binary `docker-compose` v2.27.1 in `/home/cody/.docker/cli-plugins/`. Use `docker compose` (space). Do **not** install or use the `docker-compose` v1 package: v1 and v2 compute different config hashes and each recreates the other's containers. |
| SSH | Key-only: `deploy/host/sshd_config.d/00-avrana-pubkey-only.conf`. |

## 2. Base system

```bash
sudo apt update
sudo apt install docker.io mergerfs zstd sqlite3 jq curl git python3 python3-venv smartmontools sabnzbdplus lvm2
sudo usermod -aG docker cody          # then log out and back in
sudo loginctl enable-linger cody      # user timers must run without a login session
```

`deploy/host/packages-manual.txt` is the full list of manually installed packages on the old host. It
includes things you should not reinstall (section 9).

Compose v2 plugin (not packaged by Ubuntu at this version):

```bash
mkdir -p ~/.docker/cli-plugins
curl -fL https://github.com/docker/compose/releases/download/v2.27.1/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
docker compose version                # must print v2.27.1 or later
```

`cloudflared` is a manually installed binary at `/usr/local/bin/cloudflared` (2025.6.1 on the old host; any
current release works). Install the `.deb` from Cloudflare's release page.

SSH: copy `deploy/host/sshd_config.d/00-avrana-pubkey-only.conf` to `/etc/ssh/sshd_config.d/` only **after**
your public key is in `~/.ssh/authorized_keys` and a key login works. Then `sudo sshd -t && sudo systemctl reload ssh`.

## 3. Storage, before Docker starts

Docker must never start without the array, or it initialises an empty data-root on the SSD
(incident 2026-08-30).

1. Mount the array. Add the two lines from `deploy/host/fstab` that mention `/mnt/avrana_media` to
   `/etc/fstab` (the array line and the `comics_merged` mergerfs line). **Do not copy the root, `/boot`
   or swap lines**: they belong to the old disk.
2. Install the mount guards:

   ```bash
   sudo install -D -m 644 deploy/docker/docker-require-array.conf /etc/systemd/system/docker.service.d/require-array.conf
   sudo install -D -m 644 deploy/storage/dropins/sabnzbd-require-array.conf /etc/systemd/system/sabnzbd.service.d/require-array.conf
   sudo install -D -m 644 deploy/storage/dropins/mylar3-require-array.conf /etc/systemd/system/mylar3.service.d/require-array.conf
   sudo install -m 600 deploy/host/daemon.json /etc/docker/daemon.json
   sudo systemctl daemon-reload && sudo mount -a && sudo systemctl restart docker
   docker info --format '{{.DockerRootDir}}'      # must print /mnt/avrana_media/docker
   ```
3. If the array was lost, create the directory layout the services expect on the new disk, owned by
   `cody:cody`: `movies tv music audiobooks books calibre-library comics comics_omnibus/library
   comics_merged comics_incoming downloads incoming mylar3 .recycle .backups/avrana`. The media itself is
   not backed up anywhere (section 10).

## 4. Put the tree and the secrets in place

The repository mirrors the deployed layout. Production lives at **`/home/cody/avrana`**; the arr stack
and Jellyfin keep their state in **`/home/cody/docker`**.

```bash
git clone https://github.com/rcnechamkin/avrana.git /home/cody/avrana
mkdir -p /home/cody/docker/{radarr,sonarr,prowlarr,seerr/config/db,jellyfin/config,jellyfin/cache}
RUN=/path/to/backup/run               # e.g. /mnt/avrana_media/.backups/avrana/2026-10-04T09-33-09Z
( cd "$RUN" && sha256sum -c --quiet MANIFEST.txt ) && python3 /home/cody/avrana/services/backups/restore-test.py "$RUN"
```

Do not continue unless the restore test passes.

Secrets come back from the backup, not from Git. `stack-config/stack-config.tar.zst` holds every `.env`
(including `services/authentik/blueprints.env`, which the blueprints reference) and every `secrets/`
directory. Extract **only those**; the rest of that archive is an older copy of what Git already has:

```bash
cd /home/cody/avrana
zstd -dc "$RUN/stack-config/stack-config.tar.zst" | tar -xpf - --wildcards \
  'services/*/.env' 'services/*/*.env' 'services/*/secrets' \
  'services/backups/.env.alert' 'services/backups/rclone.conf'
mkdir -p ~/.cloudflared && zstd -dc "$RUN/cloudflared/cloudflared-config.tar.zst" | tar -C ~/.cloudflared -xpf -
chmod 700 ~/.cloudflared
```

(`.env.alert` and `rclone.conf` only exist in runs taken after they were configured; tar reports them as
not found otherwise, which is harmless.)

## 5. Restore application state

`services/backups/restore-map.txt` lists every artifact and its destination; it is the reference. Restore
with every service **stopped** (nothing has been started yet). The cases that bite:

| Artifact | Restore as | Why it matters |
|---|---|---|
| `calibre-web-automated/cwa.key` | `services/calibre-web-automated/config/.key` | **Renamed.** Without it `app.db` cannot be decrypted and every CWA login fails (September 2026). |
| `bookstack/bookstack.env` | `services/bookstack/.env` | Renamed. Holds `APP_KEY`. Only needed while BookStack still exists. |
| `omnibus/omnibus.env` | `services/omnibus/.env` | Renamed. `NEXTAUTH_SECRET` is the database encryption key. |
| `shelfarr/.encryption_keys`, `.secret_key_base` | `services/shelfarr/data/` | The database is unreadable without them. |
| `libation/libation-master.key` | `services/libation/config/` | Account settings are unreadable without it. |
| `home-assistant/ha-config.tar.zst` | untar into `services/home-assistant/` **with sudo** | Contains root-owned 0600 auth files; a non-root untar silently drops them. |
| `jellyfin/jellyfin-config.tar.zst` | untar into `/home/cody/docker/jellyfin/config` | Includes the database and artwork. Never run a library-wide metadata refresh afterwards; see `docs/findings/2026-09-23-jellyfin-artwork.md`. |
| `calibre-web-automated/calibre-metadata.db` | `/mnt/avrana_media/calibre-library/metadata.db` | Only if the array was lost. If the array survived, the live file is newer: leave it. |

The plain copies (SQLite databases and config files for the arr stack, Audiobookshelf, Komga, Seerr,
Shelfmark, Mylar, SABnzbd, the Audible connector, Libation) go to the paths in `restore-map.txt`.
Create the destination directories first; keep modes 600 on keys and `.env` files.

Databases that are restored **into a running database container** come in section 7 (Authentik,
Tracearr, BookStack).

## 6. Getting the backup from Backblaze B2 (only if the array is gone)

Install rclone (`sudo apt install rclone`, or use the `rclone/rclone` Docker image). Recreate the
configuration with the values from 1Password:

```bash
bash /home/cody/avrana/services/backups/offhost-setup.sh       # hidden prompts; writes services/backups/rclone.conf
python3 /home/cody/avrana/services/backups/offhost-backup.py --list
```

Pick the newest run marked `complete`, then download it. Only a run containing
`OFFHOST-COMPLETE.json` is a verified recovery set.

```bash
mkdir -p ~/restore && cd ~/restore
docker run --rm --user 1000:1000 -e RCLONE_CONFIG=/c/rclone.conf -v /home/cody/avrana/services/backups/rclone.conf:/c/rclone.conf:ro \
  -v "$PWD:/out" rclone/rclone copy avrana-offsite-daily:<RUN> /out/<RUN>
( cd <RUN> && sha256sum -c --quiet MANIFEST.txt )
```

Details, retention and the design are in `services/backups/OFFHOST.md`.

## 7. Bring the stack up

**External networks first.** Two compose networks are declared `external` and nothing creates the first one:

```bash
docker network create --subnet 10.220.25.0/24 avrana-ldap      # used by authentik and calibre-web-automated
```

`authentik_portal`, `authentik_kindle` and `authentik_olivetin` are also external, for `avrana-portal`,
`avrana-kindle-connector` and `olivetin` respectively (staged, not applied: `docs/runbooks/g1-network-isolation.md`).
They are created by the `authentik` project when its `server` service starts, which is why Authentik starts first
and why `docker compose down` must never be run in `services/authentik`.

Each directory under `services/` is its own Compose project, named after the directory, with **one
exception**: the arr stack in `services/media` runs as project **`docker`**, and Jellyfin is behind the
**`media`** profile. Home Assistant reads `COMPOSE_PROFILES=stt` from its `.env`.

```bash
cd /home/cody/avrana/services

# 1. identity: database first, restore, then the rest
( cd authentik && docker compose up -d postgresql )
zstd -dc "$RUN/authentik/authentik.pgdump.zst" | docker exec -i authentik-postgresql sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
( cd authentik && docker compose up -d )

# 2. arr stack and Jellyfin: project name and profile are mandatory
docker compose -p docker -f media/docker-compose.yml --profile media up -d

# 3. locally built images (Dockerfiles are in this repository)
for s in avrana-portal avrana-kindle-connector avrana-audible-connector avrana-imax-verify calibre-web-automated; do
  ( cd "$s" && docker compose build && docker compose up -d )
done

# 4. everything else
for s in audiobookshelf komga libation libation-status shelfmark shelfarr omnibus recyclarr completeseries \
         home-assistant homepage olivetin beszel tracearr; do
  ( cd "$s" && docker compose up -d )
done

# 5. Tracearr keeps Postgres (with TimescaleDB) inside its own container. NOT REHEARSED: the image
#    creates its schema on first start, so the dump may need an empty database first. If the load
#    reports existing objects, drop and recreate the `tracearr` database inside the container and
#    load again. Tracearr holds playback history only; nothing else depends on it.
zstd -dc "$RUN/tracearr/tracearr.pgdump.zst" | docker exec -i tracearr sh -c 'psql -U tracearr -d tracearr'
docker restart tracearr
```

Running `docker compose up` in `services/media` **without** `-p docker --profile media` creates a second
project and orphans Jellyfin. Bazarr (`optional` profile) and Kavita are not deployed.

BookStack is being retired; its content is in `docs/archive/bookstack/`. Rebuild it only if you need the
wiki itself: `( cd bookstack && docker compose up -d )`, then
`zstd -dc "$RUN/bookstack/bookstack.sql.zst" | docker exec -i bookstack-mariadb sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'`.

### Host services

```bash
# SABnzbd (apt package, runs as cody)
sudo install -m 644 /home/cody/avrana/deploy/host/systemd/sabnzbd.service /etc/systemd/system/
mkdir -p ~/.sabnzbd/admin   # then sabnzbd.ini and admin/history1.db from the backup

# Mylar3: upstream checkout, not in this repository
git clone https://github.com/mylar3/mylar3.git /home/cody/avrana/services/mylar3
cd /home/cody/avrana/services/mylar3 && git checkout cdc94a4 && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# then mylar.db and config.ini from the backup
sudo install -m 644 /home/cody/avrana/deploy/host/systemd/mylar3.service /etc/systemd/system/

# Cloudflare tunnel: the unit is in the backup (systemd/system/cloudflared-avrana.service)
sudo install -m 644 "$RUN/systemd/system/cloudflared-avrana.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sabnzbd mylar3 cloudflared-avrana
```

The tunnel reuses the restored credential file, so the 12 public hostnames in
`deploy/host/cloudflared/config.yml` work again without touching DNS.

### Timers (user units)

```bash
mkdir -p ~/.config/systemd/user
cp /home/cody/avrana/deploy/systemd/*.{service,timer,path} /home/cody/avrana/deploy/storage/systemd/* ~/.config/systemd/user/
rm -f ~/.config/systemd/user/avrana-cloudflared-restart.*      # system units, optional, never installed
systemctl --user daemon-reload
systemctl --user enable --now avrana-backup.timer services-health.timer avrana-boot-verify.timer \
  avrana-offhost.timer avrana-restore-test.timer omnibus-cache-purge.timer avrana-backup-trigger.path
```

## 8. Validate

```bash
docker ps --format '{{.Names}}' | wc -l                       # 40 with BookStack, 38 without
docker ps --filter health=unhealthy --format '{{.Names}}'     # must print nothing
/home/cody/avrana/deploy/storage/verify-array.sh              # array identity, mount, kernel log
/home/cody/avrana/scripts/services-health.sh                  # every line OK; exit 0
/home/cody/avrana/scripts/drift-check.py --quiet              # deployed tree matches Git
systemctl --user start avrana-backup.service                  # take a backup of the rebuilt host
python3 /home/cody/avrana/services/backups/restore-test.py    # and prove that backup restores
python3 /home/cody/avrana/services/backups/offhost-backup.py  # and ship it
```

`deploy/docker/verify-baseline.sh` expects the containers in `deploy/docker/expected-containers.txt`
and one tunnel per enabled `cloudflared*.service`. Then sign in through `https://auth.avrana.net` and
open one title in Jellyfin, Audiobookshelf, Komga and Calibre-Web.

The rebuild is done when the health check exits 0, a new backup reports `ok` with 23 components, the
restore test passes on it, and it is off-host.

## 9. What must NOT be restored blindly

- **`systemd/fstab` from the backup**: only the array and mergerfs lines. The rest describes the dead disk.
- **`systemd/system/*` wholesale**: it contains retired units (`cloudflared.service`, `cloudflared-comics`,
  `cloudflared-health`, `avrana.service`, `watch-health`, `comic-watcher`, `jdownloader2`, `whisper`,
  `remote-faster-whisper`, `summarize_lastfm`) and distribution units. Install only the three named above.
- **`systemd/user/*` wholesale**: it contains the retired Kern timers (`blackbox`, `fetch_lastfm`,
  `lastfm_fetcher`, `strava_fetch`, `summarize_lastfm`, `tag_all`, `parse_health_export`) and dead
  `cloudflared.service` / `mylar.service`. Use `deploy/systemd/` from Git.
- **`kern-data/`**: personal data from the retired Kern project. Keep the archive; do not unpack it into
  the production tree.
- **The whole `stack-config` archive over a fresh clone**: it would replace current Git files with last
  night's copies and re-create the Kern-era `.gitignore`.
- **Old recovery or migration scripts** from `rcnechamkin/Kern-Ecosystem` (`restore-stack*.sh`,
  `renumber-networks*.sh`, `apply-address-pools*`). They caused or belong to the August incidents.
- **Plex, nginx, libvirt/qemu, podman, the second Cloudflare tunnel (`comics.avrana.media`)**: installed on
  the old host, scheduled for retirement, not part of the rebuild.
- **`deploy/ufw/`**: a staged firewall that has never been applied. Do not apply it as part of a rebuild.
- **Jellyfin**: no library-wide refresh, no database replacement from older sets.
- Never `source` or `eval` a file found by searching the disk. The September 2026 data loss was a shell
  sourcing a log file.

## 10. Not recoverable from Git + backup

Know these before you start:

- **The media library** (about 2.4 TB): never backed up, by design.
- **Jellyfin transcodes/cache, Audiobookshelf caches, Docker images**: regenerated or re-pulled. Several
  compose files use unpinned `latest` tags, so a rebuild may get newer versions than the old host ran.
- **UniFi OS Server** (rootless Podman under user `uosserver`): in no backup. Reinstall from Ubiquiti and
  restore from UniFi's own backup if one exists (`docs/services/unifi-os-server.md`).
- **`/etc/netplan`**, `/etc/docker/daemon.json` (content recorded here), smartd and unattended-upgrades
  settings (copies in `deploy/host/`): recreate by hand.
- **Recovery evidence** from September 2026 (`/mnt/avrana_media/recovery-20260920`, the golden backup):
  local only.

## 11. How far this guide has been tested

It has **not** been executed end to end on a spare machine. That rehearsal is on the roadmap. Checked on
2026-10-04 against the running host and backup run `2026-10-04T09-33-09Z`:

| Checked | Result |
|---|---|
| Host facts in section 1 (OS, uid, address, Docker, Compose, data-root, UUID) | read from the host |
| All compose files parse (`docker compose config -q`) | 23 of 23 |
| Secret extraction command in section 4 | selects the env files (14 since `blueprints.env`, 2026-10-06), 2 `secrets/` directories, `.env.alert` and `rclone.conf`; no blueprint, since none carries a secret any more |
| Authentik database restore (section 7, step 1) | loaded into a disposable Postgres 16 with no network: 0 errors, 215 tables, 18 users, 16 flows |
| BookStack database restore | loaded into a disposable MariaDB 11.8 with no network: 41 tables, 72 pages |
| Every SQLite database, archive and dump in the run | `restore-test.py`: all pass |
| Audiobookshelf boots from restored data | `restore-test.py --boot-abs` |
| Backup run retrieved from B2 and verified | see the Batch 2 ledger |

Not rehearsed: installing the base system, building the six local images from a clean clone, the Home
Assistant and Jellyfin untar steps, the Tracearr restore, Mylar3 from a fresh upstream clone, and
re-establishing the Cloudflare tunnel on new hardware.
