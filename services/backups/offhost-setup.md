# Off-host backup setup

Everything is built and tested except the one thing only you can provide: an object-store key.
Ten minutes of setup, then it runs nightly on its own.

## Why this exists

`avrana-backup.sh` writes to `/mnt/avrana_media/.backups`, which is on the media array. That
survives a root-disk failure but not the loss of the array, which would take the media **and every
backup** together. The tree is ~680 MB across 7 daily runs, so shipping it costs cents per month
and closes the last total-loss gap.

## Read this before you start

**The backup is encrypted client-side, and the passwords are the only way back in.**

The tree contains Authentik's full `pg_dump` (every user, password hash and OIDC client secret),
BookStack's `APP_KEY`, `services/*/secrets`, the \*arr API keys and the cloudflared tunnel
credentials. Sending that to a third party in the clear would be worse than not backing it up, so
it goes through an rclone `crypt` remote: the provider only ever sees encrypted blobs and encrypted
filenames.

> **Store the two crypt passwords in your password manager, off this machine, before you finish.**
> If the array and the root disk both die, the remote copy is all that is left, and without those
> passwords it is unreadable noise. A backup you cannot decrypt is not a backup.

## 1. Create a bucket and key

Either provider is fine; **Backblaze B2** is the simpler and cheaper of the two at this size.

**Backblaze B2** — create a private bucket (e.g. `avrana-backups`), then an *application key*
scoped to just that bucket. You get a `keyID` and an `applicationKey`.

**Cloudflare R2** — create a bucket, then an R2 API token. You get an access key id, a secret, and
your account id.

## 2. Generate the crypt passwords

Run this and keep the two values; you will paste them in the next step **and** into your password
manager:

```bash
docker run --rm rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
  version >/dev/null   # sanity check the pinned image runs
openssl rand -base64 32   # -> crypt password
openssl rand -base64 32   # -> crypt salt (password2)
```

## 3. Write the config

Create `services/backups/rclone.conf` (already gitignored, and it is the only file that holds these
secrets). Obscure the two crypt passwords first, because rclone stores them obscured:

```bash
docker run --rm rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
  obscure 'THE-PASSWORD-FROM-STEP-2'
```

Then, for **B2**:

```ini
[avrana-b2]
type = b2
account = YOUR_KEY_ID
key = YOUR_APPLICATION_KEY

[avrana-crypt]
type = crypt
remote = avrana-b2:avrana-backups/avrana
filename_encryption = standard
directory_name_encryption = true
password = OBSCURED_PASSWORD
password2 = OBSCURED_SALT
```

For **R2**, replace the first block with:

```ini
[avrana-r2]
type = s3
provider = Cloudflare
access_key_id = YOUR_ACCESS_KEY
secret_access_key = YOUR_SECRET
endpoint = https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
acl = private
```

and point `remote =` at `avrana-r2:avrana-backups/avrana`.

Then lock it down:

```bash
chmod 600 /home/cody/avrana/services/backups/rclone.conf
```

## 4. First run

```bash
/home/cody/avrana/services/backups/offhost-sync.sh
```

It refuses to run unless the local tree looks healthy (at least one dated run, and the most recent
local backup reported `ok`), because a mirror faithfully reproduces destruction. It also caps
deletions at 3 per pass, so a corrupted or half-written array cannot wipe the remote copies.

After uploading it **verifies**: it reads the newest run's `MANIFEST.txt` back *from the remote*,
decrypts it, and diffs it against the local copy. A sync that reports success but wrote nothing
readable fails the run.

## 5. Enable the timer

```bash
ln -sf /home/cody/avrana/deploy/systemd/avrana-offhost.service ~/.config/systemd/user/
ln -sf /home/cody/avrana/deploy/systemd/avrana-offhost.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now avrana-offhost.timer
systemctl --user list-timers avrana-offhost.timer
```

Runs at **03:30**, an hour after `avrana-backup.timer` at 02:30, so it ships a completed run rather
than racing a partial one.

## Monitoring

`scripts/services-health.sh` (15-minute timer) now fails if the off-host sync is missing, stale
(>50 h, i.e. two consecutive misses), or did not complete cleanly. It stays silent until
`OFFHOST_LAST_RUN.json` first appears, so it does not nag before setup.

```bash
cat /mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json
journalctl --user -u avrana-offhost.service -n 50
```

## Restoring from the remote

The remote is a plain mirror of the local tree once decrypted, so recovery is the same as a local
restore, with a download in front:

```bash
docker run --rm --user 1000:1000 \
  -v /home/cody/avrana/services/backups/rclone.conf:/config/rclone/rclone.conf:ro \
  -v /tmp/restore:/out \
  rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
  copy avrana-crypt:2026-08-17T03-22-51Z /out
sha256sum -c /tmp/restore/MANIFEST.txt
```

Then follow the per-component steps in `README.md` / *Backups & Recovery*.
