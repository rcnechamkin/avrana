# Pre-beta audit: Authentik -> Home -> Komga authentication (2026-10-30)

Owner brief: eliminate redundant authentication between Avrana Home and Komga before closed beta without destabilising
what works; no auth rewrite, no plaintext passwords, fail securely, keep the production enrollment flow, defer Connected
Apps / universal SSO. Success: a newly enrolled member signs in to Avrana once, reaches Comics with minimal or no extra
authentication, and never has to provide an obsolete password.

Read-only evidence: repo at main 1da4e86; live host `avrana` (ssh, read only: compose files, blueprint file names and
line numbers, image labels, env variable NAMES only); Komga 1.25.0 source (`SecurityConfiguration.kt`,
`KomgaUserLifecycle.kt`, `LoginView.vue`, `router.ts`, `UISettings.vue`, `application.yml`, tag 1.25.0); Authentik
2026.5.6 source (`stages/user_write/stage.py`, `stages/password/stage.py`, the live image's version label). No secret
value was read or printed. Nothing live was changed.

## 1. The flows as they are today

| Step | Mechanism | Credential | State on live |
|---|---|---|---|
| Sign in to Avrana (avrana.net, Home) | Authentik embedded outpost in front of Home; Home reads the `X-authentik-*` headers and verifies the outpost JWT (`jwt_required`) | Authentik session | live |
| Enrollment creates the Komga account | `avrana-komga-create` (enrollment flow, login stage, order 1): creates the Komga user with the SAME email and password the member just chose, with the Komga admin API key (`X-API-Key`; live since the AVR-784 key swap) | credential replication, not SSO | live |
| Enrollment mints Home's key | `avrana-komga-key-mint` (order 2): signs in to Komga AS the member with that password, makes the `avrana-home` API key, PUTs it to Home's intake (`/internal/komga-key/<subject>`, bearer token + private subnet + no proxy header) | the member's own password, inside the flow only | live, e2e tested 2026-10-30 (AVR-784) |
| Home reads the member's Comics | per-member `X-API-Key` from `state/komga_member_keys` (Continue reading, On Deck, New for You) | the member's own key | live |
| Me -> Comics -> Connect comics | member types the Avrana password; Home signs in to Komga as them with HTTP Basic, mints the key, forgets the password (5 tries / 15 min, CSRF, never logged) | the member's password, once | live (`HOME_KOMGA_CONNECT=on`) |
| Komga web UI (read.avrana.net) | Komga's own OIDC client against Authentik (`komga.yaml`; `oauth2-account-creation: true`, account matched by email) | Authentik session via OIDC | live; neither `webui.oauth2.hide_login` nor `webui.oauth2.auto_login` set (public `GET /api/v1/client-settings/global/list` = `{}`) |
| OPDS / reader apps | HTTP Basic with the Komga copy of the password | credential replication | live |
| Password reset | `avrana-recovery` (identification -> email link -> new password -> write). No Komga step. | | live. **This is the only self-service password change on live** (the `avrana-account` flows are not applied; Home's security links are off) |

## 2. Where "redundant authentication" actually comes from

1. **The Komga API has no OAuth2 resource server** (Komga 1.25.0 `SecurityConfiguration`: session cookie, remember-me,
   HTTP Basic, `X-API-Key`, `X-Auth-User`, `/kobo/{key}` only). Authentik tokens are not accepted. Home must hold a
   per-member Komga API key, and Komga mints keys only for the signed-in account (`POST /api/v2/users/me/api-keys`;
   no admin route for another user). So some Komga credential of the member is needed at mint time. That is why the
   project's standing decision is "keys are minted where the password lives" (enrollment).
2. **The Komga password is a copy.** Enrollment sets it to the Avrana password, but a later Avrana password reset
   leaves the copy behind. Three visible symptoms: "Connect comics" asks for the Avrana password and the copy says the
   one from enrollment ("use the one you joined with"); OPDS apps keep working only with the old password; a member
   who never had a key (enrollment before the key mint existed, or Komga/Home down at that moment) can be stuck. The
   retired admin-key provisioner also reset some members' Komga passwords to values nobody knows (S-01 damage,
   `state/komga_member_keys.reset_failed`).
3. **Komga's web login page** shows an email/password form whose password is this same copy. A member who tries their
   current Avrana password there after a reset fails for no reason they can see, although "Sign in with Authentik" one
   click away would work.

## 3. Komga's native OIDC with Authentik: what it can and cannot do (1.25.0 source)

- OIDC login works today (`komga.yaml`, implicit consent). After it, Komga keeps a 7-day session cookie
  (`server.servlet.session.timeout: 7d`), so deep links from Home (`/book/{id}`) work for a week per browser without any
  prompt. Remember-me is only set by the form login's checkbox, not by OAuth2.
- Client settings `webui.oauth2.hide_login` and `webui.oauth2.auto_login` exist (Server settings -> UI section:
  "Hide login fields if OAuth2 is enabled", "Automatic OAuth2 login"; auto login needs exactly one provider and hide
  login). They hide the obsolete password form and start the Authentik login by themselves.
- **Limits that no Avrana-side change removes:**
  - OAuth2 login runs in a popup (`window.open(..., 'oauth2Login')`), also on master. Auto login fires from
    `mounted()` without a user gesture, so strict popup blockers (Safari, iOS) may block it; the provider button
    remains and works on a click.
  - The intended destination is lost across an OAuth2 login: the success handler is
    `defaultSuccessUrl("/?server_redirect=Y", true)` (always), and the popup sends the opener to the site root. The
    `?redirect=` that the SPA keeps is honoured after FORM login only. So the first Komga visit of each 7-day window
    lands on the dashboard; later deep links go straight to the book. Upstream feature, not ours.
  - No Komga setting or hook issues an API key to a third party at login. Home cannot obtain a member's key through
    OIDC; the password path stays.

## 4. Risks and dependencies found

| # | Finding | Severity | Handled by |
|---|---|---|---|
| R1 | A password reset leaves the Komga copy obsolete; the Connect copy tells members to use an old password | medium (UX + the "obsolete password" criterion) | this change: `avrana-komga-password-sync` |
| R2 | Members without a Komga account (enrolled before the key swap: "enrollment never created Komga accounts before" AVR-784) have no copy at all; Connect comics cannot work for them | medium | this change creates the account on reset, same roles as enrollment |
| R3 | S-01 damaged members (`reset_failed`): neither key nor known Komga password | medium | a reset heals them (R1/R2); no owner-held password needed |
| R4 | Komga web login page shows a password form that only misleads Avrana members | low | owner setting: hide login (+ auto login), section 6 |
| R5 | Destination lost on the first Komga visit per 7 days | low, upstream | documented; nothing to build |
| R6 | iPhone PWA: avrana.net runs standalone; a Komga link opens an in-app browser whose Authentik session may differ, so Komga's OIDC may ask for the Avrana sign-in once per browser context | low | expected "once"; checked by the owner's phone pass (runbook) |
| R7 | PR #186 (phase-4 cleanup) touches the enrollment blueprint, `member_keys.py`, `main.py`, `settings.py` and the key runbook | process | this branch touches none of those files; merge either first |
| R8 | `services/authentik/.env` vs `blueprints.env`: a policy that reads `os.environ` runs in the SERVER; the admin key lives in `blueprints.env` (worker only) | process | runbook step: also put `AVRANA_KOMGA_ADMIN_API_KEY` in `.env`, recreate authentik-server |
| R9 | Komga `PATCH /api/v2/users/{id}/password` expires that user's web sessions | info | one forced Komga web re-login after a reset; API keys and reading progress untouched (`KomgaUserLifecycle.updatePassword`) |

## 5. Decision: the smallest safe implementation

Not chosen: (a) Home holding a Komga admin key again (rejected S-01 design); (b) members pasting a key (rejected
2026-10-28); (c) a new "Connect via Avrana" Authentik flow that re-verifies the password and syncs Komga: it would
remove Home's password form entirely, but it is a new flow plus Home routing, and the Connect form becomes a rare
fallback once (d) is in; (d) **chosen:** extend "minted where the password lives" to the one other place the password
is in a flow, the password reset. Additive policy `avrana-komga-password-sync` on the recovery flow's write binding
(and, in the not-yet-applied `avrana-account` password flow, the same binding by name):

1. member in `avrana-comics`? else skip;
2. with the Komga admin API key (server env, run time): find the Komga account by email and set the new password, or
   create the account (`FILE_DOWNLOAD`, `PAGE_STREAMING`, like enrollment);
3. exactly like `avrana-komga-key-mint`: sign in to Komga AS the member, replace the `avrana-home` key, PUT it to
   Home's intake with `source=recovery`;
4. every path returns True; nothing secret or identifying is logged; 5 s timeouts.

Home: the intake accepts `source=recovery` under the enrollment rule (an unknown subject is accepted from Authentik's
own stages); Me -> Comics copy no longer mentions the enrollment password and points a failing member to the reset.
Nothing else in Home changes. Fail-secure check: the account matched on reset is the Komga account with the email the
member has just proved they control (recovery is email-gated), the same rule enrollment uses; keys are still filed
under the account they open (`GET /api/v2/users/me`), never under the subject's claim.

Outcome against the success criterion: a new member signs in once (enrollment -> Home); Comics in Home is connected by
the enrollment mint; Comics' web UI needs one click on "Sign in with Authentik" (or none with auto login) per browser
per 7 days; no member is ever asked for an obsolete password, because the only way to change the Avrana password now
also changes the Komga copy and renews the key, and the one remaining manual form asks for the CURRENT password with
the reset as its escape hatch.

## 6. Owner steps (summary; the runbook has the detail)

1. Merge and deploy Home (intake accepts `recovery`; copy). Order matters: Home first, then Authentik.
2. Authentik: `AVRANA_KOMGA_ADMIN_API_KEY` into `services/authentik/.env` (hidden prompt), recreate authentik-server;
   copy the policy and its binding into the LIVE `avrana-recovery.yaml` and set the write binding's
   `re_evaluate_policies: true` (or the admin-UI route).
3. Komga: Server settings -> UI: tick "Hide login fields if OAuth2 is enabled"; try "Automatic OAuth2 login" and
   keep it only if the phone pass is fine.
4. Test matrix (runbook): throwaway enrollment, reset for an existing member (key count unchanged, OPDS works with the
   new password, Me -> Comics Connected), reset for a member with no Komga account, Disconnect -> Connect with the
   current password, offboarding, iPhone PWA + Safari.

## 7. What was and was not tested here

- Ran: `tests/test_recovery_komga_sync.py` (12, policy expression with fakes), `tests/test_enrollment_komga_key.py`
  (10, unchanged), Home `tests/test_komga_key_lifecycle.py` (28), `webtests/test_web_komga_keys.py` (26). YAML loads;
  `bash -n` on the CI script. The CI job `enrollment-policy` now also applies `avrana-recovery.yaml` to a throwaway
  Authentik 2026.5.6 and checks the binding and the policy's no-op pass (runs on the PR).
- Not run: anything against live Authentik, Komga or Home; the iPhone pass; a real reset. Those are the runbook's
  test matrix and need the owner.
