# Changing and deploying

`rcnechamkin/avrana` is canonical. Production (`/home/cody/avrana`) is a plain directory, not a Git
checkout, and nothing synchronises the two automatically. A change reaches production by a deliberate,
recorded copy of specific files.

## Before committing

1. `git status` and the exact diff.
2. `python3 tests/run_offline.py`.
3. Stage exact paths; review the staged content.
4. `python3 scripts/review_git_content.py --staged` must report 0 blocked files.

## Deploying one change

1. On the host, run `scripts/drift-check.py --quiet` from a checkout or exported copy of the commit.
   Know what differs before you start.
2. Save the current production file under a batch directory on the array
   (`/mnt/avrana_media/.backups/batch<N>-<date>/rollback/`), with its SHA-256.
3. Copy only the files in the change. Keep modes (scripts 755, units 644, secrets 600).
4. For a compose change: `docker compose config -q` first. Recreating a container needs the owner's
   approval; see the Compose v1/v2 warning in `AGENTS.md`.
5. Verify with the service's own check and `scripts/services-health.sh`.
6. Run `drift-check.py` again and record the result in the batch ledger.

Rollback is the saved copy.

## Layout facts that are easy to get wrong

- Compose project names equal the directory name under `services/`, except `services/media`, which is
  project `docker`; Jellyfin needs `--profile media`.
- `services/komga/docker-compose.yml` is a regular file on the host too since 2026-10-06; the old
  `deploy/compose/` mirror directory is gone.
- User units are tracked in `deploy/systemd/` and `deploy/storage/systemd/` and installed in
  `~/.config/systemd/user/`. Host units and drop-ins are in `deploy/host/`, `deploy/storage/dropins/`
  and `deploy/docker/`.
- Seven Authentik blueprints exist in Git only as `.template` files. Editing a template does not change
  production; the deployed `.yaml` must be edited on the host.

## History

The repository began on 2026-09-23 as a selective 41-file development snapshot
(`docs/findings/source-migration.md`, `audible-source-migration.md`). On 2026-10-04 it was rebuilt from
the live tree as the canonical source: `docs/provenance/import-2026-10-04.tsv` records the origin and
SHA-256 of every imported file, and `not-imported-2026-10-04.tsv` records what was left in
`Kern-Ecosystem` and why.
