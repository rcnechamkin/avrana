#!/usr/bin/env bash
# Read-only storage preflight for the Avrana media array.
#
# Proves the array is present, is the RIGHT filesystem, is writable, and that Docker's data-root
# actually lands on it. That last check is the one that matters: on 2026-08-30 Docker started with
# the array absent, found /mnt/avrana_media/docker to be an ordinary directory on the root LV, and
# built an empty estate there while 2.6T of real data sat on an unmounted disk.
# See deploy/docker/INCIDENT-2026-08-30.md.
#
# READ-ONLY. Creates nothing, writes nothing, mounts nothing, repairs nothing. Safe to run at any
# time -- including with the array absent, which is the case it exists to report.
#
# Device names are NOT authoritative. The enclosure has already presented as sdb and sdc across
# boots and will change again when the hardware is swapped. The UUID is the identity.
#
# Exit: 0 all checks pass, 1 one or more failed.

set -uo pipefail

ARRAY="${AVRANA_ARRAY_ROOT:-/mnt/avrana_media}"
WANT_UUID="${AVRANA_ARRAY_UUID:-f2276a43-a56c-4e18-80a1-1845918243d4}"
WANT_FSTYPE="ext4"
# 8 TB drive -> ~7.3 TiB usable. Generous bounds: catches "mounted the wrong disk" and
# "fell through to the 58G root LV" without tripping on normal fs-overhead variation.
MIN_TIB="7.0"
MAX_TIB="7.6"
WANT_DIRS=(audiobooks books calibre-library comics docker incoming movies music tv .backups)

fail=0
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
skip() { printf '  \033[90mSKIP\033[0m %s\n' "$*"; }

echo "== array identity =="

# ---- 1. is it a mount point at all? -----------------------------------------------------------
# Everything below is meaningless if this fails, so bail immediately and loudly.
if ! mountpoint -q "$ARRAY"; then
  bad "$ARRAY is NOT a mount point -- the array is not mounted"
  echo
  printf '\033[31m%s\033[0m\n' "ARRAY ABSENT. Do not start Docker. Do not run 'docker compose up'."
  printf '\033[31m%s\033[0m\n' "Docker's data-root would be created on the root LV and the stack"
  printf '\033[31m%s\033[0m\n' "would look empty while the real data sits on an unmounted disk."
  echo
  echo "  next: check the enclosure is powered and enumerated --"
  echo "        lsusb ; lsblk -o NAME,SIZE,FSTYPE,UUID ; ls -l /dev/disk/by-uuid/$WANT_UUID"
  exit 1
fi
ok "$ARRAY is a mount point"

SRC="$(findmnt -n -o SOURCE --target "$ARRAY" 2>/dev/null | head -1)"
[ -n "$SRC" ] && ok "mounted from $SRC (informational -- device names are not authoritative)"

# ---- 2. UUID is the identity ------------------------------------------------------------------
GOT_UUID="$(findmnt -n -o UUID --target "$ARRAY" 2>/dev/null | head -1)"
if [ -z "$GOT_UUID" ]; then
  bad "could not determine the mounted filesystem's UUID"
elif [ "$GOT_UUID" = "$WANT_UUID" ]; then
  ok "UUID $GOT_UUID"
else
  bad "WRONG FILESYSTEM MOUNTED -- uuid $GOT_UUID, expected $WANT_UUID"
fi

# ---- 3. filesystem type -----------------------------------------------------------------------
GOT_FS="$(findmnt -n -o FSTYPE --target "$ARRAY" 2>/dev/null | head -1)"
[ "$GOT_FS" = "$WANT_FSTYPE" ] && ok "fstype $GOT_FS" || bad "fstype $GOT_FS, expected $WANT_FSTYPE"

# ---- 4. writable, not remounted read-only -----------------------------------------------------
# An aborted EXT4 journal remounts the filesystem ro underneath a running stack. Containers stay
# 'Up' and healthy while every write fails, so this is checked explicitly rather than inferred.
OPTS="$(findmnt -n -o OPTIONS --target "$ARRAY" 2>/dev/null | head -1)"
case ",$OPTS," in
  *,ro,*) bad "filesystem is mounted READ-ONLY (opts: $OPTS) -- likely an aborted journal" ;;
  *)      ok  "mounted read-write" ;;
esac

echo
echo "== capacity =="

# ---- 5. size is consistent with the 8 TB array ------------------------------------------------
BYTES="$(df -P --block-size=1 "$ARRAY" 2>/dev/null | awk 'NR==2{print $2}')"
if [ -z "${BYTES:-}" ]; then
  bad "could not read capacity"
else
  read -r TIB VERDICT < <(awk -v b="$BYTES" -v lo="$MIN_TIB" -v hi="$MAX_TIB" \
    'BEGIN{t=b/(1024^4); printf "%.2f %s\n", t, (t>=lo && t<=hi) ? "in" : "out"}')
  if [ "$VERDICT" = "in" ]; then
    ok "capacity ${TIB} TiB (expected ${MIN_TIB}-${MAX_TIB})"
  else
    bad "capacity ${TIB} TiB is OUTSIDE ${MIN_TIB}-${MAX_TIB} TiB -- wrong disk, or the mount fell through to the root LV"
  fi
fi

echo
echo "== expected layout =="

# ---- 6. top-level directories -----------------------------------------------------------------
missing=()
for d in "${WANT_DIRS[@]}"; do [ -d "$ARRAY/$d" ] || missing+=("$d"); done
if (( ${#missing[@]} == 0 )); then
  ok "all ${#WANT_DIRS[@]} expected top-level directories present"
else
  bad "missing top-level dirs: ${missing[*]}"
fi

echo
echo "== docker data-root =="

# ---- 7. Docker is CONFIGURED to use the array -------------------------------------------------
# Prefer the live daemon; fall back to daemon.json so this still works with Docker stopped, which
# is exactly the state a post-incident preflight runs in.
DATAROOT=""
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  DATAROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)"
  SRC_OF="live daemon"
elif [ -r /etc/docker/daemon.json ]; then
  DATAROOT="$(python3 -c 'import json,sys;print(json.load(open("/etc/docker/daemon.json")).get("data-root",""))' 2>/dev/null)"
  SRC_OF="daemon.json (daemon not running)"
fi

WANT_ROOT="$ARRAY/docker"
if [ -z "$DATAROOT" ]; then
  warn "could not determine Docker's data-root (daemon down and daemon.json unreadable)"
else
  if [ "$DATAROOT" = "$WANT_ROOT" ]; then
    ok "configured data-root is $DATAROOT [$SRC_OF]"
  else
    bad "data-root is $DATAROOT, expected $WANT_ROOT [$SRC_OF]"
  fi
fi

# ---- 8. ...and that it PHYSICALLY lands on the array, not the root LV --------------------------
# The whole 2026-08-30 fault in one check. A matching path proves nothing: /mnt/avrana_media/docker
# is a valid path on the root LV too when nothing is mounted. Compare device ids.
if [ -d "$WANT_ROOT" ]; then
  DEV_ARRAY="$(stat -c %d "$ARRAY" 2>/dev/null)"
  DEV_ROOT="$(stat -c %d / 2>/dev/null)"
  DEV_DATA="$(stat -c %d "$WANT_ROOT" 2>/dev/null)"
  if [ "$DEV_DATA" = "$DEV_ARRAY" ] && [ "$DEV_ARRAY" != "$DEV_ROOT" ]; then
    ok "data-root is on the array (device-id $DEV_DATA, root LV is $DEV_ROOT)"
  elif [ "$DEV_DATA" = "$DEV_ROOT" ]; then
    bad "DATA-ROOT IS ON THE ROOT LV (device-id $DEV_DATA) -- this is the 2026-08-30 fault"
  else
    bad "data-root device-id $DEV_DATA matches neither the array ($DEV_ARRAY) nor the root LV ($DEV_ROOT)"
  fi
else
  warn "$WANT_ROOT does not exist yet"
fi

echo
echo "== device health (read-only, best effort) =="

# ---- 9. kernel-visible storage errors ---------------------------------------------------------
# Only this boot: older events are history, not a live signal.
if journalctl -b -k --no-pager >/dev/null 2>&1; then
  if journalctl -b -k --no-pager 2>/dev/null | python3 "$(dirname "$0")/../../scripts/storage-log-check.py" --mode array; then
    ok "kernel storage classification passed; unrelated snapshot failures are monitored separately"
  else
    bad "storage/USB errors require inspection (known invalid recovery-snapshot read errors are reported separately)"
  fi
else
  skip "kernel log unreadable"
fi

# ext4 keeps a running error counter in sysfs; readable without root.
DEVNAME="$(basename "${SRC:-}")"
SYSFS="/sys/fs/ext4/$DEVNAME/errors_count"
if [ -r "$SYSFS" ]; then
  EC="$(cat "$SYSFS" 2>/dev/null)"
  [ "${EC:-0}" -eq 0 ] && ok "ext4 errors_count = 0" || bad "ext4 errors_count = $EC (recorded in the superblock)"
else
  skip "ext4 errors_count unavailable for ${DEVNAME:-unknown}"
fi

# SMART needs root and a device that passes it through USB; never fail the run on its absence.
if command -v smartctl >/dev/null 2>&1 && [ -n "${SRC:-}" ] && [ "$(id -u)" -eq 0 ]; then
  DISK="/dev/$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1)"
  if [ -b "$DISK" ]; then
    if smartctl -H "$DISK" 2>/dev/null | grep -qiE 'PASSED|OK'; then
      ok "SMART health PASSED ($DISK)"
    else
      warn "SMART did not report PASSED for $DISK (USB bridges often block SMART; not conclusive)"
    fi
  fi
else
  skip "SMART (needs root; USB bridges frequently block it)"
fi

echo
if (( fail == 0 )); then
  printf '\033[32m%s\033[0m\n' "ARRAY OK -- all checks passed."
  exit 0
fi
printf '\033[31m%s\033[0m\n' "ARRAY VERIFY FAILED: $fail check(s). Do not start array-dependent services."
exit 1
