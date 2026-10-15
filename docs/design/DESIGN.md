---
name: Avrana
description: The member-facing house style for avrana.net and the custom services behind it.
colors:
  ink: "#000000"
  paper: "#ffffff"
  ash: "#9a9a9a"
  rule-quiet: "#474747"
  rule-control: "#6e6e6e"
  rule-strong: "#999999"
  ok: "#8fe3a6"
  warn: "#e8cf8a"
  err: "#ff8b8b"
typography:
  wordmark:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "clamp(2.6rem, 9vw, 4.4rem)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.34em"
  wordmark-compact:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "clamp(1.75rem, 6vw, 2.5rem)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.34em"
  headline:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "clamp(1.7rem, 5vw, 2.3rem)"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "0.04em"
  title:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "1.7rem"
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "0.06em"
  subtitle:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "1.35rem"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "0.04em"
  body:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.55
  small:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "0.92rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "\"Times New Roman\", Times, \"Liberation Serif\", Tinos, \"Noto Serif\", serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: "0.22em"
  code:
    fontFamily: "ui-monospace, \"SF Mono\", Menlo, Consolas, \"Liberation Mono\", monospace"
    fontSize: "0.95em"
    fontWeight: 400
rounded:
  none: "0"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "44px"
  "8": "64px"
components:
  button-primary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "12px 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  button-ghost:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "12px 20px"
    height: "44px"
  button-ghost-hover:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  button-danger:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.err}"
    rounded: "{rounded.none}"
    padding: "12px 20px"
  tile:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.title}"
    rounded: "{rounded.none}"
    padding: "22px 24px"
  tile-hover:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  field:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "12px 14px"
    height: "48px"
  badge:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ash}"
    rounded: "{rounded.none}"
    padding: "2px 10px"
---

# Design System: Avrana

> **Status: proposed.** Written 2026-10-11 from the code that is in Git today
> (`services/avrana-portal/portal.py`, `services/avrana-kindle-connector/kindle.py`,
> `services/avrana-audible-connector/connector/app/static/style.css`,
> `services/authentik/blueprints/avrana-landing.yaml`). It codifies the existing identity and
> closes the gaps listed in [the 2026-10-11 audit](../audits/2026-10-11-web-interface-audit.md).
> It is the visual standard for [Avrana Media 2.0](MEDIA-2.0.md).
> Nothing here is deployed. Every change to a running service needs the owner's approval for that
> change, per `AGENTS.md`.

## Scope

This system governs the surfaces Avrana owns:

| Tier | Surfaces | How the system applies |
|---|---|---|
| Custom (source in this repo) | avrana.net portal, Kindle connector, Audible connector | Full system: tokens, components, copy rules |
| Configurable (upstream app, supported theming hook) | Authentik flows and user library (brand CSS), Homepage (`custom.css`, settings) | Tokens only, through the app's own hook, never by DOM surgery |
| Upstream (leave alone) | Jellyfin, Seerr, Audiobookshelf, Komga, Calibre-Web, Shelfarr, Shelfmark, Omnibus, the arr stack, SABnzbd, Mylar3, Beszel, Tracearr, OliveTin, Home Assistant, UniFi, BookStack | Not themed. The system's job there is to hand off cleanly: correct link, correct sign-in instructions, nothing injected |

## Overview

**Creative North Star: "The Title Card"**

Avrana looks like the card before a film starts: black screen, one serif word in widely spaced
capitals, a short rule beneath it, then nothing that does not need to be there. The libraries
behind it (Jellyfin, Audiobookshelf, Komga) are full of colour and artwork; Avrana's own pages are
the quiet frame around them, and that contrast is the point. A member should recognise an Avrana
page from across the room and never mistake it for a generic dashboard.

The surfaces are in **Operate** mode (the visitor came to get somewhere or set something up) with
one **Read** surface (Help). Brand lives in precise details: the wordmark, the tracking, the square
rules, the inversion on hover. Everything else is plain, legible and quick.

**Key Characteristics:**
- Pure black ground, white type, one grey for secondary text. No accent colour.
- One serif family for everything people read. Monospace only for strings people copy.
- Square corners, 1px rules, no shadows, no gradients, no icons for decoration.
- Interaction is inversion: hover and focus turn an outlined element solid white.
- Single column, centred, at most 720px wide.

## Colors

A monochrome palette with three status colours that only ever carry status.

### Neutral
- **Ink** (#000000): every page background, and the text colour of inverted (hovered, primary) elements.
- **Paper** (#ffffff): primary text, the wordmark, primary buttons, hovered tiles.
- **Ash** (#9a9a9a): secondary text: descriptions, hints, section labels, step lists. 7.4:1 on Ink.
- **Quiet Rule** (#474747): dividers between list rows and platform sections. Decorative only; 2.3:1, so it must never be the only edge of something clickable or typeable.
- **Control Rule** (#6e6e6e): the resting border of anything interactive: tiles, fields, ghost buttons, badges that sit next to controls. 4.1:1 on Ink, which clears WCAG 1.4.11.
- **Strong Rule** (#999999): the rule under the wordmark and underlines on text links.

### Status
- **Ok** (#8fe3a6), **Warn** (#e8cf8a), **Err** (#ff8b8b): text and border colour for banners, badges and failed rows. All above 10:1 on Ink.

### Named Rules
**The No Accent Rule.** There is no brand colour. Emphasis comes from inversion (white block on
black), size and position. Adding a hue for decoration breaks the title-card read.

**The Status Is Words Rule.** A status colour always travels with a word ("Imported", "Failed",
"Audible Plus"). Colour alone never carries meaning.

**The Interactive Edge Rule.** If it can be clicked or typed into, its resting edge is Control
Rule or brighter. Quiet Rule is for separating content, not for drawing controls.

## Typography

**Display and Body Font:** Times New Roman (with Times, Liberation Serif, Tinos, Noto Serif, serif)
**Code Font:** the platform monospace (ui-monospace, SF Mono, Menlo, Consolas, Liberation Mono)

**Character:** a single system serif, used at regular weight throughout, with hierarchy built from
size, tracking and case rather than boldness. Liberation Serif and Tinos are metric-compatible with
Times New Roman, so line breaks stay put on Linux and ChromeOS; Noto Serif covers Android, which
ships no Times.

### Hierarchy
- **Wordmark** (400, clamp(2.6rem, 9vw, 4.4rem), tracking 0.34em with an equal `text-indent`): the home page only.
- **Wordmark compact** (400, clamp(1.75rem, 6vw, 2.5rem), same tracking): every other page, as the link home.
- **Headline** (400, clamp(1.7rem, 5vw, 2.3rem)): the page's own title, the one `<h1>`.
- **Title** (400, 1.7rem, tracking 0.06em): tile labels.
- **Subtitle** (400, 1.35rem): sub-sections such as a help page's platforms.
- **Body** (400, 1.0625rem / 17px, line height 1.55, measure 65ch): prose, form labels, list items.
- **Small** (400, 0.92rem): hints, descriptions under tiles, footer text.
- **Label** (400, 0.9rem, tracking 0.22em, uppercase, Ash): section headings only.

### Named Rules
**The Matched Indent Rule.** Tracked, centred capitals carry a `text-indent` equal to their
`letter-spacing`, or they sit visibly left of centre. Change the two together.

**The One Wordmark Rule.** The wordmark exists in exactly two sizes, both defined here. Today it
is drawn four different ways (portal, Kindle, Audible topbar, Authentik); all four converge on these.

**The Copyable Mono Rule.** Monospace is for strings a person types or copies elsewhere: server
addresses, OPDS URLs, Kindle addresses, recovery codes, tokens. Never for labels or decoration.

**The One Caps Level Rule.** Uppercase tracked labels appear at one level per page. A label
directly above another uppercase label (as on the Kindle page today) is not allowed.

## Layout

A single centred column, `max-width: 720px` (640px for single-form pages), with 24px side padding
(20px under 560px). Vertical rhythm comes from the spacing scale (4, 8, 12, 16, 24, 32, 44, 64px);
the main column uses a 44px gap between blocks on desktop and 32px on phones.

Tiles sit in a two-column grid with a 16px gap that collapses to one column under 560px. Prose
and step lists cap at 65ch. Pages open with roughly 12vh of space above the wordmark on the home
page and 6vh on inner pages, so the content, not the brand, owns the first screen on a phone.

**The Footer Is Navigation Rule.** Every page ends with the same footer row: the relevant
"Back" or "All help" link, then "Avrana home". Nothing is reachable only by the browser's back
button.

## Elevation & Depth

Flat. There are no shadows, blurs, gradients or layered surfaces. Depth is replaced by two tools:
the 1px rule (structure) and inversion (state). The only box-shadow in the system is the focus
ring, which is a two-ring outline, not an elevation.

**The Focus Ring Rule.** Every interactive element shows the same ring on `:focus-visible`:
`box-shadow: 0 0 0 2px #000, 0 0 0 4px #fff`, plus `outline: 2px solid transparent` so Windows
High Contrast still draws one. No element sets `outline: none` without this ring.

## Shapes

Square everywhere (`border-radius: 0`). Edges are 1px. The rule under the wordmark is 64px wide
on custom pages and 160px in Authentik, where the wordmark sits in a wider card; both are kept.
Cover art in lists is a square crop with no rounding. (Media artwork: each library's own shape is proposed; see Media components.)

## Components

### Wordmark header
- Centred `AVRANA` in the wordmark style, a 64px Strong Rule beneath it.
- On inner pages it is a link to `https://avrana.net` and uses the compact size.
- The Audible connector's left-aligned topbar is replaced by this header.

### Tile (navigation)
- Outlined block, Control Rule edge, 22px by 24px padding, label in Title style, one line of
  description in Small/Ash beneath.
- Hover and focus invert: Paper ground, Ink text, description darkens to #333333.
- Used only for navigation (portal grid, choosers, the interstitial's two choices). Never for
  displaying data.

### Buttons
- **Shape:** square, minimum 44px tall.
- **Primary:** Paper ground, Ink text. One per form.
- **Ghost:** transparent, Control Rule edge, Paper text; inverts on hover and focus.
- **Danger:** ghost with Err text and edge; inverts to an Err ground. Always behind a confirmation.
- **Hover / Focus:** 160ms colour transition only; the focus ring is always added on
  `:focus-visible`, independent of the hover inversion.

### Fields
- Transparent ground, Control Rule edge, 12px by 14px padding, 48px tall, body type.
- Focus: edge turns Paper, plus the focus ring.
- A visible `<label>` above every field; hints sit under the field in Small/Ash and are linked
  with `aria-describedby`. Errors use Err text in the banner and `aria-invalid="true"` on the field.
- Pages declare `color-scheme: dark` so native checkboxes, selects and scrollbars render dark.

### Banner
- 1px edge in the status colour, text in the same colour, 12px by 16px padding.
- Success and notices use `role="status"`; errors use `role="alert"`.

### Badge and chip
- Uppercase small text with 0.06em tracking, 1px edge, 2px by 10px padding. Status colour only
  when the badge names a status.

### List row
- Rows separated by Quiet Rule, first row also ruled on top. Cover (60px, 48px on phones), meta,
  then the row's control on the right. The control's hit area is the whole row where possible
  (wrap the row in the `<label>`).

### Text link
- Paper text with a 1px Strong Rule underline offset 2px; underline turns Paper on hover; focus
  ring on focus. In footers, links get 12px of vertical padding so the target reaches 44px.

### Help page (signature component)
- Headline names the topic ("Movies and TV"). Under it, a row of platform links that jump to each
  section, so a member with a Roku does not scroll past six other devices.
- Each platform is a section with a Subtitle heading, the recommended app first, store link as an
  inline text link (not full width), then numbered steps. Server addresses are in Copyable Mono.

## Media components

> **Status: proposed (AVR-426, 2026-10-14). Nothing here is deployed.** Built against fixtures in
> [the home preview](../../tests/ui/home_preview/README.md), which shows every component below in
> every state at 360, 390 and 1280px (`check.mjs` writes the renders; this repository tracks no
> images). **Owner-approved** and not to be revised here: the compact Home with one Continue row
> and one bounded New row, and browsing on its own New page (AVR-431, AVR-452). Everything else in
> this section is a proposal. Where it departs from the rules above, it says so and names the
> owner decision in [the preview's proposals](previews/home/README.md#proposals-for-the-owner).
> It follows the [Media UX research](https://linear.app/avranakern/document/avrana-media-ux-research-implementation-principles-backlog-gap-4a08eb39e598).

### Two shells
- **Read and Operate** (Help, Account, Welcome, sign-in pages): the 640px single-form column.
- **Browse** (Home, New, Search, a title page): the 720px column. A wider Browse shell is not
  proposed: four covers fit in 720px, and a wider page would need its own type sizes (owner decision 10).
- Both shells share the top: the account control, the compact wordmark linking home, then the
  bar of places. Both end with the shared footer: Account and security (signed in) and Help.

### Four things that look alike and are not
| Component | Used for | Looks like | One outcome |
|---|---|---|---|
| Navigation tile | Choosing a place (portal, choosers) | Outlined block, Title-style word, inverts on hover | Goes to the place |
| Media card | One title in New, on Home or the New page | Cover in its library's shape, title, one Small/Ash line | Opens the title page |
| Resume card | One title in Continue | A media card with a 3px progress rule and the time left in words | Opens the library's own app at the place the member stopped |
| Search result | One match on the Search page | A ruled list row: small cover, title, one line, "In" and the library | Opens the title page |

A tile never shows a title, and a card is never used for navigation. No card carries a second
control, a menu or an icon.

### Artwork
- **Proposed exception to Shapes** (owner decision 1): each library keeps its own shape
  (2:3 posters for films and series, 16:9 stills in Continue, square audiobook covers, 2:3 books,
  13:20 comics). Covers keep 1px Quiet Rule edges, square corners and no shadow. Under the
  alternative, every cover is the square crop the Shapes section names today.
- Covers in one row share a top edge; their widths differ. A cover is decoration (`alt=""`):
  the title is always beside it in words.
- Library artwork keeps its colour; the page around it stays black and white (owner decision 3).

### Places bar
- Watch, Listen, Read, Request and Help, as words in one ruled bar under the wordmark on every
  Browse page. It wraps at large text and never scrolls.
- Only places the member can use. A library the member cannot use has no place at all. A library
  whose service is down keeps its word, struck through and not a link, with ", unavailable" for
  screen readers (owner decision 7).

### Account control
Specified in [the preview's account section](previews/home/README.md#account-and-shared-navigation-avr-478-proposed)
(AVR-478): a square initial and the word Account, a native disclosure, three items, no icon.

### Row of titles (rail)
- At most four cards. On a phone it scrolls sideways inside itself with part of the next cover
  showing; at 720px and wider all four fit and it does not scroll. The page never scrolls sideways.
- Under the row, a text link to the whole list ("Everything new this week"). Nothing is reachable
  only by swiping.
- **Keyboard and focus on a phone:** each card is one link and one Tab stop, in reading order left
  to right; the row scrolls the focused card into view (browser default, no script); the card
  shows the two-ring focus mark and its cover's edge turns Paper. After the last card, Tab reaches
  the "Everything new" link, then the next section.

### Tabs
Views of one row (All, then each library). Each tab is a link the server answers; the tab on
screen is underlined in Paper and carries `aria-current`. On a phone the tabs scroll inside their
own row. A tab exists only for a library that is answering and that the member can use.

### Wall
The New page's grid of media cards: three columns on a phone, six at 720px. Same card, same shape rules.

### Search field
- A plain GET form to the same site (`form-action 'self'`, still no script). A visible label above
  the field ("Title, author or year"), the field (Fields component), a Primary button "Search",
  and a Small/Ash hint linked by `aria-describedby`: "Searches your libraries only."
- No suggestions while typing: a suggestion list is a second way to leak a title, and needs script.
- The query is trimmed, cut to 100 characters, escaped, and shown back in the field and the page title.
- **The entry point on Home is not placed yet** (owner decision 9). The approved Home composition
  is not changed here.

### Search result
- Results grouped by library under Subtitle headings, each group a ruled list (List row). A row is
  one link: the cover at a fixed width (60px, 48px on phones) in its own shape, the title, its
  line, and "In Movies and TV", so a row read alone says where the title lives.
- A count in words before the groups ("8 found."), announced as a status.
- Only libraries the member can use are searched. "Nothing called ... in your libraries" reads the
  same whether the title is in a library the member cannot use or nowhere at all.

### Title page
- In this order: the title (Headline, the one `h1`), one line of kind and year or author, **one**
  Primary action, the progress rule and time left when the library reports it, one sentence about
  the title when the library has one, then the facts (Library, Year or Author) in a ruled list.
- The action names the library and never claims anything plays: "Watch in Movies and TV",
  "Resume in Audiobooks", "Read in Books". It opens that library's own app at the title (M3.5).
- At 720px the cover sits beside the words; on a phone it sits above them, small enough that the
  title and the action are on the first screen.
- A title in a library the member cannot use does not exist: the same Not Found as an unknown title.

### Unavailable section
- One library down: one Warn banner under the bar on Home and the New page, said once
  ("Movies and TV are unavailable right now. Everything else works."), its place struck through,
  its tab, items and Continue entries gone. Everything else works as usual.
- All of the member's libraries down: the operator's notice in the banner; Request, Help and the
  account still work.
- An error and a timeout read the same to a member as unavailable or slow. No raw error, host,
  service or software name ever reaches the page.

### States and the words for them
Loading is never a spinner: the page renders once, and a part whose service missed its two
seconds says so and offers "Try again", a plain link to the same page.

| Component | Loading (slow) | Empty | One library down | All down | No library | Signed out |
|---|---|---|---|---|---|---|
| Continue | "Audiobooks are taking longer than usual." and Try again; other items shown | "Nothing in progress. Whatever you start in a library appears here, ready to pick up where you stopped." | Its items are left out; the banner says why | Not shown | Not shown | Not shown |
| New row | The same sentence on that tab, and Try again | "Nothing new in audiobooks this week." or "Nothing new this week." | No tab for it | Not shown | Not shown | Not shown |
| New page | The same sentence, and Try again | "Nothing new here this week." | No tab for it | "Movies and TV, audiobooks, books and comics are unavailable right now." | "No library is shared with this account yet. Ask the person who invited you, or read Help." | "Sign in to see the libraries shared with you." |
| Search | "Audiobooks are taking longer than usual, so nothing from them is shown yet." and Try again; other results shown | "Nothing called "…" in your libraries. Check the spelling, or ask for it with Request." | "Movies and TV were not searched, because they are unavailable right now." | "… are unavailable right now, so nothing can be searched. Try again later, or read Help." Field and button disabled | As the New page | As the New page |
| Title page | "Audiobooks are taking longer than usual." and Try again; no action | No progress: the action is the plain verb ("Watch in …") | "Movies and TV are unavailable right now. This title will be here when they are back." No title, no action | As one library down | Not Found | Not Found |
| Places bar | Unchanged | Unchanged | Struck through, not a link | Every library struck through | Request and Help | Help, and Sign in in place of Account |

All copy follows the house rules: second person or neutral, no "we", no dashes, library names in
member language, and nothing named that the member cannot use.

## Do's and Don'ts

### Do:
- **Do** keep pages black with white serif type and one grey (#9a9a9a) for secondary text.
- **Do** draw every interactive edge in Control Rule (#6e6e6e) or brighter.
- **Do** show the two-ring focus indicator on every interactive element.
- **Do** use the compact wordmark as a link home on every inner page, and end every page with the shared footer row.
- **Do** keep copy in plain second person or neutral imperatives, with no first-person "we" and no em or en dashes.
- **Do** keep the 404-not-403 doctrine: a page for something the viewer cannot use does not exist for them.

### Don't:
- **Don't** add a brand accent colour, gradients, shadows, glass, rounded corners or decorative icons.
- **Don't** use `outline: none` without the focus ring.
- **Don't** set monospace as a general UI face (Authentik's brand CSS currently does); keep it for copyable strings.
- **Don't** theme upstream applications by injecting CSS through the proxy or patching their files. Use only a hook the application supports.
- **Don't** auto-refresh whole pages; update the changing part, or let the member refresh.
- **Don't** name a service in copy that the viewer might not be allowed to reach.
