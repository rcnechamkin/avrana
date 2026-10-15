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

**UNVERIFIED (identity inputs).** The 150-character username limit is this layer's own bound taken
from Authentik's documented user model as remembered, not checked against the deployed Authentik.
The `|` group separator, and the `,` also accepted, follow `services/avrana-portal/portal.py::parse_groups`
and the repository's notes about the outpost header; the exact form the deployed outpost sends has
not been observed by this work. Both belong to the recorded read-only check before any real header is
parsed.

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
- Non-mapping input to the parser (`None`, a string, a generator, malformed pairs, a pair whose
  name is not text) is no principal. Usernames and group names may not contain Unicode line or
  paragraph separators, non-breaking or other non-ASCII spaces (an ordinary space is allowed).
- Display-only `name` and `email` are stripped, and dropped (set to `None`) if empty after the strip,
  too long, duplicated, or containing control characters, so consumers never have to clean them.
- Two constructors: `principal_from_headers` (a mapping or a list of text pairs) and
  `principal_from_raw_headers` (a list of `(bytes, bytes)` pairs as an ASGI server provides). The raw
  form decodes strictly: names must be ASCII, and the identity headers must be pure ASCII, so any
  non-ASCII or non-UTF-8 value (including latin-1 mojibake) yields no principal. This is deliberately
  stricter than Authentik allows; relaxing it for non-ASCII usernames is an owner decision.
- **Framework header-mapping behaviour is UNVERIFIED.** The statement that a framework's header
  mapping merges duplicates and decodes as latin-1 is recalled from Starlette's documented behaviour,
  not tested here (no framework is installed in this offline work). It is why section 10 requires the
  raw header list; if a framework turns out to preserve duplicates, the raw form is still the safe one.
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
4. **In-flight caps, then circuit.** If the adapter already has its maximum number of upstream calls
   running (default 8, for example because some are hung): `UNAVAILABLE` (`busy`). If this member
   already holds their share (default 2, below the service cap, so one member cannot take every slot):
   `UNAVAILABLE` (`member_busy`). If the shared circuit is cooling off, or its single half-open trial
   is taken: `UNAVAILABLE` (`cooling_off`). All three start no upstream traffic.
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
- Mapping outcomes are cached per member for **60 s**, found, absent or ambiguous alike (a negative
  result is cached too). This bounds how long a renamed, swapped or deleted upstream account can
  keep serving the old mapping. Jellyfin item responses carry no user name, so there is no stronger
  evidence to check; the residual window is therefore up to 60 s. A 404 on a later route addressed by
  the bound user, with a cached mapping, drops the mapping so it is resolved again (section 6, what a
  404 means).
- **Single-flight.** The sections of one page run concurrently and would both miss the mapping cache
  on a cold page. The mapping lookup is single-flight per (adapter, member): one page is one
  mapping call and, in an outage, one counted failure; the follower sections share the leader's
  answer and are not counted again. A follower waits at most what is left of its own request
  budget (never the hard cap); a flight older than one budget is abandoned and the next caller leads
  afresh; a follower never accepts an answer older than the mapping TTL; every follower gets its own
  new exception instance, never the leader's. A follower also knows its mapping was just confirmed by
  the leader, so it never drops a mapping the leader has just confirmed.
- A `/Users` list that is non-empty but has **no parsable entry** (schema drift) is `UpstreamMalformed`
  (`UNAVAILABLE`, counted, not cached), never "everyone is unlinked". An empty list is legitimately
  unlinked.
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
The path templates are **unverified against the live apps**, and so are the Audiobookshelf
(`li_` plus 6 to 40 lowercase alphanumerics) and Komga (6 to 32 alphanumerics) id patterns in
`contract.py`: they are placeholders written from memory so that a typo cannot become a URL, not
observed ids. Only the Jellyfin pattern (32 lowercase hex) is a documented format.

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

**One mechanism, following the approved design.** `MEDIA-2.0.md` section 3, "Cache", says in full:
"A small SQLite file in the container's own volume, holding catalogue metadata and resized artwork with
short lifetimes. It is disposable: deleting it costs a slower first page, nothing else." The reference
implements one SQLite mechanism, once: `DisposableCache` over stdlib `sqlite3` (`MemberCache` and
`SharedCache` are thin facades; only `MemberCache` has a member API, `SharedCache` has none). There is
no second cache mechanism in the tree.

**Where this implementation is stricter than, or deviates from, the charter text.**

- *Artwork in memory only is a deviation.* The charter names catalogue metadata **and resized artwork**
  as the file's content. This implementation's conservative default keeps artwork out of the file
  (it is visibility-checked per member, so it is member data); artwork reaches a file only if the
  application widens `persist_classes`. That is a deviation from the charter text, flagged for the
  owner (decision below), not something the charter asked for.
- *"Deleted and recreated at every start" is this implementation's stricter reading of "disposable",
  not the charter's wording.* The charter only says deleting it costs nothing; recreating it at
  every start is a choice that keeps the file from ever becoming a store.
- *Per-member progress and the per-member mapping are not in the charter's list at all.* They are
  cached in memory because the home page needs them; whether they may ever touch a file is the open
  owner decision below.

| | Default (tests, local development, and until the owner decides) | Configured file path (the deployment the charter describes) |
|---|---|---|
| Database | `:memory:` | a file in the application's own volume |
| Created | in memory | **deleted and recreated at every start**, mode 0600, created with `O_EXCL` (and `O_NOFOLLOW` where the platform has it), never migrated, never backed up, never a system of record |
| Pragmas | `secure_delete=ON`, `temp_store=MEMORY` | the same plus rollback journal kept in memory (no sidecar or temp files) and `synchronous=OFF`; `application_id` marks the file as ours |
| Schema | `user_version` = 2 | the same |
| Existing file at the path | n/a | replaced **only** if it is a regular file that is empty or carries this cache's `application_id`. Anything else (another program's file, a symlink, a directory) is **refused**: one log line by reason class only (`cache_path_refused`), the file is left untouched, and the cache runs in memory |
| Two caches, one path | n/a | the second is refused with `CachePathInUseError` (raised at construction) |
| Shutdown | nothing to do | `close()` closes the connection and removes the file |
| Errors | no database, encoder or decoder exception reaches a caller: a sqlite error is a **miss** and the cache is rebuilt; an undecodable or type-invalid row is a miss and is deleted; a value that cannot be encoded is simply not stored | the same; an unusable path degrades to memory |

Two databases are attached to one connection under one lock and one quota code path: `main` (the
file, when configured) and `member` (always `:memory:`). Each write declares a data class, and one
policy decides where it may live:

| Data class | Written by | Persisted to a file by default? |
|---|---|---|
| `member_progress` | continue, recent and item sections (all permission dependent) | **No** |
| `member_mapping` | the upstream mapping outcome | **No** |
| `artwork` | image bytes, visibility-checked per member | **No** |
| `catalogue` | permission-independent shared data (`SharedCache` only) | Yes (`persist_classes` default) |

`MemberScope.set` accepts only the three member classes and `SharedCache.set` only `catalogue`, so a
member-keyed entry can never be filed under `catalogue`. The application may widen `persist_classes`;
that is the owner decision below.

**Keys and values.** Every partition key and entry key is an HMAC-SHA256 under a random key
generated at start and never stored (every part is length-prefixed, so no two part lists can give
one input), so neither a file nor a memory dump contains usernames,
service names, item ids or artwork references as key material, and a file left behind is useless
after a restart. **Values are plaintext JSON** (titles, progress, image bytes): that is why member
classes stay out of the file by default. Stored types are a whitelist of immutable domain types.

Bounds (a member over quota evicts only their own oldest entries; under global pressure the member
holding the most bytes loses entries first; an entry larger than the per-member byte quota is not
stored): 2048 entries and 32 MiB in total; per member 128 entries and 8 MiB. **All byte bounds are in
STORED bytes**: the cache measures the encoded payload itself (text column plus any binary column plus
a fixed 200-byte per-row overhead) and ignores any size a caller declares (the old `size` argument
is accepted and ignored). Artwork is stored as a BLOB, not base64. Inside one member, eviction goes by
class (artwork first, then section data, the mapping last) and then oldest first, in one pass.
`purge_member(principal)` (a `MemberCache` method) removes everything cached for one member from both
databases (offboarding). Concurrent use is safe (one connection, one lock). A write that is refused
(non-positive, NaN or infinite TTL; unencodable; over quota) also removes any previous value under
that key.

| Data | Shared across members? | Key | TTL |
|---|---|---|---|
| Upstream mapping | No | member, service | 60 s (found, absent or ambiguous) |
| Continue items | No | member, service, section, **limit** | 30 s |
| Recently added | **No**, because library visibility depends on the member | member, service, section, limit | 120 s |
| Item metadata | No | member, service, item id | 120 s |
| Artwork bytes | No (visibility is checked per member first) | member, service, ref | 300 s |
| Failures, `UNAVAILABLE`, `NOT_LINKED` section results, and results from a call that finished after the circuit moved on | Never cached | | |

**Artwork TTL, and why 300 s.** If an item is hidden from a member in Jellyfin, or the member's
library access changes, cached artwork for that item can still be served until its TTL expires.
Five minutes is accepted because the image is a poster the member could legitimately see within
the previous five minutes, and because a loss of the Authentik group takes effect immediately
(the group check precedes the cache). `ARTWORK_TTL` is the one place to tighten it.

The permission check runs **before** any cache read, so removing a group takes effect immediately
even with a warm cache. A cache hit is served even while the circuit is open.

**Owner decision (open): may per-member watch state be written to a disk file?** Today the answer
is no, by policy default, because it is an unresolved privacy question. Options and consequences:

1. *Keep member classes in memory only (the default).* No member data on disk; a restart empties the
   member cache (one slower first page per member); nothing to back up, exclude or purge.
2. *Persist `member_progress`, `member_mapping` and/or `artwork` in the file.* Titles and progress are
   plaintext in the file for as long as it exists. Survives a restart only if the recreate-at-start
   rule is removed, which makes it a data store that needs thought: it must then be excluded from
   backups and off-host copies (it is not a system of record), purged on offboarding
   (`purge_member`, plus free pages, which `secure_delete` zeroes), covered by the privacy page
   (what is recorded, who can see it), and its file mode and volume ownership reviewed.
3. *Persist only artwork bytes.* The lowest-risk file use: images are already served to the member;
   keys stay hashed per member. Needs the visibility-change window above to be accepted.

Until the owner decides, only option 1 is implemented as the default; the code path for 2 and 3 exists
behind `persist_classes` but is not enabled. This document does not edit `MEDIA-2.0.md` or
`DECISIONS.md`.

## 6. Failure handling

- **One deadline per request.** A request has a 2 s budget shared by the mapping and the work
  (`REQUEST_BUDGET`, or the `timeout` an adapter is built with); each transport call gets what is
  left, so a request that respects its budget can never reach the hard cap in `gather`. The hard cap
  is **derived**: the longest request timeout among the adapters passed to `gather` plus 1 s (3 s with
  the defaults); `derive_hard_cap(adapters)` computes it and an explicit `hard_cap` still overrides.
- **No retries** in the request path.
- **The circuit is shared by every member of an adapter.** Policy, exactly:
  1. Counts toward it (service-wide evidence): timeouts, connection errors (including
     `http.client` errors and any other surprise exception class a transport raises), HTTP 5xx,
     429, unexpected 3xx, **401** (the service credential is refused), **403 on the user list**
     (the credential lacks rights), malformed or oversized payloads, total schema drift (section 9),
     and `UpstreamMisbehaved`. 401/403 semantics are **unverified** against the deployed Jellyfin.
  2. Does not count (about one member's or one item's request): other 4xx; **403 on a member-scoped
     call** (that member gets `UNAVAILABLE`); and the two member-specific kinds of 404 below.
  3. **What a 404 means is declared by the ROUTE** (each allow-listed route names its class; a bare
     404 from a transport is converted by the guard):
     - *user route* (addressed by the bound user: resume, latest, items for Jellyfin) = `UserGone`.
       With a *cached* mapping the account is gone: `NOT_LINKED`, reason `upstream_user_not_found`,
       that member's mapping dropped, not counted. Right after the mapping was freshly confirmed (by
       this call or by the single-flight leader it followed) it is contradictory, so it is drift:
       `UNAVAILABLE` reason `UserGone`, counted, mapping kept.
     - *item route* (the image of one item) = `ItemGone`: an `EMPTY` result (reason `item_not_found`,
       artwork `EMPTY`), never counted, never cached.
     - *fixed route* (the user list) = `RouteMissing`: the route is gone, service-wide drift,
       `UNAVAILABLE`, counted. A 404 nobody classified is treated the same way.
  4. Only calls that actually reached the upstream report to the breaker. A mapping served from the
     cache (found, absent or ambiguous) is neutral: it can neither reset a failure run nor hold a
     failing service open.
  5. Threshold: **3 consecutive** counted failures open it (any success resets the run). Open for
     60 s with no upstream traffic.
  6. After the cool-off it is half-open: exactly **one** trial is admitted at a time; success closes,
     one failure re-opens. The trial holds a 30 s **lease**: if it never reports, one new trial is
     admitted and the lost trial's result is ignored.
  7. Each opening bumps an epoch. A call admitted before that and finishing after (a hung call)
     cannot close the circuit and cannot populate a cache.
- **Programming errors in our own adapter code** (as opposed to anything an upstream or transport
  can provoke) are not swallowed: the method raises, so tests see them; under `gather` that section
  is `UNAVAILABLE`, is logged by class only, and that adapter's circuit is force-opened.
- **Hung adapters.** Python cannot kill a hung thread, so concurrency is bounded instead. `gather()`
  runs sections on one shared 48-thread pool of daemon threads (so a hung call cannot keep a shutting
  down process alive) with a hard wall-clock cap (derived, 3 s with the defaults); an adapter that
  exceeds it has its circuit force-opened and reports `UNAVAILABLE` (`hard_cap`). Each adapter allows
  8 in-flight calls and 2 per member; beyond that, `busy` / `member_busy` immediately. Work that
  never started when the cap hits is cancelled and reported `queued`, and touches no circuit. This
  protection covers sections run through `gather`; a caller that calls adapter methods directly gets
  the in-flight caps, the per-request deadline and the epoch protection, but no hard cap.
- **Boundary.** Anything an upstream or transport can provoke (`RecursionError` from nested JSON,
  numeric overflow, `http.client` errors, wrong types) becomes an `UpstreamError`; a public method
  returns a state and never raises for upstream-controlled input. The same holds for the cache: no
  exception from encoding, decoding or sqlite escapes it (a failure is a miss), and a clock that
  raises cannot leak an in-flight slot.
- Logging: `adapter_failure service=<name> error=<ExceptionClass>`. Never member identity, titles,
  URLs, exception messages or credentials. Reprs of principals, users and transports are redacted.
- **Health vocabulary** (`AdapterHealth.state`, rendered by the app's readiness check):

  | State | Meaning |
  |---|---|
  | `ok` | closed; no failure in the current run |
  | `failing` | closed, but 1 or 2 consecutive counted failures so far (`consecutive_failures`); an early outage |
  | `cooling_off` | open; no upstream traffic for `retry_in_seconds` |
  | `unknown` | never heard from, or a cool-off ended and the trial call has not reported |

  `health_summary()` returns `{"home": "ok", "libraries": "ok|degraded", "adapters": [{service,
  state, last_error_class, retry_in_seconds, consecutive_failures}]}`; `libraries` is `degraded` when
  any adapter is `failing` or `cooling_off`. It makes no upstream call of its own.
- Error classes: timeout, unreachable, HTTP error, auth error, not found, malformed body, oversized
  body, and `UpstreamMisbehaved` (the response contradicts the request scope, section 7).

## 7. Isolation requirements for every adapter

1. Every upstream request is scoped to the mapped upstream user, enforced in code at one choke point,
   not by convention.
2. Only an allow-list of read-only routes may be called, by exact method and path template. Any other
   method or path raises `ForbiddenRequest` **before** the transport is called.
3. Upstream ids are validated before use and never interpolated unvalidated.
4. A response that contradicts the request scope (for example an item whose user data names another
   user or another item, or more items than requested) is discarded whole: `UNAVAILABLE`, and it
   counts toward the circuit (section 6). **`UserData.UserId` may well be absent from real Jellyfin
   responses (unverified); the code checks it only if present**, so do not rely on it.
5. The credential lives only inside the transport. It is in no result, repr or log line. The
   guard also refuses to bind anything that is not a 32-hex user id.
6. The service credential is never used to produce an "everyone" or admin view as a fallback.

**UNVERIFIED Jellyfin behaviours this isolation relies on** (all part of the recorded read-only check):
(a) `GET /Items?userId=..&ids=..` returns an **empty list**, not a 404, for an item the user cannot see
(if it returns 404 instead, `ItemGone`/`UserGone` classification of that route must be revisited);
(b) `userId` is **honoured** when the request is authenticated with an API key;
(c) API keys are administrator-equivalent, with no scopes; (d) the image route honours `maxWidth` and
`quality`.

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

**Jellyfin authorization header form (unverified).** The transport sends the key only as a header,
never in the query string (`api_key=` would end up in URLs and logs). The form used throughout the
tests and expected in configuration is `Authorization: MediaBrowser Token="<key>"`; Jellyfin has
accepted other spellings over time (`X-Emby-Token`, `X-MediaBrowser-Token`, the older
`X-Emby-Authorization`). Which form the **deployed 10.11.11** accepts, and that the same key works for
`GET /Users`, is **unverified** and is part of the recorded read-only contract check (section 7).

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
partial drops stay as before. A non-empty user list in which no entry can be parsed is drift too
(section 3). Re-recording against a real server with a read-only step, before any upstream
upgrade, remains the Media 2.0 plan (section 7 of `MEDIA-2.0.md`) and is an owner-approved action.

## 10. Integration requirements for the application (FastAPI shell)

- **Adapters are synchronous.** Call them from the threadpool (for example `run_in_threadpool`),
  never directly on the event loop; `gather` already blocks until its sections finish or the cap hits.
- **Read identity from the raw header list** (`request.scope["headers"]`, a list of byte pairs) and
  build the principal with `principal_from_raw_headers`, so duplicates stay visible and decoding is
  strict. Do not use a framework header mapping (it merges duplicates and decodes as latin-1).
- **One worker process.** The circuit, the in-flight counters, the single-flight table and the cache
  are per process; several workers would each learn about outages separately and each hold a cache.
- **Artwork responses** must carry `X-Content-Type-Options: nosniff` and the `Content-Type` the
  adapter returned (it has verified the magic number against the claimed PNG, JPEG or WebP type).
  Serve them only on an authenticated route, from `fetch_artwork`.
- **Expect `busy` and `member_busy`.** A page that requests many images at once from one member will
  see `member_busy` beyond the per-member cap; the image route should serialise or retry, not treat it
  as an error page.
- **Never call an adapter without a principal**, and never pass a username from anywhere else.

## 11. Audiobookshelf adapter (AVR-378)

Status: **proposed, not deployed.** `services/avrana-home/avrana_home/adapters/audiobookshelf.py`,
standard library only, proven only against fixtures that are **hand-written, unverified against the
deployed version**; a recorded read-only contract check is a separate owner-approved step before any
real data is read. Every fixture file under `tests/fixtures/audiobookshelf/` carries that sentence in
its `_synthetic` field. The adapter contacts no server in any test (the network guard is on).

**What it offers.** One section, "Continue listening": the member's in-progress audiobooks, read-only.
`recent_items`, `item` and `fetch_artwork` return `EMPTY` (reason `not_offered`) with no upstream call
and nothing cached; ask `gather` for `sections=("continue",)` so the UI does not render an empty
"recent" for this service. Covers are **left out** (a cover route cannot be bound to the member), so
`artwork` is `null` on every item.

### 11.1 How it stays member-scoped with an admin-capable token

Audiobookshelf has no impersonation, so the credential is admin-capable and the isolation is the
adapter's job:

1. **Token inside the transport only.** The adapter takes a `Transport`; the token is in the
   transport's headers (for example `UrllibTransport(base, {"Authorization": "Bearer <token>"})`). It is
   in no repr, result, health report, log line or cache row (tested with a sentinel).
2. **GET only, explicit route list**, enforced by the shared guard before any I/O: the user list
   `/api/users` (mapping only, no query), the member's record `/api/users/{id}` and one item
   `/api/items/{id}` (query key `expanded` only). Nothing else, in particular no "me" route.
3. **The bound user id travels in the PATH** of the member route and the guard compares it with the id
   the adapter bound (a 36-character lowercase UUID, validated before binding). Another member's id, a
   traversal, an encoded slash, an upper-cased id or no bound id is `ForbiddenRequest`.
4. **Identity is checked in the response, and is mandatory.** The record's own `id` must equal the
   bound id, and **every** progress entry must carry a `userId` equal to it. An entry that names another
   user, **or names nobody**, is `UpstreamMisbehaved` and the whole section is discarded (counted toward
   the circuit). An item lookup that answers with a different item id is `UpstreamMisbehaved` too.
5. **Permissions come from the user's own record, before any item is fetched.** Item metadata fetched
   with an admin token is not member-scoped, so an item is shown only if it passes that user's library
   access list (or "can access all libraries"), the explicit-content flag and the tag allow or deny
   list. Every permission field must be present and correctly typed: a malformed permission record makes
   the section `UNAVAILABLE` (`UpstreamMalformed`) and no item is fetched; a malformed item is left out;
   if items were looked up, none could be shown and at least one was unusable, the section is
   `UNAVAILABLE` with the drift reason, never an empty or unfiltered list.
6. **Never the token owner's view.** The only request not carrying the bound id is the user list used
   for mapping; the tests assert that no other request ever goes out.
7. **Tokens in upstream responses are never retained.** The user list and the user record may contain
   per-user tokens; the adapter reads only whitelisted fields (id, name, active flag, permissions,
   progress), stores only the opaque id, and never logs a body.
8. Item 404 = omitted and neutral (`ItemGone`); user-route 404 = `NOT_LINKED` with a cached mapping,
   drift when the mapping was just confirmed; the user-list 404 = route drift (section 6).

### 11.2 Mapping, and the owner decision it needs

The principal's **username** is matched to the Audiobookshelf `username` with the shared
exact-or-refuse helper: exact and case-sensitive; a case, Unicode or whitespace difference is
`NOT_LINKED` (`case_or_unicode_mismatch`); two matches are `NOT_LINKED` (`ambiguous`); an inactive
account is `NOT_LINKED` (`disabled`); no match is `NOT_LINKED` (`unmapped`). **The e-mail is never used
for mapping** (tested: an account whose e-mail equals the member's but whose username differs is not
linked).

**Conflict to decide (owner).** `docs/services/sso-architecture.md` and the Authentik blueprint record
that Audiobookshelf matches existing users **by e-mail** (`authOpenIDMatchExistingBy: email`), so an
account that predates OIDC may carry a username different from the Authentik username.

| Option | Consequence |
|---|---|
| A. Username, exact (implemented, the default) | Safe against an e-mail claimed by another member. An account whose ABS username differs (case, spelling) stays `NOT_LINKED` until the operator reconciles it. Whether OIDC-created accounts carry the Authentik username is **unverified** (assumption 9). |
| B. E-mail | Only as trustworthy as the e-mail: if members can edit their e-mail in Authentik, or it is unverified, one member could be mapped to another's account. Needs the owner to confirm e-mails are immutable and verified. Not implemented. |
| C. Owner-maintained link list (username to ABS user id), outside Git | Strongest, as the assessment recommends; costs a maintained list and a load-time duplicate check. Not implemented; fits behind the same `_resolve_user` hook. |

Until the owner decides, only A exists. Note the assessment recommended excluding the user-list route
and using a link list; this adapter does list users (option A needs it) and mitigates by parsing only
`username`, `id` and `isActive` and retaining only the id.

### 11.3 Fixed behaviour

- Group gate: `avrana-audiobooks`; without it, `NOT_PERMITTED` with no upstream call and no cache read.
- Excluded from the section: finished entries, entries the member hid from continue listening, podcast
  episodes, items marked missing or invalid, non-book media.
- Progress fraction is clamped to 0 to 1 (a non-positive progress is "not started"); positions and
  durations are bounded integers; the list is newest-first by `lastUpdate`; at most 24 item lookups per
  request however long the list is, each under the shared 2 s request budget.
- Cache writes use member classes only (`member_progress`, `member_mapping`); a file-backed cache holds
  zero rows of them by default (tested).
- Hand-off URL: `https://listen.avrana.net/item/<id>` from the fixed host table; the id must match the
  `li_` pattern (assumption 6).

### 11.4 Example, "ok"

All titles are invented.

```json
{"service": "audiobookshelf", "section": "continue", "state": "ok", "items": [
  {"id": "audiobookshelf:li_book000001", "service": "audiobookshelf", "kind": "audiobook",
   "title": "Synthetic Audiobook One", "subtitle": "Synthetic Author", "series": "Synthetic Saga #1",
   "progress": {"fraction": 0.42, "percent": 42, "position_seconds": 15120, "duration_seconds": 36000},
   "artwork": null, "handoff_url": "https://listen.avrana.net/item/li_book000001"}]}
```

The other states are as in section 4: `empty` (nothing in progress), `unavailable` (upstream down, slow,
misbehaving or malformed), `not_linked` (no exact match), `not_permitted` (omitted by the app). Render
the text equivalent of the progress as for Jellyfin.

### 11.5 Residual risks

- An upstream that ignores the user id in the path and returns another member's record **with that
  member's id** is caught; one that returns the right id with wrong data cannot be detected.
- Permission fields are read from the user record: if Audiobookshelf changes their names or meaning,
  the adapter fails closed (`UNAVAILABLE`) rather than showing unfiltered items, at the cost of an
  outage until the field map is updated (it is one class, `_Access`).
- The token is admin-capable: a bug in the allow-list would be a bug with admin reach. The allow-list
  has three entries and no write method.
- No per-member rate limit yet (as for Jellyfin).

### 11.6 Unverified upstream assumptions (every one)

Every fixture file carries `_target_version` (Audiobookshelf 2.36, the version the contract says is deployed, not confirmed) and `_provenance`, which separates the shapes recalled from the public API documentation (not re-checked) from the SYNTHETIC assumptions below, and states that live compatibility is unproven. A test enforces both fields.

1. Authentication is `Authorization: Bearer <token>` with an admin-capable API token or JWT, and that
   token can call the three routes below. (Which form 2.36 accepts is unknown.)
2. `GET /api/users` returns `{"users": [ ... ]}` with `id`, `username`, `isActive` per user.
3. `GET /api/users/{id}` returns one user with `id`, `isActive`, `permissions` (`accessAllLibraries`,
   `accessAllTags`, `accessExplicitContent`, `selectedTagsNotAccessible`), `librariesAccessible`,
   `itemTagsSelected` and `mediaProgress`.
4. `selectedTagsNotAccessible: true` means the selected tags are a **deny** list, `false` an **allow**
   list (the adapter's reading; inverted would show forbidden items, so this is a first contract-check item).
5. Each `mediaProgress` entry carries `userId`, `libraryItemId`, `episodeId`, `progress` (0 to 1),
   `currentTime`, `duration`, `isFinished`, `hideFromContinueListening` and `lastUpdate` (ms). The
   adapter **requires** `userId`: if the real API omits it the section is `UNAVAILABLE` until the
   fixture and adapter are changed on evidence.
6. `GET /api/items/{id}?expanded=1` returns `id`, `libraryId`, `mediaType` (`book` for audiobooks),
   `isMissing`, `isInvalid` and `media` with `metadata` (`title`, `authorName`, `seriesName`,
   `explicit` as a **boolean**) and `tags` (list of text) and `duration`. Library item ids match
   `li_` plus 6 to 40 lowercase alphanumerics; user ids are 36-character lowercase UUIDs; the
   hand-off path `/item/<id>` exists.
7. An unknown user or item gives HTTP 404 (not 200 with an empty body or 400).
8. Missing explicit flag handling: the adapter treats an item with no boolean `explicit` as unusable;
   if the real API omits it for some items, those items will be left out (fail closed).
9. OIDC-created accounts carry the Authentik username as the Audiobookshelf `username`.
10. The user list and user record may contain per-user tokens (the adapter never retains them).

### 11.7 Recorded read-only contract check (checklist, owner-approved, NOT run by this work)

Nothing here is a script and nothing touches the host. When the owner approves a check, a human does
the following with a dedicated, rotatable, read-only-by-habit token and records the results:

1. **Request, read-only (GET), one at a time:** `/api/users` (once); `/api/users/{id}` for **two**
   members with different library or tag access and an explicit-content difference; `/api/items/{id}?expanded=1`
   for one item in each of: an accessible library, an inaccessible library, an explicit item, a tagged item.
2. **Compare:** each assumption in 11.6 against the real response (field names, types, presence of
   `userId` on every progress entry, boolean `explicit`, deny versus allow list meaning, 404 behaviour for
   an unknown id, the id formats); that the user record and the progress entries differ per member;
   that the admin token reads `/api/users/{id}` without needing `?include=`.
3. **Do not request:** any POST, PATCH or DELETE; sessions, e-reader device settings, backups, libraries
   listings, covers, or any "me" route.
4. **Redact before anything is stored or shared:** all tokens and API keys (the user list may contain
   them), e-mail addresses, real usernames (replace by `member-a`, `member-b`), real titles, authors and
   series, library and item ids (replace consistently), IP addresses and device names, timestamps (shift).
5. **Record:** the Audiobookshelf version, the date, which assumptions held and which did not, and
   update the fixtures and the adapter from the evidence in a separate reviewed change.

## 12. Komga adapter (AVR-379)

Status: **proposed, not deployed.** `services/avrana-home/avrana_home/adapters/komga.py`, standard library only,
proven only against fixtures that are **hand-written, unverified against the deployed version**. Every fixture
under `tests/fixtures/komga/` carries `_synthetic`, `_target_version` and `_provenance`; the last separates the
shapes recalled from the public API documentation (not re-checked) from the SYNTHETIC assumptions, and says that
live compatibility is **UNPROVEN**. A test enforces all three.

### 12.1 What it offers

One section, "Recently added" (`recent_items`, and `item` for one book): comics as `Kind.COMIC`, hand-off
`https://read.avrana.net/book/<id>` from the contract builder. `continue_items` returns `EMPTY` (reason
`not_offered`) with no upstream call: in Komga, read progress belongs to the credential's user, not to the member,
and the book responses' `readProgress` is never read. `search` stays as the contract defines it (not implemented).
Read lists and collections are server-global and are not in the route table (no collection or title leak).
Artwork is the book thumbnail, fetched only after the member's restrictions allowed that book; a missing
thumbnail is `EMPTY`.

### 12.2 OWNER DECISIONS this adapter cannot make

1. **Key scope.** Komga has no impersonation. A member's restrictions (library sharing, age restriction, sharing
   label allow and exclude lists) are in that member's user record, which only an **admin** credential can list.
   Implemented here: an admin-capable key behind the GET-only allow-list (five routes), with a fail-closed
   client-side filter built from the member's own record. The read-only property comes from the allow-list, not
   from the key. The alternative is a non-admin shared-view account (`ADAPTER-ASSESSMENT.md`, section 2): it
   cannot read restrictions, so it is correct only while no member is restricted. **Until the owner chooses, no
   key may be wired to this adapter.** If the owner picks the non-admin account, the filter becomes a no-op and
   the "no restricted member" invariant must be checked in the runbook.
2. **Member mapping** (same open decision as section 11.2). A Komga user record has an `email` (the login) and no
   username. The mapping is a seam, `linker`: the default `exact_name_linker` applies the contract's current rule
   (exact, case-sensitive, loose matches never link, two matches ambiguous) to the Komga `email` field, which links
   a member only when the Authentik username equals the Komga login exactly and otherwise gives `NOT_LINKED`
   (fail safe). `link_table_linker` is option C (an owner-maintained link list, outside Git). The e-mail rule (B)
   is **not** implemented, and the principal's e-mail is never consulted.

### 12.3 How it stays member-scoped

Komga routes cannot carry the member in the path or query, so, unlike Jellyfin and Audiobookshelf, the guard cannot
bind a request to a member (it only requires that a mapped member exists before any non-mapping route). Isolation
is the adapter's filter, built to fail closed:

- The member's own record is read from `/api/v2/users` (matched by the linked id; none = `NOT_LINKED`, two =
  `UpstreamMisbehaved`) **before** any book is requested; a malformed restriction field makes the section
  `UNAVAILABLE`, never an unfiltered list.
- A book is shown only if its library (from the book, and equal to its series' library), its series' age rating and
  its series' sharing labels pass. The check is **stricter than Komga's own combination** (every configured rule must
  pass): an allow-only age rule hides unrated content, an exclude label wins over an allow label.
- A book whose series cannot be checked is left out; if nothing could be shown and something was unusable the
  section is `UNAVAILABLE` (drift), never "nothing new". Series lookups are bounded (12 per request), the page is
  bounded (`size` at most 100, a larger answer is `UpstreamMisbehaved`).
- Ids that are also Komga sub-routes (`latest`, `updated`) are never treated as ids.

### 12.4 Unverified upstream assumptions (every one)

1. Authentication by an admin-capable credential in a transport header (Basic or API key: the repository records
   that `X-API-Key` was rejected in the deployed version).
2. `GET /api/v2/users` returns a bare array of users with `id`, `email`, `roles`, `sharedAllLibraries`,
   `sharedLibrariesIds`, `labelsAllow`, `labelsExclude` and `ageRestriction` (`null` or `{age, restriction}` with
   `ALLOW_ONLY` or `EXCLUDE`).
3. Semantics: `ALLOW_ONLY n` shows ratings up to n; `EXCLUDE n` hides ratings from n; labels match case-insensitively.
4. `GET /api/v1/books/latest?page&size` returns `{content: [...]}` newest first; each book has `id`, `seriesId`,
   `seriesTitle`, `libraryId`, `name`, `deleted`, `media.status` and `metadata.{title,number}`.
5. `GET /api/v1/series/{id}` returns `id`, `libraryId` and `metadata.{ageRating (integer or null), sharingLabels}`:
   age and labels are series-level, not book-level.
6. `GET /api/v1/books/{id}/thumbnail` returns a PNG, JPEG or WebP; an unknown id is 404.
7. Ids are 6 to 32 alphanumeric characters (`contract.py` placeholder pattern); the hand-off path `/book/<id>` exists.
8. A 404 for an unknown book or series (not 200 with an empty body).

### 12.5 Recorded read-only contract check (owner-approved, NOT run by this work)

As for section 11.7, with a dedicated token and redaction: GET `/api/v2/users` once; one book and its series for
members with different library, age and label restrictions; compare every assumption above, in particular the
meaning of the age and label rules and whether age and labels are series-level; do not request pages, files,
read lists, collections or any write route. Record the Komga version and update fixtures and adapter in a
separate reviewed change.

### 12.6 Residual risks

- The admin key reaches everything; a bug in the five-route allow-list would be a bug with admin reach.
- The member's restrictions are re-read per section (one extra call to the user list, which returns every
  account; only the member's record is read and nothing else is retained).
- Komga's real combination of allow rules is not verified; the adapter shows less, never more, by design.
- No per-member rate limit yet (as for the other adapters).
