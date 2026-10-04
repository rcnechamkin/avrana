# Audiobookshelf: 13378 (LAN + tunnel `listen.avrana.net`)

> Promoted from the BookStack wiki on 2026-10-04 (page 14, "Audiobookshelf (ABS)", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/14-audiobookshelf-abs.md).

Audiobook + podcast server. Container `audiobookshelf`.
- **SSO:** OIDC login via Authentik ("Sign in with Avrana"), including mobile apps (audiobookshelf / **AudioBooth**). See *Authentik & SSO*. **Restart ABS after changing SSO settings.**
- **Gotcha (2.36):** the new `allowedOrigins` CORS whitelist defaults **empty**, which silently blocks browser/API clients: the failure *looks like bad credentials*. Fix by adding the origin to `allowedOrigins` in `absdatabase.sqlite`, then restart. **No UI toggle** in 2.36.
- **Ebook read-along:** an epub in the same folder as the `.m4b` gives a "Read" button: but ONLY if the library setting **`audiobooksOnly=false`** (it defaulted `true`, silently blocking all ebook attachment), AND the item is re-probed: a **per-item rescan** (`POST /api/items/{id}/scan`), since a library-wide scan skips known folders. ABS has no cross-folder matcher (#3062): `scripts/epub_audiobook_matcher.py` automates placing the epub; see *Pipelines* → *epub ↔ audiobook matcher*. `audiobooksOnly` is now off.
- **Backups:** the DB is the only copy of OIDC config, the CORS allowlist, and metadata edits: now covered by the **nightly whole-stack backup with a tested ABS restore** (2026-08-14); see *Backups & Recovery*.
