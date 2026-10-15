# Media 2.0 member acceptance scenarios

Status: **DRAFT for owner review** (prepared for AVR-479 and AVR-387). Nothing in this file has been run.
It is a test plan, not a result.

## What this is for

AVR-479 asks for a versioned device and service matrix, failure copy, fixture tests and owner-approved
real-device evidence for every handoff. AVR-387 asks three to five consenting members to try the
journey unaided. This file gives both of them one list of scenarios, so fixture tests, local runs, device
checks and the member beta all talk about the same thing.

The journey: **sign in, Home, then Continue, New or Search, then an authorized handoff to Jellyfin,
Audiobookshelf, Komga or Calibre-Web, then Help.**

## What has NOT been tested

Read this before anything else. Do not quote any scenario below as passed.

- **No real device has been used for any of this.** Not an iPhone, not an Android phone, not a desktop
  browser against the new Home, not a television. The iPhone visual review for PRs #23, #24, #26 and #27
  (`avrana-review-kit/CHECKLIST.md`) is still waiting for the owner. It checks looks and VoiceOver on
  fixture pages. It does not check any handoff.
- **No handoff has been tried against a live app.** The link shapes in `services/avrana-home/avrana_home/contract.py`
  (`/web/#/details?id=`, `/item/`, `/book/`) are marked there as unverified against the live apps.
  Whether a phone opens the installed app or the website for each link is unknown.
- **Nothing has run in production.** No member, no real library, no real session.
- **The new Home, Search and title pages are not merged** (PRs #23, #24, #26 are waiting for visual
  approval). Only the Jellyfin adapter exists in `services/avrana-home`. The Audiobookshelf, Komga and
  Calibre-Web adapters are not built. Their scenarios cannot run yet, even on fixtures.
- **Expected wording below is intent.** Where a sentence is quoted it comes from the charter
  (`docs/design/MEDIA-2.0.md` section 5) or the review checklist. Confirm against the built page, and
  against the owner's approved wording (see the owner decisions at the end).
- **Single sign-on is not uniform.** Per `docs/services/sso-architecture.md`, Audiobookshelf and Komga
  sign in silently, Calibre-Web has its own login form, and Jellyfin has its own local account. The
  "sign-in prompt" outcomes below are expected for those two. M2 (AVR-371, AVR-372) may change Jellyfin.
- **No cross-device control is claimed.** Opening a link on a phone does not start playback on a
  television. No scenario here expects it.

## Evidence types

| Code | Meaning | Who can produce it | Counts toward |
|---|---|---|---|
| F | Fixture: automated test, fake upstream, synthetic principal | An agent, offline | Regression only |
| L | Local: the app running on a development machine with fixture upstreams, driven in a browser | An agent, offline | Layout, copy, flow. Not device behaviour |
| D | Real device: a physical phone, tablet or computer the owner or a consenting member holds | The owner or a tester, on a fixture or beta host | AVR-479 evidence, AVR-387 |
| P | Production or beta host with real services | The owner only, with approval for that change | Launch criteria |

A scenario that needs D or P may still carry F and L rows. Passing F or L never stands in for D or P.
A result is recorded as **task success** and **false success** separately. False success means the
member believed it worked and it did not, for example Avrana looked finished while the app showed an error.
Zero false successes is a requirement (AVR-387).

## Synthetic members

Invented names only. No real member, no real account, no real title from anyone's history.

| Id | Groups | Upstream accounts | Used for |
|---|---|---|---|
| M-ALL | avrana-users, avrana-videos, avrana-audiobooks, avrana-books, avrana-comics | All four mapped | The full journey |
| M-VID | avrana-users, avrana-videos | Jellyfin mapped | Single library, hidden others |
| M-BOOK | avrana-users, avrana-books | Calibre-Web mapped | "Books only" Home (checklist H6) |
| M-NOLIB | avrana-users | None | Signed in, no library |
| M-NOLINK | avrana-users, avrana-videos | No Jellyfin account matches | Not linked state |
| M-TWO | avrana-users, avrana-videos | Jellyfin mapped, different history from M-VID | Isolation: no one sees another member's items |
| (none) | no identity headers | n/a | Signed out |

Fixture library items (synthetic): one film and one series episode half watched, one audiobook half
listened, one comic and one ebook unread, one title that exists in two libraries, one title in a library
M-VID cannot use, and one title missing from every library.

## Scenarios

Wording rule for copy in this file: plain sentences, no dashes, no first person.

### A. Sign in and Home

| Id | Preconditions | Steps | Expected member-visible result | Evidence |
|---|---|---|---|---|
| A1 | M-ALL, all upstreams up | Open avrana.net signed out, sign in | Lands on Home, not on a loop. Place links come first (Watch, Listen, Read, Request, Help). Continue and New rows are short. Search is top left, Account top right | F, L, then D (iPhone, Android, desktop), then P |
| A2 | M-BOOK | Sign in, read all of Home | Nothing mentions films, audiobooks or comics: no row, link, word or alt text | F, L, D |
| A3 | M-NOLIB | Sign in | A plain sentence that nothing is set up yet, a way to reach help, and Account. No library names | F, L, D |
| A4 | No identity headers | Open Home | Sign in and Help only. No Search, Account or rows. Never a half page | F, L, D |
| A5 | M-ALL | Open Account, then Sign out | Menu shows who is signed in. Sign out is reachable. Which sessions end is unverified (register U-19), so the result is recorded, not assumed | L, D, P |
| A6 | M-ALL, session expired | Reload Home after the session ends | Sent to sign in and back to Home. No error page | L, D, P |
| A7 | M-ALL, invite reused or expired | Open an old invite link | A plain message and a next step. Owned by AVR-363, listed so the journey is whole | P only |

### B. Continue, New and Search

| Id | Preconditions | Steps | Expected member-visible result | Evidence |
|---|---|---|---|---|
| B1 | M-ALL with in-progress items in two libraries | Read the Continue row | Items from libraries the member can use, each says where it lives. Row is bounded. Progress shown | F, L, D |
| B2 | M-VID, M-TWO, same Jellyfin fixture | Compare Continue for each | Each sees only their own items. Nothing of the other appears anywhere, including search | F (required), L |
| B3 | M-ALL, nothing in progress | Read Continue | An empty state in one plain sentence, not a blank gap | F, L, D |
| B4 | M-ALL | Open New, then New this week | Recent items from allowed libraries, tabs by library, covers keep natural shape | F, L, D |
| B5 | M-ALL | Search a title in two libraries | Results grouped by library, each row says "In Movies and TV", "In Audiobooks" and so on | F, L, D |
| B6 | M-ALL | Search `metropolis`, `METROPOLIS`, `Métropolis` | Same results for all three | F, L |
| B7 | M-ALL | Search a title that is nowhere | One plain sentence and a link to Request. No empty boxes | F, L, D |
| B8 | M-VID | Search a title that exists only in a library M-VID cannot use | Same as B7. It must not say the title exists elsewhere | F (required), L |
| B9 | M-ALL, Jellyfin down | Search | Says once that Movies and TV could not be searched. Other results still show | F, L, D |
| B10 | M-ALL, phone keyboard | Tap the search field, submit | Keyboard shows a Search key. Page does not jump sideways | D |
| B11 | Empty, very long, or script-like query | Submit each | No error page, no raw text echoed unescaped, no slow hang | F, L |

### C. Handoff to the right app

Common to C1 to C4: the member opens a title page or a Continue item, then presses the one main action
(Play, Resume, Read or Open). Avrana must never say playback started. It only opens the app and shows
a way back.

| Id | Service | Preconditions | Steps | Expected member-visible result | Evidence |
|---|---|---|---|---|---|
| C1 | Jellyfin | M-ALL or M-VID, item in Continue | Press Resume | Opens `watch.avrana.net` at that item (link built from a fixed host and a validated id only). If not signed in there, Jellyfin's own sign-in appears (separate account today). After sign-in, the item. Avrana shows nothing claiming success | F (link build, id check), L (click through to a fake host), D (iPhone, Android, desktop), P |
| C2 | Audiobookshelf | M-ALL, audiobook in Continue | Press Resume in Audiobooks | Opens `listen.avrana.net` at that item. Signed in silently if the Avrana session is live, otherwise the Avrana sign-in button | F, L, D, P. Needs the adapter |
| C3 | Komga | M-ALL, comic in New | Press Read | Opens `read.avrana.net` at that book. Silent sign-in if live. Reader apps have their own password (register U-3) and are a separate check | F, L, D, P. Needs the adapter |
| C4 | Calibre-Web | M-ALL, ebook in New | Press Open | Opens `books.avrana.net` at that book. Its own login form is expected | F, L, D, P. Needs the adapter |
| C5 | Any | Item id with odd characters, wrong length, or a full URL pasted as id | Build the handoff | Refused. No link is shown. No open redirect. Section does not break | F (required) |
| C6 | Any | Upstream returns its own URL field | Build the handoff | Upstream URL ignored. Only the fixed host table is used | F (required) |
| C7 | Any | Member opens the handoff, then presses Back | Return | Back to Avrana at the same place, with the browser's own Back or the in-app way back | D |

### D. Inaccessible libraries, missing content, unavailable services

| Id | Preconditions | Steps | Expected member-visible result | Evidence |
|---|---|---|---|---|
| D1 | M-VID | Type the Komga or Audiobookshelf title URL by hand | The standard "That page does not exist" 404. Not 403. No hint a service exists | F (required), L, D |
| D2 | M-VID | Read Home, Help, search suggestions and page source | No label, host name or help topic for a library outside the member's groups | F (required), L |
| D3 | M-NOLINK | Open Home | The Movies and TV section says the account is not set up for it yet and points to Help. No error page | F, L, D |
| D4 | M-ALL, Jellyfin down | Open Home | Movies and TV is replaced by "Movies and TV are unavailable right now". Other rows load. Page is not slowed past the section timeout (about 2 seconds) | F, L, D, P (drill, owner only) |
| D5 | M-ALL, one slow service | Open Home | The slow section degrades alone. Page whole within 3 seconds | F |
| D6 | M-ALL, all libraries down | Open Home | One clear notice. Request, Help and Account still work | F, L, D |
| D7 | M-ALL, request service down | Press the Request link | "Requests are unavailable right now" and the rest still works | F, L |
| D8 | M-ALL, item deleted upstream after Home listed it | Press the item | Upstream shows its own not found page. Avrana offers a way back and search. The next Home load drops the item once its cache ages out | F (stale link), L, D |
| D9 | M-ALL, title in no library | Search, then follow Request | Opens the right request service with the search filled in where it supports it. No promise it will be fetched | F, L, D |
| D10 | M-ALL, cache of one hour old data, service now down | Open Home | Either the stale-but-valid cache or the unavailable sentence, never a half item with a dead link. Owner decides which (see decisions) | F |
| D11 | Operator notice set | Open Home | One plain sentence at the top. No host names or internals | L (when built) |

### E. Help

| Id | Preconditions | Steps | Expected member-visible result | Evidence |
|---|---|---|---|---|
| E1 | M-ALL, any state in A to D | Reach Help from Home and from each failure message | Help opens. The topic matches the library the member was in | F, L, D |
| E2 | M-VID | Read Help | Only Movies and TV topics. Requests topic follows the register item D-14 | F (required), L |
| E3 | Avrana Assistant offline | Read Help | All help works without it (AVR-364) | F, L |
| E4 | Phone | Use the device jump links | Jump to the right device section. Back to top works. Text scales to the largest setting with no sideways scroll | D |
| E5 | Any | Read the contact line | Shows the owner-approved contact route. **Blocked until D-1 is answered** | Needs decision |

## Device matrix

Rows are the devices the owner asked for. Each cell is a status, and today every status below is
**Not tested**. Fill the "Tested on" column with a device and OS version when it happens, never "iPhone".

| Device class | Browser | Home screen app | Handoff to the Jellyfin, Audiobookshelf, Komga, Calibre-Web web pages | Native app handoff | Tested on | Status |
|---|---|---|---|---|---|---|
| iPhone | Safari | Add to Home Screen (AVR-364) | A1 to E4 | Whether a link opens the installed Jellyfin or Audiobookshelf app is unknown | (blank) | Not tested |
| Android phone | Chrome | Install or Add to Home screen | A1 to E4 | Same unknown | (blank) | Not tested |
| Desktop | One Chromium browser and one Firefox or Safari | Not applicable | A1 to E3 | Not applicable | (blank) | Not tested |
| Television or player | Not in the three-device ask | Not applicable | Not applicable | AVR-479 wants one actually used TV or native player path. A phone link never starts playback on a TV | (blank) | Not in scope until the owner names a device |

Each cell has two outcomes to record: task success (the member got to the right item) and false success.
For phones, also record: text scaling at the largest setting, VoiceOver or TalkBack reading order, and
whether tapping Back returns to Avrana.

## Failure recovery for each handoff

Written so the same text can become Help copy. Steps are for the member; "Avrana shows" is what the page
must offer.

| Failure | Jellyfin (Movies and TV) | Audiobookshelf | Komga (Comics) | Calibre-Web (Books) |
|---|---|---|---|---|
| App not installed (phone opens website) | Use the website, or install the one recommended app from Help (register D-12) | Same, with the listening app named in Help | Same | The website is the app. Kindle steps are in Help |
| Asked to sign in | Use the Movies and TV account. It is separate from the Avrana sign-in today. Forgotten password: Help, subject to D-13 | Choose the Avrana button | Choose the Avrana button. A reader app asks for e-mail and password | Use the Books login form |
| Signed in as the wrong person | Sign out in that app, then reopen from Avrana | Same | Same | Same |
| Item not found | Search again from Avrana. If it is not there, use Request | Same | Same | Same |
| Link expired or session ended | Open Avrana again and choose the item again | Same | Same | Same |
| Service down | Avrana shows the unavailable sentence. Other libraries still work. Try later | Same | Same | Same |
| Wrong item opened | Report it with the date and device. This is a bug, not a member mistake | Same | Same | Same |
| Way back | Browser Back, or the Avrana home screen icon | Same | Same | Same |

Avrana must always offer one next step: open or install the app, sign in, use the browser version, or read
the matching Help topic.

## How this feeds the other issues

- **AVR-479:** the device matrix and section C, D rows are its matrix. Fixture rows (C5, C6, D1, D2, D8,
  B2, B8) satisfy "fixture tests prove links are allowlisted and member-scoped". The D rows give the
  real-device evidence it asks for. Both stay open until a person runs the D rows.
- **AVR-387:** use A1, B1 or B3, B5 and B7, C1 to C4 (the member's own library), D3 or D4, and E1 as
  the task list. Record without names: device class, success, first wrong tap, help needed, whether
  the member thought it worked when it did not, rough time and confidence from 1 to 5. Add the two
  extra scenarios it names: finding Account and Security (A5), and one library down against all down
  (D4 against D6). Beta runs on the beta hostname only (charter D-5, D-6).
- **AVR-363 and AVR-364:** A3, A6, A7 and E4 overlap with their acceptance. Do not count them twice.

## Owner decisions this needs

1. **Test devices (AVR-479).** Which exact phones, OS versions and desktop browsers are used, and which
   TV or native player is the one real path. Without this the D column cannot start.
2. **Who tests (D-6).** Which three to five members, covering a phone-first, a TV-first, a listener
   and a recent joiner. Consent and a short note on what is recorded.
3. **Where D rows run.** A beta hostname (charter D-5, needs an ingress entry and an Authentik provider),
   or a local fixture host reachable from a phone on the home network as the review kit does. Approval
   for any production step is separate for each change.
4. **Failure wording.** Approve the sentences for unavailable, not linked, empty, missing item and
   request unavailable (register D-15). This file only holds intent.
5. **Support contact (D-1, AVR-458).** Needed before E5 and every "go to Help" ending.
6. **What may be recorded (D-7, AVR-458).** The beta task scorecard in AVR-387 records times and
   confidence. Confirm that is within the privacy page, and that no history leaves the tester.
7. **Single sign-in story (AVR-371, AVR-372).** Whether Jellyfin keeps its separate account for launch.
   This changes the sign-in rows in C1 and the failure table.
8. **Television app (D-12).** Which one app Help recommends for TVs.
9. **Stale data rule (D10).** Show cached items when a service is down, or show the unavailable sentence.
10. **Adapters for the other three libraries.** C2 to C4 cannot even run on fixtures until Audiobookshelf,
    Komga and Calibre-Web adapters exist. Confirm the order they are built in.
11. **Does the Requests help topic follow the videos group?** Register D-14. Main now says yes.
