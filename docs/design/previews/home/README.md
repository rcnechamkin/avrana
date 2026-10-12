# Member home: preview and proposals

> **Status: proposed, 2026-10-11 (AVR-426). Composition changed the same day (AVR-452): the owner
> reviewed two compositions in AVR-431 and chose the compact content home with a separate New
> page.** Screenshots of a fixture-only preview
> ([how to open it](../../../../tests/ui/home_preview/README.md)). Nothing here is deployed, and
> nothing here changes the portal that runs today. Items marked *Proposal* wait for the owner.

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
  under the wordmark, on every page. On a 360 by 640 phone the bar ends 140px into the page. The
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
- The home page is 854px tall at 360 by 640 (the first version: 2,994px). On a phone a row scrolls
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

## Proposals for the owner

| # | Question | Shown in the preview | Alternative |
|---|---|---|---|
| 1 | Artwork shape | each library's own shape | one shape everywhere (crops covers) |
| 2 | Rail or grid | one bounded rail on Home; a wall of covers on `/new` | a wall on Home (a longer page) |
| 3 | Artwork colour on a monochrome page | as the library supplies it; the page stays black and white | greyscale (the "Artwork: grey" switch, `/?art=mono`) |
| 4 | Wordmark size on the home page | the compact wordmark, so the first shelf is on screen | the full wordmark, as today |
| 5 | Continue as one mixed row | stills and square covers in one row of four (decided, AVR-431) | one row per library (the rejected first version) |
| 7 | A struck-through place when its service is down | the word stays in the bar, struck through, not a link | remove it from the bar |
| 6 | Wording of the slow, empty and all-down sentences | as written in `fixtures.py` and `home.html` | owner's wording |

The preview's drawn covers are tinted so that question 3 can be judged; real artwork is brighter
and more varied than these.

## Not shown, not decided

Search, title pages, request links, the real adapters, caching, per-member identity and the
group gating of each shelf are outside this preview (M3.2 to M3.5 in Media 2.0).
