# Me: account-wide Home preferences, profile and Quick Connect (proposals)

Status, 2026-10-27: **proposals for owner decision. Nothing here is built.** Quick Connect direction chosen by the owner
the same day: the admin key with guardrails (§4). Companion to
[ME-ACCOUNT-SECURITY.md](ME-ACCOUNT-SECURITY.md). Covers the three Media 2.0 Me items that need a decision before code:
HOME-02 (account-wide Home preferences), ME-06 plus the supplement's profile (photo, display name, optional bio), and
ME-05 (embedded Jellyfin Quick Connect). Decisions to make are collected in §5; build order is in §6.

The three share one root problem. Home is deliberately stateless and read-only today (HOME-APP.md §9: no volume, GET
only, an in-memory disposable cache). Preferences and profile need **something durable per member**; all three need **a first write route**. The
foundation in §1 is decided once and reused.

## 1. Shared foundation

### S1. A Home member store (recommended)

One small SQLite file owned by Home, kept separate from the disposable cache.

| Option | Verdict |
| --- | --- |
| **SQLite file in a named volume, Home only** | **Recommended.** Matches Home's footprint (stdlib `sqlite3`, no server, no new dependency). One process writes it. Easy to back up and purge |
| Authentik user attributes | Writing them needs an Authentik API token that can change users, which is an admin-grade credential inside Home (supplement §6 forbids that). Reading would also need a property mapping into the JWT, inside the 8 KiB header budget |
| Jellyfin per-user display preferences | Exists only for members with TV and Movies, and couples Home settings to one library |
| Browser storage | Can't be account-wide (HOME-02 forbids device overrides) |
| Postgres (Authentik's or a new one) | Much more operational weight for three small records per member |

Shape (proposal):

```sql
CREATE TABLE member_home_prefs (member TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, version INTEGER NOT NULL,
  starting_category TEXT NOT NULL, shelf_priority TEXT NOT NULL, visible_categories TEXT NOT NULL,
  updated_at INTEGER NOT NULL);                              -- JSON arrays of catalogue IDs
CREATE TABLE member_profile (member TEXT PRIMARY KEY, version INTEGER NOT NULL, bio TEXT NOT NULL DEFAULT '',
  avatar BLOB, avatar_etag TEXT, updated_at INTEGER NOT NULL);
CREATE TABLE member_jellyfin_link (member TEXT PRIMARY KEY, jellyfin_user_id TEXT NOT NULL, token BLOB NOT NULL,
  device_id TEXT NOT NULL, linked_at INTEGER NOT NULL);      -- only if the optional C3 hardening (§4) is built
```

- **Key:** the verified Authentik username, the same key the adapters use. This is safe because usernames are never
  reused (DECISIONS.md, 2026-10-27, "No username reuse"). If the identity migration later exposes a stable `sub`, the
  store moves to it in one migration. `scripts/offboard.py` would also delete the member's rows.
- **Tension to resolve:** the same decision row ends "No link table" (it meant: no username-to-upstream mapping table).
  `member_jellyfin_link` (C3) is a credential record, not a mapping; the mapping stays exact-username, and the stored
  Jellyfin user id is checked against that mapping on every use. Only relevant if C3 is ever built.
- **Container:** a named volume (`avrana_home_members`) mounted at `/data`. The root filesystem stays `read_only: true`
  and the tmpfs stays. WAL mode; one uvicorn worker (already the case).
- **Operations:** add the volume to the B2 backup set and the completeness gate; update HOME-APP.md §9 ("no volume to
  back up" stops being true). Wire `purge_member` (already in `cache.py`, connected to nothing) to also delete the
  member's rows; this is the offboarding hook.
- **Failure:** if the store can't be read, Home renders with defaults and says "your Home settings couldn't be loaded";
  it never writes defaults over a saved record.

### S2. Home's first write routes

Each feature adds exactly one `POST`. They follow the existing progressive-enhancement rule: a plain HTML form that works
with JavaScript off, answered with a 303 back to the page and a status line (post/redirect/get).

- **One body reader.** A new `forms.py` becomes the only module allowed to read a request body, exactly as
  `identity.py` is the only one allowed to read headers. The route-layer guard (`test_route_layer_source.py`) gains it.
  `application/x-www-form-urlencoded` only (parsed with `urllib.parse`, so no new dependency). Size cap 4 KiB.
  Allowlisted field names only.
- **CSRF, three locks:**
  1. `Sec-Fetch-Site: same-origin` (or an `Origin` equal to Home's own) is required;
  2. a per-form token: an HMAC over member, form and expiry, the same construction as the Account & Security return
     state;
  3. form pages carry CSP `form-action 'self'` (the search page already does).
- **Concurrency:** every record carries `version`. A save sends the version it started from; a stale save gets a
  "changed on another device" page offering Reload, and the draft is kept in the form. Last-write-wins is never silent.
- **Logging:** route template, status, and a fixed outcome code. Never field values.

## 2. Account-wide Home preferences (HOME-01 / HOME-02)

### Catalogue, mapped to today's Home

#118 already gave Home its categories: the **filters** (All plus one per library place the member has: Watch, Listen,
Read; `build_filters`). They come from the group-filtered catalogue, not from any library's health, so a library outage
can never make a category look deleted. That is the catalogue:

| Field | Meaning in Home | Default |
| --- | --- | --- |
| `starting_category` | The filter Home opens on when the address has no `?for=` | `all` |
| `visible_categories` | Which places get a filter chip and appear in All | every place the member has |
| `shelf_priority` | Order of the shelves: `continue`, `up_next`, `recent` | Home's current order |

Rules (proposal):
- **Effective = saved ∩ allowed now.** Preferences apply after the access filter, so a saved place the member lost
  disappears quietly, and one they gain later appears in its curated position.
- **The starting category must be visible**, and **at least one place stays visible**. Invalid combinations are refused
  as a whole, keeping the last good record.
- **An explicit `?for=` wins** for that page view (deliberate navigation never rewrites the saved start).
- Hiding a place is presentation only; the copy never calls it a restriction or parental control.
- No device override exists anywhere, including in browser storage.

### Editor

- `/me/home`: one form: a start picker, a show/hide checkbox per place, and Move up / Move down buttons for shelves
  (buttons, not drag). Save and Cancel. The copy says "These settings apply to your account on every device."
- **Customize** beside the Home heading links to `/me/home?from=home`, and Preferences links to the same page: one
  editor, one record.
- `POST /me/home` validates against the member's own catalogue, checks `version`, writes atomically, and redirects to
  `/` (or back to Me) with "Saved".

### Tests to require

Save on one client and read on another (two TestClients sharing the store); two accounts on one browser; a stale
version; unknown, duplicate or hidden-start IDs; losing and then regaining a group; store unreadable leading to defaults
with no write; `?for=` overriding the start without saving.

## 3. Profile (ME-06 and the supplement's photo / display name / bio)

ME-06 forbids a second profile database that drifts from the real account, so each field gets exactly one owner:

| Field | Owner | How the member edits it |
| --- | --- | --- |
| **Display name** | **Authentik** (`name`, already shown from `X-authentik-name`) | A hand-off to Authentik's user settings, the same pattern as Account & Security. Home never stores a copy |
| **Bio** (optional) | Home store, plain text up to 160 characters (NFC-normalised, control characters stripped, always escaped) | `/me/profile` form |
| **Photo** | Home store, re-encoded (below) | `/me/profile` upload |
| Username, email | Authentik | Read-only in Home; email via Account & Security |

Points to check on the host first: that the deployed user-settings flow lets members edit their name (upstream's
`default-user-settings-flow` does), and how soon the outpost's `X-authentik-name` reflects a change (it may only update
at the next sign-in; the copy would then say so).

**Who sees it:** Media 2.0 has no social features, so the profile is shown only to the member themself (Me header, the
shell avatar). With that audience, the bio is of limited value; keeping it is your call (B2).

### Photo pipeline (needs a dependency decision)

Upload needs `multipart/form-data` and an image decoder, which means two new pinned dependencies: `python-multipart`
and `Pillow`. A decoder is attack surface, so:

- accept JPEG, PNG or WebP up to 5 MB, detected by sniffing the bytes, never trusting the extension or Content-Type;
- set `Image.MAX_IMAGE_PIXELS` to about 40 megapixels against decompression bombs; decode, apply EXIF orientation, then
  **drop all metadata** (location included);
- centre-crop to a square and re-encode at 256×256 WebP (about 20 KB); store the bytes, never the original;
- serve it at `/me/avatar` as `private, no-store` with an ETag, to the member only (`img-src 'self'` already allows it);
- removing the photo goes back to the initial.

Lighter alternative: keep initials and let the member pick one of the brand colours (no upload, no new dependency).

## 4. Embedded Jellyfin Quick Connect (ME-05)

### What Jellyfin actually does (read from the 10.11.0 source; Home is pinned to 10.11.11, so recheck against that)

- `POST /QuickConnect/Initiate` (no auth) creates a request: a **6-digit code** for the person, a 64-hex secret for the
  device. Requests expire after **10 minutes**. Codes aren't checked for collisions (a new request silently overwrites
  one with the same code).
- `POST /QuickConnect/Authorize?code=…[&userId=…]` requires authentication. It signs the waiting device in **as the
  approving user** (`AuthenticateDirect` with that device's ID and name). A `userId` other than the caller's needs the
  Administrator role. Unknown code: not found. Already approved: an error. Quick Connect off server-wide: 401.
- `GET /QuickConnect/Enabled` (no auth) says whether Quick Connect is on, so Home can hide the feature honestly.
- **API keys are given the Administrator role** (`CustomAuthenticationHandler`). Home's existing `JELLYFIN_API_KEY` can
  therefore *already* authorize any code as any user. That's exactly the shortcut ME-05 forbids, and it's worth knowing
  that Home holds this power today.

### Why the admin key is acceptable here (owner decision, 2026-10-27)

ME-05 says not to approve codes with an administrator credential. The owner chose to anyway, for a concrete reason:
Home **already** reads every member's viewing history with this same key, passing `userId` for the member matched from
the verified username. Approving a Quick Connect code is the same key, the same username match and the same trust in
who is signed in. A compromise of Home exposes the key whichever design is used, so a member-linked token would only
protect against Home's own logic bugs.

What *is* different is the consequence, and the guardrails below exist for exactly that:

| | Reading history (today) | Approving a code (planned) |
| --- | --- | --- |
| A wrong member | One member sees another's viewing; ends when the bug is fixed | A device gets a lasting Jellyfin login as someone else until revoked; for a Jellyfin admin, control of the server |
| Input from outside | None | A 6-digit code that points at whichever device is waiting; a typo or a guess can attach the account to a stranger's TV |

### Options considered

| | How | Status |
| --- | --- | --- |
| **C1. Hand-off** | The guide opens Jellyfin's own Quick Connect page at `watch.avrana.net` (user menu → Quick Connect); the member types the TV's code there | **Ship now** as the guide step and the permanent fallback |
| **C2. Admin key + `userId`, with guardrails** | Home matches the verified username to the Jellyfin user (as the adapter already does) and calls Authorize with the API key and that `userId` | **Chosen** (owner, 2026-10-27) |
| C3. Member-linked token | One-time **Link TV and Movies**: Home receives the member's own Jellyfin token and approves codes with it, with no `userId`, so Jellyfin itself limits a member to their own account | Optional later hardening. It also gives in-browser playback the member token that POST-M3-VALIDATION-PLANS.md asks for ("Quick Connect or password; R1 §7"), so it may come back for that reason |

### Guardrails (required for C2)

1. **Verified identity only.** Real mode refuses to start unless `HOME_IDENTITY_MODE=jwt_required`, now that the Jellyfin
   key is recognised as an admin key, as the Audiobookshelf admin token already was (settings.py; landed in PR #121).
   The sealed owner preview stays exempt, as before.
2. **Never for a Jellyfin administrator.** Before approving, Home reads the target user's `Policy` (from `/Users`, which
   the adapter already reads to match usernames) and refuses when `IsAdministrator` or `IsDisabled` is true. Admins use
   Jellyfin's own page (C1).
3. **The exact-username mapping, fail closed.** Missing, ambiguous or disabled mapping: no approval. No override.
4. **Gate on the server switch.** `GET /QuickConnect/Enabled`; when off, show only the hand-off.
5. **Rate limits.** 5 tries per member per 10 minutes, and a small global cap. Explicit submit; never auto-submit on the
   sixth digit.
6. **CSRF.** The S2 design (same-origin check, per-form HMAC token bound to member, form and expiry,
   `form-action 'self'`).
7. **An audit line per approval.** `quick_connect` with a fixed outcome code and the route template only. Never the
   code, username or device. With the Authentik session log, that is enough to trace an approval in time.
8. **Honest words.** The page says which account is being shared, and that the approval only counts for the TV showing
   that code.

### What Jellyfin answers, and what the member reads

- `POST /me/devices/quick-connect` with `code` (exactly `\d{6}`) and the CSRF token, then 303 back with a status line.
- Outcomes:
  - Jellyfin `true`: "Approved. Your TV should sign in within a few seconds. If it doesn't, check the code and try
    again." This acknowledges the approval; it doesn't verify the sign-in.
  - not found: "That code didn't work. Codes last 10 minutes."
  - already approved: "That code was already used."
  - 401 (switched off): only the hand-off is shown.
  - timeout: "We couldn't tell whether it went through. Check your TV before trying again." No automatic retry, because
    approving isn't idempotent.
- The code is never logged, cached, stored or echoed.
- **Tests:** a fake Jellyfin covering every outcome; an admin target refused; a disabled or missing mapping refused;
  rate limit; CSRF refusals; a cross-member attempt impossible (the `userId` comes only from the verified principal);
  timeout without retry; no code in logs.
- **Physical acceptance** per supported client (as the ME-03 catalogue decides), recording server and client versions.

## 5. Decisions for the owner

| ID | Decision | Recommendation |
| --- | --- | --- |
| S1 | Give Home a durable member store (SQLite in a named volume, backed up, purged on offboarding) | Yes |
| S2 | Allow Home's first POST routes with the CSRF design above | Yes |
| A1 | Categories = Home's filters (All, Watch, Listen, Read); shelves = Continue, Up next, Recently added | Yes |
| A2 | Explicit Save/Cancel rather than autosave | Save/Cancel |
| B1 | Display name stays in Authentik, edited by hand-off | Yes |
| B2 | Keep the optional bio although only the member sees it | Your call; it's cheap either way |
| B3 | Photo upload with Pillow + python-multipart, or initials with a colour choice | Initials + colour first; photo later |
| C1 | Hand-off to Jellyfin's Quick Connect page now | Yes |
| C2 | Admin key + `userId` with the §4 guardrails | **Decided: yes** (owner, 2026-10-27) |
| C3 | Member-linked token | Later, only if wanted for hardening or browser playback (then also encrypt tokens at rest) |

Also check (not a decision): whether Quick Connect is switched on in the Jellyfin dashboard, and the exact Jellyfin web
route for its Quick Connect page at 10.11.11.

## 6. Build order once decided

1. **C1 hand-off** (copy and a link; can land at once).
2. **S2 + C2**: `forms.py`, the CSRF design and the embedded approve step with every §4 guardrail. It needs no member
   store, so it can come first. Then the physical device pass.
3. **S1 + HOME-02** (store, `/me/home`, Customize beside Home, account-wide behaviour, tests in §2).
4. **Profile**: name hand-off, bio, and the colour or photo choice from B3.
5. C3 only if it's wanted later (hardening, or browser playback).

Each lands as its own draft PR on the shared foundation, with an owner-approved deploy and a rollback that keeps the
volume (a rollback never deletes member records).
