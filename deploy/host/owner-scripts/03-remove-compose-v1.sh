#!/usr/bin/env bash
# Bug hunt A12, last step. Every container has carried Compose v2 labels since 2026-10-06, so the
# v1 package (`docker-compose` 1.29.2) is dead weight and a trap. Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/03-remove-compose-v1.sh
#
# Refuses if any container still carries a v1 label. Rollback: `apt-get install docker-compose`.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
v1=$(sudo -u cody docker ps -a --format '{{.Names}}' | while read -r c; do
  [[ "$(sudo -u cody docker inspect "$c" --format '{{index .Config.Labels "com.docker.compose.version"}}')" == 1.* ]] && echo "$c"; done || true)
[[ -z "$v1" ]] || { echo "REFUSING: still created by Compose v1: $v1"; exit 1; }
dpkg -l docker-compose 2>/dev/null | grep -q '^ii' || { echo "docker-compose v1 is not installed"; exit 0; }
apt-get remove -y docker-compose
echo "v2 for cody: $(sudo -u cody docker compose version)"
command -v docker-compose >/dev/null && echo "WARNING: a docker-compose binary is still on PATH: $(command -v docker-compose)" || echo "docker-compose (v1) is gone"
