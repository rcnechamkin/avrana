# Operations and recovery boundaries

Evidence date: 2026-09-23. Start with read-only observations, not repair commands.

```sh
hostname
git -C /home/cody/dev/avrana status --short --branch
docker ps --format '{{.Names}}\t{{.Status}}'
findmnt /mnt/avrana_media
```

Inspect selected container mounts and health without dumping environment variables. Read narrowly bounded logs with credential redaction. A mount source existing on the host does not prove a long-running container sees that inode. A database ping can remain green while its old files are deleted but open.

The September recovery ledger records 11 stale bind mounts across five containers after Authentik worker maintenance. This is a recorded count, not a fresh inode comparison. Do not restart Authentik server, Audible connector, Libation companion, Speech-to-Phrase or Piper casually. Preserve deleted-open state before any approved maintenance. The latest ledger takes precedence over the older handoff's 15-mount count.

BookStack is currently healthy by Docker checks and was restored/validated during recovery. No change to its deployment is necessary to use these docs. The existing offline SQL export supplied this migration's wiki inventory; it was parsed as text, never executed. No live SQL queries or API writes were needed.

On September 23, Jellyfin was serving media but had incomplete artwork. The September 23 captured working-copy database passed full SQLite integrity checking. This does not establish that all referenced files exist or replace a fresh checkpoint before a future repair. See [the forensic finding](findings/2026-09-23-jellyfin-artwork.md); do not substitute a broad refresh for that diagnosis.

## Safe database analysis

Do not open live or golden SQLite files with ordinary SQLite tooling: even a read-only connection can create WAL sidecars in some circumstances. This session used byte reads to private temporary copies; the live database and WAL hashes were stable before/after capture and matched copied bytes. SQLite then opened only the disposable copy and `query_only` was enabled. This is a verified quiescent capture, not a universal online-backup algorithm. If hashes change, reject the capture and use an approved consistent backup procedure.

Never clean the existing sidecar/empty-database contamination of recovery evidence. Preserve the original manifest and explain later additions. Do not run old restore/repair scripts copied from historical documentation.

## Development and deployment

Use [DEPLOYMENT.md](DEPLOYMENT.md) for the review process. Local commits are separate from deployment. A future approved service change needs an exact file/action list, current-state preservation, rollback, service-specific validation and an operator-controlled window where necessary. No sync or bulk copy between development and production is configured.
