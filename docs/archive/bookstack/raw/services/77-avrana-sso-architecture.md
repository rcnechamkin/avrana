---
bookstack_page_id: 77
title: "Avrana SSO Architecture"
shelf: "Avrana Homelab"
book: "Services"
chapter: ""
created: 2026-08-28 17:05:01
updated: 2026-08-28 17:05:01
last_editor: "Cody"
revisions: 1
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/sso-architecture.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-28; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/sso-architecture.md`.

# Avrana SSO Architecture
# Avrana SSO Architecture

How a member gets from `avrana.net` into a service, and why some tiles still show one extra
button. Audited and updated **2026-08-28**. Companion to
[Authentik & SSO](/books/services/page/authentik-sso) and
[Authentik sessions & passkeys](/books/services/page/authentik-sessions-passkeys).

## The model

**Authentik is the only identity provider.** The portal at `avrana.net` sits behind Authentik's
embedded proxy outpost, so reaching the tile grid at all already proves an Authentik session. Each
tile then 307s to a service. Where the service can start its own OIDC flow from a plain link, the
tile points at that start URL instead of the service root — so a live Authentik session lands the
member inside the app with nothing to click.

Portal routing lives in `services/avrana-portal/portal.py`: `SERVICES` maps group → tile, and
`SSO_INIT` overrides the redirect target for services that support GET-initiated SSO.

## Per-service behaviour

| Service | Tile | Auth mechanism | Silent SSO | Why |
|---|---|---|---|---|
| Komga | Comics | OIDC | **Yes** | `GET /oauth2/authorization/authentik` works |
| Audiobookshelf | Listen | OIDC | **Yes** | `authOpenIDAutoLaunch` redirects itself |
| Avrana Portal | avrana.net | Authentik proxy | **Yes** | outpost authenticates before the app |
| Kindle connector | Kindle | Authentik proxy | **Yes** | same |
| OliveTin | Operations | Authentik proxy | **Yes** | same (admin-only) |
| Omnibus | Request → Comics | OIDC | No | sign-in is POST + NextAuth CSRF |
| Shelfarr | Request → Books | OIDC | No | sign-in is POST + Rails CSRF |
| Calibre-Web | Books | LDAP form | No | no SSO flow exists; own login form |
| Jellyfin | Watch | **local accounts** | No | **no OIDC plugin installed** |
| Seerr | Request → Movies & TV | Jellyfin credentials | No | 3.4.1 has no OIDC support |

QuarterMaster is **not deployed** (no container); a stale `QM` Jellyfin API key survives it.

## Direct SSO initiation, verified

Endpoints were probed against the deployed versions on 2026-08-28, not assumed:

```
Komga     GET  /oauth2/authorization/authentik  -> 302 Authentik      USABLE
Shelfarr  GET  /auth/oidc                       -> 404               not usable
Shelfarr  POST /auth/oidc  (no token)           -> InvalidAuthenticityToken
Omnibus   GET  /api/auth/signin/oidc            -> 302 back to /login?error=oidc
Omnibus   POST /api/auth/signin/oidc + csrf     -> 302 Authentik      same-origin only
ABS       root                                   -> client auto-launches
```

Shelfarr and Omnibus both require a **same-origin POST carrying a CSRF token**. A cross-site link
from the portal cannot supply one, and faking it would mean scraping a token from their login page
on every click — exactly the fragile mechanism to avoid. They keep one SSO button. That button is a
single click against an already-valid Authentik session, so it never asks for a password.

## Jellyfin: OIDC vs LDAP

**There is no Jellyfin OIDC today.** The `jellyfin` entry in Authentik is a *link-only* application
with no provider attached. Jellyfin authenticates against its own local accounts, seeded by
**credential replication** at signup — a copy of the password, frozen at that moment. An Authentik
password change does **not** reach Jellyfin.

Installed plugins: `LDAP Authentication 23.0.0.0` — present but **unconfigured** (no config file in
`plugins/configurations/`). No SSO/OIDC plugin is installed.

### LDAP was NOT enabled, and this is why

Enabling LDAP authentication would make Authentik the password authority for Jellyfin — genuinely
useful. But the two user sets have diverged, measured 2026-08-28:

| Jellyfin user | In Authentik? | Has `avrana-videos`? | Effect if LDAP became authoritative |
|---|---|---|---|
| Audrey | **no** | — | loses access |
| Cody | **no** | — | loses access (admin) |
| Jared | **no** | — | loses access |
| Tyler | **no** | — | loses access |
| Collinyourmom | yes | **no** | denied by group filter |
| Navarreheard, Rachel, mvjones | yes | yes | fine |

Four active Jellyfin users have **no Authentik account at all**, and a fifth lacks the video group.
Turning LDAP on without reconciling those identities would lock them out, and any username casing
difference would make the plugin create a **duplicate** Jellyfin user — which would in turn corrupt
Seerr's user sync, since Seerr derives its accounts from Jellyfin.

**Verdict: LDAP is useful in principle but not safe to enable in the current state.** It is also
worth being clear that LDAP would **not** deliver the goal of this work — it is a login *form*
backed by Authentik, not browser SSO. It removes password drift; it does not remove a login screen.

Prerequisites before revisiting: create Authentik accounts for Audrey, Cody, Jared and Tyler;
decide whether Collinyourmom should hold `avrana-videos`; confirm username casing matches exactly.

### What real Jellyfin SSO would require

A third-party plugin (`jellyfin-plugin-sso`) plus a new Authentik OIDC provider. That adds an
external dependency to the authentication path of the primary media service, and the plugin has
historically lagged Jellyfin releases (running 10.11.11). **Not installed** — it is an
architectural addition, not a configuration change, and wants an explicit decision.

## Provisioning and group mapping

Access is gated by Authentik group policy on each application, unchanged by this work:

| App | Group |
|---|---|
| Komga, Omnibus | `avrana-comics` |
| Audiobookshelf | `avrana-audiobooks` |
| Calibre-Web, Kindle | `avrana-books` |
| Shelfarr | `avrana-books` or `avrana-audiobooks` |
| Jellyfin, Seerr (tiles) | `avrana-videos` |
| Portal | `avrana-users` |
| OliveTin | `authentik Admins` |

The portal returns **404, never 403**, for a service the member's groups don't permit — no hint the
service exists. ABS auto-registers OIDC users matched by email (`authOpenIDMatchExistingBy: email`),
so no duplicate accounts are created for existing members.

## Emergency local login (administrators only)

Do not publish these to members.

| Service | Escape route |
|---|---|
| Audiobookshelf | `https://listen.avrana.net/login?autoLaunch=0` — bypasses auto-launch, shows the local form. `local` remains in `authActiveAuthMethods`, and the root account is intact. |
| Komga | Local admin account still valid at the normal login form |
| Jellyfin | Local accounts are the *only* mechanism — nothing to bypass |
| Seerr | `localLogin: true` — local sign-in retained |
| Calibre-Web | Local admin account (LDAP is an additional backend, not a replacement) |
| Authentik itself | `akadmin`, plus the recovery flow `avrana-recovery` |

**To disable ABS auto-launch entirely** (debugging):
```
curl -X PATCH -H "Authorization: Bearer <root-token>" -H 'Content-Type: application/json' \
  -d '{"authOpenIDAutoLaunch": false}' http://10.0.0.218:13378/api/auth-settings
```
Pre-change settings are saved in `services/audiobookshelf/backups/auth-settings-pre-autolaunch-*.json`.

**To disable portal SSO initiation**: remove the entry from `SSO_INIT` in `portal.py` and rebuild.
The tile falls back to the service root and its own login page.

## Logout semantics — read this before assuming you are signed out

**Signing out of an application does not sign you out of Avrana.** Each app clears only its own
session. The Authentik session survives, so reopening the app silently signs you straight back in —
and with the current 30/180-day session that state persists for months.

This is expected, not a bug, but it means **"log out" on a shared device is not sufficient**. To
actually leave, sign out of Authentik at `https://auth.avrana.net/if/user/#/settings`, or have an
admin delete the session under *Directory → Users → Sessions*.

Global single logout (OIDC back-channel) is **not** implemented. It would need every app to honour
back-channel logout; Jellyfin and Seerr can't participate at all, so it would be partial and
misleading. Deliberately left alone.

## Native clients are unaffected

Browser SSO changes nothing for native apps, which keep their own credential flows:

| Client | Authentication |
|---|---|
| Jellyfin apps (Swiftfin, Streamyfin, Findroid, TV apps) | Jellyfin local username/password |
| AudioBooth / Absorb / ABS mobile | ABS OIDC via `audiobookshelf://oauth`, `AudioBooth://oauth` mobile redirect URIs — unchanged |
| Komga OPDS readers (Panels, Moon+) | OPDS URL + Komga credentials |
| Pocket for Seerr | Seerr/Jellyfin credentials |

ABS mobile redirect URIs were **not** modified; auto-launch is a web-client behaviour driven by
`authFormData`, and the mobile flow uses `/auth/openid/mobile-redirect` regardless.

## Troubleshooting redirect loops

1. **Loop between app and Authentik** — usually a `redirect_uri` mismatch. Compare what the app
   sends against the provider's allowed list:
   `read.avrana.net` must send `https://read.avrana.net/login/oauth2/code/authentik`, which is
   registered `strict` in Authentik. An app reached by LAN IP will send the *IP* redirect_uri.
2. **Bounced back to the login page** — the member lacks the application's group. Authentik denies
   at the authorization flow. Check group membership, not the SSO wiring.
3. **ABS keeps redirecting** — append `?autoLaunch=0` to reach the local form, then check the OIDC
   settings under Settings → Authentication.
4. **Verify a chain without a browser**:
   `curl -sL -o /dev/null -w '%{num_redirects} %{url_effective}\n' <url>` — a healthy
   unauthenticated Komga start is **2 redirects** ending at the Authentik flow.
