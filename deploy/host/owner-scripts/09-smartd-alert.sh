#!/usr/bin/env bash
# Give smartd somewhere to send disk warnings (bug hunt A21). Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/09-smartd-alert.sh
#
# /etc/smartd.conf already says `-m root -M exec /usr/share/smartmontools/smartd-runner`, which
# runs every script in /etc/smartmontools/run.d/. This adds one that hands the message to
# scripts/avrana-alert.py (as cody), so a disk warning reaches the same mailbox as the health
# check. Delivery works once the SMTP2GO password is rotated and .env.alert is configured; the
# test at the end tells you which state you are in. Rollback: delete the installed script.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
SRC=/home/cody/avrana/deploy/host/smartmontools/20avrana-alert
DST=/etc/smartmontools/run.d/20avrana-alert
grep -q 'smartd-runner' /etc/smartd.conf || { echo "smartd.conf does not use smartd-runner; stopping"; exit 1; }
install -m 755 -o root -g root "$SRC" "$DST"
echo "installed $DST"
echo "== test (a fake message through the real path)"
tmp=$(mktemp); echo "test message from 09-smartd-alert.sh, not a disk problem" > "$tmp"
if SMARTD_SUBJECT="smartd alert path test" "$DST" "$tmp"; then
  echo "alert script accepted the message (delivered if .env.alert is configured)"
else
  echo "alert script returned non-zero: delivery is not configured yet (expected until the SMTP2GO rotation); the hook is in place"
fi
rm -f "$tmp"
systemctl is-active smartd && echo "smartd active; next warning will use the hook"
