# Member home: preview and proposals

> **Status: proposed, 2026-10-11 (AVR-426).** Screenshots of a fixture-only preview
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

## What changed for a member

- The page opens on what they were doing: **Continue watching** as wide stills with a thin rule
  for how far along, and **Continue listening** as rows with a square cover. The time left is
  always written beside the rule.
- **Recently added** has one shelf per library the member can use, and each library keeps its own
  artwork shape: 2:3 posters, square audiobook covers, 2:3 books, 13:20 comics.
- On a phone a shelf scrolls sideways inside itself with part of the next cover showing, and the
  page never scrolls sideways. From 720px a shelf is a single row that needs no scrolling.
- Every edge of something clickable is the Control Rule or stronger, every target is at least
  44px, and every Tab stop shows the two-ring focus mark.
- The navigation tiles are the ones the portal has now, under the shelves.

## States

| State | Address | What a member sees |
|---|---|---|
| Loading | `/?state=slow` | one service past its two seconds: a sentence, the outline of its shelf, "Try again" |
| Empty | `/?state=empty` | "Nothing in progress" in place of both Continue sections; "Nothing new in the last 30 days" on one shelf |
| One service down | `/?state=degraded` | "Movies and TV are unavailable right now", once; the other libraries unchanged |
| Libraries unavailable | `/?state=unavailable` | the operator notice, one sentence, Request, Help and Account |

Loading has no spinner and no script: the page is rendered once, a section whose service did not
answer in time says so in a sentence, keeps the outline of what will be there, and offers
"Try again", which is a plain link to the same page.

## Proposals for the owner

| # | Question | Shown in the preview | Alternative |
|---|---|---|---|
| 1 | Artwork shape | each library's own shape | one shape everywhere (crops covers) |
| 2 | Rail or grid | rail on a phone, one row from 720px | wrapping grid on a phone (a longer page) |
| 3 | Artwork colour on a monochrome page | as the library supplies it; the page stays black and white | greyscale (the "Artwork: grey" switch, `/?art=mono`) |
| 4 | Wordmark size on the home page | the compact wordmark, so the first shelf is on screen | the full wordmark, as today |
| 5 | Continue listening as rows | rows, because the words matter more than the cover | a second rail of square covers |
| 6 | Wording of the slow, empty and all-down sentences | as written in `fixtures.py` and `home.html` | owner's wording |

The preview's drawn covers are tinted so that question 3 can be judged; real artwork is brighter
and more varied than these.

## Not shown, not decided

Search, title pages, request links, the real adapters, caching, per-member identity and the
group gating of each shelf are outside this preview (M3.2 to M3.5 in Media 2.0).
