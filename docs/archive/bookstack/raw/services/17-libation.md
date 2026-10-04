---
bookstack_page_id: 17
title: "Libation"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Books and Audio"
created: 2026-08-13 21:28:47
updated: 2026-08-21 00:15:02
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/libation.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/libation.md`.

# Libation
# Libation
Audible downloader/decrypter → writes to `/mnt/avrana_media/audiobooks`. Container `libation`. **No web UI**: all interaction is `LibationCli` via `docker exec`. Runs a **scan+liberate loop every 12h**.
- **Two Audible accounts** on one instance (shared DB dedups by **ASIN**). As of 2026-08-13 both `cnechamkin@` and `liammmurph95@` are added and scanned; **196/212 liberated**. Folders carry an `[ASIN]` suffix (relevant to the epub↔audiobook matcher).
- **~15-17 Audible-Plus titles cannot download** without an active membership (expected "content license denied").
- **OOM fix (2026-08-13):** `InProgress` staged to `/tmp`, a **RAM-backed tmpfs** under `mem_limit` 2g, so large books (e.g. *A Storm of Swords*) filled RAM and the memcg **OOM-killed** liberate (exit 137). Fixed by bind-mounting `/mnt/avrana_media/.libation-inprogress` → `/tmp` (disk) and raising `mem_limit` to 4g. Protects the native loop too.
- **Manual liberate gotcha:** `docker exec` does NOT inherit the compose env, so a manual run needs `docker exec libation LibationCli liberate --libationFiles /config -o Books=/data -o InProgress=/tmp` (else "Books directory is not set"). Simples: `docker restart libation`.
- **Progress widget:** the `libation-status` container (:8087, digest-pinned read-only python) serves library/downloaded/pending/state JSON, feeding a Homepage **customapi** widget under *Automation*.
