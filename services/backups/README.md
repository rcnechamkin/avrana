# Backups

| File | Purpose |
|---|---|
| `avrana-backup.sh` | Nightly local backup, 23 components. Timer `avrana-backup.timer`, 02:30. |
| `required-artifacts.txt`, `verify-required.py` | The completeness gate: 179 files and archive members every run must contain. |
| `restore-map.txt` | Where each artifact goes on a rebuilt host. |
| `restore-test.py` (`restore-test.sh` is a wrapper) | Proves a run can rebuild the server without touching the run or production. Timer `avrana-restore-test.timer`, Sundays 04:30. |
| `offhost-backup.py`, `offhost-setup.sh`, `offhost-verify-secrets.sh`, `OFFHOST.md` | Encrypted, add-only copy to Backblaze B2. Timer `avrana-offhost.timer`, 03:30. |
| `tests/` | Offline tests for the tooling above. |

## What a run contains

`/mnt/avrana_media/.backups/avrana/<UTC timestamp>/`, mode 700, files 600, about 1.1 GB:

`arr` `audiobookshelf` `authentik` `avrana-audible-connector` `beszel` `bookstack` `calibre-web-automated`
`cloudflared` `home-assistant` `host-docker` `jellyfin` `kern-data` `komga` `libation` `mylar`
`omnibus` `sabnzbd` `seerr` `shelfarr` `shelfmark` `stack-config` `systemd` `tracearr`, plus `MANIFEST.txt`.

SQLite databases are copied with the online backup API, Postgres and MariaDB with their dump tools, and
config and secrets as files or `tar.zst` archives. The media library is not backed up.

## Behaviour that matters

- **Status.** `LAST_RUN.json` records `ok` or `partial` with the failed components. Any non-zero exit
  sends an alert e-mail.
- **Completeness.** Before a run is finalised it is checked against `required-artifacts.txt`. Anything
  missing fails the owning component, so a run cannot be `ok` and incomplete.
- **Incomplete runs** are kept as `<timestamp>.partial-failed` and never count towards rotation. Only the
  newest three are kept.
- **Rotation.** The newest 7 complete runs are kept. A run containing a `.keep` file is never pruned
  (the 2026-09-20 golden backup).
- **Guards.** The script refuses to run when the array is not mounted or is nearly full.

When a service is added, retired or gains a secret, change `avrana-backup.sh`, `required-artifacts.txt`,
`restore-map.txt` and the component list in `restore-test.py` in the same commit. The restore test fails
if they disagree.

## Restore test

```bash
services/backups/restore-test.py                 # newest complete run
services/backups/restore-test.py /path/to/run    # a specific run, e.g. one downloaded from B2
services/backups/restore-test.py --boot-abs      # also boot a throwaway Audiobookshelf on 127.0.0.1:18378
```

It fingerprints the run before and after and fails if anything in it changed. Databases are checked on
copies in a scratch directory that is removed afterwards. It verifies the manifest, the 23 components,
the required artifacts, the restore map (including files that are renamed on restore, such as the
Calibre-Web key), every SQLite database, every archive, the three SQL dumps, and the rebuild
prerequisites (compose files, secrets, tunnel credential, units, fstab, Docker data-root, Dockerfiles,
external networks named in `BOOTSTRAP.md`). A run downloaded from B2 also carries `OFFHOST-COMPLETE.json`;
its manifest hash and file count are checked against the download. The result of the scheduled run is in
`/mnt/avrana_media/.backups/avrana/RESTORE_TEST_LAST.json`; a failure sends an alert e-mail.

It does not restore anything onto production and does not prove that each application starts on the
restored data. Only Audiobookshelf has a boot test.

## Restoring

Follow `BOOTSTRAP.md`. For a single service: stop it, copy the artifacts to the destinations in
`restore-map.txt`, start it. Never restore over a newer live database without saving it first.
