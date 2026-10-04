#!/usr/bin/env bash
# Disarm the deadman. Run this ONLY from a NEW SSH session, after confirming that your
# own access, Jellyfin, Home Assistant and the UniFi console all still work. Until this
# runs, the firewall reverts automatically.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
if systemctl stop avrana-firewall-deadman.timer 2>/dev/null; then
  echo "deadman disarmed -- the firewall is now permanent."
else
  echo "no armed deadman found (already disarmed, already fired, or never armed)."
fi
systemctl reset-failed avrana-firewall-deadman.timer avrana-firewall-deadman.service 2>/dev/null || true
echo; echo "current policy:"; ufw status verbose
echo; echo "DOCKER-USER:"; iptables -S DOCKER-USER
