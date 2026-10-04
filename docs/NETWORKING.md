# Networking

> **Update 2026-10-04.** Verified: the host address is 10.0.0.218 by DHCP reservation on bridge `br0`;
> one tunnel (`cloudflared-avrana`) publishes 12 hostnames (`deploy/host/cloudflared/config.yml`), of which
> `avrana.net`, `ops` and `kindle` pass through the Authentik outpost and the rest use each application's
> own login; a second, obsolete tunnel for `comics.avrana.media` is still running and is to be retired.
> **No host firewall is active** (ufw is off, `DOCKER-USER` is empty), so every published port is reachable
> from the LAN. The network `avrana-ldap` is external and must be created by hand on a new host
> (`BOOTSTRAP.md`). The address-pool migration was abandoned; its tooling stays in `Kern-Ecosystem`.

Observed Docker metadata: 2026-09-23. Most published application ports bind to `10.0.0.218`; selected tunnel origins also bind loopback. Jellyfin, Home Assistant and Beszel agent use host networking. [Services](SERVICES.md) lists observed container endpoints.

Independent Compose networks remain in use. Authentik backend/frontend networks and selected shared media networks exist; do not recreate or renumber them. BookStack and its MariaDB share `bookstack_default`, with only application port 6875 published on the LAN. The database has no published port.

BookStack pages 2 and 7 describe Cloudflare tunnels for public applications and LAN-only administrative interfaces. Current tunnel routes, DNS and firewall enforcement were not re-audited; published port bindings alone do not prove public reachability or isolation. Old operations documentation still mentions the retired health API, so it was not copied as current truth.

Historical `deploy/ufw/README.md` is a draft. August Docker address-pool changes caused outages and rollback defects; later notes correct the claim that changing default pools renumbers existing networks. Never apply those proposals during documentation work. See [historical findings](findings/2026-08-infrastructure-incidents.md).
