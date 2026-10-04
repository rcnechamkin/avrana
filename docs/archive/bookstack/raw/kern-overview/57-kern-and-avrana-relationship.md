---
bookstack_page_id: 57
title: "Kern and Avrana Relationship"
shelf: "Kern"
book: "Kern: Overview"
chapter: ""
created: 2026-08-18 01:46:09
updated: 2026-08-21 00:15:54
last_editor: "Cody"
revisions: 9
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Kern and Avrana Relationship
# Kern and Avrana Relationship

**Status: Avrana is current state; the Kern layer above it is planned.**

## Avrana is a subsystem, not a peer

Avrana is the media subsystem beneath Kern, and today it is the most developed part of the
ecosystem by a wide margin: it is a working stack with real users, SSO, backups and runbooks.
That maturity is why it is the right first subsystem to sit behind Kern, and also why it must
not be destabilised to get there.

Avrana keeps its own shelf. **Do not duplicate Avrana service documentation here.** Link to it:

| Topic | Where it lives |
|---|---|
| Service and port map | [Service & Port Map](http://10.0.0.218:6875/books/infrastructure/page/service-port-map) |
| Storage layout | [Storage Layout](http://10.0.0.218:6875/books/infrastructure/page/storage-layout) |
| Identity and SSO | [Authentik & SSO](http://10.0.0.218:6875/books/services/page/authentik-sso) |
| Requests | [Seerr](http://10.0.0.218:6875/books/services/page/seerr) |
| Acquisition | [Radarr / Sonarr](http://10.0.0.218:6875/books/services/page/radarr-sonarr), [Prowlarr](http://10.0.0.218:6875/books/services/page/prowlarr), [SABnzbd](http://10.0.0.218:6875/books/services/page/sabnzbd) |
| Playback | [Jellyfin](http://10.0.0.218:6875/books/services/page/jellyfin) |
| Books and comics | [Audiobookshelf](http://10.0.0.218:6875/books/services/page/audiobookshelf-abs), [CWA](http://10.0.0.218:6875/books/services/page/calibre-web-automated-cwa), [Komga](http://10.0.0.218:6875/books/services/page/komga-komf-kavita) |
| Front door | [Avrana Portal](http://10.0.0.218:6875/books/services/page/avrana-portal-avrananet) |
| Backups | [Backups & Recovery](http://10.0.0.218:6875/books/infrastructure/page/backups-recovery) |
| Current work | [Roadmap / Open TODOs](http://10.0.0.218:6875/books/runbook/page/roadmap-open-todos) |
| Traps already paid for | [Known Gotchas](http://10.0.0.218:6875/books/runbook/page/known-gotchas) |

## What Kern will and will not do to Avrana

**Kern will**

- expose media capability through Kern-owned contracts (request a title, check availability,
  report state),
- hold the canonical record of what was asked for, by whom, and what came of it,
- absorb upstream API differences so callers never learn Sonarr's or Seerr's shapes.

**Kern will not**

- replace Seerr, Sonarr, Radarr or Jellyfin,
- become a second place where media state is authoritative,
- require Avrana to be rewritten to participate.

## Why the wrapper matters

A concrete example from the running stack: Seerr's request status is derived from whether its
media-server library scan matched the item. A caller that asked Seerr directly "is this ready?"
would get an answer that depends on scan configuration, not on whether the file is actually
playable. Kern's job is to define what *ready* means once, and to compute it from the service
that is genuinely authoritative for that fact.

See *Orchestration & API Principles* and *State, Events & Reliability*.

## Sequencing

Avrana must be **stable first**. A control plane over a moving target inherits every instability
underneath it and makes the cause harder to see. Concretely: outstanding items on the Avrana
roadmap get finished before Kern gains authority over Avrana.
