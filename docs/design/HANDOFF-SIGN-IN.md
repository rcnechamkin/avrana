# Hand-off sign-in walls: what each library does, and what can change

Status: **research memo, 2026-10-27.** Source-checked against the versions Avrana pins; nothing was run
against a real service, no setting was changed. Serves AVR-479 (hand-off and recovery), AVR-368/AVR-371
(Jellyfin single sign-on) and the "SSO login walls" left open by the live beta. Complements section 4 of
[`CONTINUE-AND-HANDOFF.md`](CONTINUE-AND-HANDOFF.md) and [`docs/services/sso-architecture.md`](../services/sso-architecture.md).

## Answer

**No library returns a member to the item after signing in.** Each one drops the target and lands on its
own start page. That is upstream behaviour, so no change in Avrana Home can fix it: Home already links to
the exact item (`contract.HANDOFF_BASE`), and the Help text "After signing in, the library may show its
start page instead of the item. Come back to Avrana and choose the item again." (`app/recovery.py`,
section `sign-in`) is accurate for all four libraries and should stay.

What can change is **how often** the wall appears and **how many taps** it costs. Ranked by value for effort:

| # | Change | Who | Effect |
|---|---|---|---|
| 1 | Find out whether the installed iPhone app keeps library sign-ins between hand-offs (test S1 below) | Owner, 5 min | Decides whether everything else matters. If each hand-off from the home-screen app opens a fresh browser sheet with no stored sign-in, members see a wall every time and only true SSO or a longer session helps |
| 2 | Komga: lengthen the 7-day idle session and note that a Komga restart signs everyone out | Owner config | Fewer Comics walls |
| 3 | Do **not** turn on Komga's "auto OAuth2 login" with "hide login" | Owner (a warning) | On iPhone it can leave a blank sign-in page (popup blocked) |
| 4 | Calibre-Web: switch the Books sign-in from LDAP form to CWA's own Authentik OIDC button | Owner config + blueprint | One tap, no password; item still lost |
| 5 | Jellyfin: SSO plugin 4.0.0.4 | Owner decision (the identity migration is done: LDAP is on) | One tap instead of a password; item still lost; native apps unchanged |
| 6 | Small upstream pull requests (Audiobookshelf first) | Optional | Would make the return-to-item work upstream |

## Per library, at the pinned version

### Audiobookshelf 2.36.0 (`listen.avrana.net/item/<id>`)

- An unsigned-in visit to `/item/<id>` is sent to `/login?redirect=/item/<id>`
  (`client/middleware/authenticated.js`).
- With a live session the login page restores it from the stored token and honours `redirect`
  (`client/pages/login.vue` 115-121): **the deep link works.**
- With an expired session, auto-launch (on in production, `authOpenIDAutoLaunch`) starts OIDC with
  `callback=` the login page's address **with its query removed** (`login.vue` 134-135:
  `location.href.split('?').shift()`). The server appends `?setToken=…&accessToken=…` to that callback
  (`server/Auth.js` 274), the login page stores the token (`login.vue` 314-317) and, with no `redirect`
  left, goes to the library home (125). **The item is lost.** With a live Authentik session this is silent
  (implicit consent), so the member just lands on the Audiobookshelf home.
- How often: refresh token 30 days by default (`REFRESH_TOKEN_EXPIRY`, `server/auth/TokenManager.js` 17),
  rotated on use (212), so 30 days of *inactivity* per browser. Access token 1 hour (19).
- Not recommended: linking Home straight to `/auth/openid?callback=…/login%3Fredirect%3D…`. It relies on
  the server's `?` being parsed inside `redirect`, puts the old token in the history, and forces an
  Authentik round trip and a new Audiobookshelf session on every hand-off.
- Upstream fix (small, optional): keep `redirect` in `openidAuthUri` and have `handleLoginSuccessBasedOnCookie`
  join with `&` when the callback already has a query. The callback is already checked as same-origin
  (`OidcAuthStrategy.isValidWebCallbackUrl`, 514).

### Komga 1.25.0 (`read.avrana.net/book/<id>`)

- An unsigned-in route goes to the startup/login view with `redirect=` (`komga-webui/src/router.ts` 334-336);
  only the **password form** honours it (`LoginView.vue` 306-307).
- The Avrana (OAuth2) button opens a **popup window** (`LoginView.vue` 259-265). On success the server
  always sends it to `/?server_redirect=Y` (`SecurityConfiguration.kt` 138, `defaultSuccessUrl(…, true)`),
  and the popup sends the opener to the site root and closes (`router.ts` 320-331). **The item is lost.**
  The portal's direct `GET /oauth2/authorization/authentik` has the same fixed landing page.
- `WEBUI_OAUTH2_AUTO_LOGIN` + `WEBUI_OAUTH2_HIDE_LOGIN` call the same popup from `mounted()`, without a tap
  (`LoginView.vue` 173-185, 256). iOS Safari blocks popups that no tap started, so the page would show no
  form and no window. **Leave both off** unless S3 below proves otherwise.
- How often: idle session 7 days (`application.yml` 62, `server.servlet.session.timeout`); sessions are held
  in memory (`spring-session-caffeine`, `build.gradle.kts` 52), so **every Komga restart signs every member
  out**. Remember-me applies to the password form only. Raising the timeout (for example
  `SERVER_SERVLET_SESSION_TIMEOUT=30d` in the Komga environment) is an owner config change with an obvious
  rollback; restarts would still sign members out.

### Jellyfin 10.11.11 (`watch.avrana.net/web/#/details?id=<id>`)

- **Changed on the host (drift check, 2026-10-28):** Jellyfin now signs members in against Authentik through
  the LDAP plugin (host-only blueprint `jellyfin-ldap.yaml`, not yet in Git), and the owner is one Authentik
  account ("Cody") across the services. The member types their **Authentik** username and password into the same
  jellyfin-web form; there is still no SSO plugin, and the form still lands on its home page, as recorded for P5.
  `docs/services/jellyfin.md` predates this and needs the same update.
- How often: once per browser storage. Jellyfin web keeps its access token in local storage and tokens do
  not expire by default, so a member who signed in once in that browser is not asked again until they sign
  out or the device entry is removed. This makes test S1 decisive for Jellyfin.
- Single sign-on: `jellyfin-plugin-sso` **4.0.0.4** targets ABI `10.11.0.0` (`build.yaml`), so it fits the
  pinned server. After the Authentik round trip it always loads `/web/index.html` (`SSO-Auth/WebResponse.cs`
  464, 506): **the item is lost** here too. It adds a button through the login disclaimer HTML; it does not
  remove the form. With LDAP in place the account prerequisites of `sso-architecture.md` (Authentik accounts for
  every Jellyfin user, username-case reconciliation) are met; what remains is group mapping and an explicit decision to put a third-party plugin in the main media service's sign-in path. Native and TV apps
  keep local passwords (Quick Connect remains the low-typing option on TVs).

### Calibre-Web-Automated 4.0.6 (`books.avrana.net/book/<n>`)

- Today an LDAP-backed form (`docs/services/sso-architecture.md`).
- CWA 4.0.6 has its own generic OIDC client for providers like Authentik (`cps/oauth_bb.py` 11, 64-66). After
  success it goes to the index (546): **item lost**, but no password.
- Reverse-proxy header sign-in exists (`cps/usermanagement.py` 197-235) and would keep the item (every
  request is authenticated by the header), but **4.0.6 trusts the header from any source** (no trusted-proxy
  or shared-secret check; upstream Calibre-Web added one later). With `10.0.0.218:8083` published on the LAN,
  anyone on the network could sign in as anyone. Only consider it if G1 isolation makes the outpost the sole
  path to CWA, and after an independent review. Recommendation: OIDC.

### Seerr 3.5.1 (request hand-offs)

No OIDC: the routes are Plex, Jellyfin (password and Quick Connect) and local (`server/routes/auth.ts`).
Seerr stays "sign in with your Jellyfin account", which since the LDAP change means the member's Authentik
username and password.

## Tests to add to the physical script (CONTINUE-AND-HANDOFF.md section 6)

| # | Device | Steps | Record |
|---|---|---|---|
| S1 | iPhone home-screen app | Hand off to a movie, sign in to Jellyfin, tap Done. Hand off to a second movie | Asked again? (yes = sheet has no persistent storage) |
| S2 | iPhone home-screen app | Same with an audiobook after `?autoLaunch=0` sign-out | Silent re-sign-in? Lands on the item or the library home? |
| S3 | iPhone Safari | Only if the owner wants to try it: Komga auto OAuth2 login on, signed out, open a Comics hand-off | A window, or a blank page? Turn it back off |
| S4 | Any | Restart Komga, then open a Comics hand-off | Signed out (expected from the in-memory sessions) |

## Not proposed

- Any Avrana-side redirect, token pass-through or "return to item" relay: it would be an open-redirect or
  token-handling surface for a problem only the upstreams can solve.
- Expecting Jellyfin LDAP (now on, see above) to remove the wall: it removes password drift, not the sign-in
  form (`sso-architecture.md`).
- Global single logout: unchanged, see `sso-architecture.md`.
