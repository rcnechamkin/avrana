# BookStack migration index

Every page of the retired BookStack wiki, where it went, and why.

- Source: backup run `2026-10-04T09-33-09Z`, `bookstack/bookstack.sql.zst` and `bookstack/bookstack-uploads.tar.zst`
  (SHA-256 in the Batch 2 ledger), restored into a disposable database with no network. The production
  BookStack was not contacted.
- Latest edit in the wiki: 2026-09-20. Nothing was written to it after the September incident.
- Structure: 3 shelves, 12 books, 3 chapters, 72 pages. `structure.json` holds the full tree.
- History: 350 page revisions. `revisions.tsv` lists each one (date, author, size); the revision
  bodies stay in the SQL dump inside every backup run and are not copied to Git.
- Attachments: 0. Images in pages: 0. The only uploaded image is one user avatar, which is not archived
  here; it remains in `bookstack-uploads.tar.zst`.

| Class | Pages |
|---|---|
| PROMOTE | 31 |
| DUPLICATE | 11 |
| STALE | 6 |
| ARCHIVE | 20 |
| OWNER REVIEW | 4 |
| **Total** | **72** |

- **PROMOTE**: copied into the maintained documentation at the destination shown.
- **DUPLICATE**: the destination already covers it better; only the archived copy is kept.
- **STALE**: kept for history, no longer true.
- **ARCHIVE**: useful history or design material; not current operating documentation.
- **OWNER REVIEW**: needs a decision from Cody.

| Page | Title | Book | Last edited | Class | Destination / better source | Note | Archived copy |
|---|---|---|---|---|---|---|---|
| 7 | Cloudflare and External Access | Infrastructure | 2026-08-29 | PROMOTE | `docs/services/cloudflare-tunnel.md` | - | [07-cloudflare-and-external-access.md](raw/infrastructure/07-cloudflare-and-external-access.md) |
| 14 | Audiobookshelf (ABS) | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/audiobookshelf.md` | - | [14-audiobookshelf-abs.md](raw/services/14-audiobookshelf-abs.md) |
| 15 | Calibre-Web-Automated (CWA) | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/calibre-web-automated.md` | - | [15-calibre-web-automated-cwa.md](raw/services/15-calibre-web-automated-cwa.md) |
| 16 | Shelfmark | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/shelfmark.md` | - | [16-shelfmark.md](raw/services/16-shelfmark.md) |
| 17 | Libation | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/libation.md` | - | [17-libation.md](raw/services/17-libation.md) |
| 18 | Komga, Komf, and Kavita | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/komga.md` | Komf and Kavita are not deployed; their sections are history | [18-komga-komf-and-kavita.md](raw/services/18-komga-komf-and-kavita.md) |
| 19 | mylar3 | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/mylar3.md` | Mylar3 currently has no login (Phase 2 finding A5); restoring it is planned | [19-mylar3.md](raw/services/19-mylar3.md) |
| 20 | Complete Series | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/completeseries.md` | - | [20-complete-series.md](raw/services/20-complete-series.md) |
| 22 | Jellyfin | Services / Video and Requests | 2026-08-24 | PROMOTE | `docs/services/jellyfin.md` | media mounts are read-only today; read docs/findings/2026-09-23-jellyfin-artwork.md before maintenance | [22-jellyfin.md](raw/services/22-jellyfin.md) |
| 23 | Radarr / Sonarr | Services / Video and Requests | 2026-08-21 | PROMOTE | `docs/services/radarr-sonarr.md` | see Phase 2 finding A13 (Supergirl download loop) for a profile problem found later | [23-radarr-sonarr.md](raw/services/23-radarr-sonarr.md) |
| 24 | Prowlarr | Services / Video and Requests | 2026-08-21 | PROMOTE | `docs/services/prowlarr.md` | - | [24-prowlarr.md](raw/services/24-prowlarr.md) |
| 25 | Seerr | Services / Video and Requests | 2026-08-21 | PROMOTE | `docs/services/seerr.md` | - | [25-seerr.md](raw/services/25-seerr.md) |
| 26 | SABnzbd | Services / Video and Requests | 2026-08-28 | PROMOTE | `docs/services/sabnzbd.md` | - | [26-sabnzbd.md](raw/services/26-sabnzbd.md) |
| 28 | Homepage | Services / Platform | 2026-08-21 | PROMOTE | `docs/services/homepage.md` | - | [28-homepage.md](raw/services/28-homepage.md) |
| 31 | Audiobook Pipeline | Pipelines | 2026-08-13 | PROMOTE | `docs/pipelines/audiobook.md` | - | [31-audiobook-pipeline.md](raw/pipelines/31-audiobook-pipeline.md) |
| 32 | Ebook Pipeline | Pipelines | 2026-08-18 | PROMOTE | `docs/pipelines/ebook.md` | - | [32-ebook-pipeline.md](raw/pipelines/32-ebook-pipeline.md) |
| 33 | Ebook and Audiobook Matcher | Pipelines | 2026-08-21 | PROMOTE | `docs/pipelines/ebook-audiobook-matcher.md` | - | [33-ebook-and-audiobook-matcher.md](raw/pipelines/33-ebook-and-audiobook-matcher.md) |
| 37 | First-Run and Default-Credential Checklist | Runbook | 2026-08-21 | PROMOTE | `docs/security/first-run-checklist.md` | - | [37-first-run-and-default-credential-checklist.md](raw/runbook/37-first-run-and-default-credential-checklist.md) |
| 42 | Authentik & SSO | Services / Platform | 2026-08-28 | PROMOTE | `docs/services/authentik.md` | 13 blueprints were re-applied during the September recovery and have not been audited | [42-authentik-sso.md](raw/services/42-authentik-sso.md) |
| 45 | Welcome to Avrana | Member Onboarding | 2026-09-10 | PROMOTE | `docs/onboarding/welcome.md` | member-facing text | [45-welcome-to-avrana.md](raw/member-onboarding/45-welcome-to-avrana.md) |
| 46 | Running the onboarding beta (admin) | Member Onboarding | 2026-08-21 | PROMOTE | `docs/onboarding/admin-onboarding.md` | - | [46-running-the-onboarding-beta-admin.md](raw/member-onboarding/46-running-the-onboarding-beta-admin.md) |
| 47 | Avrana Portal: avrana.net | Services / Platform | 2026-08-28 | PROMOTE | `docs/services/avrana-portal.md` | - | [47-avrana-portal-avrananet.md](raw/services/47-avrana-portal-avrananet.md) |
| 62 | Kern HQ: Home Assistant | Kern HQ: Home Assistant | 2026-08-21 | PROMOTE | `docs/services/home-assistant.md` | Home Assistant runs in production under the name Kern HQ | [62-kern-hq-home-assistant.md](raw/kern-hq-home-assistant/62-kern-hq-home-assistant.md) |
| 67 | IMAX framing verification | Services | 2026-08-21 | PROMOTE | `docs/services/imax-verify.md` | - | [67-imax-framing-verification.md](raw/services/67-imax-framing-verification.md) |
| 70 | Shelfarr | Services | 2026-08-29 | PROMOTE | `docs/services/shelfarr.md` | - | [70-shelfarr.md](raw/services/70-shelfarr.md) |
| 71 | Omnibus | Services / Books and Audio | 2026-08-21 | PROMOTE | `docs/services/omnibus.md` | - | [71-omnibus.md](raw/services/71-omnibus.md) |
| 72 | Tracearr | Services / Video and Requests | 2026-08-24 | PROMOTE | `docs/services/tracearr.md` | - | [72-tracearr.md](raw/services/72-tracearr.md) |
| 74 | Beszel | Services / Platform | 2026-08-22 | PROMOTE | `docs/services/beszel.md` | page had no Markdown source; converted from HTML | [74-beszel.md](raw/services/74-beszel.md) |
| 76 | Authentik sessions & passkeys | Services | 2026-08-28 | PROMOTE | `docs/services/authentik-sessions-passkeys.md` | - | [76-authentik-sessions-passkeys.md](raw/services/76-authentik-sessions-passkeys.md) |
| 77 | Avrana SSO Architecture | Services | 2026-08-28 | PROMOTE | `docs/services/sso-architecture.md` | - | [77-avrana-sso-architecture.md](raw/services/77-avrana-sso-architecture.md) |
| 78 | UniFi OS Server | Services | 2026-08-28 | PROMOTE | `docs/services/unifi-os-server.md` | UniFi is in no backup; see BOOTSTRAP.md | [78-unifi-os-server.md](raw/services/78-unifi-os-server.md) |
| 2 | Host & Access | Infrastructure | 2026-08-29 | DUPLICATE | `BOOTSTRAP.md`, `docs/ARCHITECTURE.md` | host facts re-verified 2026-10-04; page still lists the retired health API | [02-host-access.md](raw/infrastructure/02-host-access.md) |
| 3 | Storage Layout | Infrastructure | 2026-08-28 | DUPLICATE | `docs/STORAGE.md` | paths current; capacity figures and Kavita reference are old | [03-storage-layout.md](raw/infrastructure/03-storage-layout.md) |
| 4 | Compose Layout and Conventions | Infrastructure | 2026-08-21 | DUPLICATE | `BOOTSTRAP.md`, `docs/DEPLOYMENT.md` | project names, profiles and Compose version are now recorded from the live host | [04-compose-layout-and-conventions.md](raw/infrastructure/04-compose-layout-and-conventions.md) |
| 5 | Service and Port Map | Infrastructure | 2026-08-29 | DUPLICATE | `docs/SERVICES.md`, `deploy/host/cloudflared/config.yml` | port map replaced by one generated from the compose files | [05-service-and-port-map.md](raw/infrastructure/05-service-and-port-map.md) |
| 8 | Backups and Recovery | Infrastructure | 2026-08-29 | DUPLICATE | `services/backups/README.md`, `docs/BACKUPS.md` | describes 10 components and the old restore test; superseded | [08-backups-and-recovery.md](raw/infrastructure/08-backups-and-recovery.md) |
| 21 | BookStack | Services / Books and Audio | 2026-08-21 | DUPLICATE | `docs/archive/bookstack/README.md` | BookStack itself is being retired | [21-bookstack.md](raw/services/21-bookstack.md) |
| 43 | Audible Sync Connector | Services / Books and Audio | 2026-08-21 | DUPLICATE | `services/avrana-audible-connector/README.md` | the service README is the maintained copy | [43-audible-sync-connector.md](raw/services/43-audible-sync-connector.md) |
| 48 | OliveTin Operations Console | Services / Platform | 2026-08-21 | DUPLICATE | `services/olivetin/README.md` | the service README is the maintained copy | [48-olivetin-operations-console.md](raw/services/48-olivetin-operations-console.md) |
| 79 | Host firewall (ufw) — design and rollback | Infrastructure | 2026-08-29 | DUPLICATE | `deploy/ufw/README.md` | the firewall is staged and has never been applied | [79-host-firewall-ufw-design-and-rollback.md](raw/infrastructure/79-host-firewall-ufw-design-and-rollback.md) |
| 80 | Incident 2026-08-29 — address-pool outage, reboot relapse, recovery | Runbook | 2026-08-30 | DUPLICATE | `docs/incidents/2026-08-29-docker-address-pools.md` | the incident report in Git is the fuller copy | [80-incident-2026-08-29-address-pool-outage-reboot-relapse-recovery.md](raw/runbook/80-incident-2026-08-29-address-pool-outage-reboot-relapse-recovery.md) |
| 82 | Audit and DR tabletop, 2026-08-30 | Runbook | 2026-08-31 | DUPLICATE | `docs/audits/2026-08-30-disaster-recovery-tabletop.md`, `docs/audits/2026-08-30-forensic-audit.md` | wiki summary of the audits kept in Git | [82-audit-and-dr-tabletop-2026-08-30.md](raw/runbook/82-audit-and-dr-tabletop-2026-08-30.md) |
| 9 | Upgrade Procedure | Infrastructure | 2026-08-21 | STALE | - | upgrade steps written for the pre-recovery layout (Compose v1, Kavita) | [09-upgrade-procedure.md](raw/infrastructure/09-upgrade-procedure.md) |
| 27 | Plex (retiring) | Services / Video and Requests | 2026-08-21 | STALE | - | Plex is documented as retiring; it is still installed and scheduled for retirement | [27-plex-retiring.md](raw/services/27-plex-retiring.md) |
| 29 | Health API: 8240 — RETIRED | Services / Platform | 2026-08-29 | STALE | - | the health API was retired on 2026-08-28 | [29-health-api-8240-retired.md](raw/services/29-health-api-8240-retired.md) |
| 35 | Known Issues | Runbook | 2026-09-09 | STALE | - | issue list frozen on 2026-09-09; superseded by the Phase 1 and Phase 2 reports | [35-known-issues.md](raw/runbook/35-known-issues.md) |
| 36 | Roadmap and Open Work | Runbook | 2026-08-29 | STALE | - | roadmap frozen on 2026-08-29; superseded by docs/ROADMAP.md | [36-roadmap-and-open-work.md](raw/runbook/36-roadmap-and-open-work.md) |
| 81 | Docker address pools — v2 design | Infrastructure | 2026-08-29 | STALE | - | address-pool design that was abandoned after the 2026-08-29 incident | [81-docker-address-pools-v2-design.md](raw/infrastructure/81-docker-address-pools-v2-design.md) |
| 6 | Docker Hardening and Networking | Infrastructure | 2026-08-29 | ARCHIVE | - | hardening conventions as designed in August; not re-audited per service | [06-docker-hardening-and-networking.md](raw/infrastructure/06-docker-hardening-and-networking.md) |
| 39 | 2026-08-13: Initial Deployment | Change Log (Archive) | 2026-08-21 | ARCHIVE | - | change log | [39-2026-08-13-initial-deployment.md](raw/change-log-archive/39-2026-08-13-initial-deployment.md) |
| 40 | 2026-08-13: Documentation Deployment | Change Log (Archive) | 2026-08-21 | ARCHIVE | - | change log | [40-2026-08-13-documentation-deployment.md](raw/change-log-archive/40-2026-08-13-documentation-deployment.md) |
| 55 | Project Overview and Naming | Kern: Overview | 2026-09-09 | ARCHIVE | - | Kern project design | [55-project-overview-and-naming.md](raw/kern-overview/55-project-overview-and-naming.md) |
| 56 | Architecture and Boundaries | Kern: Overview | 2026-08-21 | ARCHIVE | - | Kern project design | [56-architecture-and-boundaries.md](raw/kern-overview/56-architecture-and-boundaries.md) |
| 57 | Kern and Avrana Relationship | Kern: Overview | 2026-08-21 | ARCHIVE | - | Kern project design | [57-kern-and-avrana-relationship.md](raw/kern-overview/57-kern-and-avrana-relationship.md) |
| 58 | Orchestration and API Principles | Kern: Design Principles | 2026-08-21 | ARCHIVE | - | Kern project design | [58-orchestration-and-api-principles.md](raw/kern-design-principles/58-orchestration-and-api-principles.md) |
| 59 | Identity, Permissions, and Security | Kern: Design Principles | 2026-08-21 | ARCHIVE | - | Kern project design | [59-identity-permissions-and-security.md](raw/kern-design-principles/59-identity-permissions-and-security.md) |
| 60 | State, Events, and Reliability | Kern: Design Principles | 2026-08-21 | ARCHIVE | - | Kern project design | [60-state-events-and-reliability.md](raw/kern-design-principles/60-state-events-and-reliability.md) |
| 61 | Model Gateway Strategy | Kern: Design Principles | 2026-08-21 | ARCHIVE | - | Kern project design | [61-model-gateway-strategy.md](raw/kern-design-principles/61-model-gateway-strategy.md) |
| 63 | Roadmap and Order of Operations | Kern: Roadmap and Infrastructure | 2026-08-24 | ARCHIVE | - | Kern project design | [63-roadmap-and-order-of-operations.md](raw/kern-roadmap-and-infrastructure/63-roadmap-and-order-of-operations.md) |
| 64 | Hardware and Infrastructure Strategy | Kern: Roadmap and Infrastructure | 2026-08-21 | ARCHIVE | - | Kern project design | [64-hardware-and-infrastructure-strategy.md](raw/kern-roadmap-and-infrastructure/64-hardware-and-infrastructure-strategy.md) |
| 65 | Risks and Known Issues | Kern: Risks and Open Questions | 2026-08-21 | ARCHIVE | - | Kern project design | [65-risks-and-known-issues.md](raw/kern-risks-and-open-questions/65-risks-and-known-issues.md) |
| 66 | Open Decisions and Future Research | Kern: Risks and Open Questions | 2026-08-21 | ARCHIVE | - | Kern project design | [66-open-decisions-and-future-research.md](raw/kern-risks-and-open-questions/66-open-decisions-and-future-research.md) |
| 68 | 2026-08-18: Profiles and IMAX Verification | Change Log (Archive) | 2026-08-21 | ARCHIVE | - | change log | [68-2026-08-18-profiles-and-imax-verification.md](raw/change-log-archive/68-2026-08-18-profiles-and-imax-verification.md) |
| 69 | Security audit, 2026-08-20 | Runbook | 2026-08-29 | ARCHIVE | - | dated security audit; superseded by the Phase 1 and Phase 2 reports | [69-security-audit-2026-08-20.md](raw/runbook/69-security-audit-2026-08-20.md) |
| 73 | Session 2026-08-18 to 2026-08-21 | Change Log (Archive) | 2026-08-21 | ARCHIVE | - | change log | [73-session-2026-08-18-to-2026-08-21.md](raw/change-log-archive/73-session-2026-08-18-to-2026-08-21.md) |
| 75 | Kern Tablet: SM-T510 desk companion | Kern: Roadmap and Infrastructure | 2026-08-24 | ARCHIVE | - | Kern project design (tablet) | [75-kern-tablet-sm-t510-desk-companion.md](raw/kern-roadmap-and-infrastructure/75-kern-tablet-sm-t510-desk-companion.md) |
| 83 | Verification pass, 2026-09-08 | Runbook | 2026-09-09 | ARCHIVE | - | verification pass that predates the 2026-09-20 incident | [83-verification-pass-2026-09-08.md](raw/runbook/83-verification-pass-2026-09-08.md) |
| 84 | Kern Quests: Station Interface and Project Metaphor | Kern: Overview | 2026-09-09 | ARCHIVE | - | Kern project design | [84-kern-quests-station-interface-and-project-metaphor.md](raw/kern-overview/84-kern-quests-station-interface-and-project-metaphor.md) |
| 87 | Overview | Avrana Party | 2026-09-20 | OWNER REVIEW | - | Avrana Party is a separate Raspberry Pi project (rcnechamkin/avrana-party); decide whether these move there | [87-overview.md](raw/avrana-party/87-overview.md) |
| 88 | Architecture | Avrana Party | 2026-09-20 | OWNER REVIEW | - | as above | [88-architecture.md](raw/avrana-party/88-architecture.md) |
| 89 | Runbook | Avrana Party | 2026-09-20 | OWNER REVIEW | - | as above | [89-runbook.md](raw/avrana-party/89-runbook.md) |
| 90 | Decisions & Current State | Avrana Party | 2026-09-20 | OWNER REVIEW | - | as above | [90-decisions-current-state.md](raw/avrana-party/90-decisions-current-state.md) |
