<!--
DRAFT FOR OWNER REVIEW (AVR-361, S1-6). Not published, not wired into any service, not sent to any member.

NOTE TO THE IMPLEMENTER
- This draft covers the help content that the audit and the charter ask for BEYOND the per-device step
  lists already in services/avrana-portal/portal.py (the HELP table). Do not copy those step lists here;
  link to the per-library help page instead.
- Neutral core plus per-library blocks. Show a block only when the member holds at least one group named
  in its marker. Marker syntax is flat: "if: group" or "if: group-a | group-b", closed by "endif".
  Remove hidden blocks from the response; do not hide them with CSS.
- The neutral core names no library, app or media type. The "I cannot see something" answer must stay
  neutral: it must never confirm that a service exists for other members.
- Structure asked for by the audit (P1, P2) and design system: the help index page gets a page headline;
  each topic page gets a topic headline (h2) naming the topic, then a row of device jump links, then one
  section per device. The topic names are the existing ones: Audiobooks, Movies and TV, Books, Comics,
  Requests. Footer: All help, then Avrana home.
- Placeholders in square brackets are open questions, listed in DECISIONS-NEEDED.md. Do not ship a page
  that still contains one.

Sources (repo paths):
  services/avrana-portal/portal.py (HELP table and sign-in comment at :104-116, routes, 404 copy)
  docs/audits/2026-10-11-web-interface-audit.md (P1 help headings, P2 long help pages)
  docs/design/MEDIA-2.0.md section 1 (help completed: headlines, device jump links, contact route)
  docs/design/DESIGN.md (Help page component, copy rules, "Don't name a service the viewer might not reach")
  docs/services/sso-architecture.md, authentik.md, jellyfin.md, komga.md, calibre-web-automated.md
-->

# Help

## Topics

The help topics are the libraries you have. Each topic page lists the apps for each device, the address
to type and the steps. Open Help from your home page and choose a topic. Only your own topics are listed.
<!-- src: services/avrana-portal/portal.py:100-103 (help tile), :596-600, :610-618 -->

## Which app on which device

On a topic page, a device that has more than one app lists them with the first marked Recommended and
the others marked Alternative. A device that has only one app lists it without a tag. The list below is
the short version. For the steps, open the topic page.
<!-- src: services/avrana-portal/portal.py:627 (tag is added only when a device has more than one client) -->

<!-- if: avrana-videos -->
**Movies and TV.** iPhone and iPad: Swiftfin. Android: Jellyfin. Roku: Jellyfin. Apple TV: Swiftfin.
Windows: Jellyfin Media Player. Fire TV, Google TV, Android TV and NVIDIA Shield:
[OWNER DECISION D-12: Jellyfin or Wholphin as the one recommended television app]. Samsung and LG: Jellyfin
if the television's store has it, otherwise use another device or cast from a phone. A browser works but
is the least reliable option.
<!-- src: services/avrana-portal/portal.py:156-234; docs/onboarding/welcome.md:35-41 -->
<!-- endif -->

<!-- if: avrana-audiobooks -->
**Audiobooks.** iPhone and iPad: AudioBooth. Android: Absorb. Any browser also works.
<!-- src: services/avrana-portal/portal.py:118-154 -->
<!-- endif -->

<!-- if: avrana-books -->
**Books.** Any browser for the library. To read on a Kindle, use the Send to Kindle steps below.
iPhone, iPad and Android: the Kindle app receives what you send. On Android, ReadEra opens downloaded
files if you prefer to download.
<!-- src: services/avrana-portal/portal.py:236-270 -->
<!-- endif -->

<!-- if: avrana-comics -->
**Comics.** Any browser. iPhone and iPad: Panels. Android: Moon+ Reader.
<!-- src: services/avrana-portal/portal.py:297-331 -->
<!-- endif -->

<!-- if: avrana-requests -->
**Requests.** iPhone and iPad: Pocket for Seerr. Android has no recommended app yet; use a browser and
add it to the home screen.
[OWNER DECISION D-14: which group shows the Requests help topic. On main the topic is gated on avrana-requests; PR #4 proposes avrana-videos. This block follows main until the owner decides]
<!-- src: services/avrana-portal/portal.py:272-295 (topic gated on avrana-requests on main) versus :56 (tile gated on avrana-videos); PR #4 branch avr-352-portal-authz-suite re-gates the topic on avrana-videos -->
<!-- endif -->

## Why signing in is not the same everywhere

Avrana is one account. What a sign-in screen looks like depends on where you sign in, and the notes
below describe what to expect for what you can use. A sign-in screen that looks unfamiliar is expected,
not a fault.
<!-- src: docs/services/sso-architecture.md:14-36; services/avrana-portal/portal.py:108-114 -->

<!-- if: avrana-audiobooks -->
- **Audiobooks:** choose the Avrana sign-in button, in the browser and in the apps. Your Avrana password
  applies at once.
<!-- src: docs/services/authentik.md:14, :21; portal.py:109-110 -->
<!-- endif -->

<!-- if: avrana-comics -->
- **Comics, in a browser:** choose the Avrana sign-in button.
- **Comics, in a reader app:** the app asks for your e-mail address and password. The comics service keeps
  its own copy of the password from when your account was created, so changing your Avrana password later
  does not change it.
<!-- src: docs/services/komga.md:13-31; portal.py:298-302, :309-331 -->
<!-- endif -->

<!-- if: avrana-books -->
- **Books:** type your Avrana username and password into the form. There is no Avrana button because the
  library checks your username and password with Avrana each time you sign in. After a password change,
  the library can take a little while to notice.
<!-- src: docs/services/calibre-web-automated.md:11-12, :81-87; docs/services/sso-architecture.md:34 -->
<!-- endif -->

<!-- if: avrana-videos -->
- **Movies and TV:** the apps ask for your Avrana username and password. The TV and phone apps cannot
  show an Avrana button, so this service holds its own copy of the password from when your account was
  created. If you change your Avrana password later, the Movies and TV password stays as it was.
  [OWNER DECISION D-13: what members are told to do to change or reset that separate password]
<!-- src: docs/services/jellyfin.md:11-31; docs/services/authentik.md:18-21; portal.py:110-114 -->
<!-- endif -->

<!-- if: avrana-videos -->
- **Asking for a film or show:** the request site signs in with the same Movies and TV username and
  password, not with an Avrana button.
<!-- src: docs/services/sso-architecture.md:36, :165; docs/services/jellyfin.md:12 -->
<!-- endif -->

<!-- if: avrana-books | avrana-audiobooks | avrana-comics -->
- **Asking for a book or comic:** the request sites show one Avrana button. It signs you in with one
  click and does not ask for a password while your Avrana session is active.
<!-- src: docs/services/sso-architecture.md:53-56 -->
<!-- endif -->

<!-- if: library-contributors -->
- **Adding Audible books:** choose the Avrana sign-in. Amazon sign-in happens on Amazon's own page.
<!-- src: docs/services/authentik.md:16, :23; services/avrana-audible-connector/README.md (Security boundaries) -->
<!-- endif -->

## Forgot your password

[OWNER DECISION D-13: today's route, either an e-mail reset link that is confirmed working, or contacting the owner, who sets a new password by hand]

<!-- src: docs/onboarding/admin-onboarding.md:74-75 (manual reset); services/authentik/blueprints/avrana-recovery.yaml:6-8, :37 (reset flow exists, link expires after 30 minutes); docs/ROADMAP.md:31-33 (mail credential rotation pending) -->

<!-- if: avrana-videos -->
**Movies and TV.** After a new Avrana password is set, the Movies and TV password stays as it was until
it is changed there too.
<!-- src: docs/services/authentik.md:21; services/authentik/blueprints/avrana-recovery.yaml:6-8 -->
<!-- endif -->

<!-- if: avrana-comics -->
**Comics.** After a new Avrana password is set, the password used in a comic reader app stays as it was.
<!-- src: docs/services/komga.md:19-31; services/authentik/blueprints/avrana-recovery.yaml:6-8 -->
<!-- endif -->

To change your password while you are signed in, open Account, then Manage account.
<!-- src: services/avrana-portal/portal.py:574-583 -->

## Something is missing from your home page

Your home page lists what has been set up for your account. Access is set per account.
If something you expected is not there, or a page says it does not exist, ask an admin
to check your account. Use the contact route below.

This is the same for everyone. A missing tile does not mean anything is broken, and the answer will only
describe your own account.
<!-- src: services/avrana-portal/portal.py:10-27 (404 not 403 rule), :678-687 (404 copy); docs/design/DESIGN.md:313, :321 -->

## Asking for something that is missing

<!-- if: avrana-videos -->
- **Films and shows:** Request on your home page, then the film and show option. Search for the title and
  choose Request.
  [UNVERIFIED U-6: whether a film or show request needs approval, and the usual wait]
<!-- src: portal.py:288-294; docs/onboarding/welcome.md:45-46 -->
<!-- endif -->

<!-- if: avrana-books | avrana-audiobooks -->
- **Ebooks and audiobooks:** Request on your home page, then the book option.
  [UNVERIFIED U-7: the steps, the approval rule and the usual wait for book requests]
  [OWNER DECISION D-16: the step-by-step text for book requests, which the repository does not document]
<!-- src: portal.py:57-58; docs/services/shelfarr.md:7-10 -->
<!-- endif -->

<!-- if: avrana-comics -->
- **Comics and manga:** Request on your home page, then the comics option. You can browse, request and
  follow series. Downloads depend on approval.
  [UNVERIFIED U-8: how you learn that a comic request was approved or finished]
<!-- src: portal.py:59; docs/services/omnibus.md:60-67 -->
<!-- endif -->

[OWNER DECISION D-1: where to send a request when no Request tile applies, the support contact route]

<!-- if: avrana-books -->
## Send to Kindle

Set your Kindle address once, then send books from the library. The steps are in Help, under Books,
in the Kindle section. Two things cause most problems.

1. The address must end in the Kindle domain. A mistyped address is not reported by Amazon: books just
   never arrive. The setup page refuses other kinds of address on purpose.
2. Amazon only accepts a book from a sender you have approved. The setup page shows the sender address
   to add under Approved Personal Document E-mail List in your Amazon account. Without it, Amazon drops
   the book.

The address is saved in each of your libraries that can send to a Kindle. To remove it, use the remove
button on the same page.
<!-- src: docs/services/calibre-web-automated.md:90-114; services/avrana-kindle-connector/README.md (Address validation, The Amazon half); services/avrana-kindle-connector/kindle.py:198-199; portal.py:244-250 -->
<!-- endif -->

## What "unavailable" means

Today, when a service is switched off, an app shows its own error and a page can show "That page does
not exist". Neither tells you whether the service is down or whether it is not set up for you.
<!-- src: services/avrana-portal/portal.py:678-687 -->

[OWNER DECISION D-15: the member wording for "this service is unavailable right now", and where an operator notice appears. The charter plans one sentence on the home page, which is not built yet]

## Contact

[OWNER DECISION D-1: the support contact route, an address or a form]

When you write, include which service and device you were using, what you did and what you saw.
Never send your password.
