#!/usr/bin/env bash
# Non-destructive verification for the OliveTin console.
#
# Safe to run at any time: it never restarts a production service, never downloads, and never
# writes to a backup. The one container it touches it creates and removes itself.
set -uo pipefail
pass=0; fail=0
P() { echo "PASS  $*"; pass=$((pass+1)); }
F() { echo "FAIL  $*"; fail=$((fail+1)); }

echo "=== config validity ==="
python3 -c 'import yaml,sys; yaml.safe_load(open("config/config.yaml"))' 2>/dev/null \
  && P "config.yaml is valid YAML" || F "config.yaml is not valid YAML"
for s in scripts/*.sh; do
  bash -n "$s" 2>/dev/null && P "$s parses" || F "$s has a syntax error"
done

echo
echo "=== default-deny is configured ==="
for k in "view: false" "exec: false" "logs: false"; do
  grep -qF "$k" config/config.yaml && P "defaultPermissions has $k" || F "missing $k"
done
grep -q 'matchUsergroups' config/config.yaml && P "an ACL matches a usergroup" || F "no usergroup ACL"
acl_count=$(grep -c 'acls: \[avrana-admins\]' config/config.yaml)
act_count=$(grep -c '^  - id: ' config/config.yaml)
[ "$acl_count" -eq "$act_count" ] \
  && P "every action ($act_count) is ACL-gated" \
  || F "only $acl_count of $act_count actions are ACL-gated"

echo
echo "=== no host port is published ==="
if docker inspect olivetin --format '{{.HostConfig.PortBindings}}' 2>/dev/null | grep -q 'map\[\]'; then
  P "olivetin publishes no host port"
else
  F "olivetin publishes a host port"
fi
ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE ':1337$' \
  && F "something is listening on 1337" || P "nothing listens on 1337"

echo
echo "=== socket proxies deny the dangerous paths ==="
for probe in "/containers/create" "/exec/x/start" "/images/json" "/volumes"; do
  code=$(docker exec olivetin curl -s -o /dev/null -m 5 -w '%{http_code}' \
    -X POST "http://olivetin-docker-restart:2375${probe}" 2>/dev/null)
  [ "$code" = "403" ] && P "restart-proxy denies ${probe} (403)" || F "restart-proxy allowed ${probe} (${code})"
done
code=$(docker exec olivetin curl -s -o /dev/null -m 5 -w '%{http_code}' \
  -X POST "http://olivetin-docker-ro:2375/containers/jellyfin/restart" 2>/dev/null)
[ "$code" = "403" ] && P "ro-proxy denies POST restart (403)" || F "ro-proxy allowed a restart (${code})"

echo
echo "=== allowlist refuses everything it should ==="
for bad in "olivetin" "authentik-server" "bookstack-mariadb" "jellyfin; rm -rf /" "../../etc/passwd" ""; do
  out=$(docker exec olivetin /opt/avrana/scripts/restart-service.sh "$bad" 2>&1 || true)
  echo "$out" | grep -q '^FAIL' && P "refused: '${bad}'" || F "ACCEPTED a bad name: '${bad}'"
done

echo
echo "=== restart plumbing, on a disposable container ==="
docker rm -f olivetin-selftest >/dev/null 2>&1
if docker run -d --name olivetin-selftest --restart=no alpine:3 sleep 120 >/dev/null 2>&1; then
  before=$(docker inspect olivetin-selftest --format '{{.State.StartedAt}}')
  docker exec olivetin sh -c 'DOCKER_HOST=$DOCKER_HOST_RESTART docker restart olivetin-selftest' >/dev/null 2>&1
  after=$(docker inspect olivetin-selftest --format '{{.State.StartedAt}}')
  [ "$before" != "$after" ] && P "restart through the proxy works" || F "restart did not take effect"
  docker rm -f olivetin-selftest >/dev/null 2>&1
else
  F "could not create the disposable test container"
fi

echo
echo "=== no secrets leak into output or logs ==="
if [ -r .env ]; then
  jk=$(grep '^JELLYFIN_API_KEY=' .env | cut -d= -f2)
  if [ -n "$jk" ]; then
    docker exec olivetin /opt/avrana/scripts/avrana-health.sh 2>&1 | grep -qF "$jk" \
      && F "health output contains the Jellyfin key" || P "health output has no key material"
    docker logs olivetin 2>&1 | grep -qF "$jk" \
      && F "olivetin logs contain the Jellyfin key" || P "olivetin logs have no key material"
  fi
  git -C ../.. check-ignore -q services/olivetin/.env && P ".env is gitignored" || F ".env is NOT gitignored"
fi

echo
echo "=== ${pass} passed, ${fail} failed ==="
[ "$fail" -gt 0 ] && exit 1
exit 0
