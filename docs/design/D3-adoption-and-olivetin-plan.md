# D-3 adoption plan: verified Authentik JWT identity for the portal, Kindle and OliveTin (AVR-498)

**Status: plan only. Nothing here is deployed, configured or enabled.** The owner decision of 2026-10-15
(`docs/DECISIONS.md`) adopts verified Authentik JWT identity as the architecture. This document is the
migration plan for the services other than Media 2.0 home, plus the OliveTin group proposal. It builds on
[D3-outpost-identity-proof.md](D3-outpost-identity-proof.md) (evidence E1 to E9). Independent security review
is required before any of it is enforced, and every live step below is marked **[OWNER APPROVAL]**.

## 1. What exists now (offline, in `services/avrana-home`)

- `avrana_home/outpost_jwt.py`: `OutpostJwtVerifier` (one provider: one issuer, one audience, one algorithm
  fixed by configuration, HS256 client secret as Authentik 2026.5.6 uses, or RS256 pinned keys from a JWKS
  document or PEM). Requires `iss`, `aud`, `exp`, `iat`; checks `nbf` when present; leeway 0..300 s (default
  60); refuses `none`, algorithm swaps, token-supplied keys, malformed or non-canonical base64, duplicate
  JSON keys, oversized tokens, unknown `kid`, and missing or empty groups or username.
- `avrana_home/principal.py`: `principal_from_verified_jwt(headers, verifier)` and the single service entry
  point `principal_for_request(headers, *, mode, verifier=None, report=None)`. Modes: `headers` (today),
  `jwt_log_only`, `jwt_required`. `mode` has no default, so JWT enforcement cannot be turned on or off by
  omission, and nothing in the repository selects a JWT mode.

## 2. Portal and Kindle connector

Both are single-file, standard-library services (`services/avrana-portal/portal.py`, 858 lines;
`services/avrana-kindle-connector/kindle.py`, 643 lines) that parse `X-authentik-*` headers themselves.

**Do they need the verifier vendored?** Yes, one of two ways, and the recommendation is a small shared module
copied into each service rather than an import across services:

| Option | For | Against |
|---|---|---|
| A. Vendor a trimmed copy of `outpost_jwt.py` (about 250 lines, stdlib only) next to each service file, with a test that pins its hash against the canonical copy | Services stay single-purpose, no Docker build-context change, no new dependency | Three copies to keep in sync; mitigated by the hash-pin test and by HS256 being the only mode needed (the RSA code, PEM and JWKS parsers can be dropped from the vendored copy) |
| B. A shared package in the image build context | One copy | Needs compose build-context and Dockerfile changes: a live change, avoided |
| C. Inline into `portal.py` / `kindle.py` | No extra file | Largest diffs to reviewed files; worst drift |

Recommended: **A, HS256-only trimmed copy**, one provider per service:

1. Each service gets its own verifier with its provider's issuer and client id as audience, and its own client
   secret (per-provider secrets are the Authentik default). A token minted for the portal is refused by Kindle
   and by home (tested: `ReplayAcrossAudiencesTests`).
2. Replace the header reads with `principal_for_request(headers, mode=<env>, verifier=...)`. The portal's
   existing 404 and redirect behaviour for "no identity" is kept: a `PrincipalError` maps to exactly what a
   missing header maps to today, and the route-by-identity matrix is re-run for both paths (acceptance item of
   AVR-498).
3. `/healthz` and any path that is unauthenticated today stay so.
4. Mode comes from one env variable per service (`AVRANA_IDENTITY_MODE`, default `headers`), read once at
   start; an unknown value stops the service from starting rather than falling back.
5. Order of work (each a separate PR, offline): portal, Kindle, then the Audible connector and anything else
   that reads `X-authentik-*`. `grep -rn "X-authentik" services/` is the inventory; each hit is moved behind the
   shared function or deleted.

Open points for the independent review: (a) Authorization-header API clients get a different token in
`X-authentik-jwt` (finding F9); the log-only phase must show zero such requests or a decision is needed;
(b) whether the sign-out redirect exposing the ID token (E7) justifies shortening `access_token_validity`.

## 3. OliveTin: a dedicated authorization group

**Today** (`services/olivetin/config/config.yaml`): identity from `authHttpHeaderUsername` /
`authHttpHeaderUsergroup` with separator `|`; one ACL `avrana-admins` matching the group `authentik Admins`
and the username `akadmin`; `defaultPermissions` grant nothing; every action lists the ACL.

**Problems:** the group name contains a space; OliveTin's JWT path joins a groups claim with spaces (E9), so
`authentik Admins` would split into `authentik` and `Admins`; the username `akadmin` is an individual, not a
role; and `authentik Admins` is also Authentik's own administration group, so being an Authentik admin and
being allowed to restart containers are the same grant.

**Proposal: a new Authentik group `avrana-ops`** (lower-case, no spaces, `[a-z0-9-]` only, no `|`, `,` or
edge whitespace, which is exactly what the verifier already enforces for every group name).

- Members: only people who may run host operations. It is not nested in, and does not inherit from, any
  other group. Membership is the only grant; no username lists.
- Group-name rule kept for all Avrana groups: `^[a-z0-9]+(-[a-z0-9]+)*$`. Existing `avrana-*` groups already
  follow it.
- OliveTin ACL after migration: `matchUsergroups: [avrana-ops]` and nothing under `matchUsernames`.

**Compatibility checks to run offline before proposing anything live** (OliveTin 3000.19.0, pinned digest):

1. Read the pinned release's auth source (`service/internal/auth/otjwt/jwt.go`, `authcheck.go`) and record,
   with file and line, the order of the auth chain (E9 says trusted headers are checked first), how a groups
   claim array is joined, and whether the separator is configurable for the JWT path.
2. Start the pinned image in a local, fixture-only container with a synthetic HS256 secret and the proposed
   config; a test sends tokens for a member in `avrana-ops`, a member outside it, a forged token, an expired
   token, and a header-only request with `authHttpHeader*` removed. Expected: only the first sees actions.
   (This is a local test container with fixture data, not the production container; it needs no approval
   beyond the sprint rules, but it is **not** run in this unit.)
3. Confirm a group without a space survives OliveTin's space-join intact, and that a member holding both
   `avrana-ops` and other groups is still matched (the test for "space-joined groups" must include a
   multi-group member).
4. Extend `services/olivetin/tests/test-olivetin.sh` (or a Python equivalent) so the committed config is
   checked for: no `matchUsernames`, no group containing whitespace, every action carrying the ACL, and
   `defaultPermissions` still empty.

**Migration steps** (each live step **[OWNER APPROVAL]**):

1. Offline PR: new ACL in `config.yaml` listing both `avrana-ops` and the old `authentik Admins` / `akadmin`
   entries (union, so nothing locks out), plus the tests above. No behaviour change until deployed.
2. **[OWNER APPROVAL]** Create the Authentik group `avrana-ops` and add the owner (admin UI; no agent
   involvement).
3. **[OWNER APPROVAL]** Deploy the union config (OliveTin container restart, owner-run). Verify the owner is
   served through `avrana-ops` by temporarily testing with the legacy entries removed on a staging copy.
4. Offline PR: remove `authentik Admins` and `akadmin` from the ACL. **[OWNER APPROVAL]** deploy.
5. Only after the JWT mode for OliveTin has been decided: switch to `authJwtHeader: X-authentik-jwt`,
   `authJwtHmacSecret` (from `services/olivetin/.env`, owner-entered), `authJwtAud`,
   `authJwtClaimUsername: preferred_username`, `authJwtClaimUserGroup: groups`, and **remove**
   `authHttpHeaderUsername` and `authHttpHeaderUsergroup` (they are checked first and would shadow the token).
   **[OWNER APPROVAL]**.
6. **Rollback** at any step: restore the previous `config.yaml` (it is in Git) and restart OliveTin
   **[OWNER APPROVAL]**. The union state of step 1 is the safe resting point.

## 4. Owner-gated live steps (none are done here)

Every item below needs its own explicit approval and none is implied by this plan, the draft PR or a merge:

1. Reading each proxy provider's client id and client secret in Authentik, and storing the secret in that
   service's env file (owner only; an agent never sees it). **[OWNER APPROVAL]**
2. Setting `AVRANA_IDENTITY_MODE=jwt_log_only` for a service and restarting it (about one week of reason-code
   observation; never log tokens or names). **[OWNER APPROVAL]**
3. Moving a service to `jwt_required`, one service at a time. **[OWNER APPROVAL]**
4. Creating the `avrana-ops` group and any change to Authentik providers, outposts, blueprints or
   `access_token_validity`. **[OWNER APPROVAL]**
5. Any OliveTin config deployment or restart (section 3). **[OWNER APPROVAL]**
6. Secret rotation (overlap procedure in the proof document). **[OWNER APPROVAL]**
7. Closing the independent security review: an independent reviewer, not the author, signs off the verifier,
   the minting path and the test matrix before step 3. **[REQUIRED GATE]**
