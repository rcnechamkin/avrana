#!/usr/bin/env bash
# Root-owned leftovers that cody cannot remove. Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/05-remove-leftovers.sh
#
#   - services/kavita: the retired Kavita's config directory (root-owned). Its backup component was
#     removed on 2026-10-06; the last copy is in the runs up to 2026-10-05 and the golden backup.
#     A tarball is saved in the batch directory first.
#   - batch2-20261004/bookstack-extract/mariadb-disposable: empty directory left by the disposable
#     database used for the BookStack export.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
B=/mnt/avrana_media/.backups/batch3-20261006/rollback
K=/home/cody/avrana/services/kavita
if [[ -d "$K" ]]; then
  tar -C /home/cody/avrana/services -czf "$B/kavita-config-final.tar.gz" kavita && chmod 600 "$B/kavita-config-final.tar.gz"
  rm -rf "$K" && echo "removed $K (saved as $B/kavita-config-final.tar.gz)"
else
  echo "$K already gone"
fi
D=/mnt/avrana_media/.backups/batch2-20261004/bookstack-extract/mariadb-disposable
[[ -d "$D" ]] && { rm -rf "$D"; echo "removed $D"; } || echo "$D already gone"
