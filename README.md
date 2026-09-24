# Avrana

Avrana is the media and related infrastructure stack on host `avrana`. This repository is the development source and technical documentation home; it is not the live deployment directory.

| Location | Role |
|---|---|
| `/home/cody/dev/avrana` | Development checkout; edit and review here |
| `/home/cody/avrana` | Live production tree; inspect cautiously, never initialize Git here |
| `/home/cody/docker` | Additional live service configuration, including Jellyfin |
| `/mnt/avrana_media` | Media, backups, and preserved recovery evidence |
| `rcnechamkin/avrana` | Private GitHub repository; this migration is local and not pushed |

Start with [agent safety](AGENTS.md), [architecture](docs/ARCHITECTURE.md), [services](docs/SERVICES.md), and [operations](docs/OPERATIONS.md). See [the September recovery](docs/findings/2026-09-20-recovery.md) and [Jellyfin artwork investigation](docs/findings/2026-09-23-jellyfin-artwork.md) before any service maintenance.

Git Markdown is the current technical reference; running code/configuration is implementation evidence. Disagreements are recorded in [decisions](docs/DECISIONS.md), not silently resolved. BookStack remains a preserved archive and human-facing wiki. Agents do not need BookStack to understand this checkout.

The source import is deliberately selective: [the initial manifest](docs/findings/source-migration.md) covers 13 files and [the Audible addendum](docs/findings/audible-source-migration.md) covers 28 more. Together they record 41 imported files and their provenance. This is not a complete, independently deployable copy of production. No synchronization, deployment, Git hook, or BookStack publisher is enabled.

Evidence was collected on 2026-09-23 America/Los_Angeles. Historical notes are explicitly labeled. [Remaining work](docs/ROADMAP.md) includes recovery closeout and an approval-gated Jellyfin repair.

See [validation and offline testing](docs/VALIDATION.md) for the final September 24 review, checks performed, and test boundaries.
