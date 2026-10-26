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
> **Brand, 2026-10-18:** on the AVR-584 draft branch, the AVRANA brand package v1.0.0 (approved 2026-10-17)
> replaces the serif, `#000`/`#fff` and typed wordmark below on Home shell pages only, pending the owner's visual
> review; see "Brand v1.0.0 on Home shell pages (AVR-584)". The rest of this document still describes the portal and
> connectors until AVR-362 converges them.
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
Cover art in lists is a square crop with no rounding. Media artwork keeps each library's own shape
(owner decision, 2026-10-15; see Media components).

## Components

### Wordmark header
- Centred `AVRANA` in the wordmark style, a 64px Strong Rule beneath it.
- On inner pages it is a link to `https://avrana.net` and uses the compact size.
- The Audible connector draws this header in place of its old topbar, and Kindle uses the compact size
  (AVR-362); the token-drift gate compares each size only with services that draw the same one.

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

### Skip link
- Canonical definition: `docs/design/components/skip-link.html` (markup) and `docs/design/components/skip-link.css` (styles). Portal (`portal.SHELL`, `portal.STYLE`) and Home (`templates/base.html`, `templates/style.css`) carry byte-identical copies; `tests/test_skip_link.py` fails on drift.
- Markup contract: the first element in `<body>` is `<a class="skip-link" href="#main">Skip to main content</a>`; the target is the page's single `<main id="main" tabindex="-1">`.
- Hidden with the clip pattern (not `display:none`), visible on `:focus-visible` as an inverted Paper-on-Ink block, fixed at top left so a sticky header cannot cover it, with the shared two-ring focus ring from `a:focus-visible`. Existing tokens only; no transition, so nothing to gate on reduced motion. Works without JavaScript.

### Shell masthead (Home, Search, Account, Help)
> *Superseded on shell pages by the Concept K shell (AVR-716): the top row is gone (Search and Account are tabs),
> the places bar is on Home only, and `viewport-fit=cover` is set. See "Concept K · Avrana Console" above.*
- The heading is the brand package's Media L3 lockup, not the typed wordmark (AVR-584; "Brand v1.0.0 on Home
  shell pages" below).
- Top row, right-aligned: Search (when the member has a searchable library) and the native account
  disclosure, whose menu holds "Account and security". Help lives in the places bar only: it is always the
  last place (Watch, Listen, Read, Request, Help), on every shell page. The places bar keeps one row at 360px and wraps whole
  words at large text; the compact wordmark is capped by the viewport width so it never wraps.
- Side gutters are `max(1.25rem, env(safe-area-inset-*))`. `viewport-fit=cover` is not set, so Safari keeps
  content clear of the notch itself; the insets matter only if a later change opts in.

### Media card (Home rails)
- One link per card, one action. Order: title (two lines at most), the creator, series or episode line
  (Ash, one line, ellipsis), progress in words, then on Continue cards the action verb ("Resume" or
  "Open") as small underlined text. Recently added cards carry no verb: the whole card opens the item.
- Clamping is visual only; the full title stays in the link text and so in its accessible name. When
  the view-model gives an `action_label`, it replaces the verb for assistive technology only.
- Every frame in a rail stands on one baseline: the rail's artwork height (180px), each shape's natural width
  (posters, books, comics, audiobook squares); a video still is held to a maximum width and stands
  shorter, bottom-aligned. Images are contained, never cropped into another shape.
- Rails scroll sideways. On phones every card in a rail is one width (11.25rem, about 1.75 to a screen), so
  the next card peeks in as a sliver; the rail snaps to card starts (mandatory), and a trailing spacer
  lets the last card snap to the start as well. From 45rem the cards fit the column and snapping is
  proximity only. A thin Quiet Rule scrollbar shows on pointer devices.
- Keyboard focus: browsers scroll a focused element into view only when it is wholly outside the
  scroller's optimal viewing region (the scroller less its `scroll-padding`), so a partly visible card
  would stay clipped. The rail's right `scroll-padding` leaves a region one card (plus focus ring) wide:
  a peeking card counts as outside, Tab and Shift+Tab bring it fully into view, and the rail's padding
  keeps the 4px ring unclipped. This relies on cards resting card-aligned, which is why phone rails snap
  mandatorily and carry the trailing spacer. No script. `tests/ui/check_home_export.mjs` checks it in Chromium with
  real key presses at 360, 390 and 390 at 200% text.
- Known, not fixed: when a cover's bytes arrive but cannot be decoded, the browser draws its own broken-image icon
  over the letter behind the frame. Hiding it needs script (an `onerror` handler, which the strict CSP forbids) or
  a full server-side image decode on every artwork request. The artwork route already refuses anything whose
  declared type is not JPEG, PNG or WebP or whose magic number does not match (`adapters/_base.py`); a matching
  magic number on a corrupt body is the remaining case, and a 404 instead would still show the same icon, so a
  decoder in the request path (more parsing of untrusted bytes) buys nothing. The dev mocks serve real,
  decodable synthetic PNGs in each natural shape (`dev/synthetic_art.py`), so reviews see real layout.
- Residual: from 45rem a still may be wider than the other cards; if the four cards ever overflow the
  column there (large text on a desktop), a still that straddles the edge can stay partly clipped when
  focused. Safari keyboard and VoiceOver behaviour is not covered by the Chromium check; it is part of
  the real-iPhone review (AVR-455).

### Help page (signature component)
- Headline names the topic ("Movies and TV"). Under it, a row of platform links that jump to each
  section, so a member with a Roku does not scroll past six other devices.
- Each platform is a section with a Subtitle heading, the recommended app first, store link as an
  inline text link (not full width), then numbered steps. Server addresses are in Copyable Mono.

## Concept K · Avrana Console on Home shell pages (AVR-713)

> **Status: in progress on fixture-only draft branches; not merged, not deployed, not phone-verified.** Owner
> decisions O2 (2026-10-25) and the Phase 1 approval (2026-10-26) are in DECISIONS.md. On **shell pages only**,
> Concept K replaces the Title Card and the monochrome rules below (the No Accent Rule, square corners, no glass,
> no decorative icons); the portal, Kindle, Audible and every page without the shell keep them, byte-identical.
> The reference is the Figma file "Avrana Media — Console" and the Concept K style kit. This section grows with
> each slice (MK-1 foundations, MK-2 shell, MK-4 Home, MK-5 pages, MK-6 motion) and is rewritten in MK-7.

**Foundations (MK-1, `templates/home.css`).** Colours keep the Brand v1.0.0 values under Concept K names
(`--ink #121214`, `--surface #161618`, `--raised #1E1E21`, `--cream #EDEAE4`, `--stone #AEABA7`, `--ash #8F8C89`,
`--graphite #5E5B57` decorative only, `--control #6E6C72`, `--line`, `--line-strong`); the older `--bg`, `--fg`,
`--dim` and `--rule-*` names are aliases. Status uses the console colours (`--ready #34D399`, `--warn #F59E0B`,
`--danger #EF4444`), always with words.

**Media yellow.** `--accent #EADA6E` (Butter-High, 13.1:1 on ink) and `--accent-deep #776A00` (14px+ semibold on
cream only, 4.55:1), with tints `--accent-selected` (22%) and `--accent-lens` (24%). It carries Atomic Purple's role
in Party: the nav lens, the chosen filter chip (tint, rim and a check glyph), the "yours" eyebrow and signal bar,
the role tag, and every focus ring (`--focus`). Never on lists that are not the member's state, never on progress
bars (cream), never inside a warning, never a large fill. Selection is told by geometry as well as colour (lens,
check, bar, tag shape); a warning is a rectangle with a glyph, words and an amber edge.

**Type.** Plus Jakarta Sans (variable 200 to 800, SIL OFL 1.1; `/brand/plus-jakarta-sans-latin.woff2` and
`-latin-ext.woff2`, `font-display: swap`, system fallback). Roles: display 48px Light, display fallback 44px Light,
page 28px, shelf 20px, button 17px Medium, body 15px, secondary 14px, eyebrow 12px Medium caps tracked 0.16em.
Big type is Light; small type Medium or SemiBold.

**Shape, glass, motion.** Radii: preview 20, panel 16, button 14, control 12, chip 8. One `.glass` class (28px
blur, inset highlights, masked `::before` rim; the element clips itself) worn by the three shell controls only (tab bar, Home button; the top-right utility on Library, MK-5a),
with solid fallbacks for no `backdrop-filter`, reduced transparency, more contrast and forced colours. Motion tiers
150, 300 and 200 ms (tier 3 capped at 200 ms; 600 ms only as a labelled Proposal behind a default-off flag); Reduce
Motion stops all animation.

**Shell (MK-2, AVR-716; D1, D5, D16).** Every shell page ends with the glass tab bar, `nav.tabbar` (aria-label
"Sections"), after the footer so it is last in reading and focus order, as on screen: Home, Library, Search, Me for a
member with a library; Home and Me for a member without one (a library a member cannot use is never named). It is
fixed above the bottom safe area (`viewport-fit=cover`, shell pages only), at most 28rem wide; its edges are in px,
and at very large text (viewport under 18em) it runs edge to edge so whole words still fit; a label never breaks
inside a word. The section's tab carries
the yellow lens, placed by `data-at` (the tab's index), which the server prints, so it is right without JavaScript;
the page script (MK-3) only moves `data-at` on a plain click. `aria-current="page"` marks the tab that is this page,
`"true"` the section a deeper page belongs to (Account, Help and its topics under Me, whose tab opens the Me hub
`/me` since MK-5b; places and titles under Home). Icons
are inline SVG in `currentColor`; Me shows the member's initial and its name says who is signed in. Library opens
its own page, `/library` (MK-5a, below). The page scrolls clear of the bar by 1rem.

Home keeps the L3 lockup as its heading, top left, and under it the places bar (Watch, Listen, Read, Request, Help)
as opaque chips: one row at 390px, whole chips wrapping at 320px or large text; a down library stays struck through.
Other shell pages keep "Avrana Media" as a visually hidden `h1` and show their own title first. Pages that are not
tabs (a place, a help topic, a title) add the glass Home button: the brand's Spire-A micro cut at the 24px it is drawn
for (`/brand/spire-a-24.svg`), the word "Home" in forced colours. The Me hub and Account link to Help; the old top
row (Search link, account disclosure) is retired.

**Home (MK-4, AVR-718; D6).** Under the places bar, a hero shows the member's own next thing: the first item in
Continue, or, with nothing in progress, the first item in Recently added. It is built only from this member's
sections for this request; a library that is down never supplies it, and a member with no library, resting
libraries or nothing set up gets no hero. Its eyebrow is part of its `h2` ("Continue: <title>"), yellow with the
3px signal bar only for Continue (the member's own state), Stone for Recently added. The title is the 48px Light
display role; it wraps and clamps visually at four lines, never fitted by shrinking. The art is the item's own
`/art` image twice: crisp at its natural shape over a blurred, dimmed copy that fades out before the text; with no
art, the letter frame; at 320px no poster (frame 22:2597); the backdrop is off in more contrast and forced colours.
One Cream hand-off names the app that opens ("Resume in Jellyfin" only for a saved position, otherwise "Open in
Jellyfin", "Listen in Audiobookshelf", "Read in Komga", "Open in Calibre-Web"), unlike cards, which name the
library in member language; it never claims playback. "Details" opens the title page only where one exists.
"New this week" is renamed "Recently added" (`id="h-new"` kept). Shelf headings take the 20px shelf role. Rails
carry 180px art (`--art-h`) in one 11.25rem card width on phones (`--card-min`, 9.5rem from 45rem), preview
radius, and on Continue a 3px Cream progress rule along the foot of the art, beside the words and hidden from
assistive technology; its length is a 5% step class (`pc0` to `pc100`), so no inline style is needed.

**Library (MK-5a, AVR-719; D1, memo sections 2 and 6).** `/library` is a tab page (its tab carries
`aria-current="page"`). Its title, "Library", sits top left in the page role, where other pages have the Home button,
and beside it the top-right glass utility, the third glass control, holds one Search link (a magnifier named
"Search"), shown only to a member who can search. The frames' filter and sort control is not built: there is no
honest order without new data. Under the title, opaque filter chips are plain links: All, then one chip per library
this member's sections hold, in Home's order and member language. `?lib=<library>` chooses one, checked against the
member's own libraries exactly as `?new=` is on Home (bounded, never echoed; anything else is All). The chosen chip
has the yellow tint, rim and a check glyph, and `aria-current="true"`; chips wrap as whole chips, and a label never
breaks inside a word. All shows one shelf per library: the newest items Home already has for it (at most four) on
the MK-4 rail, with a quiet "Open <app>" link to the member's own place route (`/watch`, `/listen`, `/comics`,
`/books`), only where the catalogue opens it for this member. One chosen library shows them as a grid on the 180px
baseline and ends with "Browse everything in <app>". A library that is down (one of its sections reports
unavailable, Home's `library_down` rule) is a warning, not a shelf: a rectangle with a glyph, Home's own sentence
("... are unavailable right now.") and Try again, an amber `--warn` edge, never yellow, and none of its items, even
those another of its sections still serves from the cache; its chip stays, struck through. As on Home, a library
answered wholly from the cache during an outage reports nothing unavailable, so its cached items still show until
their cache time ends. Not set up says so, with "What to do next"; nothing anywhere is one panel, "Nothing recently
added."; a member with no library reads Home's "No library yet" and a Help link. The page ends with a group linking
the existing Request and Contribute place pages ("Requests", or "Request or contribute" when both are there), only
when the member's catalogue holds them. Without a member, or with sections off, `/library` is the standard 404; its
CSP and Cache-Control are those of the other shell pages.

**Title page (MK-5a; frames 19:1748, 19:1846).** Restyled only: behaviour, permission checks and copy are unchanged.
The art is the item's own `/art` image twice, as in Home's hero (crisp at its natural shape over a blurred, dimmed
copy; without art, the letter frame and no backdrop). From 360px a tall cover (poster, book, comic) rises beside the
glass Home button; a wide still or a square stays below it, so art never sits under the button. The kicker is a
Stone eyebrow and the title the 48px Light display role (it wraps and clamps visually at four lines). Progress stays
in words, with the 3px Cream rule under them (`pc0` to `pc100`, hidden from assistive technology), then the one Cream
action across the column and the "Opens in" note in an opaque panel. An unavailable library is the same warning as
on Library. The frames' "Continue" eyebrow, "Resume in Jellyfin" label and detail panel are not built: they change
the page's copy, which this slice keeps.
**Search, Request, Me, Account and Help (MK-5b, AVR-719).** Tab pages (Search, Me, Account, Help) put their title in
the 28px page role where the Home button would be; place pages (Request, Read) keep the Home button and set the
chooser's title in the same role. Lists are **grouped rows**: an eyebrow heading (12px Medium caps, 0.16em, wrapping)
over one opaque panel (`--surface`, 1px `--line`, panel radius); each row is one link at least 44px tall, with a
decorative inline-SVG icon in a 40px raised circle, the label, an optional Stone line, and a chevron (stays in Avrana)
or the external-link glyph (leaves Avrana, said in words as well). Focus is drawn inside the row. At very large text
on a narrow screen the icon circles are dropped so the words keep the width.
*Search* keeps its plain GET form (`form-action 'self'`), its visible label and its Search button (keyboards, no
script); the field is opaque with a 3:1 Control edge and 17px text. Results are one panel per library, the title link
covering the row. No results offers "Ask for it": the member's own request routes only (the same view-model as
before; each row says "Opens the request website", since every one leaves Avrana), and Contribute only when the
member's catalogue holds it. A library that could not answer is said in words
inside the warning panel (triangle glyph, words, 1px `--warn` edge, rectangle; never the yellow); a library the member
cannot use is never named. *Request* groups the member's own request places under "Ask for something", each row the
catalogue's own wording for that member and "Opens the request website", then "Add to the library" only with
Contribute. *Me* (`/me`, shell only; otherwise the standard 404) shows the member's initial, name and "Signed in as
<username>", then Account, Help and "If something doesn't open", Operations (with the yellow, slanted ADMIN role tag)
only behind the catalogue's own Operations group gate, and Sign out through MK-3's `/signout` hop (it
clears this device, then goes on to the catalogue's sign-out; the same on Account). *Account* keeps every fact, list and note; its section headings are the eyebrow
role (the old letter-spaced caps pushed a 320px page sideways at 200% text), and Manage account and Sign out are rows
under the words that explain them. *Help* lists the member's own topics as rows; topic pages set each platform in an
opaque panel at a readable measure. Not built (no data or no page today): an avatar image, an install row on Me,
request statuses, and the offline, update and session-ended states (MK-3).

**Motion (MK-6, AVR-720; memo section 10).** Moving between shell pages is a cross-document view transition
(`@view-transition { navigation: auto }`, Chrome 126+, Safari 18.2+), CSS only and with no CSP change, declared only
inside `@media (prefers-reduced-motion: no-preference)`: with Reduce Motion nothing moves or fades, and the names are
never set. Same origin only, so the sign-in bounce and the hand-off to a library get none; a browser without support
just loads the page. The page cross-fades and two things travel, each name on one element per page: the tab bar's
lens (`k-lens`, sliding to the new tab; the bar itself is not named, so it stays put and readable) and the art
(`k-art`), which the title page's one frame carries and which, on the page being left, the page script gives to the
frame beside the followed link (the hero's Details, or a search result) only while the old page is captured, so the
art flies into the title page. Nothing flies back to Home (its hero may be another item). Every animation is tier 3,
200 ms (`--motion-3`, `--ease-meaningful`); the 600 ms token is a Proposal behind `HOME_MOTION_PROPOSAL=on` (default
off). Interruptible: a key or the browser's back still navigates during a transition; where the browser exposes the
active transition, the script ends it on the first press, so a touch tap then reaches the page; a mouse click during
the 200 ms may be lost. No
inline script, no storage, no `preventDefault`; everything still works with JavaScript off (the page fade and the lens
still run; only the art flight needs the script). Not built: a flight back to the list, and same-document transitions
(cards hand off to the libraries, so there is no in-page detail to morph into).

## Brand v1.0.0 on Home shell pages (AVR-584)

> **Status: implemented on a fixture-only draft branch. The branded UI is not approved, merged or deployed.** The
> AVRANA brand package v1.0.0 (the package itself approved 2026-10-17) replaces this document's Times New Roman,
> `#000`/`#fff` and typed-wordmark stand-ins on the **Home shell pages only**: Home with sections, Search, Account,
> Help and its topics, title pages, Watch, Listen, Read and Request. The owner's review of the actual branded UI on
> an iPhone (Safari, VoiceOver; AVR-455) is required before merge.

| Owner direction, 2026-10-18 | State |
|---|---|
| Hash-verified base64 packaging of the brand's PNG and WOFF2 files in `avrana_home/app/brand/` | Accepted for v1.0, for that folder only; the repository's binary policy is unchanged |
| `font-src 'self'` on shell pages only | Accepted |
| 56px L3 lockup | Provisionally retained, subject to the real-device review |
| Portal and every page without the shell unchanged | Accepted; AVR-362 owns broader convergence |
| Browse at 720px | Kept; the 1120px comparison is not approved |
| The branded UI as a whole | Not yet reviewed; no merge or deployment until the owner has seen it on a device |

**Where it applies.** Only `templates/home.css`, which is added to a page only when it wears the shell. The portal,
the Kindle and Audible connectors, and every Home page without the shell (sections off, the chooser and
interstitial without a principal, errors and the 404) keep the frontmatter tokens above, byte-identical to the
portal (the parity test). Converging those is AVR-362's job; this section adds no second token file.

**Tokens.** The shell maps the package tokens (`03-Typography-and-Colors/tokens/avrana-tokens.css`) onto its
existing variables, so no rule below them changes:

| Variable | Was | Brand token | On Spire Ink |
|---|---|---|---|
| `--bg` | `#000000` | Spire Ink `#121214` | |
| `--fg` | `#ffffff` | Cream `#EDEAE4` | 15.6:1 |
| `--dim` | `#9a9a9a` | Stone `#AEABA7` | 8.2:1 |
| `--rule-strong` | `#999999` | Ash `#8F8C89` | 5.6:1 |
| `--rule-control` | `#6e6e6e` | Control `#6E6C72` | 3.6:1 (clears 1.4.11) |
| `--rule-quiet` | `#474747` | Graphite `#5E5B57` | 2.8:1, decorative only |
| `--dim-on-fg` | `#333333` | Graphite `#5E5B57` | 5.6:1 on Cream |

Atomic Purple and Purple Deep are Party only and are not used. Media stays monochrome; library artwork keeps its
original colour and natural shape. *(Superseded on shell pages by the Media yellow, AVR-715; see the Concept K
section above.)*

**Type.** *(Superseded on shell pages by Plus Jakarta Sans, AVR-715; see the Concept K section above.)* Geist
(variable, 100 to 900, SIL OFL 1.1) replaced the serif on shell pages, served from `/brand/geist.woff2` with
`font-display: swap` and the package's system fallback stack. Sizes and the existing
hierarchy are unchanged; section labels keep Regular caps tracked 0.22em, which is the package's Media heading.

**Mark.** The masthead shows the package's **L3 Media product lockup** (`/brand/avrana-media-l3.svg`, cream,
trimmed) as an `<img alt="Avrana Media">` inside the home link, 3.5rem tall (56px, twice the package's 28px
minimum so the product name inside it stays legible, and scaling with text size), with no rule beneath it (owner, 2026-10-18; the portal keeps its rule until AVR-362).
The owner approved the size, with the branded UI, after the real-device review on 2026-10-18. The wordmark is never retyped. The favicon is the
package's 16 px micro cut (`/brand/favicon.svg`); the install icons and manifest colours are the package's.

**CSP.** Shell pages, and only they, add `font-src 'self'` beside `manifest-src 'self'`, and since MK-3 (AVR-717,
DECISIONS.md 2026-10-26) `script-src 'self'; worker-src 'self'` for the one first-party script and the service worker. No inline script, no
other origin. Every other response keeps the CSP unchanged, except `/sw.js` (adds `connect-src 'self'`) and `/offline`
(adds `font-src 'self'`).

**Files and provenance.** `avrana_home/app/brand/` (README and `SOURCES.json`: package path, byte count and SHA-256
per file; the server refuses a file that does not match). Refreshed only by `tools/sync_brand_assets.py`.

**Browse width.** Unchanged at 720px (45rem). A wider 960 to 1120px stage is shown only as an unapproved
comparison in the AVR-584 review.

## Media components

> **Status: proposed (AVR-426, 2026-10-14). Nothing here is deployed.** Built against fixtures in
> [the home preview](../../tests/ui/home_preview/README.md), which shows every component below in
> every state at 360, 390 and 1280px (`check.mjs` writes the renders; this repository tracks no
> images). **Owner-approved** and not to be revised here: the compact Home with one Continue row
> and one bounded New row, and browsing on its own New page (AVR-431, AVR-452). **Owner decisions of
> 2026-10-15** (`docs/DECISIONS.md`) settle the artwork shape and colour, the Search entry, the
> 720px browsing column with Kindle's 640px form column, and the script-free account menu. The
> visual result still waits for the owner's review on a phone (AVR-455); the rest of this section
> is the specification that review checks.
> It follows the [Media UX research](https://linear.app/avranakern/document/avrana-media-ux-research-implementation-principles-backlog-gap-4a08eb39e598).

### Two shells
- **Read and Operate** (Help, Account, Welcome, sign-in pages): the 640px single-form column.
- **Browse** (Home, New, Search, a title page): the 720px column (owner decision, 2026-10-15,
  subject to a desktop review). Kindle's form keeps the 640px single-form column.
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
- **Each library keeps its own shape** (owner decision, 2026-10-15)
  (2:3 posters for films and series, 16:9 stills in Continue, square audiobook covers, 2:3 books,
  13:20 comics). Covers keep 1px Quiet Rule edges, square corners and no shadow.
- Covers in one row share a top edge; their widths differ. A cover is decoration (`alt=""`):
  the title is always beside it in words.
- Library artwork keeps its original colour; the page around it stays black and white (owner
  decision, 2026-10-15).

### Places bar
- Watch, Listen, Read, Request and Help, as words in one ruled bar under the wordmark on every
  Browse page. It wraps at large text and never scrolls.
- Only places the member can use. A library the member cannot use has no place at all. A library
  whose service is down keeps its word, struck through and not a link, with ", unavailable" for
  screen readers (decided, preview decision 7).

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
- **Entry point** (owner decision, 2026-10-15): the word **Search**, a visible text link at the top
  left of every Browse page, opposite Account and directly above the bar of places. The bar keeps
  Watch, Listen, Read, Request, Help in that order; Search is not a sixth place in it. Shown once
  search works for members (M3.4); the preview shows it now for review.

### Search result
- Results grouped by library under Subtitle headings, each group a ruled list (List row). A row is
  one link: the cover at a fixed width (60px, 48px on phones) in its own shape, the title, its
  line, and "In Movies and TV", so a row read alone says where the title lives.
- A count before the groups ("8 found."), announced as a status. Case, accents and punctuation do
  not matter to a search ("bronte" finds Brontë).
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
| Search | "Audiobooks are taking longer than usual, so nothing from them is shown yet." and Try again; other results shown, or "Nothing called "…" in the libraries that answered." | "Nothing called "…" in your libraries. Check the spelling, or ask for it with Request." | "Movies and TV were not searched, because they are unavailable right now." (in place of the banner) | "… are unavailable right now, so nothing can be searched. Try again later, or read Help." Field and button disabled | As the New page | As the New page |
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
