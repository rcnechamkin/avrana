#!/usr/bin/env python3
"""Avrana portal — the role-aware front door served at avrana.net.

It sits BEHIND Authentik's embedded proxy outpost: the outpost authenticates the user (the
application is gated by the `avrana-users` group), then reverse-proxies to this service with the
user's identity injected as `X-authentik-*` request headers. This process reads
`X-authentik-groups` and renders ONLY the tiles the user's groups permit — a user with fewer
services simply sees a smaller grid that looks complete, with no hint that anything is hidden.

Routes:
  /              the role-aware grid
  /watch /listen /comics /books /requests /contribute
                 short, memorable single-domain entry points. Each one is gated on the same
                 group as its tile and then redirects to the service's own hostname. The
                 per-service subdomains stay as-is for native clients (AudioBooth, Jellyfin
                 apps, Komga readers); these paths are the human/web way in.
  /account       who you are signed in as, what you have access to, and the links to manage
                 the account or sign out (both handled by Authentik).
  /healthz       liveness

Deliberately a redirect and not a reverse proxy: serving Jellyfin/ABS/Komga under a path prefix
would mean per-app base-URL reconfiguration plus websocket + range-request proxying, which is not
something to hand-roll on stdlib http.server. Each service already enforces its own Authentik
gate, so the redirect loses nothing.

A user who lacks the group for a route gets a plain 404, not a 403 — same principle as the grid:
nothing hints that a service exists but is withheld.

Security model: this service has NO published port; it is reachable only on Authentik's internal
docker network, so nothing bypasses the outpost. The outpost strips any client-supplied
`X-authentik-*` headers and sets its own, so the group header is trustworthy here. Redirect
targets come from the fixed table below and never from request input, so there is no open
redirect.

Stdlib only (no deps) — it's a tiny render-a-string server behind the outpost.

Identity mode (AVR-498, OFF by default). AVRANA_IDENTITY_MODE selects where identity comes from:
  headers       (default, and the only mode used today) the plain X-authentik-* headers, as always.
  jwt_log_only  still serves from the headers, but also verifies X-authentik-jwt and writes one fixed
                reason code per request to stderr ("ok", "mismatch", or a rejection code). Never a token,
                name or group.
  jwt_required  identity only from the verified token (portal_jwt.py, HS256); any failure means no
                identity, which is exactly what an empty group header means today (404 on gated routes).
The JWT modes need AVRANA_JWT_ISSUER, AVRANA_JWT_AUDIENCE and AVRANA_JWT_SECRET (owner-provided, never in
this repository). An unknown mode or missing JWT setting stops the service at start. Nothing sets a JWT mode.
"""
from __future__ import annotations

import html
import importlib.util
import os
import sys
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# group -> (label, description, path, subdomain). Every entry here is a DIRECT service: its
# route 307s straight to that hostname. Comics and Books keep their own direct routes so native
# clients and old links still work, even though the home grid now reaches them via a chooser.
SERVICES = [
    ("avrana-videos",        "Watch",      "Movies &amp; TV",              "watch",      "watch.avrana.net"),
    ("avrana-audiobooks",    "Listen",     "Audiobooks",                   "listen",     "listen.avrana.net"),
    ("avrana-comics",        "Comics",     "Comics &amp; manga",           "comics",     "read.avrana.net"),
    ("avrana-books",         "Books",      "Ebooks &amp; Send&nbsp;to&nbsp;Kindle", "books", "books.avrana.net"),
    ("avrana-books",         "Kindle",     "Set your Send&#8209;to&#8209;Kindle address", "kindle", "kindle.avrana.net"),
    # The three request services. Each is gated on the group for the LIBRARY it feeds, so the
    # ability to ask for a thing tracks the ability to consume it: Seerr fills Jellyfin
    # (avrana-videos), Shelfarr fills CWA + Audiobookshelf, Omnibus fills Komga.
    # They keep their own direct routes; the home grid reaches them via the Request chooser.
    ("avrana-videos",        "Movies &amp; TV", "Ask for a film or show",  "requests",   "request.avrana.net"),
    (("avrana-books", "avrana-audiobooks"),
                             "Books",      "Ask for an ebook or audiobook", "requestabook", "requestabook.avrana.net"),
    ("avrana-comics",        "Comics",     "Ask for a comic or manga",     "requestacomic", "requestacomic.avrana.net"),
    ("library-contributors", "Contribute", "Add your Audible books",       "contribute", "contribute.avrana.net"),
    # Admin-only. Gated on the same group Authentik gates the app with, so an ordinary
    # member never sees the tile AND /ops 404s for them (see the 404-not-403 rule below).
    ("authentik Admins",     "Operations", "Health, restarts, backups",    "ops",        "ops.avrana.net"),
]

# Direct SSO initiation. A tile normally 307s to the service root; for entries here it 307s to
# the app's own SSO-start endpoint instead, so an existing Authentik session lands the member
# straight inside the app with no "Login with SSO" button to press.
#
# Only endpoints that actually work over a plain GET belong here -- verified 2026-08-28:
#   Komga      GET /oauth2/authorization/authentik  -> 302 to Authentik            USABLE
#   Shelfarr   POST /auth/oidc, CSRF-checked; GET 404s                             NOT usable
#   Omnibus    POST /api/auth/signin/oidc, needs a same-origin NextAuth CSRF token NOT usable
#   ABS        no GET route needed -- authOpenIDAutoLaunch=true redirects itself    n/a
# Jellyfin and Seerr have no OIDC at all (see the SSO architecture doc), so they are absent.
#
# Trade-off: this always runs an OIDC round-trip, even for a member who already holds a session
# in the target app. With a live Authentik session that is two invisible redirects, which is
# cheaper than showing a login screen. It cannot loop: if Authentik denies the group policy the
# member gets Authentik's own error page, and the tile 404s for non-members before we get here.
SSO_INIT = {
    "comics": "https://read.avrana.net/oauth2/authorization/authentik",
}

# A chooser is a tile that opens a SUB-PAGE instead of redirecting: (label, desc, path, members).
# "Read" covers two libraries that are one idea to a reader, so the grid shows one tile and the
# split happens on the next page. Rendered by the same shell, so it inherits the identical look.
CHOOSERS = [
    # The subtitle here is only the FULL form, shown to a viewer who may open every member. What a
    # viewer actually sees is built by chooser_subtitle() from the members they may open, so a
    # books-only member is never told a comics library exists, nor the reverse (AVR-430).
    ("Read", "Comics &amp; ebooks", "read", ["comics", "books", "kindle"]),
    # Note the path is "request" (singular) while Seerr's long-standing direct route stays
    # "requests" (plural) so existing links keep working. They are distinct paths.
    # The subtitle is deliberately MEDIA-AGNOSTIC. A static list like "Movies, books &
    # comics" leaks the existence of services the viewer cannot reach -- someone with only
    # avrana-comics would learn there is a movies service. It was also inaccurate: Seerr
    # covers TV as well as film. Keep any future wording here free of media types.
    # House style: no first person. "Ask for something that's missing", not "we don't have".
    ("Request", "Ask for something that&rsquo;s missing", "request",
     ["requests", "requestabook", "requestacomic"]),
]

# Copy that depends on WHICH of a shared service's groups the viewer holds (AVR-430).
# Request Books is open to ebook readers and audiobook listeners alike, so one static label and
# subtitle ("Books" / "Ask for an ebook or audiobook") told each of them about the other
# library. Key: the gating groups the viewer holds, in the order SERVICES lists them. Holding
# all of them falls back to the table's own (full) wording.
SERVICE_VARIANTS = {
    "requestabook": {
        ("avrana-books",): ("Books", "Ask for an ebook"),
        ("avrana-audiobooks",): ("Audiobooks", "Ask for an audiobook"),
    },
}

# What each chooser member contributes to the chooser tile's subtitle, as a lowercase noun.
# Members absent here (the Kindle address page belongs to Books) add nothing.
CHOOSER_PARTS = {
    "read": {"comics": "comics", "books": "ebooks"},
}

# Grid order for the home page. Entries are service paths or chooser paths.
HOME_ORDER = ["watch", "listen", "read", "request", "contribute", "ops", "help"]

# --- Help ---------------------------------------------------------------------------------
# One page per user-facing library, gated on the SAME group as the service itself, so help for
# something is visible exactly when the thing itself is. Each page 404s for anyone without that
# group, so hiding a tile is never the only protection.
#
# Sign-in differs per service and is taken from the live configuration, not assumed:
#   Audiobookshelf  OIDC is active ('local' + 'openid'), so there is an Avrana sign-in button
#   Komga           OIDC provider registered under the display name "Avrana"
#   Calibre-Web     LDAP (config_login_type=1), so it is a normal username and password form
#   Jellyfin        no OIDC plugin installed, so it uses the Avrana username and password that
#                   were created with the account
#
# Store links were checked before being written down; none are guessed.
HELP = [
    ("avrana-audiobooks", "Audiobooks", "listen.avrana.net", [
        ("iPhone and iPad", [
            ("AudioBooth", "App Store",
             "https://apps.apple.com/us/app/audiobooth-audiobooks-player/id6753017503", [
                "Install AudioBooth from the App Store.",
                "Add server: https://listen.avrana.net",
                "Choose SSO.",
                "Sign in with the Avrana account.",
             ]),
            ("Absorb", "App Store",
             "https://apps.apple.com/us/app/absorb-for-audiobookshelf/id6760673498", [
                "Install Absorb from the App Store.",
                "Add server: https://listen.avrana.net",
                "Choose the Avrana sign-in option.",
             ]),
        ]),
        ("Android", [
            ("Absorb", "Google Play",
             "https://play.google.com/store/apps/details?id=com.barnabas.absorb", [
                "Install Absorb from Google Play.",
                "Add server: https://listen.avrana.net",
                "Choose the Avrana sign-in option.",
             ]),
            ("Audiobookshelf", "Google Play",
             "https://play.google.com/store/apps/details?id=com.audiobookshelf.app", [
                "Install Audiobookshelf from Google Play.",
                "Add server: https://listen.avrana.net",
                "Choose the Avrana sign-in option.",
             ]),
        ]),
        ("Web browser", [
            ("Any browser", None, None, [
                "Go to https://listen.avrana.net",
                "Choose the Avrana sign-in button.",
             ]),
        ]),
    ]),

    ("avrana-videos", "Movies and TV", "watch.avrana.net", [
        ("iPhone and iPad", [
            ("Swiftfin", "App Store", "https://apps.apple.com/us/app/swiftfin/id1604098728", [
                "Install Swiftfin from the App Store.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
            ("Jellyfin Mobile", "App Store",
             "https://apps.apple.com/us/app/jellyfin-mobile/id1480192618", [
                "Install Jellyfin Mobile from the App Store.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        ("Android", [
            ("Jellyfin", "Google Play",
             "https://play.google.com/store/apps/details?id=org.jellyfin.mobile", [
                "Install Jellyfin from Google Play.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        # No store links here on purpose: these are installed from the television's own store,
        # so a phone link would send people to the wrong place.
        ("Roku", [
            ("Jellyfin", None, None, [
                "Open the Roku Channel Store and search for Jellyfin.",
                "Add channel, then open it.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        ("Fire TV and Fire Stick", [
            ("Jellyfin", None, None, [
                "From the Fire TV home screen, search for Jellyfin and install it.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        ("Google TV, Android TV and NVIDIA Shield", [
            ("Jellyfin", None, None, [
                "Open the Play Store on the television and search for Jellyfin.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        ("Apple TV", [
            ("Swiftfin", None, None, [
                "Open the App Store on the Apple TV and search for Swiftfin.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        ("Samsung and LG smart TVs", [
            ("Jellyfin", None, None, [
                "Search the television's own app store for Jellyfin.",
                "If it is not available, use a Roku, Fire Stick or Apple TV instead, or cast "
                "from a phone.",
                "Add server: https://watch.avrana.net",
             ]),
        ]),
        ("Windows", [
            ("Jellyfin Media Player", "jellyfin.org",
             "https://jellyfin.org/downloads/windows/", [
                "Download Jellyfin Media Player from jellyfin.org.",
                "Add server: https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
                "This handles more video formats than a browser, so it is the better choice "
                "on a computer.",
             ]),
        ]),
        ("Web browser", [
            ("Any browser", None, None, [
                "Go to https://watch.avrana.net",
                "Sign in with the Avrana username and password.",
                "Playback in a browser is the least reliable option. Use an app where possible.",
             ]),
        ]),
    ]),

    ("avrana-books", "Books", "books.avrana.net", [
        ("Web browser", [
            ("Any browser", None, None, [
                "Go to https://books.avrana.net",
                "Sign in with the Avrana username and password.",
                "Open a book to read it in the browser, or use the download button.",
             ]),
        ]),
        ("Kindle", [
            ("Send to Kindle", None, None, [
                "Set the Kindle address once at https://kindle.avrana.net",
                "Add cody@avrana.net to the approved sender list on Amazon.",
                "In the library, open a book and choose Send to Kindle.",
             ]),
        ]),
        ("iPhone and iPad", [
            ("Kindle", "App Store",
             "https://apps.apple.com/us/app/amazon-kindle-reading-app/id302584613", [
                "Books sent from the library appear in the Kindle app automatically.",
                "No server address is needed.",
             ]),
        ]),
        ("Android", [
            ("Kindle", "Google Play",
             "https://play.google.com/store/apps/details?id=com.amazon.kindle", [
                "Books sent from the library appear in the Kindle app automatically.",
                "No server address is needed.",
             ]),
            ("ReadEra", "Google Play",
             "https://play.google.com/store/apps/details?id=org.readera", [
                "Download a book from https://books.avrana.net",
                "Open the downloaded file in ReadEra.",
             ]),
        ]),
    ]),

    ("avrana-videos", "Requests", "request.avrana.net", [
        ("iPhone and iPad", [
            ("Pocket for Seerr", "App Store",
             "https://apps.apple.com/us/app/pocket-for-seerr/id6746105104", [
                "Install Pocket for Seerr from the App Store.",
                "Add server: https://request.avrana.net",
                "Sign in with the Avrana username and password.",
             ]),
        ]),
        ("Android", [
            ("Web browser", None, None, [
                "There is no recommended Android app yet.",
                "Open https://request.avrana.net in a browser.",
                "Add it to the home screen for one-tap access.",
             ]),
        ]),
        ("Web browser", [
            ("Any browser", None, None, [
                "Go to https://request.avrana.net",
                "Sign in with the Avrana username and password.",
                "Search for a title and choose Request.",
             ]),
        ]),
    ]),

    ("avrana-comics", "Comics", "read.avrana.net", [
        # Verified WITH admin credentials: /opds/v1.2/catalog returns 200 (Atom). Bare
        # /opds/v2 is a 404 - unauthenticated it returns an OPDS auth document, which is just
        # Komga's challenge for any /opds/** path and misleadingly looks like a real endpoint.
        # OPDS needs HTTP Basic with email + password, and enrollment now replicates those into
        # Komga, so the same Avrana credentials work in comic apps.
        ("Web browser", [
            ("Any browser", None, None, [
                "Go to https://read.avrana.net",
                "Choose the Avrana sign-in button.",
             ]),
        ]),
        ("iPhone and iPad", [
            ("Panels", "App Store",
             "https://apps.apple.com/us/app/panels-comic-reader/id1236567663", [
                "Install Panels from the App Store.",
                "Add a comic service: https://read.avrana.net/opds/v1.2/catalog",
                "Sign in with the Avrana email address and password.",
             ]),
        ]),
        ("Android", [
            ("Moon+ Reader", "Google Play",
             "https://play.google.com/store/apps/details?id=com.flyersoft.moonreader", [
                "Install Moon+ Reader from Google Play.",
                "Add a catalog: https://read.avrana.net/opds/v1.2/catalog",
                "Sign in with the Avrana email address and password.",
             ]),
            ("Librera", "Google Play",
             "https://play.google.com/store/apps/details?id=com.foobnix.pro.pdf.reader", [
                "Install Librera from Google Play.",
                "Add a catalog: https://read.avrana.net/opds/v1.2/catalog",
                "Sign in with the Avrana email address and password.",
             ]),
        ]),
    ]),
]

# Paths that show a warning before handing over, instead of redirecting straight away:
#   path -> (warning, help path)
# Only the portal route is intercepted. watch.avrana.net goes cloudflared -> Jellyfin directly
# with nothing in between, so a bookmark or a native app still reaches it unimpeded - which is
# what you want, since an interstitial in front of an app's API would just break the app.
INTERSTITIALS = {
    "watch": ("It is advised to use the Jellyfin app for the most stable playback.",
              "/help/movies"),
}

# Friendly aliases. "read" is NO LONGER an alias for comics - it is the chooser now, and
# "request" is likewise NO LONGER an alias for Seerr: it is the Request chooser. Seerr keeps
# its own direct route at /requests (plural), so old links still resolve. Aliases are applied
# BEFORE the chooser lookup, so leaving this entry in place made /request 307 straight to
# Seerr and the chooser was unreachable.
ALIASES = {}

GROUPS_HEADER = "X-authentik-groups"
NAME_HEADER = "X-authentik-name"
USERNAME_HEADER = "X-authentik-username"
EMAIL_HEADER = "X-authentik-email"

JWT_HEADER = "X-authentik-jwt"
IDENTITY_MODES = ("headers", "jwt_log_only", "jwt_required")
MAX_USERNAME_LEN = 150
MAX_GROUPS = 64
MAX_GROUP_LEN = 128
MAX_DISPLAY_LEN = 254

AUTH_HOST = "https://auth.avrana.net"
ACCOUNT_URL = f"{AUTH_HOST}/if/user/"      # Authentik's own user settings (password, MFA, sessions)
SIGNOUT_URL = "/outpost.goauthentik.io/sign_out"  # intercepted by the outpost, never reaches us

STYLE = """
  :root{color-scheme:dark;--bg:#000000;--fg:#ffffff;--dim:#9a9a9a;--rule-quiet:#474747;
    --rule-control:#6e6e6e;--rule-strong:#999999;--dim-on-fg:#333333;}
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;}
  body{background:var(--bg);color:var(--fg);font-family:"Times New Roman",Times,"Liberation Serif",Tinos,"Noto Serif",serif;
    -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;min-height:100vh;
    display:flex;justify-content:center;}
  .page{width:100%;max-width:720px;padding:12vh 24px 8vh;display:flex;flex-direction:column;gap:44px;}
  main{display:flex;flex-direction:column;gap:44px;}
  header{text-align:center;display:flex;flex-direction:column;gap:14px;align-items:center;}
  h1{margin:0;font-weight:400;font-size:min(clamp(2.6rem,9vw,4.4rem),calc((100vw - 3rem) / 6.6));
    letter-spacing:0.34em;text-indent:0.34em;line-height:1;overflow-wrap:anywhere;}
  h1 a{color:inherit;text-decoration:none;}
  a:focus-visible{outline:2px solid transparent;box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--fg);}
  .rule{width:64px;height:1px;background:var(--rule-strong);margin-top:6px;}
  .sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
    clip:rect(0,0,0,0);white-space:nowrap;border:0;}
  nav.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;}
  a.tile{display:flex;flex-direction:column;gap:6px;padding:22px 24px;border:1px solid var(--rule-control);
    text-decoration:none;color:var(--fg);background:transparent;overflow-wrap:anywhere;
    transition:background .16s ease,color .16s ease,border-color .16s ease;}
  a.tile .label{font-size:1.7rem;letter-spacing:0.06em;line-height:1.1;}
  a.tile .desc{font-size:0.98rem;color:var(--dim);transition:color .16s ease;}
  a.tile .host{font-style:italic;}
  a.tile:hover,a.tile:focus-visible{background:var(--fg);color:var(--bg);border-color:var(--fg);}
  a.tile:hover .desc,a.tile:focus-visible .desc{color:var(--dim-on-fg);}
  footer nav{display:flex;justify-content:center;gap:26px;flex-wrap:wrap;}
  a.account,a.store{color:var(--fg);text-decoration:underline;text-decoration-color:var(--rule-strong);
    text-decoration-thickness:1px;text-underline-offset:2px;display:inline-block;min-height:44px;
    padding:12px 0;margin:-12px 0;line-height:1.5;}
  a.account:hover,a.account:focus-visible,a.store:hover,a.store:focus-visible{
    text-decoration-color:var(--fg);}
  a.account{letter-spacing:0.03em;font-size:0.9rem;}
  a.store{font-size:0.92rem;align-self:flex-start;padding:8px 0 12px;margin:-8px 0 -14px;}
  dl.facts{margin:0;display:grid;grid-template-columns:auto 1fr;gap:12px 28px;align-items:baseline;}
  dl.facts dt{color:var(--dim);font-size:0.9rem;letter-spacing:0.08em;text-transform:uppercase;}
  dl.facts dd{margin:0;font-size:1.15rem;overflow-wrap:anywhere;}
  ul.access{margin:0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:10px;}
  ul.access li{border:1px solid var(--rule-quiet);padding:6px 14px;font-size:1rem;overflow-wrap:anywhere;}
  section.block{display:flex;flex-direction:column;gap:16px;}
  section.block h2{margin:0;font-weight:400;font-size:1rem;letter-spacing:0.22em;
    text-transform:uppercase;color:var(--dim);}
  h2.topic{margin:0;font-weight:400;font-size:clamp(1.7rem,5vw,2.3rem);line-height:1.15;
    letter-spacing:0.04em;overflow-wrap:anywhere;}
  p.note{margin:0;color:var(--dim);font-size:0.98rem;line-height:1.5;}
  .platform{border-top:1px solid var(--rule-quiet);padding-top:20px;display:flex;flex-direction:column;gap:18px;}
  .platform > h3{margin:0;font-weight:400;font-size:1.35rem;letter-spacing:0.04em;}
  .client{display:flex;flex-direction:column;gap:8px;}
  .client .cname{font-size:1.05rem;}
  .client .tag{color:var(--dim);font-size:0.8rem;letter-spacing:0.14em;text-transform:uppercase;
    margin-left:10px;}
  .client ol{margin:6px 0 0;padding-left:1.3rem;color:var(--dim);font-size:0.98rem;line-height:1.6;}
  .client ol li{margin:4px 0;overflow-wrap:anywhere;}
  .client code{font-family:inherit;color:var(--fg);border-bottom:1px solid var(--rule-quiet);}
  @media (max-width:560px){nav.tiles{grid-template-columns:1fr;}
    .page{padding:9vh 20px 7vh;gap:36px;}main{gap:36px;}
    dl.facts{grid-template-columns:1fr;gap:4px 0;}dl.facts dd{margin-bottom:10px;}}
  @media (prefers-reduced-motion:reduce){a.tile,a.tile .desc{transition:none;}}
"""

SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
<div class="page">
  <header>
    <h1>{heading}</h1>
    <div class="rule"></div>
  </header>
  <main>
{body}
  </main>
  <footer>
    <nav aria-label="Footer">
{footer}
    </nav>
  </footer>
</div>
</body>
</html>
"""

# The hostname is deliberately NOT shown. Readers do not care that "Watch" happens to live at
# watch.avrana.net, and the tile reads cleaner without it. Call sites still pass host= -- it is
# ignored by str.format, and the value is still needed for the redirect target, so the routing
# is unaffected. The .host CSS class is kept for now in case a tile wants it back.
TILE = ('    <a class="tile" href="/{path}">\n'
        '      <span class="label">{label}</span>\n'
        '      <span class="desc">{desc}</span>\n'
        '    </a>')


def parse_groups(raw: str) -> set[str]:
    """Authentik joins groups with '|'; be tolerant of ',' and whitespace too."""
    for sep in ("|", ","):
        raw = raw.replace(sep, "\n")
    return {g.strip() for g in raw.split("\n") if g.strip()}


def _load_jwt_module():
    """Import the vendored verifier next to this file. Only called in the JWT modes."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portal_jwt.py")
    spec = importlib.util.spec_from_file_location("avrana_portal_jwt", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_verifier(env):
    """Build the HS256 verifier from environment-style settings, or raise SystemExit with a message that
    names the missing setting and never a value."""
    missing = [k for k in ("AVRANA_JWT_ISSUER", "AVRANA_JWT_AUDIENCE", "AVRANA_JWT_SECRET") if not env.get(k)]
    if missing:
        raise SystemExit("identity mode needs: " + ", ".join(missing))
    secrets = [env["AVRANA_JWT_SECRET"].encode("utf-8")]
    if env.get("AVRANA_JWT_SECRET_PREVIOUS"):
        secrets.append(env["AVRANA_JWT_SECRET_PREVIOUS"].encode("utf-8"))
    try:
        return _load_jwt_module().OutpostJwtVerifier(
            issuer=env["AVRANA_JWT_ISSUER"], audience=env["AVRANA_JWT_AUDIENCE"], hmac_secrets=secrets)
    except ValueError as exc:
        raise SystemExit(f"identity mode configuration refused: {exc}") from None


def _has_bad_chars(text: str) -> bool:
    for c in text:
        cat = unicodedata.category(c)
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and c != " "):
            return True
    return False


class IdentityRefused(Exception):
    """No verified identity. `reason` is a fixed code, never request content."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def verified_identity(headers, verifier):
    """(groups, name, username, email) from the verified X-authentik-jwt, or IdentityRefused.
    `headers` is an http.client.HTTPMessage. Plain identity headers, if present, must agree with the
    claims; a request mixing a valid token with different headers is refused, not reconciled."""
    tokens = headers.get_all(JWT_HEADER) or []
    if not tokens:
        raise IdentityRefused("missing_header")
    if len(tokens) != 1:
        raise IdentityRefused("duplicate_header")
    try:
        claims = verifier.verify(tokens[0].strip())
    except Exception:  # every verifier failure, expected or not, is the same closed answer
        raise IdentityRefused("unverified_identity") from None
    if not isinstance(claims, dict):
        raise IdentityRefused("unverified_identity")
    user, groups = claims.get("preferred_username"), claims.get("groups")
    if (not isinstance(user, str) or not user or len(user) > MAX_USERNAME_LEN or user != user.strip()
            or _has_bad_chars(user) or "|" in user or "," in user
            or not isinstance(groups, list) or not groups or len(groups) > MAX_GROUPS
            or not all(isinstance(g, str) and g and len(g) <= MAX_GROUP_LEN and g == g.strip()
                       and "|" not in g and "," not in g and not _has_bad_chars(g) for g in groups)):
        raise IdentityRefused("malformed_claims")
    group_set = set(groups)
    sent_user = headers.get_all(USERNAME_HEADER) or []
    sent_groups = headers.get_all(GROUPS_HEADER) or []
    if sent_user and (len(sent_user) != 1 or sent_user[0].strip() != user):
        raise IdentityRefused("identity_mismatch")
    if sent_groups and (len(sent_groups) != 1 or parse_groups(sent_groups[0].strip()) != group_set):
        raise IdentityRefused("identity_mismatch")

    def display(key):
        value = claims.get(key)
        ok = isinstance(value, str) and 0 < len(value) <= MAX_DISPLAY_LEN and not _has_bad_chars(value)
        return value if ok else ""

    return group_set, display("name"), user, display("email")


def allows(spec, groups: set[str]) -> bool:
    """A service's group slot accepts EITHER a single group name or a tuple of them.
    A tuple means "any of these" -- Request Books is reachable by ebook readers and
    audiobook listeners alike, since Shelfarr routes to CWA and ABS respectively."""
    if isinstance(spec, (tuple, list)):
        return any(g in groups for g in spec)
    return spec in groups


def permitted(groups: set[str]):
    return [svc for svc in SERVICES if allows(svc[0], groups)]


def by_path(path: str):
    for svc in SERVICES:
        if svc[3] == path:
            return svc
    return None


def chooser_by_path(path: str):
    for ch in CHOOSERS:
        if ch[2] == path:
            return ch
    return None


def chooser_members(chooser, groups: set[str]):
    """The member services this user may actually see. Empty means the chooser is hidden."""
    out = []
    for mpath in chooser[3]:
        svc = by_path(mpath)
        if svc and allows(svc[0], groups):
            out.append(svc)
    return out


def service_copy(svc, groups: set[str]):
    """(label, description) of a service as THIS viewer should read it."""
    variants = SERVICE_VARIANTS.get(svc[3])
    if variants and isinstance(svc[0], (tuple, list)):
        held = tuple(g for g in svc[0] if g in groups)
        if held in variants:
            return variants[held]
    return svc[1], svc[2]


def chooser_subtitle(chooser, groups: set[str]) -> str:
    """The chooser tile's subtitle, built only from the members this viewer may open."""
    parts = CHOOSER_PARTS.get(chooser[2])
    if parts is None:
        return chooser[1]
    words = []
    for svc in chooser_members(chooser, groups):
        word = parts.get(svc[3])
        if word and word not in words:
            words.append(word)
    if not words:
        return chooser[1]
    text = " &amp; ".join(words)
    return text[0].upper() + text[1:]


def render_home(groups: set[str]) -> str:
    parts = []
    for path in HOME_ORDER:
        ch = chooser_by_path(path)
        if ch:
            # A chooser appears if the user can reach ANY of its members. Someone with only
            # comics still sees one "Read" tile, which looks complete rather than reduced.
            if chooser_members(ch, groups):
                parts.append(TILE.format(label=ch[0], desc=chooser_subtitle(ch, groups),
                                         path=ch[2], host="avrana.net"))
            continue
        if path == "help":
            # Shown to everyone who can see the portal at all. The landing page lists only the
            # topics their groups permit, so an empty-handed member still gets a sane page.
            parts.append(TILE.format(label="Help", desc="Apps &amp; setup guides",
                                     path="help", host="avrana.net"))
            continue
        svc = by_path(path)
        if svc and allows(svc[0], groups):
            label, desc = service_copy(svc, groups)
            parts.append(TILE.format(label=label, desc=desc, path=svc[3], host=svc[4]))
    return SHELL.format(
        title="Avrana",
        style=STYLE,
        heading="AVRANA",
        body=f'  <nav class="tiles" aria-label="Your Avrana services">\n{chr(10).join(parts)}\n  </nav>',
        footer='    <a class="account" href="/account">Account &amp; sign&#8209;in</a>',
    )


def render_chooser(chooser, members, groups=frozenset()) -> str:
    """A sub-page in the identical shell: same type, same rules, one level down."""
    rows = []
    for svc in members:
        label, desc = service_copy(svc, groups)
        rows.append(TILE.format(label=label, desc=desc, path=svc[3], host=svc[4]))
    tiles = "\n".join(rows)
    return SHELL.format(
        title=f"{chooser[0]} · Avrana",
        style=STYLE,
        heading='<a href="/">AVRANA</a>',
        body=f'  <nav class="tiles" aria-label="{chooser[0]}">\n{tiles}\n  </nav>',
        footer='    <a class="account" href="/">Back</a>',
    )


def render_account(groups: set[str], name: str, username: str, email: str) -> str:
    facts = []
    if name:
        facts.append(("Name", name))
    if username:
        facts.append(("Username", username))
    if email:
        facts.append(("Email", email))
    if not facts:
        facts.append(("Signed in", "yes"))
    facts_html = "\n".join(
        f"      <dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd>" for k, v in facts
    )

    # Only what the user HAS — never a list of what they don't, same principle as the grid.
    mine = permitted(groups)
    access_html = "\n".join(f"        <li>{service_copy(svc, groups)[0]}</li>" for svc in mine)
    if mine:
        access_block = (
            '    <section class="block">\n'
            "      <h2>Your access</h2>\n"
            f'      <ul class="access">\n{access_html}\n      </ul>\n'
            "    </section>"
        )
    else:
        access_block = (
            '    <section class="block">\n'
            "      <h2>Your access</h2>\n"
            '      <p class="note msg">Nothing is set up on this account yet. '
            "Ask Cody to add what you need.</p>\n"
            "    </section>"
        )

    body = (
        '  <section class="block">\n'
        "    <h2>Signed in as</h2>\n"
        f'    <dl class="facts">\n{facts_html}\n    </dl>\n'
        "  </section>\n"
        f"{access_block}\n"
        '  <section class="block">\n'
        "    <h2>Preferences</h2>\n"
        '    <p class="note">Your password, two&#8209;factor devices and active sessions are '
        "managed in your Avrana account. Per&#8209;service settings, such as notifications, "
        "live inside each service.</p>\n"
        "  </section>"
    )
    footer = (
        f'    <a class="account" href="{ACCOUNT_URL}">Manage account</a>\n'
        f'    <a class="account" href="{SIGNOUT_URL}">Sign out</a>\n'
        '    <a class="account" href="/">Back</a>'
    )
    return SHELL.format(
        title="Account · Avrana",
        style=STYLE,
        heading='<a href="/">AVRANA</a>',
        body=body,
        footer=footer,
    )


HELP_SLUGS = {"Audiobooks": "audiobooks", "Movies and TV": "movies",
              "Books": "books", "Comics": "comics", "Requests": "requests"}


def help_permitted(groups: set[str]):
    """Help topics this user may see. Same groups as the services themselves, never a second
    permission system to keep in step."""
    return [h for h in HELP if h[0] in groups]


def help_by_slug(slug: str):
    for h in HELP:
        if HELP_SLUGS.get(h[1]) == slug:
            return h
    return None


def render_help_index(topics) -> str:
    tiles = "\n".join(
        TILE.format(label=label, desc="Apps and setup", path=f"help/{HELP_SLUGS[label]}", host=host)
        for _grp, label, host, _plat in topics
    )
    body = (f'  <nav class="tiles" aria-label="Help topics">\n{tiles}\n  </nav>' if tiles else
            '  <section class="block"><p class="note msg">Nothing is set up on this account yet.</p></section>')
    return SHELL.format(title="Help · Avrana", style=STYLE, heading='<a href="/">AVRANA</a>',
                        body=body, footer='    <a class="account" href="/">Back</a>')


def render_help_page(topic) -> str:
    _grp, label, host, platforms = topic
    out = []
    for pname, clients in platforms:
        rows = [f'    <h3>{pname}</h3>']
        for i, (cname, store, url, steps) in enumerate(clients):
            tag = "Recommended" if i == 0 and len(clients) > 1 else ("Alternative" if i else "")
            head = f'<span class="cname">{cname}</span>'
            if tag:
                head += f'<span class="tag">{tag}</span>'
            block = ['      <div class="client">', f'        <div>{head}</div>']
            if store and url:
                # Each source reads differently: "on the App Store", "on Google Play",
                # "from jellyfin.org". One template cannot cover all three.
                phrase = {"App Store": "Get it on the App Store",
                          "Google Play": "Get it on Google Play"}.get(store, f"Download from {store}")
                block.append(f'        <a class="store" href="{url}" target="_blank" '
                             f'rel="noopener noreferrer">{phrase}<span class="sr"> (opens in a new tab)</span></a>')
            block.append("        <ol>")
            for st in steps:
                block.append(f"          <li>{st}</li>")
            block.append("        </ol>")
            block.append("      </div>")
            rows.append("\n".join(block))
        out.append('  <section class="platform">\n' + "\n".join(rows) + "\n  </section>")
    # The topic headline: the page's own name, right after the wordmark h1 so the platforms
    # (h3) never skip a level and a member arriving from a link can tell which help this is.
    body = f'  <h2 class="topic">{label}</h2>\n' + "\n".join(out)
    return SHELL.format(title=f"{label} help · Avrana", style=STYLE,
                        heading='<a href="/">AVRANA</a>', body=body,
                        footer=f'    <a class="account" href="/help">All help</a>\n'
                               f'    <a class="account" href="https://{host}">Open {label}</a>\n'
                               f'    <a class="account" href="/">Back</a>')


def render_interstitial(svc, warning: str, help_path: str) -> str:
    """A deliberate pause before handing off, in the same shell as everything else."""
    _grp, label, _desc, _path, host = svc
    body = (
        '  <section class="block">\n'
        f'    <h2>Before you continue</h2>\n'
        f'    <p class="note msg" role="note">{warning}</p>\n'
        "  </section>\n"
        '  <nav class="tiles" aria-label="Continue">\n'
        f'    <a class="tile" href="https://{host}" aria-label="Understood, continue to {host}">\n'
        f'      <span class="label">Understood</span>\n'
        f'      <span class="desc">Continue to <span class="host">{host}</span></span>\n'
        "    </a>\n"
        f'    <a class="tile" href="{help_path}">\n'
        f'      <span class="label">Set up the app</span>\n'
        f'      <span class="desc">Apps and setup for {label}</span>\n'
        "    </a>\n"
        "  </nav>"
    )
    return SHELL.format(title=f"{label} · Avrana", style=STYLE,
                        heading='<a href="/">AVRANA</a>', body=body,
                        footer='    <a class="account" href="/">Back</a>')


def render_404() -> str:
    return SHELL.format(
        title="Not found · Avrana",
        style=STYLE,
        heading='<a href="/">AVRANA</a>',
        body='  <section class="block">\n'
             '    <p class="note msg">That page does not exist.</p>\n'
             "  </section>",
        footer='    <a class="account" href="/">Back</a>',
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "avrana-portal/1"
    # HTTP/1.0: one request per connection, closed after each reply. Isolation between members
    # relies on that (a connection never carries two identities); do not switch protocol_version
    # without revisiting it. tests/test_portal_authz.py pins this.
    protocol_version = "HTTP/1.0"
    # Drop a client that stalls mid-request instead of pinning a handler thread forever.
    timeout = 15

    def _headers(self, code, length, ctype="text/html; charset=utf-8", location=None):
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def end_headers(self):
        # Every response, including http.server's own error replies, carries these.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send(self, code, body, ctype="text/html; charset=utf-8", location=None):
        data = body.encode("utf-8")
        self._headers(code, len(data), ctype, location)
        if self.command != "HEAD":
            self.wfile.write(data)

    def _hdr(self, name: str) -> str:
        return (self.headers.get(name) or "").strip()

    # Identity mode: set once by main(). The class default is the unchanged header behaviour.
    IDENTITY_MODE = "headers"
    JWT_VERIFIER = None

    @staticmethod
    def JWT_REPORT(code):
        print("identity_jwt=" + code, file=sys.stderr, flush=True)

    def _header_identity(self):
        """The unchanged header-trusting identity: (groups, name, username, email)."""
        # Header lookup is case-insensitive via http.client.HTTPMessage.
        # More than one group header is ambiguous (which one did the outpost set?): grant nothing.
        raw_groups = self.headers.get_all(GROUPS_HEADER) or []
        groups = parse_groups(raw_groups[0].strip()) if len(raw_groups) == 1 else set()
        return (groups, self._hdr(NAME_HEADER), self._hdr(USERNAME_HEADER), self._hdr(EMAIL_HEADER))

    def _identity(self):
        mode = self.IDENTITY_MODE
        if mode == "headers":
            return self._header_identity()
        if mode not in IDENTITY_MODES or self.JWT_VERIFIER is None:
            return (set(), "", "", "")                       # misconfigured: no identity at all
        if mode == "jwt_required":
            try:
                return verified_identity(self.headers, self.JWT_VERIFIER)
            except IdentityRefused:
                return (set(), "", "", "")
        served = self._header_identity()                      # jwt_log_only: serve from the headers
        try:
            verified = verified_identity(self.headers, self.JWT_VERIFIER)
            code = "ok" if (verified[0], verified[2]) == (served[0], served[2]) else "mismatch"
        except IdentityRefused as exc:
            code = exc.reason
        try:
            self.JWT_REPORT(code)
        except Exception:
            pass
        return served

    def do_GET(self):
        route = self.path.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"

        if route == "/healthz":
            return self._send(200, "ok", "text/plain; charset=utf-8")

        groups, name, username, email = self._identity()

        if route == "/":
            return self._send(200, render_home(groups))

        if route == "/account":
            return self._send(200, render_account(groups, name, username, email))

        if route == "/help":
            return self._send(200, render_help_index(help_permitted(groups)))

        if route.startswith("/help/"):
            topic = help_by_slug(route[len("/help/"):])
            # Gated on the topic's own group, so a help page is never reachable just because
            # someone guessed the URL. 404 rather than 403, same as everywhere else.
            if topic is None or topic[0] not in groups:
                return self._send(404, render_404())
            return self._send(200, render_help_page(topic))

        slug = ALIASES.get(route[1:], route[1:])

        # Choosers first: /read renders a sub-page rather than redirecting. Same 404-not-403 rule
        # as everything else -- a user with neither library gets a plain 404, not a hint.
        ch = chooser_by_path(slug)
        if ch:
            members = chooser_members(ch, groups)
            if not members:
                return self._send(404, render_404())
            return self._send(200, render_chooser(ch, members, groups))

        for svc in SERVICES:
            grp, _label, _desc, path, host = svc
            if path == slug:
                # Not in the group -> 404, never 403: no hint the service exists.
                if not allows(grp, groups):
                    break
                warn = INTERSTITIALS.get(path)
                if warn:
                    return self._send(200, render_interstitial(svc, warn[0], warn[1]))
                return self._send(307, "", location=SSO_INIT.get(path, f"https://{host}"))

        return self._send(404, render_404())

    do_HEAD = do_GET

    def log_message(self, *args):  # keep logs quiet; no per-request user data
        pass


def main():
    port = int(os.environ.get("PORT", "8095"))
    mode = os.environ.get("AVRANA_IDENTITY_MODE", "headers")
    if mode not in IDENTITY_MODES:
        raise SystemExit("AVRANA_IDENTITY_MODE must be one of: " + ", ".join(IDENTITY_MODES))
    if mode != "headers":
        Handler.JWT_VERIFIER = build_verifier(os.environ)
    Handler.IDENTITY_MODE = mode
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
