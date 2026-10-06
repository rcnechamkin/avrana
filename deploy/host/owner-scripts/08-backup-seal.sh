#!/usr/bin/env bash
# Backups that cody cannot delete (bug hunt E5). Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/08-backup-seal.sh
#
# Installs /usr/local/sbin/avrana-backup-seal and the avrana-backup-seal.{service,path,timer}
# system units, enables the path unit (seals right after each backup) and the daily timer
# (fallback), seals the existing complete runs once, then proves that cody can still read a run
# and run the restore test but can no longer delete or modify a sealed run. The backup script
# (services/backups/avrana-backup.sh, deployed in Batch 5) leaves root-owned runs to this unit.
#
# Rollback: `systemctl disable --now avrana-backup-seal.path avrana-backup-seal.timer`, then
# `chown -R cody:cody /mnt/avrana_media/.backups/avrana && chmod 775 /mnt/avrana_media/.backups/avrana`
# (the previous ownership; the previous modes of each run are 775/664 or 700/600 as the backup
# script created them, and nothing depends on the exact values).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
REPO=/home/cody/avrana
ROOT=/mnt/avrana_media/.backups/avrana
B=/mnt/avrana_media/.backups/batch5-20261006/rollback/seal
mkdir -p "$B"; chmod 700 "$B"
stat -c '%A %U:%G %n' "$ROOT" "$ROOT"/*Z > "$B/ownership-before.txt"
echo "before: $(wc -l < "$B/ownership-before.txt") entries recorded in $B/ownership-before.txt"

echo "== install"
install -m 755 -o root -g root "$REPO/deploy/host/backup-seal.sh" /usr/local/sbin/avrana-backup-seal
for u in service path timer; do
  install -m 644 -o root -g root "$REPO/deploy/host/systemd/avrana-backup-seal.$u" "/etc/systemd/system/avrana-backup-seal.$u"
done
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/avrana-backup-seal.service /etc/systemd/system/avrana-backup-seal.path /etc/systemd/system/avrana-backup-seal.timer

echo "== dry run"
/usr/local/sbin/avrana-backup-seal --dry-run | tail -5
echo "== seal now"
/usr/local/sbin/avrana-backup-seal
systemctl enable --now avrana-backup-seal.path avrana-backup-seal.timer
systemctl list-timers --no-pager avrana-backup-seal.timer | head -2

echo "== verify"
newest=$(ls -1d "$ROOT"/*Z | sort | tail -1)
[[ "$(stat -c %U "$newest")" == root ]] || { echo "FAIL: $newest is not root-owned"; exit 1; }
if sudo -u cody rm -rf "$newest" 2>/dev/null; then echo "FAIL: cody could delete $newest"; exit 1; fi
if sudo -u cody touch "$newest/x" 2>/dev/null; then echo "FAIL: cody could write into $newest"; rm -f "$newest/x"; exit 1; fi
if sudo -u cody mv "$newest" "$newest.moved" 2>/dev/null; then echo "FAIL: cody could rename $newest"; mv "$newest.moved" "$newest"; exit 1; fi
sudo -u cody test -r "$newest/MANIFEST.txt" || { echo "FAIL: cody cannot read the run"; exit 1; }
sudo -u cody mkdir "$ROOT/.seal-test.partial" && sudo -u cody rmdir "$ROOT/.seal-test.partial" || { echo "FAIL: cody cannot create a run"; exit 1; }
echo "cody: can read, can create a new run, cannot delete, write into or rename a sealed one"
echo "== restore test as cody (no state, no boots; about 90 s)"
sudo -u cody python3 "$REPO/services/backups/restore-test.py" --no-state 2>&1 | tail -2
echo "== off-host listing as cody"
sudo -u cody python3 "$REPO/services/backups/offhost-backup.py" --list 2>&1 | tail -3 || echo "(off-host listing failed: check separately; it needs B2)"
echo "done. The next backup (02:30) writes a new run as cody; the path unit seals it within seconds; retention is now the seal's job."
