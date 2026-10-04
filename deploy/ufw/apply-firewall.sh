#!/usr/bin/env bash
# Apply the full two-layer firewall with automatic rollback on failure.
#
#   snapshot -> arm deadman -> stage INPUT rules -> install DOCKER-USER -> enable ufw
#            -> verify -> (pass: wait for operator confirmation | fail: roll back now)
#
# THREE independent safety nets, because the failure mode here is losing SSH:
#   1. verify-firewall.sh runs immediately after enabling; any failure rolls back at once.
#   2. A DEADMAN timer rolls back after $DEADMAN_MIN minutes unless the operator runs
#      confirm-firewall.sh. This covers the case where verification passes from the host
#      itself but the operator's own access is broken -- the failure verify cannot see.
#   3. The snapshot is a verbatim iptables-save, restorable by hand at the console.
#
# Run as root:  sudo bash deploy/ufw/apply-firewall.sh
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }

HERE=/home/cody/avrana/deploy/ufw
DEADMAN_MIN=${DEADMAN_MIN:-15}

say() { printf '\n=== %s ===\n' "$*"; }

say "1/7 preflight"
for f in snapshot-firewall.sh rollback-firewall.sh rules-input.sh rules-docker-user.sh verify-firewall.sh; do
  [[ -x "$HERE/$f" ]] || { echo "missing/not executable: $HERE/$f" >&2; exit 1; }
  bash -n "$HERE/$f" || { echo "syntax error in $f" >&2; exit 1; }
done
ip link show "${LAN_IF:-br0}" >/dev/null 2>&1 || { echo "LAN interface ${LAN_IF:-br0} not found" >&2; exit 1; }
# Refuse to run while the address-pool migration is still pending: it restarts Docker and
# renumbers every bridge, and stacking the two changes makes any failure ambiguous.
if systemctl is-active --quiet avrana-docker-address-pool.timer 2>/dev/null \
   && ! grep -q 'default-address-pools' /etc/docker/daemon.json 2>/dev/null; then
  echo "REFUSING: the Docker address-pool migration has not run yet (timer still armed," >&2
  echo "and daemon.json has no default-address-pools). Let it complete first, then re-run." >&2
  echo "Override with ALLOW_PREMIGRATION=1 if you really mean to." >&2
  [[ "${ALLOW_PREMIGRATION:-0}" == "1" ]] || exit 1
fi
echo "preflight OK"

say "2/7 snapshot"
SNAP=$("$HERE/snapshot-firewall.sh" | tail -1)
[[ -d "$SNAP" ]] || { echo "snapshot failed" >&2; exit 1; }
echo "snapshot: $SNAP"

say "3/7 arm deadman (${DEADMAN_MIN} min)"
# AccuracySec is NOT optional here. systemd's default is AccuracySec=1min, which lets a
# timer fire up to a minute late -- unacceptable slop for the mechanism that restores your
# access. Verified: with the default, a 5s test timer had not fired after 10s; with
# AccuracySec=1s it fired at 6s.
systemd-run --collect --on-active="${DEADMAN_MIN}min" \
  --timer-property=AccuracySec=1s \
  --unit=avrana-firewall-deadman \
  /bin/bash "$HERE/rollback-firewall.sh" "$SNAP" >/dev/null 2>&1 \
  || { echo "could not arm deadman -- ABORTING before any change" >&2; exit 1; }

# Trust nothing: systemd-run can exit 0 without leaving a usable timer. Assert it is really
# armed BEFORE making any change, and abort while the system is still untouched.
if ! systemctl is-active --quiet avrana-firewall-deadman.timer; then
  echo "deadman did not arm (timer not active) -- ABORTING before any change" >&2; exit 1
fi
echo "deadman armed and confirmed active: rolls back at $(date -d "+${DEADMAN_MIN} min" '+%H:%M:%S') unless confirmed"
systemctl list-timers avrana-firewall-deadman.timer --no-pager | sed -n 2p

rollback_now() {
  echo; echo "!!! $1 -- ROLLING BACK !!!" >&2
  systemctl stop avrana-firewall-deadman.timer >/dev/null 2>&1 || true
  bash "$HERE/rollback-firewall.sh" "$SNAP"
  exit 1
}

say "4/7 stage INPUT rules (ufw still off)"
"$HERE/rules-input.sh" || rollback_now "staging INPUT rules failed"

say "5/7 install DOCKER-USER + persistence"
"$HERE/rules-docker-user.sh" || rollback_now "DOCKER-USER install failed"
install -m644 "$HERE/avrana-docker-user-rules.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable avrana-docker-user-rules.service >/dev/null 2>&1 \
  || rollback_now "could not enable the DOCKER-USER persistence unit"

say "6/7 enable ufw"
sed -i 's/^ENABLED=no/ENABLED=yes/' /etc/ufw/ufw.conf
ufw --force enable || rollback_now "ufw enable failed"
# Docker reasserts its own FORWARD jumps on restart; do it now so ordering is deterministic
# rather than depending on whether ufw or Docker touched the chain last.
systemctl restart docker || rollback_now "docker restart after enable failed"
echo "waiting 45s for the container fleet"; sleep 45

say "7/7 verify"
if sudo -u cody "$HERE/verify-firewall.sh"; then
  echo
  echo "VERIFICATION PASSED."
  echo
  echo "  The deadman is STILL ARMED and will roll everything back at"
  echo "  $(date -d "+${DEADMAN_MIN} min" '+%H:%M:%S') unless you confirm."
  echo
  echo "  From a NEW SSH session -- prove your own access still works -- run:"
  echo "      sudo bash $HERE/confirm-firewall.sh"
  echo
  echo "  To roll back by hand at any time:"
  echo "      sudo bash $HERE/rollback-firewall.sh $SNAP"
else
  rollback_now "verification failed"
fi
