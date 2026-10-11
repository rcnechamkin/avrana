# Avrana as a service: the member experience plan

Status: **agreed direction, 2026-10-11.** Nothing here is built or deployed yet. Each milestone ships
as its own PRs, and every change to a running service needs the owner's approval for that change
(`AGENTS.md`). Companion documents: [the design system](DESIGN.md) and
[the 2026-10-11 interface audit](../audits/2026-10-11-web-interface-audit.md).

## Goal

Avrana should feel like a genuine service to the people who use it: one address, one account, one
place to find, request and continue things, with the polish and the follow-through people expect
from something they would pay for. The audience is small and stays small: 3 to 5 regular members
today, up to about 20 accounts in theory, a few dozen at most ever. One person maintains it.

Those two facts set the rules for every decision below:

- **The bar is quality, not scale.** Nothing is built for load that will never arrive. Everything
  members touch is finished: states covered, copy written, help available, failures explained.
- **Maintenance is the scarce resource.** Every component must earn its upkeep through every
  Jellyfin, Audiobookshelf and Komga upgrade. When in doubt, use what an upstream app already does
  well and put the Avrana frame around it.

## The model: Avrana owns the front of house, the apps own the media

```
                 members (browser, phone home screen)          native apps, TVs
                                │                                      │
                       avrana.net (Avrana)                    watch. listen. read.
     home · search · title pages · requests · account · help   (unchanged hostnames)
                                │                                      │
            server side only: per-service adapters, cache              │
                                │                                      │
   Jellyfin   Audiobookshelf   Komga   Calibre-Web   Seerr   Shelfarr   Omnibus
```

- **Avrana's own site** handles finding things, requesting things, picking up where you left off,
  your account, and help. It is the evolution of today's portal, at the same address, behind the same
  Authentik gate.
- **The upstream applications** keep doing what they are good at: playing video, playing audio,
  reading. Pressing Play or Read hands off to the right app. Native apps and TVs keep using the
  per-service hostnames and never pass through Avrana.
- **No upstream application is modified.** Avrana talks to each one through its public API.
  Configurable apps are themed only through hooks they support (Authentik brand CSS, Jellyfin
  branding). Nothing is injected through the proxy, and Jellyfin's database is never touched.

## The service standard

What a member can count on once this plan is complete. Each line is testable, and each milestone
below says which lines it delivers.

| # | Promise | Today |
|---|---|---|
| S1 | **One address.** Everything starts at avrana.net, on any device, and it installs to a phone's home screen like an app | Portal exists; not installable |
| S2 | **One account.** One username and password (or passkey) for everything on the web; TVs pair with a code instead of typing a password | Separate logins for Jellyfin, Seerr and Calibre-Web |
| S3 | **Invite to first play in ten minutes.** An invite email, a sign-up page, a welcome page that says what is available and which app to install, and it works the first time | Enrollment works; the emailed link has never been tested end to end in a browser |
| S4 | **Pick up where you left off.** The home page shows what you were watching and listening to, and what is new in the libraries you can use | No |
| S5 | **One search, one request button.** Search every library at once; if something is missing, ask for it from the same page | Four separate apps and three request services |
| S6 | **Requests are followed through.** You can see the status of what you asked for, and you are told when it arrives | Seerr notifies on its own terms; Shelfarr and Omnibus vary |
| S7 | **Help for every device.** Plain setup steps for every supported app and television, and a way to ask a person | Help pages exist; no contact route |
| S8 | **It looks and behaves like one product.** One visual language, accessible to WCAG 2.2 AA, fast on a phone | Strong identity; accessibility gaps listed in the audit |
| S9 | **It is there when you want it, and you are told when it is not.** Planned work is announced on the home page; an outage of one library does not break the others | No notices; no degradation design |
| S10 | **Your data is safe and your privacy is respected.** Libraries, progress and accounts are backed up off the host; a short page says what is recorded (playback history, requests) and who can see it; you can leave and have your account removed | Off-host backups run nightly to B2; no privacy or house-rules page; no offboarding procedure |

## Milestones

Ordered by member impact per unit of upkeep. M0 and M1 change almost nothing about the
architecture and deliver most of the "real service" feeling for a group this size.

### M0. Foundations members never see but always feel

Already tracked in [`docs/ROADMAP.md`](../ROADMAP.md); listed here because the service standard
depends on them. No new work, only sequencing.

- **Email delivery** (ROADMAP: rotate the SMTP2GO password, run the alert script). Invites,
  password resets and every notification in M4 depend on it. **Blocking for S3 and S6.**
- **`akadmin` MFA** and the Authentik proposals P1 to P6. The account system is the service.
- **Seerr CSRF protection and proxy trust** (A20).
- **Off-host backup verification** (`offhost-verify-secrets.sh`, the B2 download cap).

Delivers part of S10.

### M1. Finish what exists

No new service. PRs against the portal, the Kindle and Audible connectors, Authentik's brand and
Homepage.

1. **Design system phase 1 and 2** from the audit: contrast, focus rings, announced status messages,
   no self-reloading pages, the shared stylesheet with a drift test, one wordmark.
2. **Invite path, tested and finished.** Run one real invite end to end in a private browser window
   and fix what it finds. Add a **welcome page** on avrana.net for a member's first visit: what they
   have access to, the one app to install per device, where help is.
3. **Installable site.** A web app manifest, Avrana icons and a theme colour, so avrana.net can be
   added to a phone's home screen and opens without browser chrome.
4. **Help, completed.** A topic headline and device jump links on every help page; a "Contact" route
   (an email address or a simple form that emails the owner); a **House rules and privacy** page
   covering what is recorded and how to leave.
5. **Notices.** A one-line banner on avrana.net the owner can set from OliveTin (planned maintenance,
   a library that is down), so members hear about problems from Avrana first.
6. **Operator side tidy-up.** Homepage regrouped by pipeline, stale tiles removed, missing operator
   links added (audit finding A4). An **offboarding runbook**: disable in Authentik, remove the
   replicated Jellyfin, Komga and Calibre-Web accounts, remove the Kindle entries, confirm.

Delivers S3, S7, S8, S10 and half of S1 and S9.

**Owner approvals:** each container rebuild; the Authentik brand CSS change; the OliveTin action.

### M2. One account

1. **Decide Jellyfin single sign-on.** The candidate is the upstream SSO plugin
   (9p4/jellyfin-plugin-sso) against Authentik, with Quick Connect for televisions. Before any
   install: confirm plugin compatibility with the running Jellyfin version, test every client in use
   (web, Swiftfin, Jellyfin for Android and Android TV, Roku, Fire TV), and keep the existing
   password login working as the fallback. Installing a plugin is a Jellyfin change: owner approval,
   backup first, no database edits.
2. **Seerr sign-in disappears for web members** once M3 files requests through Avrana. Seerr stays
   available for the owner and for Pocket for Seerr users.
3. **Help pages updated** to one sign-in story per device.

If the plugin fails the client test, the fallback is explicit: keep the Jellyfin password, which
enrollment already replicates, and say so plainly in the welcome page and help. Delivers S2, or
documents why it is partial.

### M3. Avrana home

The portal grows into the member home. Same service name, same hostname, same Authentik outpost
gate, same routes (`/watch`, `/listen`, `/read`, `/request`, `/help`, `/account` keep working).

**Features, in build order:**

1. **Continue:** in-progress items from Jellyfin and Audiobookshelf for the signed-in member, each
   opening the right app at the right item.
2. **New for you:** recently added items across every library the member can use.
3. **Search:** one box across Jellyfin, Audiobookshelf, Komga and the Calibre-Web catalogue. Results
   show where each item lives and offer **Open** or, if it is missing, **Request**.
4. **Title pages:** artwork, description, which library has it, Open in the right app.
5. **My requests:** status of the member's requests across Seerr, Shelfarr and Omnibus, with
   requesting filed through Avrana where the service supports acting for a member (Seerr's API user
   header, to be verified; Shelfarr and Omnibus to be investigated before committing).

**Architecture:**

- **Stack.** Python with FastAPI and Jinja templates, server-rendered with a small amount of
  JavaScript. This matches the Audible connector, so the same patterns, tests and deployment shape
  apply. No front-end build step.
- **Server-side adapters.** One adapter per service, holding that service's key. The browser never
  sees a service credential. Read-only keys wherever a service offers them.
- **Identity mapping.** The Authentik username from the outpost headers maps to each service's user,
  the same way the Kindle connector already maps to Calibre-Web and Audiobookshelf.
- **Authorization in Avrana, tested.** Avrana now decides what each member can see from every
  service, so the group rules are enforced on every adapter call, with the same 404-not-403 rule
  and an offline test per rule. This is the highest-risk part of the plan and is built first.
- **Degradation.** Each home-page section loads independently with a short timeout. A slow or down
  service greys out its own section and its search results, never the page.
- **Cache, not an index, to start.** A small SQLite cache with short lifetimes. A full search index is
  added only if live search measures slow against the real libraries.
- **Artwork.** Fetched through each API, resized and cached by Avrana, so pages stay fast and
  consistent on a phone.
- **Mock services.** Every adapter has a mock with recorded responses, as the Audible connector has a
  mock companion, so the site is built, tested and screenshotted without touching production.
- **Contract tests.** The recorded responses double as API contract tests, run before any upgrade of
  Jellyfin, Audiobookshelf, Komga or Seerr.

Delivers S4, S5, the rest of S1 and S9, and most of S6. Passes the service deployment checklist
(`docs/service-deployment-checklist.md`) before it replaces the current portal.

### M4. Follow-through

1. **"Your request is ready."** When a requested item arrives, the member gets one email and an
   entry on the home page, whichever service fulfilled it.
2. **Weekly "New on Avrana".** One short email per member, listing only what arrived in libraries
   they can use, in the house style. Opt-out on the account page.
3. **Account page, completed:** notification preferences, connected Kindle address, linked Audible
   contribution status, a link to manage password and passkeys in Authentik.

Delivers the rest of S6. Depends on M0 email delivery.

### M5. Only if usage says so

Decided from evidence (Tracearr for viewing, Audiobookshelf listening stats, and simply asking
members), not built speculatively:

- An **audiobook player inside Avrana** using Audiobookshelf's playback sessions, if listening is a
  main use.
- A **comic and ebook reader inside Avrana** using Komga page images and the ebook files, if reading
  in the browser is common.
- **Jellyfin branding** (splash, login message, custom CSS) to make the video hand-off feel continuous.

## Not doing

- A custom video player. Jellyfin's apps and web player stay the way video is played.
- Custom television or native phone apps.
- Embedding upstream apps in frames or serving them under avrana.net paths.
- Theming upstream apps by injecting CSS or patching their code.
- A public status page or a separate staging host. Mock services cover development; notices cover
  outages.

## How success is judged

Checked at the end of each milestone, with the members themselves where it matters:

- A new member goes from invite email to playing something in under ten minutes, without help.
- Every member can say where to go for anything: avrana.net.
- Support questions to the owner go down, not up.
- Weekly active members (from Tracearr and Audiobookshelf), as a direction rather than a target.
- The upkeep check: an upstream upgrade costs no more than a contract-test run and at most an hour of
  adapter fixes.

## Decisions for the owner

1. Approve this plan as the direction (merging this PR).
2. Contact route for S7: an email address, or a form that emails the owner.
3. Whether to pursue Jellyfin single sign-on (M2), accepting the client testing it needs.
4. Whether request filing moves into Avrana (M3.5) or stays as links to each request service.
5. Which signals decide M5: a short member survey, the usage stats, or both.

## Sequencing summary

| Milestone | Depends on | Roughly | Production changes |
|---|---|---|---|
| M0 | Owner steps in ROADMAP | Owner time | Credentials, Authentik, Seerr settings |
| M1 | M0 email for the invite test | 2 to 4 weeks | Rebuilds of three custom containers; Authentik CSS; Homepage; one OliveTin action |
| M2 | Owner decision | 1 to 2 weeks plus client testing | Jellyfin plugin, if approved |
| M3 | M1 shared stylesheet | 4 to 8 weeks | Portal replaced by the new app, behind the same gate |
| M4 | M0 email, M3 | 2 to 3 weeks | The new app only |
| M5 | Evidence | Per item | Per item |
