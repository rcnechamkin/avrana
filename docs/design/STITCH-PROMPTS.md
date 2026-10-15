# Stitch prompts for Avrana Media 2.0

Prompts for exploring Avrana Media 2.0 screens in Google Stitch. Exploration only: Stitch output is
reference material for the owner, never a source of code or tokens. The normative rules stay in
[`DESIGN.md`](DESIGN.md); scope comes from [`MEDIA-2.0.md`](MEDIA-2.0.md).

Stitch has none of the design skills used on this project, so their rules are written into the
prompts themselves: Prompt 0A carries the visual contract, Prompt 0B the anti-slop and craft
contract, every screen prompt names its required states, and Prompt Z is the finish gate.

## Sources

| Source | What it contributes |
|---|---|
| `DESIGN.md` | "The Title Card": black, white, ash, one serif, tracked wordmark, square 1px rules, inversion on hover, no accent, no shadow, no rounding, no decorative icons |
| AVR-452 (owner-approved composition B, 2026-10-11) | Compact content home: one bar under the wordmark (Watch, Listen, Read, Request, Help) ending above y=260 at 360x640; one Continue row (video and audio mixed, at most four); one "New this week" row (at most four) switched by link tabs; no per-library shelves on Home; Home at most two phone screens; a separate New page; a down service struck through in the bar, said once in a notice, its items absent |
| AVR-431 (owner rejection) | The earlier previews put "shelves ahead of Request, Help and services" |
| AVR-426 / PR 11 | Each library keeps its own artwork shape; artwork in colour on the monochrome page; rail on phones, single row from 720px; compact wordmark |
| AVR-430, portal rules | Copy never names a library the member cannot use; no first person; no dashes |
| AVR-364, AVR-365 | Installable site without promising offline playback; outage notices in member language |
| Media 2.0 charter | Avrana never plays media; every Play or Read names the app it hands off to |
| **anti-ui-slop / UIZZE ui-design** | Work from the existing system; a design contract; cover every reachable state (loading, empty, error, success, disabled, selected, recovery); spacing before borders; one component vocabulary; real product language; a hard finish gate |
| **Impeccable craft floor** | The refusal list (identical icon cards, hero metrics, eyebrow labels above headings, section numbers, gradient text, glass, thick coloured side borders, hard offset shadows, monospace as costume, emoji as icons); themed browser surfaces; more space above a heading than below; 65 to 75 character measure; one authored motion moment |
| **Anthropic frontend-design** | The calibration list of generated-design tells (near-black #111 standing in for black, "A · B · C" meta strings, "WORD — fragment" labels, arrows appended to buttons, one accented word in a headline); spend boldness in one place; copy names actions; errors name the problem and the recovery |
| **Vercel web-design-guidelines** | Visible focus, real labels, 44px targets, curly quotes and the ellipsis character, "Loading…", tabular numerals, `color-scheme: dark`, theme colour, safe areas, no disabled zoom, links for navigation and buttons for actions |

Device sizes throughout: **360x640** and **390x844** phones, **1280x800** desktop.

### Where the skills and the brief disagree (resolved)

The skills describe category defaults; the owner's pinned brief wins every conflict. Stitch is told so
explicitly, so it does not "correct" the identity toward something generic.

| Skill default | Avrana decision |
|---|---|
| Impeccable: a system face as the display voice is a failure | Times New Roman is the brief's pinned identity, used deliberately and rendered in the device's real serif |
| frontend-design: zero radius and hairline rules are a broadsheet tell | Square corners and 1px rules are the brief. The difference from a broadsheet: single centred column, lots of black, no dense columns |
| frontend-design and Impeccable: all-caps labels and eyebrows | Kept only as the section heading itself (one level per screen), never as a label stacked above another heading |
| Vercel: Title Case buttons | House style is sentence case |
| Impeccable: theme light or dark from the use scene | Dark fits the scene (evenings, televisions, bed) and is the committed single theme |

---

## How to use

1. Create a **Web** project. If Stitch offers a design-system or DESIGN.md import, load
   `docs/design/DESIGN.md`.
2. Send **Prompt 0A**, then **Prompt 0B**. Attach a screenshot of today's avrana.net.
3. One screen per prompt, phone size first: composition B is judged on the phone.
4. After each screen, send **Prompt Z** (the finish gate) and apply its fixes before moving on.
5. Explore tone with the Section 3 variants, which keep composition B intact.
6. Correct drift with the Section 4 edit prompts rather than regenerating.

Placeholder artwork: real film and book covers as stand-ins only. Do not keep generated imagery as
Avrana art.

---

## Prompt 0A. Product brief and visual contract

```
You are designing screens for "Avrana", a private media service for about 15 invited members: a
family's own films and shows, audiobooks, comics and ebooks. Members sign in once, pick up what
they were in the middle of, see what is new, search, and get help. Avrana never plays anything
itself. Every Play or Read button hands off to the app that does and names it: Jellyfin for video,
Audiobookshelf for audiobooks, Komga for comics, Calibre-Web for ebooks. It must feel like a
genuine, calm, premium consumer service, used mostly in the evening on phones and next to a
television. It must never feel like a self-hosted admin dashboard.

This is an established identity, not a blank slate. Extend it; do not replace it.

Creative direction, "The Title Card": every screen feels like the black card before a film starts.
Pure black, white type, one serif typeface, the wordmark AVRANA in widely spaced capitals with a
short thin rule beneath it, and nothing that does not need to be there. The libraries are full of
colourful artwork; Avrana is the quiet black frame around them. Artwork is the only colour. The one
bold thing on any screen is the artwork; everything else stays quiet.

Visual rules (strict, and they override any general design habit you have):
- Background exactly #000000, never a tinted near-black. Text #FFFFFF. Secondary text #9A9A9A.
  Interactive borders #6E6E6E. Dividers #474747. Status colours only beside words: ok #8FE3A6,
  warning #E8CF8A, error #FF8B8B.
- No accent colour, no gradients, no shadows, no blur or glass, no rounded corners anywhere
  (radius 0), 1px borders and rules only. No icons, no emoji, no avatars. Text labels only.
- One typeface: Times New Roman with a serif fallback, regular weight 400 everywhere. This is a
  deliberate identity choice, not a fallback. Hierarchy comes from size, letter-spacing and
  capitals, never bold, never italic accents on single words.
- Wordmark "AVRANA": capitals, letter-spacing about 0.34em, centred, a 64px thin rule beneath.
  Compact size on Home; on every other page it is a link home.
- Section headings: small uppercase serif, letter-spacing 0.22em, grey, one level per screen. The
  section heading is the heading itself. Never put a small label above another heading.
- Hover and focus invert: an outlined element becomes solid white with black text. Every
  interactive element has a visible focus ring: a 2px black gap then a 2px white ring.
- Touch targets at least 44px tall. Body text 17px with line height 1.55, lines no longer than
  about 70 characters. More space above a section heading than below it.
- Artwork keeps each library's own shape: 2:3 posters for films and shows, square for audiobooks,
  2:3 for books, 13:20 for comics. Square corners. No overlays, badges or text on artwork.
- Progress is a 2px white line on a #474747 track, always with words beside it.
- Numbers that line up (times, counts) use tabular figures.
- Patterns may follow Material's structure (top bar, tabs, list-detail, chips, progress, snackbar)
  but never its look: no rounded pills, no elevation, no colour fills, no ripples.
```

## Prompt 0B. Anti-slop and craft contract

```
Before designing, read this contract. It lists the habits that make generated interfaces look
generic. Avrana must not show any of them, even where a typical design would.

Never use:
- Rows of identical cards made of an icon, a heading and a line of text. Never nest cards.
- A big number with a small label and supporting stats.
- A small label or eyebrow stacked above a heading.
- Section numbers like 01, 02, 03.
- Gradient text, glass, blur, glow, or soft grey shadows under rounded boxes.
- A thick coloured border on one side of a card, list item or alert.
- Monospace as decoration. Monospace is only for text a person copies, such as a server address.
- Emoji or symbols standing in for icons. Arrows appended to buttons or links.
- Meta strings joined with middle dots or bullets ("2021 · Drama · 2 h"). Write a short phrase
  instead ("2021, directed by Denis Villeneuve, 1 hour 56 minutes").
- Labels built as "WORD — fragment", or one word in a headline set in a different style.
- Hero banners, carousels with arrows, rating stars, genre pills, stat tiles, charts, sidebars,
  avatar circles, stock photos and illustrations.
- Any brand colour, including streaming-service red, purple or blue.
- Anything operator-facing: server health, container names, queues, logs, metrics.

Always:
- Group with spacing and alignment first; add a rule only where spacing is not enough.
- Use one component vocabulary on every screen: the same bar, the same tab style, the same row,
  the same button pair (solid white primary, outlined secondary), the same notice.
- Show the states a member can reach: loading, empty, error, one service down, success,
  selected, disabled. Each state says what is happening in words.
- Name every control by what it does ("Resume in Jellyfin", "Copy address", "Request this").
  Never "Submit", "Continue" or "Learn more".
- Write errors as the problem and the way forward ("Audiobooks are unavailable right now. Try
  again later, or open Audiobookshelf directly.").
- Write calm, plain, second-person copy in sentence case. Never "we", "our" or "us". No em or en
  dashes. Use curly quotes and the ellipsis character ("Loading…").
- Never mention a library the member cannot use. A member sees a complete service, never a
  reduced one with gaps.
- Theme the browser surfaces too: text selection is white with black text, scrollbars are thin and
  grey on black, the text caret is white, and links use an underline offset of a few pixels.
- Motion: one moment only, the thin rule under the wordmark drawing in from the centre on first
  load. Everything else is an instant change or a short colour inversion. Respect reduced motion.
- Use credible content. Titles, names and times are illustrative placeholders, so keep them
  realistic and never invent features Avrana does not have.

Confirm the contract, then wait for the first screen prompt.
```

---

## Section 2. Screen prompts

### Prompt 1. Home, phone (360x640, then 390x844)

```
Screen: Avrana Home for a signed-in member, Ada, at 360x640. Composition "compact content home".

1. The compact centred AVRANA wordmark with its thin rule. Directly under it, one text bar of five
   links in a single row: Watch, Listen, Read, Request, Help, 44px tall, ending above y=260. Small
   text links "Search" and "Ada" at the top right.
2. CONTINUE: one row of at most four items, video and audio mixed, as a rail with the next item
   visibly cut off at the right edge so it reads as scrollable. Each item: artwork in its own shape
   (16:9 still for an episode or film, square for an audiobook), the title in white beneath, one
   grey line in words ("Episode 4, 32 minutes left", "Chapter 12, 3 hours 10 minutes left"), and a
   2px progress line under the artwork. Each item is a link to the app that plays it.
3. NEW THIS WEEK: text tabs All, Movies and TV, Audiobooks, Books (only the libraries Ada can use);
   the selected tab is white with a 1px white line beneath, the others grey. One row of at most
   four new items in their own shapes, with the title and the library name in grey. A text link
   "See everything new".
4. Footer: small centred text links Account and Sign out.

Home is no taller than two phone screens (about 1280px). No per-library shelves, no hero image,
no search field taking space. Show the focus ring on the first Continue item.
```

### Prompt 2. Home, desktop (1280x800)

```
Screen: the same Avrana Home at 1280x800.

Same order and content: compact centred wordmark and rule, the five-link bar centred beneath it,
"Search" and "Ada" at the far right. Continue and New this week each sit on a single line of four
items in a centred column about 1080px wide; no rails. Tabs above New this week as text links. The
page fits in about one desktop screen with generous black space. Footer links centred. Show one bar
link in its hover state (solid white, black text).
```

### Prompt 3. Home states (phone, one canvas, five variants)

```
Screen: five variants of the Avrana Home at 360x640 on one canvas, labelled underneath for review
only.

A, one service down: "Listen" in the bar is struck through in grey. Directly under the bar, one
notice with a 1px #E8CF8A border and #E8CF8A text: "Audiobooks are unavailable right now. Films,
shows and books still work." Audiobook items are absent from Continue and New. Help and Account
still work.

B, everything down: the bar shows all four library links struck through. One notice: "Avrana's
libraries are unavailable right now. Help and your account still work." No rows.

C, planned maintenance: the same notice style with an operator-written sentence: "Avrana is
getting an update tonight at 10 pm. Expect a short break." Nothing struck through.

D, new member: no Continue section. In its place one grey sentence: "Nothing started yet. Start
with something new below." Then New this week as normal.

E, loading: headings in place; artwork areas drawn as empty 1px #474747 outlines on pure black in
each library's shape, and the word "Loading…" in grey under each heading. No spinners, no shimmer,
no grey fills.
```

### Prompt 4. The New page

```
Screen: Avrana "New" page at 390x844 and at 1280x800.

Compact wordmark linking home, the five-link bar. Heading "New" in large serif. Text tabs: All,
Movies and TV, Audiobooks, Comics, Books (only libraries the member can use), the selected tab
white with a line beneath. Items grouped by library under a grey section heading with a count in
tabular figures ("MOVIES AND TV  6"). Phone: a wrapped grid of two posters or three square or comic
covers per line. Desktop: a wrapped grid in each library's own shape. Each item shows artwork, the
title, and a grey line in words ("Added on Tuesday"). Include an empty tab state: "Nothing new in
Comics this week."
```

### Prompt 5. Search and results

```
Screen: Avrana search at 390x844, query "dune". Where search lives is not yet decided; explore it
as its own page reached from the "Search" link at the top right.

A full-width field with a visible label "Search" above it, a 1px #6E6E6E border, square, and the
placeholder "Films, shows, books, audiobooks…". Results grouped by where they live, each under a
grey section heading with a count: "MOVIES AND TV  3", "AUDIOBOOKS  2", "BOOKS  4". Each result is a
ruled row: small artwork in its own shape, the title in white, a grey line in words ("2021, directed
by Denis Villeneuve", "Frank Herbert, read by Scott Brick, 21 hours"), and on the right an outlined
button naming the destination: "Open in Jellyfin", "Listen in Audiobookshelf", "Open in Calibre-Web".

Below, a section "NOT HERE YET" with one row "Dune: Part Three, 2026" and an outlined button
"Request this", which opens the request service with the search filled in. Above the results, one
grey line: "Comics could not be searched right now." Also show the no-results state on a second
frame: "Nothing matches “zzz”. Check the spelling, or ask for it with Request."
Results only include libraries the member can use.
```

### Prompt 6. Title page: film, list-detail on desktop

```
Screen: Avrana title page for the film "Arrival", at 390x844 and at 1280x800.

Phone: compact wordmark, the bar, then the 2:3 poster at about 60% of the width, centred. The title
"Arrival" in large serif with balanced line breaks. A grey line: "2016, directed by Denis Villeneuve,
1 hour 56 minutes". A 2px progress line with "41 minutes left" beside it. A short synopsis in white
at 17px. Then one solid white full-width button "Resume in Jellyfin" (black text, square) and an
outlined button "Open the Jellyfin app". A grey line: "Plays in Jellyfin. The app gives the
steadiest playback."

Desktop: list-detail, the poster at 280px on the left and the details on the right, with "MORE IN
MOVIES AND TV" as one row of four posters beneath. No backdrop image, no ratings, no genre pills.
Show the primary button's focus state.
```

### Prompt 7. Title pages: audiobook and comic

```
Screen: two Avrana title pages side by side at 390x844, same structure as the film page.

Left, the audiobook "Project Hail Mary": a square cover, the title, a grey line "Andy Weir, read by
Ray Porter, 16 hours 10 minutes", "Chapter 18 of 34, 7 hours 2 minutes left" with a progress line, a
synopsis, a white button "Continue in Audiobookshelf", and an outlined button "Listen on your phone"
that leads to help for the listening apps.

Right, the comic "Saga, Volume 1": a 13:20 cover, the title, a grey line "Brian K. Vaughan and Fiona
Staples, issues 1 to 6", a white button "Read in Komga", and an outlined button "Read in a comic app"
that leads to help.
```

### Prompt 8. Welcome (first visit after an invite)

```
Screen: Avrana welcome page shown once to a new member, Sam, at 390x844.

Compact wordmark. Heading "Welcome, Sam." One sentence: "Here is what is ready for you, and the one
app to install for each." One ruled row per library Sam can use (for example Movies and TV, and
Audiobooks), each naming what it is, the recommended app for Sam's phone, and a text link "Set it up".
Then a section "ADD AVRANA TO YOUR HOME SCREEN" with two short numbered steps each for iPhone (Share,
then Add to Home Screen) and Android (the menu, then Add to home screen), and a grey line: "Avrana opens
like an app. Films and books still play in their own apps." A white button "Go to Avrana". This screen
may be the most spacious and ceremonial of all, like the first card of a film.
```

### Prompt 9. Help for one library, with device jump links

```
Screen: Avrana help page "Movies and TV" at 390x844.

Compact wordmark, the bar with Help selected. Heading "Movies and TV". Under it, device links that
wrap onto two or three lines and jump down the page: iPhone and iPad, Android, Roku, Fire TV, Google
TV, Apple TV, Smart TVs, Windows, Web browser. Each device is a section: a serif heading, the app name
with a small grey "Recommended" note beside it, an inline text link "Get it on the App Store", and
numbered steps in grey. The server address appears in monospace in a thin outlined box with a text
button "Copy address": https://watch.avrana.net. After copying, a snackbar slides up at the bottom:
a black bar with a 1px white border reading "Address copied". Footer links: All help, Back. No
accordions, no screenshots, no icons.
```

### Prompt 10. Account

```
Screen: Avrana account page for Ada at 390x844.

Heading "Your account". A list of Name, Username and Email, labels small and grey, values white.
A section "YOUR LIBRARIES" as outlined text chips naming only what Ada can use. A section "KINDLE"
with the saved address in monospace and a text link "Change address". A section "SIGN-IN AND
SECURITY" with outlined buttons "Password and passkeys" and "Sign out". A grey line: "To leave
Avrana or remove your data, write to Cody." with the address as a text link.
```

### Prompt 11 (optional). "Ask Avrana" help entry

```
Screen: the Avrana Help index at 390x844 with an "Ask Avrana" entry. This is a separate, unapproved
workstream; explore only.

Under the heading "Help", a labelled field "Ask a question about using Avrana" with a white button
"Ask". Beneath, a grey line: "Answers come from these help pages. For anything about your account,
write to Cody." One answered example as plain text with two cited help-page links underneath
("From the Movies and TV help"). Also show the refusal state: "That needs a person. Write to Cody."
Then the help topics as ruled rows. No chat bubbles, no avatars, no typing animation.
```

---

## Prompt Z. Finish gate (send after every screen)

```
Review the screen you just made against the Avrana contract and list every violation, then fix all
of them in one pass and show the corrected screen. Check:

1. Composition: on Home, the wordmark, then the five-link bar ending above y=260 at 360x640, then one
   Continue row, then one New this week row with tabs. No per-library shelves. At most two phone
   screens tall.
2. Colour: background exactly #000000; artwork is the only colour; status colour appears only
   beside words.
3. Type: one serif at weight 400; no bold; no single accented word; body lines under about 70
   characters; more space above headings than below.
4. Shape: radius 0 everywhere, 1px rules, no shadows, gradients, blur or glow.
5. Slop: no icon cards, stat tiles, eyebrow labels, section numbers, middle-dot meta strings,
   appended arrows, emoji, pills, carousels, ratings, hero banners or sidebars.
6. Hand-off: every Play, Read or Listen action names its app.
7. States: the screen's loading, empty, error and down states each say what is happening in words.
8. Access: every control is at least 44px tall, has a visible label, and shows the focus ring;
   contrast passes (secondary text #9A9A9A, interactive borders #6E6E6E).
9. Copy: actions named by what they do; errors give the way forward; no "we", "our" or "us"; no
   dashes; nothing names a library the member cannot use; nothing operator-facing.
10. Identity: with the wordmark covered, the screen still could not be mistaken for any other
   streaming service.

Report which checks failed before fixing, and say plainly if any check could not be verified.
```

---

## Section 3. Tone variants inside composition B

Ask for each as a variant of Prompts 1, 2 and 6. They change tone, never structure.

**Variant A, Title Card (baseline)**
```
Variant "Title Card": artwork at modest size and even spacing, generous black space, long thin rules
between sections, the wordmark slightly larger. Quiet and ceremonial.
```

**Variant B, Programme**
```
Variant "Programme": like a repertory cinema's printed programme. Artwork a little larger, titles set
beneath in tracked serif capitals, captions in grey. Still one Continue row and one New row, still no
hero image.
```

**Variant C, Catalogue**
```
Variant "Catalogue": like a well-kept library index. Continue as ruled rows (thumbnail, title, time left
in words, the app it opens in) instead of artwork tiles; New this week as a compact row. The densest
and fastest to scan of the three.
```

---

## Section 4. Edit prompts

```
Set the background to exactly #000000 everywhere; remove any near-black or grey surface fills.
```
```
Make every corner square (radius 0), including buttons, tabs, fields, chips and artwork.
```
```
Remove all shadows, gradients, blur, glow and elevation. 1px borders only.
```
```
Use Times New Roman at weight 400 for every text element. No bold, no italic emphasis on single words.
```
```
Remove every icon, emoji and appended arrow. Use text labels only.
```
```
Replace every middle-dot or bullet meta string with a short phrase in words.
```
```
Remove any small label sitting above a heading. Keep the heading only.
```
```
Move the five-link bar (Watch, Listen, Read, Request, Help) directly under the wordmark so it ends
above y=260 at 360x640.
```
```
Remove the per-library shelves from Home. Keep one Continue row and one New this week row with tabs.
```
```
Show each artwork in its library's shape: 2:3 films, shows and books, square audiobooks, 13:20 comics.
```
```
Show the focus ring (2px black gap, 2px white ring) on the primary button and one artwork item, and the
hover inversion on one bar link.
```
```
Rewrite every line of copy in calm sentence case, naming actions by what they do, with no "we", "our",
"us" or dashes.
```

## What Stitch output is not

Concept references only. Anything adopted is rebuilt in the Avrana home application against
`DESIGN.md` with no JavaScript (AVR-452), and passes the offline UI harness, the accessibility checks
and the authorization and degradation tests the charter requires.
