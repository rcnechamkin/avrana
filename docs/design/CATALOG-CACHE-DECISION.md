# Catalogue caching and search index: decision (AVR-503)

Status: **decision proposed for review, 2026-10-16** (Home 2.0 sprint, lane E). Implemented and locally
measured on synthetic data only. Not independently reviewed, not merged, not deployed. Nothing here was run
against a real upstream.

## Decision

**The current disposable, in-memory, per-member cache is sufficient. No search index (FTS5 or normalised
tables), no persistent catalogue store and no background job are proposed, and no owner approval is
requested.** Three non-index changes are recommended instead, because the measurements show where Home is
actually slow or fragile, and none of them is a cache or an index (section "Defects and findings").

Why, in one paragraph: with every simulated upstream answering in 20 ms, a warm Home costs about 6 ms of
server time and no upstream call; a cold Home about 100 ms at the median (p95 about 600 ms, set by one
adapter, below); search (never cached) about 45-50 ms at the median and about 170 ms at p95, for 100, 5,000
and 50,000 items per library alike. The Avrana side
does not grow with the catalogue, because every upstream page it asks for is bounded (12 results, at most 50
or 100 per page). What does hurt is not search at all: it is Audiobookshelf's Continue, which makes one
upstream call per in-progress book, in series, inside the one 2 s budget, so that at 200 ms per upstream call
it times out every time and its timeouts open the Audiobookshelf circuit for every member. A local index would
not touch that path, and it would mean a second, member-visibility-sensitive copy of four libraries to keep
correct on every permission change. The extra persisted data and operations are not justified by anything
measured.

## What exists today (review of the cache semantics)

Source: `services/avrana-home/avrana_home/cache.py`, `contract.py` (`MediaAdapter`), `app/main.py`,
`app/artwork.py`; rules in `ADAPTER-CONTRACT.md` section 5 and `HOME-APP.md`.

| Aspect | Today |
|---|---|
| Mechanism | One `MemberCache` per process: stdlib SQLite on `:memory:`, shared by all adapters. No file-path setting; closed on shutdown. A restart costs one slow page per member. |
| Keys | HMAC-SHA256 under a per-process random key over (member username, service, entry name). No usernames, ids or refs as key material. Values (titles, progress, image bytes) are plaintext in process memory. |
| What is cached, TTL | Continue 30 s, Recent 120 s, single item 120 s, thumbnail bytes 300 s (`ARTWORK_TTL`), upstream mapping found/absent 60 s. Only OK and EMPTY results are stored, and only when fresh (a late answer after the circuit moved on is not stored). |
| Never cached | Search results and the search term (`MediaAdapter.search`). Unavailable sections. Shared views (Komga, Calibre-Web) are still cached per member: there is no shared catalogue cache in use (`SharedCache` exists, unused). |
| Bounds | 2048 entries and 32 MiB in total; 128 entries and 8 MiB per member, measured in stored bytes. A member over quota evicts their own entries (thumbnails first, mapping last); under global pressure the heaviest member pays first. |
| Authorization at read time | The Authentik group check runs **before** the cache is read (`_section`, `fetch_artwork`, `search`): a lost group takes effect on the next request, with no upstream call and no cached byte served. Entries are partitioned by member; a member scope cannot name another member. |
| Upstream-side permission changes | Not visible until the entry expires: a title or progress the member lost upstream (library access removed, Audiobookshelf library/tag permissions, account disabled) can be shown to **that same member** for up to 30 s (Continue) or 120 s (Recent, item), a thumbnail for up to 300 s, a mapping for 60 s. Search reflects it on the next search. |
| Purge | `MemberCache.purge_member(principal)` exists and is tested; it is wired to nothing (owner decision, HOME-APP.md). `clear()` is only a speed cost. |
| Logs | `logsafe.log_event` allow-lists the fields (route template, status, duration, service, section, state, reason, error class). Never a username, title, item id, term or URL. The benchmark reads exactly these events. |

### Two-user and revoked-entitlement checks

No cached title, image or progress was disclosed in any check. Existing tests already cover the cold-cache
rules: `tests/test_search.py` (a revoked group acts on the next search, no upstream call), `tests/test_cache.py`
(member-scoped delete and purge), `tests/test_phase1.py` (purge removes what the adapter would serve),
`webtests/test_web_artwork.py` (another member's cover and a member without the group get the standard 404),
`webtests/test_web_home.py` (two members see only their own items), `tests/test_audiobookshelf.py`
(cross-member progress under threads). The one gap was the **warm** case, so one small benchmark-adjacent
module was added, `services/avrana-home/webtests/test_bench_cache_revocation.py`: with member A's Home and
thumbnails already in the cache, (1) A after losing every library group gets no title, no `/art/` link, no
Continue rail, a 404 for every one of A's cached thumbnails and zero upstream calls, and an empty search;
(2) A after losing three of four groups gets nothing from those libraries, thumbnails included; (3) another
member never gets A's page or thumbnails (a shared-group cover is re-checked upstream for that member and
answers exactly as an empty cache would). It is not a general isolation suite; lane D owns that.

## Method

Command (versioned; `BENCH_VERSION = "1"`):

    cd services/avrana-home
    python -B tools/bench_catalog.py                 # the run below: 3 rounds, about 11 minutes
    python -B tools/bench_catalog.py --quick         # smoke run
    python -B tools/bench_catalog.py --json out.json # raw summary as well

`tools/` is not under `tests/` or `webtests/` and the file is not `test_*.py`, so neither `unittest discover`
nor `run_web_tests.py` collects it.

- **The real application and adapters.** `create_app` with the real Jellyfin, Audiobookshelf, Komga and
  Calibre-Web adapters on one shared `MemberCache` (as `build_adapters` does), timeout 2 s, section limit 12,
  driven through Starlette's in-process `TestClient`. No socket is opened, not even on loopback.
- **Simulated upstreams** (`SimTransport` over generated routers that speak the shapes of the existing
  synthetic fixtures). Catalogue sizes 100, 5,000 and 50,000 items **per service**. Search in the simulator is
  a word index (cost proportional to the hits), so the catalogue size changes what an upstream answers, not
  what it costs; the simulator's own compute stayed below 75 ms max per call (reported in the JSON notes).
  Synthetic thumbnails are 48 KiB. The Calibre-Web simulator pages search at 60 entries (assumed).
- **15 synthetic members**, mixed groups: three with all four libraries, pairs, singles, one with none (portal
  only), one in the videos group with no Jellyfin account (not linked). Jellyfin members see one to three of
  three libraries; half the Audiobookshelf members are limited to one of two libraries; 8 books in progress each.
- **Latency profiles**: every call 20 ms, 100 ms or 200 ms; Jellyfin hangs until the caller's timeout;
  Audiobookshelf refuses connections; every upstream refuses connections.
- **Phases per round** (a round is a fresh app, i.e. a cold cache): Home cold, Home warm, the New tabs
  (`/?new=<library>`), six thumbnails per member cold then warm, four searches per member (every title /
  one noun / one item number / no match), Home after +31 s and +131 s of simulated time. Between phases the
  adapters' clock is wound back by the phase's own duration, so TTLs age only where a phase says so.
  Burst: all 15 members' cold Home at once, one client each.
- **Measured**: server-side time from the app's own access-log `duration_ms`; upstream calls per request
  counted in the transport; unavailable sections and their reasons from the app's `section` events.
  p50/p95 are nearest-rank over all requests in the cell (45 per Home cell: 15 members x 3 rounds).
- **Machine**: Windows 11 dev laptop, 4 logical CPUs, Python 3.12.3, FastAPI 0.115.6. **This is not the
  production host** (`avrana`), and the numbers are only comparable with each other.

## Results

Recorded run (`bench_catalog v1 seed=503 rounds=3 members=15 python=3.12.3 fastapi=0.115.6 os=Windows 11 machine=AMD64 cpus=4 wall=650s`):

| scenario | phase | n | p50 ms | p95 ms | upstream calls / req (mean, max) | unavailable sections (reasons) | 5xx |
|---|---|---:|---:|---:|---:|---:|---:|
| normal 20 ms, 100 items | home cold | 45 | 351 | 854 | 7.4, 15 | 0 | 0 |
| normal 20 ms, 100 items | home warm | 45 | 6 | 12 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 100 items | new tabs (warm) | 69 | 8 | 11 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 100 items | art cold | 216 | 62 | 158 | 2.0, 3 | 0 | 0 |
| normal 20 ms, 100 items | art warm | 216 | 1 | 3 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 100 items | search (never cached) | 180 | 45 | 248 | 2.6, 5 | 0 | 0 |
| normal 20 ms, 100 items | home +31 s (continue expired) | 45 | 8 | 581 | 2.2, 10 | 0 | 0 |
| normal 20 ms, 100 items | home +131 s (all sections, mapping expired) | 45 | 129 | 641 | 7.4, 15 | 0 | 0 |
| normal 20 ms, 5,000 items | home cold | 45 | 105 | 578 | 7.4, 15 | 0 | 0 |
| normal 20 ms, 5,000 items | home warm | 45 | 6 | 11 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 5,000 items | new tabs (warm) | 69 | 7 | 12 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 5,000 items | art cold | 216 | 64 | 160 | 2.0, 3 | 0 | 0 |
| normal 20 ms, 5,000 items | art warm | 216 | 1 | 3 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 5,000 items | search (never cached) | 180 | 44 | 168 | 2.7, 7 | 0 | 0 |
| normal 20 ms, 5,000 items | home +31 s (continue expired) | 45 | 32 | 474 | 4.0, 10 | 0 | 0 |
| normal 20 ms, 5,000 items | home +131 s (all sections, mapping expired) | 45 | 177 | 653 | 7.4, 15 | 0 | 0 |
| normal 20 ms, 50,000 items | home cold | 45 | 96 | 584 | 7.4, 15 | 0 | 0 |
| normal 20 ms, 50,000 items | home warm | 45 | 7 | 12 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 50,000 items | new tabs (warm) | 69 | 8 | 12 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 50,000 items | art cold | 216 | 63 | 154 | 2.0, 3 | 0 | 0 |
| normal 20 ms, 50,000 items | art warm | 216 | 1 | 2 | 0.0, 0 | 0 | 0 |
| normal 20 ms, 50,000 items | search (never cached) | 180 | 50 | 170 | 2.8, 7 | 0 | 0 |
| normal 20 ms, 50,000 items | home +31 s (continue expired) | 45 | 30 | 479 | 3.7, 10 | 0 | 0 |
| normal 20 ms, 50,000 items | home +131 s (all sections, mapping expired) | 45 | 71 | 694 | 7.4, 15 | 0 | 0 |
| slow 100 ms, 5,000 items | home cold | 45 | 322 | 1449 | 7.4, 15 | 0 | 0 |
| slow 100 ms, 5,000 items | home warm | 45 | 7 | 12 | 0.0, 0 | 0 | 0 |
| slow 100 ms, 5,000 items | new tabs (warm) | 69 | 8 | 12 | 0.0, 0 | 0 | 0 |
| slow 100 ms, 5,000 items | art cold | 216 | 252 | 434 | 2.0, 3 | 0 | 0 |
| slow 100 ms, 5,000 items | art warm | 216 | 1 | 2 | 0.0, 0 | 0 | 0 |
| slow 100 ms, 5,000 items | search (never cached) | 180 | 155 | 487 | 2.7, 7 | 0 | 0 |
| slow 100 ms, 5,000 items | home +31 s (continue expired) | 45 | 6 | 120 | 0.1, 1 | 0 | 0 |
| slow 100 ms, 5,000 items | home +131 s (all sections, mapping expired) | 45 | 328 | 1346 | 7.4, 15 | 0 | 0 |
| slow 200 ms, 5,000 items | home cold | 45 | 448 | 2128 | 4.6, 14 | 21 (UpstreamTimeout 9, cooling_off 12) | 0 |
| slow 200 ms, 5,000 items | home warm | 45 | 6 | 12 | 0.0, 0 | 21 (cooling_off 21) | 0 |
| slow 200 ms, 5,000 items | new tabs (warm) | 69 | 8 | 12 | 0.0, 0 | 39 (cooling_off 39) | 0 |
| slow 200 ms, 5,000 items | art cold | 198 | 445 | 523 | 1.7, 2 | 0 | 0 |
| slow 200 ms, 5,000 items | art warm | 198 | 1 | 2 | 0.0, 0 | 0 | 0 |
| slow 200 ms, 5,000 items | search (never cached) | 180 | 229 | 292 | 1.5, 3 | 84 (cooling_off 84) | 0 |
| slow 200 ms, 5,000 items | home +31 s (continue expired) | 45 | 6 | 232 | 0.1, 1 | 21 (cooling_off 21) | 0 |
| slow 200 ms, 5,000 items | home +131 s (all sections, mapping expired) | 45 | 455 | 2016 | 3.4, 15 | 21 (UpstreamTimeout 3, cooling_off 18) | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | home cold | 45 | 56 | 2151 | 5.7, 13 | 60 (UpstreamTimeout 18, cooling_off 42) | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | home warm | 45 | 4 | 9 | 0.0, 0 | 60 (cooling_off 60) | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | new tabs (warm) | 69 | 6 | 8 | 0.0, 0 | 114 (cooling_off 114) | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | art cold | 162 | 59 | 166 | 2.0, 3 | 0 | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | art warm | 162 | 1 | 3 | 0.0, 0 | 0 | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | search (never cached) | 180 | 45 | 185 | 2.1, 6 | 120 (cooling_off 120) | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | home +31 s (continue expired) | 45 | 4 | 426 | 0.6, 9 | 60 (cooling_off 60) | 0 |
| Jellyfin hangs (2 s timeout), others 20 ms | home +131 s (all sections, mapping expired) | 45 | 74 | 2015 | 5.6, 13 | 60 (UpstreamTimeout 3, cooling_off 57) | 0 |
| Audiobookshelf down, others 20 ms | home cold | 45 | 50 | 156 | 2.9, 6 | 21 (UpstreamUnreachable 9, cooling_off 12) | 0 |
| Audiobookshelf down, others 20 ms | home warm | 45 | 6 | 10 | 0.0, 0 | 21 (cooling_off 21) | 0 |
| Audiobookshelf down, others 20 ms | new tabs (warm) | 69 | 8 | 10 | 0.0, 0 | 39 (cooling_off 39) | 0 |
| Audiobookshelf down, others 20 ms | art cold | 198 | 44 | 114 | 1.7, 2 | 0 | 0 |
| Audiobookshelf down, others 20 ms | art warm | 198 | 1 | 3 | 0.0, 0 | 0 | 0 |
| Audiobookshelf down, others 20 ms | search (never cached) | 180 | 25 | 99 | 1.5, 3 | 84 (cooling_off 84) | 0 |
| Audiobookshelf down, others 20 ms | home +31 s (continue expired) | 45 | 26 | 84 | 0.6, 1 | 21 (cooling_off 21) | 0 |
| Audiobookshelf down, others 20 ms | home +131 s (all sections, mapping expired) | 45 | 50 | 108 | 2.8, 6 | 21 (UpstreamUnreachable 3, cooling_off 18) | 0 |
| all upstreams down | home cold | 45 | 3 | 101 | 0.9, 5 | 120 (UpstreamUnreachable 39, cooling_off 81) | 0 |
| all upstreams down | home warm | 45 | 2 | 3 | 0.0, 0 | 120 (cooling_off 120) | 0 |
| all upstreams down | new tabs (warm) | 69 | 3 | 5 | 0.0, 0 | 243 (cooling_off 243) | 0 |
| all upstreams down | search (never cached) | 180 | 2 | 4 | 0.0, 0 | 360 (cooling_off 360) | 0 |
| all upstreams down | home +31 s (continue expired) | 45 | 2 | 4 | 0.0, 0 | 120 (cooling_off 120) | 0 |
| all upstreams down | home +131 s (all sections, mapping expired) | 45 | 3 | 4 | 0.3, 4 | 120 (UpstreamUnreachable 12, cooling_off 108) | 0 |
| burst 20 ms, 5,000 items | home cold, 15 at once | 45 | 461 | 805 | 7.2, 7 | 6 (busy 6) | 0 |
| burst 200 ms, 5,000 items | home cold, 15 at once | 45 | 1618 | 3081 | 5.9, 6 | 45 (UpstreamTimeout 21, busy 24) | 0 |

Run-to-run variance on this laptop is large for cold cells: an earlier full run of the same command gave a cold Home p50/p95 of 74/317 ms (100 items) and 68/288 ms (5,000 items) where this run shows 351/854 and 105/578 ms; the first cell also carries interpreter and template warm-up. Warm cells, call counts and unavailable reasons were the same in both runs. Read the cold numbers as an order of magnitude, not as a target.

Reading the table: "unavailable sections" counts sections shown as unavailable across all requests in the cell,
with their reason classes; `cooling_off` means the circuit for that service was open.

## Interpretation

1. **Warm is cheap, and Home is mostly warm.** Warm Home, the New tabs and warm thumbnails take single-digit
   milliseconds with zero upstream calls in every scenario, including when upstreams are slow, hung or down
   (a warm member keeps their page while it lasts).
2. **Catalogue size does not reach Avrana.** 100, 5,000 and 50,000 items give the same calls per request and
   medians within noise (the 100-item cell is the first one run and carries warm-up).
   Avrana never pages through a catalogue; it asks each upstream for one bounded page. Caveat: the simulated
   upstream search is an O(hits) word index, so this shows Avrana's side only; real upstream search time at
   real catalogue sizes is unmeasured (see What remains unmeasured).
3. **Search without a cache is fine at 20 ms upstreams** (p95 about 170 ms, 2-3 calls on average, at most 7;
   about 490 ms p95 at 100 ms upstreams). Its cost is the
   upstream's own search time plus Audiobookshelf's per-library round trips, which a local index would replace
   only by copying four libraries' visibility rules into Avrana.
4. **Audiobookshelf Continue is the slow path.** A cold Audiobookshelf member costs up to 15 upstream calls
   (users, own record, then one lookup per in-progress book, in series). The cold-Home p95 is consistent with this (inferred from call counts; the bench does not
   attribute time per service)
   (about 600 ms at 20 ms, about 1.4 s at 100 ms, where it still fits). At 200 ms per call, with about 8 or more
   in-progress books (the bench's assumption), it cannot fit the 2 s budget: the section times out, three timeouts open the Audiobookshelf circuit, and Audiobookshelf
   Continue, search and covers then answer `cooling_off` **for every member** (84 of 84 Audiobookshelf searches
   in that run), though the service is merely slow.
5. **Failure containment works.** A hung Jellyfin costs at most three members about 2 s each before its
   circuit opens; afterwards those sections answer `cooling_off` in milliseconds and other libraries render.
   With everything down, every page answers in a few milliseconds with no 5xx.
6. **A cold burst of 15 members is refused, not queued.** With everyone cold at once, the per-adapter cap of
   8 in-flight upstream calls refuses some sections (`busy`: 6 sections over three bursts at 20 ms, 24 at
   200 ms), and they render as unavailable although nothing failed. A reload a moment later is served. Likely
   only right after a restart, but visible. (The burst p95 of about 3 s at 200 ms is partly the harness: 15
   in-process clients on 4 CPUs.)
7. **The cache stays small.** After a full round (15 members, six thumbnails each) the cache held about
   140 entries and 3.7 MB, against the 2048 / 32 MiB bounds.

## Defects and findings (reported, not fixed here)

| # | Finding | Where | Owner to route |
|---|---|---|---|
| F1 | Audiobookshelf Continue makes up to 24 serial item lookups inside the 2 s budget; at about 200 ms per upstream call it times out for a member with about 8 or more in-progress books, and those timeouts count toward the shared circuit, so a slow Audiobookshelf goes dark for every member for 60 s cycles. Options: fetch the lookups concurrently under the same budget, cap them at the section limit, or use a single listing route if Audiobookshelf has one (UNVERIFIED). | `adapters/audiobookshelf.py` `_continue_items`; `resilience.counts_toward_breaker` | lane B (Audiobookshelf continue parsing) |
| F2 | A simultaneous cold Home for 15 members makes the in-flight cap (8 per adapter, `DEFAULT_MAX_IN_FLIGHT`) refuse sections as `busy`; they render as unavailable. Options: a short bounded wait for a slot, or a cap sized for the member count. | `contract.py` `_acquire_slot` | orchestrator (shared contract) |
| F3 | Expired entries are not swept: they are deleted only when that key is read again or when a quota is reached, so a member's expired titles, progress and thumbnail bytes can stay in process memory indefinitely (bounded by 32 MiB, never served). A data-minimisation gap, not a disclosure. A one-line fix is to call `_purge_expired` on each write (bounded: at most 2048 rows). | `cache.py` `_set` | lane D (owns `cache.py`) |
| F4 | Cache keys use the Authentik **username**. If an account is deleted and the username given to someone else within 300 s, the new person could be served the old person's cached sections or thumbnails, because `purge_member` is wired to nothing. Options: key by a stable Authentik identifier if one reaches the app, or call `purge_member` on offboarding. Review note: the issue is broader than the cache, because the adapters also map upstream accounts by username, so a reused username reaches the previous holder's upstream account regardless of caching; the stable-identifier question covers identity mapping too (AVR-375). | `cache.py` `MemberCache.for_member`; offboarding | lane D / owner |
| F5 | Upstream-side revocations (not Authentik groups) are honoured only at TTL: 30 s / 120 s for titles and progress, 300 s for thumbnails, to the same member. Acceptable for a household; document it in Help or shorten `ARTWORK_TTL` if the owner wants revocation to be faster than five minutes. | `contract.py` TTLs | owner decision, no change proposed |

No unbounded cache growth was found (entries and bytes are bounded in total and per member), and no case where
a lost group served cached data.

## Conditions that reopen this decision

Re-run the benchmark (and, with the owner's approval, the measurements below) and revisit a local index or a
shared catalogue cache if any of these holds:

- measured upstream search p95 on the avrana host above **500 ms** for any library, or cross-library search
  p95 above **1 s** server-side;
- a cold Home p95 above **1 s** on the host after F1 is fixed;
- a library much larger than 50,000 items where the upstream's own search is the measured bottleneck;
- a product need the upstreams cannot answer per member (typo tolerance, ranking across libraries,
  search inside text) that the owner wants;
- member count well above 15 (more than about 30 concurrent members) with F2 showing on warm restarts.

Any of these leads to a request for owner approval first: a persistent index is new personal-data storage
(what each member may see) and new infrastructure to operate and invalidate.

## What remains unmeasured

- **Real upstream latency and real search cost on the avrana host**, per service, cold and warm; the 20 ms and
  200 ms profiles are assumptions that bracket it, not measurements.
- **Real catalogue sizes**, real thumbnail sizes (assumed 48 KiB) and real in-progress counts.
- Calibre-Web's real OPDS search page size (assumed 60) and whether an unpaged broad search would exceed the
  1 MiB body or 5,000-element bounds (it would then show as unavailable).
- Production concurrency (uvicorn workers, the starlette thread pool) on the host's CPU.

The benchmark has deliberately **no real mode**. A real-mode counterpart (the same phases against the real
services, read-only, with the owner's own account) is possible later only with the owner's explicit approval,
as a separate, reviewed step; nothing in this tool can call a live service.
