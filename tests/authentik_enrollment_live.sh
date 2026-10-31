#!/usr/bin/env bash
# RC1 finding S1: run the enrollment username policy (services/authentik/blueprints/avrana-enrollment.yaml) inside a
# REAL, throwaway Authentik, the same image digests as production (services/authentik/docker-compose.yml).
#
# CI only (.github/workflows/enrollment-policy.yml); never against production. Everything runs on one Docker network
# created with --internal: no container can reach the internet or the LAN, so the email stage's SMTP host and every
# other real address are unreachable by construction. Stub Jellyfin and Komga answer at 10.0.0.218:8096 and :25600, the
# addresses the policies call. Every credential here is random and generated for this run. The checks themselves:
# tests/authentik_enrollment_live.py.
#
# AVR-791: the two admin keys are sentinels. The server reads them from a directory mounted like production's
# (services/authentik/docker-compose.yml). The worker holds them in its environment ON PURPOSE, as a tripwire: it is
# what renders !Env, so an expression that goes back to !Env puts a sentinel in the policy row and fails here, where
# with the variable unset it would quietly render "None". Whether a sentinel reached Postgres or a log is a count.
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
komga_key=$(rand)
# World-readable here only: a throwaway directory on a CI runner, whose user is not the container's uid 1000.
keys=$(mktemp -d)
chmod 755 "$keys"
put_key() { printf '%s\n' "$2" >"$keys/.new"; chmod 644 "$keys/.new"; mv "$keys/.new" "$keys/$1"; }
put_key jellyfin_enrollment_key "$jf_key"
put_key komga_enrollment_key "$komga_key"

cleanup() {
  if [ "${1:-0}" != 0 ]; then
    for c in ak-server ak-worker; do
      echo "--- last log lines of $c"
      docker logs --tail 60 "$c" 2>&1 | grep -v -i -e password -e token -e secret || true
    done
  fi
  docker rm -f ak-server ak-worker ak-db stub-jellyfin >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -rf "$keys"
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
  -e AVRANA_SMTP2GO_PASSWORD="$(rand)"
)
tripwire=(-e AVRANA_JELLYFIN_API_KEY="$jf_key" -e AVRANA_KOMGA_ADMIN_API_KEY="$komga_key")
blueprint="$here/services/authentik/blueprints/avrana-enrollment.yaml:/blueprints/avrana/avrana-enrollment.yaml:ro"

docker run -d --name stub-jellyfin --network "$net" --ip 10.0.0.218 -e JF_KEY="$jf_key" \
  -e KOMGA_KEY="$komga_key" -e JF_USERS=member-a,Orphan -v "$here/tests:/t:ro" --entrypoint python "$ak_image" \
  /t/authentik_enrollment_live.py stub >/dev/null
docker run -d --name ak-server --network "$net" --ip 10.0.0.11 "${ak_env[@]}" -v "$blueprint" \
  -v "$keys:/run/avrana-policy-secrets:ro" "$ak_image" server >/dev/null
docker run -d --name ak-worker --network "$net" --ip 10.0.0.12 "${ak_env[@]}" "${tripwire[@]}" -v "$blueprint" \
  "$ak_image" worker >/dev/null

drive() {
  docker run --rm --network "$net" --ip 10.0.0.20 -e AK_URL=http://10.0.0.11:9000 -e AK_TOKEN="$token" \
    -e SENTINELS="$jf_key,$komga_key" -v "$here/tests:/t:ro" --entrypoint python "$ak_image" /t/authentik_enrollment_live.py "$@"
}

# Counts only, so the output never holds a value. The dump and the logs have no reason to hold a sentinel; only the
# worker's environment does.
leaks=0
scan() {
  local dump server worker
  dump=$(docker exec ak-db pg_dump -U authentik authentik | grep -c -F -e "$jf_key" -e "$komga_key" || true)
  server=$(docker logs ak-server 2>&1 | grep -c -F -e "$jf_key" -e "$komga_key" || true)
  worker=$(docker logs ak-worker 2>&1 | grep -c -F -e "$jf_key" -e "$komga_key" || true)
  echo "sentinel lines, $1: database dump $dump, server log $server, worker log $worker"
  if [ "$dump" != 0 ] || [ "$server" != 0 ] || [ "$worker" != 0 ]; then leaks=1; fi
}
status=0
drive checks || status=1
scan "after apply"
# The check the rotation runbook gives the owner: length and counts per expression, never the text.
bash "$here/scripts/authentik-policy-literal-check.sh" ak-db || leaks=1
if [ "$status" != 0 ] || [ "$leaks" != 0 ]; then exit 1; fi

drive provision
scan "after a real enrollment"

# Swapped by rename in the mounted directory, with no restart: what the rotation runbook does.
put_key komga_enrollment_key "$(rand)"
drive refused wrong-komga-key
put_key komga_enrollment_key "$komga_key"
rm "$keys/jellyfin_enrollment_key"
drive refused no-jellyfin-file
put_key jellyfin_enrollment_key "$jf_key"
rm "$keys/komga_enrollment_key"
drive refused no-komga-file
put_key komga_enrollment_key ""
drive refused empty-komga-file
put_key komga_enrollment_key "$komga_key"

docker stop stub-jellyfin >/dev/null
drive jellyfin-down
docker start stub-jellyfin >/dev/null

rm "$keys/jellyfin_enrollment_key" "$keys/komga_enrollment_key"
drive gap
scan "at the end"
if [ "$leaks" != 0 ]; then exit 1; fi
echo "enrollment policy verified against a real Authentik ($ak_image)"
