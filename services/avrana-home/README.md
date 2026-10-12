# Avrana home: adapter layer

Status: **not deployed, synthetic data only.** Import-only library code and tests. There is no
server, no compose file, no Dockerfile, no hostname, and nothing here is wired into
`services/avrana-portal`. Gates G1 (network isolation) and G2 (authorization suites) have not
passed in production, so nothing in this package may read real member data.

Part of [Avrana Media 2.0](../../docs/design/MEDIA-2.0.md). The written contract is
[`ADAPTER-CONTRACT.md`](../../docs/design/ADAPTER-CONTRACT.md).

- `avrana_home/principal.py`: member identity from trusted edge headers only, fail closed.
- `avrana_home/contract.py`: adapter base class, result types, states, hand-off URL builder.
- `avrana_home/resilience.py`: timeouts, circuit cool-off, transport interface, safe logging.
- `avrana_home/cache.py`: disposable in-memory TTL cache, member-partitioned by API shape.
- `avrana_home/aggregate.py`: independent sections, health summary.
- `avrana_home/adapters/`: one module per upstream (Jellyfin only so far).

Standard library only. Run the tests with `python -B tests/run_offline.py` from the repository
root. No test opens a network socket; upstreams are replaced by a fake transport that serves
hand-written synthetic fixtures.
