# Me → Account & Security (Media 2.0)

Status, 2026-10-28: **reworked for the owner's "invisible identity" rule, behind the Home shell, not deployed, not
verified against the running Authentik.** Source brief: *Avrana Media 2.0 — Account & Security and Me Completion
Supplement* (owner, 2026-10-27), decisions AS-01..AS-11, amended by the owner on 2026-10-28:

> Members should never be thinking about "Authentik". They should never be rerouted to an Authentik page. If we have to
> send people to Authentik, they at least shouldn't even know that it's Authentik. Keep it visually consistent.

That reverses AS-01/AS-07's "hand off to Authentik's user settings" fallback (and supplement §8.6). Code:
`services/avrana-home/avrana_home/app/security.py`, `avrana_home/accountreader.py`, template `me_security.html`, tests
`webtests/test_web_me_security.py`. The Authentik side (single-purpose flows, sign-out, recovery return, the reader's
service account, the brand) is in `services/authentik/` (blueprint `avrana-account.yaml`, brand v2).

Evidence rule used throughout: **repo** means read from this repository's blueprints and service docs (which can lag
the host); **live** means observed on host `avrana`. Nothing below is live unless it says so. Per `AGENTS.md`, the
running system wins where they disagree.

## 1. What Home does

Avrana owns every screen a member reads or manages. Authentik only runs the moments that must prove who the member is,
each as one Avrana-styled step that returns by itself.

| Route | What it is |
| --- | --- |
| `/me/security` | Hub: Sign-in & recovery (Password, Sign-in protection, Account recovery), Account access (Where you're signed in), Sign out of Avrana |
| `/me/security/protection` | Equal-weight chooser (Passkey, Authenticator app) and, with the reader, **On your account**: the member's own passkeys and authenticator apps with added / last-used dates |
| `/me/security/password`, `/protection/passkey`, `/protection/authenticator`, `/recovery/codes` | "What to expect", then **Continue** when that flow is configured; otherwise "ask the person who invited you". Never a link to Authentik's user pages |
| `/me/security/recovery` | Forgot-password route (sign-in page), the member's masked recovery address (`m•••@example.net`), backup codes, owner-assisted fallback |
| `/me/security/sessions` | With the reader: the browsers signed in to the account (device, approximate place, last active) and **Sign out** for one of them (`POST`, every forms.py lock). Without it: who to ask |
| `/me/security/go/<action>` | 303 to the configured flow `https://<auth host>/if/flow/<slug>/`. `action` ∈ `password passkey totp recovery_codes`; an unconfigured or unknown action is the standard 404 |
| `/me/security/done/<action>` | Where each flow's closing redirect lands. Says **added / changed only on fresh evidence** from the reader (a method of that kind created in the last 15 minutes, or `password_change_date` in that window); otherwise "we couldn't see a change yet" |
| `/me/security.json` | Capability map; enrollment is `verified_enrolled` / `verified_absent` with the reader, `unknown` without it. No slug, host or member identifier |

All of it exists only with the Home shell on and a verified member; otherwise every path is the portal's 404. The
`/account` page no longer links Authentik's user interface ("Manage account" is gone); it points at Account & Security.

### What is native and what is a flow

| Concern | Rendered by | Credential Home holds |
| --- | --- | --- |
| Sign-in methods on the account (names, dates) | Avrana | scoped reader (view) |
| Where you're signed in; sign out one session | Avrana | scoped reader (view, delete sessions) |
| Recovery address (masked) | Avrana | none (from the verified identity) |
| Change password | flow `avrana-password` (confirm current password → new → write → back) | none |
| Add passkey / authenticator app / backup codes | flows `avrana-passkey`, `avrana-authenticator`, `avrana-backup-codes` (confirm password → enrol → back) | none |
| Remove a passkey or authenticator | owner (Admin → user → MFA devices) | none |
| Forgot password | sign-in page "Forgot password?" → `avrana-recovery`, which now ends back on Avrana | none |
| Sign out | `/signout` → outpost → `avrana-sign-out` invalidation flow: ends the Authentik session too, then back to Avrana's sign-in | none |

Why the credential steps stay on the sign-in host: every existing passkey is bound to the relying party
`auth.avrana.net`, so a passkey ceremony can only run there; and the API permissions to set a password or edit a user
would let a compromised Home take over any account, admins included. The reader is deliberately read-mostly: viewing
devices and sessions, deleting a session. It cannot change passwords, users or devices (supplement §6 forbade doing
this *silently*; this is the owner's explicit choice, 2026-10-28).

### The scoped reader (`accountreader.py`)

Off unless `HOME_ACCOUNT_READER_URL` and `HOME_ACCOUNT_READER_TOKEN` (or `_FILE`) are both set; real mode also needs
`HOME_IDENTITY_MODE=jwt_required`. Its allow-list is exactly four requests:

| Request | Use |
| --- | --- |
| `GET /api/v3/core/users/?username=<u>` | the member's account id, active flag, last password change. Exactly one exact, active match or nothing |
| `GET /api/v3/authenticators/admin/all/?user=<id>` | names, kinds and dates of the member's methods. The per-kind admin endpoints are not allowed (the static one carries backup codes) |
| `GET /api/v3/core/authenticated_sessions/?user__username=<u>` | the member's sessions |
| `DELETE /api/v3/core/authenticated_sessions/<uuid>/` | one session, only after it is found in a fresh read of that member's list |

Reads are reused for 30 s per member; a sign-out and the done page read fresh. An unreadable answer is shown as
"couldn't be loaded", never as "none". **Endpoint shapes are from the Authentik API as documented for recent
versions, not checked against 2026.5.6**: `docs/runbooks/account-reader.md` has the owner's check before enabling.

### Turning flows on (owner, after the Authentik blueprint is applied and checked)

`HOME_SECURITY_FLOWS=password=avrana-password,passkey=avrana-passkey,totp=avrana-authenticator,recovery_codes=avrana-backup-codes`.
Unknown keys, repeated keys and anything that isn't a plain slug stop Home from starting. Set a slug only after, on the
deployed instance, a signed-in test member completes that flow, lands on `/me/security/done/<action>`, and (for
methods) the new device is accepted at the next sign-in. `HOME_SECURITY_RETURN_ORIGIN` is retired: setting it is now a
startup error, because every flow returns through its own redirect stage.

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

**Sign out of Avrana** → `/signout` → `Clear-Site-Data: "cache", "storage"` on this device → the outpost's
`/outpost.goauthentik.io/sign_out` → the portal provider's invalidation flow. That used to be
`default-provider-invalidation-flow`, whose closing page (Authentik's "You've logged out of …", with a button to the
Authentik dashboard) broke the owner's rule, and which left the Authentik session alive, so reopening Avrana signed
straight back in. The blueprint `avrana-account.yaml` gives the portal provider `avrana-sign-out` instead: end the
Authentik session, then redirect to `https://avrana.net/`, which shows the Avrana-styled sign-in. The copy still
promises only "Signs you out on this device"; TV and phone apps signed in directly stay signed in (correct). No "Sign
out everywhere" exists.

Owner tests once applied (supplement §6): S-1 sign out, reopen Avrana (expect the sign-in screen); S-2 sign out, open
`auth.avrana.net` (expect the sign-in screen); S-3 sign out one session from "Where you're signed in", then use that
browser; S-4 sign out the session you're using from that list; S-5 sign out while a TV stays signed in to Jellyfin;
S-6 refresh mid-sign-out.

## 4. Recovery policy (AS-06, provisional)

1. Forgot password, has email → "Forgot password?" on the sign-in page (works today, repo). The blueprint now ends
   `avrana-recovery` with a redirect to Avrana, so the member never lands on Authentik's dashboard afterwards.
2. Lost one factor, has another or backup codes → sign in with the other one (validation stage accepts them, repo).
3. Lost email and every factor → owner-assisted: `docs/runbooks/owner-assisted-recovery.md`.

Precondition still open: the verification-email click-through was "not yet verified end to end" in
`docs/services/authentik.md`; recovery uses the same SMTP2GO sender.

## 5. Discovery checklist (supplement §8)

| Item | State |
| --- | --- |
| Authentik version and flow names | Repo only (above). Live: Admin → System → version; Admin → Flows list |
| Safe direct entry per action | Flows declared in `avrana-account.yaml` (not applied); Home offers none until `HOME_SECURITY_FLOWS` is set |
| Member-scoped status/session read | Scoped reader service account (`docs/runbooks/account-reader.md`), off until configured |
| Enrollment verification output | Fresh reader read on `/done/<action>`; `unknown` without the reader |
| Password change and recovery mail | Needs a test account on the host |
| Passkey accepted at sign-in | Repo/doc yes (five members, 2026-08-28); re-check after any flow change |
| TOTP and static codes accepted | Device classes allowed (repo); enroll + sign in with a test account |
| No lost-factor dead end | Expected dead end → owner runbook; confirm |
| Real sign-out behaviour | §3 S-1..S-6 |
| iOS / Android standalone PWA return | Not tested. Each flow's closing redirect returns to Avrana; on iOS the step may open in an in-app browser sheet |
| Nobody lands on Authentik's dashboard | Owner step: the Cloudflare redirect rule in `services/authentik/README-member-surfaces.md` |

Smoke-account matrix (supplement §8.8): local password only; + TOTP; + passkey; both; no recovery email; locked out.
External-SSO accounts don't exist today.

## 6. Built elsewhere

- **Profile (photo, display name)**, **account-wide Home preferences (HOME-02)**, the **device setup card**: their own
  branches on top of this one, on the member store decided 2026-10-28 (S1).
- **Embedded Jellyfin Quick Connect (ME-05)**: built (#127).
