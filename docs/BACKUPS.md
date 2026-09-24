# Backups and evidence

Sources: live `services/backups/avrana-backup.sh` inspected 2026-09-23; recovery ledger F1–F8/M5; BookStack page 8 (older and partly superseded).

Stack backups live under `/mnt/avrana_media/.backups/avrana/<UTC timestamp>`. These contain credentials and application state and must never enter Git. The recovery ledger records the 2026-09-23T01-23-10Z run as 24 components, 106 original manifest entries verified and 18 SQLite artifacts validated on disposable copies. That is a historical verification, not a newly run backup/restore test. Later directory counts include documented verification contamination.

The September 20 golden backup has two preserved copies: the `.keep`-marked production backup `2026-09-20T09-34-23Z` and `recovery-20260920/GOLDEN-BACKUP-2026-09-20T09-34-23Z`. Preserve both exactly. The latter is outside normal retention. Do not remove sidecars or empty files created by earlier verification.

## Confirmed Jellyfin coverage gap

The live backup function explicitly excludes `metadata`, `cache`, `transcodes`, `log` and `logs` from the Jellyfin config archive. The September 20 archive has no metadata subtree. Metadata artwork is therefore not recoverable from that backup, even though the database contains image paths. Artwork/custom selections are not equivalent to disposable transcoding cache.

The Jellyfin function also archives database files directly with tar; its result should not be advertised as a transactionally consistent SQLite online backup. The examined golden working copy passed integrity, but this does not validate future captures. A proposed change should use a consistent SQLite backup plus config and metadata capture, distinguish transient cache from durable artwork, and validate on disposable copies. No production backup script was changed or run here.

## Other gaps

The latest recovery notes say off-host backup is not provisioned, weekly restore coverage remains incomplete, SSH recovery configuration needs backup coverage, and maintenance/final re-freeze remain open. Old wiki claims of 10/11 components are superseded by the later ledger's 24-component record. Restore-test claims are dated evidence, not a standing guarantee.

BookStack needs its database, application configuration/APP_KEY and uploaded assets considered together. The preserved recovery export already supported this documentation extraction; do not create or overwrite a dump for migration convenience. Any future restoration requires explicit approval and must preserve newer live state first.
