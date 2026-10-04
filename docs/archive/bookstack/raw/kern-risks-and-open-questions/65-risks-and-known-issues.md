---
bookstack_page_id: 65
title: "Risks and Known Issues"
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

# Risks and Known Issues
# Risks and Known Issues

**Status: known in advance.** Several of these have already been observed in the running Avrana
stack and are recorded here so Kern does not rediscover them.

## Identity does not survive by default

Authentik identities and permissions must be carried through Kern actions. The failure mode is
Kern acting as a single privileged user, which silently voids every permission boundary
underneath it.

**Shared voice devices do not prove who spoke.** Treat a shared device as a low-trust identity.
See *Identity, Permissions & Security*.

## Services disagree about state

Not a bug: they answer different questions. Already observed: Sonarr reporting a season complete
with every file present while Seerr reported it partially available, because their catalogues
number episodes differently.

**Mitigation:** name one authority per fact. Record the rest as signals.

## "Known about" is not "ready"

A request existing in Sonarr says nothing about whether anything is watchable. Model the
lifecycle: requested, searching, downloading, importing, indexed, ready, failed: and expect
items to **stall** in the middle states rather than fail loudly.

## Retries create duplicates

A timeout leaves the caller unable to tell whether the action happened. Its safe response is to
retry, and without idempotency keys that produces duplicate requests and duplicate downloads.

Already observed in a smaller form: a bulk grab where one release was already queued returned an
error rather than silently duplicating: the desired behaviour, and exactly what Kern must
guarantee deliberately.

## Partial failures are normal

Multi-service actions fail halfway. Persist intent **before** calling downstream, so recovery can
distinguish "never started" from "started, outcome unknown".

## Models are not business logic

A model may propose an action. It may not decide whether the action is permitted, correct or
safe. Anything that must be right belongs in Kern where it can be tested.

The related trap: putting rules in a prompt. Prompts cannot be unit-tested and change behaviour
when the provider updates the model.

## Ambiguous titles cause wrong actions

Two Avrana incidents involved this failure mode: matching by title accepted *God Emperor of Dune* for *Dune*, and
a study guide titled "Summary Of ..." passed a similarity threshold aimed at real books.

**Mitigation:** canonical IDs between services; titles are display strings. Where resolution is
uncertain, ask rather than guess.

## Home Assistant becoming the orchestrator

The most likely architectural drift, because HA's automation engine is convenient and already
adjacent to voice. Kern HQ is an interface and a subsystem. Kern orchestrates.

## Upstream API churn

Sonarr, Seerr and Home Assistant will change their APIs. Without a Kern-owned interface layer,
each change ripples into every caller.

Recent evidence of the shape of this problem: CWA shipped code calling a method its own database
class never defined, and a checksum table its migration never created. Upstream projects are not
stable ground; wrap them.

## Over-broad credentials

Handing broad admin credentials to components: or worse, to models: makes every later
permission decision unenforceable. Scoped service credentials from the start.

## Unexplainable actions

If Kern cannot say what happened, who initiated it, what it called and what came back, then any
misbehaviour becomes an unverifiable account. Auditability is a design requirement, required.

## Building the model gateway too early

The model gateway is the model-facing component and the last one that should be built. A voice
assistant on top of unreliable orchestration produces confident wrong answers, which is worse
than no assistant.
