# Homepage: 3000 (LAN)

> Promoted from the BookStack wiki on 2026-10-04 (page 28, "Homepage", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/28-homepage.md).

Dashboard. Container `homepage` + `homepage-dockerproxy` (read-only, GET-only Docker socket proxy). Config in `deploy/homepage/config/`.
- Groups, by media pipeline in flow order (AVR-366, 2026-10-27): **Video** (Seerr → Radarr/Sonarr → Prowlarr → SABnzbd → Jellyfin → Tracearr) · **Audiobooks** (Audible Connector → Libation → Audiobookshelf) · **Books** (Shelfmark, Shelfarr → Calibre-Web Automated) · **Comics** (Request Comics → Mylar3 → Komga) · **Operations** (OliveTin, Authentik admin, Beszel). Native widgets for Seerr, Jellyfin, ABS, Komga, CWA, Radarr, Sonarr, Prowlarr, SABnzbd, Mylar3. `tests/test_homepage_nav.py` keeps groups, layout and container names consistent.
- **Libation** has no web UI: its tile links to libation-status (8087, JSON) and uses a `customapi` widget there. Until 2026-10-27 the link opened Audiobookshelf by mistake. The **BookStack** tile (retired) and the tile for Homepage itself were removed. The legacy **Health API tile was removed** 2026-08-13 (the service still runs).
- Widget secrets: `services/homepage/widget-secrets.env` (mode 600, gitignored). Dedicated read-only creds per service (Jellyfin/Komga API keys, CWA viewer account).
