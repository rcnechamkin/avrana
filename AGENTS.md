# Agent entrypoint

Read this file, `docs/OPERATIONS.md` and `docs/incidents/2026-09-20-home-directory-deletion.md` before
touching production. That incident was caused by an agent.

## Where things are

- Host `avrana`. Production is `/home/cody/avrana` and `/home/cody/docker`. This repository
  (`rcnechamkin/avrana`) is the canonical source; its layout mirrors `/home/cody/avrana`.
- `/home/cody/dev/avrana` is an older development checkout on the host. `rcnechamkin/Kern-Ecosystem` is an
  archive. Neither is authoritative.
- Evidence order when sources disagree: the running system, then this repository, then archives. Report
  the disagreement; do not silently pick one.

## Rules

- **Credentials.** Never search the disk for a credential. Never `source`, `eval` or execute a file found
  by searching. Never print a secret value or a line that may contain one. If a credential is needed, stop
  and have the owner enter it at a hidden prompt on the host. `docs/SECRETS.md` lists locations, not values.
- **Observe first.** Inspect state, record it, keep rollback material, change one thing, verify, record
  the result. Stop on anything unexpected instead of improvising.
- **No production change without the owner's approval for that change**: restarting or recreating
  containers, restarting Docker, rebooting, mounts, network, firewall, pruning, deleting volumes,
  restoring databases, upgrades. Approval for one batch does not carry to the next.
- **Compose.** Use `docker compose` v2 only. The arr stack is project `docker` with `--profile media`
  (`BOOTSTRAP.md`, section 7). Every container has carried Compose v2 labels since 2026-10-06; `up -d`
  still recreates whatever differs from the file, so dry-run first (`up -d --dry-run`).
- **Never use a Docker socket or a privileged container to get around a filesystem permission.**
- **Evidence is immutable**: `/mnt/avrana_media/recovery-20260920`, the golden backup
  `2026-09-20T09-34-23Z`, backup runs. Analyse copies. Do not open SQLite files in place, even read-only.
- **Jellyfin**: no SQL changes, no database replacement, no library-wide refresh. See
  `docs/findings/2026-09-23-jellyfin-artwork.md`.
- **BookStack** is retired in place. Do not repair its API, create credentials for it, or write to it.
  Its content is in `docs/archive/bookstack/`.
- **Git.** Stage exact paths, review the staged content, run
  `python3 scripts/review_git_content.py --staged`. Never initialise Git inside the production tree.
  No force push. Push only when the owner has asked for it.
- **Root.** There is no passwordless sudo. Stage root steps as a script for the owner to run.

## Reading order

`README.md` → `BOOTSTRAP.md` → `docs/ARCHITECTURE.md` → `docs/SERVICES.md` → `docs/STORAGE.md` →
`services/backups/README.md` → `docs/DECISIONS.md` → `docs/ROADMAP.md`. Dated files under
`docs/findings/`, `docs/audits/` and `docs/archive/` are history, not instructions.

Tests use fixtures and temporary directories only (`python3 tests/run_offline.py`). Importing source does
not authorise running it against production.
