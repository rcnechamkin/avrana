# BookStack offline knowledge inventory

Source: existing rescued export `/mnt/avrana_media/recovery-20260920/bookstack-live/bookstackapp-live-20260921T043826Z.sql`, parsed as text on 2026-09-23. No SQL was executed. Only entity/page/container content was parsed; authentication tables were not extracted. Raw SQL, page bodies and private working data remain outside Git. API access is unestablished, not diagnosed as broken. No production API or DB inspection was needed.

The export contains 90 entities: 12 books, 3 chapters, 72 pages and 3 shelves; none of those entity rows are marked deleted. This is an export-time inventory, not proof of current live counts. Recovery comparison reports identical morning/rescued tables. Later wiki edits, if any, are outside this source.

Classification applies to selected claims, not a guarantee that an entire page is currently correct. CURRENT means limited corroboration noted below; UNCLEAR means not independently verified. DUPLICATED denotes topic overlap, not byte equality. No whole-page verbatim import was made.

## Containers

| Type | ID | Name | Parent book |
|---|---|---|---|
| book | 1 | Infrastructure | — |
| book | 10 | Services | — |
| chapter | 11 | Books and Audio | Services |
| chapter | 12 | Video and Requests | Services |
| chapter | 13 | Platform | Services |
| book | 30 | Pipelines | — |
| book | 34 | Runbook | — |
| book | 38 | Change Log (Archive) | — |
| bookshelf | 41 | Avrana Homelab | — |
| book | 44 | Member Onboarding | — |
| book | 49 | Kern: Overview | — |
| book | 50 | Kern: Design Principles | — |
| book | 51 | Kern HQ: Home Assistant | — |
| book | 52 | Kern: Roadmap and Infrastructure | — |
| book | 53 | Kern: Risks and Open Questions | — |
| bookshelf | 54 | Kern | — |
| bookshelf | 85 | Avrana Party | — |
| book | 86 | Avrana Party | — |

## Pages

| ID | Page | Updated in export | Classification | Destination / reason |
|---|---|---|---|---|
| 2 | Host & Access | 2026-08-29 11:24:51 | CURRENT / UNCLEAR | ARCHITECTURE, NETWORKING: Host/LAN facts corroborated; exposure/firewall claims need fresh audit |
| 3 | Storage Layout | 2026-08-29 06:35:00 | CURRENT / STALE | STORAGE: Paths corroborated; historical capacity/free-space figures superseded |
| 4 | Compose Layout and Conventions | 2026-08-21 07:15:45 | CURRENT / UNCLEAR | DEPLOYMENT: Independent Compose layout corroborated; full conventions not re-audited |
| 5 | Service and Port Map | 2026-08-29 11:24:52 | DUPLICATED / STALE | SERVICES: Replaced by fresh Docker endpoint inventory; host services separately qualified |
| 6 | Docker Hardening and Networking | 2026-08-29 10:35:42 | HISTORICAL BUT USEFUL | NETWORKING, SECURITY: Hardening/network claims must be checked per service |
| 7 | Cloudflare and External Access | 2026-08-29 11:04:02 | UNCLEAR | NETWORKING: Tunnel relationships retained as historical; DNS/routes not reverified |
| 8 | Backups and Recovery | 2026-08-29 10:35:23 | STALE / CONTRADICTED | BACKUPS: Component counts superseded; metadata exclusion explains incomplete artwork restore |
| 9 | Upgrade Procedure | 2026-08-21 07:15:00 | HISTORICAL BUT USEFUL | DEPLOYMENT: Upgrade instructions not executable authorization |
| 14 | Audiobookshelf (ABS) | 2026-08-21 07:15:01 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 15 | Calibre-Web-Automated (CWA) | 2026-08-21 07:15:01 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 16 | Shelfmark | 2026-08-21 07:15:01 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 17 | Libation | 2026-08-21 07:15:02 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 18 | Komga, Komf, and Kavita | 2026-08-21 07:15:02 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 19 | mylar3 | 2026-08-21 07:15:02 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 20 | Complete Series | 2026-08-21 07:15:03 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 21 | BookStack | 2026-08-21 07:15:03 | CURRENT / STALE | SERVICES, DECISIONS: Deployment tags corroborated; wiki-authoritative role superseded |
| 22 | Jellyfin | 2026-08-25 03:10:59 | CONTRADICTED / HISTORICAL BUT USEFUL | Jellyfin finding: Current media read-only, not writable; playback observations remain historical |
| 23 | Radarr / Sonarr | 2026-08-21 07:15:04 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 24 | Prowlarr | 2026-08-21 07:15:04 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 25 | Seerr | 2026-08-21 07:15:05 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 26 | SABnzbd | 2026-08-29 06:35:00 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 27 | Plex (retiring) | 2026-08-21 07:15:05 | STALE | Archive: Retiring service; no current Docker presence established |
| 28 | Homepage | 2026-08-21 07:15:06 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 29 | Health API: 8240 — RETIRED | 2026-08-29 11:04:01 | HISTORICAL BUT USEFUL | DECISIONS: Retired API; not a current onboarding dependency |
| 31 | Audiobook Pipeline | 2026-08-14 04:28:52 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 32 | Ebook Pipeline | 2026-08-18 08:09:58 | HISTORICAL BUT USEFUL | STORAGE: Transient inbox/deletion and acquisition false-match caveats retained; workflow not retested |
| 33 | Ebook and Audiobook Matcher | 2026-08-21 07:15:48 | HISTORICAL BUT USEFUL | SERVICES: Identifier/title matching order and ambiguity caveat retained; matcher source not imported |
| 35 | Known Issues | 2026-09-09 09:25:36 | STALE / HISTORICAL BUT USEFUL | DECISIONS, findings: Mixed dates and completed/unfinished actions; later ledger prevails |
| 36 | Roadmap and Open Work | 2026-08-29 11:42:36 | STALE | ROADMAP: Superseded by September recovery priorities |
| 37 | First-Run and Default-Credential Checklist | 2026-08-21 07:15:50 | HISTORICAL BUT USEFUL | SECURITY: Principles only; no credential values imported |
| 39 | 2026-08-13: Initial Deployment | 2026-08-21 07:15:51 | HISTORICAL BUT USEFUL | Archive: Initial deployment history |
| 40 | 2026-08-13: Documentation Deployment | 2026-08-21 07:15:51 | HISTORICAL BUT USEFUL | Archive: Prior documentation deployment model |
| 42 | Authentik & SSO | 2026-08-29 00:05:14 | CURRENT / UNCLEAR | SECURITY, SERVICES: Identity role corroborated; per-app details not retested |
| 43 | Audible Sync Connector | 2026-08-21 07:15:08 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 45 | Welcome to Avrana | 2026-09-10 09:38:14 | UNCLEAR | Archive: Member-facing material remains wiki archive |
| 46 | Running the onboarding beta (admin) | 2026-08-21 07:15:09 | HISTORICAL BUT USEFUL | Archive: Onboarding beta procedures require review before use |
| 47 | Avrana Portal: avrana.net | 2026-08-29 00:05:15 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 48 | OliveTin Operations Console | 2026-08-21 07:15:53 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 55 | Project Overview and Naming | 2026-09-09 10:17:13 | CONTRADICTED | ARCHITECTURE, DECISIONS: Kern HQ planned claim conflicts with page62 and running HA |
| 56 | Architecture and Boundaries | 2026-08-21 07:15:53 | HISTORICAL BUT USEFUL | Archive: Planned control-plane architecture, not deployed truth |
| 57 | Kern and Avrana Relationship | 2026-08-21 07:15:54 | HISTORICAL BUT USEFUL | ARCHITECTURE: Avrana subsystem boundary; larger orchestration is planned |
| 58 | Orchestration and API Principles | 2026-08-21 07:15:55 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 59 | Identity, Permissions, and Security | 2026-08-21 07:15:55 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 60 | State, Events, and Reliability | 2026-08-21 07:15:56 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 61 | Model Gateway Strategy | 2026-08-21 07:15:56 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 62 | Kern HQ: Home Assistant | 2026-08-21 07:15:13 | CURRENT / UNCLEAR | ARCHITECTURE: Home Assistant container corroborated; historical version not assumed current |
| 63 | Roadmap and Order of Operations | 2026-08-25 03:10:58 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 64 | Hardware and Infrastructure Strategy | 2026-08-21 07:15:58 | HISTORICAL BUT USEFUL | Archive: Hardware strategy is not an applied change |
| 65 | Risks and Known Issues | 2026-08-21 07:15:59 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 66 | Open Decisions and Future Research | 2026-08-21 07:15:59 | HISTORICAL BUT USEFUL | Archive / SECURITY principles: Planned Kern design; no implementation implied |
| 67 | IMAX framing verification | 2026-08-21 07:15:15 | CURRENT / UNCLEAR | SERVICES, source: Verifier exists; source imported, historical performance not rerun |
| 68 | 2026-08-18: Profiles and IMAX Verification | 2026-08-21 07:16:00 | HISTORICAL BUT USEFUL | Archive: Profiles/IMAX experiment history |
| 69 | Security audit, 2026-08-20 | 2026-08-29 11:24:50 | HISTORICAL BUT USEFUL | SECURITY: Dated audit, not a new security assessment |
| 70 | Shelfarr | 2026-08-29 10:34:53 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 71 | Omnibus | 2026-08-22 05:56:45 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 72 | Tracearr | 2026-08-25 03:22:00 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 73 | Session 2026-08-18 to 2026-08-21 | 2026-08-22 05:56:46 | HISTORICAL BUT USEFUL | Archive: Dated session record |
| 74 | Beszel | 2026-08-23 01:28:33 | UNCLEAR | SERVICES / archive: Service/topic inventoried; only corroborated relationship summaries incorporated |
| 75 | Kern Tablet: SM-T510 desk companion | 2026-08-25 03:10:21 | UNCLEAR | Archive: Separate tablet/hardware scope not inspected |
| 76 | Authentik sessions & passkeys | 2026-08-28 23:43:56 | DUPLICATED / UNCLEAR | SECURITY: Overlaps identity pages42/77; no live policy audit |
| 77 | Avrana SSO Architecture | 2026-08-29 00:05:01 | DUPLICATED / UNCLEAR | SECURITY: Overlaps identity pages42/76; newer blueprint effects unresolved |
| 78 | UniFi OS Server | 2026-08-29 06:36:34 | UNCLEAR | SERVICES: Host Podman service, not Docker; live validation deferred |
| 79 | Host firewall (ufw) — design and rollback | 2026-08-29 11:42:14 | HISTORICAL BUT USEFUL | NETWORKING: Firewall design, not authorization or verified deployment |
| 80 | Incident 2026-08-29 — address-pool outage, reboot relapse, recovery | 2026-08-30 09:24:24 | HISTORICAL BUT USEFUL | August finding: Overlaps source incident report; synthesized once |
| 81 | Docker address pools — v2 design | 2026-08-30 00:06:23 | STALE / HISTORICAL BUT USEFUL | August finding: Unapplied/superseded design claims |
| 82 | Audit and DR tabletop, 2026-08-30 | 2026-08-31 07:49:02 | HISTORICAL BUT USEFUL | August finding: Dated tabletop; later corrections matter |
| 83 | Verification pass, 2026-09-08 | 2026-09-09 09:25:21 | HISTORICAL BUT USEFUL | August/September findings: Sept8 verification predates deletion/recovery |
| 84 | Kern Quests: Station Interface and Project Metaphor | 2026-09-09 10:37:28 | HISTORICAL BUT USEFUL | Archive: Planned interface/metaphor; not deployed media architecture |
| 87 | Overview | 2026-09-20 07:39:17 | UNCLEAR | Archive / ARCHITECTURE boundary: Separate Avrana Party Pi project; not inspected or migrated |
| 88 | Architecture | 2026-09-20 07:39:17 | UNCLEAR | Archive / ARCHITECTURE boundary: Separate Avrana Party Pi project; not inspected or migrated |
| 89 | Runbook | 2026-09-20 07:39:17 | UNCLEAR | Archive / ARCHITECTURE boundary: Separate Avrana Party Pi project; not inspected or migrated |
| 90 | Decisions & Current State | 2026-09-20 07:39:18 | UNCLEAR | Archive / ARCHITECTURE boundary: Separate Avrana Party Pi project; not inspected or migrated |

## Knowledge incorporated

Host/development boundaries; media and durable-state layout; service roles and pipeline relationships; identity boundaries; BookStack deployment and preservation requirements; backup coverage limitations; August mount/network lessons; Kern versus Avrana versus Avrana Party scope. Each current document labels direct observations separately from archived descriptions.

## Left archival

Member onboarding copy, credential-related procedures, dated playback measurements, personal/household design plans, party-device operating commands, old upgrade/restore instructions and unverified hardening claims remain archival. No user data, page revision bodies, attachments, uploaded images, tokens, account tables or full database exports were imported. BookStack itself remains unchanged.
