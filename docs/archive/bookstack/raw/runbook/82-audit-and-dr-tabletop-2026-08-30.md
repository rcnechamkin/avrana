---
bookstack_page_id: 82
title: "Audit and DR tabletop, 2026-08-30"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-08-31 00:49:01
updated: 2026-08-31 00:49:02
last_editor: "Cody"
revisions: 1
tags: []
source_format: markdown
classification: DUPLICATE
destination: "docs/audits/2026-08-30-disaster-recovery-tabletop.md, docs/audits/2026-08-30-forensic-audit.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-31; exported 2026-10-04. Classified DUPLICATE; current information is in `docs/audits/2026-08-30-disaster-recovery-tabletop.md, docs/audits/2026-08-30-forensic-audit.md`. Wiki summary of the audits kept in Git.

# Audit and DR tabletop, 2026-08-30
# Audit and DR tabletop, 2026-08-30

Three linked exercises run on 2026-08-30: a forensic audit, an adversarial verification of that
audit, and a disaster-recovery tabletop. This page is the summary and the index.

**The full reports live in Git, not here, and that is deliberate.** BookStack is itself a restored
component, so recovery instructions must be readable when no infrastructure is running.

| Report | Path in the repo |
|---|---|
| Forensic audit | `docs/audits/2026-08-30-forensic-audit.md` |
| Adversarial verification | `docs/audits/2026-08-30-forensic-audit-verification.md` |
| Disaster-recovery tabletop | `docs/audits/2026-08-30-disaster-recovery-tabletop.md` |

Related: *Security audit, 2026-08-20* (page 69), *Incident 2026-08-29* (page 80), *Known Issues*
(page 35), *Backups and Recovery* (page 8).

## Verdict in one paragraph

The container estate and the backup subsystem are well engineered, and several things that look
wrong are load-bearing defences. The problems cluster in three places: the verification layer
stopped verifying, a documented defence has already regressed, and the failure mode that caused the
last outage has no detection. The disaster-recovery position is worse than the backup dashboard
suggests, because the bare-metal tier and several service encryption keys are not captured at all.

## Confirmed findings

| ID | Finding | Severity |
|---|---|---|
| C1 | `restore-test.sh` fails on one stale assertion (`user/health_api.service`, retired 2026-08-28). Nothing schedules the test, so nothing noticed. | HIGH (process) |
| C2 | `avrana-imax-verify` mounts the array root and can read **477 files** under `.backups`, including the cloudflared tunnel credentials, three Authentik dumps, an SMTP credential file and the `*arr` `config.xml`. | HIGH |
| N1 | The nightly backup does not capture the bare-metal tier: `~/.sabnzbd/sabnzbd.ini`, `services/mylar3/config.ini`, and (via a glob depth bug) `services/bare-metal-auth.env` and `services/smtp2go.env`. | HIGH |
| C5 | The staged Bazarr stanza mounts the array root **read-write**, unhardened and untagged, contradicting the decision recorded on page 36. Latent: it cannot start without `--profile optional`. | HIGH if deployed |
| N2 | `avrana-imax-verify` has no authentication. `movieFile.path` is taken verbatim from an unauthenticated POST, and the only gate reads `customFormats` from the same attacker-supplied body. | MEDIUM-HIGH |
| C6 | `/ping` is the only `*arr` check. `/api/v3/health`, which carries indexer, download-client and root-folder faults, is polled by nothing. | MEDIUM |
| N3 | SABnzbd and mylar3 are absent from the 15-minute health check. They appear only in the manual `verify-baseline.sh`. | MEDIUM |
| C8 | Backup retention sorts by name and ignores `status`, so seven consecutive `partial` runs rotate away the last good one. | MEDIUM |
| C9 | Three running services are on mutable tags: `bookstack:26.05.3`, `mariadb:11.8.8`, `shelfmark:1.3.6`. This fails the repository's own deployment checklist section 4. | MEDIUM |
| N6 | There is a deployment checklist and no retirement checklist. The Health API retirement updated two of four consumers. | MEDIUM (process) |

### Two evidence notes worth keeping

**The `0600` mode on `config.xml` is inert against a container sharing uid 1000.** The backup script
writes `arr/*/config.xml` at 0600 to protect the API key. `avrana-imax-verify` runs as uid 1000, the
same uid that owns the file, and was observed reading it. File modes are not a control against a
container that shares the uid; only the mount scope is.

**Root cause of C2, established from Git history.** The `tmpfs` shadow that keeps the backup tree out
of media containers was added on 2026-08-16 (`e2fa7de`). `avrana-imax-verify` was added on
2026-08-18 (`cc86382`) with the array root and no shadow. The deployment checklist that forbids this
was written on 2026-08-28, ten days later, and was never applied retroactively to existing services.

## Findings downgraded or dismissed on second pass

Recorded so they are not re-raised.

- **Authentik and BookStack dump integrity: downgraded HIGH to LOW.** The first audit claimed a
  truncated dump would be reported as good. That ignored `set -uo pipefail`, which was tested
  directly and does catch it, even when bytes were already written. The residue is that neither dump
  has a restore-test assertion, which stays MEDIUM.
- **Committed Strava credential: downgraded HIGH to MEDIUM.** Real and present on `origin/main`, but
  the GitHub repository is not publicly readable, `manual_exchange.py` is referenced by nothing, and
  `kern_secrets/strava.json` is 0 bytes. Rotation is still required; urgency is not.
- **`daemon.json` missing from the backup: downgraded MEDIUM to LOW.** Page 8 does not claim it is
  captured, and its content is recorded in seven other tracked locations.
- **DISMISSED: "the deployment checklist does not prevent the array-root mount recurring."** It does,
  at section 5. The real problem is retroactive application.
- **DISMISSED: "the staged firewall still opens the retired port 8240."** `deploy/ufw/rules-input.sh`
  explicitly records the retirement and creates no rule.
- **RETRACTED: "the restore path is unproven."** `restore-test.sh` was executed. It passes fourteen
  assertions including booting a real Audiobookshelf from restored bytes, and fails exactly one. The
  backups are recoverable; the test's exit code is wrong.

## Correction to this wiki and to CLAUDE.md

**There are two indexers, not one.** Prowlarr holds **NZBgeek and NZBFinder**, both enabled, both
Usenet, confirmed against the live API. Page 35, page 36 and the repository `CLAUDE.md` all still say
there is exactly one, and the roadmap still lists "a second indexer" as open work that is in fact
done. Any conclusion of the form "no English version exists" now means "not on either of two
indexers", which is a materially different claim.

Also stale: `docs/services-operations.md` still describes the `health.avrana.media` connector as
running and gives instructions to disable `cloudflared-health.service`. Both were retired
2026-08-28.

## Disaster recovery

Two scenarios were traced from a blank Linux machine, following dependencies rather than judging
services in isolation.

**Scenario A, disaster today, before any off-host sync has ever run.** There is no off-host copy of
anything. Recovery starts at "clone Git", and everything not in Git is gone: Authentik's entire
identity store, all watch, listening and read progress, 70 custom formats, every service secret, the
tunnel identity, and this wiki. Verdict: **catastrophic, partial reconstruction.** Days to a
structurally similar stack; never to the same one.

**Scenario B, after the bare-metal gap and the restore-test assertion are fixed and one verified
backup has reached the remote.** Substantially recoverable. Identity, all media-service state, the
automation configuration, the tunnel and the systemd layer all return. That is the difference
between catastrophe and a long weekend.

### What Scenario B still would not capture

These were found on disk and are covered by neither the current backup nor the proposed fix:

| Artifact | Consequence if lost |
|---|---|
| `services/libation/config/libation-master.key` | Its own `NOTICE.txt`: *"It will not decrypt tokens encrypted under a different machine's key."* Audible must be re-authenticated. |
| `services/libation/config/AccountsSettings.json`, `LibationContext.db` | Audible account binding and the download ledger |
| `services/calibre-web-automated/config/.key` | Fernet key for the SMTP password inside `app.db`; Send-to-Kindle must be reconfigured |
| `services/shelfmark/config/users.db`, `settings.json`, `.flask_secret` | Every Shelfmark user account |
| `services/komf/application.yml` | The Komga admin password, in a fully gitignored directory |
| `services/mylar3/mylar.db` | The comic database |

Twelve running services have no backup component. Nine are genuinely stateless. Three are not:
**shelfmark**, **libation** and **komf**.

### The single highest-stakes item in the whole plan

Reading the off-host backup requires `rclone.conf`, which holds the object-store credentials **and**
the two crypt passwords. That file is correctly excluded from the backup, because putting the
decryption key inside the encrypted archive would defeat it. The Backblaze account survives a
disaster and a new key can be issued. **The two crypt passwords exist only in a password manager.**

`offhost-setup.md` mandates storing them. Nothing in the system verifies it was done. If they cannot
be produced, Scenario B collapses into Scenario A with extra steps.

### Media

Media is deliberately not backed up, and is lost in both scenarios. That decision is sound, but the
consequence should be stated plainly in any recovery estimate: movies and TV are re-acquirable
subject to Usenet retention, audiobooks only after re-authenticating to Audible, and **comics
(roughly 134 GB) and ebooks are not systematically re-obtainable.** Mylar3's only download path is
already documented as dead.

## False-green traps

Each of these leaves `services-health.sh` fully green, because eleven of its thirteen checks are
liveness endpoints and two are bare root pages.

- SABnzbd configuration not restored: searches succeed, nothing ever downloads.
- Indexer backoff after an outage: containers healthy, Sonarr dark for hours.
- Authentik restored against `.env` files from a different run: every SSO login fails at the token
  exchange.
- Calibre-Web restored without `.key`: fails at send time only.
- Libation restored without its master key: runs, downloads nothing.
- Komga healthy with the mergerfs union unmounted: libraries empty, and an empty read list pegs a
  CPU core.
- Array mounted read-only: every container healthy, imports failing.

Adding `/api/v3/health` for the three `*arr` and a real SABnzbd probe removes four of these at once.

## Defences that must not be removed during cleanup

- The `*arr` whole-array mount plus the `tmpfs` shadow over `/data/.backups`. Narrowing `/data` to
  subdirectories silently downgrades every import from hardlink to copy through `EXDEV`. Fixing C2
  must not tempt anyone to make the `*arr` consistent with `avrana-imax-verify`; the two need
  opposite treatments.
- `set -uo pipefail` in the backup script. It is the reason the Authentik finding was downgraded.
- The four Docker socket proxies, all digest-pinned, socket read-only, minimally scoped.
- `avrana-portal` publishing no host port. Its trust in `X-authentik-*` headers is sound only
  because of that.
- `restore-test.sh` booting a real Audiobookshelf. Fix the stale line; do not simplify the test.
- The `.partial` suffix and `grep -vi partial` in rotation, which prevent an in-progress run being
  pruned.

## Remediation order

Nothing has been remediated. The batches below are ordered by risk reduction, not ease.

1. **Restore the verification gate.** Remove the stale `health_api.service` assertion; extend the
   backup to cover the bare-metal tier **and** the six artifacts listed above; add restore-test
   assertions for all of them plus the Authentik and BookStack dump markers; schedule the restore
   test weekly. Exit criterion: `restore-test.sh` exits 0.
2. **Close the imax exposure.** Narrow to `/mnt/avrana_media/movies:/data/movies:ro`, which is the
   minimum scope its Radarr webhook integration needs, and add authentication plus path confinement.
   One container recreate. Do not touch the `*arr` mounts.
3. **Configuration only.** Bring the Bazarr stanza in line with page 36, rotate the Strava secret,
   fix the stale documentation including the indexer count.
4. **Monitoring and retention.** Add `/api/v3/health` and a SABnzbd probe; protect the newest `ok`
   run from rotation. Expect the first run to surface real pre-existing faults.
5. **Image pinning**, in its own window, `bookstack-mariadb` last and separately.

Two items are unchanged and blocked elsewhere: off-host backups still need a Backblaze or R2 key,
and the firewall in `deploy/ufw/` remains staged, complete and needing root. **Batch 1 should land
before the first off-host sync**, so the first copy to leave the building actually contains the
bare-metal tier.
