# Avrana Audible Sync Connector

A small, Avrana-branded onboarding flow that lets a nontechnical, Authentik-authorized user
connect their Audible account, pick the audiobooks they own, and import them into the shared
Audiobookshelf library, **without ever giving Avrana their Amazon password**.

It is intentionally narrow: connect Audible → Libation → Audiobookshelf. It is *not* a
Readarr/Shelfarr-style manager.

> Design, assumptions, and the isolation rationale live in [`PLAN.md`](./PLAN.md).

---

## Architecture

```
 browser ── HTTPS ──▶ cloudflared ──▶ connector (public web tier, OIDC via Authentik)
                                          │  private "internal" network, bearer token
                                          ▼
                                       companion (LibationCli, per-account profiles)
                                          │  writes finished M4B (+ cover/chapters/pdf)
                                          ▼
                              /mnt/avrana_media/audiobooks  ◀── Audiobookshelf reads
```

- **connector**: FastAPI + Jinja2, server-rendered. Public web tier. Holds the SQLite
  ownership map, drives the UI, and is the *only* thing the browser talks to. Never runs
  LibationCli, never sees an Amazon password.
- **companion**: a thin HTTP adapter built **from the pinned `rmcrackan/libation` image**
  (v13.7.7 digest) that runs `LibationCli` against a **separate Libation profile directory per
  connected account**. Private network only, **no published port**.

### Two tiers, one private link
The companion has no host/public port and lives on an `internal: true` Docker network. Only
the connector can reach it, authenticated with a bearer token read from a read-only mounted
file (`secrets/companion_token`), never from an env var, never sent to the browser.

---

## Isolation strategy (no cross-user catalog disclosure)

Each connected Audible account gets an opaque `profile_id` and a **physically separate**
Libation state directory (`/profiles/<profile_id>`); every LibationCli call passes
`--libationFiles /profiles/<profile_id>`. The connector's DB binds `authentik_sub → profile_id
→ ASINs`, and **every route resolves the profile from the authenticated subject**. No route
accepts an account/profile id from the client. Revocation deletes the profile directory.
Result: one user can never scan, list, or import against another user's account, and the
catalogs are separate databases, not one shared list. See `PLAN.md` for the full argument;
`tests/test_flow_isolation.py` proves it.

---

## Security boundaries (what is enforced)

- **AuthN/AuthZ**: Authentik OIDC (Authorization Code + PKCE); access requires the
  `library-contributors` group. (A `header` mode for an Authentik proxy outpost is also
  supported; see *Auth modes*.)
- **The Amazon password never touches Avrana.** The user signs in on Amazon's own page; only
  the final redirect URL is pasted back, forwarded once to the companion, and **discarded**:
  it is never written to the DB, logs, audit trail, or traces (`tests/test_security.py`).
- **CSRF** on every state-changing route (signed token bound to the subject).
- **Rate limiting** on auth-start / auth-complete.
- **Redaction**: a logging filter + `redact()` scrub URLs and tokens from every log line and
  every companion error before it reaches a user or a log.
- **Path safety**: ASINs/ids are strictly validated; output paths are never built from titles.
- **No Docker socket** anywhere; the connector cannot create containers.
- **Audit trail** (`audit` table) records connection started/completed, mode changed, book
  queued, import completed/failed, disconnected, **without secrets**.

---

## Setup

Prereqs: Docker + compose, the existing Authentik at `auth.avrana.net`, and the shared
`/mnt/avrana_media/audiobooks` directory.

```bash
cd services/avrana-audible-connector

# 1. Generate local secrets (companion token + session key). Idempotent.
bash scripts/gen-secrets.sh

# 2. Apply the Authentik blueprint (creates the library-contributors group + OIDC app).
#    The blueprint file already carries a generated client_id/secret.
cp services/authentik/blueprints/audible-connector.yaml \
   ../authentik/blueprints/                       # if not already there
docker restart authentik-worker
# Put the SAME client secret from the blueprint into the connector secret file:
#   (client_id also goes into .env as OIDC_CLIENT_ID)
printf '%s' '<client_secret_from_blueprint>' > secrets/oidc_client_secret

# 3. Configure .env
cp .env.example .env    # set OIDC_CLIENT_ID=<client_id_from_blueprint>

# 4. Add the public hostname to cloudflared (see below) and add the DNS route.

# 5. Build & start
docker compose up -d --build
docker compose ps
```

### cloudflared route
Add to `~/.cloudflared/config.yml` ingress (before the catch-all 404):
```yaml
  - hostname: contribute.avrana.net
    service: http://localhost:8092     # Avrana Audible Connector
```
Then `cloudflared tunnel route dns <tunnel> contribute.avrana.net` and restart the tunnel.

### Add contributors
In Authentik, add users to the **`library-contributors`** group. Only they can reach the app.

---

## Auth modes

`AUTH_MODE`:
- `oidc` *(default)*: the connector is its own OIDC client (matches ABS/Komga on this host).
- `header`: trust `X-authentik-*` headers from an Authentik **proxy outpost** in front. Only
  use this if the connector is reachable **exclusively** via the outpost (no direct port), or
  headers can be spoofed.
- `dev`: static `DEV_IDENTITY` for local walkthroughs/tests only. Never in production.

---

## Sync modes (what the user picks)

| Mode | Behaviour |
|------|-----------|
| **Import once** | Imports the selected books. When all succeed, the Audible authorization is **revoked** (profile deleted) automatically. On failure it is retained so the user can retry/disconnect. |
| **Ask me** | Retained. Daily metadata-only scan. New purchases appear as *pending*; nothing downloads until approved. |
| **Auto** | Retained. Daily scan. New **purchased** ASINs are auto-queued. Audible Plus / borrowed titles are never imported; nothing already present/active/completed/excluded is requeued. |

The user can switch modes or disconnect at any time.

---

## Account removal

- **User self-service:** the “Disconnect” link (mode & progress pages) opens a confirmation page,
  `GET /contribute/audible/disconnect`, which only reads: it says what disconnecting removes and keeps,
  and offers **Cancel** (back to the page it came from) and **Disconnect**. There is no script and no
  inline handler (AVR-502). Only that page's CSRF-protected `POST /contribute/audible/disconnect` acts:
  it calls the companion's idempotent `POST /v1/revoke`, which deletes the profile directory (stored
  Audible tokens and state), and removes the connector rows. A revoked account cannot be scanned again.
  `connector/tests/test_disconnect_confirm.py` covers it.
- **One-time mode** does this automatically after a fully successful import.
- **Admin:** delete `profiles/<profile_id>` and the matching `connection` row.

---

## Maintenance, backup & recovery

- **Back up:** `data/connector.db` (ownership map, jobs, audit) and `secrets/`. The `profiles/`
  directory holds Audible auth tokens; treat as sensitive; back up if you want to avoid users
  re-authing after a host rebuild, otherwise it is safe to discard (users simply reconnect).
- **DB migrations** run automatically on start (forward-only SQL in `connector/app/migrations`).
- **Upgrade:** `docker compose build --pull && docker compose up -d`. Re-pin the connector base
  image digest in `connector/Dockerfile` and the companion base digest as needed.
- **Recovery:** restore `data/connector.db` + `secrets/`; `docker compose up -d`. If `profiles/`
  is lost, connected users just reconnect their Audible account through the UI.
- **Libation locking:** the companion serializes all CLI operations with a global lock, so it
  never runs two LibationCli operations at once. It uses its **own** profile directories and
  does **not** share the existing `services/libation` config/DB, so it never races the admin's
  12-hour scan/liberate loop.

---

## Testing

```bash
cd connector
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest pyyaml
python -m pytest tests/ -q
```
Tests never use real Audible credentials; the companion is faked in-process. Coverage includes
authz enforcement, session ownership/expiry, CSRF, redirect-URL redaction, catalog isolation,
purchased-vs-Plus, selection, ASIN dedup, refresh-safe jobs, progress/polling, failure/retry,
one-time revocation, scheduled ask/auto scans, disconnect/reconnect, path-traversal, and the
companion-privacy deployment invariants.

`connector/tests/test_a11y.py` (S1-4 / AVR-359) renders every page state from the fake companion and checks
the manual refresh control, headings, labels, `role="alert"` and `role="status"`, contrast, focus ring,
44px targets, `color-scheme`, CSRF tokens and copy (no em or en dashes, no first person). It uses the
stdlib helper `connector/tests/a11y_helpers.py` and the shared `style.css` is the only stylesheet. It is not
run by the repository's `tests/run_offline.py` because it needs the packages above. From this directory,
with a Python that has `connector/requirements.txt` plus `pytest` installed (`pyyaml` is needed only by
`test_deploy_config.py`; the `companion` tests import `termios`, so they run on Linux or macOS only):

```bash
cd connector
python -m pytest tests/test_a11y.py -q            # the accessibility and refresh checks
python -m pytest tests -q                         # the whole connector suite
```

It is not a browser: layout, 200% text zoom and screen reader speech still need a manual pass.

### Import progress page

The page no longer reloads itself. It shows the current status in a `role="status"` line ("2 of 5 imported,
1 failed, 2 still in progress.") and a **Refresh** button. In-place polling is deferred to Media 2.0 M3.

**Loading the page changes nothing** (owner decision, 2026-10-15). `GET /contribute/audible/progress` only
reads: it never dispatches, polls, finalises or revokes. **Refresh** is a CSRF-protected
`POST /contribute/audible/progress/refresh`. It dispatches queued jobs, polls running ones and, in one-time
mode, finishes the import (revokes the stored Audible authorization and records it) once every book the
member chose is in. It answers with a `303` back to the page, so reloading never resubmits it; a second
Refresh changes nothing the first did not. The background scheduler does the same work every five minutes,
so an import still finishes when the browser is closed. When Refresh finishes a one-time import it shows the
result itself (the connection is gone afterwards) and no further Refresh.

**An empty choice finishes nothing.** Selecting no book is refused with "Choose at least one book to import.",
and one-time mode cannot be chosen with nothing selected. Only books the member chose (they have a job) count
towards "all done": books a scan found already in Avrana no longer do, so they alone can never revoke the
authorization. A chosen book that turns out to be present still counts, so the one-time promise holds.

**A failed book keeps the authorization.** A chosen book that failed counts as unfinished, so the import is
not finished and the member can still **Retry** it (or disconnect themselves). Once the retried book is in,
the next Refresh or scheduler pass finishes the import.

**Finishing happens once.** Before revoking, the finisher claims the connection with one conditional update
(`connected` to `finishing`). Overlapping Refreshes, or Refresh and the scheduler, therefore revoke and audit
exactly once; the others do nothing. A failed revoke hands the claim back (with the sanitized failure), and a
claim left by a process that stopped mid-revoke is released when the connector starts.
`tests/test_once_lifecycle.py` covers the whole lifecycle, including CSRF and isolation between members.

### Credential-free UI walkthrough (mock companion)
```bash
bash scripts/gen-secrets.sh
docker compose -f docker-compose.yml -f docker-compose.mock.yml up --build
# browse http://127.0.0.1:8092/contribute/audible  (dev identity, fake library)
```

---

## Limitations / verification status

- The **real companion**'s live Audible handshake and the exact `export --json` field mapping
  are **not exercised in CI** (no test Audible account, by policy). Verbs/flags were confirmed
  against `LibationCli help` (v13.7.7). Confirm `_normalize_export` against one real export
  before first production import; the mock proves the connector logic end to end.
- Single connector replica (in-memory rate limiter). Move the limiter to the DB before scaling
  horizontally.
- `header` auth mode requires an outpost in front to be safe (documented above).
