#!/usr/bin/env bash
# Post-change reachability probe. Exit 0 = everything that must work still works.
# Exit non-zero = apply-firewall.sh rolls back automatically.
#
# Runs as any user; needs no root. Deliberately probes via the LAN address 10.0.0.218
# rather than 127.0.0.1, because loopback bypasses exactly the rules we are testing.
# A localhost-only probe would pass even with a completely broken firewall.
set -uo pipefail

LAN_IP=${LAN_IP:-10.0.0.218}
fail=0; checks=0
ok()   { printf '  OK   %s\n' "$*"; }
bad()  { printf '  FAIL %s\n' "$*" >&2; fail=$((fail+1)); }

# http NAME URL ACCEPTABLE_CODES...
http() {
  local name=$1 url=$2; shift 2
  checks=$((checks+1))
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$url" 2>/dev/null)
  for want in "$@"; do [[ "$code" == "$want" ]] && { ok "$name ($code)"; return; }; done
  bad "$name -> got $code, wanted one of: $*"
}

# tcp NAME HOST PORT
tcp() {
  local name=$1 h=$2 p=$3; checks=$((checks+1))
  if timeout 5 bash -c "exec 3<>/dev/tcp/$h/$p" 2>/dev/null; then ok "$name (tcp $h:$p)"
  else bad "$name -> tcp connect to $h:$p refused/timed out"; fi
}

echo "== SSH (the one that must never break) =="
tcp  "ssh"                  "$LAN_IP" 22

echo "== bare-metal host services =="
http "sabnzbd login redirect" "http://$LAN_IP:8082/config/switches/" 303
http "mylar3 login redirect"  "http://$LAN_IP:8090/home"             303
http "jellyfin"               "http://$LAN_IP:8096/health"           200
tcp  "home assistant"         "$LAN_IP" 8123

echo "== UniFi OS Server (management + adoption) =="
tcp  "unifi console 8444"   "$LAN_IP" 8444
tcp  "unifi inform 8080"    "$LAN_IP" 8080

echo "== Docker-published services (the DOCKER-USER layer) =="
http "homepage"             "http://$LAN_IP:3000/api/healthcheck"        200
http "radarr"               "http://$LAN_IP:7878/ping"                   200
http "sonarr"               "http://$LAN_IP:8989/ping"                   200
http "prowlarr"             "http://$LAN_IP:9696/ping"                   200
http "audiobookshelf"       "http://$LAN_IP:13378/healthcheck"           200
http "shelfmark"            "http://$LAN_IP:8084/api/health"             200
http "calibre-web-automated" "http://$LAN_IP:8083/"                      200 302
http "completeseries"       "http://$LAN_IP:8085/"                       200
http "bookstack"            "http://$LAN_IP:6875/status"                 200
http "beszel"               "http://$LAN_IP:8093/api/health"             200
http "authentik"            "http://$LAN_IP:9000/-/health/live/"         200 204
http "komga"                "http://$LAN_IP:25600/actuator/health"       200
http "seerr"                "http://$LAN_IP:5055/api/v1/status"          200
http "shelfarr"             "http://$LAN_IP:5056/"                       200 302 303
http "tracearr"             "http://$LAN_IP:5057/"                       200 302 307
http "omnibus"              "http://$LAN_IP:5058/"                       200 302 307

echo "== Cloudflare tunnel connectivity (OUTBOUND -- must survive default-deny inbound) =="
checks=$((checks+1))
if pgrep -f 'cloudflared tunnel' >/dev/null; then
  n=$(pgrep -fc 'cloudflared tunnel --config'); ok "cloudflared running ($n connectors)"
else bad "cloudflared not running"; fi
checks=$((checks+1))
if curl -s -o /dev/null --max-time 10 https://1.1.1.1/ 2>/dev/null; then ok "outbound https"
else bad "outbound https broken"; fi

echo "== container fleet =="
checks=$((checks+1))
down=$(docker ps -a --format '{{.Names}}\t{{.Status}}' 2>/dev/null | grep -vcE '\bUp\b' || true)
if [[ "${down:-0}" -eq 0 ]]; then ok "all containers up"; else bad "$down container(s) not Up"; fi

echo
if (( fail == 0 )); then echo "VERIFY PASS ($checks checks)"; exit 0; fi
echo "VERIFY FAIL: $fail of $checks checks failed"; exit 1
