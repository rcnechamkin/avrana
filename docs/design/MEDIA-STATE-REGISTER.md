# Avrana Media state register

Dated **2026-10-26** (AVR-505). One page that says which tier each piece of Avrana Media is in, so a draft,
an approved scope or a direction is never read as deployed behaviour. Issue IDs are Linear (AVR-…); PR
numbers are `rcnechamkin/avrana`. When this page and the running host disagree, the host wins
(`AGENTS.md`, evidence order); record the disagreement here instead of picking one silently.

Nothing in this register approves a production change, a merge or an implementation. Each still needs the
owner's approval for that specific step, as [`MEDIA-2.0.md`](MEDIA-2.0.md) and `AGENTS.md` require.

## The six tiers

| Tier | Means | Evidence that moves an item into it |
|---|---|---|
| 1. Deployed | Running on host `avrana` today | Listed in [`SERVICES.md`](../SERVICES.md) or observed on the host |
| 2. On main | Merged to `main`, not running on the host | A merge commit on `main` |
| 3. Draft PR | Open pull request: not merged, not approved | An open PR number |
| 4. Approved M3 scope | What the launch milestone is allowed to build | An owner decision in [`DECISIONS.md`](../DECISIONS.md) or the charter |
| 5. Selected direction | Product direction the owner has chosen for after M3 | An owner statement marked "direction"; **not** implementation approval |
| 6. Far future / deferred | Recorded so it is not lost; no work planned | Owner deferral |

An item moves down a tier (towards 1) only on the evidence in the right-hand column. Being described in a
higher tier never implies the tier below it.

## 1. Deployed (host `avrana`)

- The containers in [`SERVICES.md`](../SERVICES.md): Jellyfin, Audiobookshelf, Komga, Calibre-Web
  Automated, Seerr, Shelfarr, Omnibus, the portal, the Kindle and Audible connectors and the rest.
- **`avrana-home` (the Media 2.0 Home) is not deployed.** It has no container and no hostname. Members use
  the existing portal and linked handoffs to the existing apps.
- No Concept K screen, OpenAPI check, identity change, synopsis change or About block is running anywhere.

## 2. On main (`99f0d7c`, 2026-10-26)

- Merged Media 2.0 code under `services/avrana-home/` and its docs, tested offline
  (`python3 tests/run_offline.py`). Merged is not deployed: none of it runs on the host.

## 3. Draft PRs (#65–#80)

Not merged. No owner phone approval. **No GitHub Actions result** for any of them (Actions is
billing-blocked); only local offline runs are claimed, never CI.

| PR | What | Issue | Base / stacking |
|---|---|---|---|
| #65 | MK-0 design foundation mirror re-sync (3 files) | AVR-714 | on main; **not** inside #74, merges cleanly on top of it |
| #66 | MK-3 PWA shell, first-party script, service worker | AVR-717 | on main; contained in #74 |
| #67 | MK-1 Concept K foundations on shell pages | AVR-715 | on main; contained in #74 |
| #68 | MK-2 shell: tab bar, Home button | AVR-716 | on #67; contained in #74 |
| #69 | MK-4 Home hero, rails, Recently added | AVR-718 | on #68; contained in #74 |
| #70, #71 | MK-5a Library and title page; MK-5b Search, Request, Me, Account, Help | AVR-719 | on #69; contained in #74 |
| #72, #73 | MK-7 docs; MK-6 motion | AVR-721, AVR-720 | merged into the #74 branch only (not main) |
| #74 | **Concept K integration base** (MK-1..MK-7) | AVR-713 | on main; supersedes #66–#71 if merged |
| #75 | R1 open-source reuse audit | AVR-746 | on main |
| #76 | R2-A Jellyfin adapter checked against an OpenAPI subset | AVR-747 | on main |
| #77 | R2-B media identity | AVR-747 | on main |
| #78 | R2-C synopsis on title pages | AVR-384 | stacked on #77; conflicts with #74 in `viewmodel.py` (resolved inside #80) |
| #79 | R4 social and federation feasibility (research; owner deferred) | AVR-749 | stacked on #75 |
| #80 | R3-A About block | AVR-748 | on #74, carrying #77 and #78 byte-for-byte |

## 4. Approved M3 scope

What M3 may build (charter [`MEDIA-2.0.md`](MEDIA-2.0.md); Concept K memo recommendations D1–D17 approved by the owner on
2026-10-26, AVR-713). Approved
scope is permission to build and review, not to deploy.

- Concept K, four tabs: **Home · Library · Search · Me**.
- Home places bar: **Watch · Listen · Read · Request · Help**.
- Media accent yellow **`#EADA6E`**.
- Progressive enhancement: every page works with JavaScript off.
- The current hero is the **first Continue item**.
- Only **proven external player handoffs** (open the right app at the right item).
- M3 gates, all open: **AVR-585** (real device and accessibility), **AVR-386** (security and CI),
  **AVR-387** (opt-in member beta acceptance), **AVR-389** (cut-over).

## 5. Selected post-M3 direction (owner, 2026-10-26)

From the owner's "Personal Experience Specification v0.1". **Direction, not implementation approval**:
each item needs its own design, review and approval before code, and none is M3 scope.

| Issue | Direction | Boundaries the owner set |
|---|---|---|
| AVR-750 | Cinematic, featured-first Home hero | Owner-pinned title that is available; an authorised fallback; Continue immediately beneath; no new tab; owner visual sign-off |
| AVR-751 | Spike: in-app, Jellyfin-compatible browser playback | Uses Jellyfin's existing player path; no new transcoder |
| AVR-390 → AVR-393, AVR-726 | Native movie and TV requests | Only through a server-side, member-authorised, allowlisted, idempotent, audited boundary; never a Seerr admin or global key in the browser |
| (same) | Request progress | Real and member-scoped; SABnzbd percentage or ETA only for a provably correlated job; "Available" comes from Jellyfin saying the member can play it |
| AVR-752 | In-app inbox | Independent of push; opt-in PWA push only on first actual playable availability, to the requester and explicit followers |
| AVR-753 | Release tracking | Independent of requests and follows; a release date is not "available on the server"; TBA when unknown |
| AVR-754, AVR-724 | Phone-to-TV control | A separate, later capability; a phone URL handoff is not TV playback |

Seerr: "not impossible to integrate", but the request broker design comes first (AVR-390).

## 6. Far future / deferred

- Social: AVR-749 (#79 is research only); no prototype.
- Household profiles.
- Native clients, TV first and only when proven necessary. Future license-compliant forks of upstream
  clients (Wholphin, for example) may be evaluated, weighing GPL/AGPL obligations, upstream notices,
  trademarks and assets, and the update burden. M3 itself makes no upstream patches.
- A public installer or white-label build.
- Multiserver, portable identity and federation: last.

## Owner dispositions (2026-10-26)

| # | Question | Disposition |
|---|---|---|
| Q1 | Jellyfin 12.x | No upgrade now. A future owner-controlled upgrade, with rollback and proof of the deployed contract |
| Q2 | Seerr in M3 | Handoffs only, and only where the URL, version and ID allowlist is proven |
| Q3 | Komga | Shared view unchanged; no member API keys |
| Q4 | Books and comics | Handoffs only |
| Q5 | OpenAPI facts | Minimal facts with hashes and provenance; legal disposition still open |
| Q6 | Social | Deferred |
| — | AVR-723 NextUp | Not approved |

## Keeping this current

Update the date and the affected tier whenever a PR merges, closes or is deployed, or the owner changes a
disposition. Do not move an item to tier 1 or 2 without the evidence in the tier table.
