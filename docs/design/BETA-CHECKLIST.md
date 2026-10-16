# Beta hostname checklist: AVR-373 phase 1 (owner change checklist)

Status: a checklist only. **Nothing in it has been done**, and this change makes no live change. Every
step that touches production is marked **[OWNER APPROVAL]**: it needs your explicit yes at the time, and an
agent does not apply it unprompted. Offline preparation is the only part that needs no approval.

Context: `C:/Users/cnech/Projects/avrana-review-kit/IPHONE-LIVE-TEST-OPTIONS.md` (outside the repository)
recommends Option A: a gated beta hostname behind Authentik, mock upstreams, real sign-in. Phase 1 is real
sign-in with fake data. This repository's part is the verified-JWT identity mode (AVR-498, `HOME-APP.md`
section 2), which lets the beta be safe before network isolation (G1): the app trusts a signed token, not
plain headers.

Placeholders: `<beta-host>` is the new hostname you choose, `<client-id>`, `<client-secret>` and
`<issuer>` are read in the Authentik admin UI. They are never written into Git, a ticket or a chat.

## 0. Preconditions (offline)

- [ ] The PR "avrana-home: verified-JWT identity modes, default headers" is reviewed and merged. Its tests
      passed locally only (GitHub Actions is unavailable because of billing).
- [ ] A container image for the Home app exists (`serve.py`, `HOME_HOST=0.0.0.0` set deliberately inside
      the container). Building it is a separate unit; this checklist does not create one.
- [ ] Decide the hostname. Tester list (owner decision, 2026-10-15): **`akadmin` only**.
- [ ] Phase 1 uses **mock upstreams only**. Real mode additionally needs `HOME_GATES_VERIFIED=yes` and G1/G2,
      and is refused by the app otherwise. Do not set it.

## 1. Authentik proxy provider and application **[OWNER APPROVAL]**

How the app expects the token (from `D3-outpost-identity-proof.md` E5/E6, `outpost_jwt.py`, and the portal
wiring in #40): the Authentik outpost sends the session's raw OIDC ID token in the request header
**`X-authentik-jwt`**. For a proxy provider it is **HS256**, signed with that provider's **client secret**.
Claims used: `iss` (the provider's issuer URL), `aud` (the provider's client id), `exp`, `preferred_username`
and `groups` (a list); `email` and `name` are display-only. Plain `X-authentik-*` headers may also arrive;
in `jwt_required` they must agree with the claims or the request gets no principal.

- [ ] Create a **new, separate** proxy provider for `<beta-host>` (forward auth, single application, mode
      "proxy" or "forward single", external host `https://<beta-host>`). Use this provider's own client secret;
      do not reuse the portal's, so a leak of one does not forge the other.
- [ ] Create the application bound to that provider. Attach it to the embedded outpost.
- [ ] Confirm the proxy sends `X-authentik-jwt` (the default for the outpost; do not strip it in the proxy or
      in cloudflared). No custom header mapping is needed.
- [ ] Read `<issuer>`, `<client-id>` and `<client-secret>` in the Authentik UI. Store the secret **only** in a
      file on the host that the container reads (`docs/SECRETS.md` pattern, mode 0600, outside Git).
      An agent never sees it.

## 2. Access policy and the test account **[OWNER APPROVAL; the owner does these in the Authentik UI]**

- [ ] Create group **`avrana-beta`** containing **only `akadmin`**. Bind it to the beta application. This is
      the only binding: no "all authenticated users", no `authentik Admins`, no direct user bindings.
- [ ] Create a **fake test account** (for example `beta-outsider`): ordinary user, not superuser, in **no**
      groups, a random password you keep in your password manager, no real name or email (use an address
      under a domain you control or leave it blank). It exists only to prove that others are refused.
      Agents do not create or sign in to it.
- [ ] Do not add library groups for the beta. Mock members come from the mock fixtures; the groups in a real
      token only decide which mock sections appear.
- [ ] The beta provider must not use the portal's group mapping changes; leave the portal and its policy
      untouched.

## 3. cloudflared ingress line **[OWNER APPROVAL]**

In `deploy/host/cloudflared/config.yml` (and the live file on the host, applied by the owner), add one entry
**before** the catch-all, pointing at the Authentik outpost, not at the container:

```yaml
  - hostname: <beta-host>
    service: http://<authentik-outpost-address>      # the same outpost target the portal hostname uses
```

- [ ] The DNS record for `<beta-host>` on the tunnel (`cloudflared tunnel route dns`, or the dashboard).
- [ ] The beta container is **not** published on any host port reachable from the tunnel, only from the
      outpost's network, until G1 is applied. (Until G1, the JWT check is what makes a direct hit useless.)
- [ ] Reload `cloudflared-avrana.service` only after the file is reviewed.

## 4. Beta container and its environment **[OWNER APPROVAL]**

```
HOME_IDENTITY_MODE=jwt_required
HOME_ALLOWED_USERS=akadmin                                # second lock behind the avrana-beta binding
HOME_JWT_ISSUER=<issuer>
HOME_JWT_AUDIENCE=<client-id>
HOME_JWT_SECRET_FILE=/run/secrets/home_jwt_secret        # mounted read-only; value never in env or Git
HOME_SECTIONS=on
HOME_UPSTREAM_MODE=mock                                   # the default; do NOT set real or HOME_GATES_VERIFIED
HOME_HOST=0.0.0.0                                         # inside the container only
HOME_HEALTH_DETAIL=off
```

- [ ] The mock upstream (Jellyfin and any other adapters' mocks) runs alongside on the container network,
      loopback or an internal network only, with synthetic data.
- [ ] Start the container. A start failure naming `HOME_IDENTITY_MODE` or `HOME_JWT_*` means a missing or short
      secret, issuer or audience: fix the configuration, never relax the mode.
- [ ] Optional soak first: run `HOME_IDENTITY_MODE=jwt_log_only` for a few sessions and read the `identity_jwt`
      log lines. Expect `reason":"ok"` for real sessions; any `unverified_identity` means the secret, issuer or
      audience is wrong. `HOME_ALLOWED_USERS` is refused in log-only mode, so leave it out for the soak (the
      `avrana-beta` binding still limits sign-in to you), then switch to `jwt_required` and add it back.

## 5. Smoke tests (run from a network where you can reach `<beta-host>`)

| # | Test | Expected |
|---|---|---|
| 1 | **Signed-out request** (private window) to `https://<beta-host>/` | Redirected by Authentik to sign-in. The Home app is never reached. |
| 2 | **`beta-outsider`** signs in (private window) | Authentik denies (policy). No Home page. |
| 2b | **Second lock**: temporarily add `beta-outsider` to `avrana-beta`, sign in, then remove it again at once | Authentik admits, Home shows the Help-only page, `/account` shows no name, `/watch` is 404; log reason `not_allowed`. |
| 3 | **`akadmin`** signs in | Home renders with mock sections for the token's groups; `/account` shows the tester's username; `/home.json` returns the mock view. Sections appear only for library groups akadmin is in (for example `avrana-videos`); with none, only Help shows, which is still a pass for sign-in. |
| 4 | **Forged header**: from a host that can reach the container directly (not through the outpost), `curl` with `X-authentik-username: x` and `X-authentik-groups: avrana-videos` | The help-only page; gated routes (`/watch`, `/home.json`) are 404. Never sections, never a 403 or a redirect. |
| 5 | **Forged token**: same, with a self-made `X-authentik-jwt` | Same 404 outcome (`unverified_identity` if logging). |
| 6 | **Expired session**: let the session lapse (or revoke it in Authentik) and reload | Authentik sign-in again. A replayed old token reaching the app gets the no-principal page. |
| 7 | iPhone: tester signs in with passkey/MFA, navigates Home, a gated tile, `/account` | Works end to end. |

Record each result with the date. A failure of 1, 2, 2b, 4, 5 or 6 means stop and roll back. After 2b,
confirm `beta-outsider` is out of `avrana-beta` again.

## 6. Rollback **[OWNER APPROVAL] for the live parts**

1. Stop and remove the beta container.
2. Remove the `<beta-host>` ingress line (and DNS record) and reload `cloudflared-avrana.service`.
3. Remove the Authentik application, provider, the `avrana-beta` group and the `beta-outsider` account.
4. Delete the secret file on the host.
5. The portal and its hostname are untouched throughout; no step above edits them.

If only the Home code needs undoing, set `HOME_IDENTITY_MODE=headers` (or unset it): behaviour is the previous
one, but then the hostname must not remain exposed, because plain headers are trusted again.
