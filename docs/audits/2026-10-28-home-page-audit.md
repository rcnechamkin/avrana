# Home page audit (2026-10-28)

The Avrana Media Home page, checked from top to bottom after the shelves and Details work in this PR. It lists what
looks good, what is missing, what looks bad and what looks weird, then gives ranked recommendations.

## What was checked, and what was not

- **Local, synthetic data.** The dev stack (`dev/run_dev.py --dev-identity` with all four mock libraries) as
  `member-b`, who has all four libraries. I ran `main` (8f41e3b + #142) and this branch side by side, at 1280×900 and
  at 375×812, and checked the page with the accessibility tree and the computed styles as well as screenshots.
- **Live beta: not checked.** media-beta.avrana.net sends the browser pane to the Authentik sign-in page, and agents do
  not enter passwords. Everything below comes from the local stack and from reading the code. Before acting on the
  layout points, look at the live page once with real artwork and real titles.
- **Not checked:** a real phone, Linux CI, and real upstream data for the new Details fields. The Komga author roles,
  Audiobookshelf narrators and Jellyfin People fields are written from the public APIs and have not been seen live.

## What looks good

- **The hero is the member's own next thing.** One Cream button names the app it opens ("Resume in Jellyfin"), and
  Details sits beside it as the secondary action. It says "Resume" only for a real saved position.
- **Progress reads as words** ("81 minutes left", "5 hours 50 minutes left"), with a thin rule beside the words,
  never instead of them.
- **Outages stay calm.** A library that is down gets one sentence, its place is struck through, and the rest of the
  page keeps working. A library the member can't use is never named.
- **The filters are quick.** All, Watch, Listen and Read narrow the page in one tap. Each place's own site is one link
  away.
- **Keyboard and screen-reader basics are solid.** There is a skip link, every card is one link with a full accessible
  name, and the rails' scroll-padding keeps a focused card's ring visible. The tab bar is last in focus order.
- **The Concept K look holds together.** Plus Jakarta Sans, the yellow used only for the member's own state and the
  chosen chip, and covers kept at their natural shapes.

## What is missing

1. **Books (Calibre-Web) have no Details view.** Their cards jump straight out to Calibre-Web, because its adapter
   has no item lookup (OPDS has no single-entry route). So the richer Details in this PR cover Movies and TV,
   Audiobooks, Comics and Komga EPUBs, but not Calibre-Web books.
2. **The Books chip in New Releases can only hold Komga EPUBs.** Calibre-Web gives no release date that Home can sort
   on, so its books never reach New Releases. A member whose novels live only in Calibre-Web will not see the Books
   chip at all (a chip appears only when its list has something).
3. **There is no way past 20 in New to Avrana or New Releases.** That cap is the owner's, but neither shelf links on
   to the Library for the rest.
4. **Up next exists only for Movies and TV.** Audiobooks have no "next in series", and Comics rely on Komga's On Deck.
5. **Details is still thin for some kinds.** It has no runtime or length, no page count, no season or episode list
   for a series, and no rating.
6. **Continue cards have no Details.** They go straight to the player (by design). Only the hero's Details button
   reaches the title sheet for something in progress.

## What looks bad

1. **On a phone the hero fills the whole first screen.** At 375×812 the art, the title (two lines at display size),
   the meta line and the two buttons reach the tab bar. The Continue heading starts under it, so a member sees no
   rail at all until they scroll.
2. **On a computer the page is a 720 px column in a 1280 px window.** About 44% of the width is empty. Now that rails
   hold 12 cards, most of each rail sits off to the side, and only about four cards show at a time.
3. **The same title appears twice in one screen.** The hero is the first Continue item, and that item is also the
   first card in Continue right below it.
4. **New Releases and New to Avrana repeat each other.** Locally, "Synthetic Film Four" is in both rails on All. Live,
   anything added soon after its release will be in both.
5. **The second line under each card changes from rail to rail.** On All, New to Avrana shows the library ("Movies
   and TV"). New Releases shows a year for a film ("2021"), the series for an episode, and "#2" for a comic. Continue
   shows the year, the author or the kind.
6. **"Resume" is underlined under every Continue card.** With 12 cards that is 12 identical underlined words in one
   row. The card is already a link, and the progress words already say what will happen.
7. **The footer on Home is one lone link**, "If something doesn't open", under the last rail. It reads like
   something left over.

## What looks weird

1. **The Library still shows four cards per shelf** (`RAIL_MOST`), while Home now shows 12. The Library, where people
   go to browse, now looks emptier than Home.
2. **Heading case is now mixed.** "New Releases" is capitalised (as asked), but "New to Avrana", "Up next", "Short
   listens" and "Epic listens" are in sentence case.
3. **The "Recently released" fallback can now barely happen.** With no date window, Recently added is empty only when
   a library is empty, so the 2026-10-27/28 fallback rows almost never show. The code is kept, but it is close to dead.
4. **Watch's Up next row now shows show posters** instead of episode stills. That matches Continue (#138), but it
   changes the look of that row.
5. **The "A new version of Avrana Media is ready" banner** sits over the bottom of the page above the tab bar after
   every deploy, covering part of the last rail until the member taps Reload.

## Ranked recommendations

| # | Change | Why | Size |
|---|---|---|---|
| 1 | **A compact hero on phones**: under 45 rem, put the art beside the text, cap the title at two lines and the hero at about 45% of the screen | So Continue shows on the first screen, which is the point of Home | S (CSS) |
| 2 | **Don't show anything twice**: leave the hero's item out of the Continue rail, or show it there marked as the hero; on All, drop from New to Avrana anything New Releases already shows | Repetition makes the page look smaller than the library is | S |
| 3 | **Use the width on a computer**: from about 75 rem, widen the column to about 1200 px so a rail shows six to eight cards; keep the hero's text measure | Rails of 12 currently hide most of their cards | M (CSS, check the hero and the sheet) |
| 4 | **One second-line rule for every card**: for example "kind · year" in rails that mix libraries, and series or author inside one library | Cards in different rails should read alike | S |
| 5 | **Show 12 per shelf on the Library too** (raise `RAIL_MOST`, or use the section limit there as well) | The browsing page shouldn't hold less than Home | S |
| 6 | **A quieter Continue action**: drop the visible "Resume" word and keep the progress words and the rule; the accessible name keeps "Resume in …" | Less noise in a rail of 12 | S |
| 7 | **Choose one heading case** for every shelf (Title Case like "New Releases", or sentence case everywhere) | It currently looks accidental | XS |
| 8 | **Move "If something doesn't open"** off Home's footer into Help and the error states | It reads as an orphan | XS |
| 9 | **Details for Calibre-Web books, and their release dates**: needs a new read-only upstream route (an OPDS entry or the book page), added to the allow-list with tests and the owner's approval | So Books stop being the odd library out | M–L |
| 10 | **More in Details**: runtime or length, page count, the seasons of a series | What people look for on a details page after the cast | M |
| 11 | **A live pass of this audit** on the beta and a real iPhone once this PR is deployed, signed in as a member | Everything above was seen with synthetic data only | S |

## What this PR does

For reference, this is what changed. Each change is covered by tests in `tests/` and `webtests/`.

- **New Releases:** the heading is capitalised, and chips under it (All, Movies and TV, Audiobooks, Comics, Books)
  filter by kind. A chip appears only when the list holds something of that kind.
- **Continue:** up to 12 items across every library the member has. On All it includes Up next, with the show's
  poster. "See all" opens a new `/continue` page, and appears only when there is more than the rail shows. The same
  applies inside Watch, Listen and Read.
- **New to Avrana and New Releases:** 12 items, then "Show more" (in place with the page script, or a reload without
  it), up to 20 in all. There is no date window: the Audiobookshelf and Komga 60-day windows are gone from Recently
  added, and Audiobookshelf's "this year or last" from New Releases.
- **Scroll bars:** none are drawn anywhere in the shell. On a computer with a mouse, each rail that overflows gets
  arrow buttons. They are out of the tab order and hidden from screen readers, because keyboard and touch already
  scroll the rails.
- **Details:** cast, directors and writers (Movies and TV); authors and narrators (Audiobooks); writers and artists
  (Comics); writers (EPUB books in Komga); plus genres and tags. Each appears only when the upstream returns it. The
  new upstream fields, and the one new Komga route (`GET /api/v1/series/{id}`, nothing under it), are in the
  allow-lists and the contract files, with tests.
