#!/usr/bin/env bash
# Restart ONE allowlisted media service and verify it comes back healthy.
#
# Defence in depth. OliveTin already constrains this to a fixed `choices` dropdown, but the
# dropdown is a UI affordance, not a security boundary: this script re-validates the name against
# its own hardcoded allowlist and refuses anything else. The name is never passed through a shell
# and is never interpolated into a command string.
#
# The restart goes through olivetin-docker-restart, a socket proxy with POST=1 ALLOW_RESTARTS=1
# and CONTAINERS=0 - so /containers/create and /exec are denied. Verification goes through
# olivetin-docker-ro, which has POST=0 and cannot mutate anything.
set -euo pipefail

# Control-plane services are deliberately absent. Authentik, the socket proxies, OliveTin itself,
# BookStack + its MariaDB, Homepage and cloudflared must not be restartable from a web button:
# restarting the thing that authenticates the button is how you lock yourself out.
# SABnzbd is a host systemd service, not a container. Bazarr is not deployed.
ALLOWED="jellyfin audiobookshelf komga calibre-web-automated seerr avrana-audible-connector radarr sonarr prowlarr"

svc="${1:-}"

if [ -z "$svc" ]; then
  echo "FAIL  no service given"
  exit 2
fi

ok=0
for a in $ALLOWED; do
  [ "$a" = "$svc" ] && ok=1 && break
done
if [ "$ok" -ne 1 ]; then
  echo "FAIL  '$svc' is not an allowlisted service"
  echo "      allowed: $ALLOWED"
  exit 2
fi

ro="${DOCKER_HOST_RO:-tcp://olivetin-docker-ro:2375}"
rw="${DOCKER_HOST_RESTART:-tcp://olivetin-docker-restart:2375}"

state_of() { DOCKER_HOST="$ro" docker inspect -f '{{.State.Status}}' "$1" 2>/dev/null || echo unknown; }
health_of() { DOCKER_HOST="$ro" docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo unknown; }

before_state="$(state_of "$svc")"
if [ "$before_state" = "unknown" ]; then
  echo "FAIL  $svc: not found via the inspection proxy"
  exit 1
fi
echo "before: $svc state=$before_state health=$(health_of "$svc")"

echo "restarting $svc ..."
if ! DOCKER_HOST="$rw" docker restart "$svc" >/dev/null; then
  echo "FAIL  $svc: restart call failed"
  exit 1
fi

# Verify rather than assume. Wait for running, then for healthy if the container defines a
# healthcheck at all ("none" means it does not, so running is the strongest signal available).
deadline=$(( $(date +%s) + 120 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  st="$(state_of "$svc")"
  hl="$(health_of "$svc")"
  if [ "$st" = "running" ] && { [ "$hl" = "healthy" ] || [ "$hl" = "none" ]; }; then
    echo "PASS  $svc restarted: state=$st health=$hl"
    exit 0
  fi
  if [ "$st" = "exited" ] || [ "$st" = "dead" ]; then
    echo "FAIL  $svc did not come back: state=$st"
    exit 1
  fi
  sleep 3
done

echo "FAIL  $svc did not become healthy within 120s (state=$(state_of "$svc") health=$(health_of "$svc"))"
exit 1
