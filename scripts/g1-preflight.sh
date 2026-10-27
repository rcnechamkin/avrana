#!/usr/bin/env bash
# G1 preflight (AVR-356): READ-ONLY checks the owner runs on the host before approving the G1 window.
#
# Usage: scripts/g1-preflight.sh [--rollback DIR] [--e1]
#   --rollback DIR  verify staged rollback material: DIR/SHA256SUMS covering the four production compose
#                   files and services-health.sh (docs/runbooks/g1-network-isolation.md, Preconditions 3)
#   --e1            also run check E1: unauthenticated requests with forged identity headers to the public
#                   hostnames and to the LAN outpost port. No credential is sent. E1 is NOT evidence that
#                   the outpost overwrites headers (that is E2, after apply, by the owner).
#
# It changes nothing: docker is only asked to list and inspect, files are only read, and the only network
# traffic is --e1. It never starts a container, never touches compose, networks, systemd or the health timer.
# tests/test_g1_preflight.py enforces that and runs this script against stubs.
#
# Output: one line per check: PASS, INFO, STOP (a precondition failed: do not apply) or VOID (the check could
# not run: its result means nothing). Exit 0 only when there is no STOP and no VOID.
set -u

backups="${AVRANA_BACKUPS_DIR:-/mnt/avrana_media/.backups}"
daemon_json="${AVRANA_DOCKER_DAEMON_JSON:-/etc/docker/daemon.json}"
ip_bin="${AVRANA_IP:-ip}"
py="${AVRANA_PYTHON:-python3}"
curl_bin="${AVRANA_CURL:-curl}"
rollback=""
run_e1=0
while [ $# -gt 0 ]; do
  case "$1" in
    --rollback) rollback="${2:-}"; shift 2 || { echo "usage: $0 [--rollback DIR] [--e1]" >&2; exit 2; } ;;
    --e1) run_e1=1; shift ;;
    *) echo "usage: $0 [--rollback DIR] [--e1]" >&2; exit 2 ;;
  esac
done

stops=0
voids=0
say() {
  level="$1"; shift
  printf '%-5s %s\n' "$level" "$*"
  case "$level" in STOP) stops=$((stops + 1)) ;; VOID) voids=$((voids + 1)) ;; esac
}

BACKENDS="avrana-portal avrana-kindle-connector olivetin"
PRIVATE="authentik_portal authentik_kindle authentik_olivetin"

# --- 0. tools --------------------------------------------------------------------------------------
for tool in docker "$py" "$ip_bin" awk sha256sum grep sed sort cut; do
  command -v "$tool" >/dev/null 2>&1 || say VOID "tool missing: $tool"
done
if [ "$voids" -gt 0 ]; then
  echo "PREFLIGHT: $stops STOP, $voids VOID (tools missing; nothing checked)"
  exit 1
fi
server=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || server=""
if [ -z "$server" ]; then
  say VOID "docker daemon not readable (permission or daemon down)"
else
  say INFO "docker server $server on $(hostname 2>/dev/null || echo unknown) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

# --- 1. subnets for the three private networks (runbook: Address room) ----------------------------
# The private networks carry explicit subnets (services/authentik/docker-compose.yml), so Docker's default
# address pools are not asked for room (the host held 30 networks on 2026-10-27, near the 32 the August
# incident hit). What matters is that each subnet overlaps no existing Docker network and no host route.
# tests/test_network_isolation.py keeps this list equal to the compose file.
G1_SUBNETS="10.220.29.0/24 10.220.30.0/24 10.220.31.0/24"
net_ids=$(docker network ls -q 2>/dev/null) || net_ids=""
routes=$("$ip_bin" -4 route show 2>/dev/null) || routes=""
if [ -z "$net_ids" ]; then
  say VOID "subnets: docker network ls returned nothing"
else
  subnets=$(docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}' $net_ids 2>/dev/null) || subnets=""
  if [ -z "$subnets" ]; then
    say VOID "subnets: docker network inspect returned nothing"
  elif [ -z "$routes" ]; then
    say VOID "subnets: '$ip_bin -4 route show' returned nothing; host routes unchecked"
  else
    printf '%s\n' "$subnets" | sort | sed 's/^/INFO  subnet: /'
    say INFO "address pools: $(printf '%s\n' "$net_ids" | grep -c .) networks; not used by G1 (explicit subnets)"
    # One line per clash: "<want> <owner>", where owner is a Docker network name or "route:<prefix>".
    clashes=$(G1_WANT="$G1_SUBNETS" G1_NETS="$subnets" G1_ROUTES="$routes" "$py" -c '
import ipaddress, os
want = [ipaddress.ip_network(w) for w in os.environ["G1_WANT"].split()]
have = []
for line in os.environ["G1_NETS"].splitlines():
    name, *cidrs = line.split()
    have += [(c, name) for c in cidrs if ":" not in c]
for line in os.environ["G1_ROUTES"].splitlines():
    first = line.split()[0] if line.split() else ""
    if first and first != "default" and first[0].isdigit():
        have.append((first if "/" in first else first + "/32", "route:" + first))
for w in want:
    for cidr, owner in have:
        if w.overlaps(ipaddress.ip_network(cidr, strict=False)):
            print(w, owner)
') || clashes="(error)"
    if [ "$clashes" = "(error)" ]; then
      say VOID "subnets: overlap check could not run"
    elif [ -n "$clashes" ]; then
      # A clash with one of G1's own networks means it already exists; check 2 reports that.
      printf '%s\n' "$clashes" | while read -r want owner; do
        say STOP "subnets: $want overlaps $owner; pick another free 10.220.x.0/24 in the compose file"
      done
      stops=$((stops + $(printf '%s\n' "$clashes" | grep -c .)))
    else
      say PASS "subnets: $G1_SUBNETS overlap no Docker network and no host route"
    fi
  fi
fi
if [ -r "$daemon_json" ]; then
  keys=$("$py" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert isinstance(d, dict); print(" ".join(sorted(d)))' "$daemon_json" 2>/dev/null) || keys="(unparseable)"
  say INFO "daemon.json keys: ${keys:-none} (do not edit)"
fi

# --- 2. current G1 state --------------------------------------------------------------------------
present=""
unknown=""
for n in $PRIVATE; do
  if err=$(docker network inspect "$n" 2>&1 >/dev/null); then
    present="$present $n"
  else
    case "$err" in
      *"No such network"*|*"network $n not found"*) ;;
      *) unknown="$unknown $n" ;;
    esac
  fi
done
if [ -n "$unknown" ]; then
  say VOID "g1 state: docker could not say whether these exist:$unknown"
elif [ -z "$present" ]; then
  say PASS "g1 state: not applied (none of the private networks exists), as expected before the window"
else
  say STOP "g1 state: private network(s) already exist:$present; find out why before applying"
fi
frontend=$(docker network inspect authentik_frontend --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null) || frontend=""
if [ -z "$frontend" ]; then
  say VOID "authentik_frontend: not inspectable"
else
  say INFO "authentik_frontend members: $frontend"
fi

# --- 3. namespace sharing (runbook: Verify; review finding F1) --------------------------------------
ids=$(docker ps -aq 2>/dev/null) || ids=""
modes=""
if [ -n "$ids" ]; then
  # Any failure (one container vanished, one bad id) discards the partial output: the container that was
  # not inspected could be the borrower.
  modes=$(docker inspect --format '{{.Name}} net={{.HostConfig.NetworkMode}} pid={{.HostConfig.PidMode}} ipc={{.HostConfig.IpcMode}}' $ids 2>/dev/null) || modes=""
fi
id_count=$(printf '%s\n' "$ids" | grep -c .)
inspected=$(printf '%s\n' "$modes" | grep -c .)
if [ -z "$ids" ] || [ -z "$modes" ]; then
  say VOID "namespace sharing: docker ps or inspect failed or returned nothing"
elif [ "$inspected" -ne "$id_count" ]; then
  say VOID "namespace sharing: inspected $inspected of $id_count containers"
else
  net_share=$(printf '%s\n' "$modes" | grep -E ' net=container:' || true)
  other_share=$(printf '%s\n' "$modes" | grep -E ' (pid|ipc)=container:' || true)
  if [ -n "$net_share" ]; then
    say STOP "namespace sharing: a container borrows another's network namespace ($inspected inspected):"
    printf '%s\n' "$net_share" | sed 's/^/STOP    /'
  else
    say PASS "namespace sharing: no net=container: among $inspected containers"
  fi
  [ -n "$other_share" ] && printf '%s\n' "$other_share" | sed 's/^/INFO  pid\/ipc sharing (report, not a network bypass): /'
  host_net=$(printf '%s\n' "$modes" | grep -E ' net=host ' | cut -d' ' -f1 | tr '\n' ' ')
  [ -n "$host_net" ] && say INFO "host-network containers (D-3 residual): $host_net"
fi

# --- 4. containers involved -----------------------------------------------------------------------
for c in authentik-server $BACKENDS; do
  line=$(docker inspect "$c" --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.StartedAt}} nets={{range $k, $v := .NetworkSettings.Networks}}{{$k}},{{end}}' 2>/dev/null) || line=""
  if [ -z "$line" ]; then
    say STOP "$c: not found"
    continue
  fi
  started=""
  read -r st health started _ <<<"$line"
  if [ -z "$started" ]; then
    say VOID "$c: inspect output not understood"
  elif [ "$st" != running ] || [ "$health" != healthy ]; then
    say STOP "$c: $st/$health (must be running and healthy before the window)"
  else
    say PASS "$c: running/healthy since $started"
  fi
done

# --- 5. backups (runbook: Preconditions 4) ---------------------------------------------------------
freshness() {  # freshness FILE MAX_HOURS LABEL
  out=$("$py" - "$1" "$2" <<'PY' 2>/dev/null
import json, sys, time, pathlib
p, limit = pathlib.Path(sys.argv[1]), float(sys.argv[2])
if not p.is_file():
    print("STOP missing"); raise SystemExit
try:
    d = json.loads(p.read_text())
except ValueError:
    print("STOP unparseable"); raise SystemExit
age = (time.time() - p.stat().st_mtime) / 3600
status = d.get("status") if isinstance(d, dict) else None
if age < -0.1:
    print("STOP modified in the future (clock problem)")
elif status != "ok":
    print(f"STOP status={status!r}")
elif age > limit:
    print(f"STOP stale {age:.0f}h > {limit:.0f}h")
else:
    print(f"PASS ok, {age:.0f}h old")
PY
) || out=""
  [ -n "$out" ] || out="VOID could not read"
  say "${out%% *}" "$3: ${out#* }"
}
freshness "$backups/avrana/LAST_RUN.json" 26 "local backup"
freshness "$backups/OFFHOST_LAST_RUN.json" 50 "off-host backup"

# --- 6. rollback material (runbook: Preconditions 3) -----------------------------------------------
if [ -z "$rollback" ]; then
  say STOP "rollback material: not checked (run with --rollback \$B/rollback once it is staged)"
elif [ ! -f "$rollback/SHA256SUMS" ]; then
  say STOP "rollback material: $rollback/SHA256SUMS missing"
else
  # Each file is checked by its own name: exactly one well-formed line, and the hash that line names.
  missing=""
  bad=""
  for f in authentik/docker-compose.yml avrana-portal/docker-compose.yml avrana-kindle-connector/docker-compose.yml \
           olivetin/docker-compose.yml services-health.sh; do
    if [ ! -s "$rollback/$f" ]; then missing="$missing $f"; continue; fi
    want=$(awk -v f="$f" '$2 == f || $2 == "*" f { print $1 }' "$rollback/SHA256SUMS")
    case "$want" in
      ""|*[!0-9a-f]*) missing="$missing $f(no-valid-sum)"; continue ;;
    esac
    if [ "${#want}" -ne 64 ]; then missing="$missing $f(no-valid-sum)"; continue; fi
    got=$(sha256sum "$rollback/$f" 2>/dev/null | cut -d' ' -f1)
    [ "$got" = "$want" ] || bad="$bad $f"
  done
  if [ -n "$missing" ]; then
    say STOP "rollback material: missing or without exactly one valid sum:$missing"
  elif [ -n "$bad" ]; then
    say STOP "rollback material: SHA-256 mismatch:$bad"
  else
    say PASS "rollback material: 5 files present and match the SHA256SUMS staged with them"
  fi
fi

# --- 7. check E1 (optional) ------------------------------------------------------------------------
if [ "$run_e1" = 1 ]; then
  if ! command -v "$curl_bin" >/dev/null 2>&1; then
    say VOID "E1: curl missing"
  else
    for u in avrana.net kindle.avrana.net ops.avrana.net; do
      for target in "https://$u/ops" "lan:http://10.0.0.218:9000/ops"; do
        url=${target#lan:}
        hostarg=""
        [ "$url" != "$target" ] && hostarg="Host: $u"
        r=$("$curl_bin" -s -o /dev/null -m 10 -w '%{http_code} %{redirect_url}' \
              -H 'X-authentik-username: forged' -H 'X-authentik-groups: authentik Admins' \
              -H 'X_authentik_groups: authentik Admins' ${hostarg:+-H "$hostarg"} "$url" 2>/dev/null) || r="000"
        case "$r" in
          "302 https://$u/outpost.goauthentik.io/start"*|"302 https://auth.avrana.net/"*) say PASS "E1 $u ${hostarg:+(LAN) }redirected to sign-in" ;;
          000*|"") say VOID "E1 $u ${hostarg:+(LAN) }no answer" ;;
          *) say STOP "E1 $u ${hostarg:+(LAN) }answered '$r' to an unauthenticated forged request" ;;
        esac
      done
    done
  fi
else
  say INFO "E1: skipped (add --e1)"
fi

# --- 8. manual items this script cannot check -----------------------------------------------------
say INFO "manual: Authentik admin UI shows no user or group attribute named additionalHeaders (finding F10)"
say INFO "manual: no other Authentik work in flight; window agreed; members told (runbook Preconditions 1, 5)"
say INFO "manual after apply: Verify section, checks A-C, E2 (only evidence for header overwrite), health script"

echo "PREFLIGHT: $stops STOP, $voids VOID"
[ "$stops" -eq 0 ] && [ "$voids" -eq 0 ]
