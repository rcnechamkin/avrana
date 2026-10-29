#!/usr/bin/env bash
# Deploy Avrana Media Home (the live-data beta, media-beta.avrana.net) from a Git ref, the same way every time.
#
#   scripts/deploy-home-beta.sh                 # dry run of origin/main: export, build, `up -d --dry-run`
#   scripts/deploy-home-beta.sh --apply         # the same, then recreate Home and check it
#   scripts/deploy-home-beta.sh --apply <ref>   # another commit or branch (fetched from origin first)
#
# Run from a checkout of this repository on a machine that can `ssh avrana`. Production approval rules
# (AGENTS.md) still apply: --apply recreates the avrana-home-beta container, so the owner says yes first.
#
# What it does, on avrana:
#   1. Exports services/avrana-home and services/avrana-portal at the ref to ~/avrana-deploy/home-<sha>/ (kept
#      across reboots, unlike /tmp; older exports are listed, never deleted).
#   2. Links the live configuration in: beta-live.env, secrets/ and state/ (members' Komga keys, Home's only
#      writable folder) from ~/avrana/services/avrana-home, and COPIES ~/avrana's docker-compose.beta-live.yml.
#      ~/avrana's compose file is the source of truth for what is switched on; the repo's copy keeps optional
#      features commented. If the repo's file has active lines ~/avrana's lacks, they are shown and the deploy
#      stops: that is a new setting for the owner to adopt first.
#   3. `config -q`, `build`, `up -d --dry-run` (must recreate only avrana-home-beta).
#   4. --apply: tags the running image avrana-home-live:pre-<sha> for rollback, `up -d`, waits for healthy,
#      shows errors from the new logs and which optional features are on (never a value).
# Rollback: printed at the end (re-run `up -d` from the previous export after re-tagging the rollback image).
set -euo pipefail

HOST=${AVRANA_HOST:-avrana}
LIVE=/home/cody/avrana/services/avrana-home
ROOT=/home/cody/avrana-deploy
PROJECT=avrana-home-beta
COMPOSE=docker-compose.beta-live.yml

apply=no
ref=origin/main
for arg in "$@"; do
  case "$arg" in
    --apply) apply=yes ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) ref=$arg ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"
git fetch -q origin
sha=$(git rev-parse --short=7 "$ref^{commit}")
dir=$ROOT/home-$sha
echo "== Home beta deploy: $ref = $sha$([ "$apply" = yes ] && echo " (apply)" || echo " (dry run)")"

# The repo's compose file must not switch on anything ~/avrana's does not have (active lines only).
# Inline lists ("secrets: [a, b]") are split into one "secrets: a" line per item, so a list that grew on
# ~/avrana does not count as new.
active() {
  sed 's/\r$//; /^[[:space:]]*#/d; s/[[:space:]]#.*$//; s/[[:space:]]*$//; /^$/d' |
    awk '/: *\[.*\]$/ { i = index($0, "["); key = substr($0, 1, i - 1); body = substr($0, i + 1); sub(/\]$/, "", body);
                       n = split(body, items, ","); for (j = 1; j <= n; j++) { gsub(/^ +| +$/, "", items[j]); print key items[j] }
                       next }
         { print }' | sort -u
}
repo_lines=$(git show "$sha:services/avrana-home/$COMPOSE" | active)
live_lines=$(ssh "$HOST" "cat $LIVE/$COMPOSE" | active)
new=$(comm -23 <(echo "$repo_lines") <(echo "$live_lines") || true)
if [ -n "$new" ]; then
  echo "!! The repo's $COMPOSE has active lines that ~/avrana's lacks. Adopt them there first (owner):" >&2
  echo "$new" >&2
  exit 3
fi

echo "== 1. export to $HOST:$dir"
git archive "$sha" services/avrana-home services/avrana-portal |
  ssh "$HOST" "set -e; if [ -e '$dir' ]; then echo 'export exists, reusing'; cat >/dev/null; exit 0; fi
               mkdir -p '$dir.tmp' && tar -x -C '$dir.tmp' && mv '$dir.tmp' '$dir'"

echo "== 2-4. link configuration, build, dry run$([ "$apply" = yes ] && echo ", apply")"
ssh "$HOST" APPLY="$apply" SHA="$sha" DIR="$dir" LIVE="$LIVE" ROOT="$ROOT" PROJECT="$PROJECT" COMPOSE="$COMPOSE" bash -s <<'REMOTE'
set -euo pipefail
cd "$DIR/services/avrana-home"
for f in beta-live.env secrets state; do
  [ -e "$LIVE/$f" ] || { echo "!! $LIVE/$f is missing" >&2; exit 4; }
  [ -L "$f" ] || ln -s "$LIVE/$f" "$f"
done
# RC1 S1: with HOME_IDENTITY_BINDINGS_FILE on, Home refuses every member until the owner has initialised the file
# from Authentik. Never build or start it without one (docs/runbooks/identity-bindings.md section 1).
if grep -qE '^[[:space:]]*- HOME_IDENTITY_BINDINGS_FILE=' "$LIVE/$COMPOSE" && [ ! -s "$LIVE/state/identity_bindings.json" ]; then
  echo "!! identity bindings are on but state/identity_bindings.json is missing: initialise it first" >&2; exit 7
fi
cp "$LIVE/$COMPOSE" "$COMPOSE"
dc() { docker compose -p "$PROJECT" -f "$COMPOSE" "$@"; }
dc config -q && echo "config ok"
dc build -q
plan=$(dc up -d --dry-run 2>&1)
echo "$plan" | tail -4
if echo "$plan" | grep -E "Network|Volume" | grep -qiE "creat|remov"; then
  echo "!! the dry run would create or remove a network or volume: stopping" >&2; exit 5
fi
echo "older exports (not deleted):"; ls -1d "$ROOT"/home-* 2>/dev/null | grep -v "home-$SHA$" | tail -5 || true
[ "$APPLY" = yes ] || { echo "== dry run only. Re-run with --apply to recreate Home."; exit 0; }

prev_image=$(docker inspect -f '{{.Image}}' avrana-home-beta)
prev_dir=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' avrana-home-beta)
docker tag "$prev_image" "avrana-home-live:pre-$SHA"
dc up -d
state=starting
for _ in $(seq 1 24); do
  state=$(docker inspect -f '{{.State.Health.Status}}' avrana-home-beta)
  [ "$state" = healthy ] && break
  sleep 5
done
echo "health: $state"
docker logs --since 3m avrana-home-beta 2>&1 | grep -iE 'traceback|error|refus' | head -5 || true
docker exec -i avrana-home-beta python - <<'PY' || true
import os
from avrana_home.app.settings import Settings
s = Settings.from_env(os.environ)
print("provisioning:", ",".join(s.provision_accounts) or "off",
      "| Komga member keys:", len(s.komga_member_keys), "| Komga admin key:", "yes" if s.komga_admin_token else "no")
PY
echo "rollback: docker tag avrana-home-live:pre-$SHA avrana-home-live:local &&"
echo "          cd $prev_dir && docker compose -p $PROJECT -f $COMPOSE up -d --no-build"
[ "$state" = healthy ] || { echo "!! not healthy: consider the rollback above" >&2; exit 6; }
REMOTE
