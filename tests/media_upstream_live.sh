#!/usr/bin/env bash
# RC3 Gate C: Home's adapters against REAL, throwaway Jellyfin, Audiobookshelf and Komga, the same image digests as
# production (services/media, services/audiobookshelf, services/komga). The Python image is the one Home ships on.
#
# CI only (.github/workflows/upstream-contracts.yml); never against production. Everything runs on one Docker network
# created with --internal: no container can reach the internet or the LAN. Synthetic files only; every credential is
# random, generated inside tests/media_upstream_live.py for this run, and never printed.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
jf_image=$(grep -m1 -o 'jellyfin/jellyfin@sha256:[0-9a-f]\{64\}' "$here/services/media/docker-compose.yml")
abs_image=$(grep -m1 -o 'ghcr.io/advplyr/audiobookshelf@sha256:[0-9a-f]\{64\}' "$here/services/audiobookshelf/docker-compose.yml")
kg_image=$(grep -m1 -o 'gotson/komga@sha256:[0-9a-f]\{64\}' "$here/services/komga/docker-compose.yml")
py_image=$(grep -m1 -o 'python:3.12-slim@sha256:[0-9a-f]\{64\}' "$here/services/avrana-home/Dockerfile.live")
net=avrana-upstreams-ci
work=$(mktemp -d)

cleanup() {
  if [ "${1:-0}" != 0 ]; then
    for c in up-jellyfin up-abs up-komga; do
      echo "--- last log lines of $c"
      docker logs --tail 40 "$c" 2>&1 | grep -v -i -e password -e token -e secret -e api-key || true
    done
  fi
  docker rm -f up-jellyfin up-abs up-komga >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -rf "$work" 2>/dev/null || true
}
trap 'cleanup $?' EXIT

for image in "$jf_image" "$abs_image" "$kg_image" "$py_image"; do docker pull -q "$image" >/dev/null; done
docker network create --internal --subnet 10.0.1.0/24 "$net" >/dev/null

# A two-minute 64x64 test pattern, made with the ffmpeg inside the pinned Jellyfin image (no network needed).
docker run --rm --network none -v "$work:/out" --entrypoint /usr/lib/jellyfin-ffmpeg/ffmpeg "$jf_image" \
  -hide_banner -loglevel error -f lavfi -i testsrc=duration=120:size=64x64:rate=1 -pix_fmt yuv420p /out/sample.mp4
docker run --rm --network none -v "$work:/media" -v "$here:/repo:ro" "$py_image" \
  python -B /repo/tests/media_upstream_live.py fixtures /media

docker run -d --name up-jellyfin --network "$net" --ip 10.0.1.11 -v "$work/jf:/media:ro" "$jf_image" >/dev/null
docker run -d --name up-abs --network "$net" --ip 10.0.1.12 -v "$work/abs:/media:ro" "$abs_image" >/dev/null
docker run -d --name up-komga --network "$net" --ip 10.0.1.13 -v "$work/komga:/media:ro" "$kg_image" >/dev/null

docker run --rm --network "$net" --ip 10.0.1.20 -e PYTHONDONTWRITEBYTECODE=1 -v "$here:/repo:ro" "$py_image" \
  python -B /repo/tests/media_upstream_live.py all
echo "adapters verified against real upstreams: $jf_image $abs_image $kg_image"
