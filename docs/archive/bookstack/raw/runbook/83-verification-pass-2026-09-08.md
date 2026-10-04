---
bookstack_page_id: 83
title: "Verification pass, 2026-09-08"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-09-09 02:25:21
updated: 2026-09-09 02:25:21
last_editor: "Cody"
revisions: 1
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-09; exported 2026-10-04. Classified ARCHIVE. Verification pass that predates the 2026-09-20 incident.

# Verification pass, 2026-09-08
# Verification pass, 2026-09-08

A re-check of the [Audit and DR tabletop, 2026-08-30](http://10.0.0.218:6875/books/runbook/page/audit-and-dr-tabletop-2026-08-30)
findings against the live host, nine days later. **No remediation has been performed in that
window** — the last commit is `fdafb5a` (2026-08-30) and two commits remain unpushed — so this
page records drift, corrections, and the items that improved by other means, not progress against
the remediation plan.

Method: every row below was checked directly on the host, not inferred from documentation.

## Audit items as of 2026-09-08

| ID | Finding | Status | Evidence |
|---|---|---|---|
| C2 | `avrana-imax-verify` reads the backup tree | **OPEN — larger than reported** | `docker exec` into the container sees **695 files** under `/data/.backups`; the audit recorded 477 |
| N1 | Bare-metal tier absent from the backup | **OPEN** | Latest run holds only `systemd/system/{sabnzbd,mylar3}.service`. `bare-metal-auth.env` and `smtp2go.env` return nothing |
| — | Six at-risk artifacts | **5 of 6 still absent** | Missing: `libation-master.key`, `AccountsSettings.json`, shelfmark `users.db`, komf `application.yml`, `mylar.db`. CWA's `app.db` **is** captured but its Fernet `.key` is **not**, which is the half that matters |
| — | Weekly restore test | **NOT SCHEDULED** | Zero restore timers in either scope |
| — | Off-host copy | **NOT STARTED** | No `~/.config/rclone/rclone.conf` |
| C6 / N3 | `*arr` health + SABnzbd probes | **OPEN** | `services-health.sh` contains 0 references to `api/v3/health` and 0 to sabnzbd or mylar |
| C9 | Mutable image tags | **OPEN** | `bookstack:26.05.3`, `mariadb:11.8.8`, `shelfmark:1.3.6` all still running on tags |
| C1 | Stale `health_api.service` assertion | **APPEARS FIXED** | No `health_api` references remain in `services/backups/restore-test.sh`. The test has not been run to confirm exit 0 |

## Improved since the audit, by other work

| Item | Then | Now |
|---|---|---|
| Failed system units | 8 | **0** — `cleanup-obsolete-units.sh` evidently ran |
| Failed user units | 5 | 5 — unchanged (`tag_all`, `lastfm_fetcher`, `strava_fetch`, `blackbox`, `summarize_lastfm`) |
| Orphan Docker container records | 6, reboot a coin flip | **Resolved** — 40 records for 40 containers |
| `home-assistant` and `tracearr` in the backup | Recorded as gaps | **Both captured** |
| Nightly backup | — | Healthy: ran 2026-09-08 02:33, `status:ok`, 169 MB, 17/17 components, `failed:[]` |

## Corrections to other pages

**1. "Komga is reboot-safe" is wrong.** *Roadmap and Open Work* records the `daemon-reload` item as
**DONE, verified 2026-08-28**, on the grounds that `docker.service` now lists
`mnt-avrana_media-comics_merged.mount` in its `After=`. The ordering edge is real and did not help.

On the **very next boot** the mount did not come up at all, and Komga served an empty library for
**five days** before anyone noticed:

- `18:41:50` boot. `/dev/sdb1` does not enumerate; the kernel first sees `sdb: sdb1` at **18:46:30**, ~4m40s in.
- `18:43:24` the by-uuid device unit hits its 90 s timeout → fsck fails → `mnt-avrana_media.mount` fails → `comics_merged.mount` fails with `result 'dependency'`.
- `19:04:41` the array is mounted manually after three `e2fsck` runs. **`comics_merged.mount` was never retried** and stayed `inactive (dead)`.

Ordering only sequences units that *start*. It does nothing when the dependency itself fails, and
`nofail` on the array guarantees boot proceeds anyway. Fixed 2026-09-04 by starting the mount unit
and restarting Komga; Docker bind mounts are `rprivate`, so the restart is mandatory, not optional.
Durable fixes still open: an `x-systemd.device-timeout` on the array's fstab line, and a
`comics_merged` assertion in `verify-array.sh` — **nothing anywhere checks that mount today**, which
is why it hid.

**2. This was a false-green trap firing for real.** The audit lists *"Komga healthy with the
mergerfs union unmounted: libraries empty"* as one of seven hypotheticals. It is no longer
hypothetical. Every health check stayed green throughout, because container liveness was never in
question. This is direct evidence for Batch 4 rather than an argument from principle.

**3. Mylar3 no longer requires a login.** *Known Issues* states "SABnzbd and mylar3 now require a
login (2026-08-28, audit C1/C2 closed)". As of **2026-09-05 the Mylar3 half is reversed** at the
operator's request: `authentication = 0`, `http_username`/`http_password` set to `None`. SABnzbd is
unchanged. API keys were not touched and every integration still authenticates by key.

A trap worth recording for anyone re-enabling it: clearing `authentication` alone does **not**
disable auth. `mylar/config.py:1442` coerces the value on load —

```python
if all([self.AUTHENTICATION == 0, self.HTTP_USERNAME is not None, self.HTTP_PASSWORD is not None]):
    self.AUTHENTICATION = 1   # silently forces HTTP basic
```

— so `authentication = 0` with credentials still populated *downgrades* a session login to a
browser basic-auth prompt instead of removing it. Both credential fields must read `None`.

**4. The indexer count is still stale.** Page 82 flagged that *Known Issues*, *Roadmap and Open
Work* and the repository `CLAUDE.md` all claim one indexer where Prowlarr holds two. All three were
still uncorrected at the time of this pass.

## Assessment

The backup subsystem is running cleanly and daily, and the systemd and Docker-record debt that
caused the August incidents is genuinely gone. The gap is unchanged and unchanging: **the nightly
run is healthy but incomplete**, and the one finding that grew rather than held steady is C2.

The sequencing argument from the audit is now sharper, not weaker. Off-host sync is the single
remaining point of total loss and the obvious thing to reach for first — but the 169 MB currently
being written is not the 169 MB a recovery needs. Batch 1 before the first sync, as the audit
states.
