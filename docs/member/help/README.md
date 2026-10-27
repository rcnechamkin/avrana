# Device help topics (draft, AVR-364 groundwork)

Status: **DRAFT, unverified.** Not wired into the Avrana home shell, not shown to any member. Every
device step ends with `[UNVERIFIED on a real device]`. Nobody has followed these steps on a phone or
computer. Remove a marker only after a person has done that step on that device and the owner has said so.

## Format (maps 1:1 onto the shell's help data)

The shell takes help from `HELP` in `services/avrana-portal/portal.py` (loaded by
`avrana_home/app/catalogue.py`, rendered by `help_topic.html`):

    (group, label, host, [ (platform, [ (client, store, url, [step, ...]) ]) ])

plus `HELP_SLUGS[label] = slug`. Each file here is one topic in that shape:

| In the file | In the shell |
|---|---|
| `# Title` | `label` |
| `slug:` | `HELP_SLUGS[label]` |
| `group:` | `group` (one Authentik group; `avrana-users` means every member) |
| `host:` | `host` (the "Open ..." link at the foot) |
| `## Heading` | `platform` |
| `### Heading` | `client` |
| `store:` and `url:` | `store` and `url`, or `none` for both |
| `1. text` lines | `steps` |

The shell shows the first client of a platform as "Recommended" when a platform has more than one.
Step text is rendered as trusted markup by the shell, so steps here use plain text only: no `<`, no `&`.
The marker text in steps is for reviewers and must be removed (by the wiring change) before members see it.

Open decisions that these topics wait on: D-1 support contact, D-12 television app, D-13 password
recovery, D-15 unavailable wording (all in `docs/member/DECISIONS-NEEDED.md` on the AVR-361 branch).
Installable Home (Home 2.0 Lane D, then Concept K MK-3, AVR-717): the shell pages link a web app manifest
(`/manifest.webmanifest`, `display: standalone`, installed name "Avrana Media" (owner decision D8), the brand
package's Spire Ink colours and icons at 180, 192 and 512 pixels, an `apple-touch-icon`). They also load one
first-party script and register a service worker whose only offline feature is a static page shown when the network
fails; no member page is ever cached. None of this has been tried on a phone: whether Chrome offers Install app,
whether iOS shows the icon behind the Authentik outpost (everything stays behind it, D9, so the icon and manifest
requests may not carry the session), and how links to other Avrana hosts open in standalone mode (iOS: a separate
in-app browser view; Android: a browser view on top) are all **unverified on a real device**. The install steps say
"Keep the name Avrana Media".

Accuracy review (2026-10-16, against `feat/home-2.0`, updated 2026-10-26 for Concept K, MK-7): the open-* topics
describe what Home does. Titles are found under Continue or Recently added on Home ("New this week" was renamed in
MK-4, AVR-718), in Library (its own tab and page since MK-5a), or with the Search tab; Resume and Open both open the
title's page on the library's own host in the same tab (no new window, no app); Resume never starts playback; each
library still has its own sign-in (no single sign-on across all of them yet). Continue is not offered for Books and
Comics, so those topics name Recently added, Library and Search only. The old top row (a Search link and an account
menu) is gone: Search, Library and the member's own hub (Account, Help, Sign out) are tabs. Sign out on the shell's
Account page now first clears what Avrana Media saved on this device (`/signout`, D10), then goes on to the sign-out;
`sign-in.md` says so and claims nothing more (U-19 is still open).

## For whoever wires these into the shell
- Convert `none` store and url values to an empty value. The template shows a store button only when both are set.
- Strip every `[UNVERIFIED on a real device]` and `[OWNER DECISION ...]` marker from step text.
- The Computer platform in `home-screen` has more than one client (Chrome or Edge, Safari on a Mac, Firefox), so the template will tag the first one "Recommended" and the others "Alternative". These are not alternatives to each other. Agent A decides how to handle that, for example one platform per browser.
- `store` and `url` here are either exactly `none` or a real https URL. A test enforces this.
