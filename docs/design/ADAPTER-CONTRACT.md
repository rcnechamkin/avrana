# Avrana home adapter contract

Status: **proposed, not deployed, 2026-10-11.** Part of [Avrana Media 2.0](MEDIA-2.0.md), slices M3.1
and M3.2 (Linear AVR-375, AVR-376, AVR-377, AVR-385). The reference implementation is
[`services/avrana-home/`](../../services/avrana-home/): standard library only, import-only, proven
against **synthetic fixtures** with a fake transport. Nothing here has run against a real Jellyfin,
Audiobookshelf, Komga or Calibre-Web.

**Prerequisite status.** Gates G1 (network isolation of the identity headers) and G2 (authorization
and isolation suites in production) have not passed. Until both have, no component may read real
member data. This contract and its tests exist so that, when the gates pass, the adapters already
have a proven shape. Approving this document approves no production step.

## 1. Identity: the member principal

`MemberPrincipal(username, groups, email?, name?)` is a frozen value built by exactly one function,
`principal_from_headers`, from the Authentik outpost headers `X-authentik-username` and
`X-authentik-groups` (`email` and `name` are display-only and never decide anything).

It **fails closed**: the function raises `PrincipalError` (and `principal_or_none` returns `None`)
for a missing, empty, duplicated, malformed or oversized required header. There is no default,
guest or anonymous principal. Input is a multi-value mapping or a list of `(name, value)` pairs so
duplicates (including case variants of the header name) are visible.

| Failure | Rule |
|---|---|
| missing | header absent |
| empty | username `""`; groups empty or only separators |
| duplicate | the header appears twice, in any case, or with a list value of length over 1 |
| malformed | non-string; control, format or unassigned characters; leading or trailing whitespace in the username; `|`, `,` or newline in the username; username not in Unicode NFC |
| oversized | username over 150 characters; groups header over 4096 characters, over 64 groups, or a group over 128 characters |

Groups are parsed like `services/avrana-portal/portal.py::parse_groups` (split on `|` and `,`,
strip, drop empties) and compared **exactly and case-sensitively**; there is no prefix matching.

Rules for the rest of the application:

- Every adapter method takes a `MemberPrincipal`. A `str` raises `TypeError`.
- No username is accepted from a query string, body, cookie or model output, ever. The principal
  cannot be constructed directly (`TypeError`), which makes the one header parser the only source.
- The trust in these headers exists only because of G1. A shared-secret header from the outpost
  (decision D-3) is the planned second layer and is out of scope here.

## 2. The adapter, in the order things happen

Each public method runs these steps, in this order, in the shared base class
(`contract.MediaAdapter`). Subclasses implement only the hooks.

1. **Principal check.** Not a `MemberPrincipal`: `TypeError`.
2. **Permission.** The member must hold the adapter's Authentik group. Otherwise the result is
   `NOT_PERMITTED` with **zero upstream calls and no cache access**.
3. **Cache** (member-partitioned, section 5). A hit returns without any upstream call.
4. **Circuit.** If the service is cooling off: `UNAVAILABLE`, zero upstream calls.
5. **Mapping** (`resolve_user`, section 3). Unmapped or ambiguous: `NOT_LINKED`.
6. **Hook.** The only place that talks to the upstream, through the guarded transport.

| Service | Required group |
|---|---|
| Jellyfin | `avrana-videos` |
| Audiobookshelf | `avrana-audiobooks` |
| Komga | `avrana-comics` |
| Calibre-Web | `avrana-books` |

### Public surface

| Method | Returns | Notes |
|---|---|---|
| `resolve_user(principal)` | `UpstreamUser` or `None` | `None` for not permitted, unmapped, ambiguous or unavailable. Never a fallback account. |
| `continue_items(principal, limit)` | `SectionResult` | In-progress items for this member only (`section: "continue"`). |
| `recent_items(principal, limit)` | `SectionResult` | Recently added items visible to this member (`"recent"`). |
| `item(principal, item_id)` | `SectionResult` | Metadata for one id the member can see (`"item"`); an invalid id is `EMPTY`, never interpolated. |
| `search(principal, query, limit)` | `SectionResult` | Signature defined; raises `NotImplementedError` for now. |
| `fetch_artwork(principal, ref)` | `ArtworkResult` | Server-side image fetch for an opaque ref, after a member-scoped visibility check. |
| `health()` | `AdapterHealth` | Circuit state only; no member data; no upstream call. |

`limit` is clamped to 1 to 50 (default 12).

## 3. Upstream user mapping

`resolve_user(principal) -> UpstreamUser | None`. The mapping is explicit and must be unambiguous.

- Match the Authentik username to the upstream account name **exactly** (case-sensitive, no
  normalisation). This follows how accounts are made in this repository: Jellyfin and Komga accounts
  are created at enrollment from the same username (credential replication, see
  `docs/services/jellyfin.md` and `docs/services/sso-architecture.md`), and a casing difference is
  the documented cause of duplicate accounts.
- **Loose matches never link.** If no account matches exactly but one matches after Unicode NFKC
  normalisation, case folding or trimming, the result is `NOT_LINKED` (reason `case_or_unicode_mismatch`).
  The operator reconciles the names; the adapter does not guess.
- **Ambiguity is refused.** Two exact matches, or one exact match that also collides with another
  account after normalisation, is `NOT_LINKED` (reason `ambiguous`). The adapter never picks one.
- A disabled upstream account is `NOT_LINKED` (reason `disabled`).
- Mapping outcomes are cached per member (found 300 s, absent or ambiguous 60 s).
- Only the opaque upstream id is retained. The fetched user list is not stored.

## 4. Result types and states

`SectionState`: `OK`, `EMPTY`, `UNAVAILABLE`, `NOT_LINKED`, `NOT_PERMITTED`.

| State | Meaning | How the UI renders it |
|---|---|---|
| `OK` | Items present | The row |
| `EMPTY` | Reachable and mapped, nothing to show | A friendly empty message ("Nothing in progress") |
| `UNAVAILABLE` | Down, slow (over about 2 s), cooling off, or the response was malformed or inconsistent | The documented "unavailable right now" message for that service only |
| `NOT_LINKED` | No unambiguous upstream account for this member | A neutral "not set up yet, ask for help" message; never an error tone |
| `NOT_PERMITTED` | The member lacks the group | **Absence.** No section, no hint the service exists. `HomeSections.member_view()` omits these entirely. |

`SectionResult.reason` is a fixed diagnostic code for operators and tests (`unmapped`, `ambiguous`,
`disabled`, `cooling_off`, `UpstreamTimeout`, `UpstreamMisbehaved`, ...). It is **not** serialised in
`to_dict()` and must never be displayed.

### JSON shapes (what the UI team codes against)

`SectionResult.to_dict()`:

```json
{"service": "jellyfin", "section": "continue", "state": "ok", "items": [ ...MediaItem... ]}
```

`MediaItem.to_dict()`; `subtitle`, `series`, `progress` and `artwork` may be `null`:

| Field | Type | Notes |
|---|---|---|
| `id` | string | `"<service>:<upstream id>"`, stable across calls |
| `service` | string | `jellyfin`, `audiobookshelf`, `komga`, `calibre-web` |
| `kind` | string | `movie`, `episode`, `series`, `audiobook`, `comic`, `ebook` |
| `title` | string | Always present, plain text, at most 200 characters, never empty (`"Untitled"` if the upstream gave none) |
| `subtitle` | string or null | For example `"S1 E3: Synthetic Pilot"` |
| `series` | string or null | |
| `progress` | object or null | `fraction` (0 to 1), `percent` (integer), `position_seconds`, `duration_seconds` (either may be null). Only for in-progress items. |
| `artwork` | object or null | `ref` (opaque) and `alt` (text alternative) |
| `handoff_url` | string | `https://` URL on a fixed Avrana hostname |

**Accessibility-relevant fields.** `artwork.alt` is always supplied when artwork exists (for example
`"Poster for Synthetic Film One"`); when `artwork` is `null` the UI shows a placeholder with no
alt text of its own because the title is adjacent. `progress.percent` and the seconds let the UI
write a text equivalent ("42 percent watched, 54 minutes in"); colour or bar width alone must not
carry the meaning. `kind` lets the UI label the type in words. Titles are text, never HTML; the
template must escape them.

**Hand-off URLs** are built only from a fixed table of hostnames (`watch.avrana.net`,
`listen.avrana.net`, `read.avrana.net`, `books.avrana.net`) plus an upstream id that must fully
match a strict per-service pattern (Jellyfin: 32 lowercase hex characters). An invalid id drops the
item; it is never interpolated. An upstream-supplied URL is never used, so there is no open redirect.
The path templates are **unverified against the live apps**.

**Artwork** is an opaque `ref` (`"jellyfin/primary/<id>"`). The home fetches it server-side via
`fetch_artwork`, which first confirms the item is visible to the mapped member, then fetches the
image through the allow-listed route, checks the content type (PNG, JPEG, WebP) and a 5 MiB bound,
and may cache the bytes **per member only**. An upstream image URL, which could carry an API key,
is never exposed.

### Synthetic examples, one per state

All titles are invented.

```json
{"service": "jellyfin", "section": "continue", "state": "ok", "items": [
  {"id": "jellyfin:00000000000000000000000000000a01", "service": "jellyfin", "kind": "movie",
   "title": "Synthetic Film One", "subtitle": null, "series": null,
   "progress": {"fraction": 0.42, "percent": 42, "position_seconds": 3024, "duration_seconds": 7200},
   "artwork": {"ref": "jellyfin/primary/00000000000000000000000000000a01",
               "alt": "Poster for Synthetic Film One"},
   "handoff_url": "https://watch.avrana.net/web/#/details?id=00000000000000000000000000000a01"}]}
```

```json
{"service": "jellyfin", "section": "continue", "state": "empty", "items": []}
{"service": "jellyfin", "section": "recent", "state": "unavailable", "items": []}
{"service": "jellyfin", "section": "continue", "state": "not_linked", "items": []}
```

`not_permitted` is never sent to the UI: the entry is omitted, so a member without `avrana-videos`
receives a payload with no `jellyfin` section at all.

**UI-owned states** (not produced by the adapters): *loading* is the client or shell showing a
placeholder while a section is pending (sections are independent and may arrive separately); *whole-
payload error* is the shell failing before any adapter ran (for example no valid principal), which is
a 404 or the sign-in flow, never a partial page. These are listed so the UI team has one table.

## 5. Cache rules

In-memory, disposable, bounded (2048 entries). Deleting it (restart) costs speed only.

| Data | Shared across members? | Key | TTL |
|---|---|---|---|
| Upstream mapping | No | member, service | 300 s found; 60 s absent or ambiguous |
| Continue items | No | member, service, section, limit | 30 s |
| Recently added | **No**, because library visibility depends on the member | member, service, section, limit | 120 s |
| Item metadata | No | member, service, item id | 120 s |
| Artwork bytes | No (visibility is checked per member first) | member, service, ref | 600 s |
| Failures, `UNAVAILABLE`, `NOT_LINKED` section results | Never cached (only the mapping outcome is) | | |

The API makes misuse hard: member data goes through `MemberCache.for_member(principal)`, which
needs a real principal and returns a view that cannot name another member. The key is the exact
username, so case, whitespace and Unicode variants are different partitions. `SharedCache` is a
separate class for permission-independent values and is not used for library, progress or artwork
data. The permission check runs **before** any cache read, so removing a group takes effect
immediately even with a warm cache.

## 6. Failure handling

- Per-call timeout about 2 s (`CallBudget` bounds a whole section across several requests).
- **No retries** in the request path.
- A failure opens a per-service **cool-off circuit for 60 s**: no upstream traffic, `UNAVAILABLE`.
  After the cool-off the next call is a trial; success closes the circuit.
- `gather()` runs sections concurrently with a hard 3 s wall-clock cap as a backstop. A failing,
  slow or hung adapter yields `UNAVAILABLE` for its own section only.
- Logging: `adapter_failure service=<name> error=<ExceptionClass>`. Never member identity, titles,
  URLs, exception messages or credentials. Reprs of principals, users and transports are redacted.
- `health_summary()` is the data for a future `/healthz`: `{"home": "ok", "libraries": "ok|degraded",
  "adapters": [{service, state, last_error_class, retry_in_seconds}]}`. It reports what the request
  path last observed (`unknown` before the first call) and makes no upstream call of its own.
- Error classes: timeout, unreachable, HTTP error, auth error (401/403), not found (benign for one
  item), malformed body, oversized body, and `UpstreamMisbehaved` (the response contradicts the
  request scope, section 7).

## 7. Isolation requirements for every adapter

1. Every upstream request is scoped to the mapped upstream user, enforced in code at one choke point,
   not by convention.
2. Only an allow-list of read-only routes may be called, by exact method and path template. Any other
   method or path raises `ForbiddenRequest` **before** the transport is called.
3. Upstream ids are validated before use and never interpolated unvalidated.
4. A response that contradicts the request scope (for example an item whose user data names another
   user, or more items than requested) is discarded whole: `UNAVAILABLE`, circuit opens.
5. The credential lives only inside the transport. It is in no result, repr or log line.
6. The service credential is never used to produce an "everyone" or admin view as a fallback.

**Residual risk (stated plainly).** A scope violation that carries no identity hint in the response
cannot be detected from the response alone. Protection then rests on request scoping and on a
read-only contract recording against the real server (owner-approved later), which should check that
the scoped parameter is honoured under API-key authentication.

## 8. Minimum credential per upstream (public documentation; all "to verify")

The requirement is the narrowest credential the upstream's public API allows, stored like every
other secret (`docs/SECRETS.md`), never reaching the browser.

| Upstream | Narrowest credential per public docs | Consequence |
|---|---|---|
| Jellyfin | An API key (Dashboard, API Keys). Jellyfin keys have **no scopes**; a key is authorised as an administrator-equivalent. *To verify on 10.11.11.* | The read-only property comes from the adapter's GET allow-list and user-id scoping, not from the key. The key must be dedicated (named for the home), only on the private path, and rotated on suspicion. |
| Audiobookshelf | A per-user API token inherits that user's rights. Another member's progress needs an admin-capable token. *To verify on 2.36.* | Admin-scope risk; see the assessment. |
| Komga | Per-user API key or HTTP Basic acting as that user; no impersonation. This repository records that `X-API-Key` was rejected in the deployed version, so admin Basic is what exists today. *To verify.* | Per-member progress is not readable with a non-admin service account; see the assessment. |
| Calibre-Web | HTTP Basic against OPDS as a normal (non-admin) local user. *To verify.* | Catalogue only; no per-member state. |

Details and the resulting risk per service are in [`ADAPTER-ASSESSMENT.md`](ADAPTER-ASSESSMENT.md).

## 9. Fixtures and API version drift

Fixtures are **hand-written and synthetic**, shaped like the upstream's public API schema; they are
not recordings. Each fixture file carries `_synthetic` and `_schema` notes. They follow the Jellyfin
10.10/10.11 public OpenAPI shape as remembered from its documentation (`BaseItemDto`, `UserData`,
`GET /Users`, `GET /UserItems/Resume`, `GET /Items/Latest`, `GET /Items`, image routes). The
deployed version is 10.11.11 and nothing was checked against it.

Drift handling: unknown fields are ignored; a missing or wrongly typed required field drops that
item (never raises into the page); a non-JSON or wrongly shaped top level is `UpstreamMalformed`
(`UNAVAILABLE`). Re-recording against a real server with a read-only step, before any upstream
upgrade, remains the Media 2.0 plan (section 7 of `MEDIA-2.0.md`) and is an owner-approved action.
