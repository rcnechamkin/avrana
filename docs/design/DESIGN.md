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

> **Status: two standards, by page.** Written 2026-10-11 from the code in Git (`services/avrana-portal/portal.py`,
> `services/avrana-kindle-connector/kindle.py`, `services/avrana-audible-connector/connector/app/static/style.css`,
> `services/authentik/blueprints/avrana-landing.yaml`, closing the gaps in
> [the 2026-10-11 audit](../audits/2026-10-11-web-interface-audit.md)); rewritten 2026-10-26 for Concept K (MK-7,
> AVR-721).
> - **Home shell pages** follow **Concept K · Avrana Console** (owner decision O2, 2026-10-25; Phase 1 approved
>   2026-10-26, DECISIONS.md). Where this standard and the shared foundation differ, this document wins (D14).
> - **Every other page** (the portal, the Kindle and Audible connectors, and every Home page without the shell:
>   sections off, the chooser and interstitial without a principal, error pages and the 404) follows **The Title
>   Card**, the next section, unchanged and byte-identical to the portal (the parity test). AVR-362 owns converging them.
>
> Concept K is built on fixture-only draft branches (the integration branch `feat/avr-713-concept-k-integration`):
> not merged to `main`, not deployed, not phone-verified. No UI change that needs visual approval merges before the
> owner has seen it on a device (D17: the AVR-585 iPhone, Safari and VoiceOver review runs on the Concept K build).
> Every change to a running service needs the owner's approval for that change, per `AGENTS.md`.

## Scope

This system governs the surfaces Avrana owns:

| Tier | Surfaces | How the system applies |
|---|---|---|
| Custom, Home shell pages | Home with sections, Library, Search, title pages, Me, Account, Help and its topics, "If something doesn't open", and Watch, Read and Request when they wear the shell | Concept K: tokens, shell, components and copy rules in its own section, after the Title Card |
| Custom (source in this repo) | avrana.net portal, Kindle connector, Audible connector, Home pages without the shell | The Title Card: tokens, components, copy rules |
| Configurable (upstream app, supported theming hook) | Authentik flows and user library (brand CSS), Homepage (`custom.css`, settings) | Tokens only, through the app's own hook, never by DOM surgery |
| Upstream (leave alone) | Jellyfin, Seerr, Audiobookshelf, Komga, Calibre-Web, Shelfarr, Shelfmark, Omnibus, the arr stack, SABnzbd, Mylar3, Beszel, Tracearr, OliveTin, Home Assistant, UniFi, BookStack | Not themed. The system's job there is to hand off cleanly: correct link, correct sign-in instructions, nothing injected |

## The Title Card: the standard for pages without the shell

The Title Card is the standard for every Avrana page that does not wear the Home shell: the avrana.net portal, the
Kindle and Audible connectors, and the Home pages without the shell (sections off, the chooser and interstitial
without a principal, error pages and the 404). Those Home pages stay byte-identical
to the portal (`webtests/test_web_parity.py`), and the front matter above is their token set (checked against the
foundation's Media theme by `tests/test_design_foundation.py` and against the services by the token-drift gate). On
Home shell pages, Concept K (after the Title Card) replaces it.

### Overview

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

### Colors

A monochrome palette with three status colours that only ever carry status.

#### Neutral
- **Ink** (#000000): every page background, and the text colour of inverted (hovered, primary) elements.
- **Paper** (#ffffff): primary text, the wordmark, primary buttons, hovered tiles.
- **Ash** (#9a9a9a): secondary text: descriptions, hints, section labels, step lists. 7.4:1 on Ink.
- **Quiet Rule** (#474747): dividers between list rows and platform sections. Decorative only; 2.3:1, so it must never be the only edge of something clickable or typeable.
- **Control Rule** (#6e6e6e): the resting border of anything interactive: tiles, fields, ghost buttons, badges that sit next to controls. 4.1:1 on Ink, which clears WCAG 1.4.11.
- **Strong Rule** (#999999): the rule under the wordmark and underlines on text links.

#### Status
- **Ok** (#8fe3a6), **Warn** (#e8cf8a), **Err** (#ff8b8b): text and border colour for banners, badges and failed rows. All above 10:1 on Ink.

#### Named Rules
**The No Accent Rule.** There is no brand colour. Emphasis comes from inversion (white block on
black), size and position. Adding a hue for decoration breaks the title-card read.

**The Status Is Words Rule.** A status colour always travels with a word ("Imported", "Failed",
"Audible Plus"). Colour alone never carries meaning.

**The Interactive Edge Rule.** If it can be clicked or typed into, its resting edge is Control
Rule or brighter. Quiet Rule is for separating content, not for drawing controls.

### Typography

**Display and Body Font:** Times New Roman (with Times, Liberation Serif, Tinos, Noto Serif, serif)
**Code Font:** the platform monospace (ui-monospace, SF Mono, Menlo, Consolas, Liberation Mono)

**Character:** a single system serif, used at regular weight throughout, with hierarchy built from
size, tracking and case rather than boldness. Liberation Serif and Tinos are metric-compatible with
Times New Roman, so line breaks stay put on Linux and ChromeOS; Noto Serif covers Android, which
ships no Times.

#### Hierarchy
- **Wordmark** (400, clamp(2.6rem, 9vw, 4.4rem), tracking 0.34em with an equal `text-indent`): the home page only.
- **Wordmark compact** (400, clamp(1.75rem, 6vw, 2.5rem), same tracking): every other page, as the link home.
- **Headline** (400, clamp(1.7rem, 5vw, 2.3rem)): the page's own title, the one `<h1>`.
- **Title** (400, 1.7rem, tracking 0.06em): tile labels.
- **Subtitle** (400, 1.35rem): sub-sections such as a help page's platforms.
- **Body** (400, 1.0625rem / 17px, line height 1.55, measure 65ch): prose, form labels, list items.
- **Small** (400, 0.92rem): hints, descriptions under tiles, footer text.
- **Label** (400, 0.9rem, tracking 0.22em, uppercase, Ash): section headings only.

#### Named Rules
**The Matched Indent Rule.** Tracked, centred capitals carry a `text-indent` equal to their
`letter-spacing`, or they sit visibly left of centre. Change the two together.

**The One Wordmark Rule.** The wordmark exists in exactly two sizes, both defined here. Today it
is drawn four different ways (portal, Kindle, Audible topbar, Authentik); all four converge on these.

**The Copyable Mono Rule.** Monospace is for strings a person types or copies elsewhere: server
addresses, OPDS URLs, Kindle addresses, recovery codes, tokens. Never for labels or decoration.

**The One Caps Level Rule.** Uppercase tracked labels appear at one level per page. A label
directly above another uppercase label (as on the Kindle page today) is not allowed.

### Layout

A single centred column, `max-width: 720px` (640px for single-form pages), with 24px side padding
(20px under 560px). Vertical rhythm comes from the spacing scale (4, 8, 12, 16, 24, 32, 44, 64px);
the main column uses a 44px gap between blocks on desktop and 32px on phones.

Tiles sit in a two-column grid with a 16px gap that collapses to one column under 560px. Prose
and step lists cap at 65ch. Pages open with roughly 12vh of space above the wordmark on the home
page and 6vh on inner pages, so the content, not the brand, owns the first screen on a phone.

**The Footer Is Navigation Rule.** Every page ends with the same footer row: the relevant
"Back" or "All help" link, then "Avrana home". Nothing is reachable only by the browser's back
button.

### Elevation & Depth

Flat. There are no shadows, blurs, gradients or layered surfaces. Depth is replaced by two tools:
the 1px rule (structure) and inversion (state). The only box-shadow in the system is the focus
ring, which is a two-ring outline, not an elevation.

**The Focus Ring Rule.** Every interactive element shows the same ring on `:focus-visible`:
`box-shadow: 0 0 0 2px #000, 0 0 0 4px #fff`, plus `outline: 2px solid transparent` so Windows
High Contrast still draws one. No element sets `outline: none` without this ring.

### Shapes

Square everywhere (`border-radius: 0`). Edges are 1px. The rule under the wordmark is 64px wide
on custom pages and 160px in Authentik, where the wordmark sits in a wider card; both are kept.
Cover art in lists is a square crop with no rounding. Media artwork keeps each library's own shape
(owner decision, 2026-10-15; on shell pages see Concept K, "Media cards and rails").

### Components

#### Wordmark header
- Centred `AVRANA` in the wordmark style, a 64px Strong Rule beneath it.
- On inner pages it is a link to `https://avrana.net` and uses the compact size.
- The Audible connector draws this header in place of its old topbar, and Kindle uses the compact size
  (AVR-362); the token-drift gate compares each size only with services that draw the same one.

#### Tile (navigation)
- Outlined block, Control Rule edge, 22px by 24px padding, label in Title style, one line of
  description in Small/Ash beneath.
- Hover and focus invert: Paper ground, Ink text, description darkens to #333333.
- Used only for navigation (portal grid, choosers, the interstitial's two choices). Never for
  displaying data.

#### Buttons
- **Shape:** square, minimum 44px tall.
- **Primary:** Paper ground, Ink text. One per form.
- **Ghost:** transparent, Control Rule edge, Paper text; inverts on hover and focus.
- **Danger:** ghost with Err text and edge; inverts to an Err ground. Always behind a confirmation.
- **Hover / Focus:** 160ms colour transition only; the focus ring is always added on
  `:focus-visible`, independent of the hover inversion.

#### Fields
- Transparent ground, Control Rule edge, 12px by 14px padding, 48px tall, body type.
- Focus: edge turns Paper, plus the focus ring.
- A visible `<label>` above every field; hints sit under the field in Small/Ash and are linked
  with `aria-describedby`. Errors use Err text in the banner and `aria-invalid="true"` on the field.
- Pages declare `color-scheme: dark` so native checkboxes, selects and scrollbars render dark.

#### Banner
- 1px edge in the status colour, text in the same colour, 12px by 16px padding.
- Success and notices use `role="status"`; errors use `role="alert"`.

#### Badge and chip
- Uppercase small text with 0.06em tracking, 1px edge, 2px by 10px padding. Status colour only
  when the badge names a status.

#### List row
- Rows separated by Quiet Rule, first row also ruled on top. Cover (60px, 48px on phones), meta,
  then the row's control on the right. The control's hit area is the whole row where possible
  (wrap the row in the `<label>`).

#### Text link
- Paper text with a 1px Strong Rule underline offset 2px; underline turns Paper on hover; focus
  ring on focus. In footers, links get 12px of vertical padding so the target reaches 44px.

#### Skip link
- Canonical definition: `docs/design/components/skip-link.html` (markup) and `docs/design/components/skip-link.css` (styles). Portal (`portal.SHELL`, `portal.STYLE`) and Home (`templates/base.html`, `templates/style.css`) carry byte-identical copies; `tests/test_skip_link.py` fails on drift.
- Markup contract: the first element in `<body>` is `<a class="skip-link" href="#main">Skip to main content</a>`; the target is the page's single `<main id="main" tabindex="-1">`.
- Hidden with the clip pattern (not `display:none`), visible on `:focus-visible` as an inverted Paper-on-Ink block, fixed at top left so a sticky header cannot cover it, with the shared two-ring focus ring from `a:focus-visible`. Existing tokens only; no transition, so nothing to gate on reduced motion. Works without JavaScript.

#### Help page (signature component)
- Headline names the topic ("Movies and TV"). Under it, a row of platform links that jump to each
  section, so a member with a Roku does not scroll past six other devices.
- Each platform is a section with a Subtitle heading, the recommended app first, store link as an
  inline text link (not full width), then numbered steps. Server addresses are in Copyable Mono.

### Do's and Don'ts

#### Do:
- **Do** keep pages black with white serif type and one grey (#9a9a9a) for secondary text.
- **Do** draw every interactive edge in Control Rule (#6e6e6e) or brighter.
- **Do** show the two-ring focus indicator on every interactive element.
- **Do** use the compact wordmark as a link home on every inner page, and end every page with the shared footer row.
- **Do** keep copy in plain second person or neutral imperatives, with no first-person "we" and no em or en dashes.
- **Do** keep the 404-not-403 doctrine: a page for something the viewer cannot use does not exist for them.

#### Don't:
- **Don't** add a brand accent colour, gradients, shadows, glass, rounded corners or decorative icons.
- **Don't** use `outline: none` without the focus ring.
- **Don't** set monospace as a general UI face (Authentik's brand CSS currently does); keep it for copyable strings.
- **Don't** theme upstream applications by injecting CSS through the proxy or patching their files. Use only a hook the application supports.
- **Don't** auto-refresh whole pages; update the changing part, or let the member refresh.
- **Don't** name a service in copy that the viewer might not be allowed to reach.

## Concept K · Avrana Console: the Home shell-page standard (AVR-713)

> Reference: the Figma file "Avrana Media — Console" (`OggTUO1p24pNYFI6iVlLWL`), the Phase 1 decision memo (D1 to
> D17) and the Concept K style kit. What was built from which frame, and what was not, is in
> [CONCEPT-K-FOLLOW-UPS.md](CONCEPT-K-FOLLOW-UPS.md) with the follow-up issues. Slices: MK-1 foundations (AVR-715),
> MK-2 shell (AVR-716), MK-3 script, worker and sign-out (AVR-717), MK-4 Home (AVR-718), MK-5a and MK-5b pages
> (AVR-719), MK-6 motion (AVR-720), MK-7 these docs (AVR-721).

### Where it applies

Concept K lives in one file, `templates/home.css`, which is inlined only into pages that wear the shell
(`respond(..., shell=...)` in `main.py`). The shell pages are listed in the Scope table above and in HOME-APP.md
I-8. On those pages, Concept K replaces the Title Card's serif, `#000`/`#fff`, square corners, the No Accent Rule
and the "no glass, no shadows, no gradients, no decorative icons" rules. Other pages do not change: `style.css` stays
equal to the portal's `STYLE`, and the Title Card governs every page without the shell. The `/offline` page wears
the shell's styles and lockup, but no tab bar, places or member data.

### Tokens

Colours keep the approved Brand v1.0.0 values under Concept K names. The mapping to the brand package and to the
foundation's role names is in [FOUNDATION-MAPPING.md](FOUNDATION-MAPPING.md).

| Token | Value | Use |
|---|---|---|
| `--ink` | `#121214` | Page ground (Spire Ink) |
| `--depth` | `#0d0d0f` | Ground behind ink panels |
| `--surface` | `#161618` | Opaque panels, rows, the search field, banners |
| `--raised` | `#1E1E21` | Chips, icon circles, the Me initial, glass fallback |
| `--cream` | `#EDEAE4` | Primary text (15.6:1), the one primary action, progress rules |
| `--stone` | `#AEABA7` | Secondary text and eyebrows (8.2:1) |
| `--ash` | `#8F8C89` | Strong rules, quiet labels (5.6:1) |
| `--graphite` | `#5E5B57` | Decorative only (2.8:1); never text on ink |
| `--control` | `#6E6C72` | Resting edge of fields and controls (3.6:1, clears WCAG 1.4.11) |
| `--line`, `--line-strong` | white at 9 % and 18 % | Panel and chip edges, and 1px dividers between grouped rows and sections |
| `--accent` | `#EADA6E` | Media yellow, Butter-High (13.1:1 on ink) |
| `--accent-deep` | `#776A00` | Yellow Deep: 14px+ semibold text on cream only (4.55:1) |
| `--accent-selected` | yellow at 22 % | Chosen chip tint |
| `--lens`, `--lens-solid` | white at 15 %; `#323236` | The tab lens (neutral glass); its opaque fallback |
| `--ready`, `--warn`, `--danger` | `#34D399`, `#F59E0B`, `#EF4444` | Status, always with words (D3: the console warn; Media's `#e8cf8a` reads as the yellow) |
| `--focus` | `var(--accent)` | Every focus ring |

The Title Card names (`--bg`, `--fg`, `--dim`, `--rule-*`, `--dim-on-fg`) are aliases of these, so older rules keep
working. More contrast raises Stone, Ash, the lines and Control.

**The Yellow Rule.** The Media yellow carries Atomic Purple's role in Party (O2), and only that: the
chosen filter chip (tint, rim and a check glyph), the "yours" eyebrow and its 3px signal bar on Continue, the ADMIN
role tag, and focus rings. Never on lists that are not the member's own state (Recently added, results), never on a
progress bar (Cream), never inside a warning, never a large fill. Selection is told by geometry as well as colour
(lens, check, bar, slanted tag); purple never appears in Media. The tab lens is neutral glass, not yellow (owner,
2026-10-26), as in every system tab bar.

**The Warning Rule.** A warning is a rectangle with a triangle glyph, words and a 1px `--warn` edge, on an opaque
panel. Any large amber area is a warning, and a warning never contains the yellow. Status is always in words.

### Type

Plus Jakarta Sans (variable 200 to 800, SIL OFL 1.1; `/brand/plus-jakarta-sans-latin.woff2` and `-latin-ext.woff2`,
the Fontsource 5.3.0 files Party ships, `font-display: swap`, system fallback), never Geist. Big type is Light;
small type Medium or SemiBold.

| Role | Size | Use |
|---|---|---|
| Display | 48px Light (44px fallback) | The hero and title-page title; wraps, clamps visually at four lines, never fitted by shrinking |
| Page | 28px | A tab page's title, top left |
| Shelf | 20px | Shelf and group headings on Home and Library |
| Button | 17px Medium | The primary action |
| Body | 15px | Prose, card titles, row labels |
| Secondary | 14px | Meta lines, notes |
| Eyebrow | 12px Medium, caps, tracked 0.16em, Stone (yellow only for "yours") | Kickers and grouped-row headings; wraps |

At 200 % text the display title grows with the viewport (`calc(0.5rem + 12.5vw)`, about 65px at 390px) so ordinary
words stay whole; a single word wider than the column may still break rather than push the page sideways.

### Shape, glass and motion

- **Radii:** preview 20 (art, hero), panel 16, button 14, control 12, chip 8; the tab bar and pills are fully
  round.
- **The Three Glass Rule.** One `.glass` class (liquid, not frosted: a thin tint, 16px blur with 1.9 saturation, a two-corner masked
  `::before` rim, inner caustics and an `::after` sheen, CSS only, never
  `border-image`; the element clips itself with its radius, `overflow: hidden` and `isolation`) is worn by exactly
  three controls: the tab bar, the top-left Home button, and the top-right utility on Library. Everything else is
  opaque: cards, chips, panels, banners, the search field, the update prompt. Fallbacks: no `backdrop-filter`,
  reduced transparency and more contrast get the solid `--raised` ground; forced colours get a system edge. The blur
  is never animated.
- **Motion tiers:** 150 ms (a press answers), 300 ms (an in-place answer), 200 ms (a scene change; Party's shipped
  cap). Anything longer, such as 600 ms, is a Proposal behind a default-off flag. The lens slides on a spring when
  the page script moves it. Reduce Motion stops every animation and transition. The cross-document transitions are
  MK-6's ("Motion (MK-6)" at the end of this section).

### Shell

- **Tab bar** (`nav.tabbar`, aria-label "Sections", D1): Home · Library · Search · Me for a member with a library;
  Home and Me for a member without one (a library the member cannot use is never named). It ends every shell page,
  after the footer, so it is last in reading and focus order, as on screen. Glass, fixed above the bottom safe area,
  at most 28rem wide, edges in px so large text gets the width. Icons are inline SVG in `currentColor`; Me shows the
  member's initial on a raised circle, and its accessible name says who is signed in.
- **Lens.** The section's tab carries the neutral glass lens, placed by `data-at` (the tab's index), which the server
  prints, so it is right without JavaScript. `aria-current="page"` marks the tab that is this page, `"true"` the
  section a deeper page belongs to (places and titles under Home; Account, Help and its topics under Me). The page
  script only moves `data-at` on a plain click, and puts it back on `pagehide`. At very large text (viewport under
  18em: 200 % at 390px, 150 % at 320px) the bar runs edge to edge, each tab takes the width its word needs, and the
  current tab carries its own capsule, which does not slide.
- **Home's heading** (D5) is the L3 Media lockup (`/brand/avrana-media-l3.svg`, `alt="Avrana Media"`, 56px tall and
  scaling with text; never retyped or recoloured), top left. In forced colours the name shows as system text.
- **The places bar stays on Home** (D16, AVR-452), under the lockup and above the hero, as opaque chips. It is
  catalogue-driven: every Home tile the member holds is a chip, in the catalogue's order (Watch, Listen, Read,
  Request, Contribute, Operations, Help), so Contribute and Operations appear only for members who have them. With
  the five usual places, one row at 390px with 44px targets; with more, at 320px or at large text, whole chips wrap.
  A library the member cannot use has no chip; a library that is down keeps its chip, struck through, linking to
  `/help/trouble#unavailable` ("Watch, unavailable: what to do"). Search is a tab, never a place.
- **Other shell pages** keep "Avrana Media" as a visually hidden `h1`. Tab pages (Library, Search, Me, Account, Help)
  show their own title in the page role, top left. Pages that are not tabs (a place, a help topic, a title,
  "If something doesn't open") add the **glass Home button**: a 44px circle holding the brand's Spire-A micro cut at
  the 24px it is drawn for (`/brand/spire-a-24.svg`, SHA-pinned, never redrawn), the word "Home" in forced colours.
- **Top-right utility** (Library only): one 44px Search link, a magnifier named "Search", shown only to a member who
  can search.
- **Safe areas and scroll end.** `viewport-fit=cover` on shell pages only; gutters are
  `max(1.25rem, env(safe-area-inset-*))`. The page scrolls clear of the bar by 1rem, and `scroll-padding-bottom`
  keeps a focused control above it (WCAG 2.4.11). `apple-mobile-web-app-status-bar-style` stays `black` (D7).
- **Column.** Browse pages keep the 720px (45rem) column on wide screens (owner decision, 2026-10-15); the wider
  stage is not approved.
- **The one script** (MK-3, O1) adds only the lens slide, the service worker and its update prompt, and a reload
  when a page returns from the back/forward cache. Every page works without it. What it and the worker may do, and
  the CSP per route class, are HOME-APP.md's "Shell pages, the script and the worker".

### Home

- **Hero** (MK-4, D6). Under the places bar, the member's own next thing: the first Continue item, or with nothing
  in progress the first Recently added item. Built only from this member's sections for this request; a library
  that is down never supplies it, and a member with no library, resting libraries or nothing set up gets no hero.
  The eyebrow is part of its `h2` ("Continue: <title>"), yellow with the 3px signal bar only for Continue, Stone for
  Recently added. The title is the display role.
- **Hero art.** The item's own `/art` image twice: crisp at its natural shape (contained, never cropped) over a
  blurred, dimmed copy that fades out before the text, blur in CSS only. With no art, the letter frame and no
  backdrop; below 360px no poster; no backdrop in more contrast or forced colours. No backdrop image type is used
  (that is follow-up F-1).
- **One hand-off.** One Cream action names the app that opens: "Resume in Jellyfin" only for a saved position,
  otherwise "Open in Jellyfin", "Listen in Audiobookshelf", "Read in Komga", "Open in Calibre-Web". It never claims
  playback. "Details" opens the title page only where one exists. Cards and the title page name the library in
  member language instead (see "Copy" for every surface that names the app; owner question Q1).
- **Shelves.** Continue (Jellyfin and Audiobookshelf merged, at most four, progress in words) and Recently added
  (`id="h-new"`; "New this week" was renamed because the lists are not date-bounded), with per-library tabs that
  are plain links. A tab exists only for a library of the member's own that is answering; a member with one such
  library gets no "All" tab. Shelf headings take the shelf role.

### Media cards and rails

- **One link per card, one action.** Order: title (two lines at most), the creator, series or episode line (Stone,
  one line, ellipsis), progress in words, then on Continue cards the verb ("Resume" or "Open") as small underlined
  text. Recently added cards carry no verb: the whole card opens the item. Clamping is visual only; the full title
  stays in the link text and so in its accessible name. When the view-model gives an `action_label`, it replaces
  the verb for assistive technology only. A card never takes an `aria-label`, a second control, a menu or an icon.
- **Artwork keeps each library's shape** (owner decision, 2026-10-15): 2:3 posters and books, 13:20 comics, square
  audiobooks, 16:9 stills. Art is 180px high in rails (`--art-h`), each shape at its natural width, contained and
  never cropped, with the preview radius. On phones a still is held to the card width and stands shorter,
  bottom-aligned; from 45rem it may be up to 12.5rem wide (`--wide-max`), wider than the 9.5rem cards.
  Covers are decoration (`alt=""`); the title is always beside them in words. Artwork keeps its original colour.
- **Progress** is words plus a 3px Cream rule along the foot of the art, hidden from assistive technology, its
  length a 5 % step class (`pc0` to `pc100`) because the CSP forbids inline style. Never yellow.
- **Rails scroll sideways** inside themselves; the page never does. On phones every card is one width (11.25rem,
  `--card-min`; 9.5rem from 45rem), so the next card peeks in; the rail snaps to card starts (mandatory) and a
  trailing spacer lets the last card snap too. From 45rem the cards fit and snapping is proximity only.
- **The Rail Focus Rule.** Browsers scroll a focused element into view only when it is wholly outside the scroller's
  optimal viewing region (the scroller less its `scroll-padding`), so a partly visible card would stay clipped. The
  rail's right `scroll-padding` leaves a region one card (plus focus ring) wide: a peeking card counts as outside,
  Tab and Shift+Tab bring it fully into view, and the rail's padding keeps the ring unclipped. This relies on cards
  resting card-aligned, which is why phone rails snap mandatorily and carry the trailing spacer. No script.
  `tests/ui/check_home_export.mjs` checks it in Chromium with real key presses at 360, 390 and 390 at 200 % text;
  Safari and VoiceOver are part of the device review (AVR-585).
- **Residual:** from 45rem a still may be wider than the other cards; if the four cards ever overflow the column there
  (large text on a desktop), a still that straddles the column edge can stay partly clipped when focused.
- **Known, not fixed:** when a cover's bytes arrive but cannot be decoded, the browser draws its broken-image icon
  over the letter behind the frame. Hiding it needs an `onerror` handler (the strict CSP forbids inline handlers) or
  a server-side image decode on every artwork request; the artwork route already refuses a declared type that is
  not JPEG, PNG or WebP or whose magic number does not match (`adapters/_base.py`). The dev mocks serve real,
  decodable synthetic art in each shape (`dev/synthetic_art.py`).

### Library

`/library` (MK-5a) is a tab page: "Library" in the page role, the Search utility top right. Opaque filter chips are
plain links: All, then one per library this member's sections hold, in Home's order and member language.
`?lib=<library>` picks one, checked against the member's own libraries (bounded, never echoed; anything else is
All); the chosen chip has the yellow tint, rim, check glyph and `aria-current="true"`. Chips wrap as whole chips.
All shows one shelf per library (the newest items Home already has, at most four) on the rail, with a quiet
"Open <app>" link to the member's own place route only where the catalogue opens it; one chosen library shows a grid
on the 180px baseline and "Browse everything in <app>". The page ends with a group linking Request and Contribute
("Requests", or "Request or contribute" when both are there), only when the member has them. The filter and sort
control in the frames is not built (no honest order without new data), and Library shows recently added items only
(follow-up F-8).

### Title page

`/title/<service>/<id>` (MK-5a) is restyled only: behaviour, permission checks and copy are those of AVR-384. The
art is the item's own `/art` image twice, as in the hero; from 360px a tall cover rises beside the Home button, a
wide still or a square stays below it, so art never sits under the button. A Stone kicker, the display title,
progress in words with the Cream rule, then one Cream action across the column (Resume, Open, or Watch, Listen,
Read by the Continue rule, never claiming playback), then "Opens in" in an opaque panel. An unavailable library is
the warning; anything the member may not see is the standard 404. When the library supplies a synopsis (R2-C, R3-A AVR-748), it sits
last under an "About" eyebrow (`h3`, Stone), after a 1px `--line` divider, as plain autoescaped text in the Body role
(Stone, 1.55 line height, 62ch measure, `dir="auto"` for right-to-left text). It wraps, is never clamped and adds no
motion; with no synopsis there is no About block.

### Search

`/search` (MK-5b) is a tab page. It keeps its plain GET form (`form-action 'self'`), the visible label "Title or
author", the Search button (keyboards, no script) and the hint ("Searches the libraries on your account. At least 2
characters."), linked by `aria-describedby`; the field is opaque with a 3:1 Control edge and 17px text. The query is
cleaned (`contract.clean_query`: at most 256 characters in, 100 out), escaped and shown back. No
suggestions while typing (a second way to leak a title, and it needs script). Only the member's own libraries are
searched; "No results" reads the same whether a title is in a library the member cannot use or nowhere. Matching is
each library's own search: Home sends the cleaned term, so how case and accents are handled is the library's
(unverified against the real services). With results, a count line ("8 found.") comes first, announced as a status;
results are one opaque panel per library under an eyebrow heading, the title link covering the row, with a chevron (title page)
or the external-link glyph (opens the library, said in words too). No results offers "Ask for it": the member's own
request routes only, each saying "Opens the request website", and Contribute only when the member has it (owner
questions Q4, Q5). A library that could not answer is the warning, inside the page; when no library answers, the page
says "Not searched" and never "No results" or a request offer.

### Request and Contribute

Request (`/request`) and Read (`/read`) are place pages with the Home button; the chooser's title takes the page
role. "Ask for something" lists the member's own request places as grouped rows, each in the catalogue's wording
for that member, with "Opens the request website" and the external-link glyph; "Add to the library" follows only
with Contribute. Nothing is submitted from Home, and no request status is shown (follow-up F-5).

### Grouped rows

Lists on Search, Request, Me, Account and Help are grouped rows: an eyebrow heading over one opaque panel
(`--surface`, 1px `--line`, panel radius). Each row is one link at least 44px tall: a decorative inline-SVG icon in a
40px raised circle, the label, an optional Stone line, and a chevron (stays in Avrana) or the external-link glyph
(leaves Avrana, also said in words). Focus is drawn inside the row. At very large text on a narrow screen the icon
circles drop so the words keep the width.

### Me

`/me` (MK-5b) is the Me tab's hub, shell only (otherwise the standard 404). It shows the member's initial on a
raised circle (Authentik gives Home no avatar), name and "Signed in as <username>"; beside the name, the yellow,
slanted ADMIN tag only for a member behind the catalogue's own Operations gate (owner question Q3). Then Account,
Help and "If something doesn't open", Operations for those members, and Sign out. Sign out goes through `/signout` (D10): it clears this site's cache and
storage on this device, then goes on to the outpost sign-out; Me's row makes no claim about what it ends (U-19). Not
built: an avatar image, and the install row (follow-ups F-7, F-10).

### Account

`/account` keeps every fact, list and note from AVR-383/478 ("Your access" in Home's language, Libraries and
Requests, "Also"); its section headings are the eyebrow role, and Manage account and Sign out are rows under the
words that explain them. The note says Sign out "signs you out of Avrana Media on this device and clears what it
saved here", and that apps and libraries signed in separately stay signed in; it never claims the Authentik session
ended. With sections off, Account is the portal's page, byte for byte.

### Help

`/help` lists the member's own topics as rows plus "If something doesn't open" (`/help/trouble`, shell only, naming
only the member's own libraries). Topic pages keep the Help page component (a headline naming the topic, platform
jump links, the recommended app first, numbered steps, server addresses in Copyable Mono), each platform in an
opaque panel at a readable measure.

### States and the words for them

Loading is never a spinner: the page renders once, and a part whose service missed its two seconds says so and
offers "Try again", a plain link to the same page. An error and a timeout read the same to a member. No raw error,
host, service or software name ever reaches the page, and nothing names a library the member cannot use.

| State | Where | What the member sees |
|---|---|---|
| One library down | Home | One notice, "Movies and TV are unavailable right now.", plus "Anything shown from them may be out of date." when cached items still show; the place struck through; Try again. That library never supplies the hero. (The notice is still the older ruled banner; follow-up F-13.) |
| One library down | Library, Search, title page | The warning: glyph, the same sentence, Try again, amber edge; on Library its chip struck through and none of its items |
| Every library down | Home | "Your libraries are resting", one combined line, "This usually passes within a minute. Your account and Help are still here.", Try again |
| Not set up | Home, Library | "Not set up yet" (or the library's line), "There is nothing to change on your side…", "What to do next" (`/help/trouble#not-set-up`) |
| No library | Home, Library | "No library yet": "No library is shared with this account yet. Ask the person who invited you, or read Help." Tabs Home and Me only |
| Nothing to show | Home, Library | "Nothing recently added." or "Nothing recently added in Comics."; an empty Continue keeps its heading and says "Nothing in progress. Whatever you start in a library appears here, ready to pick up where you stopped." Only a member with no Continue section at all (Comics or Books only) gets no Continue shelf |
| No connection | `/offline`, shown by the worker only when the request itself fails | "This phone has no connection. Avrana Media needs one to show your libraries." and Try again. The same bytes for everyone |
| New version waiting | Any shell page with the script | "A new version of Avrana Media is ready." and a Reload button, in an opaque panel above the tab bar (`role="status"`) |
| Signed out | `/signout` | Clears this site's cache and storage, then the outpost sign-out. No "session ended" screen exists (D13, follow-up F-6) |

### Accessibility rules

- Every page works with JavaScript off and keeps the skip link first in `<body>`, byte-identical, above the glass
  (it stays `z-index` 1000); one `<main id="main" tabindex="-1">` per page.
- Targets are at least 44px. Text reflows at 320px and at 200 % text with no sideways page scroll; words are never
  shrunk to force one row and normal words never break mid-word.
- Focus: the yellow ring with an offset on every control; inside a glass host the ring is drawn inside
  (`outline-offset: -3px`), because the host clips what lies outside. Nothing focused hides under the tab bar.
- Reduce Motion stops all animation and transition; reduced transparency and more contrast make glass solid; forced
  colours get system edges, the lockup as text and "Home" as a word.
- Status is always in words; colour, the lens or a glyph never carries meaning alone.
- Decorative icons and glyphs are `aria-hidden`; a link's accessible name starts with its visible words (WCAG 2.5.3).
- No inline `style=` for data and no inline script: the CSP forbids both.

### Copy

Functional labels only: no narration, counts as numbers, reasons in one line beside the blocked thing, ellipsis
only for in-progress states. Second person or neutral, no "we", no em or en dashes. Libraries are named in member
language ("Movies and TV", never "Watch" or "Movies & TV"). The upstream app is named only where the member is sent
into it: the Home hero's hand-off, Library's "Open <app>" and "Browse everything in <app>", and the Watch
interstitial's app advice. Cards, the title page and all other copy use member language (owner question Q1).
Nothing ever claims playback ("Opening Jellyfin" must never imply it started), and no copy may say "verified on
iPhone". The installed app is "Avrana Media" (D8).

### Do's and Don'ts on shell pages

- **Do** build from `home.css` tokens only; one token file (the foundation is mirrored, not edited: D4, D14).
- **Do** keep glass on the three shell controls and everything else opaque.
- **Do** keep the yellow for the member's own state, selection and focus; the tab lens stays neutral.
- **Do** keep the 404-not-403 doctrine: a page, chip, heading, link or empty state for a library the member cannot
  use does not exist for them.
- **Don't** use purple, Geist, `#e8cf8a` or a large yellow fill, or put the yellow in a warning or a progress bar.
- **Don't** add a fifth tab, a floating button or a second bar; Search is never a sixth place.
- **Don't** build a Proposal frame's element before its data exists.
- **Don't** auto-refresh whole pages; update the changing part, or let the member refresh.

### Motion (MK-6)

AVR-720; memo section 10. Moving between shell pages is a cross-document view transition
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

## History

Superseded sections, kept short. The full earlier text is in Git (this file at `df49211`, the integration branch
before MK-7).

### Brand v1.0.0 on Home shell pages (AVR-584)

The AVRANA brand package v1.0.0 (approved 2026-10-17) replaced the serif, `#000`/`#fff` and typed wordmark on Home
shell pages in October 2026 (owner direction 2026-10-18, DECISIONS.md). Still in force under Concept K:

- Brand binaries (install PNGs, the interface font) are base64 copies of the exact source bytes in
  `avrana_home/app/brand/` only, SHA-256 pinned in `brand/SOURCES.json` and refreshed only by
  `tools/sync_brand_assets.py`; the server refuses a file that does not match.
- `font-src 'self'` on shell pages only (since MK-3 also `script-src 'self'; worker-src 'self'`; HOME-APP.md I-8).
- The 56px L3 lockup on Home, with no rule beneath it; the favicon is the package's 16px micro cut; the install icons
  and manifest colours are the package's.
- The 720px browsing column.

Superseded: Geist (by Plus Jakarta Sans, AVR-715) and "Media stays monochrome" (by the Media yellow, O2). The
token table it carried, old variable to brand token, is now in FOUNDATION-MAPPING.md.

### Media components (AVR-426) and the shell masthead

The pre-Concept K component specification for Home (2026-10-14, owner decisions of 2026-10-15) described two
shells (the 640px Read and Operate column and the 720px Browse column), a masthead with Search and a native account
disclosure in a top row, the places bar on every Browse page, link tabs, a "New this week" row and New page, a Wall,
ruled search results and a ruled title page. On shell pages Concept K replaces it: Search and Me are tabs and the
account disclosure is retired (MK-2), the places bar is on Home only (D16), "New this week" is "Recently added"
(MK-4), and Library, Search, the title page, Me, Account and Help are restyled (MK-5). Rules that survive (the card's
one-link contract, natural artwork shapes, the rail focus contract, the search behaviour and the state wording) are
in the Concept K section above. The preview at `tests/ui/home_preview/` still renders the older components.
