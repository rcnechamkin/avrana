# Second-Pass Adversarial Verification

**Date:** 2026-08-30 · **Subject:** `docs/audits/2026-08-30-forensic-audit.md`
**Method:** every CRITICAL/HIGH/MEDIUM finding re-derived from source, reproduced live where safe,
traced through Git history, and actively attacked. Findings that did not survive are dismissed
rather than softened.
**Mutations:** none. One throwaway container was created and destroyed by the project's own
`restore-test.sh`; one `eventType: Test` POST was sent to `avrana-imax-verify`, which by design
queues nothing. No code, configuration, service, documentation or the original report was changed.

---

## Headline

Six of the ten original findings survive. Three are downgraded, one materially. Two of my own
claims were falsified by evidence, and one of those was a claim about the codebase being *worse*
than it is. Against that, verification surfaced **one new HIGH finding that is more serious than
anything in the first report**: the nightly backup does not capture the bare-metal tier's
configuration, and two secret files sit in a glob blind spot, existing only on the disk the backup
exists to survive.

The single most useful result: `restore-test.sh` was executed. It passes fourteen assertions
including booting a real Audiobookshelf, and fails exactly one. The first report's claim that "the
restore path is unproven for the last two nightlies" was **too strong and is retracted**. The
backup is demonstrably recoverable; the test's exit code is wrong.

---

## A. Findings CONFIRMED

### C1. `restore-test.sh` fails on one stale assertion — CONFIRMED, impact claim retracted
**Severity: HIGH (process) · Data-loss risk: LOW · Confidence: HIGH**

**Reproduced.** The script was run end to end against the newest backup:

```
PASS  manifest checksums verified
PASS  restored DB has 293 library items and 8 users
PASS  throwaway ABS booted and is healthy
PASS  server reports isInit=true
PASS  radarr db integrity ok (QualityProfiles=10, CustomFormats=70, Movies=62)
PASS  sonarr db integrity ok (QualityProfiles=10, Series=12)
PASS  prowlarr db integrity ok (Indexers=2)
PASS  home-assistant archive carries auth store, registries and ESPHome keys (680 entries)
PASS  home-assistant recorder integrity ok (states=7216)
PASS  tracearr pg_dump complete and well-formed (961 tables)
FAIL  systemd: user/health_api.service missing from backup
EXIT=1
```

**Falsification attempt succeeded, partially.** The first report implied broader rot. Each of the
other assertions was independently re-derived against the newest backup and all pass. This is
**exactly one** stale assertion, not a pattern of decay.

**Git history.** `4b87668` added the assertion at 2026-08-28 20:07. `68d8e92` retired the Health
API at 2026-08-28 21:00, **53 minutes later, in the same working session**. At 21:25 `a149a69`
removed the corresponding reference from `services-health.sh`. The author remembered one consumer
and missed the other.

**Revised impact.** The data is recoverable; this was proven, not assumed. The risk is process: a
verification gate that always returns 1 gets ignored or bypassed, and
`docs/service-deployment-checklist.md` §2 instructs every future service to add an assertion to a
script that already fails. Severity stays HIGH for that reason, and only that reason.

---

### C2. `avrana-imax-verify` array-root mount — CONFIRMED and ESCALATED
**Severity: HIGH · Confidence: HIGH**

**Escalated on evidence.** The first report described the nightly `avrana/` tree. The mount actually
exposes the whole of `/mnt/avrana_media/.backups`, which also holds ad-hoc operational snapshots.
Enumerated from inside the running container: **477 files**, including

- `credrotate-20260818T023938Z-smtp2go.env` (an SMTP credential file)
- `offboard-test-accounts-.../authentik.pgdump.zst` and
  `authentik-pre-verified-enrollment-.../authentik.pgdump.zst` (two further full identity dumps)
- `cwa-pre-smtp2go-.../app.db` (Calibre-Web users)
- `seerr-pre-profile-change-.../db.sqlite3`, `jellyfin-users.json`, `abs-users.json`
- the nightly `cloudflared-config.tar.zst` (tunnel credentials) and `arr/*/config.xml`

`config.xml` is written `0600` specifically to protect the API key; the container runs as uid 1000,
the same uid that owns it, so the mode is inert. Verified by reading the file from inside the
container.

**Git history establishes the root cause.** `e2fa7de` added the `tmpfs` shadow to the \*arr on
2026-08-16 10:36, explicitly to keep the backup tree out of media containers. `cc86382` added
`avrana-imax-verify` with `/mnt/avrana_media:/data:ro` on 2026-08-18 13:13, **two days later**.

**A first-report claim is DISMISSED here.** The original said the deployment checklist does not
prevent recurrence. It does: `docs/service-deployment-checklist.md:77-80` reads *"**Never mount the
array root** (`/mnt/avrana_media`) into a new service. It exposes `.backups` ..."* with the \*arr
exception documented. The correct root cause is narrower and more useful: **the gate was written on
2026-08-28, ten days after the offending service landed, and was never applied retroactively to
existing services.**

**Minimum required scope, determined precisely.** Radarr's only root folder is `/data/movies`
(queried live). `server.py` consumes `movieFile.path` from the Radarr webhook, and there is no
Sonarr integration (`grep -c SONARR` returns 0). Therefore
`- /mnt/avrana_media/movies:/data/movies:ro` preserves the documented path-identity rationale
exactly while removing the entire exposure. No `tmpfs` shadow is needed.

---

### C5. Staged Bazarr configuration — CONFIRMED, correctly bounded as latent
**Severity: HIGH if deployed · Confidence: HIGH**

Verified: no `bazarr` container exists (`docker ps -a` count 0) and
`docker compose config --services` from `/home/cody/docker` does not list it. It cannot start
without an explicit `--profile optional`. The stanza mounts `/mnt/avrana_media:/data` **read-write**
with no `cap_drop`, `security_opt`, `read_only`, `mem_limit`, `pids_limit` or image tag, while every
sibling in the same file has all of them.

**The drift is the finding.** BookStack page 36 records the correct decision (mount only `movies`
and `tv`). The compose file records the wrong one. A session following the wiki fixes it; a session
following the repo does not. Given `CLAUDE.md` names the repo as more authoritative than BookStack
for current state, the repo will usually win.

---

### C6. \*arr health monitoring — CONFIRMED, and it generalises (see N3)
**Severity: MEDIUM · Confidence: HIGH**

Re-verified that nothing else compensates: `deploy/homepage/config/services.yaml` has `siteMonitor`
entries for Jellyfin, Tracearr, ABS and Komga but **none** for Radarr, Sonarr or Prowlarr;
`services/olivetin/scripts/avrana-health.sh` checks Jellyfin and ABS only. `/ping` returns
`{"status": "OK"}` on all three while `/api/v3/health` is the endpoint carrying indexer,
download-client and root-folder faults.

**Beyond the known incident,** `/api/v3/health` is also where a read-only or missing root folder and
an unreachable download client surface. Both are live scenarios here: the array is a USB spinning
disk, and SABnzbd is bare-metal (confirmed configured as Radarr's download client at
`10.0.0.218`). `/ping` stays green through all of them.

---

### C8. Retention is status-blind — CONFIRMED
**Severity: MEDIUM · Confidence: HIGH**

`avrana-backup.sh:406` sorts by name and keeps the newest `KEEP` with no reference to `status`, and
`mv "$PARTIAL" "$DEST"` at line 400 promotes a degraded run unconditionally. Seven consecutive
`partial` runs would rotate out the last good copy.

**Mitigation found, and it is weaker than it looks.** `services-health.sh` fails on any non-`ok`
`LAST_RUN.json` every fifteen minutes, so this is loud. But there is no alert transport: the signal
is an exit code and a line on stderr. Detection depends on a human reading the journal within seven
days. Severity held at MEDIUM because of that dependency, not lowered because of the check.

---

### C9. Unpinned upstream images — CONFIRMED, and it violates the repo's own gate
**Severity: MEDIUM · Confidence: HIGH**

Three running services on mutable tags: `lscr.io/linuxserver/bookstack:26.05.3`,
`lscr.io/linuxserver/mariadb:11.8.8`, `ghcr.io/calibrain/shelfmark:1.3.6`. Two non-running on
`:latest` or untagged: `kavita`, `bazarr`. Locally built images were correctly excluded.

**Reinforcement:** `docs/service-deployment-checklist.md` §4 is titled *"Image pinning — REQUIRED"*.
These are not merely below best practice; they fail the repository's own stated gate. MariaDB is the
one that converts a silent tag rebuild into a restore event.

---

## B. Findings DOWNGRADED

### C3. Authentik / BookStack dump validation — HIGH → LOW, with a MEDIUM residue
**Falsified by experiment.**

The first report claimed a truncated dump would be reported as good because only `[[ -s ]]` is
checked. That ignores `set -uo pipefail` at line 20. Tested directly, reproducing the exact
construct:

```
sh -c "echo partial-content; exit 1" | zstd -o t.zst && [[ -s t.zst ]]
RESULT: reported FAIL (pipefail caught it)      # file existed, 29 bytes, still failed
```

So every realistic truncation path is already caught: a dying container, a broken `docker exec`, a
failing `zstd`, a full disk. The current dump was also validated directly: completion marker
present, 215 `CREATE TABLE` statements.

**Residual finding, downgraded to MEDIUM:** Authentik and BookStack still have **no restore-test
assertion at all**. The exposure is now narrow, a `pg_dump` that exits 0 while producing
structurally valid but content-poor output, but Authentik remains the most consequential artifact in
the tree and the only large one with no verification. The remediation is unchanged; the urgency is
not what was claimed.

### C4. Committed Strava credential — HIGH → MEDIUM
Confirmed present and on `origin/main`. Three mitigating facts established:

- The GitHub API returns **404** unauthenticated, which is how GitHub reports a private repository
  to an anonymous caller. Not publicly readable.
- `manual_exchange.py` is referenced by **nothing**. `strava_fetch.service` runs
  `fetch_activities.py`, a different file.
- `kern_secrets/strava.json` is **0 bytes**, so the exchange never completed and the integration is
  non-functional. `kern_secrets/` is gitignored.

Rotation is still required, because a secret in Git history is permanent and the client secret does
not expire on its own. It is not urgent.

### C7. `daemon.json` silently absent from the backup — MEDIUM → LOW
Two falsifying facts. BookStack page 8's component table does **not** claim `daemon.json` is
captured, so no documentation is wrong. And the content is recorded in seven other tracked
locations, including `deploy/docker/daemon.json.proposed`, `deploy/docker/README.md`,
`deploy/docker/ADDRESS-POOLS.md` and `CLAUDE.md`. Loss is fully recoverable.

What survives is a code-quality issue: `backup_systemd`'s success criterion is `(( n > 0 ))` counting
unit files only, so the component reports `good` while silently dropping non-unit artifacts. That is
the same silent-success class the script already fixed for `backup_omnibus` and the Home Assistant
archive. Worth fixing as robustness, not as disaster recovery.

### D2. `sqlite_backup` busy timeout — reclassified to informational
No occurrence in any of the seven retained runs, all `ok`. Retained as a note, not a finding.

---

## C. Findings DISMISSED

1. **"The deployment checklist does not prevent the array-root mount recurring."** False. §5 lines
   77-80 state the rule explicitly and document the \*arr exception. The real problem is retroactive
   application, which is a different and more tractable task. Dismissed as written.

2. **"The staged firewall may still open the retired port 8240."** Falsified.
   `deploy/ufw/rules-input.sh:51` reads `# Health API 8240 : retired 2026-08-28. No rule.` and
   `deploy/ufw/README.md:71` lists it under Retired. The firewall author completed that cleanup
   correctly. Dismissed.

3. **"`services/calibre-web-automated/docker-compose.yml` references the retired 8240."** It is a
   comment listing historically occupied ports, to justify choosing 8083. Harmless. Dismissed.

4. **"The restore path is unproven for the last two nightlies."** Directly falsified by running the
   test: fourteen assertions pass, including a real ABS boot from restored bytes. Retracted.

---

## D. Newly discovered findings

### N1. The bare-metal tier's configuration is not backed up, and two secrets sit in a glob blind spot
**Severity: HIGH · Confidence: HIGH · Automatable: YES**

This is the most serious finding in either report. It was missed the first time because the audit
read the backup script's component list rather than asking what a rebuild actually needs.

**Not captured anywhere in the nightly backup:**

| Artifact | Holds | Only copy lives on |
|---|---|---|
| `~/.sabnzbd/sabnzbd.ini` | SABnzbd's API key (referenced by Radarr, Sonarr, Prowlarr and Shelfmark), the LAN credentials set on 2026-08-28, **Usenet provider server credentials**, categories, post-processing wiring | root LV |
| `services/mylar3/config.ini` | mylar3 configuration, inside the fully gitignored `services/mylar3/` | root LV |
| `services/bare-metal-auth.env` | the SABnzbd and mylar3 login credentials | root LV |
| `services/smtp2go.env` | SMTP credentials | root LV |

**The glob blind spot, verified.** `backup_stack_config` enumerates
`"$REPO"/services/*/.env` and `"$REPO"/services/*/*.env`. Both require a directory level.
`services/bare-metal-auth.env` and `services/smtp2go.env` sit at `services/<file>`, one level up, so
**neither pattern matches**. Confirmed against the live archive:

```
$ tar -tf stack-config.tar.zst | grep -E '^services/[^/]+\.env$'
  (no output)
```

Both files are mode 600 and exist only on the root LV. The only `sabnzbd.ini` anywhere on the array
is `sec-remediation-20260820T071153Z/sabnzbd.ini.PRE`, a pre-change snapshot from 2026-08-20 that
predates both the authentication change and the 8080 to 8082 move.

**Failure scenario (this is the "host dies" simulation, and it fails).** The root LV is lost. Every
container is rebuilt correctly from the backup. SABnzbd starts with no configuration: no API key, so
all four consumers break; no Usenet server credentials, so nothing can download at all. The stack
comes back looking healthy and cannot acquire a single file. The Usenet provider credentials may
exist nowhere else.

**Remediation.** Add `"$REPO"/services/*.env` to the allowlist, and add a `backup_baremetal()`
capturing `~/.sabnzbd/sabnzbd.ini` and `services/mylar3/config.ini` at 0600, with a restore-test
assertion. Safe to automate.

### N2. `avrana-imax-verify` accepts unauthenticated jobs with an attacker-controlled path
**Severity: MEDIUM-HIGH · Confidence: HIGH · Automatable: YES**

`server.py` has no authentication of any kind. Confirmed live from the LAN:

```
$ curl -X POST -d '{"eventType":"Test"}' http://10.0.0.218:8099/
{"status": "ok", "message": "avrana-imax-verify reachable"}
```

The `Download` path takes `movieFile.path` **verbatim** from the request body with no normalisation
and no confinement to `/data/movies`, then queues it for `iv.verify()`, which runs ffprobe and
ffmpeg against it. The only gate, `matched_imax(payload)`, reads `customFormats` **from the same
attacker-supplied payload** and is passed by sending `[{"name":"IMAX"}]`. There is no verification
against Radarr.

The exploit chain was **not executed**; this is derived from source, and the `Test` event above
proves only that unauthenticated POSTs are accepted.

**Honest bounding of impact.** The attacker controls the *path*, not the file *content*, and ffprobe
does not return file contents, so this is not a read primitive for the backup tree. What it is: an
unauthenticated file-existence oracle (results are exposed on the unauthenticated `GET /history` and
`/results`), a bounded CPU denial of service, and an ffmpeg parsing surface reachable by any LAN
device against any path on a 7.3 TB array. ufw is inert, so "LAN device" means every device.

**Its real significance is compositional.** It lowers the precondition for C2 from "compromise the
container" to "reach port 8099". Narrowing the mount per C2 also collapses this finding's reach.

### N3. Bare-metal services are absent from the scheduled health check
**Severity: MEDIUM · Confidence: HIGH · Automatable: YES**

`grep -c 'sabnzbd\|8082' scripts/services-health.sh` returns 0. SABnzbd and mylar3 appear only in
`deploy/docker/verify-baseline.sh`, which is manual. The 15-minute timer probes thirteen container
URLs and no bare-metal listener.

`systemctl --failed` is checked, so a service that *crashes* is caught. A service that is `active`
but wedged and not serving is invisible. For SABnzbd, the single download path for the entire stack,
that is the difference between a fifteen-minute detection and noticing that nothing has imported for
a week. This is the same root cause as C6 and generalises it.

### N4. Documentation, including `CLAUDE.md`, understates the indexer count
**Severity: LOW · Confidence: HIGH**

`restore-test.sh` reported `prowlarr Indexers=2`. Confirmed live: **NZBFinder and NZBgeek**, both
enabled, both Usenet. `CLAUDE.md` (written earlier today), BookStack and the archived audit all say
there is exactly one indexer, NZBgeek, and the roadmap still lists "a second indexer" as open work
that is in fact done.

This is a self-inflicted error worth recording plainly: the context file was populated from the
archived audit rather than from the live API on this specific point, which is the exact failure mode
`CLAUDE.md` itself warns about.

### N5. `docs/services-operations.md` describes retired infrastructure as running
**Severity: LOW · Confidence: HIGH**

Lines 21 and 27-28 state the `health.avrana.media` connector runs and give instructions to disable
`cloudflared-health.service`. Both were retired on 2026-08-28. This file is in `docs/`, not
`docs/archive/`, so it reads as current.

### N6. There is a deployment checklist and no retirement checklist
**Severity: MEDIUM (process) · Confidence: HIGH**

`docs/service-deployment-checklist.md` has eight REQUIRED sections for adding a service. Nothing
covers removing one. The Health API retirement had to touch `services-health.sh` (done),
`restore-test.sh` (missed, C1), `deploy/ufw/` (done correctly), and `docs/services-operations.md`
(missed, N5). Two of four consumers were updated. This is the root cause of C1 and N5 and will
recur on the next retirement, of which Plex and nginx are already queued.

---

## E. Shared and root causes

Ten findings reduce to five causes. Remediating the causes is cheaper than remediating the findings.

| # | Root cause | Findings |
|---|---|---|
| **RC1** | **Hardening gates were written after the services they govern and never applied retroactively.** The checklist post-dates `avrana-imax-verify` by ten days and Bookstack/Shelfmark by longer. | C2, C5, C9 |
| **RC2** | **No retirement counterpart to the deployment checklist.** Adding is gated; removing is freehand. | C1, N5 |
| **RC3** | **Allowlists carry unstated depth and path assumptions.** `services/*/*.env` silently excludes `services/*.env`; `backup_systemd`'s `n > 0` counts only unit files; the backup's mental model is "containers" so the bare-metal tier fell outside it. | N1, C7 |
| **RC4** | **Monitoring models the container estate, not the host.** Everything scheduled probes containers; bare-metal and application-level health live only in manual scripts. | C6, N3 |
| **RC5** | **No alert transport.** Every check ends at an exit code. Several findings are only tolerable if a human reads the journal within days. | amplifies C1, C8 |

RC1 and RC3 are the two worth fixing structurally. A single "audit existing services against the
current checklist" pass closes C2, C5 and C9 together and prevents the next instance.

---

## F. Defenses that must be preserved

Verified during this pass, and all of them are load-bearing. Remediation must not weaken them.

- **The \*arr whole-array mount plus `tmpfs` shadow over `/data/.backups`.** Re-verified empty from
  inside `radarr` and `sonarr`. Narrowing `/data` to subdirectories would silently downgrade every
  import from hardlink to copy via `EXDEV`. **Fixing C2 must not tempt anyone to "make the \*arr
  consistent with imax-verify".** The two need opposite treatments for good reasons.
- **`set -uo pipefail` in the backup script.** It is doing more work than the first report credited,
  and is the reason C3 was downgraded. Any refactor that splits those pipelines into separate steps
  must preserve the failure propagation.
- **The four Docker socket proxies.** Re-read: all digest-pinned to one image, socket `:ro`, and
  `olivetin-docker-restart` grants `POST=1 ALLOW_RESTARTS=1` with `CONTAINERS=0 EXEC=0 IMAGES=0
  NETWORKS=0 VOLUMES=0 ALLOW_STOP=0 ALLOW_START=0`.
- **`avrana-portal` publishing no host port.** Its trust in `X-authentik-*` headers is sound *only*
  because of this. Verified unreachable from the LAN. Never add a port mapping for convenience.
- **`restore-test.sh` booting a real Audiobookshelf.** The one assertion that catches faults no
  static check would. Fix the stale line; do not simplify the test.
- **`backup_home_assistant` archiving inside the container**, and the `0600` handling for
  `config.xml`, `bookstack.env`, `omnibus.env` and the Shelfarr keys. Note that `0600` is *not* a
  control against a container sharing uid 1000; it is still correct against other local users.
- **`json_arr()`'s empty-array guard and `emit()`'s Python-built JSON.** Both fix real past bugs.
- **The `.partial` suffix plus `grep -vi partial` in rotation.** This is what prevents an
  in-progress run being pruned. Any rotation change for C8 must keep it.
- **`avrana-backup-trigger.service`'s reasoning about systemd serialisation.** Verified correct:
  systemd will not run two instances of the oneshot unit, so the OliveTin trigger genuinely cannot
  race the timer. Do not add a lock believing it is broken; add one only for the *manual shell
  invocation* path.

---

## G. Revised remediation priority

| # | Task | Severity | Cause | Automatable |
|---|---|---|---|---|
| 1 | Capture the bare-metal tier: add `services/*.env` to the allowlist, add `sabnzbd.ini` and mylar3 `config.ini`, assert them in restore-test | HIGH | RC3 | yes |
| 2 | Narrow `avrana-imax-verify` to `/mnt/avrana_media/movies:/data/movies:ro` | HIGH | RC1 | yes |
| 3 | Delete the `user/health_api.service` assertion; confirm restore-test returns 0 | HIGH | RC2 | yes |
| 4 | Bind `avrana-imax-verify` to loopback or add a shared-secret header; confine `movieFile.path` to `/data/movies` | MED-HIGH | — | yes |
| 5 | Bring the Bazarr stanza in line with BookStack page 36 before it can ever start | HIGH-latent | RC1 | yes |
| 6 | Add `/api/v3/health` for the three \*arr, and SABnzbd plus mylar3 probes, to `services-health.sh` | MEDIUM | RC4 | yes |
| 7 | Schedule `restore-test.sh` weekly and surface its result | MEDIUM | RC5 | yes |
| 8 | Protect the newest `ok` run from rotation | MEDIUM | RC5 | yes |
| 9 | Digest-pin bookstack, bookstack-mariadb, shelfmark | MEDIUM | RC1 | yes |
| 10 | Add restore-test assertions for the Authentik and BookStack dumps | MEDIUM | RC3 | yes |
| 11 | Rotate the Strava secret; delete `manual_exchange.py` | MEDIUM | — | partly |
| 12 | Write a retirement checklist; fix `docs/services-operations.md` and the indexer count in `CLAUDE.md` | MEDIUM | RC2 | yes |

Dropped from the priority list: `daemon.json` (C7, now LOW, fold into task 1's robustness fix) and
the `cloudflared-linux-amd64.deb` removal (cosmetic).

---

## H. Safest batch ordering

**Batch 1 — restore the verification gate. Do this first, alone.**
Tasks 3, then 1, then 10, then 7. Fixing the stale assertion first means every later batch can be
validated by a test that returns 0. Task 1 changes what the backup captures, so it must be followed
by a real backup run into a throwaway `AVRANA_BACKUP_ROOT` and a restore-test against that run, not
against production. **Exit criterion:** `restore-test.sh` exits 0 and the new artifacts are asserted.

**Batch 2 — close the imax exposure. One container recreate.**
Tasks 2 and 4 together, because both touch the same service and a single recreate covers them.
Verify by re-running the enumeration from inside the container and confirming `/data/.backups` no
longer resolves, and that a webhook from Radarr still verifies a real import.
**Do not** touch the \*arr mounts in this batch, or in any batch.

**Batch 3 — configuration only, nothing running changes.**
Tasks 5, 11, 12. Bazarr is not deployed, `manual_exchange.py` is referenced by nothing, and the docs
changes are inert. Safe to combine.

**Batch 4 — monitoring and retention.**
Tasks 6 and 8. These change what counts as a failure, so land them only after Batches 1 and 2 have
settled and the baseline is known green. Expect task 6 to surface genuine pre-existing faults on
first run; that is the check working.

**Batch 5 — image pinning. Its own window.**
Task 9. Pin to the digests of the images already running so the recreate is a content no-op. Handle
`bookstack-mariadb` last and separately: it is the one where a wrong digest is a restore event.
Run `deploy/docker/verify-baseline.sh` before and after.

---

## I. Immediate versus deliberately deferred

**Fix immediately (this session or the next):**

- **Task 3**, the one-line stale assertion. Ten minutes, zero risk, and it restores the gate that
  makes every other change verifiable.
- **Task 1**, the bare-metal backup gap. This is the only finding in either report where the current
  state means a real disaster is unrecoverable, and the Usenet provider credentials may exist
  nowhere else on Earth. It does not require touching any running service.
- **Task 2**, narrowing the imax mount. One container recreate, and it closes the largest
  confidentiality exposure plus most of N2's reach.

**Deliberately defer:**

- **Task 11 (Strava).** Real, but the repository is private, the code path is dead and the token
  store is empty. Batch it with other housekeeping rather than interrupting for it.
- **Task 9 (image pinning).** Correct, but changing image references is exactly the class of work
  that caused the 2026-08-29 outage. It wants a deliberate window, not a slot at the end of another
  batch.
- **Task 6's SABnzbd probe**, if it is likely to surface long-standing faults, should land when
  someone has time to triage what it finds rather than immediately before a quiet period.
- **The legacy Kern Prime decision** from the first report. Unchanged in urgency, still needs a
  decision from Cody, still should not share a session with operational work.

**Explicitly not remediation, and unchanged by this pass:** off-host backups remain blocked on a
credential, and the firewall remains staged, complete and needing root. Neither is affected by
anything above, except that **task 1 should land before the first off-host sync**, so that the first
copy to leave the building actually contains the bare-metal tier.
