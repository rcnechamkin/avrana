---
bookstack_page_id: 60
title: "State, Events, and Reliability"
shelf: "Kern"
book: "Kern: Design Principles"
chapter: ""
created: 2026-08-18 01:47:32
updated: 2026-08-21 00:15:56
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# State, Events, and Reliability
# State, Events, and Reliability

**Status: planned architecture.**

## Define who is authoritative, per fact

Different services will disagree, and the disagreement is usually not a bug: they are answering
different questions. Kern must name, for each kind of fact, **which service is the source of
truth**, and derive everything else from that.

A worked example from the running stack. For "is this show ready to watch?", three services give
three defensible answers:

| Service | What it actually knows |
|---|---|
| Seerr | whether its library scan matched the item |
| Sonarr | whether episode files exist on disk per its metadata source |
| Jellyfin | whether a playable, indexed item exists for a user |

A real case: Sonarr reported a season complete with every file present, while Seerr reported it
partially available: because the two use catalogues that number episodes differently. Neither
was lying. Nobody had decided which one *counts*.

**Rule:** Kern picks one authority per fact and records the others as supporting signals.

## Availability is a lifecycle, not a boolean

Do not equate "Sonarr knows about it" with "ready to watch". Anticipate at least:

```text
requested → searching → downloading → importing → indexed → ready
                                                        ↘ failed
```

Each transition can stall, and stalling is the normal failure mode rather than a crash. An item
sitting in `importing` for a day is a problem that a boolean `available` flag cannot express, and
a user asking "is it ready yet?" deserves a better answer than yes or no.

Kern tracking these states is also what lets it answer *why* something is not ready.

## Partial failure is the default

Any multi-service action can fail halfway: the request was created but the search never started;
the download finished but the import failed; the file landed but the library never re-scanned.

**Rule:** persist enough state to resume or safely abandon. Specifically, before calling a
downstream system Kern should record intent, so that after a crash it can tell the difference
between "never started" and "started, outcome unknown".

Reconciliation matters as much as execution: something must periodically compare Kern's belief
against reality and correct the drift. Not every failure announces itself.

## Retries

Retries interact with idempotency and must be designed together: see
*Orchestration & API Principles*.

- Retry only what is safe to retry.
- Back off; a stuck downstream service should not be hammered.
- Cap attempts and surface a terminal state rather than retrying forever.
- Never retry a destructive action automatically.

## Events

Interfaces should not poll Kern in a loop to find out whether something finished. Kern should
emit state-change events that interfaces subscribe to, which is also what makes
"tell me when it's ready" possible without a language model in the path.

**Open decisions:** event transport, whether events are persisted or fire-and-forget, and whether
Kern exposes a full event history or only current state plus recent transitions.
