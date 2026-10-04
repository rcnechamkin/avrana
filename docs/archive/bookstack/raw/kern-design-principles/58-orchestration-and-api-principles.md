---
bookstack_page_id: 58
title: "Orchestration and API Principles"
shelf: "Kern"
book: "Kern: Design Principles"
chapter: ""
created: 2026-08-18 01:47:31
updated: 2026-08-21 00:15:55
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Orchestration and API Principles
# Orchestration and API Principles

**Status: planned architecture.** These are the constraints an implementation must satisfy. None
of this is built.

## Kern owns its own interface

Every capability is exposed through a **Kern-owned contract**, never by proxying an upstream
service's API shape. Callers must never learn what Sonarr's JSON looks like.

The reason is containmen: upstream projects rename fields and change semantics on their own
schedule. When that happens the scope of required changes must be one adapter inside Kern, not every caller.

**Rule:** if a Sonarr, Seerr or Home Assistant field name appears in a Kern response, the
abstraction has leaked.

## Canonical identifiers

Pass **stable IDs** between systems, not human-readable titles. Titles are ambiguous, get
re-released, differ by region, and collide.

This is not theoretical. Two failures already observed while working on Avrana:

- Matching an ebook to an audiobook by title accepted *God Emperor of Dune* for *Dune*, because
  a short title is fully contained by a longer, different one.
- Two catalogues numbering the same show differently (TVDB counting 22 episodes where TMDB
  counts 20) made a complete season look incomplete.

Both were identity problems rather than matching problems. Kern should carry `tmdb`, `tvdb`,
`asin`, `isbn` and internal IDs, and treat a title as a display string only.

Where an ID genuinely does not exist ye: a user said a name out loud and nothing has resolved
i: that resolution step is an explicit, reviewable action, not a silent guess.

## Action classes and confirmation

Not all actions deserve the same trust. Classify every Kern action and attach requirements to
the class rather than to individual endpoints:

| Class | Examples | Expectation |
|---|---|---|
| **Read-only** | is this available, what is playing | No confirmation |
| **Additive** | request a title, add to a list | Low friction, must be idempotent |
| **Expensive** | large downloads, bulk operations | Explicit confirmation, quota-aware |
| **Administrative** | change settings, manage users | Elevated identity, audited |
| **Destructive** | delete media, remove users | Explicit confirmation naming the target, audited, reversible where possible |

A voice interface should be able to perform read-only and additive actions comfortably, and
should **not** be a path to destructive ones without a deliberate, separately-authorized step.

## Idempotency

Repeating an action after a timeout must not produce a second effect. A caller that gets no
response does not know whether the action happened, and its safe response is to retry.

**Rule:** state-changing actions carry a caller-supplied idempotency key. Kern records the key
with the outcome. A repeat with the same key returns the original outcome instead of acting
again. Without this, one flaky network moment turns into duplicate requests.

## Errors

Errors are part of the contract, not an afterthought. A caller needs to distinguish:

- **rejected**: invalid or not permitted; retrying is pointless,
- **failed**: a downstream problem; retrying may work,
- **unknown**: Kern could not determine the outcome; the idempotency key is how it is resolved.

An error should say which downstream system was involved and whether any partial effect
persisted.

## Logging and auditability

Kern should eventually be able to answer, for any action: **what happened, who or what initiated
it, which downstream systems were called, and what each returned.**

For a voice-initiated action this needs to include the interpreted intent alongside the raw
request, so a wrong outcome can be traced to interpretation rather than execution. This is the
main defence against "the AI did something odd and nobody can tell what".

## Open decisions

- Contract style (REST, RPC, or an internal command bus).
- Whether idempotency keys are caller-supplied, derived, or both.
- Retention period for audit records.
