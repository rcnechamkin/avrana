# Member beta readiness (Home 2.0, AVR-364, AVR-375, AVR-386, AVR-387)

Status: a checklist written 2026-10-16 on `feat/h2-security` (Home 2.0 sprint, Lane D). It records evidence, not
approval. **Avrana Home is not ready for a member beta.** The LAN owner preview (`docs/runbooks/home-owner-preview.md`)
shows the owner's own data behind one password; it does **not** prove Authentik integration, multi-member
isolation with real accounts, or production readiness, and nothing in this document treats it as if it did.

## The six states

Each gate is in exactly one state, the highest one reached; reaching one is never evidence of the next.

1. **Implemented and locally verified**: code and offline tests on a branch, run locally (GitHub CI is unavailable).
2. **Independently reviewed**: an independent review of that change found no unresolved high or medium finding.
3. **Merged**: on the integration branch (`feat/home-2.0`) or `main`, by the owner's decision.
4. **Deployed to owner preview**: running in the LAN owner preview on `avrana`.
5. **Physically verified**: a person did it on a real device, and the owner recorded it.
6. **Ready for member beta**: all of the above, plus the owner's explicit go for members.

`-` means not reached. A row at 2 means the behaviour existed before this change and an independent review of
an earlier PR covered it; the tests and fixes added on `feat/h2-security` are at 1 until this PR is reviewed.
Test names are in `services/avrana-home` unless they start with `tests/` at the repository root.

## Identity and access

| Gate | State | Evidence | What is missing |
|---|---|---|---|
| A member's identity comes only from the outpost, and forged headers cannot reach the app (G1) | - | `docs/runbooks/g1-network-isolation.md` (plan) | G1 applied and verified in production (owner) |
| Authorization and isolation suites pass in production (G2) | - | | Owner-run G2 evidence |
| Verified-JWT identity (AVR-498, PR #52) | 1 on its own branch, not on `feat/home-2.0` | PR #52, `docs/design/BETA-CHECKLIST.md` on that branch | Review, merge, Authentik provider (AVR-373), log-only week |
| Group gates every library before any cache read or upstream call | 2 | `tests/test_h2_security.py::MappingLifetime::test_a_revoked_group_is_immediate_whatever_is_cached`, `SharedViewCovers::test_losing_the_group_gates_sections_item_and_artwork_with_a_warm_cache`; reviews of #50, #53 | Real Authentik groups for real members |
| Upstream account mapping: exact, case-sensitive, ambiguous refused, confusables never linked | 1 | `docs/design/IDENTITY-MAPPING.md` section 2; `tests/test_h2_security.py::MatchExactlyOne` | Each real member's account names checked against Authentik (owner) |
| The preview owner override cannot be enabled outside the sealed path | 1 | `tests/test_h2_security.py::SealedOverride`, `tests/test_preview_gate.py::SealedSettings` | Review |
| Libraries a member cannot use are absent (never named, counted or "unavailable") | 2 | `webtests/test_web_search.py`, `webtests/test_web_sections.py`, `webtests/test_web_isolation_h2.py` | Real multi-member check |

## Isolation and caching

| Gate | State | Evidence | What is missing |
|---|---|---|---|
| No title, id, cover or progress of one member reaches another (`/`, `/home.json`, `/search`, `/art`), cold and warm cache, one upstream failing | 1 | `webtests/test_web_isolation_h2.py` (all classes), `webtests/test_bench_cache_revocation.py` (#54, warm-cache group revocation) | Title pages (Lane C, TODO in that module); two real members on two devices (owner, physical) |
| Cache partitioned per member (HMAC key), per-member quotas | 2 | `tests/test_cache.py`; `tests/test_h2_security.py::SharedViewCovers::test_the_cover_cache_is_per_member`; review of #50 | |
| Cover revoked on the next request when the member loses the item (per-member services) | 1 | `tests/test_h2_security.py::JellyfinArtworkRevocation`, `AudiobookshelfArtworkRevocation` (fixes #53 LOW) | Jellyfin and Audiobookshelf hiding behaviour on the real servers (owner) |
| Covers not kept by proxies; browser copies revalidated through the full check on every use | 2 | `Cache-Control: private, no-cache` + `ETag` on `/art/` (`webtests/test_web_artwork.py::RevalidationTests`, `test_web_realserver.py`, `test_web_isolation_h2.py`) | Residual: a page already open keeps showing an image until reloaded |
| Shared-view covers (Komga, Calibre-Web) bounded by `ARTWORK_TTL` 300 s after removal from the one account | 1 (documented residual) | `tests/test_h2_security.py::SharedViewCovers::test_a_shared_cover_outlives_removal_at_most_artwork_ttl` | Owner acceptance |

## Reliability

| Gate | State | Evidence | What is missing |
|---|---|---|---|
| One failed upstream (down, slow, 500, malformed, wrong user) never breaks the page or other sections | 2 | `webtests/test_web_isolation_h2.py::OneUpstreamFailing`, `webtests/test_web_artwork.py`, `tests/test_breaker_policy.py`, `tests/test_hung.py` | Real outage on the preview (owner, physical) |
| Circuit breaker opens and recovers | 2 | `tests/test_breaker_policy.py`, `tests/test_h2_security.py::JellyfinArtworkRevocation::test_an_unreachable_upstream_never_serves_a_cached_cover_and_recovers` | |
| Unavailable is not empty in search | - here (Lane C owns it) | review of #53 LOW | Lane C fix and its tests |

## Member experience (AVR-364, AVR-386, AVR-387)

| Gate | State | Evidence | What is missing |
|---|---|---|---|
| Installable Home: manifest, icons, head tags only on shell pages, CSP narrowed to `manifest-src 'self'` on shell pages only | 1 | `webtests/test_web_install_h2.py`; parity tests (`webtests/test_web_parity.py`) | Install on iPhone, Android and a computer (owner, physical). Behind Authentik forward auth the manifest and icon requests may not carry the session: unverified |
| Shell-only script and service worker (MK-3, AVR-717): offline page only on a failed network, no cached member data | 1 | `webtests/test_web_pwa.py` (PageScript, ScriptTagAndCsp, Worker, OfflinePage, Signout), `webtests/test_web_install_h2.py::ManifestAndIcons::test_shell_pages_have_exactly_one_first_party_script_and_nothing_inline`; `tests/ui/harness/pwa_run.py` (worker logic in Node, browser checks in Chromium, by hand) | Dedicated security review; a real phone (iOS 26.x installed app, Chrome Android); HTTPS only, the LAN preview is plain http |
| Device help topics accurate against what Home does | 1 (draft) | `docs/member/help/*.md`, `tests/test_device_help.py` | Every step is `[UNVERIFIED on a real device]`; owner decisions D-1, D-12, D-13, D-15; the topics are not wired into the shell |
| Account page explains sign-in per service, sign-out and where help is, without claiming single sign-on | 1 | `account.html` (shell only; sections-off page byte-identical to the portal) | Owner review of the copy; behaviour of Sign out per service (unverified) |
| Handoff links from standalone mode | - | Documented in `docs/member/help/home-screen.md` (iOS opens other hosts in a separate browser view) | Physical check on iOS and Android |
| Visual sizes 360 px, 390 px, desktop, 200 % text | Lane A | | |

## Preview and operations

| Gate | State | Evidence | What is missing |
|---|---|---|---|
| Owner preview gate: outermost, constant-time compare, throttle | 2 (#53 is a draft, not merged; HOME-2.0-SPRINT.md says the preview runs `feat/lan-demo`, which this lane has not checked) | `tests/test_preview_gate.py`; review of #53 | Owner merge decision; physical check |
| Preview lockout by shared client address (review of #53, LOW) | assessed, unchanged | `docs/design/IDENTITY-MAPPING.md` section 5 item 5 | Owner decision: check the address Docker presents; optionally a session cookie (new credential) |
| Offboarding purges a member's cache | 1 (method only) | `MemberCache.purge_member`, `tests/test_cache.py` | Not wired into any offboarding step |
| A reused username never reaches the previous holder's upstream accounts or cache (F4) | - (residual, owner decision) | `docs/design/IDENTITY-MAPPING.md` section 5 item 6 | Stable id (Authentik uid or JWT `sub` plus an owner-maintained link table) or the offboarding steps there: deactivate, disable or rename upstream accounts, wait 5 minutes or restart |
| Expired cache entries are swept, not left in memory (F3) | 1 | `tests/test_h2_security.py::ExpiredEntriesAreSwept` | Review |
| Fifteen members opening Home at once get every section (F2) | - | IDENTITY-MAPPING.md section 5 item 8 (recommendation) | Bounded queue implemented 2026-10-27 (36 to 0 busy on the synthetic burst); live measurement on the beta still to do |
| Upstream-side permission changes take effect within 30 s / 120 s (sections), covers per request or 300 s (F5) | documented | IDENTITY-MAPPING.md section 5 item 7 | Owner decision |

## What the LAN owner preview proves, and what it does not

It proves that the owner's own Jellyfin, Audiobookshelf, Komga and Calibre-Web data can render in Home on the
LAN, once the owner has deployed it and looked. It does not prove: Authentik sign-in, outpost headers, G1 or G2;
that any other member is linked correctly or isolated; behaviour with more than one identity (the preview has
exactly one); production networking, TLS, or Cloudflare; installability behind Authentik.
