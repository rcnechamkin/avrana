# Remaining work

1. Obtain operator approval for a one-item Jellyfin missing-artwork regeneration pilot after preserving current state and defining rollback. No bulk refresh or database replacement. Independent forensic/repair reviews completed; the live-action gate remains unmet because a narrow rollback has not been demonstrated and the selected item/checkpoint/containment plan need approval.
2. Complete service-by-service recovery maintenance and audit the 13 Authentik blueprint applications. Preserve deleted-open state first; then perform the final backup and recovery re-freeze under an approved plan.
3. Improve Jellyfin backup coverage to include metadata assets and a consistent database snapshot; test recovery on disposable copies before deployment. Provision off-host protection and validate remaining backup gaps.
4. Review this local source/documentation import and authorize the initial GitHub push. Expand the explicit source allowlist only after file review; do not import personal history or live config wholesale.
5. Reconcile library paths and verify client-visible artwork after the approved pilot. Preview/trickplay generation is a separate decision from restoring posters.
6. Consider implementing the optional [BookStack publisher](BOOKSTACK-PUBLISHING.md) after local review; activation requires explicit approval. Publishing is unactivated and never required for Git or agent work.

These are tracked proposals, not scheduled jobs or authorization to perform production changes. The most useful immediate operator action is the narrowly scoped Jellyfin pilot decision documented in the artwork finding.
