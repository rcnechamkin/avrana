---
bookstack_page_id: 14
title: "Audiobookshelf (ABS)"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Books and Audio"
created: 2026-08-13 21:28:46
updated: 2026-08-21 00:15:01
last_editor: "Cody"
revisions: 6
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/audiobookshelf.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/audiobookshelf.md`.

# Audiobookshelf (ABS)
# Audiobookshelf: 13378 (LAN + tunnel `listen.avrana.net`)
Audiobook + podcast server. Container `audiobookshelf`.
- **SSO:** OIDC login via Authentik ("Sign in with Avrana"), including mobile apps (audiobookshelf / **AudioBooth**). See *Authentik & SSO*. **Restart ABS after changing SSO settings.**
- **Gotcha (2.36):** the new `allowedOrigins` CORS whitelist defaults **empty**, which silently blocks browser/API clients: the failure *looks like bad credentials*. Fix by adding the origin to `allowedOrigins` in `absdatabase.sqlite`, then restart. **No UI toggle** in 2.36.
- **Ebook read-along:** an epub in the same folder as the `.m4b` gives a "Read" button: but ONLY if the library setting **`audiobooksOnly=false`** (it defaulted `true`, silently blocking all ebook attachment), AND the item is re-probed: a **per-item rescan** (`POST /api/items/{id}/scan`), since a library-wide scan skips known folders. ABS has no cross-folder matcher (#3062): `scripts/epub_audiobook_matcher.py` automates placing the epub; see *Pipelines* → *epub ↔ audiobook matcher*. `audiobooksOnly` is now off.
- **Backups:** the DB is the only copy of OIDC config, the CORS allowlist, and metadata edits: now covered by the **nightly whole-stack backup with a tested ABS restore** (2026-08-14); see *Backups & Recovery*.
