# Shelfarr

> Promoted from the BookStack wiki on 2026-10-04 (page 70, "Shelfarr", last edited 2026-08-29) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/70-shelfarr.md).

Request and management platform for ebooks and audiobooks. Jellyseerr, but for books: a user
requests a title, Shelfarr searches the configured indexers, hands the download to a download
client, and files the finished book into the inbox directories the rest of the stack already
consumes.

> **Deployed 2026-08-20, NOT yet in service.** The container is healthy and reachable, but no
> admin account exists and the download client is not connected. See *Remaining setup*.

> **Shelfmark stays in service.** Shelfarr is being evaluated alongside it, not replacing it. Do
> not migrate users or retire [Shelfmark](../../docs/services/shelfmark.md)
> until that evaluation concludes. They overlap: Shelfmark is a search box that hands off a
> finished download; Shelfarr manages requests, users and monitoring. **Both write into the same
> inboxes, so a title requested in both places will be fetched twice.**

## Access

| | |
|---|---|
| URL | `http://10.0.0.218:5056` |
| Binding | `10.0.0.218:5056` -> container port 80. LAN only |
| Public | **No.** No cloudflared ingress, no Authentik proxy provider |
| Container | `shelfarr` |
| Compose | `services/shelfarr/docker-compose.yml` (project `shelfarr`) |

Not exposed publicly: it is an admin-facing request manager, and the tunnel ingress is reserved
for member-facing apps. 5056 is upstream's default and was verified free before allocation.

## Version and pinning

`ghcr.io/pedro-revez-silva/shelfarr:0.1.0@sha256:61c38fc13aeabeb6bdb71ec2f53fe2008fd38571444ebea0fc26394c1c664cca`

Tag **and** digest, per repo convention. **Upstream is v0.1.0** -- early software. `latest` on GHCR
is already ahead of the only semver tag, which is exactly why the digest pin matters here.

## Storage

| Container path | Host path | Purpose |
|---|---|---|
| `/rails/storage` | `services/shelfarr/data` | SQLite DB, generated encryption keys. **The only non-reconstructable state** |
| `/ebooks` | `/mnt/avrana_media/books` | Ebook output = the CWA ingest inbox. CWA imports into `calibre-library` and deletes the inbox copy |
| `/audiobooks` | `/mnt/avrana_media/audiobooks` | Audiobook output = the live ABS library folder, picked up by its watcher |
| `/mnt/avrana_media/incoming` | same | **Identity mount.** SABnzbd is bare-metal with `complete_dir=/mnt/avrana_media/incoming` and reports HOST paths; mounting at the same location makes them resolve with no path remapping, and keeps the move into `/ebooks` a same-filesystem rename |
| `/downloads` | `/mnt/avrana_media/incoming` | Same directory, second name. Shelfarr's seeded `download_local_path` default is `/downloads` and that setting **cannot** be set from the environment, so this makes the default valid out of the box |
| `/rails/tmp` | tmpfs (RAM, 512m) | **Load-bearing, see Troubleshooting** |

No parallel media directories were created. All four verified writable as uid/gid 1000 from inside
the container.

## Integrations

| Integration | Status |
|---|---|
| Prowlarr | Credentials staged in `.env`. **Must be entered in the admin UI** |
| SABnzbd | **Must be added in the admin UI** (`download_clients` is a table, not a setting) |
| Audiobookshelf | Credentials + library id `ddc9d1fd-8734-4fc7-993e-da8197a85a7c` staged in `.env`. Enter in UI |
| Audible / Libation | **Deliberately NOT enabled** |
| OIDC | Not configured. See below |

**Audible/Libation is off on purpose.** Upstream ships a `shelfarr-libation` companion; Avrana
already has its own Audible pipeline (`services/avrana-audible-connector` +
`avrana-libation-companion`) with per-account profile isolation that Shelfarr's single-account
companion lacks. Running both means two Libation instances competing for the same Audible accounts
and the same audiobook inbox. Do not add the companion.

> **Only `oidc_*` and `webhook_*` settings can be set via `SHELFARR_SETTING_<KEY>` environment
> variables.** Prowlarr, Audiobookshelf, the output paths and the download client are NOT
> env-settable. Verified 2026-08-20 by setting them in compose and reading the `settings` table
> back, where they stayed empty. Do not re-add those variables expecting them to work.

## Authentication

Shelfarr has local accounts with TOTP 2FA, plus OIDC/SSO. **Neither is configured yet** -- the
first visit to `/` redirects to `/sign_up`, and the first account created becomes admin.

OIDC is supported and would use `SHELFARR_SETTING_OIDC_*` (issuer, client id, client secret,
provider name, auto-create, default role) with callback `/auth/oidc/callback`. It was **not**
configured because the callback would have to be `http://10.0.0.218:5056/auth/oidc/callback` --
plaintext HTTP on the LAN. That is the same pattern Komga already uses, and it is recorded as
finding **M1** in the [security audit](../../docs/archive/bookstack/raw/runbook/69-security-audit-2026-08-20.md).
Repeating it silently on a new service seemed worse than flagging it. Decide deliberately.

## Healthcheck

Native Rails endpoint: `curl -fsS http://localhost:80/up`, 30s interval, 60s start period. Returns
200 with a green page once the app has booted and the database is reachable, so it is a real
readiness signal rather than "something is listening". Observed healthy ~25-30s from start.

## Backup coverage

Covered by `services/backups/avrana-backup.sh` -> `backup_shelfarr`, added 2026-08-20.

Captures `production.sqlite3` (online SQLite copy) plus `.encryption_keys` and `.secret_key_base`
at 0600. **The DB alone is not restorable.** Shelfarr auto-generates its encryption keys on first
run and stores them beside the database; the key cannot be supplied externally because it must
decrypt the `credentials.yml.enc` baked into the image. Lose the key files and the DB is
undecryptable. Cache/queue/cable SQLite files are deliberately skipped as regenerable.

Verified by restoring the backup copy and reading 51 settings rows back.

## Upgrade procedure

1. Read the upstream changelog. This is a 0.1.0 project; assume breaking changes.
2. Resolve the new digest:
   `curl -s -H "Authorization: Bearer $(curl -s 'https://ghcr.io/token?scope=repository:pedro-revez-silva/shelfarr:pull' | jq -r .token)" -I -H 'Accept: application/vnd.oci.image.index.v1+json' https://ghcr.io/v2/pedro-revez-silva/shelfarr/manifests/<TAG> | grep -i docker-content-digest`
3. Update tag **and** digest in `docker-compose.yml`.
4. Back up `services/shelfarr/data` first, or run the nightly backup.
5. `docker compose up -d`, then confirm healthy and check `/up`.

## Troubleshooting

**Container Up but unhealthy, log stops after "Seeding complete!", nothing listening.**
This is the failure that cost the most time on deployment day. Shelfarr's entrypoint runs
`chown -R rails:rails /rails/storage /rails/tmp` **before** booting Puma. **Docker's root dir on
this host is `/mnt/avrana_media/docker`**, i.e. a container's writable layer lives on the 7.3T
media array, so that recursive chown hits the array's ext4 journal and wedges in
uninterruptible-sleep (`jbd2_log_wait_commit`), driving `sdb` to 99% utilisation at ~0.1 MB/s
while the web server never starts. Reproduced twice, then fixed by putting `/rails/tmp` on tmpfs
so the chown walks RAM. **`CHOWN_ON_START=false` does NOT prevent this; upstream ignores it.**

If a future service shows the same signature, check `docker info | grep "Root Dir"` before
concluding the disk is failing. It looks exactly like a dying drive and is not one.

**`key must be 16 bytes` / `ActiveSupport::MessageEncryptor::InvalidMessage` on boot.**
Something is setting `RAILS_MASTER_KEY`. Do not. Upstream's README claims a 64-char hex key; Rails
wants 16 bytes (32 hex), and even a correctly sized value fails because it must decrypt the
image's baked-in credentials. Leave it unset and let the key auto-generate into `./data`.

**`Unable to proxy request /up ... connection refused` (INFO).** Benign. The `thrust` proxy logs
this in the ~1s before Rails binds port 3000.

## Remaining setup

1. Create the first account at `http://10.0.0.218:5056/sign_up` (becomes admin).
2. Admin -> Settings: enter Prowlarr URL + API key, Audiobookshelf URL + API key + library id.
   Values are in `services/shelfarr/.env`.
3. Add SABnzbd as a download client (`http://10.0.0.218:8080`, API key in `.env`), category for
   books, and confirm `download_local_path` / `download_remote_path` both read
   `/mnt/avrana_media/incoming`.
4. Decide on OIDC (see Authentication).

## The Hardcover rate-limit loop — root cause found 2026-08-28, fix PENDING APPROVAL

Shelfarr was producing ~3,600 log lines a day of
`[HealthCheckJob] [HardcoverClient] Connection test failed: Rate limit exceeded`. The Hardcover
JWT is **shared with CWA and Shelfmark**, so this was never confined to Shelfarr.

**It is not a misconfigured interval.** `health_check_interval` is a database setting defaulting
to **300 s**, and it is unchanged. The observed cadence was one run every ~10 seconds.

**There are 30 concurrent `HealthCheckJob` chains.** `schedule_next_run` ends every run with
`HealthCheckJob.set(wait: interval.seconds).perform_later`, so each execution enqueues its own
successor. Every container start adds a fresh chain, and the existing chains survive in
SolidQueue's SQLite — nothing cancels them. 30 chains ÷ 300 s = one run every 10 s, which is
exactly what was measured. `DownloadMonitorJob` has the same problem with 3 chains.
Queue totals: 30 unfinished `HealthCheckJob`, 3 `DownloadMonitorJob`, 13,731 jobs all-time.

The errors stopped around 2026-08-28T23:59Z when the Hardcover quota window reset, and the check
currently reports `Connection test: passed` — **the loop is still running at ~6 calls/minute and
will exhaust the quota again.** Absence of errors is not resolution here.

**FIXED 2026-08-29.** Storage snapshotted to
`/home/cody/backups/shelfarr-jobdedupe-20260829T032505Z/` first, container stopped so the
SolidQueue worker could not race the write, all unfinished `HealthCheckJob` (30) and
`DownloadMonitorJob` (3) rows deleted along with their scheduled executions, database
`integrity_check` ok, container started. The boot initializers re-enqueued **exactly one chain
of each**, which is the intended state.

`DownloadMonitorJob` was the same bug — `download_monitor.rb:10` enqueues at boot,
`download_monitor_job.rb:87` self-enqueues at `download_check_interval` (default 60 s). It
started this time, so a download client **is** now configured, superseding the older note on
this page.

**Verified after the fix:**

| Check | Result |
|---|---|
| Chains | `HealthCheckJob` 1, `DownloadMonitorJob` 1 |
| Cadence | `03:26:14 -> 03:31:15` = **302 s** (target 300) |
| Rate-limit errors | **0** |
| Hardcover | 36 consecutive `Connection test: passed` |
| Container | healthy |
| CWA / Shelfmark | healthy, unaffected |

> **A note on reading the queue.** SolidQueue's SQLite runs in **WAL mode**, so
> `docker cp` of `production_queue.sqlite3` alone shows a stale, often *empty* view — it briefly
> looked as though the chains had vanished entirely. Copy `-wal` and `-shm` alongside it, or the
> numbers are meaningless.

**This will recur.** Every container start adds a chain and nothing cancels the old ones, so the
count creeps up with each restart. Worth reporting upstream (Shelfarr is v0.1.0). Re-check with:

```bash
for e in "" -wal -shm; do docker cp "shelfarr:/rails/storage/production_queue.sqlite3$e" "/tmp/q.sqlite3$e"; done
python3 -c "import sqlite3;print(list(sqlite3.connect('/tmp/q.sqlite3').execute(
  'select class_name,count(*) from solid_queue_jobs where finished_at is null group by 1')))"
```
