# Authentik & SSO

> Promoted from the BookStack wiki on 2026-10-04 (page 42, "Authentik & SSO", last edited 2026-08-28) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: 13 blueprints were re-applied during the September recovery and have not been audited.
> Original: [archive](../../docs/archive/bookstack/raw/services/42-authentik-sso.md).

**Authentik** is the homelab OIDC/LDAP identity provider. `services/authentik/`: containers `authentik-server` + `authentik-worker` + `authentik-postgresql` + `authentik-ldap` (LDAP outpost). **:9000 LAN**, public tunnel **`auth.avrana.net`**. Version 2026.5.6. Secrets in gitignored `.env`; declarative config in gitignored `services/authentik/blueprints/` (auto-applied by the worker: `docker restart authentik-worker` to apply changes).

## How each app authenticates (they are NOT all the same)

| App | Mechanism | Group gate | Password change in Authentik propagates? |
|-----|-----------|------------|------------------------------------------|
| Audiobookshelf | OIDC (real SSO) | `avrana-audiobooks` | ✅ yes (live) |
| Komga | OIDC (real SSO) | `avrana-comics` | ✅ yes (live) |
| Audible Connector | OIDC (real SSO) | `library-contributors` | ✅ yes (live) |
| Calibre-Web | LDAP (own login form) | `avrana-books` | ✅ yes (live) |
| Jellyfin | **credential replication** | (created via `avrana-videos`) | ❌ **no: copy is frozen** |
| Seerr | rides on Jellyfin |: | ❌ no |

**Real SSO vs credential replication**: ABS/Komga/Audible/CWA validate against Authentik at every login, so an Authentik password change applies instantly. Jellyfin/Seerr get a **copy** of the password made at signup (because their TV/phone apps can't do OIDC), so a later Authentik password change does **not** reach them. Verified 2026-08-14.

## OIDC apps (ABS, Komga, Audible Connector)
- Each is an Authentik OAuth2 provider + application, gated by a group policy binding. Blueprints: `audiobookshelf.yaml`, `komga.yaml`, `audible-connector.yaml`.
- **ABS:** issuer `.../application/o/audiobookshelf/`, `autoRegister=true`, `matchExistingBy=email`, `groupClaim=groups`. A returning local user is re-matched by **email** (no duplicate); their progress/bookmarks are preserved. Mobile app uses two redirect lists: see the ABS service page.
- **Komga:** `oauth2-account-creation: true` (auto-creates, all libraries by defaul: trim per user). Matches existing by email.
- **`email_verified` gotcha:** Authentik's stock email scope hardcodes `email_verified:false`, which ABS/Komga reject ("email not verified"). Fixed per-user via an `email_verified` attribute; the invite flow stamps it automatically. Komga instead has `oidc-email-verification: false`.
- **App-slug-rename trap:** the Authentik app *slug* is the OIDC issuer path. Renaming an app in the UI changes the slug and silently 404s the issuer/JWKS (this broke ABS SSO on 2026-08-13). Blueprints pin ABS by pk so the display name can change but the slug can't.

## Calibre-Web: LDAP outpost
CWA has no OIDC, only a username/password form. It authenticates against the **`authentik-ldap`** outpost (image `ghcr.io/goauthentik/ldap`, on the private `avrana-ldap` docker network, LDAP :3389 never on the LAN). Users type their Authentik username+password into CWA's form; gated by `avrana-books`. Public at `books.avrana.net`. **Killer gotcha:** the LDAP provider's *authorization_flow* must be `default-authentication-flow` (not implicit-consent) or every bind fails "Flow does not apply." Full detail on the CWA service page.

## Jellyfin / Seerr: credential replication
Jellyfin can't do OIDC in its clients, so at **enrollment** an Authentik expression policy (`avrana-jellyfin-create`, gated on `avrana-videos`) calls Jellyfin `POST /Users/New` with the username+password the person typed: creating a Jellyfin account with the same password. **Seerr** then auto-creates on that user's first Jellyfin login (no config needed). Caveats: reaches Jellyfin by host IP `10.0.0.218:8096` (host networking, not `jellyfin:8096`); a pre-existing same-username Jellyfin account is left untouched (keeps its old password); password changes don't propagate.

## Invite-based onboarding
Flow **`avrana-invite`** ("Join Avrana", `services/authentik/blueprints/avrana-enrollment.yaml`): invite → prompt (username/name/email/password) → user_write → login. One invite → one account → every app the invite's groups grant provisions itself.

**Send an invite:** Authentik → Directory → Invitations → Create → flow "Join Avrana" → set custom attributes:
```json
{"avrana_groups": ["avrana-audiobooks", "avrana-comics", "avrana-books", "avrana-videos", "library-contributors"]}
```
Link: `https://auth.avrana.net/if/flow/avrana-invite/?itoken=<uuid>`. **Single-use invites are consumed the instant the flow starts**: use expiring+reusable for a nontechnical invitee so an interrupted signup can resume.

**How groups map to access:** the invite carries group names in `avrana_groups`; a bridge expression policy (`avrana-invite-groups`, bound to user_write with `re_evaluate_policies`) turns them into real group membership at execution time. `avrana-users` is the baseline (auto-added). Superusers are **not** exempt from app gates, so `akadmin` is a member of every `avrana-*` group.

## Groups reference
`avrana-users` (baseline) · `avrana-audiobooks` (ABS) · `avrana-comics` (Komga) · `avrana-books` (Calibre-Web) · `avrana-videos` (triggers Jellyfin/Seerr) · `library-contributors` (Audible Connector) · `avrana-requests` (reserved, gates nothing yet) · `ldap-service` (holds the CWA bind account's search permission).

## Verified enrollment and passkeys (2026-08-17)

The invite flow now verifies the email address before the account can be used, and offers a
passkey at the end.

| Order | Stage | Notes |
|---|---|---|
| 0 | invitation | unchanged: no token, no enrollment |
| 10 | prompt | username, name, email, password |
| 20 | user_write | **creates the account INACTIVE**; the groups policy still runs here |
| 30 | **verify email** | sends a link; `activate_user_on_success` flips the account on |
| 40 | user_login | Jellyfin + Komga provisioning policies hang off this binding |
| 45 | **passkey offer** | a single tick-box: set up Face ID or a passkey now |
| 50 | **passkey** | WebAuthn registration, **skipped entirely if they declined** |
| 60 | redirect | to the portal |

### The one deviation from "no user before verification"

Authentik's email stage **cannot run before `user_write`**. Its code path exits with
*"No pending user"* unless `PLAN_CONTEXT_PENDING_USER` is set, and only `user_write` sets it
(`authentik/stages/email/stage.py`). Authentik's supported pattern is therefore the reverse:
create the account **inactive**, then activate on successful verification, which is exactly what
`activate_user_on_success` exists for.

So an unverified enrollment does leave a row in `authentik_core_user`: but it is `is_active=false`,
which means:

- it cannot authenticate to Authentik, so no OIDC or LDAP app will ever see it,
- **no downstream account is created**, because the Jellyfin and Komga policies are bound to the
  *login* stage at order 40, which is after verification at 30.

**Verified by test:** with an invite carrying `avrana-comics` + `avrana-videos`, an enrollment
stopped at the email stage showed `is_active=f`, groups assigned, **Jellyfin not provisioned,
Komga not provisioned**, and a Jellyfin login attempt returning **401**.

> **A trap worth knowing about.** Re-ordering the flow through the blueprint silently left the
> Jellyfin and Komga policies attached to *both* the verification stage and the login stage,
> because the binding row at the old order number was reused. That would have provisioned
> downstream accounts **before** verification. The duplicates were removed and the flow was
> re-applied to confirm they do not come back. **After any future re-order, re-check which
> stages the provisioning policies are bound to.**

### Passkeys

A dedicated `avrana-enrollment-passkey` stage, rather than editing the shared
`default-authenticator-webauthn-setup` that other flows use.

**Face ID is offered, never demanded.** Both settings are `preferred`, not `required`:

- `user_verification: preferred`: Authentik's own wording is *"user verification would be great,
  but if not that's okay too"*. An iPhone still presents Face ID; a device without biometrics is
  not shut out.
- `resident_key_requiremen: preferred`: still produces a discoverable credential (a real passkey
  that syncs into iCloud Keychain) on iOS, Android and modern browsers, without hard-failing on
  authenticators that cannot store one.
- `authenticator_attachment` is left unset on purpose so a hardware security key also works.
- `configure_flow` points at `default-authenticator-webauthn-setup`. **Because setup is optional,
  people will skip it, so there has to be a way back**: this is what puts a Configure button in
  the MFA section of the account page, letting someone add a passkey later without a second
  enrollment.

### Making it genuinely optional

**Authentik's WebAuthn stage has no skip button.** Once a flow reaches it, the person must
register a credential: so setting `user_verification: preferred` alone still left Face ID
effectively mandatory, because the *stage* was mandatory even though the *credential* was not.

Optional is therefore expressed with two objects rather than a setting:

1. `avrana-enrollment-passkey-offer` (order 45): one tick-box, **ticked by default** so passkeys
   stay the encouraged path, with one click to decline.
2. `avrana-passkey-optin`, an expression policy bound to the passkey stage (order 50). Returning
   `False` from a policy **skips the stage it is bound to**. The binding uses
   `evaluate_on_plan: false` + `re_evaluate_policies: true`, which is essential: at plan time the
   answer does not exist yet, so a plan-time evaluation would skip for everybody.

The policy treats a missing, empty, `False` or `"false"` value as declined, because an unticked
checkbox arrives in several shapes. **Verified against all six:**

| Answer | Result |
|---|---|
| ticked (`True`) / (`"true"`) | passkey stage runs |
| unticked (`False`) / (`"false"`) / absent / empty string | passkey stage skipped |

Declining costs nothing: login already happened at order 40, so the account is verified, working
and signed in, and the Configure button on the account page adds a passkey later.

Authentik remains the authentication authority; nothing here is app-specific.

### Admin recovery procedures

**Someone is stuck as inactive** (verification email lost, link expired after 30 minutes):

```bash
# activate by hand
docker exec authentik-postgresql psql -U authentik -d authentik \
  -c "UPDATE authentik_core_user SET is_active=true WHERE username='<name>';"
```

They can then sign in normally, and downstream provisioning happens on their next login through
each app's own OIDC/LDAP path. Jellyfin is the exception: its account is created only by the
enrollment policy, so if they never completed the flow, create it in the Jellyfin dashboard or
re-issue the invite.

**Find abandoned enrollments** (created but never verified):

```bash
docker exec authentik-postgresql psql -U authentik -d authentik \
  -c "SELECT username, email, date_joined FROM authentik_core_user WHERE is_active=false;"
```

Delete them in FK order: `authentik_flows_flowtoken`, `authentik_core_token`,
`authentik_core_user_groups`, `authentik_core_authenticatedsession`, then
`authentik_core_user`: each as a **separate** statement, because a multi-statement `psql -c`
shares one implicit transaction and one error silently rolls the rest back.

**Retries do not duplicate.** The Komga policy looks the account up by email and sets the password
on the existing row rather than failing; the Jellyfin policy logs and returns without blocking if
the account already exists.

> **Not yet verified end to end: clicking the emailed link.** The verification mail definitely
> sends (confirmed in SMTP2GO's activity log), the token is issued, and invalid tokens are
> correctly refused. But the click-through completes in the browser's flow-executor session, which
> could not be simulated from a script. **Do one real enrollment in a browser before issuing
> invites**, and if the account does not activate, use the manual activation above and say so.

## Branding: "Welcome to Avrana!" and the wordmark (2026-08-21)

`auth.avrana.net` previously greeted every visitor with **"Welcome to authentik!"** and authentik's
orange logo. Both are now Avrana.

### Flow titles

The greeting is NOT the brand's `branding_title` (that was already "Avrana"). It is the **flow's own
`title`**, so each flow had to be changed:

| Flow | Was | Now |
|---|---|---|
| `default-authentication-flow` | `Welcome to authentik!` | **`Welcome to Avrana!`** (login) |
| `avrana-invite` | `Create your Avrana account` | **`Welcome to Avrana!`** (sign-up) |
| `default-source-authentication` | `Welcome to authentik!` | `Welcome to Avrana!` |
| `default-source-enrollment` | `Welcome to authentik! Please select a username.` | `Welcome to Avrana! Please select a username.` |

The two `default-source-*` flows are inert today (no external identity sources are configured) but
were fixed anyway, because they would have leaked "authentik" the moment one was added.

`avrana-recovery` deliberately still reads **"Reset your Avrana password"**. It was already
Avrana-branded, and "Welcome to Avrana!" on a password-reset screen would be wrong.

> **`avrana-invite`'s title lives in `services/authentik/blueprints/avrana-enrollment.yaml`**, which
> auto-applies from the mounted blueprints directory. Changing it only in the database silently
> reverts on the next apply. The blueprint was updated too. The other three flows are unmanaged
> (`managed=None`) and persist as database edits.

### The wordmark is CSS, not an image

`branding_logo` still points at authentik's stock SVG; that image is **hidden by CSS** and the
wordmark is drawn on its container. This looks roundabout and is not:

- **`branding_logo` cannot be a data URI.** authentik treats the field as a *media path* and
  rewrites it to `/files/media/public/<value>`, so a data URI becomes
  `/files/media/public/data:image/svg+xml;base64,...` which 404s and renders as a broken-image
  icon. This was tried first and is exactly what it looks like on screen.
- **`/media` is not a mounted volume on this host.** An SVG dropped there would vanish on the next
  container recreate.
- Drawing it in CSS avoids both, survives upgrades because it lives in the brand record, and
  renders in the client's **real** Times New Roman rather than a rasterised approximation.

The rule under the wordmark is a **background gradient, not a second element**. The brand div also
carries `.pf-c-login__main-header`, so switching it to flex in order to position a `::before`
beneath the `::after` would risk moving the flow title. A background paints inside the existing box
and cannot reflow anything.

### Where it lives, and the knobs

All of it is `Brand.branding_custom_css` on the default brand, appended to the existing
black/white/square house style rather than replacing it.

    .pf-c-brand img, .ak-brand img, img.pf-c-brand { display: none !important; }
    .pf-c-brand::after, .ak-brand::after {
      content: "AVRANA";
      font-family: "Times New Roman", Times, serif;
      font-size: 40px;
      letter-spacing: 0.34em;
      text-indent: 0.34em;          /* cancels the trailing letter-space so it centres */
      padding-bottom: 24px;
      background-image: linear-gradient(#8a8a8a, #8a8a8a);
      background-size: 160px 1px;   /* the rule */
      background-position: center bottom 10px;
    }

| To change | Edit |
|---|---|
| Letter tracking | `letter-spacing` **and** `text-indent` together, keep them equal |
| Rule length | `background-size: 160px 1px` |
| Rule distance | `background-position` and `padding-bottom` |

`text-indent` matching `letter-spacing` is not decoration: letter-spacing adds a gap after the final
letter too, which makes centred text sit visibly left of centre without it.

### Troubleshooting

**Old logo or title still showing.** The brand payload and flow bundle cache aggressively. Hard
refresh. Verify what is actually being served with:

    curl -s https://auth.avrana.net/if/flow/default-authentication-flow/ | grep -oE 'branding_logo[^,]{0,90}|Welcome to Avrana!'

**Broken-image icon where the wordmark should be.** Something has set `branding_logo` to a value
that is not a path starting with `/`. See the data-URI note above.

Backup of the pre-change brand record and flow titles:
`/mnt/avrana_media/.backups/authentik-branding-20260821T201629Z/branding.PRE.json`


## Session lifetime & passkeys

Session duration, remember-me, network/GeoIP binding and passkey (Face ID) login are documented separately in **[Authentik sessions & passkeys](../../docs/services/authentik-sessions-passkeys.md)** (updated 2026-08-28).

## SSO experience across services

Which tiles open with no extra click, which still show an SSO button and why, Jellyfin OIDC vs LDAP, logout semantics and emergency local logins are documented in **[Avrana SSO Architecture](../../docs/services/sso-architecture.md)** (2026-08-28).
