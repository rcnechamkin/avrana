#!/usr/bin/env bash
# Restart the Cloudflare tunnel, for when a new hostname has been added to the ingress config.
#
# WHY THIS IS A FILE TRIGGER AND NOT A COMMAND
#   cloudflared-avrana.service is a HOST SYSTEM unit, not a container. The Docker socket proxies
#   cannot see it, and restarting a system unit needs root. Rather than give this container any
#   route to root, it drops a marker file that a root-level systemd.path unit watches. That unit
#   hardcodes the service name and accepts no arguments, so the capability granted here is exactly
#   "restart the tunnel" - it cannot be turned into "run anything as root".
#
# YOU ARE RESTARTING THE THING CARRYING THIS REQUEST
#   The press arrived through the tunnel. The trigger unit sleeps 3s before bouncing it so this
#   response gets back to the browser first; the tunnel is then briefly down (~5-15s) and any open
#   page will blink. That is expected, and is why this action needs a confirmation.
#
# VERIFICATION DELIBERATELY USES A DIFFERENT HOSTNAME
#   Polling ops.avrana.net would mean asking the service that is answering you whether it is up.
#   Checking a different tunnel hostname proves the tunnel itself came back.
set -uo pipefail

TRIGGER="${AVRANA_CF_TRIGGER:-/state/request-cloudflared-restart}"
PROBE_URL="${AVRANA_CF_PROBE:-https://listen.avrana.net/}"   # Audiobookshelf, independent of OliveTin
SETTLE="${AVRANA_CF_SETTLE:-8}"      # give the unit its 3s delay plus reconnect time
TIMEOUT="${AVRANA_CF_TIMEOUT:-90}"

probe() { curl -s -o /dev/null -m 8 -w '%{http_code}' "$PROBE_URL" 2>/dev/null || echo 000; }

dir="$(dirname "$TRIGGER")"
if [ ! -d "$dir" ]; then
  echo "FAIL  trigger directory $dir is not mounted"
  exit 2
fi

before="$(probe)"
echo "tunnel before: $PROBE_URL -> HTTP $before"

echo "requesting a cloudflared restart ..."
if ! : > "$TRIGGER" 2>/dev/null; then
  echo "FAIL  could not write the trigger file"
  exit 2
fi

# If the root path unit is not installed the marker just sits there. Detect that rather than
# reporting a restart that never happened: the unit removes the file as its first step.
waited=0
while [ -f "$TRIGGER" ] && [ "$waited" -lt 15 ]; do
  sleep 1
  waited=$((waited + 1))
done
if [ -f "$TRIGGER" ]; then
  rm -f "$TRIGGER" 2>/dev/null
  echo "FAIL  the marker was never picked up after ${waited}s."
  echo "      avrana-cloudflared-restart.path is probably not installed or not enabled."
  echo "      It is a ROOT unit and needs a one-time install; see the OliveTin README."
  exit 1
fi
echo "trigger accepted after ${waited}s (root unit picked it up)"

echo "waiting for the tunnel to come back ..."
sleep "$SETTLE"
deadline=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  code="$(probe)"
  case "$code" in
    200|302|307)
      echo "PASS  tunnel is serving again ($PROBE_URL -> HTTP $code)"
      exit 0
      ;;
  esac
  sleep 3
done

echo "FAIL  the tunnel did not respond within ${TIMEOUT}s (last: HTTP $(probe))"
echo "      cloudflared may still be reconnecting. Check: systemctl status cloudflared-avrana.service"
exit 1
