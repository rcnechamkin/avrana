<!--
DRAFT FOR OWNER REVIEW (AVR-361, S1-6). Not published, not wired into any service, not sent to any member.

NOTE TO THE IMPLEMENTER
- This page is written to be rendered later (for example by the Avrana home application). It has a
  neutral core and per-library blocks. Show a block only when the signed-in member holds at least one
  of the groups named in its marker. Everything outside a block is safe for every member.
- Marker syntax (flat, no nesting): "if: group" or "if: group-a | group-b" (any of), closed by "endif".
  Group names are the Authentik groups the portal already uses. Hidden blocks must be removed from the
  response, not hidden with CSS, so a member never receives text about a service they cannot use.
- The neutral core deliberately names no library, app or media type. Keep it that way.
- Placeholders in square brackets are open questions. They are listed in DECISIONS-NEEDED.md. Do not
  ship a page that still contains one.
- Per-device step lists already exist in the portal help pages. This page links to them and does not
  repeat them.

Sources (repo paths; nothing here is from memory):
  docs/onboarding/welcome.md (opening paragraph, account, sign-in, requests)
  services/avrana-portal/portal.py (HELP table, SERVICES groups, choosers, account page)
  docs/services/authentik.md, docs/services/authentik-sessions-passkeys.md, docs/services/sso-architecture.md
  docs/design/MEDIA-2.0.md sections 1, 2, 6, 9; docs/design/DESIGN.md (copy rules)
-->

# Welcome to Avrana

**DRAFT for owner review. Not published and not final.**

Avrana is a small, private media service shared with friends and family. You have one Avrana account,
and it opens the parts of Avrana that have been set up for you.
<!-- src: docs/onboarding/welcome.md:8, :14-15 -->

## Sign in

1. Go to the Avrana home page: [OWNER DECISION D-11: which address members are told to use for the home page].
2. Sign in with your Avrana username and password. If you added a passkey, such as Face ID, you can use
   that instead of typing the password.
3. Your home page shows tiles for the things you can use. Nothing else is listed. Bookmark it, or add it
   to your phone's home screen.

Staying signed in: a normal sign-in lasts 30 days. Choose the option to stay signed in when it is
offered and it lasts 180 days.
<!-- src: docs/services/authentik-sessions-passkeys.md:21-33, :75-83; docs/onboarding/welcome.md:18 -->

On a shared or borrowed device, signing out of an app does not sign you out of Avrana. The Account page
on your home page has a Sign out link and a Manage account link. Avrana's own documentation points to
the account settings page, opened with Manage account, for signing out of Avrana itself.
[UNVERIFIED U-19: what the Sign out link on the Account page actually ends]
<!-- src: docs/services/sso-architecture.md:142-150 (sign out at the Authentik settings page); services/avrana-portal/portal.py:378-379, :644-647 (Manage account links to Authentik; Sign out is an outpost endpoint, not shown to end the Authentik session) -->

## What you can use

The tiles on your home page are your list. If something is not there, it has not been set up for your
account. That is normal and is not an error.

<!-- if: avrana-videos -->
### Movies and TV

App to install:

| Your device | Install this |
|---|---|
| iPhone or iPad | Swiftfin |
| Android phone or tablet | Jellyfin |
| Roku | Jellyfin |
| Apple TV | Swiftfin |
| Fire TV, Google TV, Android TV, NVIDIA Shield | [OWNER DECISION D-12: Jellyfin or Wholphin as the one recommended television app] |
| Samsung or LG television | Jellyfin, if the television's store has it |
| Windows computer | Jellyfin Media Player |
| Any browser | Works, but it is the least reliable option |

Sign in to the app with your Avrana username and password.
[UNVERIFIED U-1: whether a sign-in code option for televisions is switched on]
Step-by-step instructions for each device
are in Help, under Movies and TV.

One thing to know: the Movies and TV password is a separate copy made when your account was created. If
you later change your Avrana password, the Movies and TV password stays as it was.
[OWNER DECISION D-13: what members are told to do to change or reset that separate password]
<!-- src: services/avrana-portal/portal.py:177-255 (recommended = first listed, per render_help_page :627); docs/onboarding/welcome.md:35-43; docs/services/jellyfin.md:19-31; docs/services/authentik.md:21 -->
<!-- endif -->

<!-- if: avrana-audiobooks -->
### Audiobooks

App to install: AudioBooth on iPhone and iPad, Absorb on Android. In a browser, open the audiobook
library and choose the Avrana sign-in button. In the apps, add the server address from Help and choose
the Avrana sign-in option. Password changes made on your Avrana account apply here straight away.
<!-- src: services/avrana-portal/portal.py:139-175; docs/services/authentik.md:12-21 -->
<!-- endif -->

<!-- if: avrana-books -->
### Ebooks and Send to Kindle

Open the ebook library in a browser and sign in with your Avrana username and password. This library
shows a username and password form, not an Avrana button. To read on a Kindle or in the Kindle app, set
your Kindle address once on the Kindle setup page (the Read tile on your home page leads to it).
That page also tells you which sender address to approve in your Amazon account. Without that approval,
Amazon silently drops the book.
<!-- src: services/avrana-portal/portal.py:257-291; docs/services/calibre-web-automated.md:12, :90-114; services/avrana-kindle-connector/kindle.py:311-312 -->
<!-- endif -->

<!-- if: avrana-comics -->
### Comics and manga

In a browser, open the comics library and choose the Avrana sign-in button. In a comic reader app,
use Panels on iPhone and iPad or Moon+ Reader on Android, add the catalog address from Help, and sign
in with your Avrana e-mail address and password.
[UNVERIFIED U-3: whether every comics member has the separate app password that catalog sign-in needs]
<!-- src: services/avrana-portal/portal.py:318-352; docs/services/komga.md:13-53 -->
<!-- endif -->

<!-- if: avrana-videos -->
### Asking for a film or show

Choose Request on your home page, then the film and show option. Search for the title and request it.
It appears in Movies and TV once it has been added.
<!-- src: services/avrana-portal/portal.py:56, :100-101; docs/onboarding/welcome.md:45-46 -->
<!-- endif -->

<!-- if: avrana-books | avrana-audiobooks -->
### Asking for an ebook or audiobook

Choose Request on your home page, then the book option. Sign in with the single Avrana button.
[UNVERIFIED U-7: whether a book request needs the owner's approval and how long fulfilment normally takes]
<!-- src: services/avrana-portal/portal.py:57-58; docs/services/sso-architecture.md:32-35, :53-56 -->
<!-- endif -->

<!-- if: avrana-comics -->
### Asking for a comic or manga

Choose Request on your home page, then the comics option. Sign in with the single Avrana button.
Downloads depend on approval.
[UNVERIFIED U-8: how a member is told a comic request was approved, and the usual wait]
<!-- src: services/avrana-portal/portal.py:59; docs/services/omnibus.md:60-67 -->
<!-- endif -->

<!-- if: library-contributors -->
### Adding your own Audible books

Open the Contribute tile. You sign in to Amazon on Amazon's own page, and Avrana never sees your Amazon
password. You can disconnect at any time.
<!-- src: docs/onboarding/welcome.md:48-49; services/avrana-audible-connector/README.md (Account removal) -->
<!-- endif -->

## Getting help

Every library has a Help page with the app, the address to type and the steps for each device. Open Help
from your home page.

If something is missing, broken or confusing, contact: [OWNER DECISION D-1: the support contact route, an address or a form].
Say which service you were using, what you did and what you saw. A screenshot helps.

## If something seems down

[OWNER DECISION D-15: what members are told when a service is unavailable, since the planned operator notice on the home page is not built yet]

While that is open, the safe general advice is to wait a few minutes, try again, and then use the
contact route above.
<!-- src: docs/design/MEDIA-2.0.md:48-60 (notice is planned, not built), :150-158 (planned degradation copy) -->

## Your account

Your name, username, e-mail address and the list of what you can use are on the Account page. Your
password, passkeys and active sessions are managed there too. What Avrana records about your use, and
how to leave, are in [House rules and privacy](house-rules-and-privacy.md).
<!-- src: services/avrana-portal/portal.py:597-654; docs/member/house-rules-and-privacy.md -->

Forgot your password? [OWNER DECISION D-13: current reset route, e-mail reset or contact the owner]
