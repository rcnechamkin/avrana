# Avrana / Kern — Forensic Audit

**Date:** 2026-08-30 · **Scope:** `/home/cody/avrana` (repo as primary source of truth) + live host
**Mode:** read-only. No files modified, no services restarted, no configuration changed.
**Baseline for intent:** `CLAUDE.md`, `docs/`, `deploy/`, and BookStack pages 8, 35, 36, 63, 75 consulted selectively.

---

## A. Executive summary

The container estate and the backup subsystem are, on the evidence, better engineered than most
production systems of comparable size. The backup script reasons explicitly about WAL tearing,
root-owned files inside containers, allowlists over exclude-lists, and its own past reporting bugs.
The restore test boots a real Audiobookshelf from restored bytes rather than asserting a file is
non-empty. The Docker socket proxies are minimal and digest-pinned. The portal's header-trust model
was checked against reality and holds. These are not accidents, and several of them are load-bearing
defences that a naive cleanup would remove.

The problems cluster in three places, and none of them is where the effort has been going.

**First, the verification layer has silently stopped verifying.** `restore-test.sh` asserts on a
systemd unit that was deliberately retired on 2026-08-28. Every backup taken since 2026-08-29 09:34
fails that assertion. Nothing schedules the restore test, so nothing noticed. The claim "the restore
is tested", repeated in BookStack page 8 and relied on implicitly everywhere else, has been false for
two days. Separately, the single most consequential backup component, Authentik's `pg_dump`, is the
only large dump with **no** structural validation at write time and **no** restore assertion, while
the far less critical Tracearr dump has both.

**Second, a defence that the codebase explicitly documents has already regressed.** The backup
script warns in its own comments that capturing cloudflared tunnel credentials is only safe because
no container mounts the array root any more. `services/avrana-imax-verify` mounts the array root.
It was verified during this audit reading the tunnel credential archive and a `0600` \*arr
`config.xml`, the latter because the file's mode is defeated by the container sharing uid 1000.
The staged-but-undeployed Bazarr service would reopen the same hole read-write.

**Third, the one failure mode that actually caused an outage has no detection.** The 2026-08-29
incident cost roughly seven extra hours because Sonarr held an indexer backoff after Prowlarr
recovered. `services-health.sh` polls `/ping`, which returned `OK` throughout. Nothing reads
`/api/v3/health`. The same outage today would again show an all-green dashboard.

One committed credential was found: a Strava OAuth `client_secret` and authorization code in
`kern_sync/strava/manual_exchange.py`, present in `origin/main`. The GitHub repository is not
publicly readable, which bounds the exposure but does not remove the need to rotate.

The legacy Kern Prime subsystem (`api/`, `core/`, `main.py`, `filing_cabinet/`) is genuinely dead
rather than merely idle, and its analysis is already correct in BookStack. It is the last large
piece of accidental complexity, and it is cheap to resolve because nothing depends on it.

---

## B. Architecture map

### Two eras in one repository

```
LEGACY (2025-06, dead)                      CURRENT (2026-08, production)
main.py, api/, core/, auth/                 services/<name>/docker-compose.yml   x24
filing_cabinet/, kern_calendar/             services/backups/                    backup + restore
kern_sync/, scheduler/, blackboxes/         scripts/services-health.sh           monitoring
avranos_gui/, utils/, config/, configs/     deploy/{docker,ufw,systemd,compose}/ host layer
                                            bin/bs                               wiki retrieval
```

The legacy tree is ~2.4 MB and reachable only through `avrana.service`, which is disabled and has
never started successfully. `main.py` builds a FastAPI `app` and returns without ever invoking
uvicorn, so even repairing the known `api/health.py` import error would produce a restart loop under
`Restart=always`. `api/health.py` is now a deliberate documented stub.

### Service topology

| Tier | Components | Notes |
|---|---|---|
| Identity | `authentik` (server, worker, ldap, postgresql) | Sole IdP. Postgres moved to SSD. |
| Ingress | one cloudflared tunnel, 12 hostnames, Authentik embedded proxy outpost | No inbound port-forward. |
| Front door | `avrana-portal` | No published port. Only on `authentik_frontend`. |
| Video | `jellyfin` (profile `media`), `radarr`, `sonarr`, `prowlarr`, `seerr` | Project **`docker`**, from `services/media/docker-compose.yml`. |
| Books/audio | `audiobookshelf`, `calibre-web-automated`, `libation`, `shelfmark`, `shelfarr`, `completeseries` | |
| Comics | `komga`, `omnibus` (+redis, engine), `mylar3` (bare metal) | mergerfs union. |
| Connectors | `avrana-audible-connector` (+companion), `avrana-kindle-connector` | Most-tested code in the repo. |
| Ops | `homepage`, `beszel`, `olivetin`, `tracearr`, `bookstack`, `recyclarr`, `avrana-imax-verify` | |
| Kern HQ | `home-assistant`, `wyoming-piper`, `speech-to-phrase` | Fully local voice. |
| Bare metal | SABnzbd, mylar3, Plex, nginx, UniFi OS Server | Outside every container control. |

### Data flows that matter

```
Radarr/Sonarr --webhook--> avrana-imax-verify --reads--> /mnt/avrana_media  (ARRAY ROOT, ro)
                                                              |
avrana-backup.sh --writes--> /mnt/avrana_media/.backups/avrana/<ts>/  <---- readable by the above
       |                                   |
       |                                   +--> restore-test.sh  (manual only, currently FAILING)
       +--> LAST_RUN.json --> services-health.sh --> (no alert transport; exit code only)

offhost-sync.sh --(blocked: no key)--> rclone crypt --> B2/R2
```

### Deliberate design vs accidental complexity

**Deliberate, and correct:** the array-root mount for the \*arr (hardlinks need one mount; `EXDEV`
otherwise) with a tmpfs shadow over `.backups`; the `docker` compose project name; profile-gated
services; the allowlist in `backup_stack_config`; building the Home Assistant archive inside the
container.

**Accidental:** the legacy tree; `komga`/`komf` being fully gitignored and mirrored by hand into
`deploy/compose/` with nothing enforcing sync; four overlapping book/comic request services
(Mylar3, Shelfmark, Omnibus, Shelfarr) writing into shared inboxes; five distinct startup
mechanisms.

---

## C. Confirmed findings, ranked by severity

### C1. `restore-test.sh` has been failing since 2026-08-29 and nothing runs it
**Severity: HIGH · Confidence: HIGH · Automatable: YES**

**Component:** `services/backups/restore-test.sh:172-176`

**Evidence.** Step 9 asserts `[[ -s "$sysdir/user/health_api.service" ]]`. The Health API was retired
on 2026-08-28 (commit `68d8e92`), so the unit file no longer exists and is no longer captured.
Measured across all seven retained runs:

```
2026-08-25 .. 2026-08-28   systemd component absent entirely  (documented, ages out)
2026-08-29T03-32-44Z       health_api present   -> the run BookStack page 8 cites as PASSED
2026-08-29T09-34-45Z       health_api MISSING
2026-08-30T09-31-29Z       health_api MISSING
```

Nothing schedules `restore-test.sh`; `grep -r restore` over the timers and `services-health.sh`
returns nothing. It is invoked by hand only.

**Failure scenario.** Restores are attempted after a real loss. The operator runs the restore test
for reassurance, it dies at step 9 on a unit nobody needs, and either the run is abandoned or the
assertion is bypassed wholesale, discarding the eight genuine checks in front of it. Meanwhile the
documentation asserts the restore path is proven.

**Remediation.** Drop `user/health_api.service` from the assertion list. Add a weekly
`avrana-restore-test.timer`, and surface its result through `services-health.sh` the way
`LAST_RUN.json` already is. Safe to automate.

---

### C2. `avrana-imax-verify` can read the entire backup tree, including tunnel credentials
**Severity: HIGH · Confidence: HIGH · Automatable: YES**

**Component:** `services/avrana-imax-verify/docker-compose.yml:37`

**Evidence.** The service mounts `- /mnt/avrana_media:/data:ro`, the array root, with no tmpfs
shadow over `.backups`. Verified from inside the running container:

```
$ docker exec avrana-imax-verify sh -c 'ls -la /data/.backups/avrana/2026-08-30T09-31-29Z/cloudflared/'
-rw-rw-r-- 1 1000 1000 1561 Aug 30 02:32 cloudflared-config.tar.zst
$ docker exec avrana-imax-verify head -c 60 .../arr/radarr/config.xml
<Config>
  <BindAddress>*</BindAddress>
  <Port>7878</Port>
```

`config.xml` is written `0600` by the backup script specifically to protect the API key. That mode
provides no protection here because the container runs as uid 1000, the same uid that owns the file.

`avrana-backup.sh:283-289` states the risk in its own words: *"That is only safe because the backup
tree is no longer readable by the media containers ... If anything ever remounts the array ROOT into
a container again, this component starts leaking the tunnel's identity."* The regression is already
present.

**Failure scenario.** `imax_verify.py` runs ffmpeg over attacker-influenced media files (filenames
and containers arrive from Usenet via Radarr). A parsing or path-handling flaw yields code execution
as uid 1000 inside the container, which then reads the cloudflared tunnel credentials, Authentik's
full `pg_dump` (every user, hash and OIDC client secret), BookStack's `APP_KEY`, and all three \*arr
API keys. The tunnel credential alone allows impersonating Avrana's public ingress. The service is
LAN-only, but ufw is confirmed inert, so every LAN device can reach `:8099`.

**Remediation.** The array root is not required. The compose comment explains the mount exists so
paths match Radarr's webhook payloads (`/data/movies/...`). Mounting
`/mnt/avrana_media/movies:/data/movies:ro` preserves that mapping exactly while excluding
`.backups`. Alternatively apply the same `tmpfs: - /data/.backups:ro,...,size=4k` shadow the \*arr
already use. Safe to automate; requires a container recreate.

---

### C3. Authentik's dump is the least-verified artifact in the backup
**Severity: HIGH · Confidence: HIGH · Automatable: YES**

**Component:** `services/backups/avrana-backup.sh:88-96`, `services/backups/restore-test.sh`

**Evidence.** `backup_authentik` accepts the dump if the compressed file is merely non-empty
(`[[ -s "$d/authentik.pgdump.zst" ]]`). `restore-test.sh` never touches it. Compare `backup_tracearr`
plus restore-test step 8, which greps for `-- PostgreSQL database dump complete`, checks specific
`CREATE TABLE` statements, and explicitly fails a truncated dump. Authentik is by far the more
consequential of the two and receives the weaker treatment.

The current dump was validated during this audit and **is** structurally complete: completion marker
present, 215 `CREATE TABLE` statements. The finding is the absence of the check, not a present
corruption.

**Failure scenario.** `docker exec ... pg_dump` writes to a pipe. If the container restarts, the
daemon is bounced, or the pipe breaks mid-stream, `zstd` still produces a valid non-empty archive of
a truncated dump. The component reports `good`, `LAST_RUN.json` says `ok`, `services-health.sh`
stays green, and the truncation is discovered when the identity provider is being rebuilt after a
loss. Every user, group, application and OIDC client secret is in that one file.

**Remediation.** Assert the completion marker at write time, exactly as Tracearr's path implicitly
allows. Add a restore-test assertion for the marker and for `CREATE TABLE public.authentik_core_user`.
Extend the same to BookStack's `mariadb-dump`. Safe to automate.

---

### C4. Committed Strava OAuth client secret, present in `origin/main`
**Severity: HIGH · Confidence: HIGH · Automatable: PARTIALLY**

**Component:** `kern_sync/strava/manual_exchange.py:4-6`

**Evidence.** The file is tracked, contains a literal `client_secret = "<32 hex chars>"`, a literal
authorization `code`, and `client_id = "165690"`. `git branch -r --contains` places its commit on
`origin/main`. Remote is `https://github.com/rcnechamkin/Kern-Ecosystem.git`.

The unauthenticated GitHub API returns **404** for that repository, which is how GitHub reports a
private repository to an anonymous caller. The secret is therefore not publicly readable. That
bounds the blast radius; it does not remove the exposure, because the value is in every clone and
in the history.

This is the only hardcoded credential literal in tracked Python. Three other files matched the
credential-shaped-literal scan and are all correct patterns reading from env vars or
`/run/secrets/`.

**Failure scenario.** The repository is made public, a collaborator is added, or a clone is shared.
The Strava application can then be impersonated. The blast radius is bounded (personal fitness data,
and `strava_fetch.service` already fails on an expired token), which is why this is HIGH and not
CRITICAL.

**Remediation.** Rotate the Strava client secret at Strava's developer console. Delete the file, or
rewrite it to read from `kern_secrets/`. History rewriting is optional given the repository is
private and the value will be rotated; note it explicitly as a decision rather than skipping it
silently. Rotation is manual; the file change is automatable.

---

### C5. Staged Bazarr configuration reopens the array-root hole, read-write and unhardened
**Severity: HIGH (latent) · Confidence: HIGH · Automatable: YES**

**Component:** `services/media/docker-compose.yml:185-204`

**Evidence.**

```yaml
bazarr:
  image: linuxserver/bazarr          # no tag at all -> :latest
  volumes:
    - /mnt/avrana_media:/data        # array ROOT, READ-WRITE
  profiles: ["optional"]
```

No `cap_drop`, no `security_opt`, no `read_only`, no `tmpfs` shadow, no `mem_limit`, no
`pids_limit`, no digest. Every sibling service in the same file has all of them. BookStack page 36
records the opposite decision explicitly: *"Mount ONLY `/mnt/avrana_media/movies` and
`/mnt/avrana_media/tv` (rw), never the array root: the root would re-expose `/data/.backups` ... to
an internet-facing service."*

**Failure scenario.** Someone resumes the shelved Bazarr work, follows the roadmap's instruction to
bring it up, and runs `docker compose --profile optional up -d bazarr`. They get an unpinned,
unhardened container with read-write access to every backup on the array. Read-write means deletion,
not merely disclosure.

**Remediation.** Bring the stanza in line with the documented decision before it is ever started:
narrow the mounts to `movies` and `tv`, pin a digest, add the house hardening baseline. Safe to
automate; the service is not running.

---

### C6. The failure mode that caused the last outage has no detection
**Severity: MEDIUM · Confidence: HIGH · Automatable: YES**

**Component:** `scripts/services-health.sh:16-18`, `deploy/docker/verify-baseline.sh`

**Evidence.** Both check `/ping` for Radarr, Sonarr and Prowlarr. Neither reads `/api/v3/health`.
Verified live:

```
GET /ping                -> {"status": "OK"}
GET /api/v3/health       -> []      (currently clean; nothing consumes it)
```

`grep -riE 'api/v3/health|indexer'` across the health scripts returns nothing.

Per `deploy/docker/INCIDENT-2026-08-29.md` fault 4, Sonarr sat at `EscalationLevel 7` with
`DisabledTill 15:20 PDT`, roughly five hours after Prowlarr was healthy, showing
`All indexers are unavailable due to failures for more than 6 hours` on exactly the endpoint nobody
polls. `/ping` was green throughout.

**Failure scenario.** Any future Prowlarr interruption leaves Sonarr silently dark for hours after
recovery, with every dashboard green. This has already happened once and cost roughly seven hours.

**Remediation.** Add an `/api/v3/health` check per \*arr service, treating any returned entry as a
warning and an indexer-specific entry as a failure. API keys are already on the host in
`/home/cody/docker/<svc>/config.xml`. Safe to automate.

---

### C7. `/etc/docker/daemon.json` is silently absent from the backup
**Severity: MEDIUM · Confidence: HIGH · Automatable: YES**

**Component:** `services/backups/avrana-backup.sh:340`

**Evidence.** `cp -p /etc/docker/daemon.json "$d/docker-daemon.json" 2>/dev/null` with no return
check. The file is `-rw------- root root`, and the backup runs as `cody`, so the copy always fails
and stderr is discarded. Confirmed absent from the 2026-08-30 run while the component reported
`good`.

The component's success criterion is `(( n > 0 ))`, where `n` counts only unit files. It can
therefore report success while omitting every non-unit artifact it claims to capture.

**Failure scenario.** A host rebuild restores containers and units but not Docker's `data-root`
setting. Docker starts with `/var/lib/docker` on the root LV, every container comes up with empty
state, and the operator concludes the backup was incomplete rather than mis-restored. This matters
more once address pools land in that file.

**Remediation.** Check the copy's result and report `fail` on loss, or read the file through a
privileged path and document that the component needs it. Note this is the same class of silent
success the script already fixed for `backup_omnibus` and the Home Assistant archive; the pattern is
recognised but was not applied here. Safe to automate.

---

### C8. Retention can rotate away the last good backup
**Severity: MEDIUM · Confidence: HIGH · Automatable: YES**

**Component:** `services/backups/avrana-backup.sh:406-408`

**Evidence.** `mv "$PARTIAL" "$DEST"` runs unconditionally, so a run with failed components is
promoted to a normal dated directory. Rotation then sorts by name and keeps the newest `KEEP=7`
regardless of `status`.

**Failure scenario.** A component breaks on day 1 and every subsequent run is `partial`. After seven
days the last fully-good backup is pruned, leaving seven consecutive degraded copies. Detection
depends on someone acting on the `services-health.sh` failure within a week, and there is no alert
transport, only an exit code.

**Remediation.** Never prune the newest run whose `status` was `ok`, or keep a separate `last-good`
pointer excluded from rotation. Safe to automate.

---

### C9. Unpinned upstream images on running services
**Severity: MEDIUM · Confidence: HIGH · Automatable: YES**

**Component:** `services/bookstack/docker-compose.yml`, `services/shelfmark/docker-compose.yml`,
`services/kavita/docker-compose.yml`, `services/media/docker-compose.yml`

**Evidence.** Digest-pinned coverage by service was measured across all 24 compose files. Genuinely
unpinned **pulled** images (locally built images correctly excluded, since a built image cannot be
digest-pinned):

| Service | Image | Running |
|---|---|---|
| bookstack | `lscr.io/linuxserver/bookstack:26.05.3` | yes |
| bookstack-mariadb | `lscr.io/linuxserver/mariadb:11.8.8` | yes |
| shelfmark | `ghcr.io/calibrain/shelfmark:1.3.6` | yes |
| kavita | `jvmilazz0/kavita:latest` | no (`legacy`) |
| bazarr | `linuxserver/bazarr` (no tag) | no (`optional`) |

**Failure scenario.** LinuxServer rebuilds version tags in place. A `docker compose pull` during
unrelated maintenance silently changes the BookStack or MariaDB binary. For MariaDB specifically,
an unintended major-version move against an existing data directory is a restore-from-backup event.

**Remediation.** Pin digests for the three running images. The two profile-gated ones are lower
priority but `:latest` and untagged should not survive. Safe to automate.

---

### C10. A 20 MB binary installer is committed to Git
**Severity: LOW · Confidence: HIGH · Automatable: YES**

**Component:** `cloudflared-linux-amd64.deb`

**Evidence.** Largest tracked file in the repository by an order of magnitude. `epub-report.csv`
(32 KB, a generated report) is the same class.

**Remediation.** Remove from tracking, add to `.gitignore`. Rewriting history is optional and the
repository is private; state the choice rather than assuming. Safe to automate.

---

## D. Suspected findings requiring runtime verification

These are reasoned from the code and not proven during this read-only pass.

### D1. `avrana-backup.sh` has no lock against manual invocation
**Severity: MEDIUM · Confidence: MEDIUM**

`grep -n 'flock\|lockfile\|pidfile'` across `services/backups/` returns nothing. The systemd path is
genuinely safe, and `avrana-backup-trigger.service` reasons about it correctly: systemd will not run
two instances of a `Type=oneshot` unit, so the OliveTin trigger cannot race the 02:30 timer. That
comment is accurate.

The gap is invocation from a shell. Running `services/backups/avrana-backup.sh` directly, which the
setup documentation and any agent session will do, bypasses systemd entirely. Two concurrent runs
would each `docker exec pg_dump`, each write `LAST_RUN.json`, and each rotate. **Unverified:**
whether the rotation race can delete a directory the other run is still writing. The `.partial`
suffix and `grep -vi partial` appear to prevent the worst case, but this was not tested.

**Verification.** Run two instances against a throwaway `AVRANA_BACKUP_ROOT` and inspect the result.

### D2. `sqlite_backup` has no busy timeout
**Severity: LOW · Confidence: MEDIUM**

`avrana-backup.sh:41-52` opens the source `mode=ro` and calls `s.backup(d)` with Python's default
5-second timeout. Under a long write on a busy database this raises `OperationalError: database is
locked`, marking the component failed and the run `partial`. Not observed in the seven retained runs,
all of which are `ok`. **Verification.** Induce a long write on a copy and observe.

### D3. Home Assistant recorder failure is treated as fatal despite the comment
**Severity: LOW · Confidence: HIGH on the mismatch, MEDIUM on the impact**

`avrana-backup.sh:210-217`. The comment reads *"a missing recorder is degraded, not fatal"* and the
code then calls `fail home-assistant`, which makes the whole run `partial` and, via C8, feeds the
retention problem. Either the comment or the code is wrong. The config archive, which is the
irreplaceable part, has already succeeded at that point.

### D4. Sibling services on `authentik_frontend` could forge portal identity headers
**Severity: LOW · Confidence: HIGH on reachability, LOW on realistic risk**

`avrana-portal` correctly publishes no host port and was confirmed unreachable from the LAN
(`curl http://10.0.0.218:8095/` fails). It trusts `X-authentik-groups`. Reachability is not limited
to the outpost: `olivetin`, `avrana-kindle-connector`, `authentik-worker` and `authentik-ldap` share
that network and could set the header directly. All are first-party, so this is defence in depth
rather than a live risk. **Verification.** Confirm whether a dedicated portal network would break the
outpost's routing.

---

## E. Technical debt and maintainability

### E1. The legacy Kern Prime subsystem is dead, not idle
`api/`, `core/`, `auth/`, `main.py`, `filing_cabinet/`, `kern_calendar/`, `kern_sync/`, `scheduler/`,
`blackboxes/`, `avranos_gui/`, `utils/`, `config/`, `configs/`, `data/`. Roughly 2.4 MB.

Two independent structural blockers, both confirmed: `api/health.py` exports no `router` (now a
documented deliberate stub), and `main.py` builds `app` and exits without invoking uvicorn, so
`Restart=always` would loop even after the import is fixed. `avrana.service` is disabled. All four
remaining failed user units (`tag_all`, `lastfm_fetcher`, `summarize_lastfm`, `strava_fetch`) belong
to this tree.

This is the last large piece of accidental complexity, and it is cheap to resolve precisely because
nothing depends on it. Leaving it failing on a live schedule is the only option with no upside.

### E2. `komga` and `komf` compose files are gitignored and mirrored by hand
`.gitignore:55-57` ignores those directories wholesale. The live definitions are mirrored into
`deploy/compose/{komga,komf}.yml`, currently byte-identical, with nothing enforcing that. They are
the only two running services that fail rule 1 of `docs/service-deployment-checklist.md`, which the
repository itself calls a gate. A drift here is invisible until a restore uses the stale copy.

### E3. Four overlapping request services
Mylar3, Shelfmark, Omnibus and Shelfarr all accept requests and several write into shared inboxes.
BookStack records the duplicate-fetch risk. This is a product decision, not a bug, but it is
unresolved and each additional service widens it.

### E4. Test coverage is bimodal
The Audible connector is genuinely well tested: 11 test files including
`test_security.py`, which dumps the entire SQLite database and asserts a secret response URL appears
nowhere in it. That is real security testing rather than coverage theatre.

Against that, **the following have no tests at all**: `services/avrana-portal/portal.py` (780 lines,
the internet-facing front door, and the component enforcing group-based authorization),
`services/backups/avrana-backup.sh` (420 lines, the disaster-recovery path),
`scripts/services-health.sh`, `services/backups/offhost-sync.sh`, and every script in
`deploy/docker/`. There is no CI: no `.github/workflows`, no other runner configuration. Tests run
only when someone remembers, and the system Python has no `pytest` installed, so even the existing
suites need the connector's own `.venv`.

The highest-value missing test is a portal authorization test: given a set of
`X-authentik-groups`, assert exactly which tiles and routes are returned, and that a missing group
yields 404 rather than 403. That behaviour is security-relevant, pure-functional, and trivial to
test.

### E5. Health checks that prove liveness rather than function
11 of 13 `check_url` targets in `services-health.sh` are genuine application health endpoints
(`/ping`, `/actuator/health`, `/api/v1/status`). Two are bare root pages:
`calibre-web-automated` (`:8083/`) and `completeseries` (`:8085/`). Those prove a web server answers,
not that the library or the series index works. No Docker `HEALTHCHECK` in the estate was found to
be port-only or process-only, which is better than typical.

### E6. No alert transport
`services-health.sh` communicates purely through exit codes and stderr. A failure is visible only to
whoever reads the journal or the dashboard. Given C1 and C8 both depend on someone noticing a
degraded state within days, this is the amplifier behind several findings rather than a finding of
its own.

---

## F. Documentation and agent-context deficiencies

The root context layer established earlier today (`CLAUDE.md`, `AGENTS.md` symlink, `bin/bs`,
`docs/archive/`) covers the general case well and is not re-litigated here. Remaining gaps:

1. **BookStack page 8 asserts a restore test that currently fails.** It states *"restore-test.sh
   PASSED on that run"* for 2026-08-29T03-32-44Z, which was true, and does not record that the
   assertion has since gone stale. Anyone reading it concludes the restore path is proven. Highest
   documentation-correctness priority.

2. **BookStack page 36's Bazarr decision is not reflected in the compose file.** The wiki says mount
   only `movies` and `tv`; the staged stanza mounts the array root read-write. A future session
   following either source alone reaches a different and worse outcome.

3. **`services/media/` warrants the first service-level `CLAUDE.md`.** It is the one subsystem where
   a new session is most likely to cause an outage: the project name is `docker` rather than the
   directory name, Jellyfin needs `--profile media`, per-service config lives outside the repo at
   `/home/cody/docker/<name>/`, and the array-root mount plus tmpfs shadow looks wrong and is
   correct. The root `CLAUDE.md` names these; a local file is where the reasoning belongs.

4. **`services/backups/` warrants the second.** The rules that are non-obvious and expensive to
   rediscover (online `.backup` API only, allowlist not exclude-list, archive built inside the
   container when files are root-owned, never capture the connector's `profiles/`) are currently
   preserved only as comments inside a 420-line script.

5. **No machine-readable service inventory.** Every session re-derives the service list, ports and
   ownership by running `docker ps` and reading 24 compose files. A generated `services.json`
   (name, port, project, network, backup component, health endpoint, hardening status) would
   collapse a recurring several-thousand-token discovery into one read, and could be regenerated by
   a script rather than maintained by hand.

---

## G. Things that look strange but are intentionally correct

Do not "fix" these. Each is load-bearing and several have written rationale.

- **The \*arr mount the whole array read-write.** Narrowing to subdirectories silently downgrades
  every import from hardlink to full copy, because `link()` returns `EXDEV` across mounts. The
  `tmpfs` shadow over `/data/.backups` is the correct compensating control and was verified working:
  `docker exec radarr ls -A /data/.backups` is empty.
- **Compose project `docker` for `services/media/`.** Derived from the launch directory through the
  symlink `/home/cody/docker/docker-compose.yml`. Renaming it orphans five running containers.
- **Jellyfin behind `profiles: ["media"]`.** Confirmed: `docker compose config --services` omits it
  without the profile. Deliberate, and the reason services got orphaned during the 2026-08-29
  recovery.
- **The four Docker socket proxies.** All digest-pinned to the same image, socket mounted `:ro`,
  and minimally scoped. `olivetin-docker-restart` grants `POST=1 ALLOW_RESTARTS=1` with
  `CONTAINERS=0 EXEC=0 IMAGES=0 NETWORKS=0 VOLUMES=0 ALLOW_STOP=0 ALLOW_START=0`. This is the
  strongest control in the stack.
- **`avrana-portal` trusting `X-authentik-*` headers.** Sound, because the container publishes no
  host port and is unreachable from the LAN. Verified.
- **Control-plane services excluded from OliveTin's restart allowlist.** Restarting the thing that
  authenticates the button is how you lock yourself out.
- **`json_arr()` in the backup script.** Guards `printf` firing once with zero arguments, which
  would render `[""]` instead of `[]` and make a monitor count a phantom failure.
- **`emit()` building JSON through Python rather than `printf`.** A detail string containing a
  backslash produced invalid JSON, losing the failure reason exactly when it mattered.
- **The `mktemp` file in `offhost-sync.sh`'s verify step.** Comparing through `$( )` strips the
  trailing newline, so a byte-identical remote manifest would have compared as different and failed
  every run.
- **`backup_home_assistant` archiving inside the container.** A host-side `tar` as `cody` exits 2 on
  the root-owned `0600` auth store and ESPHome pairing keys while still producing a plausible
  archive.
- **`api/health.py` exporting no router.** A deliberate documented stub after the Health API
  retirement, not an oversight.
- **`.env` files at mode 664.** `/home/cody` is 750 and no other local user can traverse in.

---

## H. Top 10 remediation tasks, ordered by risk reduction

| # | Task | Severity | Effort | Automatable |
|---|---|---|---|---|
| 1 | Fix the stale `health_api.service` assertion in `restore-test.sh`, then run it against the newest backup and confirm PASS | HIGH | 10 min | yes |
| 2 | Narrow `avrana-imax-verify` to `/mnt/avrana_media/movies:/data/movies:ro`, or shadow `.backups` with tmpfs | HIGH | 20 min | yes |
| 3 | Rotate the Strava client secret; remove the literal from `kern_sync/strava/manual_exchange.py` | HIGH | 15 min | partly |
| 4 | Validate the Authentik and BookStack dumps structurally at write time; assert them in `restore-test.sh` | HIGH | 45 min | yes |
| 5 | Bring the staged Bazarr stanza in line with the documented decision before it can be started | HIGH | 20 min | yes |
| 6 | Add `/api/v3/health` checks for Radarr, Sonarr and Prowlarr to `services-health.sh` | MEDIUM | 30 min | yes |
| 7 | Schedule `restore-test.sh` weekly and surface its result through the health check | MEDIUM | 30 min | yes |
| 8 | Protect the newest `ok` run from rotation; fix the `daemon.json` silent copy failure | MEDIUM | 30 min | yes |
| 9 | Digest-pin bookstack, bookstack-mariadb and shelfmark | MEDIUM | 20 min | yes |
| 10 | Decide the legacy Kern Prime tree: delete, archive, or repair. Anything but leaving it failing | MEDIUM | 1-2 h | needs a decision |

Deliberately **not** in the top 10, with reasons: off-host backups remain the largest unrecoverable
risk but are blocked on a credential and already fully built; the firewall is staged and complete but
needs root and an explicit maintenance decision; the four-request-service overlap is a product
question, not an engineering defect.

---

## I. Suggested implementation batches

**Batch 1 — verification layer (no service impact, do first).**
Tasks 1, 4, 7. Nothing running is touched; only the scripts that check it. Finishing this batch
first means every later batch is validated by a restore test that actually runs. Verify with
`services/backups/restore-test.sh` returning PASS.

**Batch 2 — secrets and staged configuration (no running service touched).**
Tasks 3, 5. Both are edits to files that are either dead or not deployed. No container recreate.

**Batch 3 — container recreates (one short window).**
Tasks 2, 9. Both require recreating containers: `avrana-imax-verify`, `bookstack` plus
`bookstack-mariadb`, `shelfmark`. Pin digests to the images already running so the recreate is a
no-op in content. Run `deploy/docker/verify-baseline.sh` before and after. Do not combine with
Batch 4: if the baseline regresses, the cause should be unambiguous.

**Batch 4 — monitoring and retention.**
Tasks 6, 8. Script-only changes, but they alter what counts as a failure, so land them after the
container work has settled and the baseline is known good.

**Batch 5 — legacy decision (separate session).**
Task 10. Needs a decision from Cody before any code moves, and it touches roughly 2.4 MB across
thirteen directories. It should not share a session with operational changes.

**Sequencing note.** Batches 1 and 2 are safe to run back to back in a single session. Batch 3 wants
a deliberate window with time to verify. The off-host backup work, when the key arrives, slots
cleanly after Batch 1, since a working restore test is what makes an off-host copy meaningful.
