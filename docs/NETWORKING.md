# Networking

Observed Docker metadata: 2026-09-23. Most published application ports bind to `10.0.0.218`; selected tunnel origins also bind loopback. Jellyfin, Home Assistant and Beszel agent use host networking. [Services](SERVICES.md) lists observed container endpoints.

Independent Compose networks remain in use. Authentik backend/frontend networks and selected shared media networks exist; do not recreate or renumber them. BookStack and its MariaDB share `bookstack_default`, with only application port 6875 published on the LAN. The database has no published port.

BookStack pages 2 and 7 describe Cloudflare tunnels for public applications and LAN-only administrative interfaces. Current tunnel routes, DNS and firewall enforcement were not re-audited; published port bindings alone do not prove public reachability or isolation. Old operations documentation still mentions the retired health API, so it was not copied as current truth.

Historical `deploy/ufw/README.md` is a draft. August Docker address-pool changes caused outages and rollback defects; later notes correct the claim that changing default pools renumbers existing networks. Never apply those proposals during documentation work. See [historical findings](findings/2026-08-infrastructure-incidents.md).
