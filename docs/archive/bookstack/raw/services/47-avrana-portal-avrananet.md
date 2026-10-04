---
bookstack_page_id: 47
title: "Avrana Portal: avrana.net"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Platform"
created: 2026-08-16 16:38:10
updated: 2026-08-28 17:05:15
last_editor: "Cody"
revisions: 9
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/avrana-portal.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-28; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/avrana-portal.md`.

# Avrana Portal: avrana.net
# Avrana Portal: avrana.net

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
**I understand** (continue) or **Set up the app** (the help page). Built as a general
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

A structural fix — deriving subtitles from `chooser_members()` so they can never drift from
permissions — was offered and **declined**: comics and ebooks always share an access level, so
`Read`'s "Comics & ebooks" is not a leak in this deployment.

## SSO experience across services

Which tiles open with no extra click, which still show an SSO button and why, Jellyfin OIDC vs LDAP, logout semantics and emergency local logins are documented in **[Avrana SSO Architecture](/books/services/page/avrana-sso-architecture)** (2026-08-28).
