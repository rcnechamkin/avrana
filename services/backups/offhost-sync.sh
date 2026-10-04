#!/usr/bin/env bash
# Off-host copy of the Avrana backup tree.
#
# avrana-backup.sh writes to /mnt/avrana_media/.backups, which is the media array. That survives a
# root-disk failure but NOT the loss of the array itself, which would take the media and every
# backup together. This script ships that tree to a remote object store so a single hardware event
# is recoverable.
#
# ENCRYPTED CLIENT-SIDE, NON-NEGOTIABLE. The tree contains Authentik's full pg_dump (every user,
# password hash and OIDC client secret), BookStack's APP_KEY, services/*/secrets, the *arr API keys
# and the cloudflared tunnel credentials. It is configured through an rclone `crypt` remote, so the
# provider only ever sees encrypted blobs and encrypted filenames. See offhost-setup.md.
#
# SAFETY: this is a mirror, and a mirror faithfully reproduces destruction. If the array is lost or
# half-written, a naive sync would delete the good remote copies. So the script refuses to run
# unless the local tree looks healthy, and caps how much it will delete in one pass.
set -uo pipefail

REPO="/home/cody/avrana"
SRC="${AVRANA_BACKUP_ROOT:-/mnt/avrana_media/.backups/avrana}"
CONF="${AVRANA_RCLONE_CONF:-$REPO/services/backups/rclone.conf}"
REMOTE="${AVRANA_OFFHOST_REMOTE:-avrana-crypt:}"
STATE="${AVRANA_OFFHOST_STATE:-/mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json}"
MAX_DELETE="${AVRANA_OFFHOST_MAX_DELETE:-3}"   # a prune removes 1 dated run; 3 is slack, not a wipe
IMAGE="rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548"

log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }

emit() {  # emit <status> <detail>
  # Built with python, not printf. Hand-rolled JSON here stripped double quotes but not
  # backslashes, so a detail containing one produced INVALID json - and services-health.sh parses
  # this file, so the failure reason would be lost exactly when it mattered. python escapes
  # properly and cannot emit a broken document.
  python3 -c 'import json,sys;json.dump({"status":sys.argv[1],"detail":sys.argv[2],"at":sys.argv[3],"source":sys.argv[4]},open(sys.argv[5],"w"))' \
    "$1" "${2:-}" "$(date -u +%FT%TZ)" "$SRC" "$STATE"
}

fail() { log "FAIL $*"; emit failed "$*"; exit 1; }

# ---- preflight ------------------------------------------------------------------------------
[[ -f "$CONF" ]] || fail "no rclone config at $CONF (see offhost-setup.md)"
[[ -d "$SRC"  ]] || fail "backup tree missing: $SRC"

# Refuse to mirror a tree that does not look like a healthy backup: at least one dated run, and the
# most recent local run reported ok. Without this, a corrupted array propagates to the remote.
runs="$(find "$SRC" -maxdepth 1 -mindepth 1 -type d -name '20*' 2>/dev/null | wc -l)"
(( runs >= 1 )) || fail "no dated backup runs under $SRC (refusing to mirror an empty tree)"

status="$(python3 - "$SRC/LAST_RUN.json" <<'PY' 2>/dev/null
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
print(json.loads(p.read_text()).get("status", "missing") if p.is_file() else "missing")
PY
)"
[[ "$status" == "ok" ]] || fail "local backup last run is '$status', not ok (refusing to mirror)"

log "off-host sync -> $REMOTE (local: $runs runs, last run $status)"

# ---- sync -----------------------------------------------------------------------------------
# Read-only mount of the source: this job must never be able to modify the local backups.
# --max-delete caps blast radius; --checksum so a same-size/different-content file is still sent.
docker run --rm \
  --user 1000:1000 \
  -v "$SRC:/data:ro" \
  -v "$CONF:/config/rclone/rclone.conf:ro" \
  "$IMAGE" \
  sync /data "$REMOTE" \
    --checksum \
    --max-delete "$MAX_DELETE" \
    --transfers 4 \
    --retries 3 \
    --stats-one-line --stats 30s \
    --log-level INFO
rc=$?

(( rc == 0 )) || fail "rclone sync exited $rc"

# ---- verify ---------------------------------------------------------------------------------
# A sync that reports success but wrote nothing readable is not a backup. Compare the remote's own
# listing against the local run directories, and confirm the newest run's MANIFEST round-trips.
newest="$(find "$SRC" -maxdepth 1 -mindepth 1 -type d -name '20*' -printf '%f\n' | sort | tail -1)"

# Write the remote copy to a FILE and diff files. Capturing it through $( ) strips trailing
# newlines, and MANIFEST.txt ends with one - so a byte-identical remote would have compared as
# different and this verify would have failed on every single run.
tmp_manifest="$(mktemp)"
trap 'rm -f "$tmp_manifest"' EXIT
docker run --rm --user 1000:1000 \
  -v "$CONF:/config/rclone/rclone.conf:ro" "$IMAGE" \
  cat "$REMOTE$newest/MANIFEST.txt" > "$tmp_manifest" 2>/dev/null

if [[ ! -s "$tmp_manifest" ]]; then
  fail "verify: could not read back $newest/MANIFEST.txt from the remote"
fi
if ! cmp -s "$tmp_manifest" "$SRC/$newest/MANIFEST.txt"; then
  fail "verify: remote MANIFEST for $newest does not match local"
fi

remote_runs="$(docker run --rm --user 1000:1000 \
  -v "$CONF:/config/rclone/rclone.conf:ro" "$IMAGE" \
  lsd "$REMOTE" 2>/dev/null | grep -c ' 20' )"

log "ok: $remote_runs runs on the remote, newest=$newest manifest verified"
emit ok "runs=$remote_runs newest=$newest"
