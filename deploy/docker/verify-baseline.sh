#!/usr/bin/env bash
# Full Avrana baseline battery. Identical checks before cleanup, after cleanup, after reboot.
L=10.0.0.218; fail=0; n=0
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad(){ printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }
p(){ nm=$1;u=$2;shift 2; n=$((n+1)); c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$u" 2>/dev/null); for w in "$@"; do [ "$c" = "$w" ] && { ok "$nm ($c)"; return; }; done; bad "$nm -> $c, wanted $*"; }
t(){ nm=$1;h=$2;o=$3; n=$((n+1)); if timeout 5 bash -c "exec 3<>/dev/tcp/$h/$o" 2>/dev/null; then ok "$nm (tcp $o)"; else bad "$nm -> tcp $o refused"; fi; }

echo "== reachability (26) =="
t ssh $L 22
p sabnzbd http://$L:8082/config/switches/ 303
# Mylar's preserved authentication=0 intentionally exposes its LAN UI. Report that
# policy separately; a stale required-303 probe must not pretend this is newly lost state.
MYLAR_AUTH=$(python3 -c 'import re,pathlib; t=pathlib.Path("/home/cody/avrana/services/mylar3/config.ini").read_text(); m=re.search(r"(?m)^authentication\s*=\s*(\d+)",t); print(m.group(1) if m else "unknown")')
case "$MYLAR_AUTH" in
  0) p mylar3 http://$L:8090/home 200 ;;
  1) p mylar3 http://$L:8090/home 401 ;;
  2) p mylar3 http://$L:8090/home 303 ;;
  *) bad "Mylar authentication mode is unknown" ;;
esac
p jellyfin http://$L:8096/health 200
t home-assistant $L 8123
t unifi-8444 $L 8444
t unifi-8080 $L 8080
p homepage http://$L:3000/api/healthcheck 200
p radarr http://$L:7878/ping 200
p sonarr http://$L:8989/ping 200
p prowlarr http://$L:9696/ping 200
p audiobookshelf http://$L:13378/healthcheck 200
p shelfmark http://$L:8084/api/health 200
p calibre-web http://$L:8083/ 200 302
p completeseries http://$L:8085/ 200
p bookstack http://$L:6875/status 200
p beszel http://$L:8093/api/health 200
p authentik http://$L:9000/-/health/live/ 200 204
p komga http://$L:25600/actuator/health 200
p seerr http://$L:5055/api/v1/status 200
p shelfarr http://$L:5056/ 200 302 303
p tracearr http://$L:5057/ 200 302 307
p omnibus http://$L:5058/ 200 302 307
# Count real cloudflared processes by argv[0], not `pgrep -f`: a -f pattern also matches THIS
# script's own command line, so the "connector" count was self-contaminated and drifted 3<->2
# with no underlying change. Real health is the HA connection count from each tunnel's metrics.
n=$((n+1))
CFP=$(ps -eo args --no-headers | awk '$1 ~ /cloudflared$/ && $2=="tunnel"' | wc -l)
CFH=0
for mp in $(ss -ltnH 'sport = :20240 or sport = :20241 or sport = :20242' 2>/dev/null | awk '{split($4,a,":"); print a[length(a)]}'); do
  v=$(curl -s --max-time 5 "http://127.0.0.1:$mp/metrics" 2>/dev/null | awk '/^cloudflared_tunnel_ha_connections/{print $2}')
  CFH=$((CFH + ${v:-0}))
done
if [ "$CFP" -eq 2 ] && [ "$CFH" -ge 4 ]; then ok "cloudflared ($CFP tunnels, $CFH HA connections)"
else bad "cloudflared -> $CFP tunnels, $CFH HA connections (want 2 tunnels, >=4)"; fi
n=$((n+1)); if curl -s -o /dev/null --max-time 10 https://1.1.1.1/; then ok "outbound https"; else bad "outbound https"; fi
n=$((n+1)); d=$(docker ps -a --format '{{.Status}}'|grep -vcE '^Up'); if [ "$d" -eq 0 ]; then ok "all containers up"; else bad "$d not Up"; fi
echo "  -> $((n-fail))/$n"

echo "== fleet =="
T=$(docker ps -aq|wc -l); U=$(docker ps -q|wc -l); H=$(docker ps -a --format '{{.Status}}'|grep -c unhealthy)
[ "$U" = 40 ] && [ "$T" = 40 ] && ok "40/40 containers Up" || bad "$U of $T Up (want 40/40)"
[ "$H" -eq 0 ] && ok "0 unhealthy" || bad "$H unhealthy"

echo "== docker network state =="
O=$(comm -13 <(docker network ls -q|while read -r i;do echo "br-${i:0:12}";done|sort) <(ip -br link show type bridge|awk '{print $1}'|grep '^br-'|sort)|wc -l)
[ "$O" -eq 0 ] && ok "0 orphan bridges" || bad "$O orphan bridge(s)"
D=$(ip -4 -br addr show|awk '{print $3}'|sort|uniq -d|wc -l)
[ "$D" -eq 0 ] && ok "0 duplicate subnets" || bad "$D duplicate subnet(s)"
declare -A LIVE; while read -r nm id; do LIVE[$nm]=$id; done < <(docker network ls --no-trunc --format '{{.Name}} {{.ID}}')
ST=0
for c in $(docker ps -a --format '{{.Names}}'); do
  while IFS='|' read -r net id; do [ -z "$net" ] && continue
    [ "${LIVE[$net]:-MISSING}" != "$id" ] && { bad "stale netID: $c -> $net"; ST=$((ST+1)); }
  done < <(docker inspect "$c" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}|{{$v.NetworkID}}
{{end}}')
done
[ "$ST" -eq 0 ] && ok "0 stale network IDs" || true

echo "== duplicate container-name records =="
# Scope to the CURRENT dockerd process, not the unit's ActiveEnterTimestamp: these errors are
# emitted during container restore, BEFORE systemd marks the unit active (10:19:09 vs 10:19:53
# on 2026-08-29), so --since ActiveEnterTimestamp silently misses every one of them.
NR=$(journalctl -u docker -b --no-pager 2>/dev/null | tac | awk '/Starting up/{exit} {print}' | grep -c 'name is reserved')
[ "$NR" -eq 0 ] && ok "0 'name is reserved' since docker started" || bad "$NR 'name is reserved' errors"

echo "== systemd =="
F=$(systemctl --failed --no-legend|wc -l)
[ "$F" -eq 0 ] && ok "0 failed units" || bad "$F failed unit(s)"

echo "== recovered service authentication =="
python3 "$(dirname "$0")/../../scripts/recovered-auth-check.py" || fail=$((fail+1))
echo
echo "== profile-gated legacy containers absent =="
LG=$(docker ps -a --format '{{.Names}}'|grep -cE '^(komf|kavita|bazarr)$')
[ "$LG" -eq 0 ] && ok "komf/kavita/bazarr absent" || bad "$LG legacy container(s) present"

echo "== public hostnames (12) =="
hf=0
for h in auth avrana books contribute kindle listen ops read requestabook requestacomic request watch; do
  [ "$h" = avrana ] && u=https://avrana.net/ || u=https://$h.avrana.net/
  c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$u")
  case "$c" in 200|204|301|302|303|307|308|401|403) ;; *) bad "$u -> $c"; hf=$((hf+1));; esac
done
[ "$hf" -eq 0 ] && ok "12/12 hostnames healthy" || true

echo
[ "$fail" -eq 0 ] && { echo "BASELINE CLEAN"; exit 0; }
echo "BASELINE FAIL: $fail check(s)"; exit 1
