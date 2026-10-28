# Forking Seerr, Shelfarr and Omnibus for member requests: plan

Status: proposal, 2026-10-28. Nothing here is built, forked or deployed. It follows the owner's chat of
2026-10-27 ("really dig into how we can fork Seerr and Shelfarr and especially Omnibus to bridge the gaps we have
here: both security and features in general") and builds on `UNIVERSAL-SEARCH-AND-REQUESTS.md` (part 1).

Evidence is from the pinned images on host `avrana` (read-only `docker exec`, `sqlite3 -readonly`) and the upstream
sources named in that document. CONFIRMED means read in the running code or data; HYPOTHESIS means not yet checked.

## Summary

| Service | The gap that matters | Smallest fork change | Size (HYPOTHESIS) |
|---|---|---|---|
| **Omnibus v1.4.4** (comics) | No server-to-server search or request at all: session cookie only | API-key auth with a named on-behalf user on `/api/search` and `/api/request`, a `requests:create` key scope, key redaction in logs | 3 to 5 days + upstream review |
| **Seerr v3.4.1** (film, TV) | The only key is full admin, and `X-API-User` can name the admin | A scoped service key that can only search and create requests for non-admin users | 3 to 4 days |
| **Shelfarr 2026.10.19.1** (books) | Any token owned by an admin acts for everyone, including delete and grab; a global legacy token is set | `api_admin?` from scope only, a narrow `requests:on_behalf` scope, approval for member requests | 1 to 2 days |

Order: **Shelfarr first** (smallest, and Home already brokers it in the `feat/home-book-requests` PR), then
**Omnibus** (the only service with no path at all), then **Seerr** (it works today with the broad key; the fork
narrows a risk, it does not unblock anything).

Every fork follows the same rules, so it stays cheap to carry:

1. Each change is written as an **upstream pull request first**. The fork is only the branch we run until it is
   merged or refused. No product features that upstream would not want.
2. One fork repository per service under the owner's GitHub account, `avrana/<upstream tag>` branches, image built
   by GitHub Actions and pinned **by digest**, exactly like the upstream images today.
3. A **rebase budget**: the fork carries at most a few hundred lines. If upstream refuses a change and it grows past
   that, fall back to the "without a fork" option listed for each service.
4. No secret moves into Home that is not needed: no `NEXTAUTH_SECRET`, no Radarr or Sonarr keys, no member tokens.
5. Each fork has a rollback: re-pin the upstream digest; the database migrations are additive only.

## Shelfarr

### What is there (CONFIRMED, 2026.10.19.1 running on `avrana`)

- Scoped bearer tokens (`app/models/api_token.rb`): `search:read requests:read requests:write` are self-service;
  `requests:admin users:write` are privileged and count only when the token's **owner is an admin**.
- `Current.api_admin?` (`app/models/current.rb`) is `legacy_api_token_authenticated || api_user&.admin? ||
  api_token&.has_scope?("requests:admin")`. So **any token owned by an admin is an admin token**, whatever its
  scopes. With only `requests:write` it can create a request for any user (`find_user` takes `username`), and
  delete or grab any request (`request_scope` is `Request.all`).
- A **global legacy token** (`settings.api_token`) is set on `avrana`. When it matches, `legacy_api_token_authenticated`
  makes the caller an admin for every scope. Where it is used is not known (Homepage widget, HYPOTHESIS).
- No approval step: a request goes straight to search and download (`RequestCreationService`, HYPOTHESIS from the
  earlier read; check again on this version).
- Shelfarr already tracks Hardcover health per provider (`metadata_provider_statuses`: `status`,
  `rate_limited_until`, `failure_count`, `last_error`) and a per-user Hardcover budget
  (`hardcover_request_budgets`). The API-cap monitor reads these (see `API-CAPS-AND-MATCHING.md`).

### Security changes

| # | Change | Why |
|---|---|---|
| S-1 | `api_admin?` = `legacy || api_token&.has_scope?("requests:admin")` only. Session admins keep their web powers | A token's power should be what its scopes say. Today the owner's own token is silently an admin token |
| S-2 | New privileged scope `requests:on_behalf`: `create` may name another active user; nothing else (no index, show, destroy or grab of others' requests) | Home needs to ask *as* a member, never to list, cancel or grab everyone's |
| S-3 | Optional per-token **source allow-list** (CIDR) and **expiry** | Home's token works only from the Home container's network, and expires |
| S-4 | Log `api_token_id` (never the token) on every create, and the named user | An audit trail of who Home asked for |

Without a fork: mint Home's token from a **dedicated non-owner admin account** that has nothing else, and clear or
rotate the legacy `api_token` once its consumer is known. Home's own client already sends only the two
allow-listed calls (`requests/shelfarr.py`), so S-1/S-2 narrow what a **stolen** token could do, not what Home does.

### Feature changes

| # | Change | Why |
|---|---|---|
| F-1 | **Approval mode**: a setting `member_requests_require_approval`; requests by non-admins start as `pending_approval`; admins approve in the existing admin request list | Owner decision U-3. Shelfmark and Shelfarr write into the same inboxes; approval keeps downloads deliberate |
| F-2 | `GET /api/v1/requests?mine=1` honoured for `requests:on_behalf` with `username` (that user's own requests only) | "Requested by you" with the stage, in Home, without a listing token |
| F-3 | Search results carry `in_library: {ebook, audiobook}` from Shelfarr's own `library_items` / `books.hardcover_id` | Shelfarr already knows what it fetched; Home can say "Already in Books" without guessing |
| F-4 | Per-user daily request cap (setting) answered as 429 | A cap in the service, not only in Home's guard |

## Omnibus

### What is there (CONFIRMED, v1.4.4 and `main`)

- `/api/search` and `/api/request` read the NextAuth session (`getToken`); the middleware protects every `/api` path
  except a short list. API keys (`src/lib/api-auth.ts`, the `ApiKey` table) open only OPDS, cron, internal and
  `/api/v1/stats`. There is an admin impersonation route.
- The engine (Rust, `omnibus-engine`) does its own provider throttling (`rate_limiter`: getcomics, Prowlarr) and
  writes failures into `JobLog`.
- **Key leak (CONFIRMED, low to medium):** one `JobLog` row on `avrana` holds a ComicVine request URL with an
  **unredacted `api_key=`**. The error text of the HTTP client includes the URL. `JobLog` is shown to admins in the
  web UI and travels in every Omnibus backup. Nothing in the container log carries it (0 matches in 30 days).
- `Series` carries `cvId`, `metronId`, `matchState` and `folderPath` (101 of 120 series matched to ComicVine).
- `NEXTAUTH_SECRET` is also the database encryption key, so Avrana must never hold it.

### Security changes

| # | Change | Why |
|---|---|---|
| O-S1 | Strip URLs from provider errors before logging or storing (`reqwest::Error::without_url()` in the engine; the same for the web app's fetch errors) | Fixes the key in `JobLog`. **Owner action now, fork or not:** delete that one row or rotate the ComicVine key |
| O-S2 | `ApiKey.scopes` (`stats`, `opds`, `search`, `requests:create`) with the existing keys defaulting to today's behaviour | Today a key is all-or-nothing for the routes that take one |
| O-S3 | `ApiKey.allowOnBehalf` (admin-only to set) and an `X-Omnibus-User: <username>` header honoured only for such a key, only for non-admin users, only on `/api/search` and `/api/request` | The member is named; the key cannot become an admin |
| O-S4 | `AuditLog` row for each on-behalf call: key id, named user, action | Who asked, as whom |

### Feature changes

| # | Change | Why |
|---|---|---|
| O-F1 | `GET /api/search?q=` with the key returns the same JSON as the session route (ComicVine volumes with `cvId`, year, publisher, `inLibrary`) | Home's universal search can offer comics |
| O-F2 | `POST /api/request {cvId, scope: volume|issue}` on behalf; existing approval rules apply (Omnibus has request approval for non-admins, HYPOTHESIS: check the setting) | Ask for a comic from Home |
| O-F3 | A search deep link `/?q=` or `/search?q=` on the web UI | Hand-offs that land on the search, as Seerr's do |
| O-F4 | `GET /api/v1/series/ids` (key, `stats` scope): `{cvId, metronId, folderPath}` for matched series, no user data | Exact comic matching in Home (see `API-CAPS-AND-MATCHING.md`) without reading Omnibus's database file |

Without a fork: link out (works today), and read `Series` from the database file read-only for matching. Both are
already possible; only the request path needs code.

Effort: O-S1 alone is half a day and the best first upstream PR (no design debate). O-S2/O-S3 + O-F1/O-F2 are the
real work, 3 to 5 days with tests, then review time upstream. The project is young and mostly AI-written, so read
its test conventions first and keep each PR small.

## Seerr

### What is there (CONFIRMED, v3.4.1)

- One global `X-API-Key`. It runs as user 1 (the owner) unless `X-API-User: <id>` names another user, who then
  acts with their own permissions, quotas and auto-approve (`server/middleware/auth.ts`).
- Nothing stops `X-API-User` naming an admin, and the key also reads `/settings/*`, which holds the Radarr and Sonarr
  keys.
- Members sign in through Jellyfin, which authenticates against Authentik LDAP on `avrana` (drift check
  2026-10-28). No OIDC in Seerr itself.

### Security changes

| # | Change | Why |
|---|---|---|
| E-S1 | **Scoped service keys**: a table of named keys (hash stored), each with a permission mask that may include only `REQUEST`, `REQUEST_MOVIE`, `REQUEST_TV`, and search; created by the owner in Settings | Home stops holding a full admin key |
| E-S2 | A scoped key **must** send `X-API-User`, and the named user must not hold `ADMIN` or any `MANAGE_*` bit; the effective permissions are the intersection of the key's mask and the user's | No path from Home to admin, even with a bug in Home |
| E-S3 | Scoped keys never reach `/settings/*`, `/user/*/settings/*` or request status changes | The Radarr and Sonarr keys stay in Seerr |
| E-S4 | Optional OIDC sign-in (there is upstream work on this, HYPOTHESIS: check its state before writing any) | Today Jellyfin's LDAP path is the sign-in, which works; OIDC only matters if Jellyfin leaves LDAP |

### Feature changes

| # | Change | Why |
|---|---|---|
| E-F1 | `GET /api/v1/user/by-jellyfin/{jellyfinUserId}` for scoped keys (id and permission bits only) | Home maps member → Seerr user without paging the whole user list |
| E-F2 | Auto-create a Seerr user on first on-behalf call when the Jellyfin user exists and the owner enabled it | Members who never opened Seerr can still ask from Home (today: "Open the request website once") |

Without a fork: Home holds the global key behind its allow-list, server-side mapping, refusal of admin ids and an
always-sent `X-API-User` (owner decision U-1 in the earlier document). That is acceptable for a beta; the fork
removes the "one bug from admin" risk.

## Delivery plan

| Phase | Work | Gate |
|---|---|---|
| 0 (now) | Home's Shelfarr broker (draft PR), Omnibus `JobLog` row deleted or ComicVine key rotated, Shelfarr legacy token's consumer found and the token cleared or rotated, Home's Shelfarr token from a dedicated account | Owner |
| 1 | Shelfarr S-1, S-2, F-1 as one upstream PR set; fork image pinned on `avrana` only after upstream review or an owner OK | Owner merge + deploy |
| 2 | Omnibus O-S1 upstream (small, uncontroversial); then O-S2/O-S3/O-F1/O-F2 as a second PR | Upstream review |
| 3 | Home's comics broker on the Omnibus on-behalf API, same shape as the Shelfarr broker (signed forms, principal-only user, two allow-listed calls) | Phase 2 merged or forked |
| 4 | Seerr E-S1..E-S3 upstream; Home's Seerr broker switches from the global key to a scoped key | Upstream review |
| 5 | Feature extras (Shelfarr F-2..F-4, Omnibus O-F3/O-F4, Seerr E-F1/E-F2) as each upstream accepts them | none |

Each phase ends with: the fork's own tests green, Home's tests green against a fake of the new API, a read-only
live check, then one real request by the owner's own account before any member sees it.

## Open owner decisions

| # | Decision |
|---|---|
| F-D1 | Fork under the owner's GitHub account and run fork images, or upstream PRs only and wait |
| F-D2 | Shelfarr approval for member requests (F-1), or open requests with a daily cap (F-4) |
| F-D3 | Rotate the ComicVine key, or only delete the one `JobLog` row (the key is also in `services/omnibus/.env` and every backup) |
| F-D4 | Clear Shelfarr's legacy global `api_token` once its consumer is known |
| F-D5 | Seerr: accept the global key for the beta, or wait for E-S1 before a Seerr broker |
