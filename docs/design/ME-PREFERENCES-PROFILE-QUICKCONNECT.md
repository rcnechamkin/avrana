# Me: account-wide Home preferences, profile and Quick Connect (proposals)

Status, 2026-10-27: **proposals for owner decision. Nothing here is built.** Companion to
[ME-ACCOUNT-SECURITY.md](ME-ACCOUNT-SECURITY.md). Covers the three Media 2.0 Me items that need a decision before code:
HOME-02 (account-wide Home preferences), ME-06 plus the supplement's profile (photo, display name, optional bio), and
ME-05 (embedded Jellyfin Quick Connect). Decisions to make are collected in §5; build order is in §6.

The three share one root problem. Home is deliberately stateless and read-only today (HOME-APP.md §9: no volume, GET
only, an in-memory disposable cache). Each feature needs **something durable per member** and **a first write route**,
so the foundation in §1 is decided once and reused.

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
  device_id TEXT NOT NULL, linked_at INTEGER NOT NULL);      -- only if C3 (§4) is chosen
```

- **Key:** the verified Authentik username, the same key the adapters use. This is safe because usernames are never
  reused (DECISIONS.md, 2026-10-27, "No username reuse"). If the identity migration later exposes a stable `sub`, the
  store moves to it in one migration. `scripts/offboard.py` would also delete the member's rows.
- **Tension to resolve:** the same decision row ends "No link table" (it meant: no username-to-upstream mapping table).
  `member_jellyfin_link` (C3) is a credential record, not a mapping; the mapping stays exact-username, and the stored
  Jellyfin user id is checked against that mapping on every use. Confirm you're happy with this reading before C3.
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

### Options

| | How | For | Against |
| --- | --- | --- | --- |
| **C1. Hand-off** | The guide's step opens Jellyfin's own Quick Connect page at `watch.avrana.net` (user menu → Quick Connect); the member types the TV's code there | No new credential or write in Home; works today | Needs the member's Jellyfin password in a browser once; it's a second site, not embedded |
| **C2. Admin key + `userId`** | Home maps the verified username to the Jellyfin user (as the adapter already does) and calls Authorize with the API key | Smallest build; no storage | **Forbidden by ME-05 as written.** A mapping bug or a forged identity would hand out a TV session for *any* account, admins included; it turns a read key into an account-granting write |
| **C3. Member-linked token** (recommended) | One-time **Link TV and Movies** in Me: Home starts its own Quick Connect request (device name "Avrana Media"); the member approves it once from any Jellyfin app or the web; Home receives the member's own token and stores it (§1). Later TV codes are approved **with that token and no `userId`**, so Jellyfin itself enforces that a member can only approve for themself | Least privilege; meets ME-05; the link appears in the member's own Jellyfin device list and can be revoked there; unlinking calls `POST /Sessions/Logout` with the token | Needs the member store, a one-time link step (and a signed-in Jellyfin client for it), and a decision on encrypting tokens at rest (C4) |

A side benefit of C3: POST-M3-VALIDATION-PLANS.md notes that in-browser playback needs a member Jellyfin token
("Quick Connect or password; R1 §7"). The linked token is exactly that, so C3 also unblocks that later work.

**Recommendation:** ship **C1 now** as the guide step and the permanent fallback. Build **C3** on the member store.
Choose C2 only if you explicitly override ME-05 for speed; if you do, require `HOME_IDENTITY_MODE=jwt_required`, refuse
Jellyfin administrator accounts, and log every approval.

### The embedded approve step (C3; most of it applies to C2 too)

- `POST /me/devices/quick-connect` with `code` (exactly `\d{6}`) and the CSRF token. Explicit submit; no auto-submit
  on the sixth digit.
- **Rate limits:** 5 tries per member per 10 minutes, and a small global cap. The code space is only 900,000 with a
  10-minute life, so a mistyped code can approve a stranger's waiting device. Jellyfin offers no way to show the device
  name before approving, so the page says plainly which account is being shared, and that the approval only counts for
  the TV showing that code.
- **Outcomes and words:**
  - success: "Approved. Your TV should sign in within a few seconds. If it doesn't, check the code and try again" (this
    acknowledges the approval; it doesn't verify the sign-in);
  - not found: "That code didn't work. Codes last 10 minutes";
  - already approved: "That code was already used";
  - 401: Quick Connect unavailable, so use the hand-off;
  - timeout: "We couldn't tell whether it went through. Check your TV before trying again" (no automatic retry, since
    approving isn't idempotent).
- The code is never logged, cached, stored or echoed. Not linked yet: the form is replaced by **Link TV and Movies**
  plus the C1 hand-off.
- **Physical acceptance** per supported client (Jellyfin on Apple TV, Android TV, Fire TV, Roku, as the ME-03
  catalogue decides), recording server and client versions.

### C4. Tokens at rest

A Jellyfin token doesn't expire until it's revoked. Options:
1. encrypt with AES-GCM (adds the `cryptography` dependency) under a key file mounted like the other Home secrets;
2. rely on volume permissions only.

Recommended: option 1. A stolen backup then yields nothing without the key, which isn't in the backup set.

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
| C2/C3 | Admin key + `userId`, or member-linked token | C3 |
| C4 | Encrypt Jellyfin tokens at rest (`cryptography`) | Yes |

Also check (not a decision): whether Quick Connect is switched on in the Jellyfin dashboard, and the exact Jellyfin web
route for its Quick Connect page at 10.11.11.

## 6. Build order once decided

1. **C1 hand-off** (copy and a link; can land at once).
2. **S1 + S2 + HOME-02** (store, `forms.py`, `/me/home`, Customize beside Home, account-wide behaviour, tests in §2).
3. **Profile**: name hand-off, bio, and the colour or photo choice from B3.
4. **C3** (link, approve, unlink, rate limits, offboarding purge), then the physical device pass.

Each lands as its own draft PR on the shared foundation, with an owner-approved deploy and a rollback that keeps the
volume (a rollback never deletes member records).
