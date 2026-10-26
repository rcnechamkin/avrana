# Concept K on Home: what was built, what was not, and what comes next

> **Status: written 2026-10-26 for MK-7 (AVR-721), against the integration branch
> `feat/avr-713-concept-k-integration` (MK-1, MK-2, MK-3, MK-4, MK-5a, MK-5b merged; MK-6 motion in progress).**
> Nothing here is merged to `main`, deployed, or tested on a phone. The standard itself is in
> [DESIGN.md](DESIGN.md), section "Concept K · Avrana Console"; the owner decisions are in
> [DECISIONS.md](../DECISIONS.md) (2026-10-25 and 2026-10-26). The follow-ups below are drafts for Linear issues;
> none has been filed yet.

Figma file: "Avrana Media — Console" (`OggTUO1p24pNYFI6iVlLWL`), page **Media Console**. Frame IDs are the
memo's section 11 map. PRs are in `rcnechamkin/avrana`: MK-1 #67, MK-2 #68, MK-3 #66, MK-4 #69, MK-5a #70,
MK-5b #71 (all drafts).

## 1. Actual vs Proposal, frame by frame

**Built** means the page or state exists and matches the frame's structure, apart from differences the data
forces. **Partly built** names what is missing. **Not built** says why. A frame labelled Proposal in Figma is never
built until its data exists.

### Home · adaptive lifecycle

| Frame | Figma label | State | Where, and why |
|---|---|---|---|
| Continue `14:3` | Actual | Built | MK-4 #69 hero (first Continue item, yellow eyebrow and signal bar, one Cream hand-off) and rails; MK-2 #68 tab bar. The places bar from `45:2962` sits above it (D16) |
| Inline preview `14:145` | Mixed | Not built | Needs the page script; MK-3 #66 shipped the script without it, and MK-4 kept the card a plain link to where the item opens (the no-script baseline). The title page is reached by the hero's Details link |
| Nothing in progress `14:254` | Actual | Built | MK-4 #69 (H0: the first Recently added item is the hero, Stone eyebrow, no bar) |
| Opening Jellyfin `15:248` | Mixed | Not built | The "Opening…" label needs script; the hand-off is a plain link and never claims that anything plays (AVR-384) |
| Movies and TV unavailable `15:336` | Actual | Partly built | Behaviour built before Concept K (one notice, struck place linking to `/help/trouble#unavailable`, Try again); MK-4 keeps a down library from supplying the hero. The notice is still the older ruled `.banner`, not the Concept K warning (glyph, amber edge) that Library and Search use. Follow-up F-13 |
| No library yet `15:698` | Actual | Partly built | The block exists with today's copy ("No library is shared with this account yet. …"); the frame's new body copy waits for the owner's wording (memo section 4) |
| Backdrop `15:449` | Proposal | Not built | Needs Jellyfin Backdrop/Thumb art at 1170 px or more, which `/art` does not allow today (D6). Follow-up F-1 |
| Playing on a TV `15:531` | Proposal | Not built | No adapter reads sessions, devices or presence. Follow-up F-3 |
| Just finished `15:614` | Proposal | Not built | Finished items drop out of Continue; no adapter reads NextUp or a series sequence. Follow-up F-2 |

### Library · Search · Title

| Frame | Figma label | State | Where, and why |
|---|---|---|---|
| Library All `17:1851` | Actual | Partly built | MK-5a #70 `/library`: chips, one shelf per library from what Home already gathers (at most four), "Open <app>". The filter and sort control is not built: there is no honest order without new data. Library shows recently added items only, not the member's in-progress items. Follow-up F-8 |
| Movies and TV `17:1996` | Actual | Built | MK-5a #70 (`?lib=jellyfin`): the chosen chip has the yellow tint, rim and check. Chips wrap instead of scrolling sideways, so the chosen chip is never off screen without script |
| Comics unavailable `17:2103` | Actual | Built | MK-5a #70 warning (glyph, words, amber edge, Try again), chip struck through, no items |
| Nothing recently added `17:2241` | Actual | Built | MK-5a #70, one panel "Nothing recently added." |
| Title Film `19:1748` | Actual | Partly built | MK-5a #70 restyle (art twice, display title, Cream action, "Opens in" panel). Not built: the frame's "Continue" eyebrow, the "Resume in Jellyfin" label and the Library/Remaining/Opens-in detail panel, because they change the page's copy and accessible name. Owner question Q1 |
| Title Audiobook `19:1846` | Actual | Partly built | As the film title |
| Search empty `19:1943` | Actual | Built | MK-5b #71 |
| Search results `19:1996` | Actual | Built | MK-5b #71 (one panel per library) |
| Search no results `19:2083` | Actual | Built | MK-5b #71 ("Ask for it": the member's own request routes, each "Opens the request website"; Contribute only when the member has it). Owner questions Q4 and Q5 |
| Search library unavailable `19:2181` | Actual | Built | MK-5b #71 warning panel |

### Requests · Me · System

| Frame | Figma label | State | Where, and why |
|---|---|---|---|
| Requests `17:619` | Actual | Built (as a place page) | MK-5b #71 `/request`: "Ask for something" rows, "Add to the library" with Contribute. Under tab option B (D1) it is a place page with the Home button, not a tab |
| Your requests `17:741` | Proposal | Not built | No adapter reads request status. Follow-up F-5 |
| Me `17:872` | Actual | Partly built | MK-5b #71 `/me`: initial, name with the ADMIN tag beside it for admins, "Signed in as", Account, Help, "If something doesn't open", Operations for admins, Sign out through `/signout`. Not built: the avatar image (Authentik gives Home none) and the "This phone · Install" row. Follow-ups F-7, F-10; owner question Q3 |
| Install hint `17:1404` | Mixed | Not built | No install help is served by Home yet (the draft is `docs/member/help/home-screen.md`, not wired). Follow-up F-10 |
| Account `17:1583` | Actual | Built | MK-5b #71 (grouped panels, eyebrow headings, Manage account and Sign out rows) |
| Help `17:1698` | Actual | Built | MK-5b #71 (topic rows, platform panels) |
| Offline `17:2329` | Actual | Built | MK-3 #66 `/offline` (lockup, one sentence, Try again; same bytes for everyone) |
| Libraries resting `17:2366` | Actual | Partly built | The "Your libraries are resting" block predates Concept K (polish pass, 2026-10-16) and wears the MK-1 tokens; it was not restyled to the frame |
| Update available `17:2431` | Actual | Built | MK-3 #66 banner (script) with MK-2 #68 styles: an opaque panel above the tab bar, one Cream Reload button |
| Session ended `17:2513` | Mixed | Not built | Nothing detects an expired session: the outpost redirects first, and D13 says no heartbeat. Follow-up F-6 |
| Authentik placeholder `18:1676` | n/a | Not Home's | Authentik's own sign-in page; Home serves nothing there |
| Back home `18:1699` | Mixed | Not built | Depends on the session-ended screen (F-6) |
| Signing out `18:1769` | Mixed | Partly built | MK-3 #66 `/signout` is a 303 with `Clear-Site-Data`, not a "Signing you out" page; the browser goes straight on to the outpost sign-out. A 200 page with a refresh is the fallback if a device test shows the header ignored on a redirect |

### Media yellow candidates · tab option B · docs-aligned · responsive

| Frame | State | Where, and why |
|---|---|---|
| Home in each yellow mode, swatch cards | Decided | D2 picked Butter-High `#EADA6E`; MK-1 #67 applies it |
| Warn-shift card `20:2416` | Not applied | D3 chose the console warn `#F59E0B` instead of shifting warn to `#EA7A12` |
| Tab option B `20:2460` | Built | MK-2 #68 (Home · Library · Search · Me) |
| Docs-aligned proposal `45:2962` | Built | MK-2 #68 (places bar, L3 lockup, tab option B) with the MK-4 #69 hero. The bar is catalogue-driven: members with Contribute or Operations get those chips too, so the one-row-at-390px result holds for the five-place case |
| Home 320 × 568 `22:2597` | Built | MK-4 #69 (no poster below 360 px; the backdrop stays as the stage) |
| Library 320 × 568 `22:2680` | Built | MK-5a #70 |
| Home 430 × 932 `22:2782`, Library 430 × 932 `22:2893` | Built | MK-4 #69, MK-5a #70 |
| Home at 130 % text `22:3017` | Built | Checked in Chromium up to 200 % text (MK-2 tab labels, MK-4 hero, MK-5 pages); not on a phone |

Header frames (summary, chip legend, flows, assessment) are notes, not product.

## 2. Follow-up issues (drafts; the lead files them in Linear)

Each names what it needs before it can start. None of these is approved work.

- **F-1 Backdrop allow-list for an edge-to-edge hero (D6).** Allow Jellyfin `Backdrop` or `Thumb` at 1170 px or
  wider through the member-scoped `/art` route, then offer the Proposal frame `15:449`. Needs its own security review
  (new upstream image types through the gateway; isolation and revocation suites extended), and a decision on what
  audiobooks and comics show, since they have no backdrop.
- **F-2 NextUp ("Just finished", K3).** Read Jellyfin `/Shows/NextUp` for the member, the Audiobookshelf series
  sequence and the Komga next book, so a finished item can offer the next one (frame `15:614`). New adapter calls
  and contract fields; each upstream read verified against the real service (REAL-SERVICES-PATH.md).
- **F-3 Sessions, "Playing on a TV" (K2).** Read Jellyfin `/Sessions` for the member only (frame `15:531`). Needs a
  contract field, a privacy review (another device's activity on a shared account), and copy that never claims Home
  controls the TV.
- **F-4 "For you".** Jellyfin suggestions for the member, shown in Stone, never yellow, never looking like
  Continue (memo section 3). Needs the adapter call and an owner view on whether recommendations belong on Home.
- **F-5 Request statuses ("Your requests", frame `17:741`).** Read request state from Seerr and the book and comic
  request services for the member only. M3 put request status out of scope (DECISIONS.md 2026-10-11), so this needs
  an owner decision first.
- **F-6 Session heartbeat and the "Session ended" screen.** D13 says none now. Revisit only after the AVR-585 device
  test shows how an installed iPhone app behaves when the Authentik session ends. If needed: an optional script
  fetch on `visibilitychange` (adds `connect-src 'self'` to shell pages, a CSP change needing review) or the no-code
  Help text "open Safari, sign in, then reopen the app".
- **F-7 Square or circle monogram.** AVR-478 asked for a square monogram identity trigger; Concept K's Me tab and hub
  use a circle (memo section 1a). Owner to choose; today's build keeps the circle.
- **F-8 Library includes in-progress items.** `/library` shows only what Home gathers as recently added, so a
  member with an audiobook in progress can read "Nothing recently added in Audiobooks" there (MK-5a risk). Either
  show the member's Continue items per library, or say where they are. Owner question Q2.
- **F-9 The title page's action names the app.** The Home hero says "Resume in Jellyfin"; the title page's button
  says only "Resume" (or Open, Watch, Listen, Read), with the accessible name "Resume <title> in Movies and TV"
  (member language). Pick one rule for both, with WCAG 2.5.3 (label in name) kept. Owner question Q1.
- **F-10 The install row on Me and the install hint.** Serve install help (the `home-screen` topic, wired from
  `docs/member/help/home-screen.md` once its steps are checked on real devices) and add "This phone · Install
  Avrana Media" on Me (frames `17:872`, `17:1404`): a `<details>` that works with JavaScript off, hidden in
  standalone mode with `@media (display-mode: standalone)`.
- **F-11 Oversized header identity test fails on Linux, also on `main`.**
  `webtests.test_web_identity` `test_oversized_header_block_is_refused_by_the_server_without_a_page` gets 200
  instead of 400 or 431 on Linux. Linux's event loop reads the 70 KB request in one piece, and h11 enforces its
  16 KiB header limit only on incomplete requests. Fails the same way on `main` 99f0d7c. Needs a limit that holds
  whatever the read size (for example a header-size check in the ASGI layer before identity), with the test kept as
  it is.
- **F-12 Intermittent `test_recovery_after_the_cool_off_needs_no_restart`.** `webtests.test_web_sections` failed in
  3 of 10 full-suite Linux runs (MK-2 and MK-3, also on `main`) and passes alone. The page still showed the library
  as down after the test reset the breaker, so it probably depends on test order or a shared clock. Find the shared
  state; do not loosen the assertion.
- **F-13 Home's outage notice and the Recently added tabs in the Concept K style.** Home's one-library-down notice
  is still the older ruled banner, while Library and Search use the warning (glyph, words, amber edge); the two
  warning blocks in `home.css` (MK-5a `.k-warn`, MK-5b `.kwarn`) also differ in radius. Home's Recently added tabs
  are still underlined text tabs, not chips. One warning component and chip tabs on Home, with the identity tests
  that read the banner and the tabs unchanged.
- **F-14 The hero repeats the first Continue card.** MK-4 kept the Continue rail whole so the rail's accessibility
  contract and its tests stay as they are. Owner to say whether the rail should start from the second item.
- **F-16 Check the house rules' "stores nothing" wording.** `docs/member/house-rules-and-privacy.md` says the home
  page "stores nothing about you and writes no per-visit log". That predates MK-7 and was written for the portal;
  check it against Home's logging (HOME-APP.md section 6) and its short per-member cache before it is published.
- **F-15 "Getting back to Avrana" help text.** `recovery.py` tells members to "choose AVRANA at the top of any Avrana
  page"; shell pages now show the Avrana Media lockup on Home and the Home button or Home tab elsewhere.

## 3. Questions for the owner

These are open. Nothing in the build answers them; each build choice above is the conservative one.

- **Q1 The title button naming the app, and which surfaces name the upstream app.** Should the title page's action
  name the upstream app ("Resume in Jellyfin"), as the Home hero does, or keep its short verb ("Resume") with the
  library in member language in its accessible name ("Resume <title> in Movies and TV"), as today? More broadly:
  today the app is named by the Home hero's hand-off, Library's "Open <app>" and "Browse everything in <app>", and
  the Watch interstitial's advice; cards, the title page and all other copy use member language. Is that the rule
  you want? (F-9)
- **Q2 Library showing in-progress items.** Should `/library` include the member's in-progress items, or stay
  "recently added" only? (F-8)
- **Q3 The ADMIN tag.** The tag on Me is derived from the catalogue's Operations gate (`authentik Admins`), the only
  role signal Home has. Keep it, or show no tag?
- **Q4 Request row wording.** Request and Search rows say "Opens the request website", not the product name (the
  product is Seerr; cards name libraries in member language). Keep?
- **Q5 Contribute in Search's no-results group.** Search's "Ask for it" group offers Contribute (adding your own
  Audible books) when the member has it, following memo section 2. Keep it there, or offer only requests?
- **Q6 The sign-out hop (D10) as built.** It shipped as a 303 redirect carrying `Clear-Site-Data: "cache",
  "storage"`, verified in Chromium only (Safari and Firefox unverified; plain http ignores the header), instead of
  the memo's 200 "Signing you out" page with a refresh. Accept the 303, or ask for the 200 page now rather than only
  if a device test shows the header ignored?
