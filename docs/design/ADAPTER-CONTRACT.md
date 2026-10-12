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

- Every adapter method takes a `MemberPrincipal`. A `str`, a look-alike object or a subclass raises
  `TypeError` (consumers check `is_minted_principal`: exact type plus the parser's seal).
- No username is accepted from a query string, body, cookie or model output, ever.
- **What the construction guarantee is, and is not.** There is no supported construction path other
  than the header parser, and accidental copies with changed fields are rejected: the class is not a
  dataclass (`dataclasses.replace` fails), cannot be called, subclassed, copied into another identity
  or pickled, and is immutable. Python cannot stop code already running in the process from using
  `object.__new__` and `object.__setattr__`; that is out of scope, and such code could equally edit
  the parser. The guarantee is against mistakes and misuse, not against hostile in-process code.
- Non-mapping input to the parser (`None`, a string, a generator, malformed pairs) is no principal.
  Usernames and group names may not contain Unicode line or paragraph separators, non-breaking or
  other non-ASCII spaces (an ordinary space is allowed).
- The trust in these headers exists only because of G1. A shared-secret header from the outpost
  (decision D-3) is the planned second layer and is out of scope here.

## 2. The adapter, in the order things happen

Each public method runs these steps, in this order, in the shared base class
(`contract.MediaAdapter`). Subclasses implement only the hooks.

1. **Principal check.** Not a `MemberPrincipal`: `TypeError`.
2. **Permission.** The member must hold the adapter's Authentik group. Otherwise the result is
   `NOT_PERMITTED` with **zero upstream calls and no cache access**.
3. **Cache** (member-partitioned, section 5). A hit returns without any upstream call, even while
   the circuit is open (cached data is bounded by short TTLs).
4. **In-flight cap, then circuit.** If the adapter already has its maximum number of upstream calls
   running (default 4, for example because some are hung): `UNAVAILABLE` (`busy`). If the shared
   circuit is cooling off, or its single half-open trial is taken: `UNAVAILABLE` (`cooling_off`).
   Both start no upstream traffic.
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
  normalisation). **This rule is Jellyfin's and Calibre-Web's only.** Jellyfin accounts are created
  at enrollment with "the username + password the person typed at signup"
  (`docs/services/jellyfin.md`, "Auth: credential replication"), and a casing difference is the
  documented cause of duplicate accounts (`docs/services/sso-architecture.md`, "LDAP was NOT
  enabled"). Calibre-Web signs members in with their Authentik `cn` over LDAP
  (`docs/services/calibre-web-automated.md`). **Komga and Audiobookshelf are keyed by e-mail, not
  username:** Komga accounts are created "with the same email and password"
  (`docs/services/komga.md`; the `avrana-komga-create` policy in
  `services/authentik/blueprints/avrana-enrollment.yaml` looks accounts up by e-mail), and
  Audiobookshelf matches existing users by e-mail (`authOpenIDMatchExistingBy: email`,
  `docs/services/sso-architecture.md`). Those two need a different mapping rule, discussed in
  [`ADAPTER-ASSESSMENT.md`](ADAPTER-ASSESSMENT.md).
- **Loose matches never link.** If no account matches exactly but one matches after Unicode NFKC
  normalisation, case folding or trimming, the result is `NOT_LINKED` (reason `case_or_unicode_mismatch`).
  The operator reconciles the names; the adapter does not guess.
- **Ambiguity is refused.** Two exact matches, or one exact match that also collides with another
  account after normalisation, is `NOT_LINKED` (reason `ambiguous`). The adapter never picks one.
- A disabled upstream account is `NOT_LINKED` (reason `disabled`).
- Mapping outcomes are cached per member (found 300 s, absent or ambiguous 60 s). A 404 on a later
  member-scoped call drops that member's cached mapping so it is resolved again.
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
| `progress` | object or null | `fraction` (0 to 1), `percent` (integer), `position_seconds`, `duration_seconds`; any of the four may be null when the upstream did not say (then show the position or no bar, never a guess). Only for in-progress items. |
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

In-memory, disposable, bounded. Deleting it (restart) costs speed only. Bounds: 2048 entries and
32 MiB in total; per member 128 entries and 8 MiB. A member over quota evicts only their own
oldest entries; under global pressure the member holding the most bytes loses entries first; an
entry larger than the per-member byte quota is not stored. One member therefore cannot push the
others out.

| Data | Shared across members? | Key | TTL |
|---|---|---|---|
| Upstream mapping | No | member, service | 300 s found; 60 s absent or ambiguous |
| Continue items | No | member, service, section, limit | 30 s |
| Recently added | **No**, because library visibility depends on the member | member, service, section, limit | 120 s |
| Item metadata | No | member, service, item id | 120 s |
| Artwork bytes | No (visibility is checked per member first) | member, service, ref | 300 s |
| Failures, `UNAVAILABLE`, `NOT_LINKED` section results, and results from a call that finished after the circuit moved on | Never cached | | |

**Artwork TTL, and why 300 s.** If an item is hidden from a member in Jellyfin, or the member's
library access changes, cached artwork for that item can still be served until its TTL expires.
Five minutes is accepted because the image is a poster the member could legitimately see within
the previous five minutes, and because a loss of the Authentik group takes effect immediately
(the group check precedes the cache). Shorter TTLs are cheap to set (`ARTWORK_TTL`) if the owner
wants a tighter window.

The API makes misuse hard: member data goes through `MemberCache.for_member(principal)`, which
needs a parser-minted principal and returns a view that cannot name another member. The key is the
exact username, so case, whitespace and Unicode variants are different partitions. `SharedCache` is
a separate store for permission-independent values and is not used for library, progress or artwork
data. The permission check runs **before** any cache read, so removing a group takes effect
immediately even with a warm cache.

**Proposed deviation from `MEDIA-2.0.md` section 3, for owner confirmation.** The approved
architecture describes "a small SQLite file in the container's own volume". This reference
implementation caches in memory only, because everything it caches is per-member and short-lived
(30 to 300 s), so a file would persist member data to disk for little gain and a restart losing it
costs one slow page. This is a proposal, not a decision. If SQLite is wanted, the one place where
it earns its keep is **resized artwork bytes**, keyed per member exactly as above (or shared only
after the visibility check is proven not to change per member), stored in the container's own
volume and deleted freely. The approved design is not changed by this document.

## 6. Failure handling

- Per-call timeout about 2 s (`CallBudget` bounds a whole section across several requests).
- **No retries** in the request path.
- **The circuit is shared by every member of an adapter.** Policy, exactly:
  1. Counts toward it (service-wide evidence): timeouts, connection errors (including
     `http.client` errors), HTTP 5xx, 429, unexpected 3xx, 401 or 403 (the service credential
     itself is refused), malformed or oversized payloads, total schema drift (below), and
     `UpstreamMisbehaved` (a response that contradicts the request scope).
  2. Does not count (specific to one member's or one item's request): 404 and every other 4xx.
     A 404 on a member-scoped call returns `NOT_LINKED` (`upstream_user_not_found`) and drops that
     member's cached mapping. A 404 on the user-list call used for mapping is route drift and does
     count. Other 4xx give `UNAVAILABLE` for that request only.
  3. Threshold: **3 consecutive** counted failures open it (any success resets the run), so one
     unlucky or odd request cannot shut a service for everyone. It stays open for 60 s with no
     upstream traffic.
  4. After the cool-off it is half-open: exactly **one** trial call is admitted at a time (no
     thundering herd). Success closes it; one failure re-opens it for a full cool-off.
  5. Each opening bumps an epoch. A call admitted before that and finishing after (a hung call)
     is ignored: it cannot close the circuit and cannot populate a cache.
- **Hung adapters.** `gather()` runs sections on one shared, fixed-size pool with a hard 3 s
  wall-clock cap as a backstop; an adapter that exceeds it has its circuit force-opened and its
  section reports `UNAVAILABLE` (`hard_cap`). Python cannot kill a hung thread, so concurrency is
  bounded instead: each adapter allows 4 in-flight upstream calls, and further requests get
  `UNAVAILABLE` (`busy`) immediately, starting no work. Queued work that never started is cancelled.
- **Boundary.** Anything an upstream or transport can provoke (`RecursionError` from nested JSON,
  numeric overflow, `http.client` errors, wrong types) becomes an `UpstreamError`; a public method
  returns a state and never raises for upstream-controlled input. Only programming errors propagate.
- Logging: `adapter_failure service=<name> error=<ExceptionClass>`. Never member identity, titles,
  URLs, exception messages or credentials. Reprs of principals, users and transports are redacted.
- `health_summary()` is the data for a future `/healthz`: `{"home": "ok", "libraries": "ok|degraded",
  "adapters": [{service, state, last_error_class, retry_in_seconds}]}`. It reports what the request
  path last observed (`unknown` before the first call) and makes no upstream call of its own.
- Error classes: timeout, unreachable, HTTP error, auth error (401/403), not found, malformed body,
  oversized body, and `UpstreamMisbehaved` (the response contradicts the request scope, section 7).

## 7. Isolation requirements for every adapter

1. Every upstream request is scoped to the mapped upstream user, enforced in code at one choke point,
   not by convention.
2. Only an allow-list of read-only routes may be called, by exact method and path template. Any other
   method or path raises `ForbiddenRequest` **before** the transport is called.
3. Upstream ids are validated before use and never interpolated unvalidated.
4. A response that contradicts the request scope (for example an item whose user data names another
   user or another item, or more items than requested) is discarded whole: `UNAVAILABLE`, and it
   counts toward the circuit (section 6).
5. The credential lives only inside the transport. It is in no result, repr or log line. The
   guard also refuses to bind anything that is not a 32-hex user id.
6. The service credential is never used to produce an "everyone" or admin view as a fallback.

The image route cannot carry a `userId`, so the guard cannot bind it to the member. Its member
scoping rests on the adapter first running a `userId`-scoped lookup of the same item
(`_visible_item`) and fetching the image only if that returns the requested id.

**Residual risk (stated plainly).** An upstream that ignores `userId` and returns another member's
items with no identity marker in the response is **undetectable by the adapter**: the tripwires
(user id or item id named in the user data, over-limit listings) fire only when the upstream
supplies evidence. A recorded, read-only contract check against the real Jellyfin version, showing
that `userId` is honoured under API-key authentication and that the response differs per user, is
therefore **required before any real member data is read**. That check is an owner-approved step.
**Not implemented yet, listed as follow-up:** a per-member rate limit on adapter calls.

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
(`UNAVAILABLE`). **Total drift:** if the upstream returned raw items and every one was unparsable
(not an object, invalid id, missing type, non-numeric position), the section is `UNAVAILABLE`
(`UpstreamMalformed`, counted toward the circuit) and is never cached as an empty success. Items
dropped for a legitimate reason (another media type, not in progress) do not count as drift, and
partial drops stay as before. Re-recording against a real server with a read-only step, before any upstream
upgrade, remains the Media 2.0 plan (section 7 of `MEDIA-2.0.md`) and is an owner-approved action.
