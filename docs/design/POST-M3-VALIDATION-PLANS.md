# Post-M3 validation plans

> **Planning only — direction, not implementation approval. Nothing here authorises a persistent store,
> production request writes, notification service, video transport or device control.**

Status: proposed, 2026-10-26. Sources: the owner's
[Personal Experience Specification v0.1](https://linear.app/avranakern/document/avrana-media-personal-experience-specification-v01-five-round-a205d2d2dcfe)
("the spec"), [`MEDIA-2.0.md`](MEDIA-2.0.md) M4/M5, [`DECISIONS.md`](../DECISIONS.md),
[`ADAPTER-CONTRACT.md`](ADAPTER-CONTRACT.md), the R1 audit appendices on PR #75 (`requests.md`, `jellyfin.md`,
not on main) and Linear AVR-750 to AVR-755, AVR-390, AVR-393, AVR-724 and AVR-726. M3 scope, the approved
Concept K shell (Home · Library · Search · Me, #EADA6E) and every gate in `AGENTS.md` are unchanged. This
document does not track state; it says what evidence would justify each next step.

## What exists on main today (2026-10-26, `99f0d7c`)

- **Jellyfin**: read-only, allow-listed GETs only (`services/avrana-home/avrana_home/adapters/jellyfin.py`,
  `ALLOWED_ROUTES`): `/Users`, `/UserItems/Resume`, `/Items/Latest`, `/Items` (ids, search) and
  `/Items/{id}/Images/Primary`, each user-scoped by `userId`. No `/Sessions`, `/Shows/NextUp`, playback or
  write route. Hand-off is a link to `/web/#/details?id={id}` (`avrana_home/contract.py`).
- **Seerr**: **no adapter.** Requests are hand-off links only: `REQUEST_FOR`, `REQUEST_SEARCH` and
  `request_options()` in `avrana_home/app/viewmodel.py` build `https://<seerr>/search?query=<term>` (route
  unverified live). Nothing reads request state. No Radarr, Sonarr or SABnzbd code exists.
- **Browser surface**: CSP `default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'none'`
  with no script source (`avrana_home/app/middleware.py`); manifest and icons but **no service worker**
  (`avrana_home/app/install.py`).
- **Storage**: one disposable SQLite cache; member-keyed data stays in memory unless the owner decides
  otherwise (`avrana_home/cache.py`). No system of record exists or is approved.
- **Hero**: none on main. The Concept K integration branch (#74, unmerged) has a hero that picks the first
  Continue item (`HERO_APP`/`HERO_VERB` in its `viewmodel.py`); that remains the approved M3 hero.

## 1. Curated Home hero (AVR-750)

- **Owner outcome.** An owner-pinned, available title leads Home; with no usable pin, a deterministic
  authorised fallback; Continue immediately beneath.
- **Spec constraints.** Available titles only, never Requestable or Upcoming; no new tab; no nav change; one
  static slot, no autoplay; no owner curation chore; reduced-motion and JS-off parity; owner visual sign-off
  before any behavioural merge.
- **Exists today.** #74 hero (first Continue item); `_visible_item` re-checks visibility per member before
  artwork (`adapters/jellyfin.py`), which a pinned title must reuse.
- **Unknowns.** Where a pin lives: options are an env/settings value read at start (`app/settings.py`), a
  file in Git, or an OliveTin action (like operator notices). Each is an owner decision; **no new DB**. What
  "deterministic" fallback keys on (most recent `/Items/Latest` by date, then id) and whether it may differ
  per member (it must, since libraries differ). TV viewing-distance layout has no device evidence yet.
- **Safe next step.** Fixture-only view-model function `hero_for(member, pin, sections)` with tests:
  pin visible, pin removed, pin out of entitlement (falls back with no pin metadata in the HTML), no pin,
  all empty; static before/after mock.
- **First gated step.** Choosing and adding the pin's persistence (settings key or operator action):
  *config/store decision*.
- **Validation.** Leak test that a restricted pin's title, artwork URL and id appear nowhere in member B's
  page; determinism test (same inputs, same pick); axe at 390/1280 px; no-JS and reduced-motion renders;
  owner iPhone Safari and TV-browser check.
- **Order.** After #74 merges; independent of everything below.

## 2. In-app video playback spike (AVR-751)

- **Owner outcome.** Know whether a proven Jellyfin-compatible web player can play inside the Avrana PWA
  without a new transcoder and without breaking existing hand-offs.
- **Spec constraints.** Existing player, not a codec stack; subtitles; session/auth/streaming/CSP and
  performance proofs; no privileged token in the client; bulk streams evaluated separately from the
  Cloudflare tunnel; fallback to the current hand-off when unsupported.
- **Exists today.** Nothing: hand-off link only (`contract.py`); CSP forbids script and media sources.
- **Unknowns.** jellyfin-web is GPL-2.0 and hash-routed; its player is not a published standalone component
  (R1 `jellyfin.md` §1, §4), so reuse may mean embedding the whole client (forbidden: no frames) or a GPL
  licence obligation. Browser stream auth needs a member Jellyfin token (Quick Connect or password; R1 §7),
  which conflicts with "no privileged tokens in the client" unless tokens are member-scoped and short-lived.
  iOS Safari HLS, direct-play limits and subtitle burn-in are unmeasured. Tunnel bandwidth terms for video
  are unknown.
- **Safe next step.** Desk study and ranked go/no-go doc: candidate players with commit, licence and assets;
  threat model (token theft, cross-member stream id guessing, CSRF on progress reports); device matrix plan.
- **First gated step.** Any CSP change (`media-src`, `script-src`), any member-token issuance, or a
  synthetic-media proof against a real Jellyfin: *CSP change + live capture + video transport*.
- **Validation.** Licence review sign-off; threat-model items each mapped to a test; synthetic-media playback
  on iPhone Safari (installed PWA and tab), desktop and the chosen TV browser; fallback rendered when
  unsupported; progress reported only for the signed-in member.
- **Order.** Research any time after M3; implementation only after the owner's go.

## 3. Native movie/TV requests and My Requests (AVR-390 → AVR-393, AVR-726)

- **Owner outcome.** Request a movie or TV season inside Avrana with explicit confirmation, then see a
  private, truthful timeline on the title page and in My Requests.
- **Spec constraints.** Server-side broker only; never the Seerr key in the browser. Stages: Requested,
  Approved, Waiting, Downloading, Preparing, Partially available, Available, plus declined, failed,
  unknown. SABnzbd % and ETA **only** for a job provably correlated through Radarr/Sonarr to this member's
  request, else "status unavailable" (never 0 % or an invented ETA). Download complete ≠ playable:
  **Available comes only from a member-playable Jellyfin import.** TV: one event when the first requested
  episode is playable, labelled Partially available until the requested set is complete. Books, comics and
  audiobooks stay hand-offs.
- **Exists today.** Hand-off links only (`viewmodel.py` `request_options`). No Seerr, arr or SABnzbd code.
- **Key fact (R1 `requests.md` §1).** Seerr's one global API key has no scopes; with `X-API-User` it acts as
  *any* Seerr user, without it as user 1 (admin). The broker must therefore be the trust boundary:
  - server-side map `{avrana member → seerrUserId}` from the verified principal, never from the client;
    refuse any mapped id holding ADMIN or MANAGE_* permissions; always send `X-API-User`;
  - allow-list exactly `GET /search`, `GET /movie/{id}`, `GET /tv/{id}[/season/{n}]`, `GET /request`
    (own), `POST /request` without `userId`; never `/settings/*`, `/user/*/settings/permissions` or
    `/request/{id}/{status}`;
  - CSRF-protected POST after an explicit confirmation page; idempotency key per (member, tmdbId, seasons);
    check existing `mediaInfo.requests` before writing; no automatic retry of a write; one audit line per
    attempt (member hash, title id, outcome class), no titles in general logs; rate limit per member.
- **Unknowns.** Deployed Seerr version and whether it already rejects duplicates; whether Seerr's CSRF and
  proxy-trust settings (M0 item A20) are applied; how members map to Seerr ids (via
  `GET /user/jellyfin/{id}`, which returns full fields only to managers); whether Radarr/Sonarr queue
  `downloadId` reliably equals the SABnzbd job id; Jellyfin scan latency after import; TMDB vs TVDB ids for
  episodes; whether status needs polling (Seerr webhooks would be a new inbound endpoint).
- **Safe next step.** Feasibility matrix (AVR-390) plus a fake Seerr/Radarr/Sonarr/SABnzbd and fixture
  contract tests for the broker and the stage mapper, including uncorrelated jobs and partial seasons.
- **First gated step.** A read-only recorded contract capture from the real Seerr (*live capture*), then,
  separately, the first real `POST /request` (*write API*), then any stored request/audit history (*store*).
- **Validation.** Tests: client-supplied user id ignored; admin-mapped member refused; missing
  `X-API-User` impossible; route outside allow-list refused; double-submit creates one request; timeout
  shows "status unavailable"; member A never sees B's requests or queue; SABnzbd values shown only with a
  correlation proof. Threat model: impersonation escalation, CSRF, replay, SSRF, key leakage, log leakage.
  Fallback: the existing Seerr hand-off on any failure.
- **Order.** AVR-390 go/no-go → AVR-393 broker (read status first, writes second) → AVR-726 UI.

## 4. Availability inbox and Web Push (AVR-752)

- **Owner outcome.** An in-app inbox that works with push off; opt-in push only when a requested or
  followed title first becomes verifiably playable.
- **Spec constraints.** Recipients: the requester (follows by default, opt-out) and explicit eligible
  followers only. No push for approval, download % or ETA; no calendar push. Dedupe across provider
  retries; entitlement re-checked at delivery and at click; per-device preview privacy (full title only by
  member choice). iOS: push needs a Home Screen install, permission from a user gesture, HTTPS and a service
  worker.
- **Exists today.** Nothing. No service worker, no script, no store, no e-mail path from Home.
- **Unknowns.** Event source: Jellyfin library change detection without a webhook plugin (polling `Latest`
  per follower is expensive); where follows, read state and push subscriptions would live (a *store*); VAPID
  key custody (`docs/SECRETS.md`); outbound push to Apple/Google endpoints from the host; retention and
  export/deletion policy (AVR-481).
- **Safe next step.** State-model doc and pure-function fixtures: event dedupe key (member, title,
  first-playable), follower eligibility, entitlement re-check, inbox rendering without JS.
- **First gated step.** A persistent store for follows/inbox (*store*); later, a service worker and VAPID
  push sender (*CSP change + push service*).
- **Validation.** Synthetic tests: cross-member isolation, offline, push denied, subscription revoked,
  duplicate provider events, entitlement lost before click (generic copy, no title). Device checks: iPhone
  installed PWA permission flow, Android Chrome, desktop.
- **Order.** Needs section 3's "Available" signal; inbox before push.

## 5. Personal release calendar (AVR-753)

- **Owner outcome.** Track or untrack an upcoming title and see it in My Calendar, with no acquisition side
  effect and no push.
- **Spec constraints.** Digital movie releases (region-specific, never derived from theatrical) and scheduled
  TV episodes first; TBA when unknown; record date kind, territory, source, provenance, last-checked and
  confidence; "official" only with primary-source evidence; release date ≠ available. Agenda-first, under
  Search → Releases / My Calendar; the four tabs stay.
- **Exists today.** Nothing.
- **Unknowns.** Radarr `/calendar` is believed (unverified) to carry digital, physical and cinema dates,
  but only for monitored titles, and each arr key is full admin (R1 §5); unmonitored titles need TMDB or similar, which needs a
  rights/terms/cost/territory review; time zones for episode air dates; where tracking persists.
- **Safe next step.** Fixture model and static agenda mock with tests for changed, conflicting, corrected and
  TBA dates, manual untrack, and no notification emitted.
- **First gated step.** Read-only arr calendar capture (*live capture*, plus a new admin-key custody
  decision); persisting tracked titles (*store*); any external metadata API (*rights review*).
- **Validation.** Provenance shown on every date; no theatrical-to-digital inference test; member B never
  sees A's tracked list; JS-off and VoiceOver agenda.
- **Order.** Independent of requests; after section 3 if it shares arr plumbing.

## 6. Phone-to-TV (AVR-754, AVR-724)

- **Owner outcome.** Eventually pick an authorised TV session from the phone and start, pause, seek and stop
  real playback. AVR-724's read-only "Playing on a TV" label is a separate, unapproved concept.
- **Spec constraints.** Phone hand-off is not TV control; only verified supported clients; unsupported
  controls disabled or replaced by a link; no arbitrary device takeover. Much later.
- **Exists today.** Nothing; `/Sessions` is not in `ALLOWED_ROUTES`.
- **Unknowns.** Jellyfin `/Sessions` and `/Sessions/{id}/Playing|Command` (not source-checked here) called
  with an API key run as Administrator (R1 `jellyfin.md` §2) and would presumably list every member's
  devices, so filtering by user is Avrana's job; which TV clients (Jellyfin Android TV, Wholphin, Swiftfin tvOS) declare `SupportsRemoteControl` in shipped releases;
  pairing and expiry; shared household accounts; 10.11 vs 12.x differences (no upgrade authorised, Q1).
- **Safe next step.** Source-verified feasibility matrix and a mock journey with an honest no-TV fallback.
- **First gated step.** Adding any `/Sessions` route, even read-only (*live capture + privacy review*); any
  command route (*device control*).
- **Validation.** Session list test shows only the member's own sessions; command refused for another
  member's session; device checks on each candidate TV client.
- **Order.** Last; after section 2.

Deferred, one line: AVR-755 Letterboxd/Goodreads interoperability (M5) and AVR-749 social are out of scope
here.

## Recommended order

1. AVR-390 feasibility matrix and fake-Seerr broker tests (research, no approval needed).
2. AVR-750 hero fixtures and mock, after #74 merges.
3. AVR-393/726 read-only request status, then gated writes.
4. AVR-752 inbox (needs a store), then push.
5. AVR-753 calendar fixtures in parallel with 3 and 4.
6. AVR-751 player go/no-go; AVR-754/724 last.

## Owner decisions needed

| # | Decision | Unblocks |
|---|---|---|
| P-1 | Where a hero pin lives (settings value, Git file or OliveTin action; no DB) | Section 1 |
| P-2 | Approve a read-only Seerr contract capture, then the broker design, then a first real write | Section 3 |
| P-3 | Whether Avrana may hold Radarr/Sonarr/SABnzbd keys (full admin each) for correlation and calendars | Sections 3, 5 |
| P-4 | A persistent store for follows, inbox, tracking and request audit, with retention and deletion rules | Sections 3 to 5 |
| P-5 | A service worker, VAPID keys and outbound push (CSP change) | Section 4 |
| P-6 | Player licence and CSP direction after the AVR-751 go/no-go | Section 2 |
