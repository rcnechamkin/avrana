# Services

Docker metadata observed 2026-09-23; this is an inventory, not a deployment manifest. Health checks indicate liveness/readiness as defined by each image, not data completeness. No service was restarted.

| Container | Published host endpoints | Health |
|---|---|---|
| audiobookshelf | 10.0.0.218:13378 → 80/tcp | healthy |
| authentik-ldap | No published host port | healthy |
| authentik-postgresql | No published host port | healthy |
| authentik-server | 10.0.0.218:9000 → 9000/tcp; 127.0.0.1:9000 → 9000/tcp | healthy |
| authentik-worker | No published host port | healthy |
| avrana-audible-connector | 10.0.0.218:8092 → 8080/tcp; 127.0.0.1:8092 → 8080/tcp | healthy |
| avrana-imax-verify | 10.0.0.218:8099 → 8099/tcp | healthy |
| avrana-kindle-connector | No published host port | healthy |
| avrana-libation-companion | No published host port | healthy |
| avrana-portal | No published host port | healthy |
| beszel | 10.0.0.218:8093 → 8090/tcp | healthy |
| beszel-agent | Host network; inspect listener separately | healthy |
| beszel-socket-proxy | 127.0.0.1:2376 → 2375/tcp | healthy |
| bookstack | 10.0.0.218:6875 → 80/tcp | healthy |
| bookstack-mariadb | No published host port | healthy |
| calibre-web-automated | 10.0.0.218:8083 → 8083/tcp | healthy |
| completeseries | 10.0.0.218:8085 → 80/tcp | healthy |
| home-assistant | Host network; inspect listener separately | healthy |
| homepage | 10.0.0.218:3000 → 3000/tcp | healthy |
| homepage-dockerproxy | No published host port | healthy |
| jellyfin | Host network; inspect listener separately | healthy |
| komga | 10.0.0.218:25600 → 25600/tcp; 127.0.0.1:25600 → 25600/tcp | healthy |
| libation | No published host port | No healthcheck |
| libation-status | 10.0.0.218:8087 → 8087/tcp | healthy |
| olivetin | No published host port | healthy |
| olivetin-docker-restart | No published host port | healthy |
| olivetin-docker-ro | No published host port | healthy |
| omnibus | 10.0.0.218:5058 → 3000/tcp | healthy |
| omnibus-engine | No published host port | No healthcheck |
| omnibus-redis | No published host port | healthy |
| prowlarr | 10.0.0.218:9696 → 9696/tcp | healthy |
| radarr | 10.0.0.218:7878 → 7878/tcp | healthy |
| recyclarr | No published host port | No healthcheck |
| seerr | 10.0.0.218:5055 → 5055/tcp; 127.0.0.1:5055 → 5055/tcp | healthy |
| shelfarr | 10.0.0.218:5056 → 80/tcp | healthy |
| shelfmark | 10.0.0.218:8084 → 8084/tcp | healthy |
| sonarr | 10.0.0.218:8989 → 8989/tcp | healthy |
| speech-to-phrase | 127.0.0.1:10300 → 10300/tcp | No healthcheck |
| tracearr | 10.0.0.218:5057 → 3000/tcp | healthy |
| wyoming-piper | 127.0.0.1:10200 → 10200/tcp | No healthcheck |

## Configuration and relationships

- Jellyfin: `/home/cody/docker/jellyfin/config` and `cache`; movie/TV media binds read-only. Public information endpoint reports 10.11.11. `/health` returned 200. Artwork remains incomplete.
- BookStack: `/home/cody/avrana/services/bookstack/docker-compose.yml`; app `config` and MariaDB `mariadb` bind directories. Running tags 26.05.3 and 11.8.8, zero recorded restarts for both at inspection. Deployment and `config/www/.env` hold sensitive configuration; never copy them.
- Authentik: server/worker/PostgreSQL/LDAP plus application integrations. Worker was recreated during September recovery; server and some dependent applications may still use stale bind inodes.
- Video: Seerr requests, Radarr/Sonarr management, Prowlarr indexing, SABnzbd host downloader, Jellyfin playback; Tracearr monitors playback.
- Books/audio: Shelfmark inbox, CWA durable library, Libation acquisition and status, Audiobookshelf playback, Komga comics. Audible and Kindle connectors integrate selected workflows.
- Operations: portal, Homepage, OliveTin and Docker socket proxies, Beszel monitoring. Source availability does not authorize running operational actions.

BookStack pages 26 and 78 record SABnzbd on host port 8082, Mylar on 8090 and UniFi OS Server under rootless Podman on 11443 (not Docker). These host services were not functionally revalidated in this session; their historical ports are not included as fresh Docker observations.

Secret locations include service `.env`, `secrets/`, Authentik configuration and application databases. Refer to paths, not values. Full production compose/configuration is deliberately not reproduced here.

## Historical ebook/audio matching caveat

BookStack page 33 describes a separate ebook/audiobook matching stage: shared ISBN/ASIN first, then normalized author/title, then same-author title-prefix matching. Ambiguous/fuzzy matches need review, and folders already containing an EPUB are skipped. The matcher implementation was not imported in this selective source snapshot. Page 32's stricter acquisition caution and page 33's prefix rule concern different stages; neither is a universal matching rule or permission to run media-linking commands.
