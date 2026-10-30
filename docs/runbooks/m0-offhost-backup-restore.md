# M0: verify the off-host backup and run a restore drill (AVR-350)

Owner runbook. Uses only tooling that is in the repo: `services/backups/offhost-backup.py`,
`offhost-verify-secrets.sh`, `restore-test.py`, and the restore recipe in `services/backups/OFFHOST.md`.
Design background is in `OFFHOST.md`; this file is the order of operations and the pass criteria.

## Purpose and what it blocks

Prove three separate things, because each can fail alone:

1. the secrets in 1Password unlock the data in Backblaze B2 (without them the backup cannot be decrypted);
2. recent runs are really off-host, complete and match their manifest;
3. a run downloaded from B2 passes the restore test.

Blocks the M0 recovery gate and, in practice, any risky change (G1, Authentik proposals, Seerr): do not
change production before you know you can get it back. Today the evidence is thin: the roadmap records the
Batch 2 restore download exhausting the daily cap, and the 2026-10-06 nightly check failing for that reason.

## The Backblaze download cap, in one paragraph

B2 refuses downloads once the account's daily download cap (Caps and Alerts, reset 00:00 UTC) is used up.
A full restore of one run is about 1.1 to 1.3 GB, which takes the whole cap on a small plan for that UTC
day. While the cap is exhausted, rclone returns `download_cap_exceeded` and the nightly job's verification
fails; `offhost-backup.py --list` then prints `NO COMPLETION MARKER` or a "cannot list" error for runs that are
fine. **That is the cap, not data loss.** (`services/backups/tests/test_restore_tooling.py` has a case for the
403 `download_cap_exceeded` reply; `offhost-backup.py` lists the marker through a directory listing precisely
because listings still work under the cap.) The nightly run catches up by itself the next UTC day
(`docs/ROADMAP.md`, Batch 4 note). Raise the cap first (step 1), and keep full-run downloads to one per day,
after the nightly job and before 00:00 UTC.

## Preconditions

- 1Password entry for B2 and the rclone crypt password and salt open. A second window is easier.
- Shell on `avrana` as `cody`, in an interactive terminal (the two scripts refuse otherwise).
- The pinned rclone image present locally (`docker image inspect rclone/rclone@sha256:b06aed98...`; both
  scripts check). `--pull never` is used throughout.
- Space: about 2.5 GB free under `/mnt/avrana_media` for a full drill.
- Owner approval for the drill. It does not touch production data: it downloads and reads a copy.

## Prepared by the agent, and what only you can do

| Prepared | Only the owner can do |
|---|---|
| This procedure; the cap analysis; read-only status commands | Raise the cap in the Backblaze console |
| `offhost-verify-secrets.sh`, `offhost-backup.py --list`, `restore-test.py` already exist and are tested offline | Enter B2 and crypt values at the hidden prompts |
| Pass and fail criteria | Run the drill, decide on the key and lifecycle gaps |

## Rules that never bend

- **Never write to or change remote objects.** The uploader is add-only (`rclone copy --immutable`); the drill
  below only reads (`rclone copy REMOTE LOCAL`). Never run `sync`, `move`, `delete`, `deletefile`, `purge`,
  `cleanup`, `copyto` towards the remote, or any command with the remote as the destination, and never
  re-upload a run under an existing name. `--immutable` makes an overwrite attempt fail loudly; do not work
  around it.
- Never run `offhost-setup.sh` to "fix" a read problem: it rewrites `rclone.conf` (it saves the old one as
  `rclone.conf.previous`) and is only for a changed key or password.
- A downloaded run contains decrypted secrets (`stack-config`). Keep it mode 700, off Git, and remove it at
  the end (step 8).
- Do not paste rclone output that includes remote object names into tickets; names are encrypted but counts
  and run timestamps are fine.

## Steps

1. **Raise the cap (owner, web console).** Backblaze, Caps and Alerts, daily download cap. Set it well above
   one run plus the nightly checks (suggestion: at least 5 GB; downloads beyond the free allowance are billed
   per GB, check the current price). Record the new value. While you are there, check the two hardening
   items from `OFFHOST.md`: the application key has **no** `deleteFiles` capability and is limited to the
   bucket (or Object Lock is on), and the bucket default is "Keep all versions" with the `daily/` lifecycle
   rule (hide after 90 days, delete 30 days after hiding) and no rule on `pinned/`.

2. **Local status, read-only.**
   ```sh
   cd /home/cody/avrana
   cat /mnt/avrana_media/.backups/OFFHOST_LAST_RUN.json
   cat /mnt/avrana_media/.backups/avrana/LAST_RUN.json
   systemctl --user list-timers avrana-offhost.timer avrana-backup.timer
   timedatectl show -p Timezone --value
   scripts/services-health.sh; echo "rc=$?"
   ```
   Expect `"status": "ok"` and `"at"` within 50 hours (the health check's threshold), `LAST_RUN.json` status
   `ok`, the timers listed for 03:30 and 02:30 local, health rc 0. Note the time zone: it decides when the UTC day
   ends relative to the timers.

3. **Secrets prove out (no download).**
   ```sh
   bash /home/cody/avrana/services/backups/offhost-verify-secrets.sh
   ```
   Type each value from 1Password at the hidden prompts. Expected: `1/3 ... ok`, `2/3 ... ok: newest remote
   run <timestamp>`, `3/3 ... ok`, then `VERIFIED`. It lists only, so the cap does not matter. Fails with a
   clear reason for a wrong key (step 1/3), wrong crypt password or salt (step 2/3), or an unmarked newest run
   (step 3/3). Stop on a FAIL and fix the 1Password entry; do not guess values.

4. **Remote inventory (listings only).**
   ```sh
   services/backups/offhost-backup.py --list
   ```
   Expect two tiers; `daily tier ... N runs` with each run `complete`, the newest within a day or so of
   `LAST_RUN.json`; `pinned tier` with at least one complete run. `NO COMPLETION MARKER` on the **newest** run
   while the nightly state is `ok` is a real problem; on an old run from before 2026-10-04 it is expected
   (those never satisfied the completeness list). A "cannot list" error naming `download_cap_exceeded` is the
   cap: wait for 00:00 UTC.

5. **Small download: marker and manifest (a few kilobytes of data).** Replace `<RUN>` with the newest
   complete run name.
   ```sh
   RUN=<RUN>
   mkdir -p -m 700 /mnt/avrana_media/tmp-restore/probe && cd /mnt/avrana_media/tmp-restore/probe
   docker run --rm --pull never --user 1000:1000 -e RCLONE_CONFIG=/c/rclone.conf \
     -v /home/cody/avrana/services/backups/rclone.conf:/c/rclone.conf:ro -v "$PWD:/out" \
     rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
     copy avrana-offsite-daily:$RUN /out/$RUN --include "OFFHOST-COMPLETE.json" --include "MANIFEST.txt"
   sha256sum $RUN/MANIFEST.txt
   python3 -c "import json,sys;m=json.load(open(sys.argv[1]));print({k:m.get(k) for k in ('marker_version','files','bytes','manifest_sha256')})" $RUN/OFFHOST-COMPLETE.json
   ```
   Expect the `manifest_sha256` in the marker to equal the hash printed above it, and plausible `files`
   (about 113 for the 2026-10-04 run) and `bytes` (about 1.1 GB). This is the download of two small files.

6. **Representative component: download one component and check its hashes.** The `seerr` component is
   small; any single component will do (components are listed in `services/backups/README.md`).
   ```sh
   docker run --rm --pull never --user 1000:1000 -e RCLONE_CONFIG=/c/rclone.conf \
     -v /home/cody/avrana/services/backups/rclone.conf:/c/rclone.conf:ro -v "$PWD:/out" \
     rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
     copy avrana-offsite-daily:$RUN /out/$RUN --include "seerr/**"
   ( cd $RUN && sha256sum -c --ignore-missing --quiet MANIFEST.txt ); echo "rc=$?"
   ```
   Expect no output and `rc=0` (and at least one file checked: `ls $RUN/seerr`). Any `FAILED` line means a
   file differs from its manifest entry: stop and escalate.

   Also prove the Home member state (S-04), from the same run (`stack-config` holds decrypted secrets; same
   directory rules as the rest):
   ```sh
   docker run --rm --pull never --user 1000:1000 -e RCLONE_CONFIG=/c/rclone.conf \
     -v /home/cody/avrana/services/backups/rclone.conf:/c/rclone.conf:ro -v "$PWD:/out" \
     rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
     copy avrana-offsite-daily:$RUN /out/$RUN --include "stack-config/**"
   zstd -dc $RUN/stack-config/stack-config.tar.zst | tar -tf - | grep -E '^services/avrana-home/(docker-compose.beta-live.yml|state/identity_bindings.json)$'
   ```
   Expect both lines. `identity_bindings.json` is what docs/runbooks/identity-bindings.md section 4 restores.
   Caveat: only runs made after the live script and required list are synced on avrana contain Home state; after
   the sync a host without the bindings file fails the completeness check by design.

7. **Full drill (once; the part that takes the cap).** Only after step 1, after the nightly job has finished,
   and before 00:00 UTC. Use a fresh directory and the OFFHOST.md recipe:
   ```sh
   mkdir -p -m 700 /mnt/avrana_media/tmp-restore/full && cd /mnt/avrana_media/tmp-restore/full
   docker run --rm --pull never --user 1000:1000 -e RCLONE_CONFIG=/c/rclone.conf \
     -v /home/cody/avrana/services/backups/rclone.conf:/c/rclone.conf:ro -v "$PWD:/out" \
     rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 \
     copy avrana-offsite-daily:$RUN /out/$RUN
   ( cd $RUN && sha256sum -c --quiet MANIFEST.txt ) && \
     python3 /home/cody/avrana/services/backups/restore-test.py "$PWD/$RUN" --no-state
   echo "rc=$?"
   ```
   `--no-state` keeps the drill out of `RESTORE_TEST_LAST.json`, which the weekly timer owns. The test also
   checks the downloaded run's marker against its manifest and file count. Expect every line `PASS` or a
   known `WARN` (a version 1 marker on `2026-10-04T20-52-13Z` reports 126 files against 113 present; that is documented in
   `OFFHOST.md`), a closing line with zero failures, and `rc=0`. Optional, heavier: add `--boot-all` to
   boot the throwaway Audiobookshelf, Komga, Jellyfin and Authentik copies on loopback ports
   (`restore-test.py` header); the weekly unit already does this on the local copy, so it proves less here.
   Nothing is restored onto production. Expected download time depends on the link; the script has no
   deadline, so leave it in `tmux`.

8. **Clean up.** The copies hold decrypted secrets. List first, then remove only these two directories:
   ```sh
   ls -la /mnt/avrana_media/tmp-restore
   rm -r -- /mnt/avrana_media/tmp-restore/probe /mnt/avrana_media/tmp-restore/full
   ```
   `rclone.conf` was only mounted read-only and the drill never put a secret in the shell.

## Done when

- Cap raised and recorded; key and lifecycle checks recorded (or the gaps escalated, below).
- Step 3 says `VERIFIED`. Step 4 shows the newest daily run complete and a complete pinned run.
- Step 5: marker hash equals the manifest hash. Step 6: `rc=0`.
- Step 7: restore test exit 0 on the run downloaded from B2, with no unexplained FAIL.
- `OFFHOST_LAST_RUN.json` is still `ok` the morning after the full drill (the nightly check was not starved).
- Temporary directories removed.

## Gaps to escalate rather than fix on the spot

- The application key can delete (has `deleteFiles`) and Object Lock is off: anyone who takes over the host
  can remove remote versions. Replace the key in the console, then re-run `offhost-setup.sh` (hidden prompts).
- No `pinned/` run, or the newest run unmarked for more than two nights.
- Restore test failures on a downloaded run that pass locally (possible corruption in transit or a marker bug).
- Anything in `OFFHOST.md` "What this does not cover": media library, B2 account loss, forgotten crypt password.

## Rollback

Nothing on the host or remote is changed by this procedure except temporary files, so the rollback is deleting `/mnt/avrana_media/tmp-restore/probe` and `full`. If the cap is
exhausted by accident, wait for 00:00 UTC; the nightly job retries unmarked runs newest first. Do not
upload, re-mark or "repair" markers by hand.

## Stop conditions

- `download_cap_exceeded` at any step: stop, do not retry in a loop; resume after 00:00 UTC.
- `offhost-verify-secrets.sh` FAIL at 2/3: the crypt values in 1Password are wrong or incomplete. This is the
  most serious outcome; do not run `offhost-setup.sh` with guessed values.
- A manifest mismatch, a marker hash mismatch, or restore-test FAIL lines that are not documented warnings.
- Any rclone command about to write to the remote.
- Free space under 2 GB on the array.

## Evidence (secret-free)

A dated note under `docs/findings/` and a comment on AVR-350: new cap value, key capability check result,
the three status files' `status` and `at` fields, `--list` run counts (not names), step 3 final line, step 5
hash equality (yes or no), step 6 and 7 exit codes, restore-test summary counts, download size and duration,
UTC date of the drill. Do not include rclone configuration, key IDs, bucket name or encrypted object names.
Update `docs/ROADMAP.md` ("Raise the Backblaze download cap" and the verify line).
