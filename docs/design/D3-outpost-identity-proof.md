# D-3: proving the outpost sent the request (offline investigation)

> AVR-498 update: the verifier is now production-grade and offline-tested, and the adoption and OliveTin
> migration plan is in [D3-adoption-and-olivetin-plan.md](D3-adoption-and-olivetin-plan.md).

**Status: proposal with an offline proof of concept. Nothing is deployed, configured or wired in.** No live
system, credential or member data was touched. Live implementation needs the owner's separate approval.

## Question

G1 stops sibling containers from reaching the header-trusting backends (`avrana-portal`,
`avrana-kindle-connector`, `olivetin`), but anything in the host network namespace (the host, Jellyfin, Home
Assistant, the Beszel agent) can still send forged `X-authentik-*` headers straight to a backend IP. D-3 asks
for a second layer: something a forger without a secret cannot produce.

## Evidence (pinned versions, source read, nothing executed)

Authentik image `ghcr.io/goauthentik/server@sha256:ed120caf…` is **2026.5.6** (registry manifest match,
2026-10-14). OliveTin `@sha256:af9d7c4d…` is **3000.19.0** (per the compose comment; tag source read).
Paths below are in the Authentik repository at tag `version/2026.5.6` unless noted.

| # | Fact | Where |
|---|---|---|
| E1 | In proxy mode every authenticated request goes through `addHeaders`, which `Set`s username, groups, entitlements, email, name, uid, `X-authentik-jwt` and meta headers, then deletes every header whose name contains `_`. | `internal/outpost/proxyv2/application/mode_common.go`, `mode_proxy.go` |
| E2 | Proxy mode registers no forward-auth endpoints (`/outpost.goauthentik.io/auth/*`); those exist only in forward modes. | `application.go` (mode switch), `mode_forward.go` |
| E3 | Paths matching `skip_path_regex` are forwarded with no identity headers set or stripped. Avrana sets none (pinned by a G1 test). | `mode_proxy.go` |
| E4 | `ak_proxy.user_attributes.additionalHeaders` is copied over the identity headers; `user_attributes` is the user's merged group attributes. | `mode_common.go`, `blueprints/system/providers-proxy.yaml` |
| E5 | `X-authentik-jwt` is the session's raw OIDC **ID token**; `aud` is the provider's client id, `iss` the provider issuer, `exp` the token expiry; `preferred_username` and `groups` are included (`include_claims_in_id_token` is forced on). | `mode_common.go`, `authentik/providers/oauth2/id_token.py`, `authentik/providers/proxy/models.py` |
| E6 | **Proxy providers are reset to `signing_key = None` at every startup**, so the ID token is **HS256-signed with the provider's client secret**. The `signing_key` in Avrana's proxy blueprints is overwritten and has no effect. | `authentik/providers/proxy/models.py` `set_oauth_defaults`, `apps.py` `proxy_set_defaults`, `authentik/providers/oauth2/models.py` `jwt_key` |
| E7 | On sign-out the outpost redirects the browser to the end-session endpoint with `id_token_hint=<raw ID token>` in the URL, so every member sees their own token (and it can reach browser history and proxy logs). | `application.go` `handleSignOut` |
| E8 | The outpost session lifetime equals the token's `exp`. | `oauth_callback.go` |
| E9 | OliveTin 3000.19.0 can authenticate from a JWT in a request header (`authJwtHeader`), verified with `authJwtHmacSecret` (HMAC) or `authJwtPubKeyPath` (RSA), with `authJwtAud`, `authJwtClaimUsername`, `authJwtClaimUserGroup`. Its auth chain checks trusted headers (`authHttpHeaderUsername`) **first**, and it joins a groups claim array with spaces. | OliveTin `service/internal/auth/otjwt/jwt.go`, `service/internal/auth/authcheck.go` |

## Options

**A. Constant shared-secret header via `additionalHeaders` (rejected).** Mechanically possible (E4), but the
value would travel inside the ID token's `ak_proxy` claim, and that token is shown to the member at sign-out
(E7): every member would learn the secret. It also depends on the same attribute channel that can override
identity headers (G1 review finding F10). Rotation would need lockstep changes.

**B. Verify `X-authentik-jwt` and take identity from its claims (recommended).** The backend checks the
token's HS256 signature with that provider's client secret (E6), `iss`, `aud`, `exp`, and refuses requests
whose plain headers disagree with the claims. A host-namespace forger needs the client secret. Seeing a token
(E7) reveals nothing about the key, and a member's own token only ever proves that member's identity.

**C. TLS client certificates from outpost to backend.** No outpost option for client certificates was found;
not pursued.

**D. Host firewall (ufw) rules for the bridge subnets.** Complementary, host-level and outage-prone; a
separate decision, not a substitute for B.

## Recommendation

Adopt **B** for the portal, the Kindle connector and the Media 2.0 home, and for OliveTin through its native
JWT support. Roll it out in log-only mode first, then enforce, one service at a time.

Proof of concept: `services/avrana-home/avrana_home/outpost_jwt.py` (stdlib only) with
`services/avrana-home/tests/test_outpost_jwt.py`: 29 offline tests, keys and secrets generated in-test.
- **Covered:** HS256 (the actual 2026.5.6 behaviour) and RS256 (if a future version keeps signing keys),
  with the algorithm fixed by configuration and never by the token.
- **Refused:** `none`/HS-RS confusion, `jku`/`jwk`/`x5u`/`x5c`/`crit`, malformed PKCS#1 padding under the
  real key, duplicate JSON keys, wrong `iss`/`aud`, expired tokens, plain headers that disagree with the
  claims, and repeated tokens.
- **Rotation:** overlap is tested, then retirement, then rollback.
- **Mutation check:** 11 of 11 hand mutants killed.

### Spoofing resistance and residual risk

- Forging needs the provider's client secret, which lives in Authentik's database. It would also sit in each
  backend's env file, which is new exposure: anyone who can read that file can mint tokens for that one
  provider. Use a per-provider secret, which is the default.
- A captured valid token can be replayed until `exp` by someone who can reach the backend directly. Members
  can see their own token (E7), but reaching a backend directly is exactly what G1 prevents for containers;
  the host namespace remains (that is D-3's scope). Shortening `access_token_validity` (24 h today) shortens
  the replay window.
- Proxy providers also allow the password and client-credentials grants (`set_oauth_defaults`). With the
  client secret, those can obtain tokens for that provider's client. That is another reason to keep the
  secret out of anything members or other services can read.
- Requests the outpost authenticates by `Authorization: Bearer`/`Basic` (always attempted in 2026.5.6, review
  finding F9) carry a different token in `X-authentik-jwt`: an introspected access token, not the session's
  ID token, so its `aud`, claims and signature may not satisfy the verifier. In enforce mode those API
  clients would be locked out. Log-only rollout must show zero such requests (or a decision on them) first.
- Group names are refused if they contain `|` or `,` or start or end with whitespace, because the backends
  and OliveTin would split them differently. Names with inner spaces (`authentik Admins`) are kept whole by
  the verifier, but OliveTin splits on spaces; see the OliveTin row below.

### Per service

| Service | Change (not made) | Notes |
|---|---|---|
| Media 2.0 home | Call `principal_for_request(headers, mode=..., verifier=...)` in place of `principal_from_headers` (implemented offline in AVR-498; mode has no default and nothing selects a JWT mode) | `principal.py`, same `MemberPrincipal` |
| Portal, Kindle | Vendor the module (single-file stdlib services); verify before reading any identity header | `/healthz` stays unauthenticated |
| OliveTin | `authJwtHeader: X-authentik-jwt`, `authJwtHmacSecret` from env, `authJwtAud: <client id>`, `authJwtClaimUsername: preferred_username`, `authJwtClaimUserGroup: groups`; **remove** `authHttpHeaderUsername`/`Usergroup` (checked first, E9) | Groups are split on spaces: `authentik Admins` becomes `authentik` + `Admins`, so the ACL must match a group without a space or match by username. **Owner decision** |

### Rollout, rotation, rollback (each live step needs owner approval)

1. The owner reads each proxy provider's client id and client secret in the Authentik admin UI and stores
   the secret in that backend's env file only (`docs/SECRETS.md` pattern). An agent never sees it.
2. **Log-only:** the backend verifies and logs reason codes only (never tokens or names), but still serves
   from headers. Watch for a week: no `bad_signature`/`expired` for real sessions.
3. **Enforce,** one service at a time; the deny response stays the existing 404.
4. **Rotation:** pin the new secret next to the old one in the backend, then set the new client secret in
   Authentik. Existing sessions keep tokens signed with the old secret until they expire (whether a secret
   change also ends sessions is unverified), so keep both pinned for one token lifetime (24 h), then remove
   the old secret.
5. **Rollback:** set the backend back to log-only (one env flag, then a container restart, which is
   owner-approved), or restore the previous secret set. Nothing in Authentik has to change.

Lockout risks are clock skew (a 60 s leeway is built in) and a secret mismatch after rotation (the overlap
covers it). Expiry is safe because `exp` equals the session lifetime (E8).

## Owner decisions needed

1. Accept B as the D-3 direction and allow implementation PRs (offline, not deployed).
2. OliveTin group naming (a group without a space, or ACL by username).
3. Whether to shorten `access_token_validity` for the three proxy providers.
4. Note for AVR-356: the blueprints' `signing_key` lines have no effect on proxy providers (E6). Whether to
   remove them is cosmetic; it is not part of G1.
