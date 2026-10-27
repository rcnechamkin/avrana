# Member home: preview and proposals

> **Status: proposed, 2026-10-11 (AVR-426). Composition changed the same day (AVR-452): the owner
> reviewed two compositions in AVR-431 and chose the compact content home with a separate New
> page.** Screenshots of a fixture-only preview
> ([how to open it](../../../../tests/ui/home_preview/README.md)). Nothing here is deployed, and
> nothing here changes the portal that runs today. Owner decisions of 2026-10-15 are under Decisions; visual approval is pending (AVR-455).

The preview keeps the identity in [DESIGN.md](../../DESIGN.md): black, white and ash, one serif,
square corners, 1px rules, no icon, shadow or accent. It adds the three things
[Media 2.0](../../MEDIA-2.0.md) asks the home page for.

This repository tracks no binary files, so the screenshots are not in Git. With the preview
running, `check.mjs` writes them to `tests/ui/home_preview/screens/` (before and after, phone and
desktop, every state), and the same pages are one click apart in the browser:

| | Address |
|---|---|
| Today's home, from `portal.py` | `http://127.0.0.1:8200/before` |
| Preview | `http://127.0.0.1:8200/` |
| New this week, by library | `http://127.0.0.1:8200/new` |

## What changed for a member

- **The places come first.** Watch, Listen, Read, Request and Help are one ruled bar directly
  under the wordmark, on every page. On a 360 by 640 phone the bar ends 178px into the page, below the account control. The
  first version of this preview put them under six shelves, more than 2,200px down; that is what the owner
  rejected.
- **Continue** is one row of at most four, whatever library each was left in: wide stills and
  square audiobook covers side by side, each with a thin rule for how far along and the time left
  in words.
- **New this week** is one row of at most four. Tabs (plain links, no script) switch it between
  All, which is the newest of each library, and one library at a time. Each library keeps its own
  artwork shape: 2:3 posters, square audiobook covers, 2:3 books, 13:20 comics.
- **Browsing has its own page.** `/new` holds everything new in one library at a time, behind the
  same tabs, with the same bar of places above it.
- The home page is 892px tall at 360 by 640 (the first version: 2,994px). On a phone a row scrolls
  sideways inside itself with part of the next cover showing; the page never does.
- Every target is at least 44px, and every Tab stop shows the two-ring focus mark.
- The five navigation tiles are gone from the home page: the bar does their work in one line.

## States

| State | Address | What a member sees |
|---|---|---|
| Loading | `/?state=slow` | one service past its two seconds: a sentence and "Try again"; what the other services answered is shown |
| Empty | `/?state=empty` | "Nothing in progress" in place of the Continue row; "Nothing new in audiobooks this week" on that tab |
| One service down | `/?state=degraded` | "Movies and TV are unavailable right now. Everything else works.", once; Watch struck through in the bar and not a link; no tab for it |
| Libraries unavailable | `/?state=unavailable` | the operator notice; Watch, Listen and Read struck through; Request, Help and Account |

Loading has no spinner and no script: the page is rendered once, a section whose service did not
answer in time says so in a sentence and offers "Try again", which is a plain link to the same
page.

## Decisions

The owner decided these on 2026-10-15 (`docs/DECISIONS.md`). Visual approval of the result is
still pending (AVR-455).

| # | Question | Decision |
|---|---|---|
| 1 | Artwork shape | each library's natural shape (posters, audiobook squares, books, comics, video stills) |
| 2 | Rail or grid | one bounded rail on Home; a wall of covers on `/new` (AVR-452) |
| 3 | Artwork colour | original colour; the interface stays black and white. The grey switch stays only as a comparison in the preview |
| 4 | Wordmark size on the home page | the compact wordmark |
| 5 | Continue as one mixed row | one row of at most four (AVR-431) |
| 6 | Wording of the slow, empty and all-down sentences | as written; open to the owner's edits during the phone review |
| 7 | A struck-through place when its service is down | the word stays in the bar, struck through, not a link |
| 9 | Where Search starts | a visible "Search" link at the top left, above the bar of places; the bar's order is unchanged |
| 10 | Width of the browsing pages | the 720px column, subject to a desktop review; Kindle keeps 640px |

The preview's drawn covers are tinted so that colour on the black page can be judged; real artwork is
brighter and more varied than these.

## Account and shared navigation (AVR-478, proposed)

The same top of the page on Home and `/new`, for every viewer. Switch viewers in the preview bar
(`?who=books`, `?who=none`, `?who=out`).

| Part | Behaviour |
|---|---|
| Account control | Top right on every page, before the wordmark in the reading order. A square initial and the word **Account**; its name to a screen reader is "Account, signed in as" and the member's display name. No photograph, icon, email, access group or technical detail. |
| Account menu | A native disclosure (`details`): Signed in as the name, then **Account and security**, **Help**, **Sign out**. Nothing unfinished: no My Avrana or profile link until M4 ships one. Plain links, not an ARIA menu, so Tab moves through them as on the rest of the page. |
| Opening and closing | Mouse, touch, Enter and Space open and close it with no script. Focus stays on the control; Tab from the open control reaches the first item. **Escape and a tap outside do not close it**: that needs a few lines of script, which the page's policy forbids today (owner decision below). |
| Places bar | Only places this member can use. A library the member cannot use has no place, tab, item or notice at all; a library that is down is struck through and said once. Read stays when either books or comics is usable. |
| Continue | Shown only to a member who can use video or audio, the two libraries that have progress. |
| No library yet | Request and Help in the bar, and one sentence: "No library is shared with this account yet. Ask the person who invited you, or read Help." |
| Signed out | What a request without a verified identity would get: Help in the bar, **Sign in** where the account control was, and nothing about any library. (In production the outpost signs people in before any page; this is the fail-closed fallback.) |
| Footer | Account and security (signed in) and Help, so both are reachable without opening the menu. |
| Targets and focus | Every control at least 44 by 44px, the two-ring focus mark on every Tab stop, the menu inside a 360px screen and at 200% text. Checked by `check.mjs` for every viewer. |

Active page: the places bar holds destinations in other apps, so on Home nothing in it is current;
the `/new` tabs mark the library on screen with `aria-current`. Help and Account will mark
themselves the same way when the shell (AVR-374) serves them.

### Decision 8: closing the menu

The owner chose the native, script-free menu first (2026-10-15). Escape and a tap outside are checked
in Safari with VoiceOver during the phone review. Only if that shows a script is needed for
accessibility does one come, as a narrowly scoped CSP exception in its own pull request for review.

## Search and title pages (AVR-426, proposed)

Specified in DESIGN.md's former "Media components" section (now summarised under
[History](../../DESIGN.md#history); on Home shell pages Concept K replaces it), with every state's sentence. Open them from the preview bar; they keep the state and viewer switches.

| Page | Address | What a member sees |
|---|---|---|
| Search | `/search?q=the` | one labelled field and a Search button; results grouped by library, each row saying "In" and its library; a count in words |
| Nothing found | `/search?q=zzzz` | "Nothing called "zzzz" in your libraries. Check the spelling, or ask for it with Request." The same for a title in a library the member cannot use |
| Search, one library down | `/search?q=the&state=degraded` | the other libraries' results, and "Movies and TV were not searched, because they are unavailable right now." |
| Title page | `/title/nosferatu` | the title, one action ("Resume in Movies and TV"), how far along, one sentence about it, then Library and Year |
| Title page, library down | `/title/metropolis?state=degraded` | the sentence, said once, and no action |
| A title the member cannot use | `/title/metropolis?who=books` | Not Found, the same as a title that does not exist |

New cards now open a title page; Continue cards still hand off to the library at the place the
member stopped. `check.mjs` checks both pages in every state at 360, 390 and 1280px, including a
focus ring at the field and the button and, on a phone, the action on the first screen.

## Not shown, not decided

Request links, the real adapters, caching and real identity (the preview's viewers are fixtures)
are outside this preview (M3.2 to M3.5 in Media 2.0). Search and title pages run on fixtures, not
on any library's API.
