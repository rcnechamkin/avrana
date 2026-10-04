#!/usr/bin/env bash
# Avrana health report. Read-only: inspects, never changes anything.
#
# Prints one PASS / WARN / FAIL line per check, then a summary. No secrets are printed: API keys
# are used to authenticate but never echoed, and endpoint checks report status codes only.
set -uo pipefail

ro="${DOCKER_HOST_RO:-tcp://olivetin-docker-ro:2375}"
pass=0; warn=0; fail=0
P() { echo "PASS  $*"; pass=$((pass+1)); }
W() { echo "WARN  $*"; warn=$((warn+1)); }
F() { echo "FAIL  $*"; fail=$((fail+1)); }

echo "=== Avrana health report - $(date -u '+%Y-%m-%d %H:%M:%SZ') ==="
echo

echo "--- containers ---"
if ! containers="$(DOCKER_HOST="$ro" docker ps -a --format '{{.Names}}\t{{.State}}' 2>/dev/null)"; then
  F "cannot reach the inspection proxy"
else
  unhealthy=0; stopped=0; total=0
  while IFS=$'\t' read -r name state; do
    [ -z "$name" ] && continue
    total=$((total+1))
    h="$(DOCKER_HOST="$ro" docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null)"
    r="$(DOCKER_HOST="$ro" docker inspect -f '{{.RestartCount}}' "$name" 2>/dev/null)"
    if [ "$state" != "running" ]; then
      F "$name is $state"; stopped=$((stopped+1))
    elif [ "$h" = "unhealthy" ]; then
      F "$name is unhealthy"; unhealthy=$((unhealthy+1))
    elif [ "${r:-0}" -gt 5 ] 2>/dev/null; then
      W "$name has restarted ${r} times"
    fi
  done <<< "$containers"
  [ "$stopped" -eq 0 ] && [ "$unhealthy" -eq 0 ] && P "all $total containers running, none unhealthy"
fi

echo
echo "--- storage ---"
# /backups is the array's backup tree, mounted read-only into this container.
# Report the array explicitly. Docker's data root lives on the array, so "/" inside this
# container is already the array filesystem, but naming /backups makes that unambiguous.
for m in /backups /; do
  line="$(df -Ph "$m" 2>/dev/null | tail -1)" || continue
  set -- $line; avail="$4"; pct="$5"; mount="$m"
  n="${pct%\%}"
  if [ "$n" -ge 90 ] 2>/dev/null; then F "$mount ${pct} used (${avail} free)"
  elif [ "$n" -ge 80 ] 2>/dev/null; then W "$mount ${pct} used (${avail} free)"
  else P "$mount ${pct} used (${avail} free)"; fi
done

echo
echo "--- memory / load / temperature ---"
# The image has no `free` or `uptime`; read /proc directly.
if [ -r /proc/meminfo ]; then
  mt=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
  ma=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
  if [ -n "$mt" ] && [ -n "$ma" ] && [ "$mt" -gt 0 ]; then
    usedpct=$(( (mt - ma) * 100 / mt ))
    msg="memory ${usedpct}% used ($((ma/1024)) MB available of $((mt/1024)) MB)"
    if [ "$usedpct" -ge 92 ]; then F "$msg"; elif [ "$usedpct" -ge 85 ]; then W "$msg"; else P "$msg"; fi
  fi
fi
if [ -r /proc/loadavg ]; then
  read -r l1 l5 l15 _ < /proc/loadavg
  # nproc reports the cgroup CPU limit (0.75 -> 1), not host cores, which would make every
  # normal load look critical. /proc/cpuinfo still shows the host CPUs.
  cores=$(grep -c ^processor /proc/cpuinfo 2>/dev/null || echo 1)
  # Compare load against core count without bc (not in the image).
  over=$(awk -v l="$l1" -v c="$cores" 'BEGIN{print (l > c*2) ? "high" : (l > c ? "warn" : "ok")}')
  case "$over" in
    high) F "load ${l1} ${l5} ${l15} on ${cores} cores" ;;
    warn) W "load ${l1} ${l5} ${l15} on ${cores} cores" ;;
    *)    P "load ${l1} ${l5} ${l15} on ${cores} cores" ;;
  esac
fi
temp=""
for z in /sys/class/thermal/thermal_zone*/temp; do
  [ -r "$z" ] || continue
  t=$(cat "$z" 2>/dev/null || echo "")
  [ -n "$t" ] && [ "$t" -gt "${temp:-0}" ] 2>/dev/null && temp="$t"
done
if [ -n "$temp" ]; then
  c=$((temp/1000))
  if [ "$c" -ge 85 ]; then F "cpu temperature ${c}C"
  elif [ "$c" -ge 75 ]; then W "cpu temperature ${c}C"
  else P "cpu temperature ${c}C"; fi
else
  W "cpu temperature unavailable (no readable thermal zone in this container)"
fi

echo
echo "--- backups ---"
lr=/backups/avrana/LAST_RUN.json
if [ -r "$lr" ]; then
  out="$(python3 - "$lr" <<'PY' 2>/dev/null
import json, pathlib, sys, time
p = pathlib.Path(sys.argv[1]); d = json.loads(p.read_text())
age = (time.time() - p.stat().st_mtime) / 3600
print(f"{d.get('status','?')}|{age:.0f}")
PY
)"
  st="${out%%|*}"; age="${out##*|}"
  if [ "$st" = ok ] && [ "${age:-999}" -le 26 ] 2>/dev/null; then P "stack backup ok (${age}h ago)"
  elif [ "$st" = ok ]; then F "stack backup is stale (${age}h ago)"
  else F "stack backup status='${st}'"; fi
else
  F "stack backup LAST_RUN.json missing"
fi
oh=/backups/OFFHOST_LAST_RUN.json
if [ -r "$oh" ]; then
  ost="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("status","?"))' "$oh" 2>/dev/null)"
  [ "$ost" = ok ] && P "off-host copy ok" || F "off-host copy status='${ost}'"
else
  W "off-host copy not configured yet"
fi

echo
echo "--- endpoints ---"
# Internal checks use container-network names; public checks confirm the tunnel + auth gate are
# up. Only status codes are printed. A 302 to Authentik is the CORRECT answer for a gated app.
check_int() { # name url expected
  code="$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$2" 2>/dev/null || echo 000)"
  if [ "$code" = "$3" ] || [ "$code" = "200" ]; then P "$1 internal HTTP $code"
  elif [ "$code" = "000" ]; then F "$1 internal unreachable"
  else W "$1 internal HTTP $code"; fi
}
check_pub() { # name url
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$2" 2>/dev/null || echo 000)"
  case "$code" in
    200|302|307) P "$1 public HTTP $code" ;;
    000)         F "$1 public unreachable" ;;
    *)           W "$1 public HTTP $code" ;;
  esac
}
[ -n "${JELLYFIN_URL:-}" ] && check_int "jellyfin" "${JELLYFIN_URL}/health" 200
[ -n "${ABS_URL:-}" ] && check_int "audiobookshelf" "${ABS_URL}/healthcheck" 200
for h in avrana.net listen.avrana.net watch.avrana.net read.avrana.net books.avrana.net; do
  check_pub "$h" "https://$h/"
done

echo
echo "=== summary: ${pass} PASS, ${warn} WARN, ${fail} FAIL ==="
[ "$fail" -gt 0 ] && exit 1
exit 0
