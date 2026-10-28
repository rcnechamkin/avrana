# Member identity and upstream account mapping (AVR-375)

Status: review of the code on `feat/home-2.0` (Home 2.0 sprint, Lane D, 2026-10-16). Offline evidence only.
Nothing here has been run against Authentik, a real member, or a real upstream user list.

## 1. How a member becomes an upstream user

1. **Principal.** `principal.py` builds the one `MemberPrincipal` from the outpost headers
   `X-authentik-username` and `X-authentik-groups`, via the raw ASGI header list (`app/identity.py`). The
   identity headers must be pure ASCII; the username must be non-empty, at most 150 characters, NFC, with no
   surrounding whitespace, no control, format, private-use or non-ASCII space characters, and no `|` or `,`.
   Duplicate, missing or malformed headers give no principal at all (the portal's no-group view).
2. **Group.** Every adapter checks its library group (`contract.REQUIRED_GROUP`) before any cache read or
   upstream call. A member without the group gets `NOT_PERMITTED`, which the pages render as absence.
3. **Mapping** (per service):
   * **Jellyfin, Audiobookshelf**: the upstream user list is read with the service key and
     `_base.match_exactly_one` picks the one account whose name equals the principal's username **exactly**
     (case-sensitive, no normalisation). Owner decision: username match, no link table.
   * **Komga, Calibre-Web**: no mapping. Every member with the group is the fixed shared viewer
     (ADAPTER-CONTRACT 12.2, 13.2); there is no per-member visibility to map.
4. **Binding.** The mapped upstream id is bound into the guarded transport; every user-scoped route must
   carry exactly that id (`_base.check_request`), so a request can never name another user.

### Checking it for real members (owner, one command)

`services/avrana-home/tools/check_member_links.py alice bob` (or `--file members.txt`, `--json`) runs the
mapping hook above with Home's own settings for each username and prints `ok` or a plain-words fix per
library (`unmapped`, `case_or_unicode_mismatch`, `ambiguous`, `disabled`, `unreachable`). It prints no
upstream id and no other account's name, reads only the user lists, and exits 1 when any member needs a fix.
Offline against the dev mocks; against real libraries it is an owner-run read (`tests/test_check_member_links.py`).

## 2. Edge cases and what the code does

| Case | Result | Evidence (offline tests) |
|---|---|---|
| Exact match | linked | `test_jellyfin_adapter.MappingTests.test_exact_name_maps` |
| `cody` vs upstream `Cody` only | `NOT_LINKED`, reason `case_or_unicode_mismatch` (never linked) | `test_h2_security.MatchExactlyOne.test_exact_case_sensitive_only`, `test_jellyfin_adapter...test_loose_match_reason_is_reported_for_operators` |
| Two upstream users that differ only by case (`Cody`, `cody`) | `NOT_LINKED`, reason `ambiguous`, for either name | `test_h2_security.MatchExactlyOne.test_two_upstream_users_differing_only_by_case_are_ambiguous_for_either_name`, `test_jellyfin_adapter...test_case_collision_in_upstream_is_refused` |
| Upstream name that is an NFKC twin (fullwidth `Ｃｏｄｙ`) next to the exact name | `ambiguous` (refused, never picked) | `test_h2_security.MatchExactlyOne.test_a_fullwidth_nfkc_twin_makes_the_exact_name_ambiguous` |
| Cyrillic confusable (`Cоdy`, Cyrillic о) upstream | never linked; does not collide with the Latin account (NFKC does not fold scripts), so the exact Latin account still links | `test_h2_security.MatchExactlyOne.test_a_cyrillic_confusable_never_links_and_never_collides` |
| Confusable or any non-ASCII **principal** | impossible over the header path: no principal | `test_h2_security.MatchExactlyOne.test_a_confusable_principal_cannot_arrive_over_the_header_path` |
| Two upstream accounts with the same exact name | `ambiguous` | `test_jellyfin_adapter...test_duplicate_exact_names_with_different_ids_are_refused` |
| The same account listed twice | linked (one id) | `test_jellyfin_adapter...test_same_account_listed_twice_is_not_ambiguous` |
| Disabled upstream user (Jellyfin `Policy.IsDisabled`, Audiobookshelf `isActive: false`) | `NOT_LINKED`, reason `disabled` | `test_jellyfin_adapter...test_disabled_upstream_account_not_linked`, `test_audiobookshelf...test_unmapped_inactive_and_ambiguous_members_are_not_linked` |
| Upstream account renamed after the mapping was cached | still linked to the same upstream id until `MAPPING_TTL_FOUND` (60 s) passes, then `unmapped`; a section cached before that lives its own TTL (30 s continue, 120 s recent and item) | `test_h2_security.MappingLifetime.test_a_renamed_upstream_account_stops_linking_once_the_mapping_ttl_passes` |
| Rename to a case variant | `case_or_unicode_mismatch`, never linked | `test_h2_security.MappingLifetime.test_a_rename_to_a_case_variant_is_never_linked` |
| Upstream user disabled after the mapping was cached | linked until the mapping TTL passes, then `disabled`. Audiobookshelf also re-reads the member's own record (`isActive`) on every uncached section, every cover and every search, so there it takes effect on the next upstream call | `test_h2_security.MappingLifetime.test_a_disabled_upstream_account_stops_linking_once_the_mapping_ttl_passes`, `test_h2_security.AudiobookshelfArtworkRevocation.test_a_deactivated_member_gets_no_warm_cover` |
| Upstream user deleted with a cached mapping | the user-scoped route answers 404: `NOT_LINKED`, mapping dropped, circuit untouched | `test_audiobookshelf...test_a_user_route_404_with_a_cached_mapping_means_not_linked_and_drops_the_mapping` |
| Authentik group removed | immediate on the next request, whatever is cached (sections, item, search, artwork, mapping) | `test_h2_security.MappingLifetime.test_a_revoked_group_is_immediate_whatever_is_cached`, `test_h2_security.SharedViewCovers.test_losing_the_group_gates_sections_item_and_artwork_with_a_warm_cache` |
| Item hidden from the member upstream (Jellyfin, Audiobookshelf) | the next cover request is a 404, even with a warm cache | `test_h2_security.JellyfinArtworkRevocation.*`, `test_h2_security.AudiobookshelfArtworkRevocation.*` |
| Cache partition | every entry is keyed by an HMAC of the member's username; one member's warm cover or section is never another's | `test_h2_security.JellyfinArtworkRevocation.test_a_second_member_never_gets_the_first_members_cached_cover`, `test_h2_security.SharedViewCovers.test_the_cover_cache_is_per_member`, `webtests/test_web_isolation_h2.py` |

## 3. The owner preview override

The LAN owner preview maps the owner's principal to fixed upstream names (`HOME_JELLYFIN_USERNAME`,
`HOME_AUDIOBOOKSHELF_USERNAME`), for the owner's principal only. It is reachable only through the sealed
path:

* `Settings.from_mapping` honours `HOME_OWNER_PREVIEW=yes` and the username variables only with the seal,
  which only `preview/run_preview.py` passes (a test pins the one importer); `serve.py` never does.
* **New in this change:** `Settings.__post_init__` refuses `owner_preview`, `owner_preview_username` or a
  member username override unless the settings carry the seal, so constructing `Settings(...)` directly or
  with `dataclasses.replace` cannot switch the override on either
  (`test_h2_security.SealedOverride.*`). An override without the owner's username is refused too.
* `main._member_username` passes an override to an adapter only when `owner_preview` is set; the adapter
  applies it only when the principal's username equals the owner's (`_base.lookup_username`). Cache scoping,
  logs and everything else keep the principal's own username.

Python code already running in the process can still bypass all of this (`object.__setattr__`); that is out
of scope, as it is for the principal itself.

## 4. Proven offline vs still to prove

**Proven offline (synthetic fixtures, fake transports, loopback mocks):** everything in the table above;
the sealed override; per-member artwork revocation; cache partitioning; the isolation of two synthetic
members across `/`, `/home.json`, `/search` and `/art/` with a cold cache, a warm cache and one upstream
failing (`webtests/test_web_isolation_h2.py`).

**Needs Authentik (AVR-373, AVR-498) and cannot be proven here:**

* that the outpost really sends the username and groups the code expects, for every member, and that no
  sibling container can forge them (gates G1, G2); the verified-JWT mode of PR #52 is not on this branch;
* that Authentik usernames are ASCII in practice. If the JWT path lands, a claim username may be Unicode
  (NFC enforced, not ASCII). The exact-match rule still never links a confusable, but the operator should
  keep Authentik usernames ASCII to avoid a member who can never be linked;
* that group removal in Authentik reaches the outpost headers promptly (session refresh behaviour).

**Needs real multi-member testing (owner, physical):**

* that each real member's Jellyfin and Audiobookshelf account name equals their Authentik username exactly
  (the owner's own differ, which is why the preview override exists);
* that Jellyfin hides an item from `/Items?userId=` when the owner restricts it for that user (parental
  rating, library access), and that a **disabled** Jellyfin user's `/Items?userId=` answers are refused. The
  adapter only re-reads `Policy.IsDisabled` when the mapping is refreshed (at most 60 s);
* Audiobookshelf permission field names (`librariesAccessible`, `isActive`, tag rules) against the deployed
  version: the fixtures are from documentation and unverified;
* two real members on two devices at the same time, with different groups, checking that neither sees the
  other's titles, progress or covers (the offline isolation test is the template).

## 5. Residual risks (accepted or for the owner)

1. Mapping TTL: a renamed or disabled upstream account keeps its link for up to 60 s, plus the section's own
   cache (30 to 120 s). It only ever shows that member's own previous data; it never links anyone else.
2. Shared views (Komga, Calibre-Web): a book removed from the one account's view can keep its cover in that
   member's own cache for up to 300 s. Group removal is still immediate.
3. Browser copies: covers are sent `Cache-Control: private, no-cache` with an `ETag`: no proxy keeps them, and the browser revalidates every use (the full check runs; 304 only if allowed).
   An image already shown in an open page stays visible until the page is reloaded.
4. Per-member covers need a live upstream check: while Jellyfin or Audiobookshelf cannot answer, their covers
   are 404 (the letter placeholder shows) even if the bytes are cached. This is deliberate (fail closed).
   Review of #57: covers have their own concurrency allowance (8 per adapter, 4 per member, separate from the
   section slots), wait up to 0.4 s for a slot within their own deadline instead of being refused at once, and
   never steer the circuit the sections use, in either direction: a cover's failure is not counted, its
   success does not reset the sections' failure run, and it never takes the half-open trial (covers are
   refused while the circuit is open or half-open, so only a section call can close it). A user-list lookup
   that a cover led and that failed is counted once, by the first section that shared it. After a cool-off,
   covers stay refused until a section call succeeds as the half-open trial; since sections may be served
   from their cache meanwhile, covers can show the letter placeholder (404) for up to the section cache
   lifetime (30 to 120 s) after the upstream is back. It recovers on its own with the next section fetch. A waiting cover holds one
   worker thread for at most 0.4 s (bounded per adapter by 8 covers in flight plus the waiters). A transient failure (busy, timeout, unreachable) keeps the
   cached bytes; only a definitive negative (not visible, not linked) drops them. Each warm cover still costs
   one upstream visibility call. **Option, owner decision:** cache the positive visibility verdict per member
   and item for a few seconds (for example 5 to 10 s) to cut those calls; this reopens a revocation window of
   that length and is not implemented.
5. **Owner preview lockout (review of #53, LOW).** `preview/gate.py` keys the failure throttle by client
   address. Assessment: if Docker presents every LAN client as one address, ten wrong passwords from any LAN
   device lock the owner out for 60 s. No safe change was found inside the gate: admitting a correct password
   during a lockout turns the lockout into a correctness oracle at full request rate, and a shorter window
   weakens the throttle for everyone. The only safe improvement is a session cookie issued after a correct
   password and honoured during a lockout, which is a new credential and therefore an **owner decision**;
   it is not implemented. Docker's default iptables DNAT normally preserves LAN client addresses (the shared
   address arises with the userland proxy), so the owner should check which address the gate sees on
   `avrana` before deciding. The gate is unchanged: constant-time compare, throttle, outermost position.
6. **Username reuse: no stable account identifier (AVR-503 benchmark F4, broadened in the review of #54).** The
   username is the only identity the application has. It is used twice: as the cache partition key (an HMAC of
   the username) and as the upstream account name (Jellyfin and Audiobookshelf are matched by exact username).
   So if an Authentik account is deleted and its username given to someone else, the new holder:
   * reaches the **previous holder's upstream accounts** (their Jellyfin and Audiobookshelf libraries, history
     and progress) for as long as those accounts keep that name, regardless of any cache; and
   * could be served the previous holder's cached entries while they live (at most 300 s for covers, 120 s for
     sections, 60 s for the mapping; the cache is in memory only and dies with the process).

   **What a stable identifier would require.** Either (a) a stable Authentik attribute in the principal (the
   outpost's `X-authentik-uid`, or the verified token's `sub` from PR #52's JWT mode), used as the cache
   partition key and recorded against each upstream account, which needs an owner-maintained mapping table
   (principal uid to Jellyfin and Audiobookshelf user ids), because upstream accounts carry no Authentik uid;
   or (b) that mapping table alone, keyed by username but written by the owner at onboarding and removed at
   offboarding, so a reused username maps to nothing until the owner links it. Both replace the owner's
   2026-10-15 decision (match by username, no link table) and touch the identity path that PR #52 changes, so
   neither is implemented here. **Owner decision 2026-10-27: no username reuse** (docs/DECISIONS.md); no link table.

   **What offboarding must do today** (add to `docs/runbooks/offboarding.md` when the owner approves):
   1. In Authentik, deactivate the member (do not delete and recreate under the same username).
   2. In Jellyfin and Audiobookshelf, disable the member's account, or rename it to a name no Authentik user
      can have (for example with a suffix Authentik usernames never carry), so the username no longer maps.
      A disabled account already maps to `NOT_LINKED` (`disabled`); a renamed one to `unmapped`.
   3. Wait at least 5 minutes before any reuse of that username, or restart Home (owner approval), so cached
      entries are gone. `MemberCache.purge_member` exists but is wired to nothing.
   4. Never assign a former member's username to a new person while their upstream accounts still carry it.
7. **Upstream-side permission changes (AVR-503 benchmark F5), owner decision.** A permission change made inside
   Jellyfin or Audiobookshelf (not in Authentik) reaches cached sections only when they expire: 30 s for
   Continue, 120 s for New this week and item lookups. Covers from those two services are re-checked on every
   request (this change); covers from the shared views keep up to 300 s. An Authentik group change is
   immediate. Shorter TTLs cost more upstream calls per page; the owner decides whether these windows are
   acceptable for the beta.
8. **Concurrency cap (AVR-503 benchmark F2).** Each adapter admits 8 upstream calls at once
   (`DEFAULT_MAX_IN_FLIGHT`), at most 2 per member. Fifteen members opening a cold Home together need about
   30 calls per service, so some sections are refused at once as `busy` and render as unavailable until the
   next load. Not changed here: a wait for a slot conflicts with the reviewed rule that `busy` is immediate
   (`tests/test_hung.py::...test_busy_is_immediate_without_waiting_for_the_cap`), which keeps hung upstreams
   from adding latency to every page. Recommendation: (a) raise the per-adapter cap (for example to 16)
   together with the shared worker pool, after the owner's live run measures what each upstream tolerates,
   keeping the per-member cap of 2 so one member cannot take every slot; or (b) a bounded wait for a slot
   taken from the request's own deadline (so the page's hard cap still holds), only while the circuit is
   closed, with that test revised in review. Either is a reviewed follow-up, not a member-beta blocker for a
   small invited group.

   **Done 2026-10-27 (owner instruction "benchmark first, then implement and test a bounded queue"): option (b).**
   A section refused by the service cap waits in a bounded queue: at most `SECTION_SLOT_WAIT` (1.0 s) and half of
   its own deadline (the wait is part of it), at most `SECTION_MAX_WAITERS` (24) queued per adapter, and only while
   the circuit is closed; the per-member cap never waits. Burst benchmark (`tools/bench_catalog.py --burst-only`,
   3 rounds, 15 members, synthetic upstreams), unavailable sections out of 45 pages:

   | Scenario | Before | After | p95 before / after |
   |---|---|---|---|
   | 20 ms upstreams | 36 (busy) | 0 | 351 / 386 ms |
   | 200 ms upstreams | 36 (busy) | 0 | 1756 / 1756 ms |
   | Jellyfin hangs, others 20 ms | 60 (24 timeout, 36 busy) | 60 (same) | 2039 / 2042 ms |

   A hung upstream still shows as unavailable and adds no latency beyond its own timeout (p95 unchanged); median
   Home in that case rises from 0.3 s to 1.0 s because queued Jellyfin sections wait before giving up.
   `tests/test_section_queue.py` covers admission, the bound, the half-deadline rule, open circuit, queue length,
   the per-member cap and 30 sections through 8 slots. Real upstream tolerance is still unmeasured.
