---
bookstack_page_id: 55
title: "Project Overview and Naming"
shelf: "Kern"
book: "Kern: Overview"
chapter: ""
created: 2026-08-18 01:46:08
updated: 2026-09-09 03:17:13
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-09; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Project Overview and Naming
# Kern

**Status: planned.** Nothing called "Kern" is deployed yet. This shelf describes the intended
shape of the system so that later work does not have to re-derive it. The one part of the
ecosystem that is real and running today is **Avrana**, documented on its own shelf.

## The three names, used consistently

| Name | What it means | Status today |
|---|---|---|
| **Kern** | Umbrella for the entire self-hosted server ecosystem, and the eventual orchestration / control plane that ties subsystems together. | Planned |
| **Kern HQ** | The Home Assistant portion of Kern: smart-home control, voice interfaces, household automation, Home Assistant Voice Preview Edition. | Planned, not deployed |
| **Avrana** | The **media subsystem** beneath Kern: Jellyfin, Seerr, Sonarr, Radarr, Audiobookshelf, Komga, Calibre-Web-Automated, media acquisition and management, media-specific notifications. | Running, most developed part |

These boundaries are deliberate. Use them exactly.

- Avrana is **not** being renamed. Existing Avrana documentation stays where it is, on the
  [Avrana Homelab](http://10.0.0.218:6875/shelves/avrana-homelab) shelf.
- Kern HQ is **a subsystem and an interface**, not the orchestrator. See
  *Architecture & Boundaries*.
- Anything that is not media and not smart-home is a "future subsystem" until it is named.

## What Kern is for

Today each service is administered directly and independently. That works, but it means every
new capability is wired point-to-point, and any natural-language layer would have to speak
directly to Sonarr, Seerr, Home Assistant and the rest.

Kern exists to provide **one stable, deterministic control and API layer** over the subsystems,
so that:

- interfaces (voice, web, mobile, future) target Kern rather than individual services,
- upstream API changes are absorbed in one place instead of rippling outward,
- actions are validated, authorized, logged and recoverable in a consistent way,
- language models can be added **above** that layer without being trusted to run it.

## Reading order for a new session

1. This page.
2. *Architecture & Boundaries*: the diagram and the layer rules.
3. *Kern ↔ Avrana Relationship*: how the running system fits underneath.
4. *Kern: Design Principles*: the constraints any implementation must satisfy.
5. *Kern: Roadmap & Infrastructure*: what order to build in, and what not to buy yet.
6. *Kern: Risks & Open Questions*: what is deliberately undecided.
7. *Kern Quests: Station Interface and Project Metaphor*: the design concept for Kern's
   presentation layer and its first practical application. Section 14 of that page records
   where the concept currently contradicts this shelf.

## How to read status labels

This shelf separates three things on purpose. Keep them separate when editing:

- **Current state**: verified as true of the running system.
- **Planned architecture**: agreed direction, not yet built.
- **Open decision**: genuinely undecided. Do not resolve one by writing an implementation.
