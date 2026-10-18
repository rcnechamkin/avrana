# Avrana Design Foundation

Status: **PROPOSED (2026-10-11, AVR-424). Shared UI engineering standards for Avrana Party and Avrana Media. Nothing here is implemented by this document, and it changes no shipped styling.**

This file and `tokens.json` are mirrored byte for byte in two repositories: `rcnechamkin/avrana-party`
(the source copy) and `rcnechamkin/avrana` (Media), both under `docs/design/foundation/`. Change the
Party copy first, copy it across, and update `MIRROR.sha256` in both. Product-specific detail stays
out of this file: Party's lives in `PARTY-MAPPING.md` beside it and `docs/UI-DESIGN-SYSTEM.md`;
Media's lives in `docs/design/FOUNDATION-MAPPING.md` and `docs/design/DESIGN.md`.

## 1. What this is

One way of engineering interfaces, two visual identities.

- **Shared:** the names of things (token roles, component states), how interactive parts behave,
  what every screen owes a keyboard, a thumb and a screen reader, and how that is tested.
- **Not shared:** colour values, typefaces, shape, layout, copy voice and implementation code.
  Party is a console; Media is a title card. Neither is restyled to resemble the other.
- **Not a library.** There is no package to install and no cross-repository runtime dependency.
  Static browser pages (Party), server-rendered HTML (Media) and Flutter widgets (the planned
  owner app) each implement the same contracts in their own code.

Material Design 3 is the reference for sound practice: semantic colour roles, a state model, window
size classes, target sizes, motion tokens. It is not a component library to adopt and not a look to
copy. Where Material and an approved product direction disagree, the product direction wins.

If this document and an accepted ADR, the Party UX/UI product brief or the Media design
specification disagree, those win and this document is corrected.

## 2. Tokens

Three tiers, the Material 3 model:

1. **Reference values**: raw colours, sizes, durations. Private to a theme.
2. **Semantic roles**: what a value is for (`surface`, `on_surface_muted`, `outline_control`).
   Components use roles only, never raw values.
3. **Component tokens**: only where a component needs a value no role gives it.

`tokens.json` holds the shared scales and both themes. Rules:

- No page, template or widget hard-codes a colour. A value that must be repeated outside the
  stylesheet (a `theme-color` meta tag, a web manifest) is listed in the product mapping so a
  token change finds it.
- A role may be `null` in a theme. Media has no accent and no raised surface, by design.
- Adding a role needs a use in two places or a state that no existing role can carry.

### Semantic colour roles

| Role | For | Party | Media |
|---|---|---|---|
| `surface` | the page ground | `#0d0d0f` | `#000000` |
| `surface_low` | a quiet step up: notices, tiles | `#161618` | none |
| `surface_raised` | a clear step up: fields, selected segments | `#1e1e21` | none |
| `on_surface` | primary text | `#edeae4` (16.2:1) | `#ffffff` (21:1) |
| `on_surface_muted` | secondary text | `#aeaba7` (8.5:1) | `#9a9a9a` (7.5:1) |
| `on_surface_faint` | quiet labels, counts | `#8f8c89` (5.8:1) | none |
| `outline_quiet` | dividers only | white at 9% | `#474747` (2.3:1) |
| `outline_control` | the edge of anything pressable | `#6e6c72` (3.7:1) | `#6e6e6e` (4.1:1) |
| `outline_strong` | emphasised rules, underlines | white at 18% | `#999999` |
| `action` / `on_action` | the one main action of a region | `#edeae4` / `#121214` | `#ffffff` / `#000000` |
| `accent` | selection, focus, links | `#b9a9e8` (9.2:1) | none |
| `selected` | a chosen item | accent at 16% | inversion |
| `focus_ring` | keyboard focus | 2px `#b9a9e8`, 2px offset | 2px black then 2px white |
| `status_ok` / `warn` / `error` | state, beside a word | `#70c696` / `#e6b862` / `#f08a7e` | `#8fe3a6` / `#e8cf8a` / `#ff8b8b` |
| `status_info` | neutral information | `#81afdf` | none |

Ratios are against the theme's `surface`, computed with the WCAG 2 formula on 2026-10-11. Every
Party text role also holds 4.5:1 on `surface_raised` and on the violet material (the lowest is
`on_surface_faint` at 4.9:1); `outline_control` holds 3:1 on all of them.

Accessibility adaptations of the approved palettes are part of the foundation, not exceptions to it:
Media's `#474747` stays the divider and `#6e6e6e` is the control edge; Party's Atomic Purple never
fills a region and status colours never stand alone.

## 3. Typography

Shared role names, product values in `tokens.json`:

| Role | Use |
|---|---|
| brand | the product's name, and nothing else |
| headline | the one top heading of a page or scene |
| title | a place's title, a tile's label |
| section | a heading inside a page |
| body | what people read |
| supporting | a second line: a hint, a value, a count |
| caption | the floor: bar labels, word tags |
| code | strings a person copies or types elsewhere |

Rules:

- Sizes in `rem` on the web and scaled logical pixels in Flutter, so the user's text size applies.
  Nothing clips at 200%; a layout reflows or scrolls instead.
- No text below 11 CSS px at default size. Fields are 16 px or larger so iOS does not zoom on focus.
- Hierarchy is built from few steps. A new size or weight is a foundation change, not a one-off
  utility in markup.
- One top heading per page, no skipped levels.

## 4. Space, size and windows

- **Space scale:** 4, 8, 12, 16, 24, 32, 48, 64. Gaps and padding come from it.
- **Windows:** the Material 3 class names. *Compact* under 600 wide (phones; the primary case for
  both products), *medium* 600 to 839, *expanded* 840 and up. Design starts at 360 wide. A product
  may break inside a class where its content needs it and records that in its mapping.
- **Reading measure:** prose caps near 65 characters.
- **Safe areas:** bars and docks pad by the device's insets.

## 5. Interactive states

Every interactive component defines all of these, or says why one does not apply:

| State | Contract |
|---|---|
| enabled | its edge or fill meets 3:1; it has an accessible name |
| hover | an enhancement only; nothing is reachable by hover alone |
| focus-visible | the theme's focus ring, always, on every interactive element; never removed without a replacement |
| pressed | immediate feedback, 100 ms or less |
| selected | two cues (for example fill and a tick) plus `aria-pressed`, `aria-selected` or `aria-current` |
| disabled | not focusable, and visibly different by more than opacity where the label must stay readable |
| busy | keeps its place, size and focus; says it is busy (`aria-disabled`, `aria-busy`); cannot fire twice |
| error | says what is wrong in words, next to the thing; `aria-invalid` on a field |

Material's state layer (a tint over the component) is one way to draw these; Party uses tint and
edge, Media uses inversion. The contract is the same.

## 6. Components and their contracts

**Buttons.** One primary action per region. Secondary actions are outlined or plain. Destructive
actions are never filled at rest and always confirm. Icon-only buttons carry a name.

**Fields.** A visible label above; a hint below, linked with `aria-describedby`; errors in words.

**Navigation.**

| Situation | Pattern |
|---|---|
| 3 to 5 top-level places on a phone | a bottom navigation bar; the current place has weight, a mark and `aria-current` |
| the same places on a medium or expanded window | a navigation rail, or the same column centred |
| a page inside a place | a back control in the top bar that names where it returns |
| a linear task (pairing, a form flow) | steps with a visible position; Back never loses entered data |
| a small set of member pages | a link home on every page and a consistent footer row |

Changing place moves focus to the new title and updates the document or route title. The system
Back gesture always works.

**Surfaces over the page.**

| Surface | Use | Contract |
|---|---|---|
| dialog | a decision that needs an answer | modal; focus goes in and is held; Escape or Back closes it when cancelling is safe; focus returns to the opener |
| bottom sheet | choices or detail about the thing on screen | as a dialog; one heading; its main action at the bottom |
| drawer | people and the social layer (Party) | as a dialog; closes when the Party moves |
| menu | a short list of actions on one item | opens at its trigger; arrow keys move; Escape closes |
| notice (inline) | something to know now, in the page | an icon, a title, one sentence, at most one action; `role="status"`, or `role="alert"` for an error |
| snackbar or toast | confirmation of something the person just did | never the only place an error or a needed action appears; stays long enough to read |

One modal surface at a time. A surface never opens another modal surface over itself.

## 7. Loading, empty, error, disconnected

| State | Contract |
|---|---|
| loading | content keeps its shape (skeleton) when the wait is visible; an action shows busy on its own control; the region is `aria-busy` |
| empty | says why it is empty and offers the one way forward or back |
| error | what happened, what it means for the person, one thing to do; plain words, no codes |
| disconnected | two steps: a quiet line at once, a notice with Try again after a delay; what was last known stays on screen and is said to be possibly out of date; the client keeps retrying; nothing says Connected over stale content |
| degraded | names the part that is off and what still works; a title stays listed with a reason, never silently missing |

Healthy infrastructure is mostly invisible. Technical detail belongs behind a deliberate step
(Party's System, an operator surface), never in a guest's or member's main path.

## 8. Focus and keyboard

- Everything reachable by touch is reachable by Tab, in visual order, with a visible ring at every stop.
- Real controls: `button`, `a href`, `input`, `select`; in Flutter, widgets with semantics, never a
  bare gesture detector.
- A state push or re-render does not drop focus.
- A page that changes place moves focus to its heading; a modal surface returns focus to its opener.
- A skip link where a page has repeated navigation before its content.

## 9. Touch and mobile ergonomics

- Targets at least 44 CSS px on the web; 48 for primary controls, and 48 logical pixels as the
  floor in Flutter. At least 8 between adjacent targets.
- Primary actions sit within thumb reach at the bottom of a phone; destructive actions do not sit
  beside them.
- Nothing depends on hover, long-press or a precise drag without an alternative.
- No sideways page scroll at 360 wide. A list may scroll sideways inside itself.
- Never disable zoom.

## 10. Motion

- Motion explains a change of place or state; it is never decoration and never the only cue.
- Durations and easing come from `tokens.json` (`scale.motion`). They are proposals: the Party
  brief leaves exact timings undecided, and the owner sets them.
- `prefers-reduced-motion` (web) and `MediaQuery.disableAnimations` (Flutter): nothing moves or
  scales. A change may cross-fade briefly or switch at once.
- Nothing flashes more than three times a second. Nothing auto-refreshes a whole page.

## 11. Validation

The bar is WCAG 2.2 AA. A screen is not done until these pass on it:

| Check | Web (Party, Media) | Flutter (owner app) |
|---|---|---|
| text contrast 4.5:1, edges 3:1 | automated on every screen and state | `textContrastGuideline` |
| every control named | automated | `labeledTapTargetGuideline` |
| target size | automated measurement | `androidTapTargetGuideline`, `iOSTapTargetGuideline` |
| one top heading, order | automated | semantics review |
| keyboard walk with a visible ring | scripted Tab walk | focus traversal test |
| 200% text, 360 wide, no clipping or sideways scroll | automated viewport run | `textScaler` 2.0 test |
| reduced motion, more contrast | automated media emulation | `disableAnimations`, `highContrast` |
| visual regression | screenshot baselines per screen and state, reviewed on change | golden tests |
| real devices and a screen reader | a human step: iPhone Safari with VoiceOver, Android Chrome with TalkBack | the same, on the built app |

Automated checks are first run against a planted fault and must catch it. A browser check is not a
phone check, and a simulated capability is not an implemented one: reports say which was done.

## 12. Shared and platform-specific

| Shared (this document) | Platform-specific (each product) |
|---|---|
| role names, state names, component contracts | colour values, typefaces, radius, layout |
| space scale, target sizes, window class names | the stylesheet, templates, widgets |
| accessibility bar and the list of checks | the test runner and its fixtures |
| the four state treatments (section 7) | the words used, the voice |
| motion roles | the motion values, once the owner sets them |

## 13. Reference projects (checked 2026-10-11)

| Project | State | Licence | Use to Avrana |
|---|---|---|---|
| Flutter (`flutter/flutter`) | active; stable 3.47 (August 2026); Android API 24+, iOS 15+, web, desktop | BSD-3-Clause | candidate for the owner app only. Its in-SDK Material library is frozen and moving to the `material_ui` package; plan on that package |
| Material Web (`material-components/material-web`) | "in maintenance mode pending new maintainers"; Lit web components | Apache-2.0 | not adopted. Party's CSP, no-build and offline rules and Media's no-framework rule argue against it, and it has no active maintainer |
| Material Components Web (`material-components/material-components-web`) | archived 13 January 2025, read-only | MIT | not adopted |
| Material Design 3 (`m3.material.io`) | the current guideline; its newer Expressive components are not in Flutter's own library | guidance | the reference for roles, states, sizes and patterns above |

## 14. Changing the foundation

1. Propose the change in the Party copy with the reason and the screens it affects.
2. If it alters an accepted ADR, the Party brief or the Media specification, it is an amendment for
   the owner to review, not an edit here.
3. Mirror to Media, update `MIRROR.sha256` in both repositories, and update each product mapping.

Work that follows from this document is tracked in Linear, not here.
