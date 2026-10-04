---
bookstack_page_id: 66
title: "Open Decisions and Future Research"
shelf: "Kern"
book: "Kern: Risks and Open Questions"
chapter: ""
created: 2026-08-18 01:49:00
updated: 2026-08-21 00:15:59
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Open Decisions and Future Research
# Open Decisions and Future Research

**Status: explicitly undecided.** Listed so future sessions can tell "not yet decided" from
"decided and undocumented".

**Do not resolve any of these by writing an implementation.** If one gets decided, record the
decision and the reasoning here, then update the relevant page.

## Kern shape and contracts

- One service, or several (API, worker, event store)?
- Contract style: REST, RPC, or an internal command bus?
- Does Kern own a datastore from day one?
- Transport to subsystems: direct HTTP, or a queue?
- Idempotency keys: caller-supplied, derived, or both?
- Audit retention period.

## State and events

- Event transport, and whether events are persisted or fire-and-forget.
- Full event history, or current state plus recent transitions?
- Reconciliation cadence, and what it is allowed to correct automatically.
- The authoritative source for each fac: needs a written table, per roadmap step 2.

## Identity and authorization

- What the trust tiers are, and which action classes each may reach.
- How a shared voice device escalates to a proven identity when needed.
- Whether per-person voice devices are worth it versus confirmation in an app.
- What may be sent to an external model provider. Media titles are probably fine; household
  routines and identities need a deliberate decision.

## Model gateway

- Which interactions justify a model at all: many are better as buttons.
- Stateless per-utterance, or conversation context?
- How clarifying questions are represented in the contract.
- Whether a local model is ever worth it, versus cloud-backed with good isolation.

## Kern HQ

- Home Assistant deployment shape: container on the existing host, or dedicated appliance?
- Wake-word and STT component choices.
- Number and placement of voice devices.
- Does HA keep autonomous automations, or defer everything cross-subsystem to Kern?

## Infrastructure

- UPS model, runtime target, and covered devices.
- Off-host backup destination.
- What measurement would justify a compute upgrade: worth defining the threshold before the
  upgrade is proposed.

## Future subsystems

- What comes after media and smart-home? Nothing is committed.
- What is the bar for something becoming a Kern subsystem rather than a standalone service?

## Deliberately not open

For clarity, these are **settled**:

- Avrana keeps its name and its documentation.
- Kern HQ is an interface and subsystem, not the orchestrator.
- Models interpret; Kern validates and executes.
- The system must keep functioning with no external LLM provider.
- Avrana stabilises before Kern gains authority over it.
