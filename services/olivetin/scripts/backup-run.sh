#!/usr/bin/env bash
# Trigger the EXISTING whole-stack backup and report the result.
#
# This is not a second backup implementation. It asks the real one to run.
#
# WHY A FILE TRIGGER AND NOT `docker exec`:
#   avrana-backup.sh runs on the host - it pg_dumps inside authentik-postgresql, mariadb-dumps
#   inside bookstack-mariadb, and reads /home/cody/docker. Reaching that from this container would
#   need either the host filesystem or Docker `exec` rights, and EXEC is denied on BOTH socket
#   proxies on purpose, because exec into a container running as root is root on the host.
#   So OliveTin gets exactly ONE capability instead: it drops a marker file. A user-level
#   systemd.path unit notices it and starts avrana-backup.service. No socket, no exec, no host
#   shell, and nothing here chooses what the backup does.
#
# CONCURRENCY: systemd will not run two instances of avrana-backup.service, so a manual run
# cannot race the 02:30 timer - it simply joins the run already in progress. The script detects
# that case and waits for the same completion rather than reporting a second success.
set -uo pipefail

TRIGGER="${AVRANA_BACKUP_TRIGGER:-/state/request-backup}"
LAST_RUN="${AVRANA_LAST_RUN:-/backups/avrana/LAST_RUN.json}"
TIMEOUT="${AVRANA_BACKUP_TIMEOUT:-1500}"

stamp_of() { [ -r "$LAST_RUN" ] && stat -c %Y "$LAST_RUN" 2>/dev/null || echo 0; }
status_of() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("status","?"))' "$LAST_RUN" 2>/dev/null || echo "?"; }

before="$(stamp_of)"
echo "last completed run: $([ "$before" = 0 ] && echo none || date -u -d "@$before" '+%Y-%m-%d %H:%M:%SZ')"

if [ ! -d "$(dirname "$TRIGGER")" ]; then
  echo "FAIL  trigger directory $(dirname "$TRIGGER") is not mounted"
  exit 2
fi

echo "requesting a stack backup ..."
: > "$TRIGGER" || { echo "FAIL  could not write the trigger file"; exit 2; }

# Wait for LAST_RUN.json to advance past the timestamp we saw before requesting.
deadline=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  now="$(stamp_of)"
  if [ "$now" != "$before" ] && [ "$now" != 0 ]; then
    st="$(status_of)"
    if [ "$st" = ok ]; then
      echo "PASS  backup completed cleanly at $(date -u -d "@$now" '+%H:%M:%SZ')"
      # Verify the run it just wrote, rather than trusting the status field alone.
      newest="$(ls -1d /backups/avrana/20* 2>/dev/null | sort | tail -1)"
      if [ -n "$newest" ] && [ -r "$newest/MANIFEST.txt" ]; then
        n=$(wc -l < "$newest/MANIFEST.txt")
        echo "PASS  newest run $(basename "$newest") has a manifest of ${n} files"
      else
        echo "WARN  newest run has no readable MANIFEST.txt"
      fi
      exit 0
    fi
    echo "FAIL  backup finished with status '${st}'"
    exit 1
  fi
  sleep 5
done

echo "FAIL  no completed backup within ${TIMEOUT}s (it may still be running; check the timer)"
exit 1
