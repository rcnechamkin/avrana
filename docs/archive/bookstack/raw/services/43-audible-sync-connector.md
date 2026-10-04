---
bookstack_page_id: 43
title: "Audible Sync Connector"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Books and Audio"
created: 2026-08-14 17:50:44
updated: 2026-08-21 00:15:08
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: DUPLICATE
destination: "services/avrana-audible-connector/README.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified DUPLICATE; current information is in `services/avrana-audible-connector/README.md`. The service README is the maintained copy.

# Audible Sync Connector
# Audible Sync Connector

A small, Avrana-branded consumer onboarding flow that lets a `library-contributors` user connect their Audible account, pick the audiobooks they own, and import them into the shared Audiobookshelf library: **without giving Avrana their Amazon password**. Built 2026-08-14. `services/avrana-audible-connector/` (first-party source, versioned). Public at **`contribute.avrana.net`** (OIDC-gated).

Deliberately narrow: connect Audible → Libation → Audiobookshelf. Not a Readarr/Shelfarr-style manager.

## Two tiers
- **connector**: FastAPI + Jinja2, server-rendered. Public web tier (OIDC via Authentik, `library-contributors`). Owns the SQLite ownership map. The only thing the browser talks to; never runs Libation, never sees an Amazon password. LAN bind `10.0.0.218:8092`, tunnel `contribute.avrana.net`.
- **companion**: built FROM the pinned `rmcrackan/libation` digest + a Python adapter that runs `LibationCli` per account. **No published port**, `internal:true` docker network. Reached only by the connector, authenticated with a bearer token from a read-only mounted file.

## Isolation (no cross-user catalog disclosure)
Each connected Audible account → an opaque `profile_id` → its own `--libationFiles /profiles/<id>` (a physically separate Libation state DB). The connector DB maps `authentik_sub → profile_id → ASINs`; every route resolves the profile from the authenticated subject, so no user can address another's catalog. Revoke = delete the profile dir. It uses its **own** Libation state: never the shared `services/libation` instance: so it never races the admin's 12h scan loop.

## The onboarding flow
1. **Connect**: enter Audible email + region; the connector asks the companion for a passwordless Amazon login link (`LibationCli login-external`).
2. **Sign in on Amazon**: the user authenticates on Amazon's own page (password/2FA/CAPTCHA never touch Avrana), then pastes the final redirect URL back. That URL is forwarded once to the companion and **discarded**: never stored, logged, or audited.
3. **Select**: a metadata-only scan lists their library as cards: owned (selectable), Audible Plus (greyed ou: never importable), already-in-Avrana, imported. Individual select or "Select all new". ASIN is the identity/dedup key.
4. **Choose a mode** (see below).
5. **Progress**: per-book states (queued/importing/imported/failed + retry). Refresh-safe (idempotent job creation, no duplicates).

**Connecting never auto-downloads**: downloads happen only for user-selected books, or (auto mode) newly-purchased ASINs. **Caveat:** choosing *Auto* on the very first connect treats the entire existing library as "newly purchased" and queues all of it. Prefer *Import once* or *Ask me* for a first connect until first-scan baselining is added.

## Sync modes
- **Import once**: imports the selection; when all succeed, the Audible auth is **revoked automatically** (profile deleted). On failure it's retained for retry/disconnect.
- **Ask me**: retained; daily metadata scan; new purchases appear as *pending* for approval; nothing downloads unprompted.
- **Auto**: retained; daily scan; new **purchased** ASINs auto-queue. Audible Plus/borrowed never imported; nothing already present/active/completed/excluded is requeued.

## Handoff to Audiobookshelf
The companion writes finished M4Bs (with cover/chapters/PDF) into `/mnt/avrana_media/audiobooks` = ABS's library folder. **The connector does not call ABS**: ABS's own watcher (`scannerDisableWatcher=false`) auto-detects and adds new books. Staging is on the array (`/mnt/avrana_media/.audible-connector-inprogress` → `/inprogress`, same filesystem as `/data`) so the finished-book move is an **atomic rename**: ABS never sees a half-written file. `liberate` pins `-o Books=/data -o InProgress=/inprogress` (a directly-invoked LibationCli ignores the image's `LIBATION_BOOKS_DIR` env).

## Security boundaries
Amazon password never reaches Avrana · pasted redirect URL never persisted/logged (redaction filter + scrub) · CSRF on all state changes · rate-limited auth · companion private with server-side bearer token · no Docker socket · audit trail without secrets · ASIN/path validation.

## Operate
- Config/secrets: `scripts/gen-secrets.sh`; OIDC client id in `.env`, client secret + tokens in `secrets/` (files, chmod 600).
- Tests: `cd connector && pip install -r requirements.txt pytest pyyaml && python -m pytest tests/ -q` (58 tests, companion mocked, no real Audible).
- Credential-free UI demo: `docker compose -f docker-compose.yml -f docker-compose.mock.yml up --build`.
- Deploy: `docker compose up -d --build`.
- Dashboard: an unauthenticated, counts-only `GET /status/summary` (profiles + book pipeline by stage; no titles/ASINs/emails) feeds a Homepage **customapi** widget under *Automation*: Profiles / To download / Downloading / Imported.
- Add a contributor: put them in the `library-contributors` Authentik group.

## Live-verified (2026-08-14)
The first real import **passed end-to-end** against a real Audible account (196-title library). One account imported **56 books**; each M4B kept its chapters, title/author/cover/ASIN tags and supplemental PDFs; Audiobookshelf auto-discovered them (248 items, **no duplicates**); *Import once* revoked and deleted its profile afterwards. The pasted redirect URL appeared in **neither** logs nor any database.

The mocks had hidden five real bugs, all fixed (commit `a38177d`):

1. **Companion had no internet.** It sat on an `internal: true` network, which blocks *outbound* as well as inbound, so `LibationCli` could never reach Amazon and `/v1/auth/start` returned 502. Fix: the companion also joins a dedicated **`egress`** bridge with no published ports and no other members: outbound yes, inbound still impossible.
2. **`login-external` needs a TTY.** Libation refuses interactive login on a pipe; it is now driven over a pseudo-terminal with echo disabled (the response URL is never reflected).
3. **Export field mapping was guessed wrong.** Real `LibationCli export -j` (v13.7.7) uses `AuthorNames`/`NarratorNames`, cover art is an Amazon **image id** (not a URL), and ownership is the **`IsAudiblePlus`** flag: `ContentType` is `"Product"` for owned *and* Plus titles, so the old logic offered every Plus title as a purchase. A sanitized schema fixture pins this.
4. **Existing library was invisible to the connector.** 193 books predate it and each account gets a fresh Libation DB, so selecting an already-owned title would have overwritten media. The companion now reports on-disk ASINs (`/v1/present`, from the `[ASIN]` folder tags) and refuses to overwrite; the connector marks such books *already in Avrana*.
5. **`rc == 0` didn't mean a file was produced**: Libation exited 0 having written nothing, recording a phantom "imported". Output existence is now verified, and a rescan resets on-disk-missing imports to retryable.

Also fixed: the scheduler only advanced jobs while a browser was open, so closing the tab stranded imports and a *once* connection never revoked its auth. It now polls/dispatches/finalizes every connected account on a 5-minute tick.

### "Session not found" on connect (fixed, commit `626dbe6`)
Reported from the first real connec: the paste-the-URL step failed once with *"Session not found"*, then worked after starting over. Two causes: (1) a failed completion deleted the one-time session but re-offered the same paste page bound to i: and `login-external` is single-shot, so the retry could never work; it now returns the connect page for a clean restart (email prefilled). (2) TTL mismatch: the connector held the session 30 min but the companion reaped the login process after 10; a slow first-time sign-in (Amazon login + MFA + copy) crossed 10 min and failed. Companion TTL raised to **30 min** to match, pinned by a deploy test.

### Current status
Live-proven; **58 tests** pass. Commits `a38177d` + `626dbe6` on local `main` (unpushed). Remaining known limitations: the companion's job map is **in-memory** (drain the queue before restarting the companion, or in-flight jobs orphan); *Auto* mode baselines nothing on first connect (see the caveat above); base image is tag-pinned, not digest-pinned.
