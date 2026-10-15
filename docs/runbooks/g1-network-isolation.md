# G1: private network per Authentik-proxied backend

**Staged, not applied.** AVR-355 prepares this; AVR-356 is the owner applying it (decision D-2). Gate G1 in
[`design/MEDIA-2.0.md`](../design/MEDIA-2.0.md) section 4; forensic audit D4. Read
[`DEPLOYMENT.md`](../DEPLOYMENT.md) and [`OPERATIONS.md`](../OPERATIONS.md) first. Steps marked
**[CHANGES PRODUCTION]** need the owner's approval for this batch; everything else is read-only.

## What changes

`avrana-portal`, `avrana-kindle-connector` and `olivetin` trust `X-authentik-*` headers. Today they share
`authentik_frontend` with `authentik-worker` and `authentik-ldap`, so a sibling can send them forged
headers. After the change each sits on its own network with `authentik-server` (the embedded outpost) only:

| Network | Members (exactly) | Outpost `internal_host` | Port |
|---|---|---|---|
| `authentik_portal` | `authentik-server`, `avrana-portal` | `http://avrana-portal:8095` | 8095 |
| `authentik_kindle` | `authentik-server`, `avrana-kindle-connector` | `http://avrana-kindle-connector:8096` | 8096 |
| `authentik_olivetin` | `authentik-server`, `olivetin` | `http://olivetin:1337` | 1337 |

The `internal_host` values do not change; the names resolve through Docker DNS on the shared private
network. Files: `services/authentik`, `avrana-portal`, `avrana-kindle-connector`, `olivetin` compose files.
The networks are created by the `authentik` project (explicit `name:`), and are `external` for the apps.

## Limits of this change

It stops sibling **containers** on other bridge networks. It does **not** stop anything in the host network
namespace (Jellyfin, Home Assistant, Beszel agent), anything with host root, or anyone on the host:
the host routes to every bridge IP, and ufw is off. See "D-3" below.

## Preconditions

1. Window agreed (D-2): a quiet weekday evening. Effects: SSO sign-in and the three hostnames drop for
   about a minute while `authentik-server` is recreated (healthcheck `start_period` 90 s); each app is
   unreachable for a few seconds while recreated. Jellyfin, Audiobookshelf, Komga and the arr stack are not
   touched. Tell members beforehand if anyone is mid-enrolment.
2. The commit is merged or at least pushed. Export it: `git archive <sha> | tar -x -C <dir>`; `drift-check.py`
   runs from that export.
3. Rollback material staged, and the owner has seen it:
   `/mnt/avrana_media/.backups/batch<N>-<date>/rollback/` holding the four **production** compose files
   (`services/authentik`, `avrana-portal`, `avrana-kindle-connector`, `olivetin`) plus
   `scripts/services-health.sh`, each with its SHA-256 (`sha256sum`), and the state record below.
4. Last backup clean (`LAST_RUN.json` status ok, under 26 h) and off-host sync clean.
5. No other Authentik work in flight (worker blueprint runs, enrolments).
6. Address-pool headroom (below) shows room for three more bridge networks.

## Address-pool headroom (read-only, before anything)

Creating three bridges can fail on this host. `services/omnibus/docker-compose.yml` (comment above its
`networks:` block) records that the host reached Docker's default address-pool limit (32 networks, `daemon.json`
sets only `data-root`) and that a further subnet failed with "all predefined address pools have been fully
subnetted". The August address-pool work caused a day of outages
([incident 2026-08-29](../incidents/2026-08-29-docker-address-pools.md)): **do not touch `daemon.json` or
the pools, and do not prune networks, to make room.**

```sh
docker network ls | tail -n +2 | wc -l                                   # current count
docker network inspect $(docker network ls -q) --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}' | sort > $B/subnets-before.txt
docker info 2>/dev/null | grep -i -A4 'address pool'                      # pools, if this Docker prints them
cat /etc/docker/daemon.json                                               # expect data-root only
```
Stop if the count plus 3 exceeds what the pools allow (the omnibus comment says 32). If it does not fit,
the change cannot be applied as written; the owner decides between giving the three networks explicit
`ipam` subnets from a free range (BOOTSTRAP uses `10.220.25.0/24` for `avrana-ldap`; the incident moved
`avrana-imax-verify_default` to `10.220.28.0/24`; pick only subnets absent from `subnets-before.txt`) and
freeing networks that nothing uses, each its own approved change. The dry run below does not prove the
allocator will succeed; the real `up` is where "fully subnetted" appears. Compose creates networks before
it recreates the container, so the server should be left running if it fails (check that
`docker inspect authentik-server --format '{{.State.StartedAt}}'` is unchanged) - expected, not verified.

## Health timer during the window

`scripts/services-health.sh` runs from the user timer `services-health.timer` (every 15 minutes,
`deploy/systemd/services-health.timer`, service `services-health.service`, user units per
`deploy/systemd/README.md`). A half-applied state would FAIL it and, after two consecutive failures, send
alert mail. Stop it for the window and run the script by hand without alerts:

- **[CHANGES PRODUCTION]** `systemctl --user stop services-health.timer` before step 0.
- Manual runs: `AVRANA_HEALTH_NO_ALERT=1 scripts/services-health.sh`.
- **[CHANGES PRODUCTION]** `systemctl --user start services-health.timer` after sign-off or after rollback;
  confirm with `systemctl --user list-timers services-health.timer`.

## Record the state first (read-only)

```sh
cd /home/cody/avrana
B=/mnt/avrana_media/.backups/batch<N>-<date>
docker ps --format '{{.Names}}\t{{.Status}}' | sort                      > $B/ps-before.txt
for n in authentik_frontend authentik_backend authentik_portal authentik_kindle authentik_olivetin; do
  echo "== $n"; docker network inspect "$n" --format '{{.Name}} {{.Id}}{{range .Containers}} {{.Name}}={{.IPv4Address}}{{end}}' 2>&1
done                                                                      > $B/networks-before.txt
for c in authentik-server avrana-portal avrana-kindle-connector olivetin; do
  docker inspect "$c" --format '{{.Name}} nets={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}} health={{.State.Health.Status}} started={{.State.StartedAt}}'
done                                                                      > $B/containers-before.txt
python3 scripts/drift-check.py --quiet                                    > $B/drift-before.txt
AVRANA_HEALTH_NO_ALERT=1 scripts/services-health.sh                       > $B/health-before.txt
for u in avrana.net kindle.avrana.net ops.avrana.net; do curl -s -o /dev/null -m 10 -w "$u %{http_code}\n" https://$u/; done  # expect 302 to auth.avrana.net
```

Expected before: `authentik_frontend` lists the three apps plus `authentik-server`, `authentik-worker` and
`authentik-ldap` (any order); the three private networks do not exist.

## Dry run (read-only)

```sh
cd /home/cody/avrana/services/authentik && docker compose config -q && docker compose up -d --dry-run --no-deps server
```
Expect: `server` recreated, three networks created, nothing else touched. Anything else (worker, ldap,
postgresql recreated): stop and report. The app stacks cannot be dry-run until the networks exist
(`external` network not found); do them after step 2 below and before step 3, one at a time:
`cd services/<app> && docker compose config -q && docker compose up -d --dry-run` expects that one app
recreated (olivetin: not `olivetin-docker-ro` / `-restart`). Compose v2 only; `up -d` recreates anything that
differs from the file, which is why the dry run comes first.

## Apply

Keep a note of how far you got; rollback branches on it.

0. **[CHANGES PRODUCTION]** Deploy `scripts/check-network-isolation.py` (mode 755) and the new
   `scripts/services-health.sh` (755); save the old one first. Run `AVRANA_HEALTH_NO_ALERT=1 scripts/services-health.sh`:
   expect this line on stderr, exit status unchanged from `$B/health-before.txt`:
   `WARN network isolation (G1): not applied, none of authentik_portal, authentik_kindle, authentik_olivetin exists; the backends still share authentik_frontend (docs/runbooks/g1-network-isolation.md)`
1. **[CHANGES PRODUCTION]** Copy the four compose files from the export, keep modes. `docker compose config -q`
   in each directory.
2. **[CHANGES PRODUCTION]** `cd services/authentik && docker compose up -d --no-deps server`. Wait until
   `docker inspect authentik-server --format '{{.State.Health.Status}}'` is `healthy` (up to ~2 minutes).
   Check: `docker network inspect authentik_portal authentik_kindle authentik_olivetin` each list
   `authentik-server` only; `https://avrana.net` still answers (apps still on `authentik_frontend`, outpost
   reaches them there). Stop here if not.
3. **[CHANGES PRODUCTION]** One app at a time, in this order, verifying after each:
   `cd services/avrana-portal && docker compose up -d` then `services/avrana-kindle-connector`, then
   `services/olivetin`. After each: container `healthy`, its private network has exactly two members, the
   public hostname answers through the outpost (below). Do not start the next on any failure.
4. Verify and run the forgery check (below). Only when all pass:
5. **[CHANGES PRODUCTION: small state file]** Sign off, so that "not applied" and "cannot check" become
   failures from now on: `mkdir -p ~/.local/state/avrana && touch ~/.local/state/avrana/g1-applied`
   (the health script also honours `AVRANA_G1_APPLIED=1`, but the timer's unit has no environment file, so use
   the marker). Run `AVRANA_HEALTH_NO_ALERT=1 scripts/services-health.sh`: expect
   `OK   network isolation (G1): 3 private networks, two members each; no backend on authentik_frontend`.
   Then restart the timer (see "Health timer").

Do not run `docker compose down` in `services/authentik` at any point: it would try to remove these networks
while the backends are attached, and what happens then was not verified.

## Verify

Network membership (read-only; member order is whatever Docker prints):
```sh
docker network inspect authentik_frontend --format '{{range .Containers}}{{.Name}} {{end}}'
# expect authentik-server, authentik-worker, authentik-ldap and none of the three apps
for n in portal kindle olivetin; do docker network inspect authentik_$n --format '{{.Name}}: {{range .Containers}}{{.Name}} {{end}}'; done
# expect exactly two names each, per the table above
for c in avrana-portal avrana-kindle-connector olivetin; do docker inspect $c --format '{{.Name}} {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'; done
# expect one network each
ids=$(docker ps -aq) && [ -n "$ids" ] && modes=$(docker inspect --format \
  '{{.Name}} net={{.HostConfig.NetworkMode}} pid={{.HostConfig.PidMode}} ipc={{.HostConfig.IpcMode}}' $ids) \
  && echo "containers inspected: $(printf '%s\n' "$modes" | wc -l)" \
  && { printf '%s\n' "$modes" | grep -E ' net=container:' && echo "NET SHARING FOUND" || echo "no network namespace sharing"; } \
  && { printf '%s\n' "$modes" | grep -E ' (pid|ipc)=container:' || echo "no pid/ipc namespace sharing"; } \
  || echo "CHECK FAILED: docker ps or inspect returned nothing or an error; result is void"
# Pass only with a non-zero "containers inspected" count (it should equal `docker ps -aq | wc -l`) AND
# "no network namespace sharing". A container whose net= is container:<id of authentik-server or a backend>
# shares that network namespace, never appears in `docker network inspect`, and passes the drift guard while
# reaching every network its host container is on: a G1 failure (AVR-345 review, finding F1). pid/ipc
# sharing is a separate finding to report, not a network bypass. Containers with net=host are the known
# D-3 residual and are not reported by this check.
```

Through the outpost, as a **member** (in `avrana-users`; `avrana-books` for Kindle) and as an **admin**
(`authentik Admins`), in a browser:
- `https://avrana.net`: sign-in, tiles render for the member's groups (member sees no Operations tile).
- `https://kindle.avrana.net`: member with `avrana-books` sees the form; one without gets the deny page.
- `https://ops.avrana.net`: admin sees actions; member is refused by Authentik. Run the harmless
  health/status action only. Do not run restart actions as a test.
- Kindle connector still reaches Audiobookshelf (`ABS_URL` is the LAN IP `10.0.0.218:13378`): the form loads
  the saved address (no save needed). OliveTin's status action reads Jellyfin/Audiobookshelf the same way.

Health script: `AVRANA_HEALTH_NO_ALERT=1 scripts/services-health.sh`, no new FAIL. Then
`python3 scripts/drift-check.py --quiet` and record the result in the batch ledger.

## Forgery check

Goal: a container on `authentik_frontend` cannot reach any backend, by name or IP, even with forged headers.
A failure to connect only means something if the same strings are shown to work from a container that does
share the backend's network, and if the test container itself has working DNS and outbound routing. So
the check has three parts: positive controls on each private network (A), the negative test (B), and a
routing control for the test container (C). A negative result with a failed control is void, not a pass.

**Strings under test.** Define them once and use these exact variables everywhere. Take IPs from the
container, which prints no `/NN` suffix; `docker network inspect ... {{.IPv4Address}}` prints `172.x.y.z/16`
and the suffix must be stripped (a leftover `/16` makes every request fail and fakes a pass).
```sh
ip_of() { docker inspect "$1" --format "{{(index .NetworkSettings.Networks \"$2\").IPAddress}}"; }
PORTAL=avrana-portal:8095;           PORTAL_IP=$(ip_of avrana-portal authentik_portal):8095
KINDLE=avrana-kindle-connector:8096; KINDLE_IP=$(ip_of avrana-kindle-connector authentik_kindle):8096
OLIVE=olivetin:1337;                 OLIVE_IP=$(ip_of olivetin authentik_olivetin):1337
echo "$PORTAL_IP $KINDLE_IP $OLIVE_IP"          # each must look like 172.20.0.3:8095, no slash, no empty IP
```

**A. Positive control: the names, IPs and ports are right and reachable from the proper side.** The prober
must share each private network with its backend. Preferred: run it inside `authentik-server`, which is on all
three, so no membership changes. First find out what that image has (read-only):
```sh
docker exec authentik-server sh -c 'command -v curl wget python3 python'
```
Use whichever it prints; the image's contents are not recorded in this repository and are unverified.
```sh
# with curl:   A() { docker exec authentik-server curl -sS -m 5 -o /dev/null -w '%{http_code}\n' "$1"; }
# with python: A() { docker exec authentik-server python3 -c 'import sys,urllib.request as u; print(u.urlopen(sys.argv[1],timeout=5).status)' "$1"; }
for t in $PORTAL $PORTAL_IP $KINDLE $KINDLE_IP $OLIVE $OLIVE_IP; do echo "$t $(A http://$t/healthz)"; done
```
Expect `200` for all six (`/healthz` is each backend's own healthcheck path and needs no headers). Any
other result: stop, the strings are wrong or a backend is down; do not proceed to B.
If the server image has none of curl, wget or python: use a throwaway container on the private network
instead (`docker run --rm --network authentik_portal ...` with the OliveTin image as in B, once per network).
That makes the network briefly three members, so the timer must be stopped (it is) and the container removed
before anything else; **[CHANGES PRODUCTION]**.

**B. Negative test from `authentik_frontend`.** Uses an image already on the host: the OliveTin image ships
`curl` (its compose healthcheck uses it), so nothing is pulled.
```sh
IMG=$(docker inspect olivetin --format '{{.Image}}')
probe() {
  docker run --rm --network authentik_frontend --read-only --cap-drop ALL --entrypoint curl "$IMG" \
    -sS -m 5 -o /dev/null -w 'http=%{http_code}\n' "$@"; echo "curl_rc=$?"
}
forge() { probe -H 'X-authentik-username: forged' -H 'X-authentik-groups: authentik Admins' "$@"; }
for t in $PORTAL $PORTAL_IP $KINDLE $KINDLE_IP $OLIVE $OLIVE_IP; do echo "== $t"; forge http://$t/; done
```
Every `probe`/`forge` call **[CHANGES PRODUCTION: starts and removes a throwaway container]**.
Expect for every target `http=000`, with `curl_rc=6` (could not resolve host) for the names and `curl_rc=7` or
`28` (refused / timed out) for the IPs. Any other `http=` value is a **G1 failure**: stop and roll back. A
`curl_rc` of 6 on an IP, or any other code, means the test itself is malformed: fix and rerun.

**C. Control for the test container.** From the same container, `probe http://authentik-server:9000/-/health/live/`
expect `http=200` or `204` (DNS and routing on `authentik_frontend` work); and
`probe http://10.0.0.218:13378/healthcheck` expect `http=200` (outbound to the LAN works, as the health
script's Audiobookshelf check does). Run C before B's verdict is accepted.

**E. Through the outpost: forged headers are replaced, not passed (owner, read-only).** G1 assumes the
pinned outpost overwrites client-sent `X-authentik-*` headers; nothing in this repository proves that for
this image (AVR-345 review, finding F3). Unauthenticated, from any LAN shell (no credential involved):
```sh
fc() { curl -s -o /dev/null -m 10 -w '%{http_code} %{redirect_url}' -H 'X-authentik-username: forged' \
       -H 'X-authentik-groups: authentik Admins' -H 'X_authentik_groups: authentik Admins' "$@"; }
for u in avrana.net kindle.avrana.net ops.avrana.net; do
  echo "$u $(fc https://$u/ops)"
  echo "lan $u $(fc -H "Host: $u" http://10.0.0.218:9000/ops)"
done
```
**E1 (unauthenticated):** expect `302` to `https://<same host>/outpost.goauthentik.io/start?rd=...` (the
outpost's `redirectToStart`, Authentik 2026.5.6), or directly to `auth.avrana.net`, for all six (the LAN port
9000 is the same outpost). Any `200`, `307` or `404` from a backend, or a redirect elsewhere, is a
**G1 failure**. `scripts/g1-preflight.sh --e1` runs exactly this check. E1 only shows that unauthenticated
requests never reach a backend; the outpost redirects before it would set or strip any header, so **E1 says
nothing about header overwrite and is not evidence for F3**.

**E2 (authenticated; the only evidence for F3).** Signed in as a **member without `authentik Admins`**, the owner
(never an agent: it needs the owner's session) uses a browser header-editing tool to add
`X-authentik-groups: authentik Admins` and opens `https://avrana.net/` and `https://avrana.net/ops`: expect no
Operations tile and a 404 for `/ops`. Then, as a member in `avrana-books`, add
`X-authentik-username: <another member's username>` and open `https://kindle.avrana.net/`: expect the signed-in
member's own saved address (or none), never the other member's. Positive control first: without the extra
header the member's own page renders normally. If the tile appears or another member's data shows, the outpost
passed the forged header: stop and roll back; G1 does not hold for this Authentik version.

**D. Expected non-failure (host).** `curl -m 5 http://<backend IP>/healthz` from the host shell **will**
succeed (the host reaches all bridge IPs). Record it as the residual risk, not a failure.

## Rollback

Trigger: any stop condition below. First, if set, remove the marker so the health script does not FAIL
during rollback: **[CHANGES PRODUCTION: state file]** `rm -f ~/.local/state/avrana/g1-applied`. Keep the
health timer stopped until the end. Then choose the branch by how far the apply got
(`docker inspect <app> --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'` for each app):

**Branch 1: the apps were never recreated** (failure at or before step 2: address-pool error, dry run
surprise, `authentik-server` unhealthy, SSO down). Every app is still on `authentik_frontend`; do not
recreate them and do not wait for the three hostnames, which cannot answer while the server is down.
1. **[CHANGES PRODUCTION]** Restore `services/authentik/docker-compose.yml` from `$B/rollback/`; verify the
   SHA-256. Restore the three app compose files too if step 1 copied them (files only; no `up`).
2. **[CHANGES PRODUCTION]** `cd services/authentik && docker compose up -d --no-deps server`
   (if the server was never recreated, this is a no-op). Wait for `healthy`.
3. Only now check `https://avrana.net`, `kindle.`, `ops.`.
4. **[CHANGES PRODUCTION]** Remove the now empty private networks if they were created:
   `docker network rm authentik_portal authentik_kindle authentik_olivetin` (owner approval; fails safely if
   anything is still attached). The health check FAILs on a partly present set.

**Branch 2: one or more apps were recreated** (failure at step 3 or later). Apps first, so the outpost never
loses a backend:
1. **[CHANGES PRODUCTION]** Restore the three app compose files from `$B/rollback/`; verify SHA-256.
   For each app that is on its private network, in turn: `docker compose config -q && docker compose up -d`
   (rejoins `authentik_frontend`); container healthy, hostname answers.
2. **[CHANGES PRODUCTION]** Restore `services/authentik/docker-compose.yml`;
   `docker compose up -d --no-deps server`; wait healthy (about a minute of SSO downtime again).
3. **[CHANGES PRODUCTION]** `docker network rm authentik_portal authentik_kindle authentik_olivetin` once empty.

Both branches, at the end: restore the old `scripts/services-health.sh` only if the new one itself
misbehaves; verify `docker network inspect authentik_frontend` lists the three apps again, the three hostnames
answer, `drift-check.py --quiet` equals `$B/drift-before.txt`; **[CHANGES PRODUCTION]**
`systemctl --user start services-health.timer`. Git (`main`) then differs from production until the owner
decides; record that in the ledger.

## Stop conditions

Stop, do not improvise, and roll back or hold as stated:
- Address-pool check shows no room, or `docker compose up` reports "fully subnetted" / any allocator error
  (Branch 1; server untouched).
- Dry run shows any container other than the one intended being recreated.
- `authentik-server` not healthy within 3 minutes, or an Authentik hostname not answering after step 2
  (Branch 1).
- Any app not `healthy` or its hostname not answering after its step: roll that app back first (Branch 2).
- A private network with any member other than the expected two, or an app on two networks.
- Forgery check: any HTTP status from a backend through `authentik_frontend`; or any positive control (A, C)
  fails (the test is then void, not passed).
- Namespace sharing found (Verify), or check E shows a forged header reaching a backend.
- The health script prints any new FAIL.
- Anything not in this document.

## D-3: outpost shared-secret header (second layer), assessment only

Idea: the outpost adds a secret header; each backend refuses requests without it, so a container wrongly
attached later, or code on the host, cannot forge identity. It closes the host-namespace gap G1 leaves.

Needed, none of it done here:
1. Confirm the running Authentik version (the image is pinned by digest, the tag is not in the repo) and that
   a proxy provider can add a **constant** header. The mechanism to verify is a property (scope) mapping on the
   proxy provider whose result carries `additionalHeaders`; documentation describes this per user/group
   attribute, **a constant per-provider value is unverified** for this version and for the embedded outpost.
2. A secret generated on the host, stored like the others (`docs/SECRETS.md`), injected into the blueprint via
   `blueprints.env` (`!Env`, worker only) and into each backend by env file. Owner step; no value in Git.
3. Backend changes: portal and Kindle connector compare the header in constant time before trusting any
   `X-authentik-*` value and return 404 otherwise (Python in `portal.py`, `kindle.py`, not touched here).
   OliveTin has no known option to require a header: unverified; it would need a small front proxy or be
   left to G1 alone.
4. Rotation: change the secret in the blueprint and each backend together; a mismatch locks everyone out
   (reversible: restore the file).
Recommendation: verify items 1 and 3 offline against the pinned image's documentation and a disposable
instance before deciding; it is worth doing before M3 reads library data because it is the only layer that
covers the host namespace.

## After applying

Record the result in `docs/DECISIONS.md` (D-2). The live gating tests in
`services/avrana-kindle-connector/tests/test_kindle.py` run containers on `authentik_frontend` and address
`avrana-kindle-connector:8096` by name; they cannot work after this change and need a different probe.
