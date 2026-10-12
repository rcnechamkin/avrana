#!/usr/bin/env bash
set -u

# All checks live in run_checks so their output can be captured: the FAIL lines are what an alert
# carries. The function body is deliberately not re-indented, to keep the checks diffable against
# the previous version. Alert handling is at the bottom of the file. (Batch 1, alert delivery.)
run_checks() {
failures=0

check_url() {
  name=$1
  url=$2
  if curl --fail --silent --show-error --max-time 10 "$url" >/dev/null; then
    printf 'OK   %s\n' "$name"
  else
    printf 'FAIL %s (%s)\n' "$name" "$url" >&2
    failures=$((failures + 1))
  fi
}

# After a cold boot the fleet needs several minutes on this host (Docker's data-root is on a USB
# disk), and both this check and boot-verify first fire at boot+5min. Wait, bounded, while any
# container still reports health=starting, so a normal boot is not recorded as a failure.
# At steady state nothing is starting and this costs one `docker ps`. (Batch 1, finding A1.)
settle_max="${AVRANA_HEALTH_SETTLE_SEC:-180}"
settle_waited=0
while [ "$settle_waited" -lt "$settle_max" ] \
      && [ -n "$(docker ps --filter health=starting -q 2>/dev/null)" ]; do
  sleep 10
  settle_waited=$((settle_waited + 10))
done
if [ "$settle_waited" -gt 0 ]; then
  printf 'INFO waited %ss for containers still starting\n' "$settle_waited"
fi

check_url radarr http://10.0.0.218:7878/ping
check_url sonarr http://10.0.0.218:8989/ping
check_url prowlarr http://10.0.0.218:9696/ping
check_url seerr http://127.0.0.1:5055/api/v1/status
check_url jellyfin http://127.0.0.1:8096/health
check_url audiobookshelf http://10.0.0.218:13378/healthcheck
check_url komga http://127.0.0.1:25600/actuator/health
check_url shelfmark http://10.0.0.218:8084/api/health
check_url calibre-web-automated http://10.0.0.218:8083/
check_url completeseries http://10.0.0.218:8085/
check_url homepage http://10.0.0.218:3000/api/healthcheck
check_url bookstack http://10.0.0.218:6875/status
check_url beszel http://10.0.0.218:8093/api/health
check_url authentik http://10.0.0.218:9000/-/health/live/

# Authentik's OIDC signing certificate ("authentik Self-signed Certificate") is not managed by
# Authentik, so it is not regenerated when it expires (2027-08-13 as of the 2026-10-06 audit); an
# expired one breaks every OIDC login. Read its expiry from the public JWKS, warn 60 days ahead.
# (Batch 5, Authentik audit finding 8.)
signing_end=$(curl --silent --max-time 10 https://auth.avrana.net/application/o/komga/jwks/ \
  | python3 -c '
import base64, json, subprocess, sys
try:
    key = json.load(sys.stdin)["keys"][0]
    der = base64.b64decode(key["x5c"][0])
    out = subprocess.run(["openssl", "x509", "-inform", "DER", "-noout", "-enddate"], input=der, capture_output=True, check=True).stdout
    print(out.decode().strip().split("=", 1)[1])
except Exception:
    pass' 2>/dev/null)
if [ -z "$signing_end" ]; then
  printf 'WARN authentik signing certificate: could not read the JWKS\n' >&2
else
  signing_days=$(( ($(date -d "$signing_end" +%s) - $(date +%s)) / 86400 ))
  if [ "$signing_days" -lt 60 ]; then
    printf 'WARN authentik signing certificate expires in %s days (%s): rotate it, see docs/findings/2026-10-06-authentik-blueprint-audit.md\n' "$signing_days" "$signing_end" >&2
  else
    printf 'OK   authentik signing certificate valid %s more days\n' "$signing_days"
  fi
fi

# libation-status bind-mounts ONE file (LibationContext.db). If Libation ever replaces that file
# instead of writing in place, the container keeps the old inode and reports stale state for ever
# (same fault class as the 2026-08-29 CWA failure; bug hunt risk 6). Compare inodes.
# (Batch 6.)
host_inode=$(stat -c %i /home/cody/avrana/services/libation/config/LibationContext.db 2>/dev/null)
container_inode=$(docker exec libation-status stat -c %i /data/LibationContext.db 2>/dev/null)
if [ -n "$host_inode" ] && [ -n "$container_inode" ]; then
  if [ "$host_inode" = "$container_inode" ]; then
    printf 'OK   libation-status sees the live database file\n'
  else
    printf 'WARN libation-status holds a replaced database file (dead inode): docker compose -p libation-status up -d --force-recreate\n' >&2
  fi
fi

# ---- media array: mounted, the right filesystem, writable, no kernel storage errors ------------
# Until Batch 1 (finding A2) these were checked once, by verify-array.sh at boot+5min. A USB drop
# or an ext4 remount-read-only later in the boot went unseen until the 02:30 backup failed, and
# with the array unmounted the df below measured the ROOT LV and printed "OK disk
# /mnt/avrana_media". The identity values match deploy/storage/verify-array.sh.
array_root="${AVRANA_ARRAY_ROOT:-/mnt/avrana_media}"
array_uuid="${AVRANA_ARRAY_UUID:-f2276a43-a56c-4e18-80a1-1845918243d4}"
array_mounted=0
if ! mountpoint -q "$array_root"; then
  printf 'FAIL array %s is NOT mounted\n' "$array_root" >&2
  failures=$((failures + 1))
else
  array_mounted=1
  got_uuid=$(findmnt -n -o UUID --target "$array_root" 2>/dev/null | head -1)
  if [ "$got_uuid" = "$array_uuid" ]; then
    printf 'OK   array mounted, UUID matches\n'
  else
    printf 'FAIL array WRONG FILESYSTEM at %s (uuid %s, expected %s)\n' \
      "$array_root" "${got_uuid:-none}" "$array_uuid" >&2
    failures=$((failures + 1))
  fi
  array_opts=$(findmnt -n -o OPTIONS --target "$array_root" 2>/dev/null | head -1)
  case ",$array_opts," in
    *,ro,*)
      printf 'FAIL array is mounted READ-ONLY (likely an aborted journal)\n' >&2
      failures=$((failures + 1)) ;;
    *) printf 'OK   array mounted read-write\n' ;;
  esac
fi

# comics_merged is a mergerfs union over two array directories. When it is not mounted Docker
# binds the empty underlying directory and Komga serves an empty library, which went unnoticed
# for five days in August (finding A6). Only meaningful while the array itself is mounted.
comics_merged="${AVRANA_COMICS_MERGED:-/mnt/avrana_media/comics_merged}"
if [ "$array_mounted" -eq 1 ]; then
  if mountpoint -q "$comics_merged" && [ "$(findmnt -n -o FSTYPE "$comics_merged" 2>/dev/null)" = fuse.mergerfs ]; then
    printf 'OK   comics_merged mounted (mergerfs)
'
  else
    printf 'FAIL comics_merged is not a mergerfs mount; Komga would serve an empty library
' >&2
    failures=$((failures + 1))
  fi
fi

for mountpoint in / "$array_root"; do
  # The array's usage is only meaningful when the array is what is mounted there.
  if [ "$mountpoint" = "$array_root" ] && [ "$array_mounted" -ne 1 ]; then
    continue
  fi
  usage=$(df -P "$mountpoint" | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')
  if [ -z "$usage" ] || [ "$usage" -ge 90 ]; then
    printf 'FAIL disk %s is %s%% full\n' "$mountpoint" "${usage:-unknown}" >&2
    failures=$((failures + 1))
  else
    printf 'OK   disk %s (%s%% used)\n' "$mountpoint" "$usage"
  fi
done

unhealthy=$(docker ps --filter health=unhealthy --format '{{.Names}}' | paste -sd, -)
if [ -n "$unhealthy" ]; then
  printf 'FAIL unhealthy containers: %s\n' "$unhealthy" >&2
  failures=$((failures + 1))
else
  printf 'OK   no unhealthy containers\n'
fi

restarting=$(docker ps --filter status=restarting --format '{{.Names}}' | paste -sd, -)
if [ -n "$restarting" ]; then
  printf 'FAIL restarting containers: %s\n' "$restarting" >&2
  failures=$((failures + 1))
else
  printf 'OK   no restarting containers\n'
fi

if find /mnt/avrana_media/audiobooks -type f -name '*.tmp.m4b' -print -quit | grep -q .; then
  printf 'WARN interrupted Audiobookshelf metadata embeds (*.tmp.m4b) found\n' >&2
fi

# Backup freshness: a backup timer that silently stops is worse than none. Read the last-run
# status the backup writes and fail if it is missing, stale (>26h, i.e. a daily run was
# skipped), or did not complete cleanly.
backup_status=$(python3 - <<'PY' 2>/dev/null
import json, time, pathlib
p = pathlib.Path("/mnt/avrana_media/.backups/avrana/LAST_RUN.json")
if not p.exists():
    print("missing"); raise SystemExit
d = json.loads(p.read_text())
age_h = (time.time() - p.stat().st_mtime) / 3600
if age_h > 26:
    print(f"stale {age_h:.0f}h"); raise SystemExit
print("ok" if d.get("status") == "ok" else f"{d.get('status')} failed={','.join(d.get('failed') or [])}")
PY
)
if [ "$backup_status" = ok ]; then
  printf 'OK   backups (last run clean)\n'
else
  printf 'FAIL backups: %s\n' "${backup_status:-unknown}" >&2
  failures=$((failures + 1))
fi

# Off-host copy: the local backup being clean says nothing about whether it left the building.
# An array failure takes the media AND every local backup, so a silently-stopped off-host sync is
# the difference between an inconvenience and a total loss. Skipped entirely until it is set up,
# so this check never nags before the remote exists.
offhost_state="/mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json"
if [ -f "$offhost_state" ]; then
  offhost_status=$(python3 - <<'PY' 2>/dev/null
import json, time, pathlib
p = pathlib.Path("/mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json")
d = json.loads(p.read_text())
age_h = (time.time() - p.stat().st_mtime) / 3600
if age_h > 50:            # daily timer; two consecutive misses before alarming
    print(f"stale {age_h:.0f}h"); raise SystemExit
print("ok" if d.get("status") == "ok" else f"{d.get('status')}: {d.get('detail','')}")
PY
)
  if [ "$offhost_status" = ok ]; then
    printf 'OK   off-host backup (last sync clean)\n'
  else
    printf 'FAIL off-host backup: %s\n' "${offhost_status:-unknown}" >&2
    failures=$((failures + 1))
  fi
fi

# Every expected container must be running. Until Batch 3 (finding A7) only `unhealthy` and
# `restarting` were looked at, so an exited or never-started container was invisible, and the
# one named check (`docker inspect ... StartedAt libation`) passed for a stopped container too.
# The list lives in deploy/docker/expected-containers.txt; an unlisted running container is a
# warning (the restore test's throwaway Audiobookshelf is expected now and then).
expected_file="$(dirname "$0")/../deploy/docker/expected-containers.txt"
if [ -f "$expected_file" ]; then
  running=$(docker ps --format '{{.Names}}')
  expected=$(sed -e 's/#.*//' -e 's/[[:space:]]//g' "$expected_file" | grep -v '^$')
  missing=""
  for name in $expected; do
    printf '%s\n' "$running" | grep -qx "$name" || missing="$missing $name"
  done
  if [ -n "$missing" ]; then
    printf 'FAIL expected containers not running:%s\n' "$missing" >&2
    failures=$((failures + 1))
  else
    printf 'OK   all %s expected containers running\n' "$(printf '%s\n' "$expected" | wc -l)"
  fi
  extra=""
  for name in $running; do
    case "$name" in abs-restore-test|avrana-restore-test-*) continue ;; esac
    printf '%s\n' "$expected" | grep -qx "$name" || extra="$extra $name"
  done
  [ -n "$extra" ] && printf 'WARN containers running but not in expected-containers.txt:%s\n' "$extra" >&2
else
  printf 'FAIL expected-containers.txt not found beside this script\n' >&2
  failures=$((failures + 1))
fi

# Gate G1 (forensic audit D4, docs/design/MEDIA-2.0.md section 4): avrana-portal,
# avrana-kindle-connector and olivetin trust X-authentik-* headers, so none of them may share a
# network with a sibling container; each sits on its own authentik_<name> network with the
# Authentik server only. The decision is in check-network-isolation.py (tested offline). Until the
# change is applied (the private networks do not exist) it prints WARN and passes; once they exist
# any drift is a FAIL. Runbook: docs/runbooks/g1-network-isolation.md. (Media 2.0, AVR-355.)
isolation_script="$(dirname "$0")/check-network-isolation.py"
if [ -f "$isolation_script" ]; then
  net_ids=$(docker network ls -q 2>/dev/null)
  net_json=""
  [ -n "$net_ids" ] && net_json=$(printf '%s\n' "$net_ids" | xargs docker network inspect 2>/dev/null)
  if [ -z "$net_json" ]; then
    printf 'WARN network isolation (G1): could not read docker network data\n' >&2
  else
    printf '%s\n' "$net_json" | python3 "$isolation_script" || failures=$((failures + 1))
  fi
else
  printf 'FAIL check-network-isolation.py not found beside this script\n' >&2
  failures=$((failures + 1))
fi

# The recycle bin held 650 GB after the September Radarr grab loop (finding A13). Say so before
# it fills the array. Two entries, so the walk is cheap.
recycle_dir=/mnt/avrana_media/.recycle
if [ -d "$recycle_dir" ]; then
  recycle_gb=$(du -sb "$recycle_dir" 2>/dev/null | awk '{printf "%d", $1 / 1073741824}')
  if [ "${recycle_gb:-0}" -ge 300 ]; then
    printf 'WARN recycle bin holds %s GB (a download loop? see bug hunt A13)\n' "$recycle_gb" >&2
  fi
fi

# Every ENABLED cloudflared unit must be active. Derived rather than listed so that retiring the
# old comics tunnel (owner's staged script) needs no edit here; none enabled at all is a failure.
tunnel_units=$(systemctl list-unit-files --state=enabled --no-legend 'cloudflared*.service' 2>/dev/null | awk '{print $1}')
if [ -z "$tunnel_units" ]; then
  printf 'FAIL no cloudflared unit is enabled\n' >&2
  failures=$((failures + 1))
fi
for unit in $tunnel_units; do
  if systemctl is-active --quiet "$unit"; then
    printf 'OK   %s\n' "$unit"
  else
    printf 'FAIL %s\n' "$unit" >&2
    failures=$((failures + 1))
  fi
done

# cloudflared-health.service was RETIRED 2026-08-28 with the Health API it fronted
# (audit H1). It is deliberately gone, so checking for it here reported a failure for a
# unit that is supposed to be absent. The two surviving connectors are checked above.

# The media-array gate excludes positively identified invalid recovery-snapshot reads.
# Keep the actual snapshot failure visible here, even after old failed-unit states are cleared.
if journalctl -b -k --no-pager >/dev/null 2>&1; then
  if ! journalctl -b -k --no-pager 2>/dev/null | python3 "$(dirname "$0")/storage-log-check.py" --mode snapshot; then
    failures=$((failures + 1))
  fi
  # Storage/USB errors anywhere in this boot's kernel log, every run and not only at boot+5min
  # (finding A2). The classifier prints its own OK/FAIL line. A logged error stays red until the
  # next boot on purpose: an I/O error on the only array is not something to age out.
  if ! journalctl -b -k --no-pager 2>/dev/null | python3 "$(dirname "$0")/storage-log-check.py" --mode array; then
    failures=$((failures + 1))
  fi
else
  printf 'FAIL snapshot status: kernel log unreadable\n' >&2
  failures=$((failures + 1))
fi

# ---- systemd failed units -------------------------------------------------------------
# The audit of 2026-08-28 found 13 failed units while this script reported all-OK, because it
# never looked. It looks now. To stay useful rather than noisy, units listed in
# scripts/known-failed-units.txt are counted as "acknowledged" and do NOT raise a failure;
# anything failing that is not on that list does. That way triaged debt stays quiet while a
# genuinely new failure is loud on the very next 15-minute run.
known_units_file="$(dirname "$0")/known-failed-units.txt"

# Units this check never counts. (Batch 1, finding A1.)
#   - services-health.service: this script's own unit. Its failed state is only the result of
#     the PREVIOUS run, so counting it makes one bad run fail every later run that is started
#     by hand or by boot-verify.
#   - anything in AVRANA_HEALTH_IGNORE_UNITS: boot-verify passes its own unit name here when it
#     runs this script as its third stage, because it is by definition not finished yet.
# Before this, the two units each failed on the other's failed state and neither could ever
# pass again without both being started at the same instant (2026-09-27 and 2026-09-28).
# A failed avrana-boot-verify.service is still reported by the 15-minute run: a bad boot stays
# visible until boot-verify is re-run, and it can now be re-run on its own.
ignore_units="services-health.service ${AVRANA_HEALTH_IGNORE_UNITS:-}"

check_failed_units() {
  scope=$1                       # "system" or "user"
  if [ "$scope" = user ]; then
    failed=$(systemctl --user --failed --no-legend --plain 2>/dev/null | awk '{print $1}')
  else
    failed=$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}')
  fi

  ack=0
  new=""
  for unit in $failed; do
    [ -n "$unit" ] || continue
    if [ "$scope" = user ]; then
      case " $ignore_units " in *" $unit "*) continue ;; esac
    fi
    if [ -f "$known_units_file" ] && grep -qE "^${scope}:${unit}([[:space:]]|#|$)" "$known_units_file"; then
      ack=$((ack + 1))
    else
      new="$new $unit"
    fi
  done

  if [ -n "$new" ]; then
    printf 'FAIL systemd(%s) NEW failed unit(s):%s\n' "$scope" "$new" >&2
    failures=$((failures + 1))
  elif [ "$ack" -gt 0 ]; then
    printf 'OK   systemd(%s) no new failures (%s acknowledged, see known-failed-units.txt)\n' "$scope" "$ack"
  else
    printf 'OK   systemd(%s) no failed units\n' "$scope"
  fi
}

check_failed_units system
check_failed_units user

return "$failures"
}

# ---- run, then tell someone --------------------------------------------------------------------
# Detection without delivery is how this check stayed red from 2026-09-28 to 2026-10-03 unseen.
# An e-mail goes out through scripts/avrana-alert.py when:
#   - the check has failed on two consecutive runs (one bad run after a restart is not news), and
#     the set of FAIL lines differs from the last one mailed, or the last mail is over 24h old;
#   - the check passes again after a failure was mailed (one RECOVERED message).
# AVRANA_HEALTH_NO_ALERT=1 disables this; boot-verify sets it for its embedded run and sends its
# own message. State is three KEY=VALUE lines that are parsed, never sourced.
out="$(run_checks 2>&1)"
rc=$?
printf '%s\n' "$out"

if [ "${AVRANA_HEALTH_NO_ALERT:-0}" != 1 ]; then
  alert_script="$(dirname "$0")/avrana-alert.py"
  state_dir="${AVRANA_STATE_DIR:-$HOME/.local/state/avrana}"
  state_file="$state_dir/health-alert.state"
  mkdir -p "$state_dir"

  state_get() { [ -f "$state_file" ] && sed -n "s/^$1=//p" "$state_file" | head -1; }
  consecutive=$(state_get consecutive); consecutive=${consecutive:-0}
  alerted_sig=$(state_get alerted_sig)
  alerted_at=$(state_get alerted_at); alerted_at=${alerted_at:-0}
  case "$consecutive$alerted_at" in *[!0-9]*) consecutive=0; alerted_at=0 ;; esac
  now=$(date +%s)

  send_alert() {   # send_alert <subject>   (body on stdin); prints one line, returns the rc
    python3 "$alert_script" --subject "$1" >/dev/null 2>&1
    arc=$?
    case "$arc" in
      0) printf 'INFO alert sent: %s\n' "$1" ;;
      3) printf 'WARN alert NOT sent (delivery not configured): %s\n' "$1" >&2 ;;
      *) printf 'WARN alert NOT sent (delivery failed, rc=%s): %s\n' "$arc" "$1" >&2 ;;
    esac
    return "$arc"
  }

  if [ "$rc" -ne 0 ]; then
    consecutive=$((consecutive + 1))
    fails=$(printf '%s\n' "$out" | grep '^FAIL' | sort)
    sig=$(printf '%s' "$fails" | sha256sum | cut -c1-16)
    if [ "$consecutive" -ge 2 ] && { [ "$sig" != "$alerted_sig" ] || [ $((now - alerted_at)) -gt 86400 ]; }; then
      if printf '%s\n\nFull output: journalctl --user -u services-health.service -n 60\n' "$fails" \
           | send_alert "health FAIL: $rc check(s)"; then
        alerted_sig=$sig; alerted_at=$now
      fi
    fi
  else
    if [ -n "$alerted_sig" ]; then
      if printf 'All checks pass again.\n' | send_alert "health RECOVERED"; then
        alerted_sig=""; alerted_at=0
      fi
    fi
    consecutive=0
  fi

  tmp_state="$state_file.$$"
  printf 'consecutive=%s\nalerted_sig=%s\nalerted_at=%s\n' "$consecutive" "$alerted_sig" "$alerted_at" > "$tmp_state" \
    && mv "$tmp_state" "$state_file"
fi

exit "$rc"
