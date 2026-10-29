#!/usr/bin/env bash
# RC1 finding S1: run the enrollment username policy (services/authentik/blueprints/avrana-enrollment.yaml) inside a
# REAL, throwaway Authentik, the same image digests as production (services/authentik/docker-compose.yml).
#
# CI only (.github/workflows/enrollment-policy.yml); never against production. Everything runs on one Docker network
# created with --internal: no container can reach the internet or the LAN, so the email stage's SMTP host and every
# other real address are unreachable by construction. A stub Jellyfin answers at 10.0.0.218:8096, the address the
# policy calls. Every credential here is random and generated for this run. The checks themselves:
# tests/authentik_enrollment_live.py.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
compose="$here/services/authentik/docker-compose.yml"
pg_image=$(grep -m1 -o 'docker.io/library/postgres@sha256:[0-9a-f]\{64\}' "$compose")
ak_image=$(grep -m1 -o 'ghcr.io/goauthentik/server@sha256:[0-9a-f]\{64\}' "$compose")
net=avrana-enrollment-ci
rand() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
pg_pass=$(rand)
secret_key=$(rand)
token=$(rand)
admin_pass=$(rand)
jf_key=$(rand)

cleanup() {
  if [ "${1:-0}" != 0 ]; then
    for c in ak-server ak-worker; do
      echo "--- last log lines of $c"
      docker logs --tail 60 "$c" 2>&1 | grep -v -i -e password -e token -e secret || true
    done
  fi
  docker rm -f ak-server ak-worker ak-db stub-jellyfin >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
}
trap 'cleanup $?' EXIT

docker pull -q "$pg_image" >/dev/null
docker pull -q "$ak_image" >/dev/null
docker network create --internal --subnet 10.0.0.0/24 "$net" >/dev/null

docker run -d --name ak-db --network "$net" --ip 10.0.0.10 \
  -e POSTGRES_USER=authentik -e POSTGRES_DB=authentik -e POSTGRES_PASSWORD="$pg_pass" "$pg_image" >/dev/null

ak_env=(
  -e AUTHENTIK_POSTGRESQL__HOST=10.0.0.10 -e AUTHENTIK_POSTGRESQL__NAME=authentik
  -e AUTHENTIK_POSTGRESQL__USER=authentik -e AUTHENTIK_POSTGRESQL__PASSWORD="$pg_pass"
  -e AUTHENTIK_SECRET_KEY="$secret_key" -e AUTHENTIK_BOOTSTRAP_TOKEN="$token"
  -e AUTHENTIK_BOOTSTRAP_PASSWORD="$admin_pass" -e AUTHENTIK_BOOTSTRAP_EMAIL=akadmin@example.test
  -e AUTHENTIK_DISABLE_UPDATE_CHECK=true -e AUTHENTIK_ERROR_REPORTING__ENABLED=false
  -e AVRANA_JELLYFIN_API_KEY="$jf_key" -e AVRANA_SMTP2GO_PASSWORD="$(rand)"
  -e AVRANA_KOMGA_ADMIN_EMAIL=komga@example.test -e AVRANA_KOMGA_ADMIN_PASSWORD="$(rand)"
)
blueprint="$here/services/authentik/blueprints/avrana-enrollment.yaml:/blueprints/avrana/avrana-enrollment.yaml:ro"

docker run -d --name stub-jellyfin --network "$net" --ip 10.0.0.218 -e JF_KEY="$jf_key" \
  -e JF_USERS=member-a,Orphan -v "$here/tests:/t:ro" --entrypoint python "$ak_image" \
  /t/authentik_enrollment_live.py stub >/dev/null
docker run -d --name ak-server --network "$net" --ip 10.0.0.11 "${ak_env[@]}" -v "$blueprint" "$ak_image" server >/dev/null
docker run -d --name ak-worker --network "$net" --ip 10.0.0.12 "${ak_env[@]}" -v "$blueprint" "$ak_image" worker >/dev/null

drive() {
  docker run --rm --network "$net" --ip 10.0.0.20 -e AK_URL=http://10.0.0.11:9000 -e AK_TOKEN="$token" \
    -v "$here/tests:/t:ro" --entrypoint python "$ak_image" /t/authentik_enrollment_live.py "$@"
}

drive checks
docker stop stub-jellyfin >/dev/null
drive jellyfin-down
echo "enrollment policy verified against a real Authentik ($ak_image)"
