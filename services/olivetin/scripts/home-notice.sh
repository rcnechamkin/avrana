#!/usr/bin/env bash
# Set or clear the one member notice Avrana Home shows (AVR-365).
#
# Writes {"id": "<notice>", "set": "<UTC time>"} to $AVRANA_NOTICE_FILE, or removes it for "clear". Home mounts the
# directory read-only and shows the words it holds for that ID (services/avrana-home/avrana_home/app/notice.py); this
# file never carries words, markup or links, so nothing typed here can reach a member's screen.
#
# The argument comes from the action's fixed `choices` and is re-checked against ALLOWED below, exactly as
# restart-service.sh does: the dropdown is convenience, this list is the control. Keep ALLOWED, the action's choices
# in config/config.yaml and notice.NOTICES in step (tests/test_home_notice.py checks all three).
set -euo pipefail

ALLOWED="video-unavailable audiobooks-unavailable comics-unavailable books-unavailable requests-unavailable slow maintenance"
FILE="${AVRANA_NOTICE_FILE:-/state/home-notice/current.json}"
DIR="$(dirname "$FILE")"
choice="${1:-}"

if [ ! -d "$DIR" ]; then
  echo "FAIL  notice directory $DIR is not mounted"
  exit 2
fi

if [ "$choice" = clear ]; then
  rm -f -- "$FILE"
  echo "PASS  notice cleared; members stop seeing it within a few seconds"
  exit 0
fi

ok=0
for allowed in $ALLOWED; do
  if [ "$choice" = "$allowed" ]; then ok=1; fi
done
if [ "$ok" != 1 ]; then
  echo "FAIL  not an allowlisted notice"
  exit 2
fi

now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
tmp="$(mktemp "$DIR/.notice.XXXXXX")"
printf '{"id": "%s", "set": "%s"}\n' "$choice" "$now" > "$tmp"
chmod 0644 "$tmp"
mv -f -- "$tmp" "$FILE"            # atomic within the directory: Home never reads half a file
echo "PASS  notice '$choice' set at $now; members see it within a few seconds"
