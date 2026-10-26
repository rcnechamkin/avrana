# Optional social enrichment and future federation: feasibility and go/no-go (R4, AVR-749)

Status: **recommendation for owner decision, 2026-10-26.** Documentation only. No social code, store, service or
federation exists or is proposed for M3. Evidence: `docs/audits/2026-10-26-oss-reuse/social-ids.md` (NeoDB
0.19.9.1 `e7020d2f`, Floppy v26.10.22 `52c17cdb`, NodeBB v4.16.4 `ce62dcd5`), and the media identity contract
`docs/design/MEDIA-IDENTITY.md` (R2-B). Coordinates with M4 tickets AVR-480 (private profile), AVR-481 (history
provenance and retention) and AVR-482 (saved titles), whose gates are unchanged.

## 1. Decision summary

| Option | Verdict | Why |
|---|---|---|
| Run NeoDB as the social layer | **No-go** | About 11 containers (two PostgreSQL, Redis, Typesense, ~8 app processes) for ~15 members; no OIDC, so Authentik cannot be its identity provider and every member gets a second account; keeps its own catalogue and scrapes outside sites; federation-first defaults to audit; AGPL-3.0 source offer if patched; separate UI outside the PWA |
| Run NeoDB as an isolated, linked-out sidecar | **Defer** | Only if members later want a public Fediverse presence; Avrana would link out, never integrate |
| Floppy (Yamtrack fork) | **No-go** | A media tracker, not social; its importers pull Jellyfin, Audiobookshelf and Komga **playback history**, which Avrana must never export |
| NodeBB for discussion | **No-go for now** | Strong moderation and ActivityPub, but no notion of a title; would need a custom plugin and a second app |
| **Thin Avrana-native social module, modelled on NeoDB's data model** | **Go for a fixture-only prototype, on owner approval (Q6)**; production needs a separate decision on a persistent store | Lives inside Home, uses Authentik identity, keys records to R2-B identity, nothing leaves the hub by default, wire format chosen so a later federation can talk to NeoDB peers |
| ActivityPub federation between Avrana instances | **Defer (Phase B)** | Feasible with a small allow-listed subset (section 6); not before a private module has real use |

What is studied from NeoDB, never copied (AGPL-3.0): the split of Work and Edition, shelf statuses (wishlist,
in progress, complete, dropped), a 1-10 rating, markdown reviews, collections (lists), and its ActivityPub
extension shape (`relatedWith` with `withRegardTo` pointing at the item). Ideas and wire formats, not code.

## 2. What the module would and would not do

In scope (all opt-in, all on title pages and Me; **no fifth tab, no feed on Home**):

- A rating and an optional short review on a title page, with a spoiler flag that collapses the text by default.
- Personal lists, and a list a member chooses to share with named friends or all members.
- "Recommend to a friend": one title, one friend, an optional note; the friend sees it on Me.
- Friends: mutual, by invitation inside the instance; block and mute.
- Optional per-title discussion thread (later; only if lists and recommendations are used).

Out of scope, always: anything derived automatically from viewing, listening or reading. Continue, progress,
history and library contents never feed the social module. A member's ratings never reveal what libraries they can
use beyond the title they chose to rate.

## 3. Privacy model

| Field | Default visibility | Who can widen it | Notes |
|---|---|---|---|
| Rating | Only me | The member, per item: friends, or all members of this instance | Never public outside the instance in Phase A |
| Review text | Only me | Same | Spoiler flag hides text behind a disclosure; screen readers announce "Contains spoilers" |
| List | Only me | Per list: named friends, all members | A shared list shows each viewer only the titles **that viewer** is entitled to see (section 4) |
| Recommendation | The recipient only | n/a | Shown only if the recipient is entitled to the title |
| Friend list | Only me | n/a | Not browsable by others |
| Viewing / listening / reading activity | **Never collected** | Nobody | Hard rule; enforced by having no write path from adapters to social |

Consent states for every shared record: `private` → `shared` (explicit action, names the audience) → `withdrawn`
(the member removes it; it disappears for others at once). Default on every new record is `private`. No bulk
"make everything public" control.

Retention: records live until the member deletes them or leaves; leaving removes everything they wrote (offboarding,
AVR-366). Export: the member's own records as JSON from Me. Deletion is real deletion inside the instance; the limits
that apply once federation exists are in section 6.

Moderation at ~15 trusted members: block, mute, hide a review, and the owner can remove a record. No public
sign-up, so no spam queue.

## 4. Entitlement filtering and identity

- Records are keyed by the R2-B identity key when one exists (`movie:tmdb:603`, `isbn13:...`), else by the service key
  (`jellyfin:<id>`). This needs **no catalogue**: a record only means something next to an item the viewer's own
  adapters returned.
- Rendering rule: a social record is shown only beside an item the viewing member can already see, found through
  that member's own adapters. A friend's rating of a title the viewer cannot access is not shown, not counted and not
  hinted at. The same rule makes a shared list per viewer.
- Identity is the Authentik principal Home already trusts (G1/G2). No second account.
- Re-identification (an upstream changes an ID) can orphan a record; the prototype shows orphans to their author
  only, under Me, so nothing is lost. A redirect table is only worth adding if this happens in practice.

## 5. The seam: social off or down never touches core media

- The module is optional: `HOME_SOCIAL=off` (default) means no route, no template block, no store connection and no
  query. Every existing page renders byte-identically to today.
- With social on, social blocks are fetched after the media content, with their own short deadline; a failure hides
  the block and never changes the page's status code, the media sections, the primary action or the cache.
- Tests the prototype must ship with (fixture-only): byte-identical Home, Library, Search, title, Me and help pages with
  social off; the same pages with social on but its store unavailable, slow and malformed; two members with
  different entitlements seeing a shared list differently; a friend's rating of a title the viewer cannot see is
  absent; revoked group removes the social block on the next request; no social data in cache keys, logs or
  `/home.json`.

## 6. Future federation (Phase B): boundary and threat model

Minimum for opt-in exchange between Avrana instances: WebFinger, one actor per member who opts in, inbox and outbox,
HTTP Signatures, `Note`/`Article` objects with NeoDB-compatible extensions for a rating, review or list, and an
**allow-list of peer instances** (no open federation, no relays).

May federate (only records the member marked for federation): ratings, reviews, shared lists, recommendations
addressed to a remote friend, the follow relationship itself.

**Never federates**: media files or URLs that play them, hand-off links, artwork bytes, library inventories, which
libraries a member can use, Continue, progress, history, upstream account names, tokens or credentials.

| Threat | Consequence | Mitigation |
|---|---|---|
| A peer ignores "followers only" | A friends-only review becomes visible beyond the audience | Federate only records marked for federation; treat everything federated as potentially public; say so at the moment of sharing |
| Deletes are best effort | A deleted review may survive in a peer's cache | Send `Delete`; tell the member deletion cannot be guaranteed once federated |
| A record reveals inventory | "Rated title X" implies the member has access to X | Rating a title never states where it was watched; the member chooses each federated record |
| Actor key compromise | Impersonation on peers | Per-member keys stored with the instance secrets; rotation runbook before go-live |
| Abuse from a peer | Harassment | Allow-list only, per-peer block, owner kill switch that stops all federation |

## 7. Owner decisions needed before any code

- **Q6a** Approve a fixture-only prototype of the native module (no store; in-memory synthetic records) as a draft PR?
- **Q6b** Later, for production: approve a persistent store for social records (SQLite inside Home's volume is the
  smallest option; it is a new persistent datastore and needs its own backup entry and review).
- **Q6c** Which features first: ratings and reviews; lists; recommendations; discussion?
- **Q6d** Federation stays deferred; revisit only after the private module has real use.

## 8. Not done here

No prototype was written, because Q6a is an owner decision and a prototype without it would be unapproved feature
work. Everything above is design; nothing was run against members or services.
