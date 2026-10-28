# Real services path: from simulated data to the real Jellyfin, Audiobookshelf, Komga and Calibre-Web

Status: **plan, 2026-10-15. Nothing here has been run against a live service.** Avrana Home (`services/avrana-home`)
today runs only on hand-written synthetic fixtures and loopback mocks. This document lists what each adapter calls,
what it needs, what is proven only synthetically, what a live check must settle, and the ordered path, with the
owner approval that gates each step. It approves nothing; every live step needs the owner's own go-ahead.

Binding owner decisions (2026-10-15): Komga is a shared regular-account view with **no admin key** and nobody will
have Komga restrictions (ADAPTER-CONTRACT 12.2). Members are matched by **username** for the services that link per
member (Jellyfin, Audiobookshelf). Calibre-Web has no member restrictions (13.2). No real data collection happens
without the owner.

## 1. Per service

`ALLOWED_ROUTES` is the complete set of requests each adapter can make: GET only, no other path, no query keys beyond
those listed. Route shapes marked **UNVERIFIED** are recalled from public documentation and not checked.

| | Jellyfin | Audiobookshelf | Komga | Calibre-Web |
|---|---|---|---|---|
| **Adapter calls** | `/Users`, `/UserItems/Resume`, `/Items/Latest`, `/Items` (lookup by `ids` and search by `searchTerm`, both with `userId`), `/Items/{id}/Images/Primary` | `/api/users`, `/api/users/{uuid}`, `/api/items/{id}` (UUID or `li_`), `/api/items/{id}/cover`, `/api/libraries`, `/api/libraries/{id}/search` | `/api/v1/books/latest`, `/api/v1/books?search=`, `/api/v1/books/{id}`, `/api/v1/books/{id}/thumbnail` | `/opds/new`, `/opds/search?query=`, `/opds/cover_240_240/{n}` |
| **Credential** | API key (`Authorization: MediaBrowser Token=...`). Jellyfin keys have no scopes: administrator-equivalent. Dedicated, named for Home, rotatable | API token that can read other users' progress (**admin-capable**, ADAPTER-CONTRACT 11.1). Dedicated | **Regular (non-admin)** Komga account's API key (`X-API-Key`), comics libraries shared to it, no admin role. Never an admin key | HTTP Basic, a dedicated non-admin local viewer account (`user:password`) |
| **Minimum scope** | Read; the GET allow-list is the real limit, not the key | Same: allow-list, not the token, is the limit; the known risk of the design | Read; allow-list of three routes | Read OPDS catalogue only |
| **Members matched** | By username, exact and case-sensitive, via `/Users`; loose or ambiguous matches are `NOT_LINKED` | Same rule against `/api/users` `username`; e-mail is never used | **Not matched.** All members with `avrana-comics` map to one fixed shared viewer | **Not matched.** All members with `avrana-books` map to one fixed shared viewer |
| **Settings / env** | `HOME_UPSTREAM_MODE=real`, `HOME_GATES_VERIFIED=yes`, `HOME_IDENTITY_MODE=jwt_required` with `HOME_JWT_*` (the Jellyfin key is an admin key; 2026-10-27), `JELLYFIN_BASE_URL`, `JELLYFIN_API_KEY` or `_FILE` | `AUDIOBOOKSHELF_BASE_URL`, `AUDIOBOOKSHELF_TOKEN` or `_FILE` (set together) | `KOMGA_BASE_URL`, `KOMGA_TOKEN` or `_FILE`, `KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes` | `CALIBRE_WEB_BASE_URL`, `CALIBRE_WEB_CREDENTIAL` or `_FILE`, `CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes` |
| **Sections** | Continue, New | Continue only | New only (no Continue: read progress is the shared account's) | New only |
| **Verified only by synthetic fixtures today** | Every route, field and the key header form | Every route and field; whether OIDC-created accounts carry the Authentik username | Every route and field, that a regular key works at all, and that `latest` is filtered by the account's library sharing | Every OPDS route and Atom field; the `cover_240_240` path |
| **Live checks needed** | Key header form on 10.11.11; `/Users` and per-user list shapes; image route | Admin token reads `/api/users/{id}`; progress entries carry `userId`; item `expanded` shape | Regular key accepted (**UNVERIFIED**: the repo records `X-API-Key` rejected for admin once); `latest`, book, thumbnail shapes; **search** may need `POST /api/v1/books/list` instead of `GET /api/v1/books?search=` (**UNVERIFIED**, not built) | OPDS Basic accepted for the viewer; `/opds/new` shape; **search** may offer only `/opds/search/{term}` (**UNVERIFIED**, not built) |
| **Owner approvals gating it** | Key creation; the capture run; real-mode run | Admin-capable token creation and acceptance of its reach; capture; real-mode run | Creating the regular account and key; the invariant that no member is restricted; capture; real-mode run | Creating the viewer account; the no-restriction invariant; capture; real-mode run |

Komga detail: with a regular key every `/api/v2/*` route is refused by the guard before it leaves the process. The
shared account's read progress exists in book responses and is never read. Calibre-Web has no member read state
either. Search (AVR-383) is merged with this view on feat/lan-demo: Komga search uses the same shared listing.
Search and title-page route shapes are now marked doc-verified, live-verified or UNVERIFIED per service in
ADAPTER-CONTRACT 14.6 (2026-10-16); the table's "may need" notes are settled there (Komga's GET search is deprecated
but present; Calibre-Web has both `/opds/search?query=` and `/opds/search/{term}`; Jellyfin search moved to `/Items`).

## 2. The ordered path

**1. The owner's capture run (#47, branch `feat/avr-376-capture-tool`).** Owner-run, on the owner's machine, own
accounts, GET only, each request pre-checked against the adapters' own `ALLOWED_ROUTES`; credentials only via the
owner's shell environment; redacted and scanned before anything is written; `--dry-run` first. Gate: owner approval of
each live step; the tool's open MEDIUM finding (Jellyfin `HasPassword` refused) fixed and re-reviewed.
**Conflict to resolve before this step:** that branch's `capture_komga` calls `/api/v2/users` and
`/api/v1/series/{id}`. After this change neither is in Komga's `ALLOWED_ROUTES`, so the tool's guard would refuse
them (fail closed, nothing leaks). #47 needs a small follow-up to capture only `latest`, one book and one thumbnail
with the shared binding (`SHARED_VIEWER`), and its webtests need the same change.

**2. Fixtures updated from the capture, in a reviewed PR.** Owner hands over the redacted files; fixtures and their
`_provenance` change from "SYNTHETIC assumption" to "recorded, version X, date" only where the capture shows it.
Gate: independent review. Anything still unrecorded stays labelled synthetic.

**3. Adapter fixes for route-shape drift.** Per service, in separate reviewed PRs, tests first against the new
fixtures. Includes: whether Komga needs a different auth header or Basic, Calibre-Web OPDS differences, Jellyfin
header form. Search route shapes are settled only when AVR-383 lands and has its own capture.

**4. A real-mode run of Home on the owner's machine** against the real services, the owner's own account,
read-only, loopback-bound (`HOME_HOST=127.0.0.1`, the default), owner-operated and owner-approved.

- Settings are supplied only through the process environment of the owner's own shell for that run, or through
  `*_FILE` variables naming files **outside the repository** (for example under the owner's home directory, readable
  by the owner only) that the owner creates by hand at a hidden prompt. Nothing is committed, written by an agent or
  put in the command line. `Settings.from_env` reads them once at start; keys are never in a `repr`, a log line or an
  error message, and a bad value is a `SettingsError` naming the variable only. Real mode refuses to start without
  `HOME_GATES_VERIFIED=yes`, each service's URL and key together, and the two owner-confirmation flags for Komga and
  Calibre-Web; it refuses a URL with credentials, a query or a trailing slash. The dev identity shim refuses real
  mode by design, so it cannot be used here.
- **Gap, decision needed:** `HOME_GATES_VERIFIED=yes` states that production gates G1 and G2 passed. A local owner run
  would set it without that being true. There is no separate "local owner run" mode. Either the owner accepts setting
  it knowingly for a loopback-only run, or a reviewed change adds a narrower mode. Do not set it without that
  decision.
- **Identity for a local run:** Home trusts the `X-authentik-username`, `X-authentik-groups` headers (G1 is what makes
  that safe in production). On loopback the owner sends their own username and groups from their own client to
  `127.0.0.1`; this is acceptable only because the process is bound to loopback and used by the owner alone.
- The owner should expect: sections for the owner's own username only, mapping outcomes `NOT_LINKED` where the
  Jellyfin or Audiobookshelf username differs, results cached up to 60 s, and per-service degraded states if a
  service is down. Stop on anything unexpected; record the version of each service.

**5. Authentication: real Authentik identity.** Not done, owner and implementation work:
`avrana_home/outpost_jwt.py` verifies the outpost's signed token (D-3) but is **not wired in** to the app, and the
portal-side flag work (`jwt_log_only`, then `jwt_required`, AVR-498) needs a week of log-only reason codes and
separate approvals. G1 (network isolation of the identity headers) and G2 (authorization and isolation suites in
production) have not passed. Missing: wire verified-JWT identity into `identity.py` to produce the same
`MemberPrincipal`; the pinned provider secret or key supplied as a secret; the G1 and G2 evidence; the owner's go on
each.

**6. Staging and deployment (out of scope here; gates only).** Owner approval of a container, network and proxy
change; the Authentik outpost as the only path to Home (G1); G1 and G2 passed in production; verified-JWT identity
on; a rollback plan; each service's dedicated key created and rotatable; restriction invariants for Komga and
Calibre-Web confirmed in writing; independent review of the deployment change; the REAL-WORLD-CHECKLIST items for
member identity, progress, handoffs and degradation passed. Nothing in this repository deploys.

## 3. What this decision changes elsewhere

`REAL-WORLD-CHECKLIST.md` (outside the repo, `avrana-review-kit`): the item "Komga real mode unblocked in
`settings.py`" is done by this change; the Komga identity line moves from "login equals Authentik username" to
"no member mapping" (only Jellyfin and Audiobookshelf are username-matched); the Komga key must be a regular
account's and the capture tool must follow step 1's conflict note; Komga needs a "no member has a Komga restriction"
confirmation like Calibre-Web; the "term matching a title the member cannot see returns nothing" search check cannot
hold for Komga or Calibre-Web (shared views), only for Jellyfin.
