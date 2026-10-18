# Avrana home web application

Status: **proposed, not built into an image, not deployed, 2026-10-12.** Slice M3.1 of
[Avrana Media 2.0](MEDIA-2.0.md) (Linear AVR-374, with the application half of AVR-375 and the
degradation half of AVR-385). The code is [`services/avrana-home/`](../../services/avrana-home/);
the adapter layer it sits on is described in [`ADAPTER-CONTRACT.md`](ADAPTER-CONTRACT.md).
Nothing here reads real member data, adds a container, edits the deployed portal, Authentik or
cloudflared, or creates a hostname. Gates G1 and G2 have not passed in production.

Approving this document approves no production step. Every cut-over step below is described, not
performed, and needs the owner's approval for that step with rollback material prepared first.

## 1. What it is

One small Python application: FastAPI and Jinja, server-rendered, no JavaScript, no front-end
build, no broker, no database server. It does two things:

1. **Serves today's portal pages and redirects unchanged** (`/`, `/watch`, `/listen`, `/comics`,
   `/books`, `/kindle`, `/requests`, `/requestabook`, `/requestacomic`, `/contribute`, `/ops`,
   the choosers `/read` and `/request`, `/help`, `/help/<slug>`, `/account`, the `/watch`
   interstitial, `/healthz`). A parity test compares it with `services/avrana-portal/portal.py`
   for every fixture identity (section 4).
2. **Behind a flag (`HOME_SECTIONS`, default off)** renders the member's *Continue* and *Recently
   added* sections from the adapter layer as deliberately plain markup above the unchanged
   navigation, and exposes the same data as JSON at `/home.json` (section 5).

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
| I-8 | Every response | Cache-Control, Referrer-Policy, X-Content-Type-Options (`nosniff`, asserted on every response) | Those three **plus** `Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` (no script source) | **Keep.** Inline `<style>` is how the portal is built today; dropping it needs a stylesheet route and the design team's agreement. |
| I-9 | Protocol-level problems (malformed request line, unknown HTTP version, oversized headers) | Python `http.server` replies (400/505) with the three headers | uvicorn/h11 replies **before the application runs**: 400/431 with no application headers; `HTTP/9.9` is accepted | **Accept.** These replies carry no application data. Documented, tested to contain no page. |
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
| Audiobookshelf, Komga, Calibre-Web | Not built yet (one adapter exists); the same pattern applies | |
| A request service | Not applicable to this slice (links only, redirects are static) | |
| Authentik or cloudflared | Nothing (outside the app) | |
| The media array (unmounted) | Same as Jellyfin down; the operator notice is a later slice | |
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
                            "artwork": {"ref","alt"}|null, "handoff_url"} ] } ] }
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

`artwork.ref` is opaque. `GET /art/<ref>` (for example `/art/komga/book/<id>`) serves it, member-scoped: `app/artwork.py` is the one module that calls `fetch_artwork`, with the verified principal and a ref of the exact shape `service/word/id` (`[A-Za-z0-9_-]` only). Unknown service, bad ref, missing group, an item the member may not see, an upstream failure and a refused content type are all the same standard 404. Responses carry `Cache-Control: private, no-store`, `nosniff`, and only `image/jpeg|png|webp` of at most 5 MiB (never SVG or HTML). Section items render `<img src="/art/..." alt=<title> width="80" height="120" loading="lazy">` only when a valid ref exists.

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
| `AUDIOBOOKSHELF_TOKEN` / `AUDIOBOOKSHELF_TOKEN_FILE` | none | Real mode only, with the URL, exactly one of the two; a token in mock mode is an error. Never in a repr, log line or error message. |
| `KOMGA_BASE_URL` / `KOMGA_TOKEN` (`_FILE`) / `KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS` | unset (adapter not built) | Optional. Mock mode: loopback URL, the token is fixed and fake, the flag is ignored. Real mode (owner decision 2026-10-15, ADAPTER-CONTRACT 12.2): needs `HOME_GATES_VERIFIED=yes`, the URL, a REGULAR (non-admin) account's key and `KOMGA_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS=yes`; otherwise a startup error. |
| `CALIBRE_WEB_BASE_URL` / `CALIBRE_WEB_CREDENTIAL` (`_FILE`) / `CALIBRE_WEB_OWNER_CONFIRMS_NO_MEMBER_RESTRICTIONS` | unset / unset / `off` | Optional. Mock mode: loopback URL, fixed fake credential. Real mode is refused unless the owner setting is `yes` (default off; Calibre-Web is a shared view, ADAPTER-CONTRACT 13.2), and then also needs `HOME_GATES_VERIFIED=yes`, the URL and a `user:password` credential together. The constructor's `owner_confirms_no_member_restrictions` is `True` only in mock mode or from that setting. |
| `HOME_TIMEOUT` | `2.0` | Per-call seconds, 0.1 to 10. |
| `HOME_SECTION_LIMIT` | `12` | Items per section, 1 to 50. |
| `HOME_HEALTH_DETAIL` | `loopback` | `loopback` or `off`. |
| `HOME_CATALOGUE_PATH` | the portal's `portal.py` | Must be a file; the tables are loaded from it. |
| `HOME_HOST`, `HOME_PORT` | `127.0.0.1`, `8096` | Bind address for `serve.py`. A container must set `HOME_HOST=0.0.0.0` deliberately. |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR. |

Real upstream adapters stay disabled unless `HOME_SECTIONS=on` **and** `HOME_UPSTREAM_MODE=real`
**and** `HOME_GATES_VERIFIED=yes` **and** an explicit URL and key are present. With the flag off no
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
image from Git, restore its environment/secret file from 1Password, start. There is no volume to
back up; its env file joins the completeness gate when it exists.

**Cut-over (per MEDIA-2.0 section 5).** The new app runs as its own container. Launch points the
`avrana-portal` proxy provider's internal host at it; rollback points it back; the previous portal
container stays deployed and unused for at least two weeks. Each of these is an owner-approved
change with a rehearsed rollback, and none is prepared by this change. The beta hostname (AVR-373,
decision D-5) must exist first, gated on `authentik Admins` plus named testers.

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
