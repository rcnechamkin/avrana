#!/usr/bin/env bash
# Avrana stack backup — captures the non-recoverable state (databases, config, secrets) of
# every service to the media array, which is a *different physical disk* (/dev/sdb1) from the
# root LV where those databases actually live. A root-disk failure or corruption is therefore
# recoverable; see the LIMITATION note below about true off-host disaster recovery.
#
# Design:
#   - Each component is a function that is allowed to fail independently. One broken service
#     never skips the others; the overall run exits non-zero if ANY component failed, so the
#     systemd unit (and thus monitoring) goes red.
#   - SQLite databases are copied with the online .backup API (never a raw cp of a live file),
#     so a copy taken mid-write is still consistent — Seerr and others run in WAL mode.
#   - A MANIFEST with sha256 + sizes is written so a restore can verify integrity, and a
#     machine-readable LAST_RUN.json is emitted for the dashboard / disk-alert check.
#
# LIMITATION (documented, not a bug): backups land on the media array. That protects against
# root-disk loss, but if the array itself dies both media AND these backups are gone. True
# disaster recovery needs an off-host copy (rclone to B2/R2). That is a separate follow-up
# with its own credentials; this script writes a self-contained tree that such a job can sync.
set -uo pipefail

# Everything this script writes is a database, a credential or a config that names them. Without
# this the run directories were 0775 and the SQLite copies, the Authentik dump and
# seerr/settings.json were world-readable, i.e. readable by every other local account (plex,
# uosserver) on a world-traversable mount. Only the files that were chmod'ed by hand were
# private. (Batch 1, finding A8.)
umask 077

# ---- config ---------------------------------------------------------------------------------
REPO="/home/cody/avrana"
DEST_ROOT="${AVRANA_BACKUP_ROOT:-/mnt/avrana_media/.backups/avrana}"
KEEP="${AVRANA_BACKUP_KEEP:-7}"           # daily backups to retain
MIN_FREE_GB="${AVRANA_BACKUP_MIN_FREE_GB:-20}"  # abort if the array has less headroom than this
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
DEST="$DEST_ROOT/$TS"
PARTIAL="$DEST.partial"

ZSTD=(zstd -q -19 -T0)
FAILED=()
OK=()

log()  { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
FAIL_DETAIL=()
fail() { FAILED+=("$1"); FAIL_DETAIL+=("$1: ${2:-}"); log "FAIL  $1: ${2:-}"; }
good() { OK+=("$1");     log "ok    $1 (${2:-})"; }

# Tell someone when a run does not finish clean -- an abort included (array not mounted, disk
# full). Until Batch 1 the only signal was a failed unit that the health check reported to the
# journal. Runs against an alternate root (AVRANA_BACKUP_ROOT, i.e. tests and checkpoints) and
# AVRANA_BACKUP_NO_ALERT=1 stay quiet. The mail carries component names and reasons, never data.
ABORT_REASON=""
alert_on_exit() {
  local rc=$?
  (( rc == 0 )) && return
  [[ -z "${AVRANA_BACKUP_ROOT:-}" && "${AVRANA_BACKUP_NO_ALERT:-0}" != 1 ]] || return
  {
    printf 'avrana-backup.sh exited %s at %s\n' "$rc" "$(date -u +%FT%TZ)"
    [[ -n "$ABORT_REASON" ]] && printf 'aborted: %s\n' "$ABORT_REASON"
    (( ${#FAIL_DETAIL[@]} )) && printf 'failed: %s\n' "${FAIL_DETAIL[@]}"
    printf '\nLog: journalctl --user -u avrana-backup.service -n 80\n'
  } | python3 "$REPO/scripts/avrana-alert.py" --subject "backup FAILED (exit $rc)" >/dev/null 2>&1 \
    || log "WARN  alert not sent (rc=$?)"
}
trap alert_on_exit EXIT

# Consistent online copy of a SQLite DB (host-side file) to $2. Handles WAL; never touches
# the source. Falls back loudly if the source is missing.
sqlite_backup() {
  local src="$1" dst="$2"
  [[ -f "$src" ]] || { echo "missing $src" >&2; return 1; }
  python3 - "$src" "$dst" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
with d:
    s.backup(d)
s.close(); d.close()
PY
}

# ---- preflight ------------------------------------------------------------------------------
avail_gb() { df -PB1G "$1" | awk 'NR==2{print $4+0}'; }

# The destination lives on the media array. If that array is not mounted, $DEST_ROOT is a plain
# directory on the root LV: the mkdir below would cheerfully create it, the df headroom check would
# measure the WRONG filesystem, and LAST_RUN.json would record a success for a backup that does not
# exist. Refuse before anything is created. Nothing is written to $DEST_ROOT on this path -- doing
# so would itself create the directory being refused. The non-zero exit marks the unit failed,
# which is what services-health.sh reports. (Incident 2026-08-30, fault 2.)
ARRAY_ROOT="${AVRANA_ARRAY_ROOT:-/mnt/avrana_media}"
if ! mountpoint -q "$ARRAY_ROOT"; then
  log "ABORT: $ARRAY_ROOT is not a mount point -- the array is not mounted."
  log "       Refusing to write a backup to the root LV or to record a false success."
  ABORT_REASON="$ARRAY_ROOT is not a mount point (array not mounted)"
  exit 4
fi

mkdir -p "$DEST_ROOT" || { echo "cannot create $DEST_ROOT"; exit 3; }
free_gb="$(avail_gb "$DEST_ROOT")"
if (( free_gb < MIN_FREE_GB )); then
  log "ABORT: only ${free_gb}G free on backup volume (< ${MIN_FREE_GB}G). Refusing to fill the disk."
  # Still record the alarm so the dashboard/timer surfaces it.
  printf '{"status":"aborted","reason":"low_disk","free_gb":%s,"at":"%s"}\n' \
    "$free_gb" "$(date -u +%FT%TZ)" > "$DEST_ROOT/LAST_RUN.json"
  ABORT_REASON="only ${free_gb}G free on the backup volume (minimum ${MIN_FREE_GB}G)"
  exit 3
fi
mkdir -p "$PARTIAL"

# ---- components -----------------------------------------------------------------------------
backup_abs() {
  local d="$PARTIAL/audiobookshelf"; mkdir -p "$d"
  # The DB is the only copy of users, listening progress, library definitions, API tokens, and
  # the allowedOrigins CORS whitelist + manual metadata edits that live nowhere else.
  sqlite_backup "$REPO/services/audiobookshelf/config/absdatabase.sqlite" "$d/absdatabase.sqlite" \
    || { fail audiobookshelf "db copy"; return; }
  # metadata/items + authors carry ABS's own cover/metadata.json edits (regenerable caches are
  # excluded to keep this small and fast).
  tar -C "$REPO/services/audiobookshelf/metadata" -cf - items authors 2>/dev/null | "${ZSTD[@]}" -o "$d/metadata.tar.zst" 2>/dev/null \
    || { fail audiobookshelf "metadata tar"; return; }
  good audiobookshelf "$(du -sh "$d" | cut -f1)"
}

backup_authentik() {
  local d="$PARTIAL/authentik"; mkdir -p "$d"
  # The identity provider: users, groups, apps, OIDC providers, invite flows, blueprints state.
  if docker exec authentik-postgresql sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>/dev/null \
       | "${ZSTD[@]}" -o "$d/authentik.pgdump.zst" 2>/dev/null && [[ -s "$d/authentik.pgdump.zst" ]]; then
    good authentik "$(du -sh "$d" | cut -f1)"
  else
    fail authentik "pg_dump"
  fi
}

backup_bookstack() {
  local d="$PARTIAL/bookstack"; mkdir -p "$d"
  # BookStack content is three parts that must be restored together: the DB, the APP_KEY
  # (without it the DB's encrypted fields are unrecoverable), AND user-uploaded images/files
  # (page images, attachments, drawings) which live on disk, not in the DB.
  local db_ok=1 env_ok=1 up_ok=1
  docker exec bookstack-mariadb sh -c 'mariadb-dump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' 2>/dev/null \
    | "${ZSTD[@]}" -o "$d/bookstack.sql.zst" 2>/dev/null && [[ -s "$d/bookstack.sql.zst" ]] || db_ok=0
  cp "$REPO/services/bookstack/.env" "$d/bookstack.env" 2>/dev/null || env_ok=0
  # uploads/images/files only — not framework/cache/themes (app code, reinstalled with the image).
  tar -C "$REPO/services/bookstack/config/www" -cf - uploads images files 2>/dev/null \
    | "${ZSTD[@]}" -o "$d/bookstack-uploads.tar.zst" 2>/dev/null || up_ok=0
  if (( db_ok && env_ok && up_ok )); then good bookstack "$(du -sh "$d" | cut -f1)"
  else fail bookstack "db=$db_ok env=$env_ok uploads=$up_ok"; fi
}

backup_connector() {
  local d="$PARTIAL/avrana-audible-connector"; mkdir -p "$d"
  # Ownership map / jobs / audit only. Deliberately NOT profiles/ — those hold live Audible
  # auth tokens; backing them up would persist a credential we work hard to keep ephemeral.
  sqlite_backup "$REPO/services/avrana-audible-connector/data/connector.db" "$d/connector.db" \
    && good connector "$(du -sh "$d" | cut -f1)" || fail connector "db copy"
}

backup_shelfarr() {
  local d="$PARTIAL/shelfarr"; mkdir -p "$d"
  # production.sqlite3 alone is NOT restorable. Shelfarr auto-generates its
  # encryption keys on first run and stores them beside the DB; the key cannot
  # be supplied from the environment (it must decrypt the credentials.yml.enc
  # baked into the image). Lose .encryption_keys/.secret_key_base and the DB is
  # undecryptable, so both are captured here at 0600.
  # The cache/queue/cable SQLite files are deliberately skipped: regenerable.
  local src="$REPO/services/shelfarr/data" bad=()
  sqlite_backup "$src/production.sqlite3" "$d/production.sqlite3" || bad+=(production.sqlite3)
  for f in .encryption_keys .secret_key_base; do
    if cp "$src/$f" "$d/$f" 2>/dev/null; then chmod 600 "$d/$f"; else bad+=("$f"); fi
  done
  (( ${#bad[@]} )) && fail shelfarr "${bad[*]}" || good shelfarr "$(du -sh "$d" | cut -f1)"
}

backup_omnibus() {
  local d="$PARTIAL/omnibus"; mkdir -p "$d"
  # Omnibus state = the SQLite DB **plus** NEXTAUTH_SECRET. That secret is not
  # just a session key: upstream uses it as the database ENCRYPTION MASTER KEY,
  # so omnibus.db restored without it is undecryptable and worthless. Both are
  # captured here; the .env copy is 0600.
  # Deliberately NOT backed up: config/cache, config/logs (regenerable), and the
  # comics themselves under /mnt/avrana_media/comics_omnibus -- media is out of
  # scope for this job, matching how the Mylar/Komga libraries are treated.
  local src="$REPO/services/omnibus" bad=()
  sqlite_backup "$src/config/omnibus.db" "$d/omnibus.db" || bad+=(omnibus.db)
  if cp "$src/.env" "$d/omnibus.env" 2>/dev/null; then chmod 600 "$d/omnibus.env"; else bad+=(.env); fi
  # Reports through good/fail like every other component. It previously called an
  # UNDEFINED `warn` and returned a status nobody read, so omnibus appeared in neither
  # ok[] nor failed[] in LAST_RUN.json -- a broken omnibus backup left status="ok" and the
  # health check saw nothing. Fixed 2026-08-28.
  if [ ${#bad[@]} -gt 0 ]; then fail omnibus "missing ${bad[*]}"; return; fi
  good omnibus "$(du -sh "$d" | cut -f1)"
}

backup_komga() {
  local d="$PARTIAL/komga"; mkdir -p "$d"
  local bad=()
  sqlite_backup "$REPO/services/komga/config/database.sqlite" "$d/database.sqlite" || bad+=(database.sqlite)
  # OIDC client configuration is required to restore SSO, not a regenerable cache.
  if cp "$REPO/services/komga/config/application.yml" "$d/application.yml" 2>/dev/null; then
    chmod 600 "$d/application.yml"
  else
    bad+=(application.yml)
  fi
  if (( ${#bad[@]} )); then fail komga "${bad[*]}"; else good komga "$(du -sh "$d" | cut -f1)"; fi
}

backup_beszel() {
  local d="$PARTIAL/beszel"; mkdir -p "$d"
  # Hub data contains systems, alerts, users and history. Agent data and
  # credentials are required for the local system to reconnect after restore.
  if tar -C "$REPO/services/beszel" -cf - data agent-data secrets 2>/dev/null \
      | "${ZSTD[@]}" -o "$d/beszel-state.tar.zst" 2>/dev/null \
      && [[ -s "$d/beszel-state.tar.zst" ]]; then
    chmod 600 "$d/beszel-state.tar.zst"
    good beszel "$(du -sh "$d" | cut -f1)"
  else
    fail beszel "state archive"
  fi
}

backup_home_assistant() {
  local d="$PARTIAL/home-assistant"; mkdir -p "$d"
  # Kern HQ. The irreplaceable part is config/.storage: the auth store, the device and entity
  # registries, config_entries, and esphome.encryption_keys -- the Voice PE pairing key, which
  # cannot be regenerated without re-provisioning the puck. secrets.yaml lives here too, so the
  # archive is 0600.
  #
  # Excluded on purpose: *.log* (rotated by HA), deps/ and tts/ (regenerable caches), and the
  # raw home-assistant_v2.db* files -- the recorder is SQLite in WAL mode and a tar of a live
  # WAL database can be torn, so it is copied separately through the online .backup API below,
  # exactly as every other SQLite component in this script.
  # The archive is created INSIDE the container. config/.storage/{auth,core.config,http,
  # onboarding,auth_provider.homeassistant} are root-owned 0600, and HA runs as root, so a
  # host-side tar as `cody` exits 2 and silently omits exactly the files that matter -- the auth
  # store and the ESPHome pairing keys. Verified 2026-08-28: host tar => "Cannot open: Permission
  # denied" on five .storage entries while still producing a plausible-looking archive.
  if docker exec home-assistant tar -C / \
        --exclude='config/home-assistant_v2.db*' \
        --exclude='config/*.log*' \
        --exclude='config/deps' \
        --exclude='config/tts' \
        --exclude='config/.cloud' \
        -cf - config 2>/dev/null \
      | "${ZSTD[@]}" -o "$d/ha-config.tar.zst" 2>/dev/null \
      && [[ -s "$d/ha-config.tar.zst" ]]; then
    chmod 600 "$d/ha-config.tar.zst"
  else
    fail home-assistant "config archive"; return
  fi
  # Recorder history via the online backup API, run inside the container (the host has no
  # sqlite3 binary; the HA image ships python3 with the sqlite3 module).
  if docker exec home-assistant python3 -c        "import sqlite3,sys
src=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
dst=sqlite3.connect('/tmp/ha-recorder.db')
src.backup(dst); dst.close(); src.close()" 2>/dev/null      && docker cp home-assistant:/tmp/ha-recorder.db "$d/home-assistant_v2.db" 2>/dev/null      && [[ -s "$d/home-assistant_v2.db" ]]; then
    docker exec home-assistant rm -f /tmp/ha-recorder.db 2>/dev/null || true
    chmod 600 "$d/home-assistant_v2.db"      # docker cp keeps the container's 0644; umask does not apply
    good home-assistant "$(du -sh "$d" | cut -f1)"
  else
    # The config archive is the part that matters; a missing recorder is degraded, not fatal.
    fail home-assistant "recorder online backup"
  fi
}

backup_tracearr() {
  local d="$PARTIAL/tracearr"; mkdir -p "$d"
  # Jellyfin watch analytics. The "supervised" image runs Postgres INSIDE the app container on
  # 127.0.0.1:5432, so the dump runs in `tracearr` itself, not a separate database container.
  # /data/postgres is root-owned on the host, which is why a plain tar of services/tracearr/
  # silently captures nothing.
  #
  # redisdata/ is deliberately skipped: it is the job/cache layer and rebuilds itself.
  # appdata/ and backupdata/ are empty.
  if docker exec tracearr sh -c 'pg_dump -U tracearr -d tracearr' 2>/dev/null        | "${ZSTD[@]}" -o "$d/tracearr.pgdump.zst" 2>/dev/null        && [[ -s "$d/tracearr.pgdump.zst" ]]; then
    good tracearr "$(du -sh "$d" | cut -f1)"
  else
    fail tracearr "pg_dump"
  fi
}

backup_calibreweb() {
  local d="$PARTIAL/calibre-web-automated"; mkdir -p "$d"
  # app.db = CWA users/settings; cwa.db = CWA automation state; calibre-library/metadata.db =
  # the actual ebook catalogue (the library itself lives on the array already).
  local bad=()
  sqlite_backup "$REPO/services/calibre-web-automated/config/app.db" "$d/app.db"       || bad+=(app.db)
  sqlite_backup "$REPO/services/calibre-web-automated/config/cwa.db" "$d/cwa.db"       || bad+=(cwa.db)
  sqlite_backup "/mnt/avrana_media/calibre-library/metadata.db" "$d/calibre-metadata.db" || bad+=(metadata.db)
  # config/.key is CWA's encryption key: app.db stores values encrypted with it, so the DB is only
  # decryptable when the key is restored alongside it. Kept 0600 like other captured secrets.
  if cp "$REPO/services/calibre-web-automated/config/.key" "$d/cwa.key" 2>/dev/null; then chmod 600 "$d/cwa.key"; else bad+=(.key); fi
  if (( ${#bad[@]} )); then fail calibre-web "${bad[*]}"; else good calibre-web "$(du -sh "$d" | cut -f1)"; fi
}

backup_seerr() {
  local d="$PARTIAL/seerr"; mkdir -p "$d"
  sqlite_backup "/home/cody/docker/seerr/config/db/db.sqlite3" "$d/db.sqlite3" \
    && cp "/home/cody/docker/seerr/config/settings.json" "$d/settings.json" 2>/dev/null \
    && good seerr "$(du -sh "$d" | cut -f1)" || fail seerr "db/settings"
}

backup_arr() {
  # Radarr / Sonarr / Prowlarr. These were missing from this script entirely until 2026-08-16,
  # which meant the only copies of their state were each service's own scheduled backups under
  # /config/Backups -- on the ROOT LV, i.e. exactly the disk this whole script exists to survive.
  #
  # Per service: the main SQLite DB (quality profiles, custom formats, the library/series/indexer
  # records) plus config.xml, which holds the API key and bind settings and is NOT reconstructable
  # from the DB. logs.db is deliberately skipped -- large, churny, and worthless to a restore.
  local d="$PARTIAL/arr"; mkdir -p "$d"
  local bad=() svc
  for svc in radarr sonarr prowlarr; do
    local src="/home/cody/docker/$svc"
    mkdir -p "$d/$svc"
    sqlite_backup "$src/$svc.db" "$d/$svc/$svc.db" || { bad+=("$svc.db"); continue; }
    # config.xml carries the API key: keep it 0600 in the backup, same as bookstack.env.
    if cp "$src/config.xml" "$d/$svc/config.xml" 2>/dev/null; then
      chmod 600 "$d/$svc/config.xml"
    else
      bad+=("$svc/config.xml")
    fi
  done
  if (( ${#bad[@]} )); then fail arr "${bad[*]}"; else good arr "$(du -sh "$d" | cut -f1)"; fi
}

backup_jellyfin() {
  local d="$PARTIAL/jellyfin"; mkdir -p "$d"
  # Keep durable artwork and config. Replace the live DB/WAL capture with one
  # consistent online SQLite backup, at the same restore path inside the archive.
  local stage="$d/.jellyfin-stage"
  mkdir -p "$stage/data"; chmod 700 "$stage" "$stage/data"
  sqlite_backup "/home/cody/docker/jellyfin/config/data/jellyfin.db" "$stage/data/jellyfin.db" \
    || { fail jellyfin "consistent db copy"; return; }
  chmod 600 "$stage/data/jellyfin.db"
  if ( set -o pipefail; tar -C "/home/cody/docker/jellyfin/config" \
      --exclude='cache' --exclude='transcodes' --exclude='log' --exclude='logs' \
      --exclude='./data/jellyfin.db' --exclude='./data/jellyfin.db-wal' --exclude='./data/jellyfin.db-shm' \
      -cf - . -C "$stage" data/jellyfin.db 2>/dev/null \
      | "${ZSTD[@]}" -o "$d/jellyfin-config.tar.zst" 2>/dev/null ) && [[ -s "$d/jellyfin-config.tar.zst" ]]; then
    rm -f "$stage/data/jellyfin.db"
    rmdir "$stage/data" "$stage"
    good jellyfin "$(du -sh "$d" | cut -f1)"
  else
    fail jellyfin "config/artwork tar"
  fi
}

backup_cloudflared() {
  # The tunnel's ingress map lives in ~/.cloudflared, OUTSIDE $REPO, so stack-config never saw
  # it — yet it's on the root LV and is exactly the kind of hand-edited state this backup exists
  # to protect. Losing it means reconstructing the public hostname -> local service map by hand.
  #
  # Captures the tunnel CREDENTIALS (*.json) and cert.pem too, not just the ingress yml —
  # without them a restore can't run the existing tunnel and has to create a new one and
  # re-point every DNS record. That is only safe because the backup tree is no longer readable
  # by the media containers: radarr/sonarr have an empty ro tmpfs shadowing /data/.backups and
  # jellyfin/komga are narrowed to their library subdirs. If anything ever remounts the array
  # ROOT into a container again, this component starts leaking the tunnel's identity.
  # Modes (0400/0600) are preserved by tar.
  local d="$PARTIAL/cloudflared"; mkdir -p "$d"
  local src="$HOME/.cloudflared"
  local paths=() p
  shopt -s nullglob
  for p in "$src"/*.yml "$src"/*.json "$src"/cert.pem*; do paths+=("${p#$src/}"); done
  shopt -u nullglob
  if (( ${#paths[@]} == 0 )); then fail cloudflared "nothing matched in $src"; return; fi
  if tar -C "$src" -cf - "${paths[@]}" 2>/dev/null \
       | "${ZSTD[@]}" -o "$d/cloudflared-config.tar.zst" 2>/dev/null \
       && [[ -s "$d/cloudflared-config.tar.zst" ]]; then
    good cloudflared "$(du -sh "$d" | cut -f1)"
  else
    fail cloudflared "tar"
  fi
}

backup_systemd() {
  local d="$PARTIAL/systemd"; mkdir -p "$d"
  # The host's startup layer. Services here start through FIVE mechanisms -- compose, system
  # units, user units, rootless podman (uosserver) and fstab. deploy/systemd/ already tracks 11
  # units in git (backup, health, cloudflared-restart, offhost) and stack-config captures those,
  # but the host has 51 custom units. The ~40 unrepresented ones include SABnzbd, mylar3, Plex,
  # the health API and all three cloudflared tunnels -- so a restore could rebuild every
  # container and still not bring the host back.
  #
  # Copies (not tars) so the files stay individually greppable in the backup tree. Unit files
  # carry no secrets on this host -- credentials live in the .env files captured by
  # stack-config -- but the tree is 0700 anyway because ExecStart lines disclose paths.
  local n=0
  mkdir -p "$d/system" "$d/user"
  # Custom system units only: vendor units come back with the packages.
  for f in /etc/systemd/system/*.service /etc/systemd/system/*.timer /etc/systemd/system/*.mount; do
    [[ -f "$f" ]] || continue
    cp -p "$f" "$d/system/" 2>/dev/null && n=$((n+1))
  done
  # Drop-in directories: added 2026-09-22. mylar3.service.d and sabnzbd.service.d carry the
  # RequiresMountsFor=/mnt/avrana_media guard that stops those services starting without the
  # array, and docker.service.d holds daemon overrides. A unit file restored WITHOUT its
  # drop-in silently loses that protection, so the unit alone is not enough.
  for dd in /etc/systemd/system/*.service.d /etc/systemd/system/*.timer.d; do
    [[ -d "$dd" ]] || continue
    cp -a "$dd" "$d/system/" 2>/dev/null && n=$((n+1))
  done
  # *.path added 2026-09-22: tag_all.path exists in NO git repo and no other backup -- it had to
  # be reconstructed from in-memory `systemctl show` properties during the 2026-09-20 recovery,
  # because this glob captured only *.service and *.timer. .socket/.target included so the next
  # unit type added does not repeat that.
  for f in "$HOME"/.config/systemd/user/*.service "$HOME"/.config/systemd/user/*.timer \
           "$HOME"/.config/systemd/user/*.path "$HOME"/.config/systemd/user/*.socket \
           "$HOME"/.config/systemd/user/*.target; do
    [[ -f "$f" ]] || continue
    cp -p "$f" "$d/user/" 2>/dev/null && n=$((n+1))
  done
  # Enablement lives in .wants/ symlinks, which were a SEPARATE loss from the unit files in the
  # 2026-09-20 incident: the files came back but every unit was disabled. enabled-user.txt below
  # records it, and this preserves the link structure itself.
  for wd in "$HOME"/.config/systemd/user/*.wants; do
    [[ -d "$wd" ]] || continue
    cp -a "$wd" "$d/user/" 2>/dev/null && n=$((n+1))
  done
  # Enablement state is not recoverable from the unit files themselves, and fstab owns the
  # mergerfs union that Komga depends on.
  systemctl list-unit-files --state=enabled --no-legend --plain > "$d/enabled-system.txt" 2>/dev/null
  systemctl --user list-unit-files --state=enabled --no-legend --plain > "$d/enabled-user.txt" 2>/dev/null
  cp -p /etc/fstab "$d/fstab" 2>/dev/null
  # /etc/docker/daemon.json is root-only (0600), so this copy has failed on every run of this
  # user-level job and the error was discarded: the file was in no backup. Its one setting that
  # a rebuild cannot guess is the data-root, which the daemon will report to an unprivileged
  # caller. Record that, and say plainly when the file itself was not captured.
  # (Batch 1, finding A4.)
  if ! cp -p /etc/docker/daemon.json "$d/docker-daemon.json" 2>/dev/null; then
    log "note  systemd: /etc/docker/daemon.json not readable as $(id -un); recording data-root only"
  fi
  docker info --format '{{.DockerRootDir}}' > "$d/docker-data-root.txt" 2>/dev/null
  chmod -R go-rwx "$d" 2>/dev/null
  if (( n > 0 )); then
    good systemd "$(du -sh "$d" | cut -f1) ($n units)"
  else
    fail systemd "no unit files copied"
  fi
}

backup_stack_config() {
  local d="$PARTIAL/stack-config"; mkdir -p "$d"
  # Everything needed to rebuild the stack, by ALLOWLIST — the services/<name>/ dirs also hold
  # cloned source trees, live DB data dirs, venvs, and (critically) the connector's profiles/
  # with live Audible tokens, none of which belong in a backup. So we enumerate only the
  # deployment artifacts. None of the allowlisted roots contains a profiles/ dir, so a plain
  # tar of the collected paths is both exact and safe.
  local paths=() p
  shopt -s nullglob
  for p in "$REPO"/services/*/docker-compose.yml \
           "$REPO"/services/*/.env "$REPO"/services/*/.env.example "$REPO"/services/*/*.env \
           "$REPO"/services/*/secrets \
           "$REPO"/services/authentik/blueprints \
           "$REPO"/services/olivetin/config "$REPO"/services/olivetin/scripts \
           "$REPO"/services/recyclarr/config/recyclarr.yml \
           "$REPO"/services/recyclarr/config/settings.yml "$REPO"/services/recyclarr/config/state \
           "$REPO"/services/backups \
           "$REPO"/scripts \
           "$REPO"/.env "$REPO"/kern_secrets \
           "$REPO"/deploy "$REPO"/.gitignore; do
    paths+=("${p#$REPO/}")            # store repo-relative for a clean archive
  done
  shopt -u nullglob
  if (( ${#paths[@]} == 0 )); then fail stack-config "nothing matched"; return; fi
  if tar -C "$REPO" -cf - "${paths[@]}" 2>/dev/null \
       | "${ZSTD[@]}" -o "$d/stack-config.tar.zst" 2>/dev/null && [[ -s "$d/stack-config.tar.zst" ]]; then
    # 0600: this archive carries every service .env, services/*/secrets, the repo-root .env and
    # kern_secrets/. It was previously left 0644 while the systemd component was hardened to
    # 0700 -- an inconsistency, since this is the more secret-dense of the two.
    chmod 600 "$d/stack-config.tar.zst"
    good stack-config "$(du -sh "$d" | cut -f1)"
  else
    fail stack-config "tar"
  fi
}

# Added 2026-09-22. SABnzbd had NO backup component at all: its config was lost in the
# 2026-09-20 incident and, because nothing referenced it, the loss never appeared in ok[],
# failed[] or skipped[] -- the run still reported success. sabnzbd.ini holds the Usenet
# provider credentials, the api_key that radarr/sonarr authenticate with, and the nzb_key;
# history1.db survived the incident only as a deleted-but-open file descriptor.
backup_sabnzbd() {
  local d="$PARTIAL/sabnzbd"; mkdir -p "$d"
  local src="$HOME/.sabnzbd" bad=()
  if cp "$src/sabnzbd.ini" "$d/sabnzbd.ini" 2>/dev/null; then chmod 600 "$d/sabnzbd.ini"; else bad+=(sabnzbd.ini); fi
  # history only; the queue/*.sab spool files are transient and worthless to a restore.
  sqlite_backup "$src/admin/history1.db" "$d/history1.db" || bad+=(history1.db)
  if [ ${#bad[@]} -gt 0 ]; then fail sabnzbd "missing ${bad[*]}"; return; fi
  good sabnzbd "$(du -sh "$d" | cut -f1)"
}

# Added 2026-09-22. kavita.db has never appeared in any manifest. The service is not currently
# running and the DB is dormant (last write 2025-07-03), but it is 67 tables of real library
# state and costs ~200 KB compressed to keep. If Kavita is ever formally retired, delete this
# function rather than letting it fail silently.
backup_kavita() {
  local d="$PARTIAL/kavita"; mkdir -p "$d"
  local src="$REPO/services/kavita/config" bad=()
  sqlite_backup "$src/kavita.db" "$d/kavita.db" || bad+=(kavita.db)
  cp "$src/appsettings.json" "$d/appsettings.json" 2>/dev/null || bad+=(appsettings.json)
  if [ ${#bad[@]} -gt 0 ]; then fail kavita "missing ${bad[*]}"; return; fi
  good kavita "$(du -sh "$d" | cut -f1)"
}

# Added 2026-09-22. /home/cody/docker/ is OUTSIDE $REPO, so stack-config's tar -C "$REPO" can
# never reach it. Its per-service DATA is already covered (radarr/sonarr/prowlarr by backup_arr,
# plus backup_jellyfin and backup_seerr, all of which read /home/cody/docker/<svc>), and the
# COMPOSE definitions for all six live in services/media/docker-compose.yml, which stack-config
# does capture. What was uncovered is any top-level file there -- the original
# /home/cody/docker/docker-compose.yml was lost in the incident and is in no backup. Nothing
# matches today; this exists so that if such a file is ever recreated it is captured from the
# first night, rather than being discovered missing after the next incident.
backup_host_docker() {
  local d="$PARTIAL/host-docker"; mkdir -p "$d"
  local src="/home/cody/docker" paths=() p n=0
  shopt -s nullglob
  # -f test per entry, NOT nullglob alone: nullglob only drops patterns that CONTAIN a wildcard,
  # so the literal "$src"/.env survived as a non-existent path and failed the copy. Caught by a
  # pre-flight run 2026-09-22 -- same family as the -print0 binding bug fixed earlier.
  for p in "$src"/*.yml "$src"/*.yaml "$src"/.env; do
    [[ -f "$p" ]] || continue
    paths+=("${p#$src/}")
  done
  shopt -u nullglob
  if (( ${#paths[@]} == 0 )); then
    printf 'no top-level compose/.env files present; service data is covered by arr/jellyfin/seerr, definitions by services/media/docker-compose.yml\n' > "$d/NOTHING-TO-CAPTURE.txt"
    good host-docker "0 files (see NOTHING-TO-CAPTURE.txt)"
    return
  fi
  for p in "${paths[@]}"; do cp -p "$src/$p" "$d/$p" 2>/dev/null && n=$((n+1)); done
  chmod -R go-rwx "$d" 2>/dev/null
  (( n > 0 )) && good host-docker "$(du -sh "$d" | cut -f1) ($n files)" || fail host-docker "copy"
}

backup_libation() {
  local d="$PARTIAL/libation"; mkdir -p "$d"
  # The owner's own Audible/Libation setup, distinct from the connector (which deliberately drops
  # other users' tokens). Without libation-master.key the account settings are undecryptable, so
  # the key and AccountsSettings.json are captured together, plus Settings.json and the
  # LibationContext.db library state. These are the owner's own account data and are kept
  # intentionally. Secrets stay 0600.
  local src="$REPO/services/libation/config" bad=()
  sqlite_backup "$src/LibationContext.db" "$d/LibationContext.db" || bad+=(LibationContext.db)
  for f in libation-master.key AccountsSettings.json Settings.json; do
    if cp "$src/$f" "$d/$f" 2>/dev/null; then chmod 600 "$d/$f"; else bad+=("$f"); fi
  done
  (( ${#bad[@]} )) && fail libation "${bad[*]}" || good libation "$(du -sh "$d" | cut -f1)"
}

backup_shelfmark() {
  local d="$PARTIAL/shelfmark"; mkdir -p "$d"
  # users.db is shelfmark's only copy of its accounts; .flask_secret signs their sessions and
  # settings.json holds the routing/provider config. Cover thumbnails and plugins are regenerable
  # and skipped. .flask_secret stays 0600.
  local src="$REPO/services/shelfmark/config" bad=()
  sqlite_backup "$src/users.db" "$d/users.db" || bad+=(users.db)
  cp "$src/settings.json" "$d/settings.json" 2>/dev/null || bad+=(settings.json)
  if cp "$src/.flask_secret" "$d/.flask_secret" 2>/dev/null; then chmod 600 "$d/.flask_secret"; else bad+=(.flask_secret); fi
  (( ${#bad[@]} )) && fail shelfmark "${bad[*]}" || good shelfmark "$(du -sh "$d" | cut -f1)"
}

backup_mylar() {
  local d="$PARTIAL/mylar"; mkdir -p "$d"
  # Mylar3 runs bare metal from services/mylar3 (User=cody), so its state was never in this backup.
  # mylar.db holds the tracked series and history; config.ini holds the API key and settings and is
  # not reconstructable from the DB, mirroring how the *arr config.xml is treated. config.ini is
  # kept 0600. The comics themselves live on the array and are out of scope.
  local src="$REPO/services/mylar3" bad=()
  sqlite_backup "$src/mylar.db" "$d/mylar.db" || bad+=(mylar.db)
  if cp "$src/config.ini" "$d/config.ini" 2>/dev/null; then chmod 600 "$d/config.ini"; else bad+=(config.ini); fi
  (( ${#bad[@]} )) && fail mylar "${bad[*]}" || good mylar "$(du -sh "$d" | cut -f1)"
}

backup_kern_data() {
  local d="$PARTIAL/kern-data"; mkdir -p "$d"
  # The decommissioned Kern Prime / AvranOS is not being revived, but its accumulated personal data
  # is irreplaceable and was in neither git (filing_cabinet/**/*.yaml is gitignored) nor this
  # backup: the Last.fm listening history, health exports, and journals under filing_cabinet, plus
  # kern_sync (Strava). Code stays preserved in git; this captures the DATA. __pycache__ is skipped.
  if tar -C "$REPO" --exclude='*__pycache__*' -cf - filing_cabinet kern_sync 2>/dev/null \
       | "${ZSTD[@]}" -o "$d/kern-data.tar.zst" 2>/dev/null && [[ -s "$d/kern-data.tar.zst" ]]; then
    good kern-data "$(du -sh "$d" | cut -f1)"
  else
    fail kern-data "tar"
  fi
}

# ---- run ------------------------------------------------------------------------------------
log "backup -> $DEST (array free ${free_gb}G, keep ${KEEP})"
backup_abs
backup_authentik
backup_bookstack
backup_connector
backup_komga
backup_beszel
backup_home_assistant
backup_tracearr
backup_shelfarr
backup_omnibus
backup_calibreweb
backup_seerr
backup_arr
backup_jellyfin
backup_libation
backup_shelfmark
backup_mylar
backup_kern_data
backup_cloudflared
backup_sabnzbd
backup_kavita
backup_host_docker
backup_systemd
backup_stack_config

# ---- completeness gate ----------------------------------------------------------------------
# The components above report success when anything at all was captured: stack-config,
# cloudflared and systemd are built from globs, and a tar of an emptied directory is still a
# non-empty archive. So a run could be "ok" while a .env, a tunnel credential or a unit file had
# silently dropped out. Check the finished tree against an explicit list and fail the owning
# component for anything absent. A missing list or verifier fails too: an unchecked run must not
# look like a checked one. (Batch 1, finding A4.)
REQUIRED_LIST="$REPO/services/backups/required-artifacts.txt"
VERIFIER="$REPO/services/backups/verify-required.py"
if [[ -f "$REQUIRED_LIST" && -f "$VERIFIER" ]]; then
  verify_out="$(python3 "$VERIFIER" "$PARTIAL" "$REQUIRED_LIST" 2>&1)"; verify_rc=$?
  if (( verify_rc == 0 )); then
    log "ok    completeness ($(tail -n1 <<<"$verify_out"))"
  elif (( verify_rc == 1 )); then
    while IFS='|' read -r tag comp what; do
      [[ "$tag" == MISSING ]] || continue
      fail "$comp" "required artifact missing: $what"
    done <<<"$verify_out"
  else
    fail completeness "verifier could not run: $(tail -n1 <<<"$verify_out")"
  fi
else
  fail completeness "required-artifacts.txt or verify-required.py is missing"
fi
# A component can now be in both lists (captured something, but not everything). FAILED wins.
if (( ${#FAILED[@]} )); then
  mapfile -t FAILED < <(printf '%s\n' "${FAILED[@]}" | awk '!seen[$0]++')
  kept=()
  for c in "${OK[@]}"; do
    [[ " ${FAILED[*]} " == *" $c "* ]] || kept+=("$c")
  done
  OK=("${kept[@]}")
fi

# ---- manifest + finalize --------------------------------------------------------------------
( cd "$PARTIAL" && find . -type f ! -name MANIFEST.txt -print0 \
    | sort -z | xargs -0 sha256sum > MANIFEST.txt ) 2>/dev/null
total="$(du -sh "$PARTIAL" | cut -f1)"

status="ok"; (( ${#FAILED[@]} )) && status="partial"
# Only a complete run takes a plain timestamp name. An incomplete one is kept, for diagnosis and
# for whatever it did capture, as <timestamp>.partial-failed. Rotation, restore-test.sh and
# offhost-sync.sh all skip names containing "partial", so an incomplete run can no longer be
# counted as one of the $KEEP runs or be picked as "the newest backup". (Batch 1, finding A3.)
if [[ "$status" != ok ]]; then DEST="$DEST.partial-failed"; fi
if ! mv "$PARTIAL" "$DEST"; then
  fail finalize "could not rename $PARTIAL"
  status="partial"; DEST="$PARTIAL"
fi
# JSON array of a bash array — empty must render [] not [""] (a monitor counting failures
# would otherwise see one). printf with a format but zero args still fires once, so guard it.
json_arr() { (( $# )) && printf '"%s",' "$@" | sed 's/,$//'; }
printf '{"status":"%s","at":"%s","dest":"%s","size":"%s","ok":[%s],"failed":[%s],"array_free_gb":%s}\n' \
  "$status" "$(date -u +%FT%TZ)" "$DEST" "$total" \
  "$(json_arr "${OK[@]}")" \
  "$(json_arr "${FAILED[@]}")" \
  "$(avail_gb "$DEST_ROOT")" > "$DEST_ROOT/LAST_RUN.json"

# ---- rotate ---------------------------------------------------------------------------------
# Complete runs are pruned ONLY when this run is itself complete. Previously a failed run was
# renamed into place like any other and the oldest run was deleted regardless, so seven bad
# nights in a row left no complete backup except the .keep-pinned one. (Batch 1, finding A3.)
if [[ "$status" == ok ]]; then
  mapfile -t old < <(ls -1d "$DEST_ROOT"/*/ 2>/dev/null | grep -vi partial | sort | head -n -"$KEEP")
  for o in "${old[@]}"; do
    # A run marked .keep is never pruned. Rolling retention would otherwise delete the
    # last known-good pre-incident set while a recovery is still in progress.
    if [[ -e "$o/.keep" ]]; then log "keep  $(basename "$o") (.keep marker)"; continue; fi
    log "prune $(basename "$o")"; rm -rf "$o"
  done
else
  log "rotation skipped: this run is $status; no complete run was pruned"
fi
# Incomplete runs: keep the newest three, never touch anything else.
mapfile -t oldfailed < <(ls -1d "$DEST_ROOT"/*.partial-failed/ 2>/dev/null | sort | head -n -3)
for o in "${oldfailed[@]}"; do
  [[ "$o" == "$DEST_ROOT"/*.partial-failed/ && ! -e "$o/.keep" ]] || continue
  log "prune $(basename "$o") (incomplete run)"; rm -rf "$o"
done

log "done: $status  size=$total  ok=${#OK[@]}  failed=${#FAILED[@]}"
(( ${#FAILED[@]} == 0 ))
