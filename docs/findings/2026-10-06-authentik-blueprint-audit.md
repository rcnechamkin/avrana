# Authentik blueprint audit, 2026-10-06

Scope: the 13 blueprints in `services/authentik/blueprints/` (all tracked in Git since Batch 4),
compared with the live objects in Authentik 2026.5.6 through a read-only `ak shell` inventory
(`batch5-20261006/authentik-inventory.txt` on the host: names, flags, dates and counts, no values).
Closes roadmap item 1 ("audit the 13 blueprints applied for the first time during the September
recovery"). Nothing in Authentik was changed by this audit. Proposed blueprint changes are on the
branch `batch5-authentik-proposals` and are listed under "Proposed" below; they wait for the owner.

## What is in good shape

- Every blueprint instance is `successful`; the live providers, applications, flows and stages match
  what the files declare (the files are what the worker applies).
- Enrollment is invite-only (`continue_flow_without_invitation: false`), accounts are created inactive
  and activated only by the e-mail verification stage, provisioning into Jellyfin and Komga runs after
  verification, and the enrollee cannot inject group names (the prompt serializer drops undeclared
  fields; `avrana_groups` comes only from the invitation's `fixed_data`).
- Recovery: identification without password, `pretend_user_exists`, matched user hidden, 30-minute
  token, flow requires an unauthenticated session, e-mail stage does not activate users.
- Passkey first factor requires user verification; the optional passkey enrollment is declinable.
- All OIDC clients are confidential, strict redirect matching, implicit consent only for first-party
  apps, `hashed_user_id` subjects, 1-hour access tokens. Proxy apps: OliveTin limited to
  `authentik Admins` with an 8-hour token; the LDAP outpost has no published port (Docker network only).
- Secrets: none left in any blueprint (Batch 4); `blueprints.env` is 0600 and captured by the backup.
- Signing certificate `authentik Self-signed Certificate` is valid until 2027-08-13.

## Findings

| # | Severity | Finding | Recommendation |
|---|---|---|---|
| 1 | high | `akadmin`, the only superuser, has no MFA device; the MFA stage is `not_configured_action: skip`, so a password alone signs the administrator in on a public hostname | Owner: enrol a passkey for `akadmin` today (account page, "Configure" under MFA). Then consider requiring MFA for superusers (proposal P4) |
| 2 | medium | No brute-force control on login: the only limit is the password stage's 5 attempts per flow execution; no reputation policy exists | Proposal P1: a reputation policy on the identification stage binding (threshold -5, scores expire after 24 h) |
| 3 | medium | No password policy is enforced anywhere (the one that exists has 0 bindings). Enrollment and recovery accept any password, and that password is replicated into Jellyfin and Komga | Proposal P2: bind a password policy (length 12, HaveIBeenPwned check, zxcvbn score 3) to the enrollment, recovery and password-change prompt stages |
| 4 | medium | Live policy bindings that no blueprint declares: `seerr` also requires `avrana-videos`; `shelfarr` also requires `avrana-books` (order 0) and `avrana-audiobooks` (order 1). Bindings are AND-ed, so Git under-describes who can open those apps | Proposal P3 declares them exactly as they are (same group, same order), no behaviour change |
| 5 | low | Komga, Omnibus and Shelfarr providers keep plain-HTTP LAN redirect URIs (`http://10.0.0.218:…`). No service config references them; an authorization code could travel in clear on the LAN | Owner decision: remove them (proposal P5) unless LAN-address logins are wanted |
| 6 | low | `avrana-recovery-write` has `user_creation_mode: create_when_required` and `user_type: external`; recovery should never create | Proposal P6: `never_create` |
| 7 | low | `Test123` is an active member account (5 groups, last login 2026-08-19); `AshChristina` is inactive (never completed verification) | Owner: delete or deactivate `Test123`; delete `AshChristina` or re-invite |
| 8 | low | The signing certificate is not managed by Authentik (`managed=None`), so it will not be regenerated when it expires on 2027-08-13; expiry would break every OIDC login | Batch 5 adds a health-check WARN 60 days before expiry, read from the public JWKS. Rotate in July 2027 |
| 9 | info | Session lifetime 30 days + 150 days "remember me", no network or GeoIP binding (owner decision of 2026-08-28). With most members on password only, a stolen cookie is valid for up to 180 days | Accepted risk; passkeys for more members reduce it. 5 of 13 members have one |
| 10 | info | Live-only configuration not in any blueprint: the `authentik Admins` group is a child of every `avrana-*` group; group `ldap-service`; the two outposts and their service accounts; the `ldap-cwa` bind token; `search_full_directory` permission | Documented in `calibre-web-ldap.yaml` comments and here; recreate by hand after a rebuild (BOOTSTRAP section 7) |
| 11 | info | The Jellyfin and Komga provisioning policies send the enrollee's password over plain HTTP to the host address. Both targets run on the same host, so the traffic never leaves the machine | None |
| 12 | info | The inventory script used the deprecated `User.ak_groups` accessor, which left 18 `configuration_warning` events in Authentik's log at 2026-10-06 16:2x UTC | Cosmetic; they expire with event retention |

## Proposed changes (branch `batch5-authentik-proposals`)

- **P1** `avrana-session-tuning.yaml`: `authentik_policies_reputation.reputationpolicy`
  `avrana-login-reputation` (`check_ip: true`, `check_username: true`, `threshold: -5`) bound to the
  identification stage binding of `default-authentication-flow`. A lockout clears when the scores
  expire (24 h by default); the owner can clear a score from the admin interface at once.
- **P2** `avrana-enrollment.yaml` and `avrana-recovery.yaml`: `authentik_policies_password.passwordpolicy`
  `avrana-password-policy` (`length_min: 12`, `check_have_i_been_pwned: true`, `hibp_allowed_count: 0`,
  `check_zxcvbn: true`, `zxcvbn_score_threshold: 3`, `password_field: password`) bound to
  `avrana-enrollment-prompt`, `avrana-recovery-prompt` and `default-password-change-prompt`.
- **P3** `avrana-landing.yaml`, `shelfarr.yaml`: declare the existing bindings (finding 4).
- **P4** (not drafted; needs a decision) require MFA for `authentik Admins`: a second validate stage
  with `not_configured_action: configure` reached only by superusers, or simply keep finding 1 fixed by
  enrolling a device.
- **P5** `komga.yaml`, `omnibus.yaml`, `shelfarr.yaml`: drop the LAN redirect URIs.
- **P6** `avrana-recovery.yaml`: `user_creation_mode: never_create`.

Applying any of them: merge to `main`, deploy the file to `services/authentik/blueprints/` on the
host; the worker applies it within minutes (or `docker compose up -d --no-deps worker`). Test an
invite enrollment and a recovery afterwards. Rollback: restore the previous file; objects P1/P2 create
can be deleted in the admin interface.
