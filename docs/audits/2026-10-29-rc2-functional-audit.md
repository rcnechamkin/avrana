# Media 2.0 RC2 functional audit (pre-closed-beta quality sprint)

Date: 2026-10-29 (evening, Pacific). Baseline revision: **`2cb228fbfdae596ef3da1754afe88e48b1556552`** (origin/main, also the
running beta). Auditor: functional audit agent, read-only. Nothing in the repository was edited, nothing was merged,
deployed or switched, no host was contacted, no real service was called. Synthetic fixtures, fake transports and the
loopback dev stack only. Every probe named below is a throwaway script under
`C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\functional\`
(called `scratch\` below).

Live switches assumed (names only, from the baseline report): real upstreams, `jwt_required`, identity bindings,
`HOME_SECTIONS`, Komga member keys + provisioning, book/watch/comic requests ON; `HOME_MEMBER_STORE`,
`HOME_SECURITY_FLOWS`, `HOME_LIBRARY_IDS_FILE`, Shelfarr/Seerr provisioning OFF. Enabled paths were audited as primary;
dormant code (My profile, Customize persistence, Account & Security flows, the catalogue-id index) only for
regressions, and is labelled so where it appears.

## (a) Method and what was actually executed

| What | Detail | Result |
|---|---|---|
| Route x identity x failure matrix | `scratch\probe_matrix.py`: the real dev stack built in-process (`dev/run_dev.build_stack`: mock Jellyfin/ABS/Komga/Calibre-Web on 18196-18199, the real `UrllibTransport`, the dev identity shim, `HOME_SECTIONS=on`), driven with Starlette's TestClient, `raise_server_exceptions=True` so any traceback is caught. **22 scenarios**: all-ok; all-slow (2.5 s, over the 2 s timeout), all-down, all-500, all-malformed; jellyfin-wrong-user; and each of the four mocks alone in slow, down, 500 and malformed. **9 identities**: member-a, member-b, member-c, member-d, member-nolib, comics-a, comics-b, synthetic-admin, none. **46 routes**: `/`, `/?for=watch|listen|read|comics|books|bogus`, `/?rel=…`, `/?more=…`, `/?new=komga`, `/watch`, `/listen`, `/read`, `/comics`, `/books`, `/request`, `/contribute`, `/continue` (+ `?for=` x3), `/library` (+ every `?lib=`, a bogus one, `?view=list`, `?view=details&lib=komga`), `/home.json`, `/search?q=` (broad, one letter, empty, no match), `/me`, `/me/tv`, `/me/home`, `/me/profile`, `/me/security`, `/account`, `/help`, `/help/trouble`, `/signout`, `/offline`, `/sw.js`. | **9,108 requests, 0 exceptions, 0 non-200/303/307/404, 0 over 5 s.** Status codes identical for every identity/route pair across all 22 scenarios (degradation never changes a status code). Results: `scratch\matrix_results.json`, log `scratch\matrix_run2.log`. |
| Degraded-state content | `scratch\probe_content.py`: 6 scenarios (all-ok, abs-down, komga-500, calibre-malformed, jellyfin-wrong-user, all-down) x 6 identities x 6 pages; extracts every `role="status"` line and heading; diffs `/home.json` item ids between members. | Correct notices everywhere (one library down: one line, others keep rendering; everything down: the "resting" block with one combined line; member-c/d: "Not set up yet"). Wrong-user mode: member-a's `/home.json` holds no id outside member-a's own set. One anomaly, see F-05. Results: `scratch\content_results.json`. |
| View-model fuzz | `scratch\probe_viewmodel_fuzz.py`: random section states (absent/ok/empty/unavailable/not_linked/not_permitted) per library and section, random item faults (missing title, foreign or missing hand-off, impossible progress, bad dates, duplicates, unknown shelves), random tiles, `?for=`, `?lib=`, `?rel=`, `?new=`, `?more=`, limits; through `build_home`, the `_sections.html` template, `build_continue_page`, `build_library`. | **15,000 iterations, 0 exceptions** (plus a separate 3,000-iteration run). |
| Real dev stack over uvicorn | `run_dev.py --dev-identity --port 8196 --mock-port 18196 --abs-mock-port 18197 --komga-mock-port 18198 --calibre-mock-port 18199`, curl as member-a/b/c and comics-a on 10 routes, then `POST /__mock/mode/down` on ABS, then `/signout` headers; stack killed afterwards. | All 200/404 as expected; cold Home 0.36-0.51 s; `/signout` = 303 to the outpost sign-out with `Clear-Site-Data: "cache", "storage"`. `--mode wrong-user` refuses to start, F-06. |
| Targeted probes | `probe_komga_epub_comics_only.py` (F-01), `probe_comics_stack_link.py` (F-02), `probe_seerr_search_timeout.py` (F-03), `probe_spurious_unavailable.py` and `probe_abs_calls.py` (F-05). | Each fails on 2cb228f as described below. |
| Existing test modules, one at a time | webtests: released_fallback, released_balance, release_order, continue, comics_continue, comics_week, new_for_you, new_rows, home_shelves, home_hero, komga_books, book_requests, book_request_units, watch_requests, comic_requests, my_requests, season_picker, broker_hardening, quick_connect, customize, search, title, library_k, bench_cache_revocation, me_security, navigation, identity_bindings, isolation_h2, pages_k, shell_k, sections, home, jwt_identity, identity, web_artwork, artwork_gateway, web_komga, web_audiobooks, web_calibre, parity, catalogue_routing. tests: komga, komga_member_reading, audiobookshelf, abs_slow_fanout, continue_semantics, search, cache, aggregate, new_for_you_adapters, release_added, title_and_search_states, jellyfin_adapter, calibre_web, quickconnect. | All pass when run alone. In one run made while other agents' suites and my matrix were running, test_web_title, test_web_library_k, test_web_identity_bindings and test_web_sections failed; each passed on rerun (F-05). test_web_me_profile cannot import locally (no Pillow in `.venv-media`); dormant feature, section (d). |

## (b) Findings

| ID | Component | Classification | Severity | Beta-blocking |
|---|---|---|---|---|
| F-01 | Home / Library / Search: Komga EPUB classification | CONFIRMED | P2 | no |
| F-02 | Home New Releases: "This week in comics" card link | CONFIRMED | P2 | no |
| F-03 | Watch requests (Seerr): 2 s search timeout + shared breaker | PROBABLE (mechanism confirmed on fakes; live latency unmeasured) | P2 | no (owner log check advised before members) |
| F-04 | Book and comic requests: "Already in" detection off on the live beta | KNOWN-DEFERRED / DESIGN QUESTION | P2 | no |
| F-05 | Timing-sensitive section budgets (tests flake; in-process "unavailable") | UNVERIFIED (product) / PROBABLE (test reliability) | P2 | no |
| F-06 | Dev stack: `--mode wrong-user` crashes with the extra mocks | CONFIRMED (dev tooling only) | P3 | no |

Counts: P0 0, P1 0, P2 5, P3 1. **No beta-blocking functional defect found on fixtures.**

### F-01 Komga EPUBs are filed under "Books" even for a member with no Books library, and under "Comics" in Search and Details

- **Component:** `avrana_home/app/viewmodel.py` (Home, Library, Search, title page). Enabled path (Komga is live with EPUB novels, #141/#143).
- **Classification / severity:** CONFIRMED, P2 (misleading classification; a library the member does not hold is named).
- **Beta-blocking:** no. Nothing is disclosed that the member may not see (the items are in their shared Komga view), but the page names a library they lack and hides those items from their own Comics filter.
- **User impact:** a Comics-only member (group `avrana-comics`, no `avrana-books`) whose Komga holds an EPUB sees a "Books" tab in New to Avrana and a "Books" chip and shelf on Library, though Account, places and the catalogue say they have no Books. For a member with both, the same novel reads "Books" on Home and Library but "Comics" in Search groups and "Book · Comics" on its Details page.
- **Reproduction:** `python -B scratch\probe_komga_epub_comics_only.py` (tiles: Comics + Request; one Komga `recent` section holding one comic and one ebook).
- **Expected vs actual:** expected New to Avrana tabs `All, Comics` (or the novel under Comics) and Library chips `All, Comics`; actual `new_tabs=(('all','All'),('komga','Comics'),('calibre-web','Books'))` and `chips=['All','Comics','Books']`. Both tests fail.
- **Evidence:** probe output `AssertionError: 'Books' unexpectedly found in ['All', 'Comics', 'Books']`.
- **Root cause:** `home_library()` (viewmodel.py:174-176) moves every Komga e-book to `calibre-web` without looking at the member's tiles; `_sections_by_service()` (viewmodel.py:600-617, the move at :614) then makes a synthetic `calibre-web` section that `build_home`'s tab list (viewmodel.py:1081) and `build_library`'s chips (viewmodel.py:1355) treat as a library the member holds. Search (`build_search`, label from `SERVICE_LABEL[service]`, ~viewmodel.py:1609) and `build_title` (viewmodel.py:1720) do not apply `home_library`, hence the "Comics" label there.
- **Regression risk of a fix:** low-moderate; tests test_web_komga_books and test_web_library_k pin today's behaviour for members holding both.
- **Minimum correction:** apply the move only when the member's tiles hold a books place (`/books` or `/read`); otherwise keep the e-book in the Komga bucket. Optionally label Search/Details with `home_library` for consistency.
- **Existing PR/issue:** none found (`gh pr list --search "komga ebook books"`: #141, #143 introduced the rule; no follow-up).

### F-02 The "This week in comics" card can link to a chip that does not exist, so tapping it reloads All

- **Component:** `build_home` New Releases (viewmodel.py:1066-1124), #154/#158. Enabled path.
- **Classification / severity:** CONFIRMED, P2 (a navigation dead end on Home).
- **Beta-blocking:** no; All stays usable and the comics are still reachable from Comics/Library.
- **User impact:** the card is drawn whenever Komga's `week` list has at least two issues, but its link `/?rel=comics` is honoured only when New Releases' own list (`picked`) holds a comic. When Komga's `released` section failed on that page, or when every released comic is already in Continue or New for You (a caught-up comics reader, the very member the card is for), the Comics chip is absent and the card's link silently shows All again.
- **Reproduction:** `python -B scratch\probe_comics_stack_link.py` (two cases: Komga `released` unavailable with `week` = 4 issues; Komga answered, and both released comics are also in `for_you`).
- **Expected vs actual:** expected following the card to show the Comics list (chip current = `comics`); actual `card href=/?rel=comics#h-released chips offered=['all', 'watch', 'listen']`, and `build_home(..., rel_tab="comics")` gives current chip `['all']`.
- **Root cause:** chips are built from `picked` only (viewmodel.py:1069-1071, `rel` dropped when "comics" is not a chip); the stack condition (viewmodel.py:1106) also accepts `len(week) >= WEEK_MIN` and always links `rel=comics` (viewmodel.py:1113).
- **Regression risk:** low.
- **Minimum correction:** offer the Comics chip whenever the stack is drawn (include `week` kinds in the chip test), and let the Comics chip list the week's issues when `picked` holds none; or link the card to `/?for=comics` / `/library?lib=komga` instead.
- **Existing PR/issue:** none (#154, #158 merged without this case).

### F-03 Watch requests keep a 2 s Seerr timeout; slow searches say "could not be reached" and three of them shut Seerr requests for every member for 60 s

- **Component:** `avrana_home/app/main.py:199-204` (`SeerrRequests(transport, timeout=settings.timeout)`), `avrana_home/requests/seerr.py:228-231` (one `CircuitBreaker` per process), `seerr.py:485` (every call uses `self._timeout`). Enabled path (`HOME_WATCH_REQUESTS=on`; `HOME_TIMEOUT` is not among the live switches, so 2.0 s).
- **Classification / severity:** PROBABLE, P2. The mechanism is confirmed on a fake transport; whether live Seerr searches exceed 2 s is not measured. #144 found exactly this for Shelfarr (a provider-backed search took 4.5 s live) and raised Shelfarr's search to 8 s (`shelfarr.py` `SEARCH_TIMEOUT`); Seerr's search and season lookup also call TMDB in-line, and Omnibus got 4 s for ComicVine (main.py:211), but Seerr was left at 2 s.
- **Beta-blocking:** no, but worth one look at the live log before members arrive (`watch_search ... state=unavailable`, `adapter_failure service=seerr error=UpstreamTimeout`). If those occur, this becomes P1 (broken requests).
- **User impact:** a member searching for a film not in Seerr's cache reads "Requests could not be reached right now"; after three such timeouts from anyone, the shared breaker opens and the next member's search or request is refused without being sent, for the 60 s cool-off.
- **Reproduction:** `python -B scratch\probe_seerr_search_timeout.py` (fake transport: search takes 2.5 s, everything else instant).
- **Expected vs actual:** expected the search to wait as long as Shelfarr's (8 s) and a later member's request to be sent; actual `Seerr search timeout used: [2.0]; Shelfarr SEARCH_TIMEOUT: 8.0; state: unavailable` and `breaker after 3 slow searches: create outcome=unavailable, calls sent=0`. Both tests fail.
- **Root cause:** see file:line above; timeouts count toward the breaker (`seerr.py` `_send`, the generic `except Exception` branch calls `self.breaker.failure`).
- **Regression risk:** low (a longer search timeout only); the request worker is held longer per slow search.
- **Minimum correction:** a `SEARCH_TIMEOUT` for Seerr `search` and `show` like Shelfarr's (6-8 s); consider not counting a search timeout toward the breaker that also guards `create`.
- **Existing PR/issue:** none found (`gh pr list --search "seerr timeout"`).

### F-04 Book and comic request pages never say "Already in" on the live beta

- **Component:** `main.py:1094-1120` (`already_have`), `main.py:957-965` (`comics_owned`), `requests/owned.py:88-90` (`_tables()` returns `{}` when `HOME_LIBRARY_IDS_FILE` is unset).
- **Classification / severity:** KNOWN-DEFERRED / DESIGN QUESTION, P2. The index is documented as optional (HOME-APP.md section 5b, `docs/runbooks/media-requests-rollout.md:244`) and is off live.
- **Beta-blocking:** no; duplicates are caught downstream for books (Shelfarr 422 → "may already be asked for, or already be in Books"), but only after the member has asked.
- **User impact:** with the index off, Ask for a book and Ask for a comic offer the ask button for titles the library already holds; comics have no downstream check described in Home's copy. Watch requests are unaffected (they use Seerr's own media state plus the member's Jellyfin lookup, `watch_owned`, main.py:1067-1081).
- **Reproduction:** code trace: `OwnedIndex(None).exact(...)` → `{}.get(...)` → None for every key; `already_have` then returns `({}, {})` for every search, and `comics_owned` returns `{}`.
- **Minimum correction:** owner decision: either install the index timer per the runbook before members, or say on the two pages that availability is checked after asking.
- **Existing PR/issue:** #124 shipped the index off by default; no follow-up issue found.

### F-05 Section budgets are timing-sensitive: web tests flake under load, and an in-process cold Home once reported a healthy library unavailable

- **Component:** adapter per-section call budget (`HOME_TIMEOUT` 2 s, `contract.py` `_section` → `_call`), Audiobookshelf's sequential permission-checked fan-out (`adapters/audiobookshelf.py:440-479`, `:103-104`); the web tests that compare two renders.
- **Classification / severity:** UNVERIFIED for the product, PROBABLE as a test-reliability issue; P2.
- **Beta-blocking:** no. Over uvicorn the same cold Home took 0.36-0.51 s and never degraded.
- **What was seen:** (1) in `probe_content.py`'s all-ok scenario member-b's first Home said "Audiobooks are unavailable right now. Anything shown from them may be out of date.", and in calibre-malformed member-a's first Home said the same with ABS healthy (2 of 36 cold loads); not reproduced in 9 isolated reruns (`probe_spurious_unavailable.py`). (2) `probe_abs_calls.py`: a cold All page made 15 (member-a) / 20 (member-b) sequential ABS calls and took 2.2-2.5 s in-process. (3) While other agents' suites ran, test_web_title, test_web_library_k, test_web_identity_bindings (`test_a_seeded_member_sees_their_own_home`: one `/home.json` section `'unavailable'`) and test_web_sections (`test_wrong_user_data_degrades_only_the_section_it_poisoned`, `test_members_never_see_each_others_titles…`) failed; each passed on rerun; the isolation tests passed 3/3 alone. Every failure inspected had the "section unavailable" shape, never wrong data.
- **Expected vs actual:** expected a healthy library never to read unavailable; actual: it can when the process is CPU-starved.
- **Root-cause hypothesis:** TestClient runs the app and the mocks in one GIL; under contention a section with many sequential upstream calls overruns the 2 s budget. Live risk depends on real ABS latency x call count, unmeasured.
- **Minimum correction:** for tests, give comparison tests a larger `HOME_TIMEOUT` or a fake clock; for the product, read the live log for `section service=audiobookshelf state=unavailable` on first visits before deciding anything. The orchestrator should not treat a single failing full-suite run of these four modules as a product defect without a rerun.
- **Existing PR/issue:** none.

### F-06 `run_dev.py --mode wrong-user` crashes when the ABS/Komga/Calibre mocks are on

- **Component:** `dev/mock_audiobookshelf.py:44` (`MODES` lacks `wrong-user`; reused by Komga and Calibre mocks), `dev/README-DEMO.md` ("Others: `500`, `malformed`, `wrong-user`").
- **Classification / severity:** CONFIRMED, P3 (dev tooling, never deployed).
- **Beta-blocking:** no.
- **Reproduction:** `python -B services/avrana-home/dev/run_dev.py --dev-identity --port 8196 --mock-port 18196 --abs-mock-port 18197 --komga-mock-port 18198 --calibre-mock-port 18199 --mode wrong-user` → `ValueError: unknown mode` at `mock_audiobookshelf.py:138`. Without the extra ports it starts.
- **Minimum correction:** apply `--mode` only to mocks that support it (or add the mode to the others), and say so in README-DEMO.

## (c) Journeys traced clean (count as verified on fixtures, revision 2cb228f)

1. **The 2026-10-29 Listen/Read HTTP 500 regression (#146/#148) is fixed and survives adjacent states.** `/?for=listen|read|comics|books|watch` and every Home/Library/Continue page answered 200 for all 9 identities in all 22 scenarios (one library down, slow, 500, malformed; all down; wrong-user; member-c/d not set up; member with no libraries; anonymous), and 15,000 fuzzed view states through `build_home` with every focus raised nothing. test_web_released_fallback passes.
2. **Degradation:** one library failing costs only its own section and one status line; the place is struck; "Try again" keeps the filter; everything down shows the one calm block; member-c/d show "Not set up yet" with the help link; status codes never change with upstream state.
3. **Member partitioning:** `/home.json` id sets per member; wrong-user upstream data discarded (member-a holds no foreign id); cache group check runs before any cache read (`contract.py:1031-1032`); test_bench_cache_revocation, test_web_isolation_h2, test_web_sections isolation tests pass.
4. **Continue ordering and progress words:** by `active` across libraries, undated last (`by_activity`); finished items excluded; "Resume" only with a saved position; minutes for video, hours for listens/reads, percent for Komga; Up next / On Deck labelled "Up next"; New for You items left out of Continue; New Releases excludes Continue and New for You (test_web_continue, test_web_comics_continue, test_continue_semantics, test_web_new_for_you, test_web_release_order, test_web_released_balance pass; code read viewmodel.py:51-136, 903-951, 753-773).
5. **Library:** every `?lib=` (own, foreign, bogus) and every `?view=` alias renders 200 and never echoes; a down library is a warning, not a shelf.
6. **Search:** broad, one-letter, empty and no-match queries render for every identity; unavailable is never "no matches"; request fallback only to the member's own request services; size caps and pagination covered by test_search / test_web_search (pass).
7. **Details and hand-offs:** `/title/<service>/<id>` is the permission-checked fresh lookup; hand-off only on the service's fixed host (`handoff_ok`); unavailable / not-set-up title pages; the sheet script (home.js:263-546) pushes the title URL, closes on Back, returns focus to the opener, and falls back to a full load on any non-title answer (signed out, redirect). test_web_title and test_web_library_k pass alone.
8. **Requests (enabled), on fakes:** signed per-member forms, same-origin check, exact fields, double-tap guard and hourly rate, post-redirect-get flash, season picker, NOT_LINKED/REFUSED/UNAVAILABLE copy, My requests ownership and cancel gates, Seerr admin refusal, Shelfarr 8 s search timeout from #144 present (`shelfarr.py` `SEARCH_TIMEOUT`), the ask-row layout fix from #144 present in CSS (`home.css:740-747`; not checked visually). test_web_book_requests, test_book_request_units, test_web_watch_requests, test_comic_requests, test_my_requests, test_season_picker, test_broker_hardening pass.
9. **Me / TV / sign-out:** `/me`, `/me/tv` (200 for TV members, 404 for others), Quick Connect guardrails (test_web_quick_connect, test_quickconnect pass), `/signout` 303 with `Clear-Site-Data`, `/offline` and `/sw.js` identity-free; JWT identity paths (test_web_jwt_identity, test_web_identity pass).
10. **Dormant code, regressions only:** `/me/home`, `/me/profile`, `/me/security` render 200 with the store and flows off; test_web_customize and test_web_me_security pass.

## (d) Not tested, and why

- **Real request brokers:** the dev stack has no Seerr/Shelfarr/Omnibus mock; request flows were checked with the webtests' fakes and code only. Live Seerr search latency (F-03) and live ABS section timings (F-05) are unmeasured (no host access by brief).
- **Playback and the upstream apps after hand-off** (never claimed), TV clients, Quick Connect against a real Jellyfin.
- **Visual/responsive checks** (the #144 button overlap fix at phone width, rail focus): no browser pass in this audit; CSS presence only.
- **Expired-session and password-reset returns through the real Authentik outpost:** only the in-app paths and the sheet's full-load fallback were traced.
- **My profile tests:** `test_web_me_profile` needs Pillow, absent from `.venv-media`; feature dormant.
- **Komga EPUB progress** (`komga.py:389-397`, page/pagesCount) for reflowable books: no EPUB fixture in the mocks.
