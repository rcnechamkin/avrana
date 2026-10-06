# Owner scripts

Root-only changes staged by Batch 3 (2026-10-06). Each is one `sudo bash` on avrana, prints what
it did, saves what it replaces under `/mnt/avrana_media/.backups/batch3-20261006/rollback/`, and
says how to roll back. Run them in order; each is independent and can wait.

| Script | What it does | Downtime | Verify afterwards |
|---|---|---|---|
| `01-mylar3-login.sh` | Restores the Mylar3 login with a password you type at a hidden prompt (A5) | Mylar3, seconds | `/home` answers 303; `verify-baseline.sh` no longer warns |
| `02-host-hardening.sh` | `nofail` on the mergerfs fstab line (A6); Docker and cloudflared excluded from unattended upgrades (A14) | none | `findmnt --verify`; `apt-config dump` shows the blacklist |
| `03-remove-compose-v1.sh` | Removes the Compose v1 package now that every container is v2 (A12) | none | `docker compose version` as cody |
| `04-retire-legacy-services.sh` | Stops and removes the comics tunnel, nine dead unit files, nginx, libvirt and Plex (package only; data kept) | Plex; `comics.avrana.media` goes dark | health check exit 0; baseline says 1 tunnel |
| `05-remove-leftovers.sh` | Deletes the retired Kavita config directory (tarball saved) and an empty root-owned leftover | none | — |
| `06-avrana-agent-account.sh` | Creates the unprivileged `avrana-agent` account with the `avrana-ro` read-only wrapper and a memory ceiling | none | the script's own checks |
| `07-update-cloudflared.sh` | Installs cloudflared from Cloudflare's apt repository (you confirm the key fingerprint at a prompt) and points the tunnel unit at it; the 2025.6.1 binary is kept for rollback (C3) | tunnel, about 10 s | the script checks 12 hostnames and rolls back on its own if any fails; then commit `deploy/host/cloudflared/cloudflared-avrana.service` |

After `04`, commit the updated `deploy/host/fstab` and `deploy/host/apt/` files that `02` copies
into the live tree, and remove `cloudflared/config-comics.yml` from the backup's `cloudflared`
component when convenient (it is harmless to keep).

## Not scripts: what only you can do

1. **Backblaze download cap**: raise it in Caps & Alerts so a 1.1 GB run can be restored more than once a day.
2. **`offhost-verify-secrets.sh`**: run once with the 1Password entry open; proves the stored values decrypt the data.
3. **Rotate**: the Komga admin password, the `audible-connector` and `omnibus` OIDC client secrets, the SMTP2GO password (alerts are silent until then). After SMTP2GO, run the Batch 1 alert-configuration script.
4. **Second SSH key** on a second device, then `06` for the agent account.
5. **GitHub**: set `rcnechamkin/Kern-Ecosystem` to archived.
6. **BookStack**: approve removing the two containers (content is in `docs/archive/bookstack/`).
7. **Avrana Party wiki pages**: decide where they belong (`docs/archive/bookstack/INDEX.md`, OWNER REVIEW).
8. **Firewall**: `sudo bash deploy/ufw/apply-firewall.sh` from a console session, not over SSH alone. It has a 15-minute dead-man rollback; confirm with `confirm-firewall.sh`. Review `rules-input.sh` first: it allows LAN access to SSH, SABnzbd, Mylar3, Jellyfin, Home Assistant and UniFi only; everything else reaches the host through the tunnel.
9. **UPS**: buy one; the September power losses are the only unmitigated cause of unclean shutdowns.
10. **Rebuild rehearsal** on a spare disk or VM following `BOOTSTRAP.md`, the only thing that turns "restore test passes" into "I have rebuilt it".
