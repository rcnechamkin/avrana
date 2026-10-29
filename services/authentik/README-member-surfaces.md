# Authentik's member-facing surfaces: invisible identity

Owner decision, 2026-10-28:

> Members should never be thinking about "Authentik". They should never be rerouted to an Authentik page. If we have to
> send people to Authentik, they at least shouldn't even know that it's Authentik. Keep it visually consistent.

Media Home (`avrana.net`) owns every screen a member reads or manages (`docs/design/ME-ACCOUNT-SECURITY.md`). This
file lists every place a member can still meet `auth.avrana.net`, and what makes each one look and behave like Avrana.
**Nothing here is applied.** Each step below needs the owner's approval for that step, after a backup (`AGENTS.md`).

## The surfaces

| Where a member meets it | What it is | What makes it Avrana |
| --- | --- | --- |
| Sign-in (also after sign-out and after a password reset) | `default-authentication-flow` | Brand CSS in Home's Concept K dress (below); flow title "Welcome to Avrana!" |
| Joining (invite link) | `avrana-invite` | Brand CSS; ends with a redirect to `avrana.net` (already) |
| Forgot password | `avrana-recovery` | Brand CSS; **now ends with a redirect to `avrana.net`** instead of Authentik's own pages |
| Change password, add passkey / authenticator, backup codes | `avrana-password`, `avrana-passkey`, `avrana-authenticator`, `avrana-backup-codes` (new, `blueprints/avrana-account.yaml`) | One card each, brand CSS, own titles, each confirms the current password first and **redirects back to the Home page that started it** |
| Sign out | `avrana-sign-out` (new) on the portal provider | Ends the Authentik session as well (reopening Avrana asks to sign in, as members expect), then goes straight back to `avrana.net`: no "You've logged out" page |
| Authentik's user dashboard `/if/user/` | Authentik's app launcher and settings | **Never linked by Home any more**, and redirected away by the Cloudflare rule below for anyone who lands on it (bookmark, typing the host, a flow ending without a destination) |
| OIDC sign-in buttons (Audiobookshelf, Komga, requests) | Implicit consent, so normally a flash of the sign-in card at most | Brand CSS |

## Owner steps, in order

1. **Back up** the brand record and flows (`brand/brand_css_change.py backup`, plus `ak export_blueprint` or a database
   snapshot per `docs/OPERATIONS.md`).
2. **Apply the blueprints**: copy `blueprints/avrana-account.yaml`, `avrana-portal.yaml`, `avrana-recovery.yaml` and
   `avrana-landing.yaml` to the host's blueprint folder; the worker applies changed files. `avrana-portal.yaml` asks for
   `avrana-account.yaml` first (meta-apply). Check Admin → Flows lists the five new flows and the portal provider's
   invalidation flow is `avrana-sign-out`.
3. **Check each flow with a test member** (not your own account), in a private window:
   - `https://auth.avrana.net/if/flow/avrana-password/` → asks for the current password, then a new one twice, then lands
     on `https://avrana.net/me/security/done/password`. Sign out and back in with the new password.
   - `…/avrana-passkey/` → password, then the passkey prompt; lands on `/me/security/done/passkey`. Sign out, sign in
     **with the passkey** (it must be accepted at sign-in, not only enrolled).
   - `…/avrana-authenticator/` → password, QR code and setup key, a code; lands on `/done/totp`. Sign in with a code.
   - `…/avrana-backup-codes/` → password, the codes; lands on `/done/recovery_codes`. Sign in with one code.
   - Sign out from Avrana → you see the Avrana sign-in screen; reopening `avrana.net` asks you to sign in.
   - "Forgot password?" → email → new password → you land on the Avrana sign-in screen.
   - Look for the word "authentik" on every screen above, including the browser tab title. Report any.
4. **Tell Home about the flows** (Home's env): `HOME_SECURITY_FLOWS=password=avrana-password,passkey=avrana-passkey,
   totp=avrana-authenticator,recovery_codes=avrana-backup-codes`, then recreate Home (dry-run first).
5. **Add the Cloudflare redirect rule** (Cloudflare dashboard → avrana.net zone → Rules → Redirect Rules → Create):
   - When: `http.host eq "auth.avrana.net" and (starts_with(http.request.uri.path, "/if/user") or http.request.uri.path eq "/")`
   - Then: static redirect, 302, to `https://avrana.net/me`, query string not preserved.
   Effect: the dashboard and the bare host send everyone to Home's Me page. **Cost:** you lose `/if/user/` too; use the
   admin interface (`/if/admin/`) for your own account, which the rule leaves alone. Roll back by disabling the rule.
   `cloudflared` ingress cannot redirect, which is why this lives in the dashboard; record that it exists in
   `docs/services/cloudflare-tunnel.md` when you add it.
6. **Favicon** (optional, cosmetic): the tab icon on these pages is still Authentik's. `branding_favicon` can't hold a
   data URI; upload Home's `favicon.svg` through Admin → System → Files and set the brand's favicon to it, or leave it.

## Rollback

Restore the brand record with `brand/brand_css_change.py rollback`; revert the four blueprint files from Git (the
worker re-applies them); unset `HOME_SECURITY_FLOWS` in Home; disable the Cloudflare rule. The new flows can stay:
nothing links to them once Home's setting is gone.
