# Me → Account & Security (Media 2.0)

Status, 2026-10-27: **built behind the Home shell, not deployed, not verified against the running Authentik.**
Source brief: *Avrana Media 2.0 — Account & Security and Me Completion Supplement* (owner, 2026-10-27), decisions
AS-01..AS-11. Code: `services/avrana-home/avrana_home/app/security.py`, template `me_security.html`, tests
`webtests/test_web_me_security.py`.

Evidence rule used throughout: **repo** means read from this repository's blueprints and service docs (which can lag
the host); **live** means observed on host `avrana`. Nothing below is live unless it says so. Per `AGENTS.md`, the
running system wins where they disagree.

## 1. What Home does

| Route | What it is |
| --- | --- |
| `/me/security` | Account & Security hub: Sign-in & recovery (Password, Sign-in protection, Account recovery), Account access (Where you're signed in), Sign out of Avrana |
| `/me/security/password`, `/protection`, `/protection/passkey`, `/protection/authenticator`, `/recovery`, `/sessions` | "What to expect" pages, each ending in **Continue securely** |
| `/me/security/go/<action>` | 303 to a fixed Authentik address. `action` ∈ `password passkey totp recovery_codes sessions account`; anything else is the standard 404 |
| `/me/security/back?s=<state>` | Return page. Only ever says "couldn't confirm" or "someone else is signed in now" |
| `/me/security.json` | The capability map for the frontend (no slugs, hosts or member data) |

All of it exists only with the Home shell on and a verified member; otherwise every path is the portal's 404. GET
only: Home still writes nothing, holds no credential, and calls no Authentik API.

### Capability map (`SecurityConfig.capabilities`)

| Capability | Default route | Why |
| --- | --- | --- |
| `change_password` | Authentik settings page | Every account is local (no external sources configured: `docs/services/authentik.md`). The password-change flow slug is **not** in the repo |
| `enroll_passkey` | Authentik settings page | Documented manual path: settings → MFA Devices → Add (`docs/services/authentik-sessions-passkeys.md`). `default-authenticator-webauthn-setup` is named as a `configure_flow` in the repo, but direct entry is not verified |
| `enroll_totp` | Authentik settings page | `totp` is an accepted device class at login (repo); setup flow not in the repo |
| `manage_recovery_codes` | Authentik settings page | `static` is an accepted device class at login (repo); setup flow not in the repo |
| `recover_by_email` | Sign-in page only | `avrana-recovery` is `require_unauthenticated`, so a signed-in member can't run it; the brand's `flow_recovery` puts "Forgot password?" on the sign-in page (repo) |
| `view_auth_sessions` | Authentik settings page | Authentik's own sessions list for the signed-in user. Home has no member-scoped read and must not use an admin token (AS-09, supplement §6) |

Enrollment state is always `unknown`. The outpost hands Home an identity, not an API token, so Home has no safe way to
read a member's devices. The UI never says "Passkey added".

### Turning on direct flows (owner, after checking on the host)

`HOME_SECURITY_FLOWS=password=<slug>,passkey=<slug>,totp=<slug>,recovery_codes=<slug>` makes that action open
`https://<auth host>/if/flow/<slug>/` instead of the settings page. Unknown keys, repeated keys and anything that
isn't a plain slug stop Home from starting. Set a slug only after, for that slug on the deployed instance:

1. it exists and is a stage-configuration flow for that authenticator (Admin → Flows),
2. a signed-in test member reaches it directly and completes it,
3. a device enrolled through it is **accepted at the next sign-in** (the validation stage allows that device class).

`HOME_SECURITY_RETURN_ORIGIN=https://<media host>` adds `next=<media host>/me/security/back?s=<state>` to direct-flow
hand-offs (never to the settings page, which is a `#` address). Set it only after checking that the deployed Authentik
actually follows a cross-host `next` at the end of that flow. If it doesn't, leave it unset; the member comes back with
the app switcher or the back button, and every page already says where to check the result.

The state is `action.expiry.HMAC(action|expiry|username)` under a random per-process key: no storage, no username or
secret in the address, 15-minute life. A different member reading it sees `session_changed`; a restart makes old
states read as a plain "couldn't confirm".

## 2. Authentik audit (repo, 2026-10-27)

Version in the repo: **2026.5.6** (`docs/services/authentik.md`). Blueprints under `services/authentik/blueprints/`.

| Area | Repo evidence | Status |
| --- | --- | --- |
| Sign-in flow | `default-authentication-flow`: identification (+ passkey first factor via `avrana-passkey-first-factor`, `user_verification: required`), password, `default-authentication-mfa-validation` (static, totp, webauthn, duo, sms, email; `not_configured_action: skip`), login 30 d / 180 d with remember-me | Repo; applied 2026-08-28 per doc |
| Passkey enrollment | Invite flow offers a passkey (`avrana-enrollment-passkey`, opt-in policy); 5 members had passkeys on 2026-08-28 | Repo/doc |
| TOTP / static setup | Accepted at login; setup flows not declared in this repo | **Needs live check** |
| Password change | Not declared in this repo | **Needs live check** |
| Recovery | `avrana-recovery`: identify (username or email) → email link, 30 min → new password → write. No login stage at the end; brand `flow_recovery` set | Repo |
| Sessions | Authentik keeps per-user sessions; the member sees them in user settings; admins can delete them | Doc |
| Logout | Portal proxy provider `invalidation_flow: default-provider-invalidation-flow` | Repo; behaviour **needs live check** (§3) |
| External IdPs | None configured; `default-source-*` flows inert | Doc |
| Jellyfin | Password **copied** at enrollment; later Authentik password changes and resets don't reach it | Doc, verified 2026-08-14 |

Findings that change member copy:

- **Password ≠ TV and Movies password.** The Password page tells members with `avrana-videos` that changing it here
  doesn't change Jellyfin's copy.
- **Recovery resets only the password.** Because `avrana-recovery` ends without logging in, the member then signs in
  normally and is still asked for any passkey or authenticator they have. Expected: no MFA bypass. Also expected: a
  member who lost **both** their password and every factor reaches a dead end after the reset, and needs owner help
  (§4). Confirm both on the host.

## 3. Sign-out scope (AS-10)

Today: **Sign out of Avrana** → `/signout` → `Clear-Site-Data: "cache", "storage"` on this device → the outpost's
`/outpost.goauthentik.io/sign_out`, which (per upstream behaviour, not checked here) ends the outpost session and runs
the provider's invalidation flow, `default-provider-invalidation-flow`.

Not known: whether that flow also ends the **Authentik** session. If it doesn't, opening Avrana again signs the member
straight back in without a prompt. The member copy only promises "Signs you out of Avrana Media on this device". No
"Sign out everywhere" exists or should until revocation is proven end to end.

Owner tests (from supplement §6): S-1 sign out, reopen Avrana (prompt or silent?); S-2 sign out, open
`auth.avrana.net` (still signed in?); S-3 revoke the current session in Authentik settings, then use Avrana; S-4 revoke
another browser's session; S-5 sign out while a TV stays signed in to Jellyfin (TV must keep working; that's correct);
S-6 refresh mid-sign-out.

## 4. Recovery policy (AS-06, provisional)

1. Forgot password, has email → "Forgot password?" on the sign-in page (works today, repo).
2. Lost one factor, has another or backup codes → sign in with the other one (validation stage accepts them, repo).
3. Lost email and every factor → owner-assisted: `docs/runbooks/owner-assisted-recovery.md`.

Precondition still open: the verification-email click-through was "not yet verified end to end" in
`docs/services/authentik.md`; recovery uses the same SMTP2GO sender.

## 5. Discovery checklist (supplement §8)

| Item | State |
| --- | --- |
| Authentik version and flow names | Repo only (above). Live: Admin → System → version; Admin → Flows list |
| Safe direct entry per action | None verified; all use the settings page until `HOME_SECURITY_FLOWS` is set |
| Member-scoped status/session read | None available to Home; settings-page hand-off used instead |
| Enrollment verification output | None; `unknown` state implemented |
| Password change and recovery mail | Needs a test account on the host |
| Passkey accepted at sign-in | Repo/doc yes (five members, 2026-08-28); re-check after any flow change |
| TOTP and static codes accepted | Device classes allowed (repo); enroll + sign in with a test account |
| No lost-factor dead end | Expected dead end → owner runbook; confirm |
| Real sign-out behaviour | §3 S-1..S-6 |
| iOS / Android standalone PWA return | Not tested. Expect the hand-off to open outside the standalone app on iOS |

Smoke-account matrix (supplement §8.8): local password only; + TOTP; + passkey; both; no recovery email; locked out.
External-SSO accounts don't exist today.

## 6. Not built here, and why

- **Account-wide Home preferences (HOME-02)** and **profile edits** need durable per-member storage. Home has none by
  design (`HOME-APP.md`: a file-backed store is an owner decision). Needs that decision first.
- **Embedded Jellyfin Quick Connect (ME-05)** needs a member-scoped Jellyfin credential strategy; the admin key must not
  be used. Needs a design and security review first.
- **Device setup card, guides, Help changes**: frontend/content work with open product questions (ME-02..ME-04, ME-07).
