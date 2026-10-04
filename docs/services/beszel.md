# Beszel

> Promoted from the BookStack wiki on 2026-10-04 (page 74, "Beszel", last edited 2026-08-22) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: page had no Markdown source; converted from HTML.
> Original: [archive](../../docs/archive/bookstack/raw/services/74-beszel.md).

Beszel provides lightweight monitoring for the Avrana host and its Docker containers. It is available only on the local network. 

## Access  
| Interface | Address |
| --- | --- | 
| Hub | `http://10.0.0.218:8093` | 
| Hub container port | `8090/tcp` | 
| Docker proxy | `127.0.0.1:2376`, host loopback only | 
| Agent transport | `/beszel_socket/beszel.sock`, Unix socket |  

## Architecture  
- `beszel` stores configuration, alerts, users, and historical metrics. 
- `beszel-agent` collects host, filesystem, network, sensor, uptime, and Docker metrics. 
- `beszel-socket-proxy` provides filtered read-only access to the Docker API. 
- QuarterMaster links to the hub and reports its container and HTTP status.  

## Security model 

The hub binds to `10.0.0.218:8093` and is not routed through Cloudflare. The agent runs as UID and GID 1000 with all Linux capabilities removed. It has no direct Docker socket mount. The socket proxy permits only container, daemon information, ping, and version GET requests. POST requests are disabled. Its TCP listener is bound to host loopback. 

Filesystem monitoring uses empty marker directories on the root and media filesystems. The agent cannot read the rest of either filesystem. Hub and agent credentials are stored below `services/beszel/` with mode 0600 and are excluded from version control. 

## Metrics  
- Host CPU, per-core use, load averages, RAM, swap, and uptime 
- Root and media filesystem capacity, read and write throughput, and byte counters 
- Physical network-interface send and receive rates 
- Container CPU, RAM, network traffic, status, and uptime 
- CPU package and core temperatures  

The Docker proxy enables automatic discovery of existing and future containers. 

### Unavailable metrics 

The host Intel HD Graphics 530 was detected and tested. Intel collection requires performance-counter access, but the host uses `kernel.perf_event_paranoid=4`. The safe non-root agent cannot collect these counters. GPU collection is disabled to prevent recurring log errors. Do not lower the kernel setting solely for monitoring. 

SMART is disabled. Beszel's container method requires raw block-device mappings plus `SYS_RAWIO` and `SYS_ADMIN`. These privileges are not justified for a monitoring container. Filesystem capacity and disk I/O remain available. 

## Health and resilience  
- The hub and agent use Beszel's built-in health commands every 120 seconds. 
- The socket proxy checks Docker's ping endpoint every 60 seconds. 
- All components use `restart: unless-stopped`. 
- The main Avrana health script checks `/api/health`.  

## Persistence and backups 

Hub state is in `services/beszel/data`. Agent identity is in `services/beszel/agent-data`. Credentials are in `services/beszel/secrets`. The nightly Avrana backup archives these paths as `beszel/beszel-state.tar.zst`. Restoring the archive preserves systems, users, alerts, history, and the agent identity. 

## Alerts  
| Condition | Threshold | Duration |
| --- | --- | --- | 
| Host unavailable | Down | 5 minutes | 
| Filesystem usage | 90 percent | 10 minutes | 
| Host CPU usage | 90 percent | 15 minutes | 
| Host memory usage | 90 percent | 15 minutes |  

These thresholds detect sustained faults while ignoring normal short workload bursts. 

## Troubleshooting 

```
cd /home/cody/avrana/services/beszel
docker compose config -q
docker compose ps
docker compose logs --since 30m
curl -fsS http://10.0.0.218:8093/api/health
```
 

If the host is offline in Beszel, verify that both hub and agent mount `./socket` and that the system host is `/beszel_socket/beszel.sock`. If containers are absent, verify `curl http://127.0.0.1:2376/_ping` on the host and inspect the socket-proxy health state.
