# Calibre-Web-Automated: 8083, `books.avrana.net`

> Promoted from the BookStack wiki on 2026-10-04 (page 15, "Calibre-Web-Automated (CWA)", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/15-calibre-web-automated-cwa.md).

Ebook library + one-click Send-to-Kindle. Container `calibre-web-automated`, pinned `v4.0.6`.
- Watches `/mnt/avrana_media/books` (Shelfmark's `DESTINATION`) as an **ingest inbox**, imports into `/mnt/avrana_media/calibre-library`, then **deletes** the inbox copy. So `/books` is transient.
- **Send-to-Kindle (unfinished):** set SMTP sender (Gmail app-password), your `@kindle.com` address, and add that sender to Amazon's Approved Personal Document list. Test with *Anxious People*.

## Auth: Authentik via LDAP (2026-08-14)
CWA has no OIDC: only a username/password form: so it authenticates against the **`authentik-ldap`** outpost. Users type their **Authentik username + password** into CWA's login box (that box *is* the "Login with Avrana": there is no SSO button, which is inherent to LDAP). Gated by the **`avrana-books`** group. `config_login_type=1` (LDAP); bind account `cn=ldap-cwa,ou=users,DC=avrana,DC=net`; base DN `DC=avrana,DC=net`; user filter `(cn=%s)`.
- **Killer gotcha:** the LDAP provider's `authorization_flow` must be `default-authentication-flow` (NOT implicit-consent) or every bind fails "Flow does not apply to current user." The bind account also needs `search_full_directory` (via a role in group `ldap-service`) **and** membership of `avrana-books` (the bind runs the app-access check). Restart `authentik-ldap` after provider changes.
- LDAP :3389 rides a private `avrana-ldap` docker network shared with CWA: **never** on the LAN. Bind password stored Fernet-encrypted in `config/app.db` (`config_ldap_serv_password_e`, key `config/.key`).
- Full LDAP build detail lives in the *Authentik & SSO* page.

## Public exposure (2026-08-14)
Now on the tunnel at **`books.avrana.net`** → `10.0.0.218:8083`. **Before exposing, the default `admin`/`admin123` was rotated** to a strong scrypt password (kept as a break-glass LOCAL admin: that account is not in Authentik; local login stays enabled, `config_disable_standard_login=0`). The new admin password is in the operator's password manager, not here. The Authentik app tile launches `https://books.avrana.net`.

## Send to Kindle (one-click)

**Pipeline (already configured):** on ingest CWA fetches missing metadata (fill-missing only),
enforces metadata into the EPUB, and runs the Kindle EPUB Fixer: so the library EPUB is clean.
Auto-send is **off**; delivery is a manual one-click action after you review metadata.

**Clean Kindle titles (custom image):** Amazon names a personal document from the *attachment
filename*. Stock Calibre-Web sent "Title - Author.epub", so Kindle showed the author appended.
Avrana runs a patched image `avrana-calibre-web-automated:v4.0.6-kindlefilename` (= upstream
v4.0.6 + a build-time patch; see `services/calibre-web-automated/Dockerfile` +
`avrana-patch/README.md`) that sends the MIME attachment as **`{title}.epub`** (no author) while
leaving the canonical library file and the EPUB's embedded metadata/cover untouched. Verified
with Cibola Burn → attachment `Cibola Burn.epub`. On a CWA version bump, rebuild; the patch fails
the build if upstream moved (regenerate per the README).

**SMTP via Postmark**: enter in *Admin → Email Server Settings* (stored encrypted, the existing
secret pattern):
| Field | Value |
|---|---|
| Server | `smtp.postmarkapp.com` |
| Port | `587` |
| Encryption | STARTTLS |
| SMTP login | your Postmark **Server API Token** |
| SMTP password | the **same** Server API Token (Postmark uses it for both) |
| From | a **verified Sender Signature** in Postmark |

Gotchas: (1) free/new Postmark accounts are approval-gated: sending to arbitrary recipients like
`@kindle.com` may need account approval first. (2) The From address must ALSO be added to
**Amazon → Preferences → Personal Document Settings → Approved Personal Document E-mail List** or
Amazon silently drops it. (3) Each user sets their own `@kindle.com` in their CWA profile; Kindle
accepts EPUB natively (no conversion).
## Metadata providers: Hardcover (primary) → Kobo (fallback)

CWA fetches book metadata (the "Get metadata" button when editing, and the fill-missing
auto-fetch on ingest) from **Hardcover first, Kobo as fallback**.

- **Token:** Hardcover needs an API token; CWA resolves it per-user → `config_hardcover_token`
  → the **`HARDCOVER_TOKEN` env var**. We use the env var, reusing the **same token Shelfmark
  uses** (`services/shelfmark/config/plugins/hardcover.json`, strip the `Bearer ` prefix). The
  value lives in the **gitignored `services/calibre-web-automated/.env`**: never in the tracked
  `docker-compose.yml`, which only references `${HARDCOVER_TOKEN}`. **Token expires 2027-08-13**;
  refresh it in Hardcover and update both Shelfmark's `hardcover.json` and CWA's `.env`.
- **Order:** `cwa.db` → `cwa_settings.metadata_provider_hierarchy` = `["hardcover","kobo",…]`
  with only Hardcover + Kobo enabled (others retained but disabled: re-enable for deeper
  fallbacks). Restart CWA to reload. Kobo needs no token.
- Separate from Hardcover *reading-progress sync* (`config_hardcover_sync`) and the scheduled
  `hardcover_auto_fetch` batch job (left off).

## The custom image fixes three things (not just Kindle titles)

`avrana-calibre-web-automated:v4.0.6-kindlefilename` (built from `services/calibre-web-automated/
Dockerfile`; patch in `avrana-patch/`) applies **three** additive patches:

1. **Clean Kindle titles**: MIME attachment filename `{title}.epub` (see *Send to Kindle*).
2. **Local-account OPDS/API auth in LDAP mode**: upstream CWA, when LDAP login is on, only tries
   an LDAP bind for HTTP Basic auth and never falls back to a local password. That silently broke
   the **Homepage `calibreweb` widget** ("API Error Info") because its `Homepage` account is a
   *local* viewer (not in the directory). The patch adds a local-hash fallback (LDAP-managed users
   have no usable local hash, so they still can't bypass LDAP). This also restores OPDS/API for
   the break-glass `admin`.
3. **Valid XHTML from the Kindle EPUB fixer** (upstream
   [#1473](https://github.com/crocodilestick/Calibre-Web-Automated/issues/1473), open in v4.0.8): the
   fixer wrote an unclosed `<meta charset="utf-8">` into book pages, which makes them invalid XML, so
   browsers and Komga's EPUB reader showed a blank page after the cover. The patch writes
   `<meta charset="utf-8"/>`. Deployed 2026-10-29 (rollback image tag
   `v4.0.6-kindlefilename-pre-charset`). 24 of 91 library books had been damaged before the patch;
   see the repair note below.

## Repairing books damaged by the fixer bug

`services/calibre-web-automated/tools/epub_charset_fix.py ROOT` lists EPUBs that still carry the
unclosed tag (dry run). With `--apply --backup DIR` it copies each one to DIR first, then closes the
tag in place (only page entries that contain it change; owner, mode and mtime are kept) and checks
every rewritten page parses as XML. Run it on the host against `/mnt/avrana_media/calibre-library`.

## OPDS performance (LDAP cached mode)

OPDS reader apps send HTTP Basic auth on **every** request, and in `direct` LDAP mode each bind
ran Authentik's full flow (~3 s), so OPDS browsing crawled. The `calibre-ldap` provider is now in
**`cached` bind + search mode** (see the *Authentik & SSO* / LDAP notes): repeat binds drop from
~3 s to ~5 ms. Trade-off: a password change or `avrana-books` removal can lag by the cache window
: to cut access immediately, disable in Authentik **and** restart the `authentik-ldap` outpost.


## Send-to-Kindle setup (2026-08-17)

Members set their `@kindle.com` address once at **<https://kindle.avrana.net>** (portal:
**Read -> Kindle**) and it is written into **both** Calibre-Web and Audiobookshelf.

The two libraries store it completely differently: Calibre-Web has a real per-user
`user.kindle_mail` column (comma-separated), while Audiobookshelf has **one global
`ereaderDevices` array**, so each device is scoped with `availabilityOption: specificUsers` plus
that user's id.

> **ABS silently coerces `specificUsers` back to `adminOrUp` when the users list is empty**
> (verified on 2.36.0). An unscoped write would quietly expose a member's Kindle address to
> every admin.

`kindle_mail` is written straight to `app.db`: it is plaintext, unlike `mail_password_e`, and
Calibre-Web reloads the user row per request. Only the three SQLite files are mounted into that
container, **never the config directory**, because that also holds `.key`, the Fernet key that
decrypts CWA's stored SMTP password.

Address validation is strict (`…@kindle.com` only): Amazon **silently discards** mail to a
non-existent Send-to-Kindle address, so a typo means books vanish with no error anywhere.

**Still manual on Amazon's side:** add `cody@avrana.net` under Personal Document Settings ->
Approved Personal Document E-mail List, or Amazon drops the book even though SMTP2GO reports
success.

## Bug sweep and fixes (2026-08-17)

Four bugs were found in CWA logs after the bulk epub import. Three are fixed.

### FIXED: missing `book_format_checksums` table (was 120 errors / 3h)

`cps/progress_syncing/checksums/manager.py` writes through `calibre_db.engine`, so the table
belongs in **metadata.db** -- not app.db or cwa.db. `models.py` defines
`ensure_checksum_table()` but it had never run, so every single book import logged
*"no such table: book_format_checksums"* and KOReader sync recorded no checksums.

Created directly in metadata.db using the exact DDL from `models.py` (id / book / format /
checksum / version / created, FK to books ON DELETE CASCADE) plus its four indexes.

### FIXED: author names displayed in the wrong order (was 108 errors, 29 of 104 books)

`cps/db.py:order_authors()` splits each book's `author_sort` on `&` and looks up
`authors.sort`. The imported epubs carried `author_sort` values that disagreed with the authors
table in three different ways:

| Book's `author_sort` | `authors.sort` | Problem |
|---|---|---|
| `COREY, JAMES S. A.` | `Corey, James S. A.` | case |
| `Cixin Liu` | `Liu, Cixin` | not inverted |
| `Czajkowski, Adrian` | `Tchaikovsky, Adrian` | different name entirely |
| `S.A. COREY, JAMES` | `Corey, James S.A.` | mis-parsed |

Fixed by recomputing `books.author_sort` from the linked authors' own `sort` values joined with
` & ` -- 44 of 104 books rewritten, 0 mismatches remaining.

> **Trap:** a plain sqlite3 connection cannot UPDATE `books`. Calibre registers a custom
> `title_sort()` SQL function, and `books_update_trg` references it even when its
> `OLD.title <> NEW.title` guard is false. Register a `title_sort` implementation on the
> connection first (articles moved to the end), or the UPDATE fails with
> *"no such function: title_sort"*. Verify afterwards that no `books.sort` value changed.

### FIXED: `'CWA_DB' object has no attribute 'close'` (was 18 errors)

`cps/editbooks.py` invalidates the duplicate cache after a deletion, then calls
`cwa_db.close()`, which upstream never defined. Invalidation runs first, so duplicate detection
was never wrong -- but the sqlite connection CWA_DB opens in `__init__` was leaked on every
delete. Fixed in the Avrana build-time patch (`avrana-patch/apply_avrana_patches.py`), image
rebuilt and redeployed. Commit `afe1d5b`.

### NOT FIXED: self-request timeout (1 occurrence)

`Failed to queue duplicate scan after change: 127.0.0.1:8083 Read timed out (read timeout=5)`.
CWA calls its own HTTP API with a hard-coded 5s timeout; under bulk deletion load it exceeded
it and one duplicate scan was skipped. Harmless in isolation and self-corrects on the next
scan. Only worth patching if it becomes frequent.

### Duplicates

10 duplicate groups / 18 extra copies appeared because the `azw3.epub.mobi` release packs were
imported as **separate books** rather than multiple formats on one book. They were not
byte-identical (different conversions), so the largest copy is the one to keep. Cleared
2026-08-17; the library now reports **0 duplicate groups**.

## Hardcover metadata (2026-08-17)

**Wiring:** the token lives in the gitignored `services/calibre-web-automated/.env` as
`HARDCOVER_TOKEN` and reaches the container by compose variable substitution. `config_hardcover_token`
in `app.db` is **empty on purpose** -- the provider falls back to `getenv("HARDCOVER_TOKEN")`, so an
empty column is not a misconfiguration. Hardcover is first in `metadata_provider_hierarchy`, with
Kobo as fallback.

**Most enrichment happens at ingest.** CWA fetches metadata as books import, so 88 of 91 books
already carried `hardcover-id` + `hardcover-slug` before any scan was run. The scheduled
auto-fetch only processes books that still lack an ID.

**Running it without the admin form.** `POST /hardcover_auto_fetch` needs an admin session. The
scheduler does no: it reads `hardcover_auto_fetch_enabled` from `cwa.db` at **startup**, so
setting `hardcover_auto_fetch_enabled=1` plus `hardcover_auto_fetch_schedule='15min'` and
restarting will fire the task ~15 minutes later (`15min` is an `IntervalTrigger`, timed from
container start, not a wall-clock slot). Remember to set the schedule back afterwards.

Current setting: **enabled, weekly, Sunday 02:00**, confidence 0.85, batch 50, rate limit 5.0.

### FIXED: `'CWA_DB' object has no attribute 'execute_write'`

`cps/tasks/auto_hardcover_id.py::_save_stats()` inserts into `hardcover_auto_fetch_stats` via
`cwa_db.execute_write()`, which upstream never defined. The `try/except` around it downgraded the
AttributeError to a warning, so the log said

```
Hardcover auto-fetch completed: 3 processed, 2 auto-matched, 0 queued for review, 1 skipped
```

while the stats table stayed **empty**. The work happened; only the record was lost.

> **This is why an empty `hardcover_auto_fetch_stats` does not mean the job never ran.** Check the
> container log for "Hardcover auto-fetch completed" before concluding anything from that table.

Fixed in the Avrana build-time patch (commit `c3dd499`), same family as the missing `close()`
(commit `afe1d5b`). Both are upstream bugs where CWA calls a `CWA_DB` method that does not exist.

### Titles from release names block matching

One book resisted matching because its title was a release-name artifact,
`Crescent City 01 - House of Earth and Blood`. Hardcover returns nothing for that string. Renamed
via `calibredb set_metadata`; note that `--field title:` does **not** update the title sort, which
needs a second `--field sort:` call.
