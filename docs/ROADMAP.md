# Remaining work

State on 2026-10-06, after remediation Batches 1 to 4. Finding numbers (A5, A9 ...) refer to the
October 2026 bug hunt. Everything that needs root is staged as a script in `deploy/host/owner-scripts/`
with its own README; everything below that is not a script needs the owner's hands or a decision.

## Waiting on the owner

Scripts, in order (`deploy/host/owner-scripts/README.md`): Mylar3 login (A5), fstab `nofail` and
the unattended-upgrade blacklist (A6, A14), Compose v1 package removal (A12), retirement of the comics
tunnel, nginx, libvirt and Plex, the Kavita config directory, the `avrana-agent` account, the
cloudflared update from Cloudflare's apt repository (C3).

Not scripts:

- Raise the Backblaze download cap; run `services/backups/offhost-verify-secrets.sh` once.
- Rotate the Komga admin password, the `audible-connector` and `omnibus` OIDC secrets, and the SMTP2GO
  password; then run the Batch 1 alert-configuration script. Until then no alert e-mail is delivered.
- Add a second SSH key.
- Set `rcnechamkin/Kern-Ecosystem` to archived on GitHub (tag `archive-2026-10-04` is pushed).
- Decide where the Avrana Party wiki pages belong (`docs/archive/bookstack/INDEX.md`, OWNER REVIEW).
- Approve retirement of the BookStack containers now that their content is archived.
- Apply the staged firewall (`deploy/ufw/`) from a console session.
- A UPS.

## Done in Batch 4 (2026-10-06), for the record

- Authentik: the nine secrets the blueprints embedded (five OIDC client secrets, the SMTP2GO
  password, the Jellyfin API key, the Komga admin e-mail and password) live in
  `services/authentik/blueprints.env` (0600, worker only) and the blueprints reference them with
  `!Env`; all 13 blueprints are tracked in Git. The applied policies, providers and e-mail stages
  were verified unchanged by digest before and after the worker re-applied them. The audit of the
  13 blueprints themselves is still open (deferred 1).
- The weekly restore test boots throwaway Komga, Jellyfin and Authentik servers from the restored
  copies, next to the Audiobookshelf one (`--boot-all` in the unit). First full run: all four pass.
- `restore-test.py`: a decompressor whose consumer exits early no longer blocks for ever (the first
  boot run hung this way); loads have a timeout; the SQLite count follows Kavita's retirement.
- Completeness gate: `services/authentik/blueprints.env` is a required stack-config member (180).
- Off-host, for the record: the 2026-10-06 nightly run uploaded but its `cryptcheck` hit the B2
  download cap that the Batch 2 restore download had used up earlier the same UTC day; the next
  nightly run catches up (the script retries unmarked runs newest first). Nothing changed.

## Done in Batch 3 (2026-10-06), for the record

- A9: the three Docker socket proxies serve Unix sockets in 0700 directories and have no network;
  port 2376 is gone and no bridge address answers the Docker API.
- A12: all 40 containers recreated with Compose v2 (Jellyfin was already v2 and was not touched).
- A7, A15: `deploy/docker/expected-containers.txt` drives the health check and the baseline; a
  stopped expected container fails, an unlisted one warns; Authentik has a URL check; the tunnel
  count follows the enabled units.
- A6 (half): `comics_merged` is checked every 15 minutes. The fstab half is script 02.
- A13 (half): the recycle bin warns at 300 GB. The custom-format scores were not analysed.
- Legacy Kern user units removed (archived in Kern-Ecosystem); `known-failed-units.txt` is empty.
- Kavita backup component retired (23 components, 179 required artifacts); Komga's compose file is a
  regular file on the host; `deploy/compose/` removed.
- Blueprints and the audible connector's `.env` and `secrets/` are no longer world-readable.

## Deferred, in rough order

1. **Authentik.** Audit the 13 blueprints applied for the first time during the September recovery
   (the secrets they embedded are out since Batch 4, so the files can now be reviewed in Git).
2. **Backups as a root system unit** with a root-owned tree (bug hunt E5), so neither `cody` nor the
   agent account can write the backup tree.
3. **Storage.** Replace the USB enclosure; move Docker's data-root off it
   (`deploy/storage/ENCLOSURE-MIGRATION.md`). A wrong filesystem at the mount point still satisfies
   every guard except the boot check (bug hunt C5).
4. **Radarr loop (A13).** Inspect the custom-format scores for the two September releases.
5. **Seerr proxy settings (A20), smartd notifications (A21)** once an alert channel exists.
6. **`cloudflared` packaging and update** (2025.6.1, outside package management).
7. **Jellyfin artwork.** One-item regeneration pilot (`docs/findings/2026-09-23-jellyfin-artwork.md`).
8. **Rebuild rehearsal** on a spare disk or VM, following `BOOTSTRAP.md` end to end.
9. **Recovery artifacts.** Clean up `~/recovery-*`, `~/jellyfin-recovery`, `/home/cody/jellyfin`,
   `*:premaint-20260922` images once the owner releases them.
10. Completed-download clean-up in `incoming/` (A18); UniFi self-updates (C1); on-host agent
    transcripts under `~/.codex` and `~/.claude` (C4).
