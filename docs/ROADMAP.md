# Remaining work

State on 2026-10-04, after remediation Batches 1 and 2. Each item needs the owner's approval before any
production change. Finding numbers (A5, A9 ...) refer to the October 2026 bug hunt.

## Waiting on the owner

- Rotate the SMTP2GO password and run the staged script that updates the two Authentik blueprints and
  writes `services/backups/.env.alert`. Until then no alert e-mail is delivered.
- Add a second SSH key. Only one device can log in.
- Raise the Backblaze download cap so one run (about 1.1 GB) can be restored more than once a day; the
  2026-10-04 repeat restore was refused with `download_cap_exceeded`. Ideally also a key without
  delete rights (`services/backups/OFFHOST.md`).
- Run `services/backups/offhost-verify-secrets.sh` once to prove the 1Password values unlock the data.
- Set `rcnechamkin/Kern-Ecosystem` to archived on GitHub (tag `archive-2026-10-04` is pushed).
- Decide where the Avrana Party wiki pages belong (`docs/archive/bookstack/INDEX.md`, OWNER REVIEW).
- Approve retirement of the BookStack containers now that their content is archived.

## Deferred, in rough order

1. **Socket-proxy isolation (A9).** The three Docker socket proxies answer on their bridge addresses, so
   any local process can read every container's environment. Needs a firewall rule or a Unix-socket design.
2. **Mylar3 login (A5).** Approved. Restore authentication and make the baseline expect it.
3. **`avrana-agent` account.** Approved in principle: a separate account with no sudo, no Docker and no
   access to `/home/cody`, a read-only wrapper, and a deploy wrapper run by the owner.
4. **Firewall.** `deploy/ufw/` is staged and has never been applied.
5. **Compose v1 to v2.** Recreate the 23 v1-created containers one project at a time; remove the v1 package.
6. **Retire** Plex, the `comics.avrana.media` tunnel, nginx, libvirt, the legacy Kern timers, Kavita state,
   then update `verify-baseline.sh` (hardcoded 40 containers, 2 tunnels), `required-artifacts.txt`,
   `restore-map.txt` and the `kern-data` and `kavita` backup components.
7. **Storage.** Replace the USB enclosure; move Docker's data-root off it (`deploy/storage/ENCLOSURE-MIGRATION.md`).
   Add a UPS.
8. **Health coverage.** Expected-container list in the recurring check (A7), `comics_merged` mount check
   and `nofail` (A6), hold Docker packages in unattended upgrades (A14).
9. **Jellyfin artwork.** One-item regeneration pilot (`docs/findings/2026-09-23-jellyfin-artwork.md`).
10. **Authentik.** Audit the 13 blueprints applied for the first time during the September recovery.
    Move the Jellyfin API key and Komga admin password out of the enrollment blueprint's expression code.
11. **Rebuild rehearsal** on a spare disk or VM, following `BOOTSTRAP.md` end to end.
12. **Recovery artifacts.** Clean up `~/recovery-*`, `~/jellyfin-recovery`, `/home/cody/jellyfin`,
    `*:premaint-20260922` images once the owner releases them.
13. Radarr download loop (A13), Seerr proxy settings (A20), smartd notifications (A21), `cloudflared`
    packaging and update.
