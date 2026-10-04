---
bookstack_page_id: 61
title: "Model Gateway Strategy"
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

# Model Gateway Strategy
# Model Gateway Strategy

**Status: planned, and deliberately last.** No model gateway should be built until deterministic
orchestration works end to end.

## The containment rule

> **Models interpret. Kern validates and executes.**

A model's only output is a *proposed structured action*. It never performs the action, never
holds credentials, and is never on the network path to a subsystem.

Everything that must be correc: permissions, identity, idempotency, state transitions, what
counts as ready, what requires confirmation: lives in Kern, where it can be tested. A prompt is
not a place to put business logic, because it cannot be unit-tested, cannot be reasoned about at
scale, and changes behaviour when the provider updates the model underneath it.

## Where the gateway sits

```text
voice / text / app
        ↓
   model gateway        ← interprets; may ask clarifying questions
        ↓  proposed structured action
      KERN              ← validates, authorizes, executes, records
        ↓
   subsystems
```

The gateway is a **client of Kern**, on the same footing as any other interface. It has no
private path and no elevated rights.

## Validation is not optional

Every proposed action is validated as if it came from a hostile client, because in effect it did:
the model's input is arbitrary human speech, possibly misheard by STT, possibly containing
instructions aimed at the model itself.

Validation covers: does this action exist; are the parameters well-formed; do the IDs resolve;
is this identity permitted; does this class require confirmation; is it a duplicate.

**A model saying an action is appropriate carries no authority.**

## Ambiguity belongs to the model, decisions belong to Kern

"The newest Ted Lasso" is a resolution problem: the model may propose that it means a specific
season of a specific show. Kern checks that the ID resolves and that the person may request it.
If resolution is uncertain, the correct outcome is a **clarifying question**, not a guess: and
for anything expensive or destructive, an explicit confirmation naming the resolved target.

## Provider independence

The gateway must be replaceable. Concretely:

- Kern's contracts do not mention any provider or model.
- Prompts and provider clients live inside the gateway.
- If the gateway is switched off, every capability remains reachable through Kern's API and the
  existing interfaces.

This is what makes *"must keep functioning if every external LLM provider disappears"* true in
practice rather than in principle.

## Local models

Running models locally is a **later, separate decision**: see
*Hardware / Infrastructure Strategy*. It is an optimisation of where inference happens, not a
change to the architecture. If the gateway is properly isolated, swapping a cloud provider for a
local one should be a configuration change.

Do not buy hardware to make this true. Build the isolation first; it costs nothing.

## Open decisions

- Which interactions justify a model at all (many are better as buttons).
- Whether the gateway is stateless per-utterance or holds conversation context.
- How clarifying questions are represented in the contract.
- What may be sent to an external provider: see *Identity, Permissions & Security*.
