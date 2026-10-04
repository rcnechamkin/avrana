#!/usr/bin/env bash
# Post-boot validation for Avrana. Runs the three existing check suites in dependency order and
# makes a bad boot visible without anyone remembering to look.
#
# Ordering is the point. verify-array.sh is a HARD GATE: if the array is not mounted, or the wrong
# filesystem is, then verify-baseline.sh and services-health.sh would emit dozens of downstream
# failures that all trace back to one cause and bury it. So when the gate fails this stops, says
# why, and does not run them.
#
# Writes only to its own log directory on the ROOT LV -- deliberately, so the log is readable in
# exactly the situation it exists to report: the array being absent.
#
# Read-only with respect to the stack: starts nothing, restarts nothing, repairs nothing.
#
# Exit: 0 everything passed, 1 something still failed after the retry (the unit then goes failed, which
# services-health.sh reports as a NEW failed unit -- see scripts/known-failed-units.txt).

set -uo pipefail

REPO="${AVRANA_REPO:-/home/cody/avrana}"
LOGDIR="${AVRANA_STATE_DIR:-$HOME/.local/state/avrana}"
LOG="$LOGDIR/boot-verify.log"
mkdir -p "$LOGDIR"

exec > >(tee -a "$LOG") 2>&1

rule(){ printf '\n=================== %s ===================\n' "$*"; }

# Tell someone. Before Batch 1 a failed boot validation was visible only to whoever read the
# journal. Body on stdin. AVRANA_BOOT_NO_ALERT=1 disables it (tests).
alert() {
  if [[ "${AVRANA_BOOT_NO_ALERT:-0}" == 1 ]]; then cat >/dev/null; return 0; fi
  python3 "$REPO/scripts/avrana-alert.py" --subject "$1" >/dev/null 2>&1 \
    || echo "WARN alert not sent (rc=$?): $1"
}

echo
echo "########## Avrana post-boot validation - $(date '+%F %T %Z') ##########"
echo "booted: $(uptime -s)   uptime: $(uptime -p)"

rc_array=0; rc_base=0; rc_health=0

rule "1/3  storage preflight (HARD GATE)"
bash "$REPO/deploy/storage/verify-array.sh" || rc_array=$?

if (( rc_array != 0 )); then
  echo
  printf '\033[31m%s\033[0m\n' "########## GATE FAILED - STOPPING ##########"
  echo "The array did not verify. Baseline and health checks are NOT being run: with the array"
  echo "absent or wrong they would report dozens of downstream failures and bury the real cause."
  echo
  echo "Do NOT run 'docker compose up'. Docker should have refused to start on its own"
  echo "(RequiresMountsFor=/mnt/avrana_media); if it is somehow running, stop it before"
  echo "anything writes to the root LV."
  echo
  echo "Runbook: $REPO/deploy/storage/ENCLOSURE-MIGRATION.md  ('If the array does NOT mount')"
  echo "Log:     $LOG"
  printf 'verify-array.sh failed (rc=%s). Docker should not be running.\nLog: %s\n' "$rc_array" "$LOG" \
    | alert "BOOT: media array did not verify"
  exit 1
fi

# The fleet is still starting at boot+5min on this host: a fixed delay measured the boot race, not
# the boot. Wait (bounded) while containers report health=starting, then allow one retry, so only
# a failure that persists is recorded. (Batch 1, finding A1.)
SETTLE_MAX="${AVRANA_BOOT_SETTLE_SEC:-240}"
ATTEMPTS="${AVRANA_BOOT_ATTEMPTS:-2}"
RETRY_SLEEP="${AVRANA_BOOT_RETRY_SLEEP:-60}"
waited=0
while (( waited < SETTLE_MAX )) && [[ -n "$(docker ps --filter health=starting -q 2>/dev/null)" ]]; do
  sleep 10; waited=$((waited + 10))
done
(( waited > 0 )) && echo "waited ${waited}s for containers still starting"

attempt=1
while :; do
  rc_base=0; rc_health=0

  rule "2/3  docker baseline (attempt $attempt/$ATTEMPTS)"
  bash "$REPO/deploy/docker/verify-baseline.sh" || rc_base=$?

  rule "3/3  service health (attempt $attempt/$ATTEMPTS)"
  # This unit is by definition unfinished while it runs, and services-health.service may still
  # carry a failed state from its own first run during the same boot race. Neither says anything
  # about the boot, and counting them is what made the two units fail on each other forever.
  AVRANA_HEALTH_IGNORE_UNITS="avrana-boot-verify.service" AVRANA_HEALTH_NO_ALERT=1 \
    bash "$REPO/scripts/services-health.sh" || rc_health=$?

  if (( rc_base == 0 && rc_health == 0 )) || (( attempt >= ATTEMPTS )); then break; fi
  echo
  echo "attempt $attempt failed (baseline rc=$rc_base, health rc=$rc_health); retrying in ${RETRY_SLEEP}s"
  sleep "$RETRY_SLEEP"
  attempt=$((attempt + 1))
done

rule "summary"
printf '  storage preflight : %s\n' "$( ((rc_array==0))  && echo PASS || echo "FAIL(rc=$rc_array)" )"
printf '  docker baseline   : %s\n' "$( ((rc_base==0))   && echo PASS || echo "FAIL(rc=$rc_base)" )"
printf '  service health    : %s\n' "$( ((rc_health==0)) && echo PASS || echo "FAIL(rc=$rc_health)" )"
echo "  log: $LOG"

if (( rc_array == 0 && rc_base == 0 && rc_health == 0 )); then
  printf '\n\033[32m%s\033[0m\n' "BOOT VALIDATION CLEAN"
  exit 0
fi
printf '\n\033[31m%s\033[0m\n' "BOOT VALIDATION FAILED - see above"
printf 'Boot validation failed after %s attempt(s).\n  docker baseline rc=%s\n  service health  rc=%s\nLog: %s\nRe-run: systemctl --user start avrana-boot-verify.service\n' \
  "$attempt" "$rc_base" "$rc_health" "$LOG" | alert "BOOT validation FAILED"
exit 1
