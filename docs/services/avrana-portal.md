# Avrana Portal: avrana.net

> Promoted from the BookStack wiki on 2026-10-04 (page 47, "Avrana Portal: avrana.net", last edited 2026-08-28) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/47-avrana-portal-avrananet.md).

The branded splash at **avrana.net**: plain Times New Roman, white on black, one tile per service
the signed-in user may use (Watch / Listen / Read / Request / Contribute) + Account. A
user with fewer services just sees a smaller grid: no hint anything is hidden.

**How it's gated + made role-aware.** cloudflared (`avrana.net`) → Authentik **embedded proxy
outpost** → the `avrana-portal` service. The outpost authenticates (application gated by the
**`avrana-users`** group) and injects `X-authentik-*` headers; the portal reads
`X-authentik-groups` and renders only the matching tiles (avrana-videos→Watch,
avrana-audiobooks→Listen, avrana-comics/avrana-books→Read, library-contributors→Contribute). Service subdomains stay as-is for native clients.

**Service** (`services/avrana-portal/`): a tiny stdlib Python server, no deps, digest-pinned,
read-only/non-root, on Authentik's `frontend` network with **no published port**: reachable only
via the outpost, so auth can't be bypassed.

**Authentik**: proxy provider `avrana-portal-proxy` (external avrana.net → internal
avrana-portal:8095) + app `avrana-portal` gated by `avrana-users`, added to the embedded outpost
(blueprint + an imperative outpost m2m). Verified: outpost loads avrana.net; role-aware render
confirmed through the outpost.

**Go-live status (2026-08-16):** DNS DONE: old apex A/AAAA deleted, proxied CNAME `avrana.net`
→ tunnel created (`cloudflared tunnel route dns`), resolves to Cloudflare edge IPs. cloudflared
ingress (`avrana.net → localhost:9000`) in place. **Only remaining:** `sudo systemctl restart
cloudflared-avrana.service` to load the ingress, then an end-to-end check (sign-in → correct
tiles). Until that restart, `avrana.net` hits the tunnel catch-all 404.


## Help section (2026-08-17)

`avrana.net/help` plus one page per library: **Audiobooks, Movies and TV, Books, Comics,
Requests**. Written for non-technical members: which app to install per device, the exact server
address, and which sign-in option to pick.

**It reuses the existing permission model rather than adding a second one.** Each topic is keyed
to the SAME Authentik group as the service it documents, and each page re-checks that group on
the request, returning **404**: so a guessed URL is refused, not merely hidden from the menu.
Help itself is visible to anyone who can load the portal; an account with no libraries gets a
page that says so.

Sign-in differs per service and was taken from live config, not assumed:

| Service | Sign-in |
|---|---|
| Audiobookshelf | Avrana button (OIDC active) |
| Komga | button labelled "Avrana" |
| Calibre-Web | username + password (**LDAP**, `config_login_type=1`) |
| Jellyfin | username + password: **no OIDC plugin installed** |

Every store link is verified before being written down. `Get it on the App Store` /
`Get it on Google Play` / `Download from jellyfin.org` are phrased per source.

### Read chooser

Comics and Books are one idea to a reader, so the grid shows a single **Read** tile that opens a
sub-page offering Comics, Books and Kindle. A chooser appears if the user can reach ANY member,
and lists only the members they may see. `/comics` and `/books` keep their own direct routes so
native clients and old links still work.

### Playback warning before Jellyfin

`/watch` shows a short page firs: *the Jellyfin app gives the most stable playback*, then
**Understood** (continue) or **Set up the app** (the help page). Built as a general
`path -> warning` table.

**Only the portal route is intercepted.** `watch.avrana.net` goes cloudflared -> Jellyfin
directly with nothing in between, so a bookmark or native client still reaches it unimpeded :
which is correct, since an interstitial in front of an app's API would break the app.

### Admin tile

An **Operations** tile gated on `authentik Admins` links to the OliveTin console. Ordinary
members see no tile and `/ops` returns 404.

## Request nesting (2026-08-21)

The three request services are now **nested under one Request tile**, mirroring the existing
Read chooser. Before this, only Seerr was on the portal at all — `requestabook` and
`requestacomic` were not exposed anywhere.

| Sub-tile | Service | Gated on | Fills |
|---|---|---|---|
| Movies & TV | Seerr | `avrana-videos` | Jellyfin |
| Books | Shelfarr | `avrana-books` **OR** `avrana-audiobooks` | CWA + Audiobookshelf |
| Comics | Omnibus | `avrana-comics` | Komga |

Permission tracks the library each service feeds: the ability to *ask* for a thing follows the
ability to *consume* it. A `SERVICES` group slot now accepts a **tuple** as well as a string,
applied at **all four** permission checkpoints including route enforcement — hiding a tile is
never the only protection.

Authentik `policy_engine_mode` is `any`, so Shelfarr's two group bindings OR together.
**`avrana-requests` is now unused** (retained, not deleted).

> ⚠ **`ALIASES` resolve BEFORE the chooser lookup.** `{"request": "requests"}` made `/request`
> 307 straight to Seerr, leaving the chooser unreachable. Removed. Seerr keeps its direct
> `/requests` route so old links still work — note singular vs plural.

**Tiles no longer print the hostname.** "Watch" reads *Movies & TV*, not *Movies & TV ·
watch.avrana.net*. Call sites still pass `host=` (ignored by `str.format`) and the value still
drives the redirect, so routing is unaffected. The interstitial still shows the destination
hostname deliberately — that one tells you where you are about to be sent.

## Subtitle wording and the leak rule (2026-08-21)

Chooser subtitles are **static** while tile visibility is **per-group**. A subtitle that
enumerates media types therefore leaks: *"Movies, books & comics"* told a comics-only user that
a movies service existed. Request now reads **"Ask for something that's missing"**.

Two rules for any future copy here:

1. **No first person.** Not "we"/"our"/"us". Phrase as an instruction or neutral noun phrase.
2. **Never name a service the viewer might not reach.** The gating model is 404-not-403; a
   subtitle listing media types undermines it.

**AVR-430 (2026-10-11): the structural fix was made after all.** The earlier decision rested on
comics and ebooks always sharing an access level, which is not true of the groups (`avrana-comics`
and `avrana-books` are separate). Copy that depends on the viewer is now computed from what they
may open: `chooser_subtitle()` builds the Read subtitle from `chooser_members()` ("Comics",
"Ebooks", or "Comics & ebooks"), and `service_copy()` picks the Request Books label and subtitle
by which of its two groups the viewer holds ("Books / Ask for an ebook", "Audiobooks / Ask for an
audiobook", or the full "Ask for an ebook or audiobook" for both). The account note no longer
lists "playback, reading position". `tests/test_portal_authz.py` (`LibraryVocabularyTests`) checks
every page for every identity against a word list per library, written out independently of
`portal.py`.

## Accessibility (AVR-357, 2026-10-11)

Markup and CSS only (sprint item S1-4, `docs/design/DESIGN.md`); routes, gating, statuses,
redirects and headers are unchanged. Interactive edges use the Control Rule (`--rule-control`,
#6e6e6e) and dividers keep `--rule-quiet` (#474747). Every link shows one two-ring focus indicator
(`a:focus-visible`) and no rule removes the outline. `color-scheme: dark` is declared. Footer,
account and store links are 44px targets (padding offset by a negative margin, so the layout does
not move). Pages are `header` / `main` / `footer` with labelled `nav`s, one `h1` (the wordmark),
and help topics open with an `h2` topic headline before their `h3` platforms. Notices carry
no `role="status"` or `role="alert"` (the portal has no live updates: every message is present at
page load, so the 404 line and the empty-state notes are plain paragraphs and the interstitial
warning is `role="note"`); store links that open a new tab say so in a visually hidden span. The account
note and interstitial lose their em dash and first person ("I understand" is now "Understood"), the
interstitial's continue link is named "Understood, continue to watch.avrana.net" (`aria-label`), the
footer `nav` is labelled "Footer", and the store links keep a 44px target without reaching into the
app name above them.
`tests/test_portal_a11y.py` pins all of this for every identity and render function; the axe-core
and screen-width checks wait for the browser harness (S1-5).

### Open for design review

Decisions the accessibility pass left alone because they are composition or token choices owned by
the design team. Nothing here was changed.

- **No topic headline on home, chooser, help index or account.** `docs/design/DESIGN.md` asks for
  one `h1` headline per page; on these pages the wordmark is the `h1` and there is no topic headline
  under it (help topic pages do have an `h2` topic headline).
- **Font stack.** It lacks the metric-compatible fallbacks named in the design tokens.
- **Status colour claim.** DESIGN.md says the status colours are "all above 10:1", but `#ff8b8b` on
  black is 9.32:1. The portal itself uses no status colours.
- **Platform jump-links row.** Raised in review; undecided.
- **Compact wordmark.** Raised in review; undecided.
- **Route name "requestabook".** A member in only the audiobooks group sees a Request tile
  ("Audiobooks / Ask for an audiobook") that links to `/requestabook`. The route name contains
  "book"; it is kept for old links and is not shown as text.
- **Duplicate entries on the account page (pre-existing).** "Your access" lists the label of every
  permitted service, and the Request service for a library reuses that library's label. A member in
  `avrana-books` therefore sees "Books" twice (the Books service and Request Books; the list is
  Books, Kindle, Books). The same happens for `avrana-comics` ("Comics" twice), and for a member
  in both `avrana-books` and `avrana-audiobooks` ("Books" twice, from the Books service and the
  combined Request Books). A member in `avrana-audiobooks` only, or `avrana-videos` only, sees no
  duplicate (Listen / Audiobooks, Watch / Movies & TV).

## SSO experience across services

Which tiles open with no extra click, which still show an SSO button and why, Jellyfin OIDC vs LDAP, logout semantics and emergency local logins are documented in **[Avrana SSO Architecture](../../docs/services/sso-architecture.md)** (2026-08-28).
