# Authentik sessions & passkeys

> Promoted from the BookStack wiki on 2026-10-04 (page 76, "Authentik sessions & passkeys", last edited 2026-08-28) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/76-authentik-sessions-passkeys.md).

How long an Avrana login lasts, and how to sign in with Face ID. Companion to
[Authentik & SSO](../../docs/services/authentik.md). Applied **2026-08-28** on Authentik **2026.5.6**.

Declarative config lives in `services/authentik/blueprints/avrana-session-tuning.yaml` (tracked in Git).
It is auto-applied by the worker; `docker restart authentik-worker` forces a re-apply.
A pre-change snapshot of every value touched is in `services/authentik/backups/pre-session-tuning-*.json`.

## Why login used to be so frequent

The user-facing `default-authentication-login` stage ran at `session_duration = seconds=0`.
Zero does **not** mean "unlimited" — it means a *browser-session cookie*, discarded when the browser
decides the session ended. iOS Safari does that aggressively, so an iPhone was effectively logged out
every time it reaped background tabs. That single value was the whole problem.

## Session lifetime (current)

| Setting | Value | Effect |
|---|---|---|
| `session_duration` | `days=30` | A normal login lasts 30 days |
| `remember_me_offset` | `days=150` | Ticking "remember me" **adds** 150 → **180 days total** |
| `remember_device` | `days=365` | Configured but **currently inert** — see below |
| `terminate_other_sessions` | `false` | Signing in on a new device never kicks out old ones |
| `network_binding` | `no_binding` | Session survives changing IP/network |
| `geoip_binding` | `no_binding` | Session survives changing location |

`remember_me_offset` is an **offset, not a total**: 30 + 150 = 180. A non-zero value is also what makes
the tickbox appear at all — at zero, no prompt is shown.

**Measured, not assumed.** A full login was run end-to-end against a throwaway account on 2026-08-28:
the `authentik_session` cookie came back at **30.0 days** without remember-me and **180.0 days** with it.
The account was deleted afterwards.

### UX change to expect

Because `remember_me_offset` is now non-zero, the final stage of login renders its own screen with a
"remember me" tickbox. Previously that stage was silent. **Login now has one extra tap.** That is the
cost of the 180-day option; it is not a bug.

## Known-device cookie: configured but inert

`remember_device = days=365` is set, but in 2026.5.6 **it never takes effect while remember-me is
enabled**. From `authentik/stages/user_login/stage.py`:

```python
if remember is None:
    return self.set_known_device_cookie(user)
return self.executor.stage_ok()
```

`remember` is `None` only when the remember-me prompt is *not* shown — i.e. only when
`remember_me_offset == 0`. The two features are **mutually exclusive** in this version. Verified: the
completed login flow set no `authentik_device` cookie at all.

**This costs nothing.** `is_known_device()` feeds only `PLAN_CONTEXT_METHOD_ARGS_KNOWN_DEVICE`, which is
**audit metadata on the login event**. It does not extend a session, skip a stage, or bypass MFA. The
180-day session is worth far more than a "known device" flag in the event log. The value is kept so the
intent is recorded and it takes effect immediately if `remember_me_offset` ever returns to 0.

## Network and GeoIP binding

Both pinned to `no_binding`. These are the two settings that would invalidate a session when a phone
moves between home Wi-Fi, cellular and public Wi-Fi. They were already off; they are now **declared
explicitly in the blueprint** so a future change cannot silently switch them on.

**Tradeoff, stated plainly:** a stolen session cookie can be replayed from any network or country. With
a 180-day lifetime that is a real, extended exposure window. This is accepted deliberately — binding a
session to a mobile network is unworkable, since cellular IPs change constantly.

## Passkeys / Face ID

WebAuthn was **already working** before this change — five members had passkeys (four via Apple
Passwords / iCloud Keychain, one via Google Password Manager), used as a *second* factor after a password.

What changed: passkeys can now also be the **first** factor. `default-authentication-identification`
now has `webauthn_stage` set, enabling conditional WebAuthn — Safari offers the iCloud Keychain passkey
inline on the login page, so **Face ID replaces typing the password**.

### The dedicated first-factor stage

`webauthn_stage` points at a new stage, `avrana-passkey-first-factor`, *not* at the existing MFA stage:

| | `default-authentication-mfa-validation` | `avrana-passkey-first-factor` |
|---|---|---|
| Role | second factor (unchanged) | first factor (new) |
| `webauthn_user_verification` | `preferred` | **`required`** |
| Device classes | static, totp, webauthn, duo, sms, email | webauthn only |

**Why a separate stage.** `preferred` is correct for a second factor — the password already proved
knowledge. As a *first* factor it would permit a **possession-only login**: someone holding an unlocked
phone could sign in without Face ID. `required` forces user verification, so the passkey path stays
genuinely two-factor (device + biometric/PIN). The existing MFA stage was left untouched.

### What did NOT change

- **Passwords still work.** The password stage is untouched and remains a separate step.
- **No forced enrolment.** `not_configured_action` stays `skip`, so members without a passkey see no change.
- **No existing MFA weakened.** The second-factor stage is byte-for-byte as it was.
- `resident_key_requirement` stays `preferred` on the enrolment stage. Apple and Google password managers
  create discoverable credentials at `preferred` anyway (proven by the five existing devices), and
  forcing `required` would risk breaking enrolment for hardware keys with limited resident-key slots.

## Manual step: enrol a passkey on the iPhone

Nothing enrols a passkey for you. On the iPhone, in Safari:

1. Go to **https://auth.avrana.net/if/user/#/settings**
2. Open **MFA Devices** → **Add** → **WebAuthn / Security key**
3. Accept the iOS prompt and save to **iCloud Keychain** (Face ID confirms)

Do it in **Safari**, not an in-app browser — the passkey binds to the relying party `auth.avrana.net`,
and iCloud Keychain enrolment is most reliable from Safari itself. Once saved, subsequent logins offer
the passkey automatically on the login page.

## Revoking a session or a device

- **One session** — Admin → *Directory → Users → (user) → Sessions*, delete the row. Effective immediately.
- **All of a user's sessions** — same screen, delete all rows. They are forced to re-authenticate everywhere.
- **A passkey** — Admin → *Directory → Users → (user) → MFA Devices*, delete the WebAuthn device;
  or the member removes it themselves at `/if/user/#/settings`.
- **Everyone, immediately** — set `session_duration` back to a short value and restart
  `authentik-worker`. Existing cookies keep their **already-issued** expiry, so also clear sessions in
  the admin UI if the intent is to force re-login now.
- **A lost or stolen phone** — delete that user's sessions *and* their passkey. Doing only one leaves a
  working way in.

## Security tradeoffs, summarised

| Decision | Gain | Cost |
|---|---|---|
| 30-day session | No constant re-login | Stolen cookie is valid far longer |
| 180-day remember-me | Phone effectively stays signed in | Longer exposure window still |
| No network/GeoIP binding | Survives Wi-Fi ↔ cellular | Session replayable from anywhere |
| `terminate_other_sessions: false` | Devices don't evict each other | Old sessions linger until expiry |
| Passkey as first factor | Face ID instead of a password | Requires `user_verification: required` to stay 2FA |

## Known caveat: `SESSION_COOKIE_SECURE`

Authentik currently runs with `SESSION_COOKIE_SECURE = False`. Externally this is harmless — everything
arrives over HTTPS via the Cloudflare tunnel — but it means the session cookie *may* be transmitted in
clear if Authentik is reached over plain HTTP on the LAN (`http://10.0.0.218:9000`). That mattered
little with browser-session cookies; it matters more now that sessions live 180 days. Not changed here
because enabling it could break LAN access to `:9000`. Worth revisiting.
