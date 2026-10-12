# G1: private network per Authentik-proxied backend

**Staged, not applied.** AVR-355 prepares this; AVR-356 is the owner applying it (decision D-2). Gate G1 in
[`design/MEDIA-2.0.md`](../design/MEDIA-2.0.md) section 4; forensic audit D4. Read
[`DEPLOYMENT.md`](../DEPLOYMENT.md) and [`OPERATIONS.md`](../OPERATIONS.md) first. Steps marked
**[CHANGES PRODUCTION]** need the owner's approval for this batch; everything else is read-only.

## What changes

`avrana-portal`, `avrana-kindle-connector` and `olivetin` trust `X-authentik-*` headers. Today they share
`authentik_frontend` with `authentik-worker` and `authentik-ldap`, so a sibling can send them forged
headers. After the change each sits on its own network with `authentik-server` (the embedded outpost) only:

| Network | Members (exactly) | Outpost `internal_host` |
|---|---|---|
| `authentik_portal` | `authentik-server`, `avrana-portal` | `http://avrana-portal:8095` |
| `authentik_kindle` | `authentik-server`, `avrana-kindle-connector` | `http://avrana-kindle-connector:8096` |
| `authentik_olivetin` | `authentik-server`, `olivetin` | `http://olivetin:1337` |

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
scripts/services-health.sh                                                > $B/health-before.txt   # expect WARN "G1 not applied" once the new script is deployed
for u in avrana.net kindle.avrana.net ops.avrana.net; do curl -s -o /dev/null -m 10 -w "$u %{http_code}\n" https://$u/; done  # expect 302 to auth.avrana.net
```

Expected before: `authentik_frontend` lists the three apps plus `authentik-server`, `authentik-worker`,
`authentik-ldap`; the three private networks do not exist.

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

0. **[CHANGES PRODUCTION]** Deploy `scripts/check-network-isolation.py` (mode 755) and the new
   `scripts/services-health.sh` (755); save the old one first. Run `scripts/services-health.sh`: expect
   `WARN network isolation (G1): not applied`, exit 0 (all else as before).
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

Do not run `docker compose down` in `services/authentik` at any point (removes the networks; the apps keep a
stale network ID).

## Verify

Network membership (read-only):
```sh
docker network inspect authentik_frontend --format '{{range .Containers}}{{.Name}} {{end}}'
# expect: authentik-server authentik-worker authentik-ldap  (none of the three apps)
for n in portal kindle olivetin; do docker network inspect authentik_$n --format '{{.Name}}: {{range .Containers}}{{.Name}} {{end}}'; done
# expect exactly two names each, per the table above
for c in avrana-portal avrana-kindle-connector olivetin; do docker inspect $c --format '{{.Name}} {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'; done
# expect one network each
```

Through the outpost, as a **member** (in `avrana-users`; `avrana-books` for Kindle) and as an **admin**
(`authentik Admins`), in a browser:
- `https://avrana.net`: sign-in, tiles render for the member's groups (member sees no Operations tile).
- `https://kindle.avrana.net`: member with `avrana-books` sees the form; one without gets the deny page.
- `https://ops.avrana.net`: admin sees actions; member is refused by Authentik. Run the harmless
  health/status action only. Do not run restart actions as a test.
- Kindle connector still reaches Audiobookshelf (`ABS_URL` is the LAN IP `10.0.0.218:13378`): the form loads
  the saved address (no save needed). OliveTin's status action reads Jellyfin/Audiobookshelf the same way.

Health script: `AVRANA_HEALTH_NO_ALERT=1 scripts/services-health.sh`. Expect
`OK   network isolation (G1): 3 private networks, two members each; no backend on authentik_frontend` and no
new FAIL. Then `python3 scripts/drift-check.py --quiet` and record the result in the batch ledger.

## Forgery check

Goal: a container on `authentik_frontend` cannot reach any backend, by name or IP, even with forged headers.
Uses an image already on the host (the OliveTin image is Fedora-based and ships `curl`), so nothing is
pulled. The container joins `authentik_frontend` only for the test and is removed (`--rm`).

```sh
IMG=$(docker inspect olivetin --format '{{.Image}}')            # read-only: image ID of the running olivetin
probe() {
  docker run --rm --network authentik_frontend --read-only --cap-drop ALL --entrypoint curl "$IMG" \
    -sS -m 5 -o /dev/null -w '%{http_code}\n' "$@"
}
forge() { probe -H 'X-authentik-username: forged' -H 'X-authentik-groups: authentik Admins' "$@"; }
```
Every `probe`/`forge` call below **[CHANGES PRODUCTION: starts and removes a throwaway container]**.

1. **Positive control (the test container works and sees the network):**
   `probe http://authentik-server:9000/-/health/live/` expect `200` or `204`. This proves the container
   starts, has DNS and routes on `authentik_frontend`.
2. **By name**, three times: `forge http://avrana-portal:8095/`
   (and `http://avrana-kindle-connector:8096/`, `http://olivetin:1337/`). Expect `curl: (6) Could not resolve host`
   and code `000`. A `200`/`403`/`302` from any backend is a **G1 failure**.
3. **By IP.** Read each backend's private-network IP (read-only):
   `docker network inspect authentik_portal --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'`
   (and `_kindle`, `_olivetin`). Repeat step 2 with `forge http://<ip>:<port>/`. Expect timeout or
   `curl: (7)`/`(28)`, code `000`. Any HTTP status is a **G1 failure**.
4. **Positive control for IP routing:** `probe http://<authentik-server frontend IP>:9000/-/health/live/`
   (IP from `docker network inspect authentik_frontend`), expect `200`/`204`. This shows an IP request from that container does work where a path exists, so the
   failures in step 3 mean isolation and not a broken test.
5. **Expected non-failure (host):** `curl -m 5 http://<backend IP>:<port>/` from the host shell **will**
   succeed (host reaches all bridge IPs). Record it as the residual risk, not a failure.

## Rollback

Trigger: any stop condition below. Production rollback is the saved copy, order matters (apps first, so the
outpost never loses a backend):

1. **[CHANGES PRODUCTION]** Restore from `$B/rollback/`: the three app compose files; verify SHA-256.
   For each app in turn: `docker compose config -q && docker compose up -d` (rejoins `authentik_frontend`);
   container healthy, hostname answers.
2. **[CHANGES PRODUCTION]** Restore `services/authentik/docker-compose.yml`;
   `docker compose up -d --no-deps server`; wait healthy (about a minute of SSO downtime again).
3. **[CHANGES PRODUCTION]** The private networks are now empty and still exist; the health check FAILs on that
   (a partly present state). Remove them once empty: `docker network rm authentik_portal authentik_kindle authentik_olivetin`
   (owner approval; fails safely if any container is still attached).
4. Restore the old `scripts/services-health.sh` only if the new one itself misbehaves.
5. Verify: `docker network inspect authentik_frontend` lists the three apps again; three hostnames answer;
   `drift-check.py --quiet` equals `$B/drift-before.txt`. Note: Git (`main`) then differs from production
   until the owner decides; record that in the ledger.

## Stop conditions

Stop, do not improvise, and roll back or hold as stated:
- Dry run shows any container other than the one intended being recreated.
- `authentik-server` not healthy within 3 minutes, or an Authentik hostname not answering after step 2.
- Any app not `healthy` or its hostname not answering after its step: roll that app back first (step 1).
- A private network with any member other than the expected two, or an app on two networks.
- Forgery check: any HTTP status from a backend through `authentik_frontend`; or the positive controls fail
  (the test is then void, not passed).
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

Record the result in `docs/DECISIONS.md` (D-2), update the ROADMAP line on D4, and
`docs/services/avrana-portal.md` (it still says the portal is on `frontend`). The live gating tests in
`services/avrana-kindle-connector/tests/test_kindle.py` run containers on `authentik_frontend` and address
`avrana-kindle-connector:8096` by name; they cannot work after this change and need a different probe.
