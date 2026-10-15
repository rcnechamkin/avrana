# Avrana Assistant: data classification and approved-corpus policy

Status: **proposed, not approved, nothing deployed.** Written for owner review under Linear AVR-397
(milestone A0). Companion to [`THREAT-MODEL.md`](THREAT-MODEL.md). The corpus it governs is the proposal in
`services/avrana-assistant/corpus/manifest.json`.

Principle: the Assistant starts from **nothing allowed** and each class below is a deliberate, narrow
opening. Anything not classified is treated as operator-internal.

## 1. Data classes

| Class | What it is (examples) | Retrieval corpus | Prompt | External model provider | Logs | Retention |
|---|---|---|---|---|---|---|
| **public-help** | Generic help that is safe for any visitor: how to reset a password, how to contact support, what the assistant cannot do. No service names, no entitlement information | Yes, audience `public` | Yes | Yes, once the owner approves a provider | Document ids may be logged | Corpus: kept under version control with the manifest |
| **member-general** | Reviewed help for signed-in members that names services and apps: per-service access, which app to install, how to request. Audience is the member's own groups | Yes, audience `all_members` or `any_of_groups`, filtered by the caller's `Principal` before ranking | Yes, only passages the caller's audience permits | Yes, once approved; only passages the caller was already entitled to read | Document ids only; never the text | Corpus as above |
| **member-personal** | Anything about one person: username, e-mail, group list, playback or reading history, request history, support messages, the member's own questions and the conversation | **No** | Question text yes (it is the input). Identity, groups, history **no** in A0 | **No** for identity, entitlements and history. The question itself is sent only after egress redaction and only to an owner-approved provider | Decisions only in A0: behaviour class, doc ids, token counts, a salted hash of the subject. No question or answer text. Any transcript retention needs consent | A0: none stored. Later phases: owner-set period, deletion route, consent (AVR-416) |
| **operator-internal** | Hostnames beyond the member set, IPs, ports, container and service names, paths, runbooks, audits, incident reports, topology, backup layout, architecture notes, Linear and design documents | **No**; the corpus test rejects deny-list hits | **No** | **No** | **No** (redacted before logging) | Stays only in the repository and on the host |
| **secret** | Passwords, tokens, API keys, OIDC secrets, recovery links, tunnel credentials, keys, anything credential-shaped | **No** | **No** (redacted from member input before any use) | **No** | **No** | Never stored by the Assistant. Locations only, as in `docs/SECRETS.md` |

Notes:

- Operator documents in this repository (for example `docs/OPERATIONS.md`, `docs/NETWORKING.md`,
  `docs/services/*`, `docs/design/MEDIA-2.0.md`, `docs/incidents/*`) contain internal detail. They are
  cited in the manifest as *provenance of a fact* only. Their text is never copied into corpus documents; a
  member-safe sentence is written fresh and the source's blob hash and a literal anchor are recorded so a
  change in the source is noticed.
- The BookStack wiki is retired (`AGENTS.md`); its archive is not a corpus source.
- A document that mixes classes takes the most restrictive one, or is split.

## 2. Who can retrieve and see what

| Source | Anonymous | Member without the group | Member with the group | Operator |
|---|---|---|---|---|
| public-help documents | yes | yes | yes | n/a |
| member-general, audience `all_members` | no | yes | yes | n/a |
| member-general, audience `any_of_groups` | no | **not retrieved, not ranked, not sent to a model** | yes | n/a |
| member-personal (the member's own) | no | own only, later phases | own only | not through the Assistant |
| member-personal (anyone else's) | no | no | no | not through the Assistant |
| operator-internal, secret | no | no | no | not through the Assistant |

The audience filter uses the `Principal` supplied by the edge, never anything in the message. Group
names follow the vocabulary in `services/avrana-portal/portal.py` (`avrana-videos`, `avrana-audiobooks`,
`avrana-comics`, `avrana-books`, `avrana-requests`, `library-contributors`).

## 3. Answering "why can't I see X" without leaking

The portal already shows a member only their own tiles and returns 404, not 403, for anything else, so
nothing hints that a withheld service exists. The Assistant extends that rule:

1. It may talk about services on the caller's own account and nothing else.
2. For a service not on the caller's account it neither confirms nor denies that the service exists, and it
   never says which other members have it. Documents for that service are not retrieved, so the model
   never sees them.
3. The answer is the generic "missing-library" document: access is set per account; your home page shows
   what is switched on; contact support if you expected something.
4. It does not offer to change access and does not reveal what would have to change. Only a person can.
5. Audience-neutral documents (access overview, request overview, account page, password reset, service
   status, support contact) do not name specific services or media types; a test enforces this.

## 4. Outbound policy (to any external model provider)

- Send only: the system text, the sanitised question, and passages classed public-help or member-general
  that the caller's audience permits. Nothing else.
- Never send: username, e-mail, groups, history, tool results about the member (A2+ requires an explicit
  redacted form approved by the owner), operator-internal text, secrets.
- The egress filter (a) rejects any message whose data class is not on the allow list, (b) blocks the
  request if system or retrieved text carries deny-list markers, (c) redacts secret-shaped and
  operator-internal strings and e-mail addresses from the member's own text.
- Keys are held server-side and never reach the browser. No provider is approved, and A0 uses none.
- The provider's own retention and training terms are an owner decision before any experiment.

## 5. Logging and retention

- Operational logs hold: timestamp, behaviour class, document ids cited, token counts, budget outcome,
  guard findings by kind and offset, a salted hash of the subject. They never hold question text, answer
  text, groups, usernames, or matched deny-list text.
- Conversation transcripts are not stored in A0. A later pilot needs a written retention period, a deletion
  route, a way for a member to leave, and the member's explicit consent to narrow, stated uses.
- Audit records for tool decisions (A2+) follow the same no-content rule.

## 6. Escalation redaction

When the Assistant hands a case to a human (pointing to the support route in A0, a ticket in A2) the
summary contains only: the service address the member named, the behaviour class, and the member's own
description after redaction of secret-shaped strings, e-mail addresses and operator-internal strings. No
history, no group list, no transcript. The member sees and confirms the exact text before it is sent.

## 7. Approved-corpus process

1. A document is written fresh in member language from member-safe sources, with its audience and class.
2. The manifest records id, title, audience, class, `review_status`, each source path, the git blob hash of
   the source at extraction, and a literal anchor string that must still appear in the source.
3. Tests fail when a source changes (re-review), an anchor disappears, a document is unreferenced, a
   document changed after review, or a deny-list marker appears.
4. Review status stays `proposed` until the owner approves; nothing in the manifest is approved today.
5. Poisoned and adversarial documents used for testing are synthetic fixtures kept outside the corpus
   (`services/avrana-assistant/eval/fixtures/`) and carry the status `synthetic-fixture`.

## 8. Corpus gaps (facts the repository does not provide)

| Gap | Owner decision that would fill it |
|---|---|
| No live service-status source | Operator notice banner (Media 2.0 M1) or a sanitised status adapter (AVR-411) |
| Repository contradicts itself on whether e-mail password recovery is live | Complete SMTP credential rotation and verify the flow end to end |
| Welcome guide recommends one TV app, portal help another | Choose the recommended TV app and correct the stale source |
| Home page address differs between sources | Confirm the member address |
| No member steps or turnaround for book and comic requests | Write member help for those services |
| Send-to-Kindle sender address exists only as a named e-mail in portal source | Decide whether the Assistant may state it |
| Support contact route (D-1) | Decide D-1 |

## 9. Member pilot prerequisites (later)

Explicit consent, narrow stated use, an opt-in switch, the retention and deletion terms above, and the
owner's separate approval. None of this is granted by approving this document.
