#!/usr/bin/env bash
# avrana-backup-seal: completed backup runs become root-owned and read-only for everyone else
# (bug hunt E5). Installed by deploy/host/owner-scripts/08-backup-seal.sh to /usr/local/sbin and
# run by avrana-backup-seal.path (after every backup) and avrana-backup-seal.timer (daily).
#
# What it does, idempotently:
#   1. the tree /mnt/avrana_media/.backups/avrana is root:cody 1775: cody can still create a run
#      (.partial) and rename it into place when it is complete, but the sticky bit stops cody from
#      renaming or deleting anything root owns;
#   2. every complete run (a name ending in Z) still owned by cody becomes root:cody, directories
#      750 and files 640: cody (the backup, off-host and restore-test units) can read, nobody but
#      root can change or delete;
#   3. retention moves here, because cody can no longer delete: the newest $KEEP complete runs are
#      kept, older ones removed unless they carry a .keep marker (root creates it:
#      `sudo touch RUN/.keep`). Incomplete runs (*.partial-failed) stay cody-owned and are still
#      pruned by the backup script itself.
# The array uses mergerfs, which has no immutable flag; ownership and the sticky bit are the
# control. `--dry-run` prints what would change.
set -euo pipefail
ROOT="${AVRANA_BACKUP_ROOT:-/mnt/avrana_media/.backups/avrana}"
KEEP="${AVRANA_BACKUP_KEEP:-7}"
OWNER=cody
DRY=0; [[ "${1:-}" == --dry-run ]] && DRY=1
run() { if (( DRY )); then echo "would: $*"; else "$@"; fi; }
note() { echo "$*"; (( DRY )) || logger -t avrana-backup-seal -- "$*"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
if [[ ! -d "$ROOT" ]]; then
  # array not mounted or no backup yet: nothing to seal, and not an error for the path unit
  echo "no $ROOT: nothing to do"; exit 0
fi
if ! findmnt -T "$ROOT" -o FSTYPE -n | grep -qE 'mergerfs|ext4|xfs|btrfs|zfs'; then
  echo "$ROOT is not on a known filesystem: refusing" >&2; exit 2
fi

if [[ "$(stat -c '%U:%G %a' "$ROOT")" != "root:$OWNER 1775" ]]; then
  run chown "root:$OWNER" "$ROOT"
  run chmod 1775 "$ROOT"
  note "tree $ROOT is root:$OWNER 1775"
fi

sealed=0
for d in "$ROOT"/*Z/; do
  [[ -d "$d" ]] || continue
  d="${d%/}"
  [[ "$(stat -c %U "$d")" == root ]] && continue
  run chown -R "root:$OWNER" "$d"
  run chmod -R u=rwX,g=rX,o= "$d"
  note "sealed $(basename "$d")"
  sealed=$((sealed + 1))
done

pruned=0
mapfile -t old < <(ls -1d "$ROOT"/*Z/ 2>/dev/null | sort | head -n -"$KEEP")
for o in "${old[@]}"; do
  o="${o%/}"
  if [[ -e "$o/.keep" ]]; then note "keep   $(basename "$o") (.keep marker)"; continue; fi
  run rm -rf "$o"
  note "pruned $(basename "$o") (keeping the newest $KEEP complete runs)"
  pruned=$((pruned + 1))
done
echo "done: sealed=$sealed pruned=$pruned complete_runs=$(ls -1d "$ROOT"/*Z/ 2>/dev/null | wc -l)"
