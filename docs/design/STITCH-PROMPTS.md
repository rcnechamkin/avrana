# Stitch prompts for Avrana Media 2.0

Prompts for exploring Avrana Media 2.0 screens in Google Stitch. Exploration only: Stitch output is
reference material for the owner, never a source of code or tokens. The normative rules stay in
[`DESIGN.md`](DESIGN.md); scope comes from [`MEDIA-2.0.md`](MEDIA-2.0.md).

## Sources these prompts follow

| Source | What it fixes |
|---|---|
| `DESIGN.md` | "The Title Card": black, white, ash, one serif, tracked wordmark, square 1px rules, inversion on hover, no accent, no shadow, no rounding, no decorative icons |
| AVR-452 (owner-approved composition B, 2026-10-11) | Compact content home: one bar under the wordmark (Watch, Listen, Read, Request, Help) ending above y=260 at 360x640; one Continue row (video and audio mixed, at most four); one "New this week" row (at most four) switched by link tabs (All, then one per library the member can use); **no per-library shelves on Home**; Home at most two phone screens tall; a separate New page; a down service is struck through in the bar, said once in a notice, and its items are absent |
| AVR-431 (owner rejection, 2026-10-11) | The earlier previews put "shelves ahead of Request, Help and services". Do not do that |
| AVR-426 / PR 11 proposals | Each library keeps its own artwork shape (2:3 posters, square audiobooks, 2:3 books, 13:20 comics); artwork in colour on the monochrome page; a rail on phones, a single row from 720px; compact wordmark; Continue listening as rows |
| AVR-431 recommendation | Material's patterns (top bar or rail, list-detail, tabs, chips, menu, progress, snackbar) expressed in plain HTML within the house style; not Material's look |
| AVR-430, portal rules | Copy never names a library the member cannot use; no first person; no dashes |
| AVR-364, AVR-365 | Installable home-screen site without promising offline playback; outage notices in member language, never internals |
| Media 2.0 charter | Avrana never plays media; every Play or Read hands off to the app and names it |

Device sizes used throughout: **360x640** and **390x844** phones, **1280x800** desktop.

## How to use

1. Create a **Web** project. If Stitch offers a design-system or DESIGN.md import, load
   `docs/design/DESIGN.md`. Either way, send **Prompt 0** first.
2. Attach a screenshot of today's avrana.net as a style reference (the outlined tiles under the
   spaced AVRANA wordmark).
3. One screen per prompt, in order. Ask for the phone size first: composition B is judged on the
   phone.
4. Use Section 3 variants to explore styling *inside* composition B, not new layouts.
5. Correct drift with the Section 4 edit prompts rather than regenerating.
6. Keep a result only if it passes the Section 5 checklist.

Placeholder artwork: use real film and book covers as stand-ins only; do not keep generated
imagery as Avrana art.

---

## Prompt 0. Product brief and visual contract (send first)

```
Design screens for "Avrana", a private media service for about 15 invited members: a family's own
films and shows, audiobooks, comics and ebooks. Members sign in once, pick up what they were in the
middle of, see what is new, search, and get help. Avrana never plays anything itself: every Play or
Read button hands off to the app that does, and names it (Jellyfin for video, Audiobookshelf for
audiobooks, Komga for comics, Calibre-Web for ebooks). It must feel like a genuine, calm, premium
consumer service, never a self-hosted admin dashboard.

Creative direction, "The Title Card": every screen feels like the black card before a film starts.
Pure black, white type, one serif typeface, the wordmark AVRANA in widely spaced capitals with a
short thin rule beneath it, and nothing that does not need to be there. The libraries are full of
colourful artwork; Avrana is the quiet black frame around them. Artwork is the only colour.

Visual rules (strict):
- Background #000000. Text #FFFFFF. Secondary text #9A9A9A. Interactive borders #6E6E6E. Dividers
  #474747. Status colours only beside words: ok #8FE3A6, warning #E8CF8A, error #FF8B8B.
- No accent colour, no gradients, no shadows, no blur or glass, no rounded corners anywhere
  (radius 0), 1px borders and rules only. No icons, no emoji, no avatars. Text labels only.
- One typeface: Times New Roman (serif fallback), regular weight 400 everywhere. Hierarchy from size,
  letter-spacing and capitals, never bold. Monospace only for things a person copies, like a server
  address.
- Wordmark "AVRANA": capitals, letter-spacing about 0.34em, centred, with a 64px thin rule beneath.
  Compact size on Home; it links home on every other page.
- Section labels: small uppercase serif, letter-spacing 0.22em, grey. One level per screen.
- Hover and focus invert: an outlined element becomes solid white with black text. Every
  interactive element has a visible focus ring (2px black gap, 2px white ring). Targets at least
  44px tall.
- Artwork keeps each library's own shape: 2:3 posters for films and shows, square for audiobooks,
  2:3 for books, 13:20 for comics. Square corners, no overlays or text on artwork.
- Progress is a 2px white line on a #474747 track, always beside words ("32 min left").
- Copy is plain and warm, second person or neutral. Never "we", "our" or "us". No em or en dashes.
  Sentence case except the wordmark and section labels. Never mention a library the member cannot
  use.
- Patterns may follow Material's structure (top bar, tabs, list-detail, chips, progress, snackbar)
  but never its look: no rounded pills, no elevation, no colour fills, no ripples.

Avoid: shelves of rows per library on Home, carousels with arrows, hero banners with gradient
overlays, KPI or stat cards, sidebars, icon grids, rating stars, genre pills, red or any brand
colour, glowing or rounded buttons, stock photos, illustrations, and anything operator-facing
(server health, container names, queues, charts).
```

---

## Section 2. Screen prompts

### Prompt 1. Home, phone (360x640 first, then 390x844)

```
Screen: Avrana Home for a signed-in member, Ada, at 360x640. Composition "compact content home".

1. Top: the compact centred AVRANA wordmark with its thin rule. Directly under it, one text bar of
   five links in a single row: Watch, Listen, Read, Request, Help. Serif, white, evenly spaced,
   44px tall. The whole bar must end above y=260. A small text link "Ada" at the top right opens
   the account page.

2. Section label "CONTINUE". One row of at most four items Ada is part way through, video and audio
   mixed. On the phone it is a horizontal rail with the next item peeking at the right edge. Each
   item: artwork in its own shape (a 16:9 still for a film or episode, square for an audiobook),
   title in white beneath, one grey line ("Episode 4 · 32 min left", "Chapter 12 · 3 h 10 min
   left"), and a 2px progress line under the artwork. Each item links to the app that plays it.

3. Section label "NEW THIS WEEK". Under it, a row of text tabs: All, Movies and TV, Audiobooks,
   Books (only the libraries Ada can use); the selected tab is white with a 1px white line beneath,
   the others grey. Then one row of at most four new items in their own artwork shapes, with title
   and a grey line naming the library. A text link "See everything new" at the end of the row.

4. Footer: small centred text links: Account, Sign out.

Home must be no taller than two phone screens (about 1280px). No per-library shelves, no search
field taking space on Home (only a small "Search" text link beside "Ada"), no hero image.
```

### Prompt 2. Home, desktop (1280x800)

```
Screen: the same Avrana Home at 1280x800.

Same order and content as the phone: compact centred wordmark and rule, the five-link bar (Watch,
Listen, Read, Request, Help) centred beneath it, "Ada" at the far right. The Continue row and the
New this week row each sit in a single line of four items across a centred column about 1080px
wide, no rail. Tabs above New this week as text links. Lots of black space; the page should fit in
roughly one desktop screen. Footer links centred.
```

### Prompt 3. Home states (phone, one canvas, four variants)

```
Screen: four variants of the Avrana Home at 360x640 on one canvas.

A, "a service is down": in the five-link bar, "Listen" is struck through in grey. Directly under
the bar, one notice line with a 1px #E8CF8A border and #E8CF8A text: "Audiobooks are unavailable
right now." Audiobook items are simply absent from Continue and New. Help and Account still work.

B, "planned maintenance": the same notice style with operator-written text: "Avrana is getting an
update tonight at 10 pm. Expect a short break." Nothing struck through.

C, "new member, nothing started": no Continue section. In its place one sentence in grey: "Nothing
started yet. Start with something new below." Then New this week as normal.

D, "loading": section labels in place, artwork areas as plain #111111 rectangles in each library's
shape, and the words "Loading" in grey under the label. No spinners, no shimmer animation.
```

### Prompt 4. The New page

```
Screen: Avrana "New" page at 390x844 and at 1280x800.

Compact wordmark linking home, the five-link bar. Heading "New" in large serif. Text tabs: All,
Movies and TV, Audiobooks, Comics, Books (only libraries the member can use). Below, a list grouped
by library, each group with a spaced grey label and a count ("MOVIES AND TV  6"). On the phone,
items wrap into a grid of two (posters) or three (square and comic covers) per line; on desktop, a
wrapped grid in each library's own shape. Each item: artwork, title, a grey line with the date it
arrived ("Added Tuesday"). Each opens the item's title page.
```

### Prompt 5. Search and results

```
Screen: Avrana search at 390x844, query "dune".

Where search lives is not fixed by AVR-452; this screen explores it as its own page, reached from
a "Search" text link beside "Ada" at the top right. A full-width search field with a 1px #6E6E6E border, square, serif placeholder "Search everything
you can open". Results grouped by where they live, each group with a spaced grey label and count:
"MOVIES AND TV  3", "AUDIOBOOKS  2", "BOOKS  4". Each result is a ruled row: small artwork in its
own shape, title in white, a grey line ("2021 · Denis Villeneuve", "Frank Herbert · narrated by Scott
Brick · 21 h"), and on the right an outlined button naming the destination: "Open in Jellyfin",
"Listen in Audiobookshelf", "Open in Calibre-Web".

Below, "NOT HERE YET" with one row "Dune: Part Three (2026)" and an outlined button "Request",
which opens the request service with the search filled in. Above the results, a grey note shows a
library that could not be searched: "Comics could not be searched right now." No red, no icon.
Results only ever include libraries the member can use.
```

### Prompt 6. Title page: film, list-detail on desktop

```
Screen: Avrana title page for the film "Arrival" (2016), at 390x844 and at 1280x800.

Phone: compact wordmark, the bar, then the 2:3 poster at about 60% width, centred. Title "Arrival"
in large serif, a grey line "2016 · 1 h 56 min · Denis Villeneuve", a 2px progress line with
"41 min left" if started, a short synopsis in white 17px text, then one solid white button
"Resume in Jellyfin" (black text, full width, square) and an outlined button "Open the Jellyfin
app". A grey line: "Plays in Jellyfin. The app gives the steadiest playback."

Desktop: list-detail. The page shows the poster at 280px on the left and the details on the right,
with "MORE IN MOVIES AND TV" as one row of four posters beneath. No backdrop image, no ratings, no
genre pills.
```

### Prompt 7. Title page: audiobook and comic

```
Screen: two Avrana title pages side by side at 390x844.

Left, audiobook "Project Hail Mary": a square cover, title, grey line "Andy Weir · narrated by Ray
Porter · 16 h 10 min", "Chapter 18 of 34 · 7 h 2 min left" with a progress line, synopsis, white
button "Continue in Audiobookshelf", outlined button "Listen on your phone" (goes to help for the
listening apps).

Right, comic "Saga, Volume 1": a 13:20 cover, title, grey line "Brian K. Vaughan, Fiona Staples ·
Issues 1 to 6", white button "Read in Komga", outlined button "Read in a comic app" (goes to help).
```

### Prompt 8. Welcome (first visit after an invite)

```
Screen: Avrana welcome page shown once to a new member, Sam, at 390x844.

Compact wordmark. Heading "Welcome, Sam." One sentence: "Here is what is ready for you, and the one
app to install for each." Then one ruled row per library Sam can use (for example Movies and TV,
Audiobooks), each with what it is, the recommended app for Sam's device, and a text link "How to set
it up". Then "ADD AVRANA TO YOUR HOME SCREEN" with two short numbered steps for iPhone (Share, Add to
Home Screen) and Android (menu, Add to home screen), and one grey line: "Avrana opens like an app.
Playback still happens in each library's own app." A white button "Go to Avrana". Calm, spacious.
```

### Prompt 9. Help for one library, with device jump links

```
Screen: Avrana help page "Movies and TV" at 390x844.

Compact wordmark, the bar with Help selected. Heading "Movies and TV". Under it, device jump links
that wrap onto two or three lines: iPhone and iPad, Android, Roku, Fire TV, Google TV, Apple TV,
Smart TVs, Windows, Web browser. Each device is a section: a serif heading, the app name with a
small grey "RECOMMENDED" label, an inline text link "Get it on the App Store", numbered steps in
grey. The server address appears in monospace in a thin outlined box with a "Copy" text button:
https://watch.avrana.net. After copying, a snackbar at the bottom: a black bar with a 1px white
border reading "Address copied". Footer: All help, Back. No accordions, no screenshots, no icons.
```

### Prompt 10. Account

```
Screen: Avrana account page for Ada at 390x844.

Heading "Your account". A two-column list (stacked on phone): Name, Username, Email; labels small
grey uppercase, values white serif. "YOUR LIBRARIES" as outlined text chips naming only what Ada can
use. "KINDLE" with the saved address in monospace and a text link "Change". "SIGN-IN AND SECURITY"
with outlined buttons "Password and passkeys" and "Sign out". A grey line: "To leave Avrana or remove
your data, write to Cody." with the address as a text link.
```

### Prompt 11 (optional). "Ask Avrana" help entry

```
Screen: the Avrana Help index at 390x844 with an "Ask Avrana" entry (a separate, not yet approved
workstream; explore only).

Under the heading "Help", a single outlined field "Ask a question about using Avrana" with a white
"Ask" button. Beneath, a grey line: "Answers come from the help pages. For anything about your
account, write to Cody." Show one answered example as plain text with two cited help-page links
underneath ("From: Movies and TV help"). Then the normal list of help topics as ruled rows. No chat
bubbles, no avatars, no typing animation.
```

---

## Section 3. Styling variants inside composition B

Ask for each as a variant of Prompts 1, 2 and 6. They change tone, not structure.

**Variant A, Title Card (baseline)**
```
Variant "Title Card": artwork at modest size, evenly spaced, generous black space, long thin rules
between sections, the wordmark slightly larger. Quiet and ceremonial.
```

**Variant B, Programme**
```
Variant "Programme": like a repertory cinema's printed programme. Artwork a little larger, titles set
beneath in serif capitals with tracking, captions in grey italic. Still one Continue row and one New
row, still no hero image.
```

**Variant C, Catalogue**
```
Variant "Catalogue": like a well-kept library index. Continue shown as ruled rows (thumbnail, title,
time left, destination) instead of artwork tiles; New this week as a compact row. Densest of the
three, fastest to scan.
```

---

## Section 4. Edit prompts

```
Make every corner square (radius 0), including buttons, tabs, fields and artwork.
```
```
Remove all shadows, gradients, blur and elevation. 1px borders only.
```
```
Use Times New Roman at regular weight 400 for every text element. No bold.
```
```
Remove every icon and emoji. Use text labels only.
```
```
Remove any accent colour. Buttons are solid white with black text, or outlined white on black.
```
```
Move the five-link bar (Watch, Listen, Read, Request, Help) directly under the wordmark so it ends
above y=260 at 360x640.
```
```
Remove the per-library shelves from Home. Keep only one Continue row and one New this week row with
tabs.
```
```
Show each artwork in its library's shape: 2:3 for films, shows and books, square for audiobooks,
13:20 for comics.
```
```
Show focus on the primary button and one artwork item: a 2px black gap then a 2px white ring.
Show hover on a bar link: solid white background, black text.
```
```
Rewrite every line of copy with no "we", "our" or "us" and no dashes, in calm sentence case.
```

---

## Section 5. Review checklist

- Composition B holds: wordmark, then the five-link bar ending above y=260 at 360x640, then one
  Continue row, then one New this week row with tabs. No per-library shelves. Home at most two phone
  screens.
- Pure black; artwork is the only colour; each library's artwork shape is kept.
- One serif at regular weight; square corners; 1px rules; no shadows, gradients, icons or accent.
- Every Play or Read names its app; nothing implies Avrana plays media.
- A down service is struck through in the bar, said once in a notice, and its items are absent.
- Loading, empty, one-down and all-down states each say so in words.
- Nothing operator-facing; nothing names a library the member cannot use.
- Copy has no first person and no dashes.
- Cover the wordmark: if it could be any streaming site, it fails.

## What Stitch output is not

Concept references only. Anything adopted is rebuilt in the Avrana home application against
`DESIGN.md`, with no JavaScript (AVR-452: the CSP has no script source), and with the accessibility,
authorization and degradation tests the charter requires.
