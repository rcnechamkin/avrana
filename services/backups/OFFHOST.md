# Off-host backup

The local backup lives on the same disk as the media and Docker. Losing that disk loses everything
unless a copy exists somewhere else. This is that copy: Backblaze B2, encrypted before it leaves the host.

## Design

```
/mnt/avrana_media/.backups/avrana/<run>/          local, 7 newest kept, written 02:30
        |
        |  03:30  offhost-backup.py   (copy only; verified; marker written last)
        v
b2://<bucket>/daily/<encrypted run>/              expires by bucket lifecycle rule
b2://<bucket>/pinned/<encrypted run>/             never expires; filled by --pin
```

| Requirement | How it is met |
|---|---|
| Remote history survives local rotation | Each run is its own directory and is uploaded once. The uploader has no mirror, remove or overwrite operation (`rclone copy --immutable` only), so pruning a local run does nothing remotely. |
| Local deletion cannot erase remote recovery points | Same. An empty or wiped local tree makes the job fail and alert; it cannot remove remote data. |
| Encrypted names and contents | Two rclone `crypt` remotes (`avrana-offsite-daily`, `avrana-offsite-pinned`) with file and directory name encryption. B2 stores only ciphertext under the two plain prefixes `daily/` and `pinned/`. |
| Secrets not committed | `rclone.conf` is created on the host by `offhost-setup.sh` from hidden prompts, mode 0600, ignored by Git. The uploader refuses a config that is group or world readable. |
| Incomplete backups are not promoted | A run is uploaded only if its name is a plain timestamp (never `*.partial*`), `required-artifacts.txt` is satisfied and every `MANIFEST.txt` checksum verifies. The newest run must be the one `LAST_RUN.json` reports `ok`, otherwise the job fails. |
| Verification metadata travels with the data | `MANIFEST.txt` (SHA-256 of every file) is part of each run. After upload `rclone cryptcheck` compares every file with the encrypted remote copy and the remote file count is compared with the local one; only then `OFFHOST-COMPLETE.json` (file count, bytes, skipped symlinks, manifest hash, time) is written into the remote run. A remote run without that marker is not a recovery set. `restore-test.py` checks the marker of a downloaded run against its `MANIFEST.txt` and the files present, and fails on a mismatch. |
| Failures are visible | Result goes to `/mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json`. `services-health.sh` fails when it is not `ok` or older than 50 hours. A failure also sends an alert e-mail. |
| Retention is explicit | Set on the bucket, below. The host cannot shorten it. |

## Retention

Set once in the Backblaze web console: bucket → Lifecycle Settings → custom rule.

| Prefix | Rule | Effect |
|---|---|---|
| `daily/` | hide files 90 days after upload; delete 30 days after hiding | about 90 nightly runs recoverable, plus 30 days in which a hidden run can still be restored. Roughly 100 GB at 1.1 GB per run. |
| `pinned/` | no rule (keep all versions) | kept until removed by hand in the console |

The bucket default must stay "Keep all versions". Because uploads are add-only, if the nightly job stops
for more than 90 days the daily tier empties itself; the 50-hour health alarm exists so that cannot happen
quietly, and the pinned tier always holds at least one known-good run.

Recommended hardening (owner, in the Backblaze console):

- Use an application key limited to this bucket **without** the `deleteFiles` capability. The uploader
  never needs it. With it, anyone who takes over this host can remove remote versions.
- Or enable Object Lock on the bucket with a default retention of 30 days.

## Operating it

```bash
bash services/backups/offhost-setup.sh              # one time: hidden prompts, writes rclone.conf
services/backups/offhost-backup.py --check           # reachability; uploads nothing
services/backups/offhost-backup.py --dry-run         # what would be uploaded
services/backups/offhost-backup.py                   # upload every complete run not yet off-host
services/backups/offhost-backup.py --pin <RUN>       # also keep RUN forever
services/backups/offhost-backup.py --list            # remote runs and whether each is complete
systemctl --user enable --now avrana-offhost.timer   # nightly at 03:30
```

rclone runs from the pinned local image `rclone/rclone@sha256:b06aed98…` (v1.75) with `--pull never`; the
backup tree is mounted read-only into it.

## Restoring from B2

```bash
mkdir -p /mnt/avrana_media/tmp-restore && cd /mnt/avrana_media/tmp-restore
docker run --rm --pull never --user 1000:1000 -e RCLONE_CONFIG=/c/rclone.conf \
  -v /home/cody/avrana/services/backups/rclone.conf:/c/rclone.conf:ro -v "$PWD:/out" \
  rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
  copy avrana-offsite-daily:<RUN> /out/<RUN>
( cd <RUN> && sha256sum -c --quiet MANIFEST.txt ) && python3 /home/cody/avrana/services/backups/restore-test.py "$PWD/<RUN>"
```

On a new machine with no configuration, run `offhost-setup.sh` first with the values from 1Password.
The full rebuild procedure is `BOOTSTRAP.md`.

## What is and is not uploaded

Regular files only. The 13 symlinks under `systemd/user/*.wants/` are skipped by rclone and are not
needed: `systemd/enabled-user.txt` in the same run lists the enabled units and `BOOTSTRAP.md` enables
them explicitly. The marker's `files` and `bytes` count regular files; `symlinks_skipped` is informational.

Known inaccuracy: the first upload of run `2026-10-04T20-52-13Z`, in both tiers, has a version 1 marker
that records 126 files and 1,107,883,058 bytes. It counted the symlinks. The run holds 113 files and
1,107,880,113 bytes, all verified. The markers are immutable and were left as they are; the restore test
enforces their manifest hash and reports the count as a warning.

## What this does not cover

- The media library is not backed up anywhere.
- Runs taken before 2026-10-04 do not satisfy the completeness list and are skipped, not uploaded.
- The September 2026 recovery evidence and golden backup are local only.
- B2 account loss or a forgotten crypt password. Keep both in 1Password.
