# Avrana Media 2.0

Status: **approved direction, 2026-10-11** (owner decision recorded in [`DECISIONS.md`](../DECISIONS.md)).
Planning only: nothing in this document is built or deployed. Every production change still needs
the owner's approval for that specific change, with rollback material prepared first, exactly as
`AGENTS.md` and [`DEPLOYMENT.md`](../DEPLOYMENT.md) already require. Approval of this plan is not
approval of any step in it.

Companion documents: [design system](DESIGN.md) ·
[shared Design Foundation](foundation/README.md) and [its Media mapping](FOUNDATION-MAPPING.md) (proposed) ·
[2026-10-11 interface audit](../audits/2026-10-11-web-interface-audit.md) ·
[roadmap](../ROADMAP.md).

## 1. Charter

**What it is.** Avrana Media 2.0 is a product-experience milestone: a polished, cohesive media
service for about 15 members, with one address, one account, one place to discover, search and pick
up where you left off, and seamless hand-off to the playback apps members already use.

**What it is not.** It is not a backend rewrite, not an enterprise streaming platform, and not a
replacement for Jellyfin, Audiobookshelf, Komga or Calibre-Web. Those stay exactly as they are,
upgraded the same way, behind the same gates.

**Launch milestone: M3.** Media 2.0 launches when M3 meets the launch criteria in Section 8. M4 and
M5 are post-launch enhancements, taken on only when actual usage justifies them.

### Principles

1. **Security first.** The identity boundary is fixed and proven by tests before any member-facing
   feature reads data from a library on a member's behalf.
2. **Member experience over feature count.** Onboarding, discovery, search, Continue Watching and
   hand-off come first. Anything else waits for evidence.
3. **Operational maturity.** Every new component states how it degrades, how it fails, how it is
   recovered and how it is rolled back, before it is deployed.
4. **Scope discipline.** M3 ships in small slices, each useful on its own. Complex request
   integrations, custom players and speculative features are deferred.
5. **Validation by people and by machines.** Real members test the service before launch, alongside
   automated accessibility, security and API contract tests.
6. **Maintainability.** Upstream applications are preserved and unmodified. Custom infrastructure is
   kept to one small application. When an upstream app already does something well, link to it.

### Who it is for

| Audience | Size | Interfaces |
|---|---|---|
| Members | About 15 accounts; 3 to 5 regular today | avrana.net, the Authentik sign-in and account pages, the Kindle and Audible connectors, and the upstream member apps (Jellyfin, Audiobookshelf, Komga, Calibre-Web, the request services) |
| Operator | One (the owner) | Homepage, OliveTin, Beszel, Tracearr, the arr stack, SABnzbd, Mylar3, Authentik admin |

## 2. Member and operator separation

The two audiences get separate interfaces and never share one by accident.

- **Member interfaces are public and gated by Authentik group.** They show only what the member may
  use (the existing 404-not-403 rule) and speak in plain language. They never show host health,
  container names, queue internals, indexers, or anyone else's activity.
- **Operator interfaces are admin-only.** They are reachable on the LAN or through a public hostname
  gated on `authentik Admins` (OliveTin today). The one link from member space into operator space is
  the existing **Operations** tile, visible only to admins.
- **Status crosses the boundary in one direction only, in member language.** The operator sets a
  notice (for example "Audiobooks are offline this evening for maintenance") from OliveTin; members see
  that sentence on avrana.net. Raw health data never appears in member space.
- **Avrana's own application uses service credentials, not operator credentials.** It holds per-service
  API keys scoped as narrowly as each service allows, read-only wherever possible, stored like every
  other secret (`docs/SECRETS.md`). It has no Docker socket, no host access and no admin session.
- **Known gap, tracked:** Mylar3 has no login and ufw is not filtering (ROADMAP owner items A5 and the
  staged firewall). Neither is a Media 2.0 dependency, but both weaken the operator boundary.

## 3. Architecture

```
  members: browser, phone home screen                      native apps and TVs
                │                                                   │
   cloudflared ─ Authentik embedded outpost (signs in, gates)       │
                │  private network per backend (Gate G1)            │
          Avrana home (evolution of avrana-portal)          watch. listen. read. books.
   home · Continue · New · search · title · help · account   (unchanged hostnames, direct)
                │
     server-side adapters, read-only keys, short-lived cache
                │
   Jellyfin   Audiobookshelf   Komga   Calibre-Web (OPDS)   request services (links only)
```

- **One small application.** The Avrana home is the evolution of `avrana-portal`: same hostname, same
  outpost gate, same routes (`/watch`, `/listen`, `/read`, `/request`, `/help`, `/account` keep
  working). Python with FastAPI and Jinja, server-rendered with minimal JavaScript, matching the Audible
  connector's patterns and tests. No front-end build step, no separate search service, no message
  queue, no new database server.
- **Adapters.** One module per upstream service. Each holds that service's key, has a timeout, maps
  the Authentik username to the service's user, and returns only what the member may see.
- **Cache.** A small SQLite file in the container's own volume, holding catalogue metadata and resized
  artwork with short lifetimes. It is disposable: deleting it costs a slower first page, nothing else.
  A dedicated search index is added only if live search measures slow on the real libraries.
- **Hand-off.** Play and Read always open the upstream app at the right item. No media bytes pass
  through Avrana.
- **No upstream modification.** Avrana uses public APIs only. Configurable apps are themed only
  through hooks they support. Nothing is injected through the proxy; Jellyfin's database is never
  touched.

## 4. Security gates

M3 cannot read member data until G1 and G2 pass. Each gate has an automated test and an owner-run
verification.

### G1. Identity-header trust boundary (forensic audit D4)

**Problem.** The portal, the Kindle connector and OliveTin trust `X-authentik-*` headers, and they
share the `authentik_frontend` network with `authentik-worker`, `authentik-ldap` and each other. Any
of those containers can reach them directly and send forged identity headers. Today the risk is low
(all first-party); Media 2.0 raises the stakes because the home will read every member's library data.

**Resolution.** Apply the staged change on branch `batch6-authentik-isolation` (`1dd04d2`): one
private network per proxied backend (`authentik_portal`, `authentik_kindle`, `authentik_olivetin`),
joined only by the Authentik server and that backend. About one minute of SSO downtime while the
Authentik server restarts; the commit message holds the apply, verify and rollback steps. Owner
approval and a maintenance window required.

**Second layer (decision pending, D-3 below).** Have the outpost add a shared-secret header through the
proxy provider, and have each backend refuse any request without it. This keeps the boundary intact
if a future container is attached to a backend's network by mistake. Feasibility in the running
Authentik version must be verified before it is proposed as a change.

**Acceptance.**
- `docker network inspect authentik_frontend` lists none of the three backends; each private network
  lists exactly two containers.
- From a throwaway container on `authentik_frontend`, a request to each backend fails to connect.
- avrana.net, kindle.avrana.net and ops.avrana.net work through the outpost for a member and an admin.
- A health-check assertion (added to `scripts/services-health.sh`) fails if any of the three backends
  rejoins `authentik_frontend`.

### G2. Per-user authorization and isolation tests

The portal (780 lines, the internet-facing authorization point) has no tests today (forensic audit
E4). Before M3 reads any library data:

- **Route matrix.** Every route against every group combination: allowed routes render, everything
  else returns 404, never 403, and never a hint that something exists.
- **Leak tests.** Rendered pages for a member contain no label, hostname or help topic for a service
  outside their groups.
- **Isolation tests (M3 adapters).** With mock services holding two members' data, every adapter
  call made for member A returns nothing that belongs to member B, including Continue entries,
  progress, requests and search results. A request with no identity headers gets nothing.
- **Header tests.** Missing, empty, duplicated or malformed `X-authentik-*` headers fail closed.

These run offline with `python3 tests/run_offline.py` and block every PR that touches the
application.

## 5. Degradation, failure handling and recovery

### Degradation matrix

| Dependency down | What members see | What still works |
|---|---|---|
| Authentik or cloudflared | Nothing on avrana.net (sign-in impossible) | Native apps already signed in to Jellyfin and Audiobookshelf |
| Jellyfin | Video rows on the home page are replaced by "Movies and TV are unavailable right now"; search notes video is missing | Everything else |
| Audiobookshelf | Same pattern for audiobooks | Everything else |
| Komga or Calibre-Web | Same pattern for comics or ebooks | Everything else |
| A request service | The Request link shows "Requests are unavailable right now" | Everything else |
| The media array (unmounted) | Every library section unavailable; the operator notice explains | Help, account, sign-in |
| The Avrana home itself | Rollback to the previous portal image (below) | All per-service hostnames and native apps, which never depend on it |

### Failure handling rules

- Each home-page section loads independently with a timeout of about two seconds. A slow service
  costs its own section, never the page.
- No retries in the request path. After a failure, an adapter skips that service for a short cool-off
  (about a minute) so a struggling service is not hammered.
- Errors are logged with the service name and error class, never with member identity or content
  titles, matching the existing services' logging rules.
- A `/healthz` endpoint reports per-adapter state so `scripts/services-health.sh` can tell "home is up
  but Komga is unreachable" from "home is down".
- Member-facing error copy is written, reviewed and part of the design system, not left to defaults.

### Recovery and rollback

- **The application is stateless apart from a disposable cache.** Recovery is: rebuild the image from
  Git, restore its `.env` from 1Password, start. No new backup component is needed beyond adding its
  `.env` to the completeness gate.
- **Cut-over by upstream switch.** The new home runs as its own container. Launch points the
  `avrana-portal` proxy provider's internal host at it; rollback points it back. The previous portal
  container stays deployed, unused, for at least two weeks after launch.
- **Beta before cut-over.** Member acceptance testing (Section 7) happens on a separate gated hostname
  before the cut-over, so the live portal is never the test bed. The hostname needs a cloudflared
  ingress entry and an Authentik provider: an owner-approved change (D-5).

## 6. Milestones

### Pre-launch

**M0. Foundations.** Owner items already in [`ROADMAP.md`](../ROADMAP.md) that members depend on:
e-mail delivery (SMTP2GO rotation and the alert script; blocks invites and every notification),
`akadmin` MFA and the Authentik proposals P1 to P6, Seerr CSRF and proxy trust (A20), off-host backup
verification.

**M1. Security gate and finish what exists.**
- G1 applied and verified; G2 test suites in place for the current portal and the Kindle connector.
- Design system phase 1 (accessibility) and phase 2 (one shared stylesheet with a drift test).
- Invite path tested end to end in a browser, plus a **welcome page** on avrana.net for a member's
  first visit: what they can use, the one app to install per device, where help is.
- Installable site (web app manifest, icons).
- Help completed: topic headlines, device jump links, a contact route, a **House rules and privacy**
  page (what is recorded, who can see it, how to leave).
- Operator notices: a one-line banner on avrana.net set from an OliveTin action.
- Operator tidy-up: Homepage regrouped, stale tiles removed (audit A4); an offboarding runbook.

**M2. One account.** Decide and, if approved, test the Jellyfin SSO plugin against Authentik with
Quick Connect for televisions, on every client in use, keeping password login as fallback. If it
fails testing, keep the replicated Jellyfin password and document it plainly. Either outcome
completes M2.

### Launch

**M3. Avrana home**, shipped in independent slices on the beta hostname, each passing its tests and
a short member check before the next starts:

| Slice | Delivers | Depends on |
|---|---|---|
| M3.1 Skeleton | The new application serving today's portal pages unchanged, the design system, mock services, the G2 suites, `/healthz`, beta hostname | G1, design phase 2 |
| M3.2 Continue Watching | In-progress items from Jellyfin and Audiobookshelf for the signed-in member, each opening the right app at the right item | M3.1, read-only keys verified |
| M3.3 New for you | Recently added items across the libraries the member can use, with cached artwork | M3.2 |
| M3.4 Search | One search box across Jellyfin, Audiobookshelf, Komga and the Calibre-Web catalogue; each result says where it lives and opens it | M3.3 |
| M3.5 Title pages and request links | A title page with artwork, description and Open; for missing items, a Request link that opens the right request service (Seerr, Shelfarr or Omnibus) with the search filled in where it supports that | M3.4 |
| M3.6 Launch | Member acceptance testing passed, launch criteria met, cut-over approved | All above |

**Deferred out of M3:** filing requests through Avrana, request status in Avrana, any in-site
player or reader, notifications.

### Post-launch

**M4. Follow-through**, once usage shows members want it: "your request is ready" e-mail, a weekly
"New on Avrana" e-mail with opt-out, a completed account page (notification preferences, Kindle,
Audible contribution status). Filing requests through Avrana and request status move here, decided
per request service after its API is verified.

**M5. Only with evidence**: an audiobook player in the site, a comic and ebook reader, Jellyfin
branding. Evidence means Tracearr and Audiobookshelf usage plus member feedback.

### Not doing

A custom video player; television or native phone apps; frames or path-mounting of upstream apps;
CSS injection or code patches into upstream apps; a public status page; a separate staging host
(mock services and the beta hostname cover development and testing); a dedicated search engine
unless measured slowness requires one.

## 7. Validation

### Automated, on every PR that touches member interfaces

| Suite | What it proves | Runs |
|---|---|---|
| Authorization and isolation (G2) | Route matrix, leak tests, cross-member isolation, header failure modes | `python3 tests/run_offline.py`, offline |
| API contracts | Each adapter against recorded upstream responses; re-recorded with read-only keys before any upgrade of Jellyfin, Audiobookshelf, Komga, Calibre-Web or a request service | Offline; re-recording is an owner-approved read-only step |
| Accessibility | axe-core on fixture renders of every page at 390px and 1280px with zero serious or critical findings; keyboard path through every page; WCAG 2.2 AA contrast checks on the design tokens | Development environment with Playwright; not on the host |
| Visual | Screenshot baselines of every page and state, reviewed on change | Development environment |
| Degradation | Each mock service switched off in turn; the page still renders with the documented message | Offline |
| Performance | Home page server render under 300ms against mocks; under 2 seconds on the real host with warm cache, measured once per slice | Offline, then one owner-approved measurement |

There is no CI today (forensic audit E4). Whether to add a GitHub Actions workflow that runs the
offline suite is decision D-8.

### Real-member acceptance testing

Before cut-over, and again at the end of any post-launch milestone:

- **Testers.** Three to five members, chosen to cover a phone-first member, a TV-first member, a
  listener and someone who joined recently. Each consents and knows the beta is a test.
- **Tasks**, done unaided on their own devices on the beta hostname:
  1. Sign in from a phone and add Avrana to the home screen.
  2. Find something already started and continue it on the device they normally use.
  3. Find a specific title by searching, and open it in the right app.
  4. Look for something that is not in the library and find out how to ask for it.
  5. Find setup help for one of their devices.
- **Pass criteria.** Each task completed unaided by at least four of five testers (or all but one if
  fewer test); no task where a tester believes they succeeded but did not; every confusion recorded
  and either fixed or explicitly accepted by the owner.
- **Questions afterwards**, kept short: what was confusing, what was missing, whether they would use
  avrana.net instead of going straight to an app.
- Results are recorded in `docs/findings/` with no member names.

## 8. Launch criteria (Media 2.0 is "launched" when all hold)

1. G1 applied and verified; G2 suites passing.
2. M0 complete: invites and password resets deliver e-mail.
3. M1 complete, including welcome page, contact route and House rules and privacy page.
4. M2 decided and either completed or its fallback documented in help.
5. M3.1 to M3.5 deployed on the beta hostname with every automated suite passing.
6. Member acceptance testing passed.
7. Degradation drill done once on the host with owner approval (one library service stopped
   briefly, outside viewing hours, page verified, service restarted).
8. Rollback rehearsed once (provider switched to the old portal and back).
9. The owner approves the cut-over.

## 9. Owner decisions

| # | Decision | Needed before | Recommendation |
|---|---|---|---|
| D-1 | Contact route: an address, or a form that e-mails the owner | M1 help work | A plain address first; a form only if spam-free delivery is easy |
| D-2 | Maintenance window to apply G1 (about one minute of SSO downtime) | M1 | A quiet weekday evening |
| D-3 | Add the outpost shared-secret header as a second layer | M3.1 | Yes, if the running Authentik supports it cleanly |
| D-4 | Pursue Jellyfin SSO (M2) and accept its client testing | M2 | Try it; the fallback is acceptable |
| D-5 | Beta hostname for acceptance testing (cloudflared ingress and an Authentik provider) | M3.1 | Yes, gated on `authentik Admins` plus named testers |
| D-6 | Which members are acceptance testers | M3.6 | Three to five, covering the profiles in Section 7 |
| D-7 | Wording of the House rules and privacy page, including what Tracearr records | M1 | Draft provided for review; the owner's words |
| D-8 | Add a GitHub Actions workflow for the offline test suite | M1 | Yes; offline only, no secrets, no deploy |
| D-9 | Member target and invite plan to reach about 15 | Launch | Invite after acceptance testing, not before |
| D-10 | Which signals justify M4 and M5 items | Post-launch | Usage stats plus a short member check-in |

## 10. Sizing

| Milestone | Roughly | Production changes (each separately approved) |
|---|---|---|
| M0 | Owner time | Credentials, Authentik, Seerr settings |
| M1 | 3 to 5 weeks | Authentik restart for G1; rebuilds of the portal and two connectors; Authentik brand CSS; Homepage; one OliveTin action |
| M2 | 1 to 2 weeks plus client testing | Jellyfin plugin, if approved |
| M3 | 5 to 9 weeks across six slices | New container; beta hostname; cut-over by provider switch |
| M4, M5 | Per item, post-launch | Per item |
