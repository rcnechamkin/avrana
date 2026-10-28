# systemd units

User units, installed in `/home/cody/.config/systemd/user/` (lingering is enabled for `cody`).

| Unit | Schedule | Runs |
|---|---|---|
| `avrana-backup.timer` | 02:30 daily | `services/backups/avrana-backup.sh` |
| `avrana-backup-trigger.path` | on request from OliveTin | the same backup |
| `avrana-offhost.timer` | 03:30 daily | `services/backups/offhost-backup.py` |
| `avrana-restore-test.timer` | Sunday 04:30 | `services/backups/restore-test.py --alert` |
| `services-health.timer` | every 15 minutes | `scripts/services-health.sh` |
| `omnibus-cache-purge.timer` | daily | clears the Omnibus cache |
| `api-caps-monitor.timer` | every 30 minutes (proposed, not installed) | `scripts/api-caps-monitor.py`: TMDB, Hardcover, ComicVine, Metron and Google Books rate limits and key failures, from logs and read-only tables; mails new incidents |
| `../storage/systemd/avrana-boot-verify.timer` | 5 minutes after boot | `deploy/storage/boot-verify.sh` |

`avrana-cloudflared-restart.path` and `.service` are **system** units for the OliveTin "restart tunnel"
button. They were written in August 2026 and are not installed on the host.

System units for SABnzbd and Mylar3 are in `deploy/host/systemd/`. The Cloudflare tunnel unit
(`cloudflared-avrana.service`) is captured in every backup run under `systemd/system/`.

The retired Kern timers that still exist on the host (`blackbox`, `fetch_lastfm`, `lastfm_fetcher`,
`strava_fetch`, `summarize_lastfm`, `tag_all`, `parse_health_export`) are not tracked here. They are
documented in `rcnechamkin/Kern-Ecosystem` (`RETIRED-COMPONENTS.md`) and are to be disabled in a later
batch.
