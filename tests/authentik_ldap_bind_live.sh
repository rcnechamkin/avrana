#!/usr/bin/env bash
# AVR-790: run services/authentik/blueprints/avrana-ldap-bind.yaml inside a REAL, throwaway Authentik with the REAL LDAP
# outpost, the same image digests as production (services/authentik/docker-compose.yml).
#
# CI only (.github/workflows/ldap-bind-flow.yml); never against production. Everything runs on one Docker network created
# with --internal: no container can reach the internet or the LAN. Every credential is random and generated for this run,
# and the passkey is a synthetic row, seeded through the ORM. The checks themselves: tests/authentik_ldap_bind_live.py.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
compose="$here/services/authentik/docker-compose.yml"
pg_image=$(grep -m1 -o 'docker.io/library/postgres@sha256:[0-9a-f]\{64\}' "$compose")
ak_image=$(grep -m1 -o 'ghcr.io/goauthentik/server@sha256:[0-9a-f]\{64\}' "$compose")
ldap_image=$(grep -m1 -o 'ghcr.io/goauthentik/ldap@sha256:[0-9a-f]\{64\}' "$compose")
net=avrana-ldap-ci
work=$(mktemp -d)
chmod 777 "$work"
rand() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
pg_pass=$(rand)
secret_key=$(rand)
token=$(rand)
admin_pass=$(rand)

cleanup() {
  if [ "${1:-0}" != 0 ]; then
    for c in ak-server ak-worker ak-ldap; do
      echo "--- last log lines of $c"
      docker logs --tail 80 "$c" 2>&1 | grep -v -i -e password -e token -e secret || true
    done
  fi
  docker rm -f ak-server ak-worker ak-db ak-ldap >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap 'cleanup $?' EXIT

docker pull -q "$pg_image" >/dev/null
docker pull -q "$ak_image" >/dev/null
docker pull -q "$ldap_image" >/dev/null
docker network create --internal --subnet 10.0.0.0/24 "$net" >/dev/null

docker run -d --name ak-db --network "$net" --ip 10.0.0.10 \
  -e POSTGRES_USER=authentik -e POSTGRES_DB=authentik -e POSTGRES_PASSWORD="$pg_pass" "$pg_image" >/dev/null

ak_env=(
  -e AUTHENTIK_POSTGRESQL__HOST=10.0.0.10 -e AUTHENTIK_POSTGRESQL__NAME=authentik
  -e AUTHENTIK_POSTGRESQL__USER=authentik -e AUTHENTIK_POSTGRESQL__PASSWORD="$pg_pass"
  -e AUTHENTIK_SECRET_KEY="$secret_key" -e AUTHENTIK_BOOTSTRAP_TOKEN="$token"
  -e AUTHENTIK_BOOTSTRAP_PASSWORD="$admin_pass" -e AUTHENTIK_BOOTSTRAP_EMAIL=akadmin@example.test
  -e AUTHENTIK_DISABLE_UPDATE_CHECK=true -e AUTHENTIK_ERROR_REPORTING__ENABLED=false
)
mounts=()
for name in avrana-ldap-bind calibre-web-ldap avrana-session-tuning; do
  mounts+=(-v "$here/services/authentik/blueprints/$name.yaml:/blueprints/avrana/$name.yaml:ro")
done

docker run -d --name ak-server --network "$net" --ip 10.0.0.11 "${ak_env[@]}" "${mounts[@]}" "$ak_image" server >/dev/null
docker run -d --name ak-worker --network "$net" --ip 10.0.0.12 "${ak_env[@]}" "${mounts[@]}" "$ak_image" worker >/dev/null

drive() {
  docker run --rm --network "$net" --ip 10.0.0.20 -e AK_URL=http://10.0.0.11:9000 -e AK_TOKEN="$token" \
    -e LDAP_HOST=10.0.0.30 -e WORK=/work -v "$work:/work" -v "$here/tests:/t:ro" \
    --entrypoint python "$ak_image" /t/authentik_ldap_bind_live.py "$@"
}

start_outpost() {
  docker run -d --name ak-ldap --network "$net" --ip 10.0.0.30 -e AUTHENTIK_HOST=http://10.0.0.11:9000 \
    -e AUTHENTIK_INSECURE=true -e AUTHENTIK_TOKEN="$(cat "$work/outpost-token")" "$ldap_image" >/dev/null
}

drive setup

# A synthetic passkey for two members, and the directory-search permission production grants by hand (ak shell).
docker exec ak-worker ak shell -c '
import secrets
from authentik.core.models import Group, User
from authentik.rbac.models import Role
from authentik.stages.authenticator_webauthn.models import WebAuthnDevice
for name in ("holder", "holder-two"):
    WebAuthnDevice.objects.create(user=User.objects.get(username=name), name="ci synthetic key", rp_id="10.0.0.11",
                                  credential_id=secrets.token_urlsafe(32), public_key=secrets.token_urlsafe(64))
role, _ = Role.objects.get_or_create(name="ci-ldap-search")
role.assign_perms("authentik_providers_ldap.search_full_directory")
Group.objects.get(name="ldap-service").roles.add(role)
print("seeded", WebAuthnDevice.objects.count(), "synthetic passkeys")
' 2>&1 | grep '^seeded'

start_outpost
drive control

# The hypothesis, in the outpost's own words: this exact error, from the real solver, on the existing flow.
count=$(docker logs ak-ldap 2>&1 | grep -c 'no compatible authenticator class found' || true)
if [ "$count" -lt 1 ]; then
  echo "FAIL control: the outpost never logged the solver error"
  exit 1
fi
echo "PASS control: the outpost logged 'no compatible authenticator class found' ($count times)"

drive cutover-before-restart
docker restart ak-ldap >/dev/null
drive cutover-after-restart
drive matrix
drive browser
drive reputation
drive revocation

# After the cached binds above: how often the outpost's own recover() fired. Reported, not judged.
echo "MEASURE recover-in-bind-handler=$(docker logs ak-ldap 2>&1 | grep -c 'recover in bind request' || true)"
echo "MEASURE solver-error-total=$(docker logs ak-ldap 2>&1 | grep -c 'no compatible authenticator class found' || true)"
echo "LDAP bind flow verified against a real Authentik and outpost ($ak_image, $ldap_image)"
