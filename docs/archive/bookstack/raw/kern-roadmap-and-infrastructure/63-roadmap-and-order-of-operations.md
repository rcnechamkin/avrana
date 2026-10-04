---
bookstack_page_id: 63
title: "Roadmap and Order of Operations"
shelf: "Kern"
book: "Kern: Roadmap and Infrastructure"
chapter: ""
created: 2026-08-18 01:48:59
updated: 2026-08-24 20:10:58
last_editor: "Cody"
revisions: 6
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-24; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Roadmap and Order of Operations
# Roadmap and Order of Operations

**Status: agreed sequence.** The ordering is the poin: several steps are only safe once
earlier ones are done.

## 1. Stabilize the existing Avrana stack

Finish outstanding work on the running system before adding a layer above it. A control plane
over an unstable subsystem inherits every fault and obscures its cause.

Track: [Roadmap / Open TODOs](http://10.0.0.218:6875/books/runbook/page/roadmap-open-todos).

## 2. Define ownership and boundaries

Write down which system owns what, across Kern, Kern HQ, Avrana and future subsystems: including
**which service is authoritative for each kind of fact**. Define these boundaries before implementation.

## 3. Define Kern's contracts

Before implementation: identities, authorization rules, action classes and confirmation
requirements, canonical IDs, state definitions, error taxonomy, logging, idempotency and retry
semantics.

This is the foundation everything else assumes. See *Orchestration & API Principles*.

## 4. Prove one deterministic end-to-end workflow, with no LLM

Pick a single real workflow and make it work through Kern, driven by an API call rather than
speech. It must handle its failure modes, not just the successful path.

This is the checkpoint that proves the architecture. If it is awkward here, adding voice will not
help.

## 5. Build reliable state and event plumbing

Persist state, track lifecycle transitions, emit events, and reconcile drift. Everything above
depends on Kern knowing what is actually true.

## 6. Add an LLM / model gateway

**Only now.** Interpretation on top of an orchestration layer that already works without it. See
*LLM / Model Gateway Strategy*.

## 7. Connect Kern HQ / Home Assistant Voice as a client

Voice becomes another interface to Kern. Not an orchestrator.

## 8. Harden, test failure modes, document recovery

Deliberately break things: subsystem down, timeout mid-action, duplicate request, partial
failure. Write the recovery procedures down, in the style of the existing Avrana runbook.

## 9. Consider local models

Only after all of the above, and only where it measurably helps. See
*Hardware / Infrastructure Strategy*.

## The invariant

> **The architecture must continue functioning if every external LLM provider disappears.**

True at every step, not just at the end. Steps 1-5 have no model in them at all, which is what
makes step 6 safe to add and safe to lose.

## Kern Tablet: a client, sequenced against this list

A separate sub-project proposes a docked Samsung SM-T510 as a desk companion running a Kern
interface. See [Kern Tablet: SM-T510 desk companion](http://10.0.0.218:6875/books/kern-roadmap-and-infrastructure/page/kern-tablet-sm-t510-desk-companion).

It is a **client surface**, not a step in the sequence above, and it does not change the ordering.
Its useful pages depend on Kern's own contracts and state plumbing existing (steps 3 and 5), so
building the shell early against **mock data** is deliberate: it validates performance on 2019
hardware without waiting on the backend it will eventually talk to.
