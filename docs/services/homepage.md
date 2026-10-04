# Homepage: 3000 (LAN)

> Promoted from the BookStack wiki on 2026-10-04 (page 28, "Homepage", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/28-homepage.md).

Dashboard. Container `homepage` + `homepage-dockerproxy` (read-only, GET-only Docker socket proxy). Config in `deploy/homepage/config/`.
- Groups: **Media · Books & Comics · Automation · Server**. Native widgets for Seerr, Jellyfin, ABS, Komga, CWA, Radarr, Sonarr, Prowlarr, SABnzbd, Mylar3.
- **Libation** uses a `customapi` widget (via libation-status:8087) under *Automation*. **BookStack** is a plain tile (gethomepage has no native bookstack widget). The legacy **Health API tile was removed** 2026-08-13 (the service still runs).
- Widget secrets: `services/homepage/widget-secrets.env` (mode 600, gitignored). Dedicated read-only creds per service (Jellyfin/Komga API keys, CWA viewer account).
