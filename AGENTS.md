# Agent entrypoint

Read this file, `docs/OPERATIONS.md`, and the two September findings before touching production.

- Verify hostname and working directory. This server is `avrana`; development is `/home/cody/dev/avrana`; `/home/cody/avrana` and `/home/cody/docker` are production.
- Edit development only by default. Inspect Git status, branch, remotes and local work first. Preserve existing changes. No force reset, force push, blanket copying, or push without explicit approval.
- BookStack is production and fragile. Never rebuild, restart, reconfigure, upgrade, reset credentials, alter its database, or recreate containers to obtain documentation. Existing offline exports are sufficient for this migration.
- Never use a Docker socket or privileged container to bypass a filesystem permission boundary.
- Do not restart Docker, reboot, change mounts/network/firewall, prune, delete volumes, restore databases, or run historical recovery scripts without specific approval. Stale mounts and deleted-open files can outlive their host paths.
- Jellyfin's recovered database is more valuable than artwork. No SQL mutation, database replacement, mass refresh, media write, or metadata deletion. See the artwork finding for evidence and repair gates.
- Treat `/mnt/avrana_media/recovery-20260920`, the golden backups, and `/mnt/root-recovery-snap` as immutable evidence. The snapshot postdates deletion. Never clean verification contamination. SQLite inspection belongs on disposable private working copies, not evidence originals.
- Secrets stay outside Git: `.env`, service secrets, credential stores, application databases and personal records are not source. Never print secret values. Review working files, stage exact development paths, then review the indexed content before committing; never stage the live tree.

Reading order: `docs/ARCHITECTURE.md` → `docs/SERVICES.md` → `docs/STORAGE.md` and `docs/BACKUPS.md` → `docs/DECISIONS.md` and `docs/ROADMAP.md`. Use dated findings for history, not current deployment instructions.

BookStack is an archive/reference/presentation layer. Git operations must never call it. Proposed publishing is explicit, one-way, and inactive; see `docs/BOOKSTACK-PUBLISHING.md`.

Local tests must use fixtures and temporary directories, with no production network calls or service imports that initialize runtime state. Copying operational source does not authorize executing it. Record limitations rather than weakening these boundaries.
