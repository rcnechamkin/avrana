# Adapter assessment: Audiobookshelf, Komga, Calibre-Web

Status: **assessment, 2026-10-11. Nothing deployed, nothing run against a live service.** Update: a
read-only Audiobookshelf adapter now exists (`continue_items` only, hand-written unverified fixtures;
see [ADAPTER-CONTRACT.md](ADAPTER-CONTRACT.md) section 11). It maps by exact **username**, not e-mail, and
raises the e-mail conflict below as an owner decision; Komga and Calibre-Web remain assessment only.
It measures the three remaining upstreams against the [adapter contract](ADAPTER-CONTRACT.md) using
only what this repository documents and what each project's public API documentation says. Every API
statement is from memory of public documentation and is marked **to verify**; none was checked
against the deployed versions. Gates G1 and G2 have not passed, so even a verified design may not read
member data yet. Part of Linear AVR-378, AVR-379 and AVR-380.

The reference for what "feasible" means is the Jellyfin adapter, which is proven against synthetic
fixtures only. Its pattern is: a service credential, a mapped upstream user id, a GET-only allow-list
bound to that id, and a response-scope tripwire.

## Summary

| | Audiobookshelf | Komga | Calibre-Web (CWA) |
|---|---|---|---|
| How members are provisioned | OIDC auto-register; existing users matched **by e-mail** | OIDC auto-create **plus** replicated account created with the member's e-mail and password | LDAP bind against Authentik; username is the Authentik `cn` |
| Upstream identity key | e-mail (and a username taken from the OIDC claim) | e-mail (also the Basic login name) | username (LDAP `cn`) |
| Safe mapping from the principal | **Not by username alone.** Needs an owner-maintained link or a verified e-mail | **Not by username.** Same | By exact username, with a case caveat |
| Per-member progress with a read-only credential | No. Admin-scope token needed | No. Not possible with any service credential | No. Only with the member's own credential |
| Catalogue (recent, search, artwork) | Yes, but a non-admin token sees only its own libraries; per-member visibility must be reproduced | Yes with a non-admin service account (all libraries are shared by decision) | Yes via OPDS with a non-admin local account |
| Contract methods feasible | `continue_items`, `recent_items`, `item`, artwork, search | `recent_items`, `item`, artwork, search. **No `continue_items`.** | `recent_items`, `item`, artwork, search. **No `continue_items`.** |
| Recommended order | 2nd (highest value, highest risk) | 3rd | 4th |

The exact-username rule in the contract (section 3) therefore applies to Jellyfin and Calibre-Web only; Komga and
Audiobookshelf are e-mail keyed, as the sources cited in that section show.

## 1. Audiobookshelf

### Member mapping

Accounts exist because of OIDC sign-in. `docs/services/sso-architecture.md` records
`authOpenIDMatchExistingBy: email`, and the Authentik blueprint (`services/authentik/blueprints/
audiobookshelf.yaml`) sends `email` and a role in the `groups` claim (`admin` for superusers, `user`
for `avrana-audiobooks`, `guest` otherwise). So the upstream identity key is the **e-mail**, not the
Authentik username. The ABS username comes from the OIDC profile claim (expected to be the Authentik
username for accounts created by OIDC, **to verify**), but accounts that predate OIDC and were matched by
e-mail may carry a different name.

Consequences for the adapter:

- Exact username matching (the Jellyfin rule) is not safe here. An account that happens to be named
  like a member but belongs to someone else would be mapped.
- Mapping by e-mail is only as trustworthy as the e-mail. The blueprint's scope mapping returns
  `email_verified` from a user attribute that is set for `akadmin` only; if members can edit their own
  e-mail in Authentik, a member could claim another member's address. **Open question for the owner:**
  can members change their e-mail, and is it verified?
- Recommended mapping: an **owner-maintained link list** (Authentik username to ABS user id), kept outside
  Git like other member data, checked at load for duplicates, with the adapter refusing anything not
  listed (`NOT_LINKED`). An unlinked member is never matched by guess.

### Credential: admin scope is probably required

ABS's public API serves "my data" endpoints for the token's own user (items in progress, own sessions,
personalised shelves). Reading **another** user's progress or sessions uses the admin user endpoints.
ABS 2.26 and later issue API keys and JWT access tokens that carry the associated user's permissions
(**to verify on 2.36**). A key bound to a non-admin service user would return only that user's own,
useless, data. So a per-member Continue needs an **admin-capable credential**.

Risk this creates, stated plainly:

- The credential can read every member's progress and listening sessions and, historically, the user list
  has returned each user's bearer token in its response (**to verify on 2.36**). A bug or a mapping error
  would not just leak progress; it could leak tokens.
- ABS can also change configuration with the same credential. The only read-only guarantee would be the
  adapter's own GET-only allow-list (as in the Jellyfin adapter), which cannot be stronger than the code.
- Mitigations to require: the allow-list excludes the user-list route entirely (fetch one user by mapped
  id only); responses are parsed into a tiny whitelist of fields so a `token` field is never retained;
  the credential is dedicated and rotatable; no route that returns tokens is in the table.
- Alternative with less blast radius, at a UX cost: ABS-native continue listening only on the ABS app,
  and the home shows a link and "recently added" only (needs only a non-admin token).

### Contract methods

| Method | Feasible | Notes |
|---|---|---|
| `resolve_user` | Yes, with the link list | `GET /api/users/:id` (admin) to confirm the id still exists and is active |
| `continue_items` | Yes, admin scope | per-user media progress, then item lookups; hand-off `https://listen.avrana.net/item/<id>` (**to verify**) |
| `recent_items` | Yes | library items sorted by `addedAt`; must be restricted to the libraries and tags the **member** may access (`librariesAccessible`, tag restrictions) because an admin token sees everything |
| `item`, artwork | Yes | cover route; must check visibility against the member's library access first |
| `search` | Yes | library search, same visibility filter |

### Isolation hazards

1. **Admin-view fallback.** The most dangerous bug is calling the "me" endpoints with an admin token,
   which returns the admin's data as if it were the member's. The allow-list must contain only routes that
   take an explicit mapped user id in the path, and none of the "me" routes.
2. **Library and tag access is a member property.** ABS users may be limited to some libraries and some
   tags (and tag restrictions can be inverted). With an admin token the server does not enforce them;
   the adapter must, or recently added and search leak titles the member cannot see in ABS. Needs the
   user object's access fields (**to verify**) and tests with two members of different access.
3. **Global arrays.** The Kindle connector already deals with ABS's single global `ereaderDevices` array,
   which coerces an unscoped `specificUsers` entry back to `adminOrUp` (documented in
   `docs/services/calibre-web-automated.md`). Never read, and never expose, any global array that mixes
   members: e-reader devices, collections, playlists, podcast items. Keep these routes out of the table.
4. **Sessions are rich.** Listening sessions contain device names, IP addresses and timestamps; the
   adapter keeps only position and item id.
5. **Token lifetime.** JWT access tokens expire and refresh; a long-lived key is preferable for a service
   credential. Session expiry must map to `UNAVAILABLE`, not a retry loop (the contract forbids retries). A 401 on the
   service credential counts toward the circuit shared by all members (three in a row open it for 60 s);
   a 403 counts only on the user list, not on one member's call; a 404 for a cached mapping is
   member-specific (`NOT_LINKED`, mapping dropped), but a 404 right after a fresh mapping is route drift and
   counts (`ADAPTER-CONTRACT.md` section 6). Both auth behaviours are unverified.
6. **CORS `allowedOrigins`** is empty by default in 2.36 (`docs/services/audiobookshelf.md`). Server-to-server
   calls are unaffected, but do not add the home's origin for convenience.

### Open questions that need a read-only check against the real service (owner-approved, later)

- ABS version in production, and whether API keys with scoped permissions exist in it.
- Exact names ABS holds for each member, versus Authentik usernames and e-mails (read the user list once
  as a count and a name-comparison, never printing tokens).
- Whether members can change their Authentik e-mail, and the effect on OIDC matching.
- The shape of the admin user endpoint (is `token` in the response), and of media progress.
- Whether library and tag restrictions are in use at all (if nobody is restricted, issue 2 is moot today but
  still must be enforced for tomorrow).
- Item hand-off URL form on `listen.avrana.net`, including whether the web app deep-links.

## 2. Komga

### Member mapping

`docs/services/komga.md` and the enrollment policy (`avrana-komga-create` in
`services/authentik/blueprints/avrana-enrollment.yaml`) show Komga accounts are created from the member's
**e-mail** and password (credential replication), and the e-mail is the Basic login name; OIDC sign-in can
also auto-create an account. The username is not the key. Like ABS, exact username mapping is wrong, and
e-mail mapping inherits the same trust question. Members enrolled before the policy have no replicated
account; they may exist only through OIDC.

For the catalogue, **mapping is unnecessary**: by decision (2026-08-17) every member sees every comic
library (`SHARED_ALL_LIBRARIES`), non-admin accounts are read-only, and the group `avrana-comics` already
gates the section. A catalogue adapter can use a single non-admin service account with exactly the roles a
member has, so what it can see equals what any member can see.

### Credential

- Komga's admin API uses HTTP Basic. This repository records that `X-API-Key` was **rejected** for both REST
  and OPDS in the deployed version (**to verify**; newer Komga documents per-user API keys).
- The credential today in `services/komf/config/application.yml` is an **admin** login. The home must not
  reuse it. Required: a new dedicated non-admin account (roles `FILE_DOWNLOAD`, `PAGE_STREAMING` at most;
  `PAGE_STREAMING` is not even needed for metadata and thumbnails, **to verify**), created by the owner,
  with its password in the secret store.
- **Per-member read progress is not obtainable.** *(UNVERIFIED: from memory of Komga's public documentation,
  not checked against the deployed version.)* Komga has no impersonation. A member's progress is
  visible only with that member's own credential, which the home neither has nor should hold (replicated
  passwords are not stored by Avrana). An admin can read user records, not their progress. So
  `continue_items` is **not feasible** and should return `EMPTY` or be omitted for Komga; the home links
  to Komga for "continue reading".

### Contract methods

| Method | Feasible | Notes |
|---|---|---|
| `resolve_user` | Trivial for the catalogue | the service account for everyone; returns a fixed non-member upstream user. Must be explicit in code that this is a shared view |
| `continue_items` | **No** | no credential available |
| `recent_items` | Yes | latest books or new series; hand-off `https://read.avrana.net/...` (**to verify**) |
| `item`, artwork | Yes | thumbnail route; no comic pages ever (AVR-379 forbids page rendering, and `PAGE_STREAMING` stays off the service account if possible) |
| `search` | Yes | series and book search |

### Isolation hazards

1. **A shared view must never carry per-member state.** Because the catalogue comes from one account, any
   field in the response that is user-specific (read status, read progress, last-read date) belongs to the
   **service account**, not the member. The adapter must whitelist fields and drop all read-progress data,
   otherwise every member would see the service account's (empty or admin-influenced) state.
2. **Per-user restrictions are silently inherited.** *(UNVERIFIED against the deployed Komga.)* Komga supports per-user library sharing, age
   restrictions and label allow or deny lists. Today all libraries are shared by decision and no age or label
   restriction is documented, so a service account equals a member. If the owner later restricts one member,
   the shared catalogue would show that member items Komga itself hides. This is the main future hazard;
   it needs a documented invariant and a check in the operator runbook.
3. **Admin credential reuse** (Komf's admin login) would turn a catalogue adapter into an admin one. Forbidden.
4. **Read lists and collections.** Komga read lists and collections are server-global. Leaving them out of the
   route table avoids the leak and the AVR-379 "collection title leak" case; including them needs a visibility
   decision.
5. Hostname confusion: Komga is reachable by LAN IP and `read.avrana.net`; hand-off URLs must use the fixed
   `read.avrana.net` table entry only.

### Open questions (read-only checks, owner-approved later)

- Komga version, and whether per-user API keys exist and are accepted for REST and OPDS.
- Whether any member has a library restriction, age restriction or label rule (read the user list as counts).
- What fields the book and series endpoints return that are user-specific, so the whitelist is correct.
- Whether a non-admin account without `PAGE_STREAMING` can still fetch thumbnails.
- Best hand-off URL form for a series versus a book.

## 3. Calibre-Web-Automated

### Member mapping

CWA has no OIDC. Members sign in with their **Authentik username and password** through the LDAP outpost
(`docs/services/calibre-web-automated.md`, `services/authentik/blueprints/calibre-web-ldap.yaml`; user
filter `(cn=%s)`), gated by `avrana-books`. An LDAP user is imported into CWA's own user table on first
login. So the key is the **username**, the same as Jellyfin's, but CWA's handling of case when importing
an LDAP user is not documented here (**to verify**); the exact-match, refuse-ambiguity, never-loose rule
from the Jellyfin adapter applies. Local accounts exist too (`admin`, `Homepage`) and must never be mapped
to a member.

With the public interface only (OPDS and HTTP), the home cannot enumerate CWA users, so `resolve_user`
cannot confirm that a member has a CWA account. A member who never signed in to CWA has no account and
nothing personal anyway.

### Credential, and why this is catalogue-only

- Per the charter: **public APIs only, no database reads.** CWA has no clean REST API; its public interface
  is **OPDS** (Atom) plus the web UI. The Kindle connector reads and writes `app.db` directly today; that is
  its own documented exception and is not a precedent for the home.
- OPDS uses HTTP Basic. The patched image (`avrana-patch`) added a local-password fallback so a **local**
  non-admin account works in LDAP mode (the Homepage widget is the precedent; **UNVERIFIED** that this
  covers OPDS, and every Calibre-Web OPDS and local-account claim in this section is unverified against
  the deployed version). The home would use a dedicated local viewer account with no upload, edit, download-of-others or
  admin rights.
- OPDS exposes per-user views (read books, shelves) only for the authenticated account *(UNVERIFIED: OPDS
  read-state behaviour is from memory of the public documentation)*, and members'
  passwords are not available. So **per-member read state is not feasible**; `continue_items` is not
  offered. Reading progress sync (KOReader, Kobo) is per-user over its own credentials and is out of scope.

### Contract methods

| Method | Feasible | Notes |
|---|---|---|
| `resolve_user` | Catalogue-only, shared viewer account | explicit shared view, like Komga |
| `continue_items` | **No** | |
| `recent_items` | Yes | OPDS "new" feed; hand-off `https://books.avrana.net/book/<id>` (**to verify**) |
| `item`, artwork | Yes | OPDS entry and cover route; the cover route is an authenticated image fetch |
| `search` | Yes | OPDS search |

### Isolation hazards

1. **Shared view equals the viewer account's restrictions.** CWA supports per-user tag and custom-column
   restrictions and "hide" lists. The viewer account must be created with the same visibility as a normal
   member; a member with a restriction would see more than CWA shows them.
2. **Per-user shelves.** OPDS shelf and read-books feeds are per-account. The route table excludes them so
   the viewer account's shelves are never shown to members. Public shelves, if any, are a visibility
   decision.
3. **Parsing untrusted XML.** OPDS is Atom/XML. Use the standard library with entity expansion off
   (`xml.etree` is not hardened against entity bombs on every version; **to verify** and consider a size cap
   plus `defusedxml`-equivalent checks, noting the standard-library-only rule). Links in the feed are
   upstream-supplied and must never become hand-off or artwork URLs; only the numeric book id is extracted
   and validated (`[0-9]{1,9}`).
4. **LDAP cache window.** CWA's `cached` LDAP mode means a removed `avrana-books` member can keep OPDS
   access for a while (documented). The home's own permission check is by Authentik group before the call,
   so the home is stricter than CWA there; but the shared account is unaffected by it.
5. **Credential in URLs.** Some OPDS clients embed credentials in the URL. The adapter must send the Basic
   header from the transport only and strip userinfo from anything it stores.
6. **Send to Kindle** addresses live in CWA's user table and in ABS's global `ereaderDevices`; neither is
   ever read by the home (no route for them).

### Open questions (read-only checks, owner-approved later)

- CWA version and OPDS feed shapes (new, search, entry, cover URLs).
- Case handling when an LDAP user is imported.
- Whether the local viewer account authenticates for OPDS in LDAP mode with the patched image.
- Whether any member has tag or column restrictions in CWA.
- Whether the book detail page URL on `books.avrana.net` is stable (`/book/<id>`).

## 4. Recommended implementation order

1. **Jellyfin (done offline).** Contract proven against synthetic fixtures. Next step is the owner-approved
   read-only contract recording against the real server, after G1 and G2.
2. **Audiobookshelf.** Highest member value (listen position is the best "pick up where you left off"
   after video) and the only other service with true per-member progress. It is also the riskiest.
   Prerequisites: the owner decides the credential (admin-scope key held behind the GET-only guard, or
   catalogue-only), supplies the link list or confirms e-mail verification, and the read-only checks above
   have run. Implement with the same guard pattern; add tests for admin-view fallback, library and tag
   restrictions, and token fields in responses.
3. **Komga (catalogue only).** Low risk if the invariant "all libraries shared, no restricted members"
   holds. Needs a new non-admin service account. Offers recently added, search and artwork; Continue links
   out to Komga.
4. **Calibre-Web (OPDS catalogue only).** Lowest value and the awkward interface (XML, no clean API,
   per-account feeds). Do it last, and only for search and recently added.

Cross-cutting before any of 2 to 4: the contract needs one addition, a `shared_catalogue` marker on
adapters that cannot map members (Komga, Calibre-Web), so the UI and the cache treat their results as
group-gated rather than member-specific. Under the current cache rules those results would still be keyed
per member, which is safe but wasteful; sharing them is allowed only when the owner confirms the
"no per-member restrictions" invariant. This is a decision for the owner, not something to assume.
