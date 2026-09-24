# Decisions and unresolved conflicts

| Decision/evidence | Consequence |
|---|---|
| User direction, 2026-09-23: Git Markdown is the technical source of truth | BookStack remains archive/reference; no agent dependency or Git hook |
| Development and live trees are separate | No Git initialization or blanket import in production |
| Production preservation outranks easier API access | Existing offline wiki export used; no API repair |
| Recovery artifacts are immutable evidence | Analyze private disposable copies only; never clean contamination |
| Source migration is selective | Personal Kern code and runtime state are not imported wholesale |

| Conflict | Evidence / disposition |
|---|---|
| BookStack is described as the primary documentation home in old source/config | Superseded by the user-approved Git-first model; live compose left unchanged |
| Old handoff: 15 stale mounts/6 containers | Later ledger M5: 11/5 after worker maintenance; no fresh inode audit yet |
| Older summaries: Compose v1 limitation | Later ledger M0/M5 records v2.27.1 |
| Wiki: Kern HQ planned | Page 62 and current running Home Assistant demonstrate deployment; larger Kern control plane still not established |
| Wiki: Jellyfin media writable | Current Docker binds are read-only |
| Wiki: backup 10/11 components | Later recovery ledger records 24; old restoration claims remain historical |
| Jellyfin DB restored and healthy implies complete recovery | False for artwork: metadata excluded from backup and image refs/files diverge |
| Movies library `/mnt` path | Not backed by current container bind; do not silently remove before assessing item identity effects |
| Early address-pool document: collision still live | Later August 29 incident records its resolution |
| Firewall draft: existing bridges renumber | Later incident/design says existing networks retain subnets |
| Backup README only mentions free-space guard | Later incident records a mount guard; current coverage requires source review |
| Off-host setup built/tested versus off-host backup absent | Implementation and actual provisioning are different; no operational off-host copy established |

Do not resolve uncertainty by copying newer-looking text without evidence. Record observation date, source and whether the statement is live-verified, historical or proposed.
