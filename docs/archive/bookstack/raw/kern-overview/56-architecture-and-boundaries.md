---
bookstack_page_id: 56
title: "Architecture and Boundaries"
shelf: "Kern"
book: "Kern: Overview"
chapter: ""
created: 2026-08-18 01:46:08
updated: 2026-08-21 00:15:53
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Architecture and Boundaries
# Architecture and Boundaries

**Status: planned architecture.**

## Intended shape

```text
Interfaces
├─ Kern HQ / Home Assistant Voice
├─ Avrana web/mobile interfaces
└─ future interfaces
          ↓
        KERN
 orchestration/control plane
          ↓
 ┌────────┼─────────┐
 │        │         │
Avrana   Home     future
        Assistant  subsystems
```

Two things to read carefully in that diagram:

1. **Home Assistant appears twice, in two different roles.** As *Kern HQ / Home Assistant Voice*
   it is an **interface**: a way a person talks to the system. As *Home Assistant* in the lower
   row it is a **subsystem** Kern controls. These are separate concerns and should not be
   collapsed.
2. **Interfaces never reach subsystems directly.** A voice command does not call Sonarr. It calls
   Kern, and Kern calls Avrana.

## The layer rule

Kern is a **deterministic** control layer. Given a validated structured action, its behaviour is
predictable, repeatable and auditable. No part of Kern's business logic may depend on a model
returning the right answer.

Language models sit **above** Kern and do exactly one job: turn fuzzy human input into a
*candidate structured action*. Kern then validates, authorizes, executes and records it.

```text
"Make sure the newest Ted Lasso is on Avrana"
        ↓
voice/STT
        ↓
LLM interprets intent
        ↓
Kern validates structured action
        ↓
Avrana performs deterministic checks/actions
        ↓
Kern tracks resulting state
```

The model produced a *proposal*. Kern decided whether it was legal, permitted, and safe, then
carried it out. If the model had produced nonsense, validation is what stops i: not prompt
wording.

## The hard requirement

> **The architecture must continue functioning if every external LLM provider disappears.**

This is a design constraint, not an aspiration. It means:

- every capability must be reachable through a non-language interface (API, web, button),
- losing the model layer degrades *convenience*, never *function*,
- no state, no scheduling and no recovery path may live inside a model or a prompt.

If a feature cannot be operated without the model, it does not meet this requirement.

## Ownership boundaries

| Concern | Owner |
|---|---|
| Interpreting natural language | Model gateway (above Kern) |
| Validating and authorizing an action | **Kern** |
| Executing media operations | Avrana subsystem |
| Executing smart-home operations | Home Assistant subsystem |
| Knowing what happened and when | **Kern** |
| Presenting things to a person | Interfaces |

## Explicit non-goal

**Home Assistant must not become the orchestrator.** It is attractive to put orchestration in HA because
its automation engine is right there and already speaks to devices. Resist i: HA automations are
hard to test, hard to version, and would scatter cross-subsystem logic into a place where media
operations do not belong. Kern HQ is a client of Kern like any other interface.

## Open decisions

- Whether Kern is one service or a small set of services (API, worker, event store).
- Transport between Kern and subsystems (direct HTTP vs a queue).
- Whether Kern owns its own datastore from day one, or borrows an existing one.

These belong in *Open Decisions / Future Research*: do not settle them by writing code.
