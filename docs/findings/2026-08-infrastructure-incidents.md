# August infrastructure incidents and lessons

Historical synthesis from live `deploy/docker/INCIDENT-2026-08-29.md`, `INCIDENT-2026-08-30.md`, `ADDRESS-POOLS.md`, `deploy/storage/ENCLOSURE-MIGRATION.md`, and BookStack pages 35, 80–83. No historical repair commands were executed or imported as an automated remedy.

August 29: Docker address-pool work caused outages involving stale network IDs, allocator failure and orphan bridge interfaces. Reboot/rollback did not reliably restore reachability. Later notes record resolution of the IMAX/libvirt subnet collision; an earlier design still calls it open. Updating default address pools does not renumber existing Docker networks. Restoring daemon configuration alone is not a full rollback of changed container/network state.

The incident also exposed CWA SQLite WAL/SHM paths becoming directories through bind-mount timing. An apparently present database file does not prove the full SQLite path set is usable. This is historical context, not permission to remove sidecars or restart CWA.

August 30: a USB-array disconnect and mount timing exposed an empty Docker root/library view and missing guards. Later September verification records an array enumeration delay exceeding systemd's device timeout; the dependent comics mount did not retry automatically. An `After=` relationship only orders starts that occur, so it is not proof of reboot safety.

The enclosure runbook and firewall/address-pool plans mix completed steps with deferred protections. Keep them as proposals/history until compared with actual host configuration. September recovery later changed the operational situation again; see [the September finding](2026-09-20-recovery.md).
