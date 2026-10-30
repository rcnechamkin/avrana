# Avrana home web application

Status: **written 2026-10-12; deployed as the live member beta since 2026-10-29 (revision 2cb228f; see docs/release/MEDIA-2.0-RC2-STATE.md).** Slice M3.1 of
[Avrana Media 2.0](MEDIA-2.0.md) (Linear AVR-374, with the application half of AVR-375 and the
degradation half of AVR-385). The code is [`services/avrana-home/`](../../services/avrana-home/);
the adapter layer it sits on is described in [`ADAPTER-CONTRACT.md`](ADAPTER-CONTRACT.md).
Nothing here reads real member data, adds a container, edits the deployed portal, Authentik or
cloudflared, or creates a hostname. Gates G1 and G2 have not passed in production.

Approving this document approves no production step. Every cut-over step below is described, not
performed, and needs the owner's approval for that step with rollback material prepared first.

## 1. What it is

One small Python application: FastAPI and Jinja, server-rendered, no JavaScript except the one optional first-party script on shell pages (MK-3, DECISIONS.md 2026-10-26), no front-end
build, no broker, no database server. It does two things:

1. **Serves today's portal pages and redirects unchanged** (`/`, `/watch`, `/listen`, `/comics`,
   `/books`, `/kindle`, `/requests`, `/requestabook`, `/requestacomic`, `/contribute`, `/ops`,
   the choosers `/read` and `/request`, `/help`, `/help/<slug>`, `/account`, the `/watch`
   interstitial, `/healthz`). A parity test compares it with `services/avrana-portal/portal.py`
   for every fixture identity (section 4).
2. **Behind a flag (`HOME_SECTIONS`, default off)** renders the member's *Continue* and *Recently
   added* sections from the adapter layer as deliberately plain markup above the unchanged
   navigation, and exposes the same data as JSON at `/home.json` (section 5). With the flag on, the pages a member
   sees wear the Concept K shell (Home, `/library`, `/search`, title pages, `/me`, Account, Help), and the one
   script, the worker, `/offline` and `/signout` exist (section 5a).

```
request ─► HygieneMiddleware (method gate, headers, access log, error containment)
        ─► portal_route ─ Depends(get_viewer) ─► principal_from_headers (ONE identity path)
                        ─► routing.decide(path, groups)  ◄── catalogue (portal tables, one place)
                        ─► [HOME_SECTIONS] aggregate.gather(principal, adapters) ─► adapters ─► transport
                        ─► Jinja templates (autoescape on)
```

Layout (`services/avrana-home/`):

| Path | Contents |
|---|---|
| `avrana_home/app/settings.py` | Validated, immutable settings; refuses to start on bad values |
| `avrana_home/app/catalogue.py` | The route/service/help tables, loaded by path from the portal behind one seam |
| `avrana_home/app/routing.py` | The portal's routing decisions as pure functions (stdlib) |
| `avrana_home/app/viewmodel.py` | Section view-model, progress in words (stdlib) |
| `avrana_home/app/logsafe.py` | Redaction-by-construction logging helpers (stdlib) |
| `avrana_home/app/identity.py` | The single identity dependency |
| `avrana_home/app/middleware.py` | Outermost ASGI middleware |
| `avrana_home/app/main.py` | `create_app(settings)` |
| `avrana_home/app/serve.py`, `asgi.py` | Server entry points (the only modules that read the environment) |
| `avrana_home/app/templates/` | `base.html`, one template per page, `_sections.html`, `style.css` |
| `dev/` | `mock_jellyfin.py`, `dev_identity.py`, `run_dev.py` (development only, never shipped) |
| `webtests/` | Tier A and Tier B tests; `tests/run_web_tests.py` runs them for CI |

## 2. Identity

There is exactly one path from a request to a member: `identity.get_viewer` reads the raw ASGI
header list, keeps only the four headers the principal parser knows (`X-authentik-username`,
`-groups`, `-email`, `-name`), and passes them with their duplicates to
`principal.principal_from_raw_headers` as raw `(bytes, bytes)` pairs. Everything downstream takes a `MemberPrincipal`.

How headers really arrive (verified over a real uvicorn server, not assumed): uvicorn lowercases
names and delivers every repeated header as its own pair, so duplicates in any case combination
are visible; Starlette's `request.headers` would merge them, so it is not used. The route layer does no decoding of its own; the adapter layer's parser works on the raw bytes. Look-alike
names (`X_authentik_username`, `X-Forwarded-User`, `Remote-User`) never reach the parser and
confer nothing. A source-level test (`test_route_layer_source`) fails if any module other than
`identity.py` reads the query string, a cookie, a path parameter, a body, a form or a header, calls
an adapter directly, or builds a redirect from request input. Per-service identity mapping
happens only inside the adapters (`resolve_user`), reached only through `aggregate.gather`.

**Outcome for a request without a valid principal** (missing, empty, duplicated, malformed or
oversized identity headers): it is served exactly as the portal serves a request with **no
groups header and no display headers**. The home page shows the Help tile and nothing else, every
gated route and chooser and help topic is the standard 404 (byte-identical to an unknown path),
`/account` shows "Signed in: yes" with no identity facts, and no adapter is called. There is never
a 403, a redirect to sign in, or a hint that anything exists. This is the portal's own fail-closed
behaviour, applied to the stricter parser.

### Identity modes (AVR-498, `HOME_IDENTITY_MODE`)

`identity.get_viewer` is still the only reader of request headers. It now hands the trusted headers
to `principal.principal_for_request` with the mode from `Settings.identity_mode`; the mode has no
default inside the principal module, and the setting defaults to `headers`.

| Mode | Identity comes from | Notes |
|---|---|---|
| `headers` (default) | the plain `X-authentik-*` headers, exactly as before | Byte-identical to the previous behaviour. `X-authentik-jwt` is not read at all. |
| `jwt_log_only` | the plain headers (still served) | Also verifies `X-authentik-jwt` and logs one line `identity_jwt` with a fixed `reason` code through `logsafe`: `ok`, `identity_mismatch`, `missing_header`, `duplicate_header`, `unverified_identity`, or another `PrincipalError` code. Never a token, name or group. Never changes the outcome. |
| `jwt_required` | only a verified token | A header-only request has **no principal**. A valid token whose claims disagree with plain identity headers that are also present is refused (`identity_mismatch`). Duplicate JWT headers are refused. |

Optional beta allowlist: `HOME_ALLOWED_USERS` (a comma-separated list of exact usernames) is a second lock
behind the Authentik application binding. It is accepted **only with `jwt_required`**, because a username
from plain headers proves nothing; any other mode, an empty list or a malformed entry refuses to start. A
verified member not on the list gets the same "no principal" outcome and one `identity_jwt` line with
reason `not_allowed`. Unset means no restriction.

Every failure in every mode is the "no principal" outcome above (portal parity): the standard 404 on
gated routes, the Help tile, never a 403 and never a redirect. The verified path mints the same
`MemberPrincipal` type as the header path, so adapters, templates and the route layer are unchanged.

Algorithm and key: **HS256 with the proxy provider's client secret**, the same as the portal (#40) and
the canonical `outpost_jwt.OutpostJwtVerifier` (#35). Authentik 2026.5.6 resets proxy providers to
`signing_key = None` at startup, so the outpost's `X-authentik-jwt` ID token is HMAC-signed with the
client secret (see `D3-outpost-identity-proof.md`, E5 and E6). The verifier also supports RS256 with
pinned public keys, but Home does **not** expose it: there is no setting for keys, so a single
Authentik provider configuration (issuer, client id as audience, client secret) serves both the portal
and Home. Adding RS256 later would be a new setting, not a change of default.

The JWT modes need `HOME_JWT_ISSUER`, `HOME_JWT_AUDIENCE` and `HOME_JWT_SECRET` (or
`HOME_JWT_SECRET_FILE`, preferred; at least 32 bytes). `HOME_JWT_SECRET_PREVIOUS` (or `_FILE`) is an
optional rotation overlap, as in the portal. JWT settings in `headers` mode are refused at start, so
nobody believes a token is being checked when it is not. An unknown, empty or miscased mode is a
`SettingsError`. The secret is a `repr=False` field, absent from `repr(settings)`, errors and logs.

The development identity shim is **headers-only**: `check_startup` raises `DevIdentityRefused` when
`HOME_IDENTITY_MODE` is not `headers`, and it never mints or forwards tokens (a client `X-authentik-jwt`
is stripped like every other identity header).

Status: nothing in production selects a JWT mode. Turning on `jwt_required` for the gated beta
hostname is described in `docs/design/BETA-CHECKLIST.md` and needs owner approval at every live step.

### Differences from today's portal (each an owner decision)

| # | Request | Portal today | This app | Recommendation |
|---|---|---|---|---|
| I-1 | Valid username, **empty** groups header | Home with Help tile; `/account` prints Name, Username, Email | Same home; `/account` prints only "Signed in: yes" | **Keep strict.** A member with no groups is a misconfiguration; showing less is safe. A second, display-only parse would be a second identity path. |
| I-2 | Groups header but **no username header** | Grants by groups: full tiles | No principal: Help tile only | **Keep strict.** The outpost always sets both; a missing username means the request did not come through it. No behaviour change in production traffic. |
| I-3 | Username with leading/trailing space, `\|`, `,`, control or format characters, not NFC, or over 150 characters; groups header over 4096 characters, over 64 groups or a group over 128 characters | Grants by groups | No principal | **Keep.** Authentik cannot produce these. |
| I-4 | **Duplicate username** header | Uses the first value | No principal | **Keep.** Same reasoning as the existing duplicate-groups rule. |
| I-5 | Non-ASCII username (UTF-8, latin-1 or mojibake) | Latin-1 decoded and shown | No principal (adapter layer: `principal_from_raw_headers` refuses any non-ASCII username) | **Keep (owner decision).** Non-ASCII usernames get no principal, so a mojibake name can never map to another account. A non-ASCII display name is shown only if it is valid UTF-8. Tested over a real socket. |
| I-6 | Display name or e-mail that is duplicated, over 254 characters or contains control characters | Shown, whitespace-stripped | Omitted from `/account` | **Keep.** Display-only values never decide anything. |
| I-7 | Method other than GET and HEAD | 501 from `http.server`, before routing, body echoes the method | 501 from the middleware, before routing and identity, fixed body that does **not** echo the method | **Chosen: 501, not 405.** 501 is what members' clients see today; FastAPI's native 405 would differ per path and add an `Allow` header. Identical for every identity and path; same hygiene headers. |
| I-8 | Every response | Cache-Control, Referrer-Policy, X-Content-Type-Options (`nosniff`, asserted on every response) | Those three **plus** `Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` (no script source) | **Keep.** Exception (AVR-383): `/search` alone sends `form-action 'self'` so its GET form can submit; every other page keeps `'none'`, title pages (`/title/<service>/<id>`, AVR-384, no form) included. Exception (Home 2.0, AVR-364): every page that renders the shell (Home with sections, Library (`/library`, MK-5a), Search, title pages, the Me hub `/me` (AVR-719; shell only, otherwise the standard 404), Account, Help and help topics, and the Read, Request and Watch pages when they wear the shell) adds `manifest-src 'self'` for the web app manifest (`app/install.py`); `respond()` sets it whenever a shell is rendered. Exception (MK-3, AVR-717, owner decision O1, DECISIONS.md 2026-10-26): the same shell pages also add `script-src 'self'; worker-src 'self'` for the one first-party page script and the service worker (`app/pwa.py`); the `/sw.js` response alone adds `connect-src 'self'`, and `/offline` adds `font-src 'self'`. Never an inline script, `unsafe-inline` or `unsafe-eval` for script, or another host. Every other response keeps the CSP above unchanged. Inline `<style>` is how the portal is built today; dropping it needs a stylesheet route and the design team's agreement. |
| I-9 | Protocol-level problems (malformed request line, unknown HTTP version, oversized headers) | Python `http.server` replies (400/505) with the three headers | uvicorn/h11 replies **before the application runs**: 400/431 with no application headers; `HTTP/9.9` is accepted. h11's 16 KiB header limit holds only while a request is incomplete, so a request read in one piece (Linux asyncio) reached the application whatever its size (AVR-732); the outermost middleware now refuses a header block over 16 KiB with 431 and fixed text before identity. One budget inside it (`app/identity.py` `IDENTITY_HEADER_BUDGET`, owner 2026-10-26): `X-authentik-jwt` up to `identity.MAX_JWT_HEADER_LEN` 8192 (a longer token header is dropped before verification, reason `oversized_header`; the shared verifier's own 16384 stays, since the portal vendors it byte for byte), username 150, groups 4096, e-mail and name 254 each, and at least 3 KiB (3332 bytes) for every other header; a request inside it is never refused as too large (an oversized token gives no token, so jwt_required fails closed; not a 431), and a parser limit raised alone fails at import | **Accept.** These replies carry no application data. Documented, tested to contain no page, at the socket and on the ASGI scope (independent of read size). |
| I-10 | Connection reuse | HTTP/1.0, one request per connection (pinned by the portal tests so a connection never carries two identities) | uvicorn keeps connections alive | **Accept.** Identity is read per request and no state is per connection; pipelined and reused connections are tested with different identities. |
| I-11 | `/readyz`, `/home.json`, `/_dev/*` | 404 | `/readyz`: loopback peer only, else 404. `/home.json`: only with `HOME_SECTIONS` on and a valid principal, else 404. `/_dev/*`: 404 (the shim is not part of the app) | **Keep.** Unchanged for anyone who is not an operator on the host or a member with the flag on. |

Everything else is identical: status codes, `Location` targets (a fixed table; no request input
reaches a redirect), the 404 body for denied and unknown routes, trailing-slash, query and fragment
handling, case sensitivity, no percent-decoding, `//` collapsing, HEAD, and the HTML of every page.

## 3. Resilience

Sections are gathered with the adapter layer's own bounds (about 2 s per call, no retries, a
shared circuit that opens after 3 consecutive service-wide failures and cools off for 60 s,
one shared 2 s deadline per page, at most 2 in-flight calls per member and 8 per service, single-flight so one cold page makes one `/Users` call; excess work is shown with the reasons `member_busy` or `queued`). One adapter down, slow, returning 500,
returning malformed JSON, or returning another member's data costs **its own section only**; the
navigation, Help, Account and every other route are unaffected. Each mode is tested through the
HTTP layer against the mock (stopped, slow, down, 500, malformed, wrong-user).

Two behaviours worth knowing:

- **The cache is per member and short (30 s continue, 120 s recent).** A member whose page is warm
  keeps seeing it while the upstream is down; the outage appears for members whose cache is cold.
  This is the adapter contract working as designed.
- **A wrong-user answer poisons only the call it arrived on.** The mock's `wrong-user` mode answers
  the resume list with the other member's items naming that member; the adapter discards it
  (`UpstreamMisbehaved`, section shown as unavailable) while the recently-added list still renders.
  An upstream that returns another member's items **without** any identity marker is undetectable
  (ADAPTER-CONTRACT section 7, residual risk); only the recorded read-only contract check against
  the real Jellyfin can close that.

### Degradation matrix (MEDIA-2.0 section 5) as implemented

| Dependency down | What a member sees here | What still works |
|---|---|---|
| Jellyfin | "Movies and TV are unavailable right now." in the Continue and Recently-added sections of members who may use it (members who may not see nothing, byte-identical to flag off) | Everything else on the page, Help, Account, redirects |
| Audiobookshelf, Komga, Calibre-Web | The same pattern, per library (all four adapters exist; the beta image rehearses Jellyfin down in CI) | |
| A request service | Not applicable to this slice (links only, redirects are static) | |
| Authentik or cloudflared | Nothing (outside the app) | |
| The media array (unmounted) | Same as Jellyfin down; operator steps in `docs/runbooks/home-degraded-library.md` | |
| The home app itself | Roll back (section 9) | All per-service hostnames and native apps |

### Health

- `GET /healthz` is **liveness only**: always 200 `ok`, no identity read, no upstream call, no
  member data. HEAD and trailing slash behave as in the portal.
- `GET /readyz` is **the detail view**: the adapter layer's `health_summary` (per-adapter state `ok`, `failing`, `cooling_off` or `unknown`, `consecutive_failures`,
  last error class, seconds until retry; no member data; `libraries` is `degraded` on `failing` or `cooling_off`), as JSON. It is served **only to a peer
  on the loopback interface that carries no identity or forwarding header**, so a member arriving
  through the outpost (whose TCP peer is the Authentik container) gets the standard 404, and the
  container's own health check or `docker exec` can read it. Setting `HOME_HEALTH_DETAIL=off`
  removes it. This relies on the server **not** rewriting the peer address from `X-Forwarded-For`
  (`serve.py` sets `proxy_headers=False`; do not run uvicorn with `--forwarded-allow-ips='*'` as the
  Audible connector does). Owner decision H-1 below.

## 4. Portal parity

`webtests/test_web_parity.py` renders every route (about 50, including unknown paths and the
variants `/watch/`, `/watch?q=1`, `//`, `/help/`) for every identity in
`tests/fixtures/identities.py` through the stdlib portal (in memory) and the app, and asserts equal
status, equal `Location`, equal `Content-Type` and equal body after one documented normalisation:
**whitespace collapsed, and the entity spellings `&#39;`/`&#34;` (markupsafe) read as
`&#x27;`/`&quot;` (`html.escape`)**; these are equivalent HTML and are the only non-whitespace
change. Identities whose headers do not form a principal are compared with the portal given no
identity headers (the documented behaviour above). `test_web_realserver.py` repeats the comparison
for odd targets (percent-encoding, `//`, backslashes, absolute-form, hostile Hosts) with the same
bytes sent to both, the app over a real socket.

The templates mirror the portal's markup one-for-one: `base.html` is the shell, each page extends
it, and the stylesheet is `templates/style.css` (a copy of the portal's `STYLE`, injected once).
The portal's accessibility repairs (AVR-357) and viewer-dependent copy (AVR-430) have merged to main and
the shell tracks them: `.page`/`main`/`footer nav` landmarks, `nav.tiles`, `color-scheme`, the help topic
`h2`, and `SERVICE_VARIANTS`/`CHOOSER_PARTS` through `catalogue.service_copy` and `chooser_subtitle`.
Any further portal markup change fails the parity test until `base.html`, the affected templates and
`style.css` are updated, which is the intended forcing function. Text from the portal tables is trusted static markup
(entities, apostrophes) and is rendered as written through a `Trusted` type that request data
can never become; everything else is autoescaped. Hostile titles, usernames, names and e-mails are
tested for escaping.

At cut-over the tables move into the app. Today `catalogue.load()` executes `portal.py` by path
(it has no import-time side effects) and copies the tables into frozen dataclasses; only that one
function changes, because every consumer goes through the seam.

## 5. Home sections and the JSON view

*The markup described in this section is M3.1's plain rendering. The shell pages now render the same view-model in
Concept K (DESIGN.md; section 5a); the state rules, the JSON view and the "unavailable" rule below still hold.*

`HOME_SECTIONS=on` adds, **above** the unchanged navigation tiles, one plain `<section>` per
section the adapters return. No classes, no images, no script, no new CSS (the portal stylesheet
styles `section`/`h2` only where it already does). Each item is a link whose `href` is the
contract's `handoff_url`, followed by optional series/subtitle text and progress in words.

| State | Rendering | Notes |
|---|---|---|
| `ok` | `<h2>` and a `<ul>` of links; progress as "1 hour 10 minutes left" (or "42 percent watched", "just started") | Words, never a bare bar. |
| `empty` | **Nothing at all** | Least presumptuous. Owner decision E-1. |
| `unavailable` | `<p role="status">Movies and TV are unavailable right now.</p>` under the section heading | Names only a library the member is permitted to use. |
| `not_linked` | `<p role="status">Movies and TV are not set up for your account yet.</p>` | Neutral, no error tone, no operator name. |
| `not_permitted` | **Absent.** The response is byte-identical to flag-off output (tested) | No markup, no hint. |

`GET /home.json` returns exactly `HomeSections.member_view()` for the verified member, with
`Cache-Control: no-store` and the other hygiene headers. It exists only when `HOME_SECTIONS` is on
and the request has a valid principal; otherwise it is the standard 404. It takes no input: a
`userId`, `user` or `groups` in the query string, cookie or body changes nothing (tested).

Schema (the adapter contract's, section 4; `reason` is never serialised):

```
{"sections": [ {"service": "jellyfin"|"audiobookshelf"|"komga"|"calibre-web",
                "section": "continue"|"recent",
                "state": "ok"|"empty"|"unavailable"|"not_linked",
                "items": [ {"id", "service", "kind", "title", "subtitle"|null, "series"|null,
                            "progress": {"fraction","percent","position_seconds","duration_seconds"}|null,
                            "artwork": {"ref","alt"}|null, "creator": str|null, "year": int|null, "handoff_url"} ] } ] }
```

One example per state (synthetic, produced by the tests' mock):

```json
{"sections": [{"service": "jellyfin", "section": "continue", "state": "ok", "items": [
  {"id": "jellyfin:aaaa0000000000000000000000000001", "service": "jellyfin", "kind": "movie",
   "title": "Synthetic Film One", "subtitle": "2001", "series": null,
   "progress": {"fraction": 0.42, "percent": 42, "position_seconds": 3024, "duration_seconds": 7200},
   "artwork": {"ref": "jellyfin/primary/aaaa0000000000000000000000000001", "alt": "Poster for Synthetic Film One"},
   "handoff_url": "https://watch.avrana.net/web/#/details?id=aaaa0000000000000000000000000001"}]}]}

{"service": "jellyfin", "section": "continue", "state": "empty", "items": []}
{"service": "jellyfin", "section": "continue", "state": "unavailable", "items": []}
{"service": "jellyfin", "section": "continue", "state": "not_linked", "items": []}
{"sections": []}      <- not_permitted: the section is omitted, so a member without the group gets this
```

### Home: one rule for "unavailable" (polish pass, 2026-10-16)

A library counts as unavailable when **any** of its sections says unavailable (`viewmodel.library_down`). That one
rule drives both the notice and the places bar, so they cannot disagree. In the first minutes of an outage a
section can still answer from the cache (recently added is cached for 120 s) while Continue fails. Before, Home
then said "Movies and TV are unavailable right now." while New this week showed Movies and TV items and Watch was
not struck. Now the place is struck and the notice reads "Movies and TV are unavailable right now. Anything shown
from them may be out of date."; the cached items stay (they are still the member's own and may still open), and Try
again is offered. Chosen over hiding cached items (an emptier page for a two-minute blip) and over leaving the place
up (a struck notice beside a live-looking place). Read is struck only when every library behind it is down. The
cost: a single failing call (for example Continue discarded by the scope tripwire) also strikes the place while
the library otherwise answers; the notice says "may", and Try again recovers it.

When nothing answers: everything unavailable is one calm block ("Your libraries are resting") with one combined
line (the library's name when there is one library, otherwise "None of your libraries is answering right now."),
never a line per library above it. Everything not set up (member-c, member-d) is one "Not set up yet" block with
the sentence and "What to do next" (`/help/trouble#not-set-up`). A mix keeps the per-library lines, Try again and
the next step.

`artwork.ref` is opaque. `GET /art/<ref>` (for example `/art/komga/book/<id>`) serves it, member-scoped: `app/artwork.py` is the one module that calls `fetch_artwork`, with the verified principal and a ref of the exact shape `service/word/id` (`[A-Za-z0-9_-]` only). Unknown service, bad ref, missing group, an item the member may not see, an upstream failure and a refused content type are all the same standard 404. Responses carry `Cache-Control: private, no-cache` with an `ETag` (revalidated through the same checks; `304` only for an allowed member), `nosniff`, and only `image/jpeg|png|webp` of at most 5 MiB (never SVG or HTML). Section items render `<img src="/art/..." alt=<title> width="80" height="120" loading="lazy">` only when a valid ref exists.

### Search results and title pages (AVR-383/384)

`GET /search?q=` groups results by library, in member language, only for the member's own libraries. Each result
shows its medium (Movie, Series, Episode, Audiobook, Book, Comic), title, creator and year when the adapter read one,
and small artwork through `/art/` only. **One link per result**: to the title page for libraries whose adapter offers
the member-scoped item lookup (Jellyfin, Audiobookshelf, Komga), otherwise (Calibre-Web, OPDS has no single-book
route) straight to the library, marked "Opens in Books". The title link's accessible name is "<title>, <medium>".

Truthful states, never mixed: results (`N results`, with a note for each library that could not answer); every
library answered and none matched (`No results`, spelling hint, request offers); some answered with no match and
some could not answer (`No results`, naming the libraries that could not be searched); **no library could answer**
(`Not searched`, "could not be searched right now", Try again; never "no matches", never a request offer); only
not-set-up libraries; no searchable library; invalid term.

Request fallback: only when at least one library answered with no match, and only for the request service that
fills that library **and** that the member's own catalogue holds (Seerr for Movies and TV; the books request service
for Books and Audiobooks; the comics request service for Comics). Links read "Ask for a film or show", "Ask for a
book or an audiobook", "Ask for a comic". Seerr gets the cleaned term through its documented search address
(`https://<catalogue host>/search?query=<percent-encoded>`; host from the static catalogue only), and the page says
"Opens the request website" beside that link (and in its accessible name); the others link to their portal route
(`/requestabook`, `/requestacomic`), which redirects by the fixed table. Nothing is submitted. The search hint is
plain ("At least 2 characters."): the wildcard and escape characters `clean_query` turns into spaces are not listed,
because none of them makes a term unusable while letters remain (tested).

Account (shell only) splits "Your access" into Libraries and Requests in Home's language ("Movies and TV", never
"Watch" or "Movies & TV"), each name once; a request service is named by the libraries it fills for this member, so
a books-only member never reads "Audiobooks". Remaining services (Send to Kindle, Contribute, Operations) are listed
under "Also". With sections off, Account is the portal's page, byte for byte.

`GET /title/<service>/<id>`: the shell masthead, `<h2>` title, artwork in its natural shape, the library (with the
medium only when the library's name does not already say it: "Episode · Movies and TV", but "Movies and TV" for a
movie), creator and year, series or episode, progress in words whenever the upstream reports it for this member,
and ONE primary action that opens the item in its library, by the Continue rule (`continue_state`): Resume for a
saved position, Open when there is progress but no position, otherwise Watch / Listen / Read. It never says
playback started. Under it, an inline link to "If something doesn't open" (`/help/trouble`). Footer: Back to search
(only when the address carries a term that passes `clean_query`, re-encoded; no other query parameter is read) and
Back to home; Help is the places bar's. A library not set up for the member links `/help/trouble#not-set-up`. Not permitted, unknown, hidden, malformed or hostile ids and a missing
identity are the standard 404, identical to an unknown route. An unavailable library is a 503 page "The ... library
is unavailable right now" with Try again; it says nothing about whether the title exists. The strict CSP applies.
Every view makes the permission-checked upstream lookup (no cache), so access removed upstream shows at once.
Hand-off links (results and the primary action) must be on the item's own service host (`contract.HANDOFF_BASE`).

## 5a. Shell pages, the script and the worker (Concept K, AVR-713)

Owner decision O1 (2026-10-25, quoted in DECISIONS.md 2026-10-26) reverses "no JavaScript" **for Home shell pages
only**: one first-party page script and one service worker, both from Home's own origin, as progressive
enhancement. MK-3 (AVR-717) built it; MK-2 (AVR-716), MK-4 (AVR-718) and MK-5 (AVR-719) built the pages. These
invariants hold on top of sections 2 to 5; nothing here weakens an identity, isolation or revocation guarantee.

**Works with JavaScript off.** Every page renders completely on the server and works with no script: the tab bar's
lens is printed by the server (`data-at`), cards and the hero are plain links, Library chips and Recently added tabs
are links, Search is a plain GET form with a button, Sign out is a link. The script only adds behaviour on top.
JavaScript-off parity is tested per page (`webtests/test_web_pages_k.py`, `test_web_library_k.py`,
`test_web_shell_k.py`) and by the browser checks with JavaScript disabled.

**What makes a page a shell page.** One flag: `respond(decision, scope, shell=...)` with shell data sets
`scope["avrana_shell"]`. From that one flag come the manifest link, the font, the `<script src>` tag,
`viewport-fit=cover`, the tab bar, and the CSP's extra sources; a test asserts "script tag if and only if
`script-src`" on every route and identity. `shell_for` gives shell data only when `HOME_SECTIONS` is on, the request
has a valid principal and adapters are built; otherwise the page is the portal's, byte for byte (section 4).

**Home's rails (owner decision 2026-10-28).** After Continue, Home shows **New releases**, by the release date
itself across the member's libraries (Jellyfin `PremiereDate`, Komga `releaseDate`, Audiobookshelf `publishedDate`
or a bare year as 1 January; a future cover date sorts as today; never what Continue already shows; hidden when
nothing has a date), then **New to Avrana**, the rail that was Recently added (by when a library added it, with its
library tabs). The hero without Continue says New to Avrana. The Watch filter adds New releases after Up next; Listen
and Comics keep their own New releases shelf. The All page gathers each library's `released` section after Continue
and New to Avrana (cached 300 s), so a member still holds at most two upstream calls per library at once.

**Shell routes** (all `Cache-Control: no-store`, all through `respond()`):

| Route | Shell page | Without the shell |
|---|---|---|
| `/` | Home: lockup, places bar, hero, Continue, New releases, New to Avrana | The portal's tile page |
| `/library` (MK-5a) | Library tab page; `?lib=` picks one of the member's own libraries | Standard 404, byte-identical to an unknown route |
| `/search` | Search tab page (`form-action 'self'`) | Standard 404 with sections off |
| `/title/<service>/<id>` | Title page; 503 page when the library is unavailable | Standard 404 |
| `/me` (MK-5b) | Me hub | Standard 404, byte-identical to an unknown route |
| `/account`, `/help`, `/help/<slug>` | Account, Help, topics (under Me) | The portal's pages |
| `/help/trouble` | "If something doesn't open" | Standard 404 |
| `/read`, `/request`, `/watch` | Place pages with the Home button | The portal's chooser and interstitial |

Old URLs (`/watch`, `/listen`, `/comics`, `/books`, `/request`, `/requestabook`, …) keep resolving exactly as in the
portal. The tab bar's links are `/`, `/library`, `/search`, `/me`; a member without a library gets Home and Me only.

**Non-page routes added by MK-3** (`app/pwa.py`), each only where the shell can render (sections on, adapters built;
otherwise the portal's 404, listed in the parity test), the same bytes for every viewer, no identity needed:

| Route | What it is |
|---|---|
| `/static/home.<hash>.js` | The page script (`app/assets/home.js`), `text/javascript`, path carries a content hash |
| `/sw.js` | The service worker (`app/assets/sw.js`, filled in by `pwa.py`), scope `/`, no `Service-Worker-Allowed` |
| `/offline` | The static page the worker shows when the network fails |
| `/signout` | The sign-out hop (D10) |

**CSP per route class** (base = `default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none';
form-action 'none'; frame-ancestors 'none'`; single source `middleware.csp_for`):

| Response class | CSP |
|---|---|
| Shell pages | base + `; manifest-src 'self'; font-src 'self'; script-src 'self'; worker-src 'self'` (`/search`: `form-action 'self'`) |
| `/sw.js` | base + `; connect-src 'self'` (the worker takes its CSP from its own response) |
| `/offline` | base + `; font-src 'self'` (no script, no manifest) |
| Everything else: the script file, `/signout`, manifest, icons, `/brand/*`, `/art/*`, `/home.json`, `/healthz`, `/readyz`, 404, 501 and error pages, the generic 500 page even when a shell route failed, sections-off pages, portal, Kindle, Audible | base, byte-identical to before |

Never an inline script, an `on*=` handler, `unsafe-inline` or `unsafe-eval` for script, a `data:` source or another
host. `style-src 'unsafe-inline'` is unchanged everywhere (inline `<style>`, no `style=` attributes for data).
`connect-src` is never on a page (D12).

**What the page script may do** (all of it; `app/assets/home.js`, loaded with `defer` in `<head>`, never between
`<body>` and the skip link):

1. Move the lens: on a plain left click on a tab it sets `data-at`, never prevents navigation, ignores modifier keys,
   the current tab and same-page links, does nothing with Reduce Motion, and restores the printed value on
   `pagehide`.
2. Register `/sw.js` (`scope: '/'`, `updateViaCache: 'none'`) after `load`, and show the update prompt ("A new version
   of Avrana Media is ready." and Reload, `role="status"`) only when a new worker waits while an old one controls the
   page; Reload sends exactly `{type: 'SKIP_WAITING'}` and reloads once on `controllerchange`.
3. Reload a page restored from the back/forward cache (`pageshow` with `persisted`), so it passes the outpost again.
4. With the kill switch on, unregister any worker and delete `avrana-*` caches instead of registering.

It may not: read member data, use `localStorage`, `sessionStorage`, IndexedDB or cookies, build HTML from text
(`innerHTML`, `document.write`), `eval`, or make a request of its own (no heartbeat, D13). A static test scans its
bytes for those APIs. Inline previews and transitions were part of O1's purpose but are not in the script.

**What the worker may do** (`app/assets/sw.js`):

- Navigations: pass the original request to `fetch` untouched, so a redirect to sign-in stays an opaque redirect the
  browser follows; answer with the stored `/offline` page only when that fetch throws a `TypeError` (no network).
  A 302, 401, 403, 404 or 5xx is returned as it is. Navigations to `/signout` and `/outpost.goauthentik.io/` are not
  handled at all, so the hop's headers and the outpost run as real navigations.
- Store, at install and all or nothing, an exact allow-list of identity-free static files: the page script,
  `/offline`, the paths in `brand.ROUTES` (font, lockup, favicon, Spire-A) and `install.ICON_PATHS`. Each response is
  guarded before it is stored: status 200, `type 'basic'`, not redirected, the one content type allowed for that
  path, no `Vary: *`, non-empty and under 512 KiB. Install requests use `redirect: 'error'` and `cache: 'reload'`.
- Serve those files cache-first; cache name `avrana-shell-<hash of worker source and stored bytes>`; activate deletes
  every other `avrana-*` cache; no `clients.claim()`; `skipWaiting()` only on the page's exact message.

It may not: answer a navigation from cache, store or read any member page, `/art/*`, `/home.json`, search results or
the manifest, store a `Request`, read credentials or request headers, use any storage but its own cache, call
`importScripts`, or follow a cross-origin redirect. Every non-navigation request outside the allow-list gets no
`respondWith` (navigations always get `respondWith(fetch(request))`, apart from the sign-out paths above).

**Sign-out hop (D10).** `GET /signout` answers 303 to the catalogue's fixed outpost target
(`/outpost.goauthentik.io/sign_out`) with `Clear-Site-Data: "cache", "storage"`, never `"cookies"` (that would sign
the member out of every app on the registered domain). It clears this site's HTTP cache, worker and storage on this
device; it does not end the Authentik session on auth.avrana.net, and no copy says it does (U-19 open). Me and
Account link Sign out to it on shell pages; sections-off Account keeps the portal's direct link (parity). Verified in
Chromium on localhost only: Safari and Firefox are unverified, and plain http (the LAN preview) ignores the header.
Like the outpost link it replaces, it is a state-changing GET reachable by a cross-site navigation.

**Authentik (D9).** Everything, including `/sw.js`, the manifest, `/offline`, the icons and the script, stays behind
the outpost. No exempt paths, no `skip_path_regex` (G1 review F5). While signed out, worker updates and the manifest
fetch get the sign-in redirect and fail quietly; they retry on the next signed-in load.

**Caching (D11, `/art` amended 2026-10-27).** Every response stays `no-store` except `/art`: `private, no-cache` plus an `ETag`, revalidated through the full permission check before every use (304 only for an allowed member). The
script's hashed path, not a header, keeps a stale script from pairing with new HTML.

**Kill switch and rollback limits.** `HOME_PWA_SW=off` (section 7) makes `/sw.js` a worker that deletes its caches
and unregisters itself, and the page script removes registrations and caches instead of registering. It reaches only
devices that load a shell page or fetch `/sw.js` while signed in, so it must be set with `HOME_SECTIONS` still on and
held long enough for active devices. Turning sections off or reverting the image does not remove installed workers
(section 9): they keep serving their stored static files and the offline page, and never member data.

**Not verified.** Nothing ran on a phone, over HTTPS or behind the real outpost; installability, standalone
behaviour, the iOS Home Screen cookie jar, `Clear-Site-Data` on Safari and bfcache with `no-store` on Safari are
research findings, not tests. The device review (AVR-585, D17) runs on the Concept K build.

## 5b. Asking for a book (request broker, Shelfarr)

Status: deployed 2026-10-29; ON in the live beta (`HOME_BOOK_REQUESTS=on`) (section 7). Design and the owner decisions:
`docs/design/UNIVERSAL-SEARCH-AND-REQUESTS.md`.

`GET /request/books` (a shell page) searches Shelfarr (2026.10.19.1, `/api/v1/search`, `content_kind=book`) as Home's
own token and lists the matches with one button per format the member may ask for: Ask for the ebook only for a
member holding `avrana-books`, Ask for the audiobook only for `avrana-audiobooks`. A member holding neither, an
unverified viewer, and every viewer while the switch is off get the standard 404. Upstream cover and source URLs are
dropped; nothing on the page loads from elsewhere.

`POST /request/books` creates one request in Shelfarr (`/api/v1/requests`) **for the verified member**: the username
is the principal's, lower-cased, never a form field. It is the only POST Home answers, and only while the switch is
on; every other POST stays 501. The rules, in order:

1. The middleware: an exact path match and a single `Content-Length` of at most 4096 bytes, else 411 or 413 (fixed
   text) before the application runs.
2. The member holds Books or Audiobooks, else 404.
3. CSRF: `Sec-Fetch-Site: same-origin`, or, from a browser without it, an `Origin` equal to the `Host`; else 403.
4. The body is `application/x-www-form-urlencoded` with exactly `work_id`, `book_type`, `title`, `author`, `q`,
   `token` (`q` is the search the form came from: navigation only, never signed, never sent upstream).
5. The token is an HMAC over the member, those four fields and an expiry 15 minutes out: only fields Home rendered
   for this member can be posted, unchanged. The key is derived from the JWT client secret
   (`HMAC(secret, "avrana-home/request-forms/v1")`), so open pages survive a restart; without a secret it is a
   per-process random key and a restart expires them.
6. The format belongs to one of the member's libraries.
7. A guard per member: the same book and format twice within a minute is answered "You just asked" without a call;
   more than 10 attempts an hour is refused (429).

**Post-redirect-get.** Every answer except the 429 is a 303 to the page's own fixed path (`/request/books`); nothing
from the request is ever in a `Location`. The outcome, the titles just asked for and the search term go into a
one-shot, per-member flash (in memory, two minutes), so the next GET shows the outcome over the same results with the
button for that title replaced by "Asked for the ebook just now"; a reload shows neither and never re-sends the form.

**Searches.** A GET with a term searches once; HEAD never does. Results are cached per process (Shelfarr: ten minutes,
shared, since Home searches as its own account; Seerr: two minutes per member, dropped when that member asks for
something from it). Each member gets 40 upstream searches in ten minutes; past that the page says "You have searched
a lot in the last few minutes" and cached searches still answer.

Outcomes, in fixed words: asked for (Shelfarr 201 or 202: "It appears in Books once it arrives"); could not be asked
for (422: already asked for or owned); not set up (404: the member has never signed in to Shelfarr, with a link to
the member's own request place); could not be reached (anything else, including a lost token scope, which also
counts toward the breaker). A timeout is never retried. Log lines carry the service, a fixed state and the format
only. Search's empty-results fallback links books and audiobooks to this page (with the term) instead of the
Shelfarr site while the broker is on.

The token can name any Shelfarr user (`requests:admin`); that is why the username comes only from the verified
principal and why the client can send exactly the two allow-listed calls (no listing, cancel, users or settings).

**Already in the library.** With `HOME_LIBRARY_IDS_FILE` set, each result is checked against the catalogue-id index
(`requests/owned.py`, written on the host by `tools/build_catalogue_index.py`, design in
`API-CAPS-AND-MATCHING.md`). The keys are the ids Shelfarr returns (`hardcover:<id>` from every provider it merged,
edition ISBNs) and the ids CWA and Shelfarr's Audiobookshelf mirror stamped on the files. Rules:

- Only the member's own formats are looked at; a library the member does not hold is never mentioned.
- Books (a shared view): an exact hit shows "Already in Books. Open", linking to the book in Books, and that format
  loses its ask button.
- Audiobooks (per member): an exact hit is shown only after the adapter's permission-checked item lookup finds it for
  this member (at most three lookups a page); the link is Home's own title page.
- A likely hit (same folded title and author surname, no shared id) keeps the ask button and adds "Audiobooks may
  already have this. Check", linking to Home's own search. It is never shown as owned.
- No file, an unreadable or malformed file, a wrong version, or an index older than 36 hours (or with no `built`
  time): no claims at all. A stopped builder therefore cannot leave Home saying "Already in Books" about a deleted
  file. The file holds catalogue ids and folded title keys only, no member data.

## 5c. Asking for a film or show (request broker, Seerr)

Status: deployed 2026-10-29; ON in the live beta (`HOME_WATCH_REQUESTS=on`). Same shape and gates as section 5b, with these
differences:

- **Who Home acts as.** Seerr has one global key (full admin). Every search and request is sent with `X-API-User` set
  to the member's own Seerr user, so Seerr's per-user permissions, quotas and auto-approve apply. That user is found
  by the Jellyfin user Home already maps the member to (the Jellyfin adapter), matched against Seerr's
  `jellyfinUserId` (user list read with the key, at most 2,000 users within a six-second deadline, cached 10 minutes;
  a miss re-reads at most once a minute; a read past its deadline is abandoned as "could not be reached"). User 1, any user with ADMIN or MANAGE_* permission bits, and a Jellyfin id shared by two Seerr users
  are refused: the member reads "Requests are not set up for your account yet", and nothing is searched.
- **Real mode needs verified identity.** As for the Audiobookshelf token, `HOME_WATCH_REQUESTS` (and
  `HOME_BOOK_REQUESTS`) in real mode require `HOME_IDENTITY_MODE=jwt_required`: their credentials can act as any
  member, so a forged username must be impossible.
- **Allow-list.** `GET /api/v1/search`, `GET /api/v1/user` (mapping only, never as a member) and
  `POST /api/v1/request`. Search and request without a member are refused in the client before anything is sent.
- **What the member reads, per title** (people are dropped): *Ask for this film* / *Ask for this show* (a show asks
  for every season); *Already in Movies and TV. Open* (Home's own title page) when Seerr knows the library item AND
  this member's own Jellyfin lookup finds it (at most three lookups a page); *Ask for the missing seasons* for a show
  that is partly there; *Already asked for* (never by whom); *Not available to ask for* (blocklisted or removed).
- **Outcomes.** Asked for (201; "it waits for approval first" when Seerr holds it for approval); already asked for
  (409); could not be asked for (403 quota or permission, 202 nothing left); not set up; could not be reached.
- **Search fallback.** "Ask for a film or show" on Search's no-results group goes to `/request/watch?q=` instead of
  the Seerr site while the broker is on and the member may use it.

**The Request chooser.** While a broker is on and the member may use it, its row on `/request` opens Home's own ask
page ("Search and ask here") instead of the request website; otherwise the row is unchanged.

The fork plan (`REQUEST-FORKS-PLAN.md`, Seerr E-S1..E-S3) replaces the global key with a scoped key that cannot act as
an administrator at all; until then the rules above are the lock. The Avrana fork's patch is ready locally
(`avrana/v3.4.1`, not yet published): `ON_BEHALF_API_KEY` acts only as a non-administrator member on search, title
details, request list/create and deleting that member's own request, and without a member reaches only the user
directory and the Jellyfin import. Home needs no change to use it: it goes in `SEERR_API_KEY`.

## 5d. My requests

Status: deployed 2026-10-29; there whenever either broker is on (sections 5b, 5c). `GET /request/mine` (a shell
page) lists the member's own requests from Shelfarr and Seerr, newest first, in two groups: **On the way** and
**Done**. A member who may use neither broker gets the standard 404. The ask pages and the Request menu link here.

**Only the member's own rows, twice over.**

- Shelfarr: `GET /api/v1/requests?username=<member>&limit=100`. The Avrana fork's `requests:on_behalf` token
  scopes this to that member (and never to an administrator). Upstream's `requests:admin` token ignores
  `username` and returns everyone's, so the client drops every row whose `user.username` is not the member; only
  formats whose library the member holds are shown.
- Seerr: `GET /api/v1/request?requestedBy=<member's Seerr id>`, sent AS the member (`X-API-User`); rows whose
  `requestedBy.id` is anyone else are dropped. Titles come from `GET /api/v1/movie/<id>` / `tv/<id>` as the member,
  cached per process for a day; at most three seconds a view are spent looking titles up, and a row still unnamed
  says "Reload to see its name".

**What each row says** (fixed words; nothing upstream sends is shown): Looking for it · Not found yet (looked for
again) · Waiting for the owner (only a paid copy found) · On its way · Waiting for approval · Partly arrived ·
Arrived · Declined · Could not be fetched · Stopped (Shelfarr records a cancel as "failed" with no attention flag,
so cancelled and given-up requests read the same). "The owner has been told" appears when Shelfarr flagged it.
Arrived titles link to Home's own pages: a film or show to its title page after this member's own Jellyfin lookup
(at most five a view), anything else to Home's search for the title. Nothing links to the request services.

**Taking a request back.** `POST /request/mine` with exactly `service`, `request_id`, `title`, `token`: the same
locks as asking (switch, group, same origin, exact fields, a signed token for this member and these fields, the
guard), then:

- Shelfarr: read the request as the member first; only if its owner is the member and it is pending, searching,
  not found or awaiting purchase (never a download or import in progress) is `DELETE /api/v1/requests/<id>` sent.
- Seerr: only a request in the member's own list that still waits for approval. Seerr itself lets any
  non-manager delete any pending request, so this check is Home's.

The answer is a 303 back to `/request/mine` with a one-shot outcome ("Cancelled your request for …").

**Errors are said as errors.** A member whose Jellyfin lookup is busy or failing is told film requests "could not be
reached", never "not set up" (which would send them off to sign in). This uses the contract's `member_link`, which
is `resolve_user` with the reason kept; the watch ask page uses it too.

**Arrivals.** A request that arrived in the last three days is marked **New**, and Done lists the newest arrivals
first; the page title counts them ("2 new, 1 on the way"). This is worked out from the upstream dates alone (Shelfarr
`updated_at`, Seerr `mediaAddedAt`, the latest imported Omnibus issue): Home keeps no state and reads no cookie, so
"seen" cannot be remembered. A "just arrived" card on Home itself is a design and owner decision (it would add the
brokers to every Home load), not built.

Comic series (section 5e) appear one row per series ("12 of 20 issues arrived"); they have no cancel button, because
the Omnibus fork's key cannot cancel.

Each view reads the lists fresh and counts against the member's search allowance (section 5b); HEAD reads nothing.

## 5e. Asking for a comic series (request broker, the Omnibus fork)

Status: deployed 2026-10-29; ON in the live beta (`HOME_COMIC_REQUESTS=on`). Needs the Avrana fork of Omnibus
(`rcnechamkin/omnibus`, `avrana/v1.4.4`): an administrator mints an API key and switches on "on behalf". With that key
and `X-Omnibus-User: <member>`, the fork accepts exactly `GET /api/search` and `GET`/`POST /api/request`, never as an
administrator, with the member's own Request permission and auto-approve; every use is in Omnibus's audit log.

`GET /request/comics` (a shell page, members holding Comics) searches ComicVine through Omnibus as the member;
Metron-only results are dropped (ComicVine ids are what the library and the index use). Each series offers **Ask for
this series** (every issue, and new ones as they come out), or, when the catalogue-id index holds its ComicVine id,
**Already in Comics. Open** (Komga's own series page; Comics is a shared view, so holding the group is the
permission) with **Ask for missing issues**. `POST /request/comics` takes exactly `cv_id`, `title`, `year`,
`publisher`, `q`, `token` and the same locks as books and films. Outcomes: asked for, waits for approval, could not
be asked for (403/400: no Request permission, manga switched off, unresolvable), not set up (401), could not be
reached. Results are cached ten minutes (metadata only, the same for every member).

## 5f. Choosing seasons

On `/request/watch`, a show offers **Ask for every season** and **Choose seasons**, which opens
`/request/watch?show=<TMDB id>`: the show's seasons read from Seerr as the member (`GET /api/v1/tv/<id>`, specials
left out), each saying what is there (in Movies and TV, partly there, already asked for). Only seasons that may still
be asked for have a checkbox. The form posts the same signed fields as any watch ask, plus `pick` and one
`season_<n>` checkbox per chosen season (n from 1 to 60; anything else is refused by the form reader). Nothing chosen
sends nothing ("Choose at least one season"). Seerr checks the season numbers against the show.

## 5g. Creating a member's request accounts (off by default)

Members never mint keys or sign up anywhere by hand (Media 2.0). Two switches let Home create the account the first
time a member asks, and nothing else:

- `HOME_SHELFARR_PROVISION=on` (needs the Shelfarr token's `users:write` scope): when an ask answers "not set up",
  Home creates a **plain** Shelfarr user named after the member (Shelfarr's API takes only name, username and
  password; never a role), with a random password that is used once and never kept, then asks again once. The member
  signs in to Shelfarr through Authentik; Shelfarr's **link existing users** setting must be on, so that sign-in joins
  this account by username. (Shelfarr's own auto-create names users after the e-mail address, which Home could not
  find.) A member whose username Shelfarr cannot hold (only `a-z`, `0-9`, `_`) is never provisioned.
- `HOME_SEERR_PROVISION=on`: when a member with a Jellyfin account has no Seerr user, Home runs Seerr's own **Import
  Jellyfin users** for that one member, from the ask pages only (never from viewing My requests), then maps them
  again. Seerr gives the user its default permissions; one that comes out an administrator is still refused.

Both are logged as `account_provision` with the service and a fixed state only.

## 6. Logging

Structured JSON, one object per line, to stderr. Fields: `route` (the route **template** such as
`/help/{slug}` or `/{service}`, never the raw path), `method`, `status`, `duration_ms`, `service`,
`section`, `state`, `reason`, `error_class`. `logsafe.log_event` accepts only those field names and
replaces any string that is not an identifier-shaped token, so a username, title, id or URL cannot
be logged by mistake. Exceptions are logged as their class only; the generic 500 page carries no
detail. uvicorn's access logger (which prints raw query strings) is disabled by `create_app` and
`configure_logging`, and `serve.py` also sets `access_log=False`. `test_web_ops.LogContractTests`
captures every record (message, args, `exc_info`, extra attributes) across about 2,000 requests
(seven identities including duplicate-header and no-library members, six mock modes, hostile
titles, an exception whose message contains an identity, a title and a key, queries containing a
marker) and asserts none contains an identity, e-mail, group, title, item id, key, upstream address
or query marker, while confirming the structured fields really are present.

## 7. Settings

All settings come from the environment (`Settings.from_env`, called only by `serve.py`/`asgi.py`);
`create_app` takes a `Settings`. Any invalid value stops startup with a `SettingsError` naming the
variables (never the values).

| Variable | Default | Meaning and failure behaviour |
|---|---|---|
| `HOME_SECTIONS` | `off` | `on` enables the sections and `/home.json`. Not a boolean: refuses to start. |
| `HOME_UPSTREAM_MODE` | `mock` | `mock`: loopback URL only, fixed fake key, a real key present is an error. `real`: see below. |
| `JELLYFIN_BASE_URL` | `http://127.0.0.1:18096` (mock mode only) | http(s), no credentials, query, fragment or trailing slash. Required in real mode. In mock mode a non-loopback host is an error. |
| `JELLYFIN_API_KEY` / `JELLYFIN_API_KEY_FILE` | none | Real mode only; exactly one; the file form is preferred (`docs/SECRETS.md`). Never in a repr, log line or error message. |
| `HOME_GATES_VERIFIED` | unset | Real mode requires the literal `yes`: an operator's statement that G1 and G2 are applied and verified. |
| `AUDIOBOOKSHELF_BASE_URL` | unset (adapter not built) | Optional. Same URL rules as Jellyfin. Mock mode: loopback only. Real mode: needs the token too, and the same gates. |
| `AUDIOBOOKSHELF_TOKEN` / `AUDIOBOOKSHELF_TOKEN_FILE` | none | Real mode only, with the URL, exactly one of the two; a token in mock mode is an error. It is an admin token, so real mode also needs `HOME_IDENTITY_MODE=jwt_required` (ABS admin-token review 2026-10-27, HIGH; the sealed owner preview is exempt). Never in a repr, log line or error message. |
| `KOMGA_BASE_URL` / `KOMGA_TOKEN` (`_FILE`) / `KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS` | unset (adapter not built) | Optional. Mock mode: loopback URL, the token is fixed and fake, the flag is ignored. Real mode (owner decision 2026-10-15, ADAPTER-CONTRACT 12.2): needs `HOME_GATES_VERIFIED=yes`, the URL, a REGULAR (non-admin) account's key and `KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes`; otherwise a startup error. |
| `HOME_BOOK_REQUESTS` / `SHELFARR_BASE_URL` / `SHELFARR_TOKEN` (`_FILE`) | `off` / unset / unset | The request broker (section 5b). `on` needs `HOME_SECTIONS=on` and the URL; the URL or token without the switch is a startup error. Mock mode: loopback URL, the token is fixed and fake, a real token is an error. Real mode: the token is required; the same URL rules as the adapters (plain http only to loopback or a single-label Docker name). The token is minted by the owner in Shelfarr with exactly `search:read requests:write requests:admin`. Real mode also needs `HOME_IDENTITY_MODE=jwt_required`. Never in a repr, log line or error message. |
| `HOME_COMIC_REQUESTS` / `OMNIBUS_BASE_URL` / `OMNIBUS_API_KEY` (`_FILE`) | `off` / unset / unset | The comic request broker (section 5e). Same rules as Seerr's: `on` needs `HOME_SECTIONS=on` and the URL; mock mode loopback with a fixed fake key; real mode needs the key (an on-behalf key from the Omnibus fork) and `HOME_IDENTITY_MODE=jwt_required`. |
| `HOME_SHELFARR_PROVISION` / `HOME_SEERR_PROVISION` | `off` / `off` | Create a member's Shelfarr account, or import their Jellyfin user into Seerr, on first ask (section 5g). Each needs its broker on. |
| `HOME_WATCH_REQUESTS` / `SEERR_BASE_URL` / `SEERR_API_KEY` (`_FILE`) | `off` / unset / unset | The film and TV request broker (section 5c). `on` needs `HOME_SECTIONS=on` and the URL; the URL or key without the switch is a startup error. Mock mode: loopback URL, fixed fake key. Real mode: the key is required, and `HOME_IDENTITY_MODE=jwt_required` (the key is full Seerr admin; Home always names the member). Never in a repr, log line or error message. |
| `HOME_LIBRARY_IDS_FILE` | unset | Absolute path of the catalogue-id index (section 5b), mounted read-only; re-read at most every minute when it changes. Absent or malformed: no "Already in" claims. A relative path refuses to start. |
| `CALIBRE_WEB_BASE_URL` / `CALIBRE_WEB_CREDENTIAL` (`_FILE`) / `CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS` | unset / unset / `off` | Optional. Mock mode: loopback URL, fixed fake credential. Real mode is refused unless the owner setting is `yes` (default off; Calibre-Web is a shared view, ADAPTER-CONTRACT 13.2), and then also needs `HOME_GATES_VERIFIED=yes`, the URL and a `user:password` credential together. The constructor's `owner_confirms_no_member_restrictions` is `True` only in mock mode or from that setting. |
| `HOME_IDENTITY_MODE` | `headers` | `headers`, `jwt_log_only` or `jwt_required` (section 2). Unknown, empty or miscased: refuses to start. |
| `HOME_JWT_ISSUER`, `HOME_JWT_AUDIENCE` | unset | Required in a JWT mode (the provider's issuer URL and client id); refused in `headers` mode. |
| `HOME_JWT_SECRET` / `HOME_JWT_SECRET_FILE` | none | Required in a JWT mode: the proxy provider's client secret (HS256), at least 32 bytes, exactly one of the two forms. Never in a repr, log line or error message. `HOME_JWT_SECRET_PREVIOUS` (`_FILE`) is an optional rotation overlap. |
| `HOME_TIMEOUT` | `2.0` | Per-call seconds, 0.1 to 10. |
| `HOME_SECTION_LIMIT` | `12` | Items per section, 1 to 50. |
| `HOME_HEALTH_DETAIL` | `loopback` | `loopback` or `off`. |
| `HOME_PWA_SW` | `on` | `off` is the kill switch for the service worker (MK-3): `/sw.js` serves a worker that removes itself and its caches, and the page script stops registering one. It only reaches a device that can fetch `/sw.js` or load a shell page, so rollback needs `off` with `HOME_SECTIONS` still on, held long enough for active devices to come back (section 9). |
| `HOME_MOTION_PROPOSAL` | `off` | `on` turns on the motion Proposal (MK-6, AVR-720): page-to-page transitions run at the 600 ms Proposal token instead of tier 3 (200 ms), on every page that carries the shell stylesheet (shell pages and the offline page). During a transition, where the browser exposes it, the first press ends it and a touch tap then reaches the page; a mouse click during the transition may be lost, for longer than at 200 ms. For the owner to compare only; never with Reduce Motion. |
| `HOME_NOTICE_FILE` | unset | Absolute path of the operator notice file (AVR-365) that the OliveTin action "Member notice on Home" writes; mount its directory read-only. Unset: no notices. The file may be absent (no notice). It carries a notice ID and a time only; the words are fixed in `avrana_home/app/notice.py`, and an unknown ID or malformed file is no notice. Re-read at most every 5 seconds. A relative path refuses to start. |
| `HOME_CATALOGUE_PATH` | the portal's `portal.py` | Must be a file; the tables are loaded from it. |
| `HOME_HOST`, `HOME_PORT` | `127.0.0.1`, `8096` | Bind address for `serve.py`. A container must set `HOME_HOST=0.0.0.0` deliberately. |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR. |

Real upstream adapters stay disabled unless `HOME_SECTIONS=on` **and** `HOME_UPSTREAM_MODE=real`
**and** `HOME_GATES_VERIFIED=yes` **and** an explicit URL and key are present **and** (2026-10-27, the Jellyfin key is an admin key) `HOME_IDENTITY_MODE=jwt_required`. With the flag off no
transport or adapter is even constructed. The development identity is deliberately **not** a
setting.

Audiobookshelf (AVR-381): the adapter is registered next to Jellyfin only when `AUDIOBOOKSHELF_BASE_URL` is set; it adds one *Continue listening* section (the adapter offers no recent list, so that section is `empty` and renders nothing). Dev: `run_dev.py --abs-mock-port 18097` starts `dev/mock_audiobookshelf.py`, which serves the adapter's own synthetic fixtures (`tests/fake_abs.py`, loaded by path, read-only). `member-a` and `member-b` carry the audiobooks group in the dev identities.

Komga (AVR-382): registered the same way, from `KOMGA_BASE_URL`; it adds one *Recently added to Comics* section. It is a SHARED regular-account view (ADAPTER-CONTRACT 12.2): every member with the comics group sees the same books, no user list is read, and the shared account's read progress is never shown (no Continue). Dev: `run_dev.py --komga-mock-port 18098` runs `dev/mock_komga.py` over `tests/fake_komga.py`; the dev identities `comics-a` and `comics-b` exist to show two members getting the same section. `dev/` is never imported by the package (`webtests/test_dev_isolation.py`).

Calibre-Web (AVR-380): registered the same way from `CALIBRE_WEB_BASE_URL`; one *Recently added to Books* section, the same for every member who holds the books group (shared view, no member mapping, no Continue). Dev: `run_dev.py --calibre-mock-port 18099` runs `dev/mock_calibre_web.py` over `tests/fake_calibre_web.py`. Covers go through `/art/calibre-web/cover/<id>` under the same 404 rules.

## 8. Development stack and the identity shim

`python services/avrana-home/dev/run_dev.py --dev-identity` (venv with the pinned requirements)
starts the mock Jellyfin and the app on 127.0.0.1 with sections on, using the real
`UrllibTransport`. Locally there is no outpost, so the shim `dev/dev_identity.py` injects
`X-authentik-*` headers for a chosen **synthetic** member. It is the most dangerous code here and
is built so it cannot be enabled by accident:

1. It lives outside the `avrana_home` package; `create_app` does not know it exists and `Settings`
   has no switch for it (a test searches the package for any trace).
2. It needs the explicit `--dev-identity` (or `HOME_DEV_IDENTITY=on` for `run_dev.py`) **and**
   `check_startup` must pass: loopback literal bind (127.0.0.1 or ::1), mock mode, loopback mock
   URL, the fixed fake key. Otherwise `DevIdentityRefused`, before anything starts.
3. The middleware cannot be constructed without the sealed token `check_startup` returns.
4. Strip-then-set happens in one function: every client-supplied header named like an identity
   header (any case, `_` or `-`, any `x-authentik*`, `x-forwarded-user`, `remote-user`,
   `x-dev-identity`) is removed, then the chosen member's headers are added. A client can only pick
   among the fixed members, by the `X-Dev-Identity` header or the cookie the switcher sets.
5. Every HTML page carries a "DEVELOPMENT IDENTITY" banner. The switcher is `/_dev/identity`.

Tests prove: the default app ignores the switch entirely (headers and cookie do nothing; `/_dev/*`
is 404); startup fails with a non-loopback bind and with a non-mock upstream URL, key or mode;
client-supplied identity headers are never trusted, with or without a selection.

## 9. Recovery, cut-over and rollback (described, not performed)

**Recovery.** The app is stateless; the cache is SQLite on `:memory:` and disposable (a restart costs one slow
page). It is constructed once per process, exposes **no file-path setting**, and is closed on shutdown. `purge_member` is the offboarding hook and is wired to nothing here (owner decision). Rebuild the
image from Git, restore its environment/secret file from 1Password, start. Its env file joins the completeness gate
when it exists. The one exception is the **member store** (owner decision S1, 2026-10-28;
`avrana_home/memberstore.py`): when `HOME_MEMBER_STORE` is set, each member's own photo and display name live in that
SQLite file in the `./state` volume, which then joins the backup set. A lost store costs members their photo and name
(Home falls back to the sign-in name and initial); nothing else depends on it. Offboarding purges a member's row
(`python3 -m avrana_home.memberstore purge <username>`, docs/runbooks/offboarding.md Step 5).

**Cut-over (per MEDIA-2.0 section 5).** The new app runs as its own container. Launch points the
`avrana-portal` proxy provider's internal host at it; rollback points it back; the previous portal
container stays deployed and unused for at least two weeks. Each of these is an owner-approved
change with a rehearsed rollback, and none is prepared by this change. The beta hostname (AVR-373,
decision D-5) must exist first, gated on `authentik Admins` plus named testers.

**Rolling back the service worker (MK-3, AVR-717).** The kill switch is `HOME_PWA_SW=off` **with `HOME_SECTIONS`
still on**. Then `/sw.js` answers 200 with a worker that deletes its `avrana-*` caches and unregisters itself, and
shell pages load a script that removes any registration and cache it finds. Keep it that way long enough for active
devices to reach it (a browser checks for a new worker on a navigation, at least once a day, and only while the
member is signed in). The switch cannot reach an installed worker once the server stops serving the new worker:
turning sections off makes `/sw.js` a 404 (the worker stays installed on devices that already have it, and a
browser may or may not unregister it), and a device whose Authentik session has ended gets a redirect to sign-in
instead of `/sw.js`, so it keeps its old worker until it signs in again. Rolling back by reverting the image or by
turning sections off therefore does not remove workers already installed; it only stops new ones. The worker
stores only static files and sends every page navigation to the network, so a worker that is left behind does not
show member data, but it does keep serving its stored script and offline page. Do not change the portal for this.
`/signout` clears this site's cache and storage on the device, which also removes the worker for that member.

**Before real adapters may be enabled** (all must be true and recorded):
1. G1 applied and verified (private network per backend, so only the outpost can reach the app and
   the identity headers can be trusted); decision D-3 (shared-secret header) decided.
2. G2 merged and deployed (the portal suite, and this app's matrix passing against the beta).
3. A **recorded, read-only contract check against the real Jellyfin** (route and field names in the
   adapter are unverified; the "upstream ignores `userId`" residual risk needs this).
4. **Name reconciliation** for members whose Jellyfin and Authentik names differ (the mapping is
   exact and case-sensitive; mismatches show as "not set up yet").
5. A read-only Jellyfin key scoped as narrowly as Jellyfin allows, stored per `docs/SECRETS.md`.
6. The beta hostname (AVR-373) and member acceptance testing.

## 10. Tests

Run from the repository root.

| Tier | Needs | Command | What it covers |
|---|---|---|---|
| A (stdlib) | system Python 3.12 | `python -B tests/run_offline.py` | Everything else in the repo plus, for the web app: settings, catalogue seam, routing decisions against the stdlib portal, view-model, log helpers, the source-level route-layer guard, the mock Jellyfin and the adapter path over loopback HTTP, the dev shim's safety checks. Tier B modules **skip with** `SKIP avrana-home web suite: fastapi not installed (run with the pinned requirements)` |
| A+B | the pinned requirements (`services/avrana-home/requirements.txt`) | `<venv python> -B services/avrana-home/tests/run_web_tests.py` | Everything above plus parity, the identity matrix (test client and real uvicorn), sections, JSON view, degradation, isolation, headers, health, logs, the dev stack. Exits non-zero if the framework is missing or any test is skipped |

The existing 137 adapter tests are unchanged (`services/avrana-home/tests/`, which forbid every
socket); the web tests run in a separate process because they need loopback.

## 11. For the design team

> *Updated 2026-10-26 (MK-7):* this section describes the M3.1 hand-over. The shell pages are now designed and built
> to Concept K (DESIGN.md, "Concept K · Avrana Console"; section 5a for routes, script and worker). The paragraphs
> below stay as the record of what M3.1 left open; "deliberately unstyled / not built" no longer holds for shelves,
> rails, cards, artwork, search, title pages or empty states.

**Routes** (all server-rendered HTML except `/home.json`): `/`, `/account`, `/help`,
`/help/<slug>`, the choosers `/read` and `/request`, the service redirects and the `/watch`
interstitial, 404. Nothing about their composition is decided here: the pages reproduce today's
portal exactly.

**Where things live.** One shell: `avrana_home/app/templates/base.html` (blocks `title`, `heading`,
`body`, `footer`). One page per template. One stylesheet: `templates/style.css`, injected inline
(`style-src 'unsafe-inline'` in the CSP; a linked stylesheet needs a static route and a CSP
change). The section markup is **`templates/_sections.html` and nothing else**: plain `<section>`,
`<h2>`, `<ul>`, `<a>`, `<span>`, `<p role="status">`, no classes. Replace it freely; keep the
state rules (section 5). Presentation logic (progress wording, headings, messages) is in
`viewmodel.py`; the JSON at `/home.json` carries the raw numbers if you prefer to compute your
own. Text is escaped by Jinja autoescape; only catalogue text passes the `trusted` filter.

**Deliberately unstyled / not built:** shelves, rails, cards, artwork (no image route yet), search,
title pages, the operator notice banner, the welcome page, empty-state copy, loading states.

**Fixture scenarios** (run `python services/avrana-home/dev/run_dev.py --dev-identity`, open
`/_dev/identity`, pick a member; or send `X-Dev-Identity: <name>`):

| Member | State you get | Why |
|---|---|---|
| `member-a` | `ok` (3 in progress incl. an untitled one, 3 recent) | Movies and TV, mapped, items |
| `member-b` | `ok` (different items; shares one title with a) | Plus books and comics groups, so the Read tile |
| `member-c` | `not_linked` (disabled account) | Group yes, Jellyfin account disabled |
| `member-d` | `not_linked` (no account) | Group yes, no Jellyfin account of that name |
| `member-nolib` | `not_permitted`: no section, page identical to flag off | No video group |
| `synthetic-admin` | `not_permitted` plus the Operations tile | Admin group only |
| (none selected) | no principal: Help tile only | |

Failure states: `curl -X POST http://127.0.0.1:18096/__mock/mode/<ok|slow|down|500|malformed|wrong-user>`
then reload as a member whose cache is cold (the cache keeps a warm member's page for 30 s).
`unavailable` appears for each failure mode; `empty` has no mock member (the unit tests use a stub).

## 12. Owner decisions this change raises

| # | Decision | Recommendation |
|---|---|---|
| I-1 to I-6 | The stricter-principal differences in section 2 | Keep strict |
| I-7 | 501 (chosen) rather than 405 for unsupported methods | Keep 501 |
| H-1 | Who may see per-adapter health detail | Loopback peer only (implemented); `off` if you prefer to rely on logs. Never to members |
| E-1 | Copy for `empty` | Render nothing (implemented). Alternative: one neutral sentence such as "Nothing in progress." |
| N-1 | Copy for `not_linked` | "Movies and TV are not set up for your account yet." (implemented); the design system may want a "contact" route (MEDIA-2.0 D-1) |
| U-1 | Copy for `unavailable` | The charter's sentence (implemented) |
| S-1 | The portal's `STYLE` is copied into `templates/style.css` and the CSP allows inline styles | Keep until design phase 2 (one shared stylesheet) |
| C-1 | At cut-over, move the tables into the app and retire the by-path load | After the a11y branch merges |
| P-1 | Plain `uvicorn==0.34.0` (no `[standard]`: no uvloop, httptools, websockets, watchfiles) run with `--http h11`; `requirements.lock` pins everything with hashes for Linux x86_64 cp312 | Keep; one HTTP implementation under test. The lock is UNTESTED on Linux |
| L-1 | Serving artwork needs a member-scoped route | Done: `/art/<ref>` (AVR-382) |

## 13. Known gaps

*As of M3.1 (2026-10-12). Since then all four adapters, `/art`, search, title pages and the Concept K shell exist on
draft branches; the open Concept K follow-ups are in [CONCEPT-K-FOLLOW-UPS.md](CONCEPT-K-FOLLOW-UPS.md).*

- One adapter (Jellyfin). Audiobookshelf, Komga, Calibre-Web are not built; the view-model and
  templates already name them.
- No artwork route, no search, no title pages, no operator notice.
- No Dockerfile, compose example or hostname (deferred on purpose; the README describes them).
  When added: the connector's `python:3.12-slim` digest, `USER` non-root, read-only filesystem,
  no published port, the Authentik private network only, and the command
  `python -m avrana_home.app.serve` with `HOME_HOST=0.0.0.0`.
- Responses to malformed requests are produced by uvicorn (item I-9).
- Synchronous logging to stderr can stall requests if the log consumer stalls (as with any
  stderr logger); under Docker's json-file driver this is not a concern.
- `contract.py` replaces an injected cache that is empty (`cache or MemberCache(...)`, since the cache defines `__len__`); `create_app` assigns `adapter.cache` after construction as a workaround. Reported to the contract owner.
