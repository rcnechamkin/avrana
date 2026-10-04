---
bookstack_page_id: 59
title: "Identity, Permissions, and Security"
shelf: "Kern"
book: "Kern: Design Principles"
chapter: ""
created: 2026-08-18 01:47:32
updated: 2026-08-21 00:15:55
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Identity, Permissions, and Security
# Identity, Permissions, and Security

**Status: Authentik is current state; everything about Kern's use of it is planned.**

## Identity must survive the whole chain

Avrana already has a real identity system: Authentik, with group-based access to each service.
See [Authentik & SSO](http://10.0.0.218:6875/books/services/page/authentik-sso).

Kern must **carry that identity through an action**, not drop it at the first hop. An action
arriving at Avrana should still be attributable to a person and checked against that person's
permissions. If Kern acts as one privileged super-user for everything, then every permission
boundary in the stack silently becomes decorative.

## The shared-device problem

> **A shared voice device does not prove who spoke.**

This is the single hardest identity problem in the planned design, and it needs to be solved
before voice can trigger anything sensitive.

A Home Assistant Voice device in a shared room knows the *device*, not the *person*. Voice
recognition is a probabilistic hint, not authentication. So:

- a shared device should default to a **low-trust identity** with a restricted action set,
- read-only and additive household actions can reasonably be allowed at that level,
- administrative and destructive actions must require identity established another way
  (an authenticated app, a confirmation in the portal, a per-person device),
- Kern should record *how* identity was established, not just who it claims to be.

Designing as if voice equals a logged-in user is the mistake to avoid.

**Open decision:** what the trust tiers are, and which actions each may reach.

## Scoped credentials

Kern should hold **narrow, purpose-scoped service credentials** for each subsystem, not broad
administrator keys, and certainly never credentials handed to a model.

Two habits already established in Avrana that should carry into Kern:

- dedicated per-service accounts rather than reusing an admin login,
- secrets in gitignored env files with restrictive permissions, never in tracked config or
  documentation.

The break-glass local admin accounts stay out of automation entirely; they exist for humans
recovering a broken system.

## What models may hold

**Nothing.** A model gets a request and returns a proposed action. It does not receive service
credentials, it does not receive a Kern token that can act unattended, and it is not on the
network path to Sonarr, Seerr or Home Assistant.

If a model needs a fact to interpret a request, Kern supplies that fact through a read-only,
scoped lookup: the model does not go and get it.

## Secrets hygiene

- Scoped credentials per subsystem, rotatable independently.
- No secrets in prompts, logs, commits, or these pages.
- Assume anything sent to an external model provider must be treated as externally disclosed.

That last point constrains what may appear in a promp: media titles are probably fine,
household routines and identities deserve more thought. **Open decision.**
