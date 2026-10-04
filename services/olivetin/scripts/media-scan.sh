#!/usr/bin/env bash
# Trigger a library scan on Jellyfin or Audiobookshelf through each product's supported API.
#
# Takes one fixed target, not a URL or a command. Credentials come from the environment and are
# never printed, never passed on the command line (where they would show in process listings),
# and never echoed on failure - only HTTP status codes are reported.
set -euo pipefail

target="${1:-}"

case "$target" in
  jellyfin)
    : "${JELLYFIN_URL:?JELLYFIN_URL not set}"
    : "${JELLYFIN_API_KEY:?JELLYFIN_API_KEY not set}"
    echo "triggering Jellyfin library refresh ..."
    code="$(curl -s -o /dev/null -m 30 -w '%{http_code}' \
      -X POST "${JELLYFIN_URL}/Library/Refresh" \
      -H "Authorization: MediaBrowser Token=${JELLYFIN_API_KEY}" || echo 000)"
    case "$code" in
      204|200) echo "PASS  Jellyfin scan started (HTTP $code)"; exit 0 ;;
      401|403) echo "FAIL  Jellyfin rejected the API key (HTTP $code)"; exit 1 ;;
      000)     echo "FAIL  Jellyfin unreachable"; exit 1 ;;
      *)       echo "FAIL  Jellyfin returned HTTP $code"; exit 1 ;;
    esac
    ;;
  audiobookshelf)
    : "${ABS_URL:?ABS_URL not set}"
    : "${ABS_API_KEY:?ABS_API_KEY not set}"
    echo "triggering Audiobookshelf library scans ..."
    libs="$(curl -s -m 20 "${ABS_URL}/api/libraries" \
      -H "Authorization: Bearer ${ABS_API_KEY}" | jq -r '.libraries[]?.id' 2>/dev/null || true)"
    if [ -z "$libs" ]; then
      echo "FAIL  could not list Audiobookshelf libraries (bad key, or none configured)"
      exit 1
    fi
    rc=0
    for id in $libs; do
      code="$(curl -s -o /dev/null -m 30 -w '%{http_code}' \
        -X POST "${ABS_URL}/api/libraries/${id}/scan" \
        -H "Authorization: Bearer ${ABS_API_KEY}" || echo 000)"
      case "$code" in
        200|202|204) echo "PASS  library ${id} scan started (HTTP $code)" ;;
        *)           echo "FAIL  library ${id} returned HTTP $code"; rc=1 ;;
      esac
    done
    exit "$rc"
    ;;
  *)
    echo "FAIL  unknown target '${target}' (expected: jellyfin | audiobookshelf)"
    exit 2
    ;;
esac
