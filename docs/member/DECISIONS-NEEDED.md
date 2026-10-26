# Decisions needed for the member content drafts

Status: **DRAFT register** (AVR-361, S1-6). Every placeholder in `welcome.md`, `help.md`,
`house-rules-and-privacy.md` and `../runbooks/offboarding.md` is listed here, and every entry here appears
in at least one of those files. `tests/test_member_content.py` enforces both directions.

Identifier scheme: `D-n` owner decision (D-1 to D-10 are the charter's numbers in
[`MEDIA-2.0.md`](../design/MEDIA-2.0.md) section 9; **D-11 onward are new here and provisional**);
`U-n` unverified fact with the read-only check the owner would do; `R-n` proposed house rule.
Nothing below has been checked on the host. Linear: AVR-361 is the parent; AVR-363, AVR-366, AVR-367
and AVR-346 are named where they own the blocker.

## Where these are asked (AVR-458, Todo)

AVR-458, "Decide Media's support contact, privacy and member test rules", is still Todo, so nothing in the
drafts is approved. It asks the owner for: the support contact (D-1); whether the new portal may ever show
another person's watch or listen history (recommended: no; this register has no entry for it, and the drafts
say nothing that depends on it); which de-identified usage facts may be collected, who sees them, and
whether members opt in (D-7); a maintenance window for network isolation (D-2, not member content);
and whether the read-only test workflow runs on every PR (D-8, not member content). D-9 to D-17 below are
not in AVR-458 and need their own answers. Treat every privacy and house-rules sentence as DRAFT until D-1
and D-7 are answered.

## Owner decisions

### D-1
- **Question:** the support contact route.
- **Options in the repo:** a plain address first, a form only if spam-free delivery is easy
  (`docs/design/MEDIA-2.0.md:295`). Existing member copy says "Message the admin who invited you"
  (`docs/onboarding/welcome.md:55`) and "Ask Cody to add what you need" (`services/avrana-portal/portal.py:733`).
- **Changes in the drafts:** the contact line in welcome, help (twice) and the leaving section of the privacy page.
- **Blocked:** welcome, help, privacy. Related: D-1; AVR-367, AVR-361. E-mail delivery also depends on M0 (AVR-346).

### D-7
- **Question:** the wording of the House rules and privacy page, including what the monitoring tool records
  and why.
- **Options:** the draft's wording (built only from `docs/services/tracearr.md:10-16, :33-52`); a shorter
  statement that omits the field list; or no mention of the tool (not recommended: the charter names it).
- **Changes:** the "how playback went" entry; the purpose line.
- **Blocked:** the privacy page. Related: D-7; AVR-361, AVR-367.

### D-9
- **Question:** invite plan and member target (about 15).
- **Options:** invite after acceptance testing, not before (`MEDIA-2.0.md:304`). Invite mechanics
  disagree: reusable and expiring for non-technical people (`docs/services/authentik.md:43`) versus
  single use (`docs/onboarding/admin-onboarding.md:38`).
- **Changes:** rule R-2 and the invite sentence.
- **Blocked:** R-2 only. Related: D-9; AVR-363.

### D-11
- **Question:** which address members are told is the home page.
- **Options:** `avrana.net`, the portal and Media 2.0 single front door (`services/avrana-portal/portal.py:397`,
  `MEDIA-2.0.md:15-16`, `docs/audits/2026-10-11-web-interface-audit.md:50-56`); or `auth.avrana.net`, as
  the existing welcome guide says (`docs/onboarding/welcome.md:18`), which is Authentik's own library page.
- **Changes:** the first sign-in step in welcome. The Authentik post-login landing is a separate approved change.
- **Blocked:** welcome. Related: audit A1; AVR-363.

### D-12
- **Question:** the one recommended television app for Fire TV, Google TV, Android TV and NVIDIA Shield.
- **Options:** Wholphin (`docs/onboarding/welcome.md:35-39`; used by the owner per
  `docs/findings/2026-09-23-jellyfin-artwork.md:1`, `docs/ARCHITECTURE.md:20`); or Jellyfin
  (`services/avrana-portal/portal.py:222-235`, `docs/services/jellyfin.md:33-38`).
- **Changes:** one table cell in welcome and one sentence in help. If Wholphin wins, the portal HELP table
  needs a Wholphin entry too (a code change, not made here).
- **Blocked:** welcome, help. Related: AVR-363.

### D-13
- **Question:** what to tell members about forgetting a password and about the separate Movies and TV
  password.
- **Options:** (a) contact the owner, who resets it by hand in two systems (`docs/onboarding/welcome.md:51-52`,
  `docs/onboarding/admin-onboarding.md:74-75`); (b) e-mail self-service: the recovery flow exists
  (`services/authentik/blueprints/avrana-recovery.yaml:6-12`, link expires in 30 minutes, `:37`) but the mail
  credential rotation is pending (`docs/ROADMAP.md:31-33`; M0), so it is not confirmed working. A reset in
  Authentik does not reach Jellyfin or the Komga password copy (`avrana-recovery.yaml:6-8`,
  `docs/services/authentik.md:21`). How a member changes the Jellyfin password themselves is not documented.
- **Changes:** three passages in welcome and help.
- **Blocked:** welcome, help. Related: M0, AVR-346; AVR-363 acceptance ("password resets deliver e-mail").

### D-14
- **Question:** which group shows the Requests help topic.
- **State of the code:** on `main` the Requests help topic is now gated on `avrana-videos`
  (`services/avrana-portal/portal.py:306`), the same group as the Request tile (`:69`). PR #4 (the portal
  authorization suite) merged and changed this; before it, the topic was gated on `avrana-requests`. The
  owner has not confirmed the rule, so the help block stays marked.
- **Other evidence:** the Authentik doc says `avrana-requests` is reserved and gates nothing
  (`docs/services/authentik.md:48`); the admin guide treats it as a real group granted together with videos
  (`docs/onboarding/admin-onboarding.md:14-21, :26`).
- **Options:** keep `avrana-videos` (matches `main` and the tile), or give requests its own group again.
- **Changes:** the group name on one block in help. That block follows `main` (`avrana-videos`);
  `tests/test_member_content.py` pins it so a silent change fails.
- **Blocked:** help, until the owner confirms the rule.

### D-15
- **Question:** the member wording for an unavailable service and where an operator notice appears.
- **Options:** the charter plans one sentence on the home page set from an OliveTin action and per-section
  messages such as "Movies and TV are unavailable right now" (`MEDIA-2.0.md:48-60, :150-158`); neither is
  built. Today the only copy is the portal 404 and each app's own error (`portal.py:851-860`).
- **Changes:** welcome and help "unavailable" passages.
- **Blocked:** welcome, help. Related: M1 operator notices.

### D-16
- **Question:** step-by-step text for requesting ebooks and audiobooks (and where to send a comic request
  that is not approved).
- **Options:** the repo only says Shelfarr is a request platform, signs in through a single Avrana button,
  and routes to the ebook and audiobook libraries (`docs/services/shelfarr.md:7-10`,
  `docs/services/sso-architecture.md:33, :53-56`). No member steps exist; the owner must supply them.
- **Changes:** one bullet in help.
- **Blocked:** help. Related: U-7.

### D-17
- **Question:** the owner's commitment on a "remove your data" request: how quickly, what exactly is
  removed, and whether to say plainly that backup copies are not edited and age out.
- **Options:** the repo establishes that backups are add-only and markers are never rewritten
  (`docs/DECISIONS.md:33`, `services/backups/OFFHOST.md:18-20`), that local runs keep the newest 7
  (`services/backups/README.md:31`) and off-host daily copies about 90 plus 30 days (`OFFHOST.md:28-37`).
  Pinned copies and the golden backup are kept indefinitely (`OFFHOST.md:33`, `docs/BACKUPS.md:12`).
  Whether the monitoring tool's history is in scope is open (U-5).
- **Changes:** the backups paragraph and "Leaving Avrana" in the privacy page (that section is now only a
  marked placeholder tied to this decision, with a holding sentence that promises nothing); the runbook's
  section on honouring a removal request. The runbook and `scripts/offboard.py` show that the tool covers
  Jellyfin, Seerr, Audiobookshelf and Authentik, that other services are manual, and that some history
  survives.
- **Blocked:** privacy page, runbook. Related: D-7; AVR-366.

## Unverified facts (read-only checks)

For each, the repository does not establish the answer. The check is read-only and for the owner.

### U-1
Whether a Jellyfin Quick Connect sign-in is enabled. Source of the claim: `docs/onboarding/welcome.md:38`.
Check: Jellyfin dashboard, General, Quick Connect setting. Changes: one line in welcome (add or drop the code option).

### U-2
Whether an Authentik user set inactive keeps working sessions. `scripts/offboard.py:203-205` only flips
`is_active`; session revocation is a separate admin action (`docs/services/authentik-sessions-passkeys.md:120-124`).
Check: on a disposable account, deactivate then try an existing session. Changes: runbook Step 4 item 7.

### U-3
Whether every comics member has the separate catalog-app password. Members who enrolled before 2026-08-17
have none (`docs/services/komga.md:52-53`). Check: compare the Komga user list with the comics group, counts
only. Changes: the sentence about reader apps in welcome and help; possible reset task.

### U-4
Movies and TV viewing history: whether other members can see it, and whether activity is cleared on a
schedule. Jellyfin's docs here describe neither. Check: Jellyfin dashboard, Activity and Users settings
(retention of the activity log), and a non-admin account's view. Changes: the viewing entry in the privacy page.

### U-5
The monitoring tool: whether its records carry the member's username, what its location fields hold (the
Jellyfin doc says every session appears to come from the tunnel's loopback address, `docs/services/jellyfin.md:113-115`,
so location may be meaningless), and how long history is kept. Check: the tool's settings page and a
read-only look at its retention setting. Changes: the playback entry and removal scope (D-17).

### U-6
Film and show requests: whether other members can see who requested what, whether a request needs approval,
the usual wait, retention. `docs/services/seerr.md` is a one-line stub. Check: Seerr settings and a
non-admin view. Changes: privacy page request entry; help line.

### U-7
Book requests: sign-in, approval rule, wait, visibility to other members, retention. The Shelfarr doc says
the service is not yet in service, LAN only and without OIDC (`docs/services/shelfarr.md:12-13, :29-31, :78-79`),
while the portal links to it and a blueprint and tunnel entry exist (`portal.py:70-71`,
`services/authentik/blueprints/shelfarr.yaml:22, :41`, `deploy/host/cloudflared/config.yml:22`).
Check: a throwaway member account, read-only view of Shelfarr settings. Changes: welcome, help, privacy.

### U-8
Comic requests: how a member learns of approval, wait, visibility and retention. Source:
`docs/services/omnibus.md:60-67` (approval queue, per-user flags). Check: Omnibus settings; a non-admin view.

### U-9
Audiobook progress and history: visibility to other members, any automatic clearing. Source for existence:
`docs/services/authentik.md:25`, `docs/onboarding/admin-onboarding.md:61`. Check: Audiobookshelf settings, a non-admin view.

### U-10
Comic reading progress: whether the owner-side view shows individual progress, and any clearing. Source for
existence: `docs/services/komga.md:75`. Check: a non-admin and an admin view of one test account.

### U-11
Ebook library per-member data beyond the Kindle address (reading state, shelves) and who can see it. Check:
the library's user profile and admin views for a test account.

### U-12
Authentik sign-in events: what they contain (the sessions doc says login events carry audit metadata,
`docs/services/authentik-sessions-passkeys.md:60`) and how long they are kept. Check: Authentik admin,
Events, and its event retention setting (read-only).

### U-13
Whether the Audible connector's event log and import records are deleted on Disconnect
(`services/avrana-audible-connector/README.md:138-144` says the profile and "connector rows" go; the audit
table is not mentioned). Check: connector database row counts before and after a disposable disconnect.

### U-14
What service and proxy logs contain about members and how long they last. The repo only shows size caps
(for example `services/avrana-portal/docker-compose.yml:32`, `services/authentik/docker-compose.yml:35`).
Check: log driver settings per container; read-only look at one log for member identifiers.

### U-15
Whether the off-host bucket lifecycle rule (90 days then 30 days, `services/backups/OFFHOST.md:28-37`) is
actually set (it is set by hand in the Backblaze console), whether the backup seal is installed
(`services/backups/README.md:33-37`), and which long-kept copies exist. Check: bucket lifecycle page;
`--list` of remote runs. Changes: the backup retention sentence.

### U-16
Whether deleting an account removes its stored Kindle address in every library. Source of the storage:
`docs/services/calibre-web-automated.md:92-107`, `services/avrana-kindle-connector/README.md:22-30`.
The address in the audiobook library lives in a global device list, not on the user. Check: delete a
disposable user and inspect the list.

### U-17
Whether Komga can disable (rather than delete) an account, and how to remove accounts in Shelfarr and
Omnibus. The repo documents none. Check: each admin UI on a disposable account. Changes: runbook Step 4.

### U-18
Whether deleting a Seerr user removes their request records, and whether Jellyfin activity entries naming a
deleted user remain. Check: disposable account. Changes: runbook Step 5 and the privacy removal wording.

### U-19
What the Account page Sign out link actually ends: unverified. The portal links it to the outpost endpoint
`/outpost.goauthentik.io/sign_out` (`services/avrana-portal/portal.py:399`, `:687-690`). Nothing in the
repository shows that this ends the Authentik session; `docs/services/sso-architecture.md:146-150` points to
the Authentik settings page for that. Check: on a disposable account, press Sign out, then open another
Avrana app and see whether it signs in without a prompt; compare with signing out at the Authentik settings
page. Changes: the sign-out passages in welcome and the privacy page.

### U-20
Whether an existing Seerr session outlives a disabled Jellyfin account. REASONED, not observed: Seerr signs
in with Jellyfin credentials and keeps its own session, and the tool does nothing to Seerr on deactivation
(`scripts/offboard.py:177-183`). Check: on a disposable account with an open Seerr session, disable the
Jellyfin account and reload Seerr. Changes: runbook Step 3 and Step 4.

## Proposed house rules

None of these is supported by a repository decision. Accept, edit or delete each.

### R-1
Your account is yours; do not share your password. Context: one invitation, one account
(`docs/services/authentik.md:37`).

### R-2
Invitations are personal; ask the owner before inviting anyone. Linked to D-9 (`MEDIA-2.0.md:304`).

### R-3
Personal use only; do not copy, share or redistribute what is on Avrana. No repository source supports it; it is a standard expectation for a private media service, listed for the owner to confirm.

### R-4
Tell the owner promptly about a lost signed-in device. Context: the owner can end sessions and remove a
passkey (`docs/services/authentik-sessions-passkeys.md:129`).

### R-5
The owner may switch off an account that is misused and will say why. No repository source.

### R-6
Check before requesting. Context: duplicate fetches are a documented operator problem when a title is
requested in two places (`docs/services/shelfarr.md:15-19`), not a documented member rule.

## Stale or contradicting statements in existing documents

These files were not edited. `file:line` is the statement; the contradiction follows.

| Statement | Contradicted by |
|---|---|
| `docs/onboarding/welcome.md:13, :31` ("Submi:", "differen") | Text truncated during the BookStack promotion. The same truncation appears at `docs/onboarding/admin-onboarding.md:72, :80, :81`, `docs/services/authentik.md:26, :102`, `docs/services/komga.md:75`, `docs/services/jellyfin.md:79, :119` |
| `welcome.md:18` home is auth.avrana.net | `portal.py:397`, `MEDIA-2.0.md:15-16`, audit A1: home is avrana.net (D-11) |
| `welcome.md:35-39` Wholphin recommended | `portal.py:222-235`, `jellyfin.md:33-38` list Jellyfin (D-12) |
| `welcome.md:38` Quick Connect | No other file confirms it is enabled (U-1) |
| `welcome.md:45-46` one request site | `portal.py:69-72`: three request services |
| `welcome.md:51-52`, `admin-onboarding.md:74-75`, `:79` no recovery flow | `services/authentik/blueprints/avrana-recovery.yaml` exists; `docs/services/sso-architecture.md:130` mentions `avrana-recovery`; mail rotation pending (`docs/ROADMAP.md:31-33`) |
| `welcome.md:10-15` account creation steps | `docs/services/authentik.md:50-64`: e-mail verification and optional passkey steps now exist |
| `welcome.md:54-55` "message the admin who invited you" | D-1 |
| `welcome.md:27-28` comics sign-in | `portal.py:332-336`, `komga.md:13-31`: reader apps need e-mail and password |
| `admin-onboarding.md:14-21, :26` Requests tile gated on `avrana-requests` | `portal.py:69` gates on `avrana-videos`; `authentik.md:48` says reserved, gates nothing (D-14) |
| `admin-onboarding.md:23` blueprints gitignored (also `services/authentik/blueprints/avrana-recovery.yaml:13`, `docs/services/omnibus.md:238`) | `docs/DECISIONS.md:38`: tracked in Git since 2026-10-06 |
| `admin-onboarding.md:38` single-use invites | `authentik.md:43` recommends reusable and expiring for non-technical invitees (D-9) |
| `admin-onboarding.md:52-72` two offboarding versions, six systems at most | `scripts/offboard.py` automates four and never mentions Shelfarr, Omnibus, the Kindle address or the Audible connector; use `docs/runbooks/offboarding.md` |
| `admin-onboarding.md:81`, `authentik.md:26` Komga "trim per user" | `komga.md:55-57`: all libraries, read only, decided 2026-08-17 |
| `admin-onboarding.md:105-109` Komga account only created at first SSO login | `komga.md:19-27`: enrollment creates it with a copy of the password |
| `docs/services/shelfarr.md:12-13, :29-31, :63, :78-86` not in service, LAN only, no OIDC | `portal.py:70-71`, `deploy/host/cloudflared/config.yml:22`, `services/authentik/blueprints/shelfarr.yaml:22, :41`, `sso-architecture.md:33` (U-7) |
| `docs/services/tracearr.md:65` not in backups | `services/backups/README.md:14-16`, `required-artifacts.txt` (`tracearr.pgdump.zst`), `avrana-backup.sh:267-279` |
| `docs/services/calibre-web-automated.md:9` (Gmail), `:35-44` (Postmark), `:112-114` (SMTP2GO, sender address) | Three different mail stories; `services/avrana-kindle-connector/kindle.py:48` and the blueprints use the SMTP2GO sender |
| `docs/services/sso-architecture.md:73-80` | Lists individual members' names in a tracked document; against the no-personal-data rule (`docs/SECURITY.md:13`). Also describes a user divergence measured 2026-08-28 |
| `services/avrana-portal/portal.py:733` first name in copy; `:682` em dash | `docs/design/DESIGN.md:335` (copy rule: second person or neutral, no dashes); audit P3 |
| `docs/services/avrana-portal.md` go-live status of 2026-08-16 ("only remaining: restart") | Superseded by later operation; kept as history |
| `docs/services/authentik.md:170-174` click-through of the verification e-mail never verified | Open owner item before invites (AVR-363) |
