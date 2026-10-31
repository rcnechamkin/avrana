#!/usr/bin/env bash
# RC3 (AVR-789): prove the Audiobookshelf and Calibre-Web-Automated pins against REAL images, old version first.
#
# CI only (.github/workflows/rc3-upstream-proof.yml); never against production. Every service container sits on one
# Docker network created with --internal: no internet, no LAN. All data is synthetic and every credential is random,
# generated for this run. Each container gets the same hardening flags as its compose file, because a read-only root or
# dropped capabilities is exactly what an upgrade can break. The checks: tests/rc3_upstream_live.py.
#
#   abs   old 2.36.0 boots and is attacked (the control), new digest migrates its data and refuses, rollback works
#   cwa   the same for the Avrana image at v4.0.6 and at the compose pin
#   pins  every digest in the compose files carries the version label the docs claim
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
abs_compose="$here/services/audiobookshelf/docker-compose.yml"
ak_compose="$here/services/authentik/docker-compose.yml"
cwa_dir="$here/services/calibre-web-automated"

# The pins RC3 replaces, kept literal: this is the control, it must not follow the compose file.
abs_old=ghcr.io/advplyr/audiobookshelf@sha256:180acad33d69c99ed208676465d8edcb268fa46967735579a7810859885b1a8e
cwa_old_base=crocodilestick/calibre-web-automated:v4.0.6@sha256:c31a738b6d5ec6982c050063dd3f063b6943eb1051fc81144789f840d9093a8d
abs_new=$(grep -m1 -o 'ghcr.io/advplyr/audiobookshelf@sha256:[0-9a-f]\{64\}' "$abs_compose")
driver_image=docker.io/library/python@sha256:e5fa639e49b85986c4481e28faa2564b45aa8021413f31026c3856e5911618b1  # 3.13.9-alpine3.22
net=rc3-proof-ci
rand() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

filtered_logs() { docker logs --tail "${2:-80}" "$1" 2>&1 | grep -v -i -e password -e token -e secret -e cookie || true; }

cleanup() {
  code=${1:-0}
  if [ "$code" != 0 ]; then
    for c in abs cwa; do
      docker inspect "$c" >/dev/null 2>&1 && { echo "--- last log lines of $c"; filtered_logs "$c"; }
    done
  fi
  docker rm -f abs cwa >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  docker volume ls -q --filter name=rc3- | xargs -r docker volume rm >/dev/null 2>&1 || true
}

drive() {
  docker run --rm --network "$net" --user 0 -v rc3-state:/state -v "$here/tests:/t:ro" "${driver_env[@]}" \
    --entrypoint python "$driver_image" /t/rc3_upstream_live.py "$@"
}

copy_volume() {  # from to: a plain file copy, what the runbook's backup is
  docker run --rm --network none -v "$1:/from:ro" -v "$2:/to" --entrypoint sh "$driver_image" \
    -c 'rm -rf /to/* /to/.[!.]* 2>/dev/null; cp -a /from/. /to/'
}

abs_run() {
  docker rm -f abs >/dev/null 2>&1 || true
  docker run -d --name abs --network "$net" --network-alias abs --user 1000:1000 -e TZ=America/Los_Angeles \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m --cap-drop ALL --security-opt no-new-privileges:true \
    --pids-limit 256 -v rc3-abs-config:/config -v rc3-abs-metadata:/metadata -v rc3-abs-books:/audiobooks "$1" >/dev/null
}

run_abs() {
  local canary_a canary_b new_version
  canary_a=$(rand); canary_b=$(rand)
  docker pull -q "$abs_old" >/dev/null
  docker pull -q "$abs_new" >/dev/null
  docker pull -q "$driver_image" >/dev/null
  new_version=$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$abs_new")
  driver_env=(
    -e ABS_URL=http://abs:80 -e ABS_ROOT_PASSWORD="$(rand)" -e ABS_MEMBER_PASSWORD="$(rand)"
    -e ABS_CANARY_A="$canary_a" -e ABS_CANARY_B="$canary_b" -e ABS_NEW_VERSION="$new_version" -e ABS_OLD_VERSION=2.36.0
  )
  docker network create --internal "$net" >/dev/null

  # The fixture: one real audiobook made here, and the synthetic files the advisory needs. /metadata/synth_400.txt is
  # the 2.36.1 shape, the folder /metadata/synth_7.d the 2.36.0 *_N.* shape, /config/rc3-canary.txt the file outside it.
  docker run --rm --network none --user 0 -v rc3-abs-config:/config -v rc3-abs-metadata:/metadata \
    -v rc3-abs-books:/audiobooks -e CA="$canary_a" -e CB="$canary_b" --entrypoint sh "$abs_old" -c '
      set -e
      d="/audiobooks/Proof Author/Proof Title"; mkdir -p "$d" /metadata/synth_7.d
      ffmpeg -loglevel error -f lavfi -i sine=frequency=440:duration=5 -c:a aac "$d/proof.m4b"
      ffmpeg -loglevel error -f lavfi -i color=c=blue:s=300x300 -frames:v 1 "$d/cover.jpg"
      printf %s "$CA" > /metadata/synth_400.txt; printf %s "$CB" > /config/rc3-canary.txt
      chown -R 1000:1000 /config /metadata /audiobooks'

  abs_run "$abs_old"
  drive abs-seed
  drive abs-control
  docker stop abs >/dev/null
  for v in config metadata; do docker volume create "rc3-abs-$v-backup" >/dev/null; copy_volume "rc3-abs-$v" "rc3-abs-$v-backup"; done

  abs_run "$abs_new"
  drive abs-new
  docker logs abs 2>&1 | grep -iE 'migration|\[Database\]' | grep -v -i -e password -e token -e secret | tail -20 || true
  docker stop abs >/dev/null

  # Rollback one: the old image on the data the new version just used. There are no schema changes to undo.
  abs_run "$abs_old"
  drive abs-old-again
  docker stop abs >/dev/null
  # Rollback two: the runbook's restore, the old image on the pre-upgrade copy.
  for v in config metadata; do copy_volume "rc3-abs-$v-backup" "rc3-abs-$v"; done
  abs_run "$abs_old"
  drive abs-old-again
  echo "Audiobookshelf proof complete: old attacked, $abs_new refused, data migrated, both rollbacks work"
}

cwa_run() {
  docker rm -f cwa >/dev/null 2>&1 || true
  # Same capability list, tmpfs and limits as services/calibre-web-automated/docker-compose.yml.
  docker run -d --name cwa --network "$net" --network-alias cwa \
    --security-opt no-new-privileges:true --cap-drop AUDIT_WRITE --cap-drop FSETID --cap-drop KILL --cap-drop MKNOD \
    --cap-drop NET_BIND_SERVICE --cap-drop NET_RAW --cap-drop SETFCAP --cap-drop SETPCAP --cap-drop SYS_CHROOT \
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=2g --pids-limit 512 \
    -e PUID=1000 -e PGID=1000 -e TZ=America/Los_Angeles -e NETWORK_SHARE_MODE=false \
    -v rc3-cwa-config:/config -v rc3-cwa-ingest:/cwa-book-ingest -v rc3-cwa-library:/calibre-library "$1" >/dev/null
}

ingest() {  # title: drop a fresh EPUB into the inbox, as Shelfmark would
  docker run --rm --network none --user 0 -v rc3-cwa-ingest:/in -v "$here/tests:/t:ro" --entrypoint python "$driver_image" \
    /t/rc3_upstream_live.py make-epub "/in/$(echo "$1" | tr -d ' ').epub" "$1"
}

cwa_flag() {  # kobo on/off, written while the service is stopped: it is read once, when the blueprints register
  docker run --rm --network none --user 0 -v rc3-cwa-config:/config --entrypoint python "$driver_image" -c "
import sqlite3
con = sqlite3.connect('/config/app.db')
con.execute('update settings set config_kobo_sync = $1')
con.commit()
print('kobo sync flag was set to $1')"
}

run_cwa() {
  local canary
  canary=$(rand)
  docker pull -q "$driver_image" >/dev/null
  docker build -q --build-arg CWA_BASE_IMAGE="$cwa_old_base" -t rc3-cwa:old "$cwa_dir" >/dev/null
  docker build -q -t rc3-cwa:new "$cwa_dir" >/dev/null
  driver_env=(
    -e CWA_URL=http://cwa:8083 -e CWA_MEMBER_PASSWORD="$(rand)Aa1!" -e CWA_CANARY="$canary"
  )
  docker network create --internal "$net" >/dev/null

  # The Avrana patches inside the new image: the tests the patch README names, on a throwaway copy, so pytest (not in
  # the image) goes in before the image loses the network.
  docker run --rm --entrypoint sh -v "$cwa_dir/tests:/avrana-tests:ro" rc3-cwa:new -c '
    /lsiopy/bin/python3 -m pip install -q --disable-pip-version-check pytest >/dev/null
    cd /app/calibre-web-automated && /lsiopy/bin/python3 -m pytest -q /avrana-tests -p no:cacheprovider'

  ingest "RC3 Seed Book"
  cwa_run rc3-cwa:old
  drive cwa-seed
  docker stop cwa >/dev/null
  # The archived log is what the unauthenticated viewer serves.
  docker run --rm --network none --user 0 -v rc3-cwa-config:/config -e C="$canary" --entrypoint sh "$driver_image" -c '
    mkdir -p /config/log_archive; printf %s "$C" > /config/log_archive/rc3-canary.log
    printf %s "$C" > /config/rc3-canary.log; chown -R 1000:1000 /config/log_archive /config/rc3-canary.log'

  cwa_run rc3-cwa:old
  driver_env+=(-e CWA_KOBO_FLAG=default)
  sleep 5
  docker run --rm --network "$net" --entrypoint python -v rc3-state:/state -v "$here/tests:/t:ro" "${driver_env[@]}" \
    "$driver_image" -c "import sys; sys.path.insert(0, '/t'); import rc3_upstream_live as r; r.Http(r.os.environ['CWA_URL']).wait('/login', 300)"
  drive cwa-control
  docker stop cwa >/dev/null
  cwa_flag 1
  driver_env+=(-e CWA_KOBO_FLAG=on)
  cwa_run rc3-cwa:old
  docker run --rm --network "$net" --entrypoint python -v rc3-state:/state -v "$here/tests:/t:ro" "${driver_env[@]}" \
    "$driver_image" -c "import sys; sys.path.insert(0, '/t'); import rc3_upstream_live as r; r.Http(r.os.environ['CWA_URL']).wait('/login', 300)"
  drive cwa-control
  docker stop cwa >/dev/null

  for v in config library; do docker volume create "rc3-cwa-$v-backup" >/dev/null; copy_volume "rc3-cwa-$v" "rc3-cwa-$v-backup"; done

  ingest "RC3 Post-Upgrade Book"
  cwa_run rc3-cwa:new
  drive cwa-new
  docker stop cwa >/dev/null

  # The runbook's rollback: the pre-upgrade copy under the old image. New tables stay behind with the discarded data.
  for v in config library; do copy_volume "rc3-cwa-$v-backup" "rc3-cwa-$v"; done
  cwa_run rc3-cwa:old
  drive cwa-old-again
  echo "Calibre-Web-Automated proof complete: old attacked, new refused, data migrated, restore works"
}

run_pins() {
  local image want got
  while read -r image want; do
    docker pull -q "$image" >/dev/null
    got=$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$image")
    case "$got" in
      *"$want") echo "PASS  $image is $got" ;;
      *) echo "FAIL  $image is $got, expected $want"; return 1 ;;
    esac
  done <<EOF
$abs_new 2.37.2
$(grep -m1 -o 'ghcr.io/goauthentik/server@sha256:[0-9a-f]\{64\}' "$ak_compose") 2026.5.8
$(grep -m1 -o 'ghcr.io/goauthentik/ldap@sha256:[0-9a-f]\{64\}' "$ak_compose") 2026.5.8
$(grep -m1 -o 'ghcr.io/calibrain/shelfmark:1.3.6@sha256:[0-9a-f]\{64\}' "$here/services/shelfmark/docker-compose.yml") 1.3.6
EOF
  # CWA's OCI version label is the LinuxServer base, so its own label is the one to read.
  image=$(sed -n 's/^ARG CWA_BASE_IMAGE=//p' "$cwa_dir/Dockerfile")
  docker pull -q "$image" >/dev/null
  got=$(docker inspect -f '{{index .Config.Labels "build_version"}}' "$image")
  case "$got" in
    *v4.0.8*) echo "PASS  $image is $got" ;;
    *) echo "FAIL  $image is $got"; return 1 ;;
  esac
}

trap 'cleanup $?' EXIT
case "${1:-}" in
  abs) run_abs ;;
  cwa) run_cwa ;;
  pins) run_pins ;;
  *) echo "usage: $0 abs|cwa|pins" >&2; exit 2 ;;
esac
