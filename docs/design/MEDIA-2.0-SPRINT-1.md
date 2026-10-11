# Media 2.0, Sprint 1: trust and test foundations

Status: **proposed, 2026-10-11.** Planning only. Part of [Avrana Media 2.0](MEDIA-2.0.md), milestone
M1. Every item that changes a running service is a separate owner approval with its rollback stated
in the PR, as `AGENTS.md` requires. Nothing in this sprint builds the new home application.

**Goal.** Close the identity boundary (G1), put the first authorization tests around today's
member-facing code (G2), fix the accessibility failures from the audit, and settle the owner
decisions that block M1. At the end, every later Media 2.0 slice has a safe base and a test harness
to build on.

**Length.** About two weeks of agent work, plus owner time that runs in parallel.

## Agent track (pull requests; offline work)

### S1-1. Portal authorization suite (G2, part 1)

Tests for `services/avrana-portal/portal.py`, which has none today.

Acceptance:
- Route matrix: every route (`/`, choosers, service redirects, `/help`, every help topic, `/account`,
  the interstitial, unknown paths) against at least these identities: no groups, each single group,
  a tuple-gated group (Shelfarr), all member groups, admin. Allowed routes return 200 or 307 to the
  fixed target; everything else returns 404, never 403.
- Leak tests: for each identity, no rendered page contains the label, hostname or help topic of a
  service outside its groups.
- Header tests: missing, empty, duplicated and malformed `X-authentik-groups` fail closed (no tiles,
  404 on gated routes).
- Redirect targets come only from the fixed table (no open redirect), including for crafted paths.
- Runs under `python3 tests/run_offline.py` with the standard library only.

### S1-2. Kindle connector authorization suite and the 404 rule (G2, part 2)

Acceptance:
- Tests cover denied, permitted and malformed identities for `GET /`, `POST /save` and `POST /remove`,
  with the Calibre-Web database and the Audiobookshelf API replaced by fixtures.
- A member without `avrana-books` gets the portal's 404 page instead of today's 403 with Amazon
  instructions (audit finding A5). A test proves it.
- Isolation test: with two fixture users, saving or removing for user A never changes user B's
  Calibre-Web row or Audiobookshelf device entry.
- The existing behaviour for permitted members is unchanged (tests pin it before the change).

### S1-3. G1 change, refreshed and ready to apply

Acceptance:
- The staged change on `batch6-authentik-isolation` (`1dd04d2`) is brought onto current `main` in a
  PR, with the apply, verify and rollback steps in its description and in
  `docs/DEPLOYMENT.md` terms.
- `scripts/services-health.sh` gains an assertion that `avrana-portal`, `avrana-kindle-connector` and
  `olivetin` are not attached to `authentik_frontend`, with a test using fixture `docker network
  inspect` output.
- A written forgery check for the owner to run after applying: start a throwaway container on
  `authentik_frontend`, attempt a request to each backend, expect connection failure.
- Nothing is applied by the agent. Applying is decision D-2.

### S1-4. Accessibility fixes (design system phase 1)

Three PRs: portal, Kindle connector, Audible connector. CSS and markup only; routes, gating, CSRF and
copy meaning unchanged.

Acceptance:
- Interactive edges use the Control Rule colour (#6e6e6e, at least 3:1); dividers keep #474747.
- One focus ring on every interactive element; no `outline: none` without it.
- Status messages carry `role="status"` or `role="alert"`.
- `color-scheme: dark` declared; footer and store links reach a 44px target.
- Help pages: a topic headline (`h2`), correct heading order.
- The Audible progress page stops reloading itself (a manual Refresh control as the minimal fix;
  in-place polling waits for M3).
- Em dashes removed from member-visible copy.
- axe-core reports zero serious or critical findings on fixture renders of every page at 390px and
  1280px; screenshots before and after are attached to each PR.

### S1-5. Test harness

Acceptance:
- The fixture render harness (pages rendered from templates with fixture identities, no network) and
  the Playwright accessibility and screenshot checks are committed under `tests/ui/`, documented as
  development-environment tools that never run against production.
- `tests/run_offline.py` runs S1-1 and S1-2 suites; the existing suites still pass.
- If D-8 is approved: a GitHub Actions workflow runs `python3 tests/run_offline.py` on pull requests,
  with no secrets and no deployment step.

### S1-6. Content drafts for owner review

Acceptance:
- Drafts, in house style, of the **welcome page**, the **House rules and privacy** page (what is
  recorded: Jellyfin and Tracearr playback history, request history, Authentik sign-in records; who can
  see it; how to leave) and the **offboarding runbook**. Committed as documents for review, not wired
  into any service.

## Owner track (parallel)

| Item | Why it blocks | Done when |
|---|---|---|
| M0 e-mail: rotate SMTP2GO, run the alert-configuration script | Invites, resets, every notification | A test invite and a password reset arrive |
| Invite tested end to end in a private browser window | S3 of the service standard; untested since enrollment was built | A new test account signs in to avrana.net from the emailed link, then is removed |
| D-1 contact route | Help and welcome page | Address or form chosen |
| D-2 G1 maintenance window | G1 | Window chosen; S1-3 applied and verified, or rolled back with notes |
| D-7 privacy page wording | M1 | S1-6 draft approved or edited |
| D-8 CI workflow | S1-5 | Yes or no |
| Member baseline | Sets the bar for acceptance testing | Three questions to current members (what they use, on which device, what annoys them); a read-only Tracearr and Audiobookshelf usage snapshot |

## Sprint done when

- S1-1 to S1-6 merged, all offline suites green, axe clean on every fixture page.
- G1 applied and verified by the owner, or a dated note in `docs/findings/` records why it was
  deferred.
- Accessibility PRs deployed one service at a time with owner approval, or explicitly queued for the
  next window.
- D-1, D-2, D-7 and D-8 recorded in `docs/DECISIONS.md`.
- Next sprint (design phase 2 and the rest of M1) re-planned with what the member baseline showed.

## Out of scope

The new home application, the beta hostname, Jellyfin SSO, Homepage changes, Authentik brand CSS,
anything in M3 or later.
