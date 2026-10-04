#!/usr/bin/env bash
# Restore the firewall to a snapshot taken by snapshot-firewall.sh.
# Usage: rollback-firewall.sh /home/cody/backups/firewall-<stamp>
#
# Safe to run at any time, including when nothing is broken -- it is idempotent and
# simply reinstates the captured ruleset and ufw enablement state.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
D=${1:?usage: rollback-firewall.sh <snapshot-dir>}
[[ -d "$D" ]] || { echo "no such snapshot: $D" >&2; exit 1; }
[[ -s "$D/iptables.v4" ]] || { echo "snapshot has no iptables.v4 -- refusing" >&2; exit 1; }

echo "rolling back from $D"

# 1. ufw down first, so its rules stop being re-applied over the restore.
ufw --force disable >/dev/null 2>&1 || true

# 2. Put back the exact pre-change config and rule files.
if [[ -d "$D/etc-ufw" ]]; then rm -rf /etc/ufw && cp -a "$D/etc-ufw" /etc/ufw; fi
[[ -f "$D/default-ufw" ]] && cp -a "$D/default-ufw" /etc/default/ufw

# 3. Restore the kernel ruleset verbatim.
iptables-restore  < "$D/iptables.v4" || echo "WARN: iptables v4 restore reported an error" >&2
[[ -s "$D/iptables.v6" ]] && { ip6tables-restore < "$D/iptables.v6" || echo "WARN: v6 restore error" >&2; }

# 4. Drop the DOCKER-USER persistence unit if this change installed it.
if systemctl list-unit-files --no-legend | grep -q '^avrana-docker-user-rules.service'; then
  systemctl disable --now avrana-docker-user-rules.service >/dev/null 2>&1 || true
fi

# 5. Re-assert ufw's ORIGINAL enablement state (it was ENABLED=no before this change).
if grep -q '^ENABLED=yes' "$D/etc-ufw/ufw.conf" 2>/dev/null; then
  ufw --force enable >/dev/null 2>&1 || true
  echo "ufw re-enabled (it was enabled in the snapshot)"
else
  echo "ufw left disabled (it was disabled in the snapshot)"
fi

# 6. Docker owns its own chains; a restart makes it re-assert them cleanly.
systemctl restart docker >/dev/null 2>&1 || echo "WARN: docker restart failed" >&2

echo "rollback complete. verifying..."
sudo -u cody /home/cody/avrana/deploy/ufw/verify-firewall.sh
