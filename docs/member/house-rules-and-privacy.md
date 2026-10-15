<!--
DRAFT FOR OWNER REVIEW (AVR-361, S1-6), decision D-7. Not published, not wired into any service, not
sent to any member. Plain language by design; this is not legal text and makes no promise the
repository cannot back. Every factual line has a source comment; where the repository does not
establish a fact, an UNVERIFIED placeholder says so and the register gives the read-only check.

NOTE TO THE IMPLEMENTER
- Neutral core plus per-library blocks. Show a block only when the signed-in member holds at least one
  group named in its marker. Marker syntax is flat: "if: group" or "if: group-a | group-b", closed by
  "endif". Remove hidden blocks from the response; do not hide them with CSS. A member must not learn,
  from this page, that a service exists which they cannot use.
- The per-system privacy entries are separate sections (not one table) so that each can be shown or
  removed whole.
- The neutral core names no library, app or media type, and does not name the operator-only monitoring
  tool. Keep it that way.
- Placeholders in square brackets are open questions, listed in DECISIONS-NEEDED.md. Proposed rules are
  marked PROPOSED RULE and must each be accepted or deleted by the owner. Do not ship a page that still
  contains a placeholder.

Sources (repo paths):
  docs/services/authentik.md, authentik-sessions-passkeys.md, sso-architecture.md, jellyfin.md,
  audiobookshelf.md, komga.md, calibre-web-automated.md, seerr.md, shelfarr.md, omnibus.md, tracearr.md
  services/avrana-audible-connector/README.md, services/avrana-kindle-connector/README.md
  services/backups/README.md, services/backups/OFFHOST.md, services/backups/avrana-backup.sh
  services/avrana-portal/portal.py; scripts/offboard.py; docs/design/MEDIA-2.0.md section 1 and D-7
-->

# House rules and privacy

**DRAFT for owner review. Not published and not final.**

Avrana is a small, private media service. This page says how to use it, what it records about you,
who can see that, how long it is kept, and how to leave.

## House rules

[PROPOSED RULE R-1, owner to accept or delete: Your account is yours. Keep your password to yourself and do not let someone else use your sign-in.]

[PROPOSED RULE R-2, owner to accept or delete: Invitations are personal. Do not pass on an invitation link. If someone else would like to join, ask the owner.]
[OWNER DECISION D-9: the invite plan, who may be invited and how many members Avrana aims for]

[PROPOSED RULE R-3, owner to accept or delete: Avrana is for personal use by its members. Do not copy, share or redistribute what you find here.]

[PROPOSED RULE R-4, owner to accept or delete: If you lose a device that is signed in to Avrana, tell the owner promptly so its sessions can be ended.]

[PROPOSED RULE R-5, owner to accept or delete: The owner may switch off an account that is misused or needed for the safety of the service, and will say why.]

Good habits that Avrana's own design supports:

- Signing out of one app does not sign you out of Avrana. On a shared or borrowed device, use Manage
  account on the Account page, which opens the account settings where Avrana documents signing out of
  Avrana itself. [UNVERIFIED U-19: what the Sign out link on the Account page actually ends]
- Use the app that Help recommends for your device.
<!-- src: docs/services/sso-architecture.md:142-150; services/avrana-portal/portal.py:398-399, :744-747 -->

<!-- if: avrana-videos -->
### Movies and TV

[PROPOSED RULE R-6, owner to accept or delete: Ask for a title once and check whether it is already there or already requested before you ask.]
<!-- src: none; proposed. Duplicate fetches are a documented operator problem for books (docs/services/shelfarr.md:15-19) -->
<!-- endif -->

<!-- if: library-contributors -->
### Adding Audible books

Only add audiobooks that you own. You sign in to Amazon on Amazon's own page, and Avrana never sees your
Amazon password.
<!-- src: docs/onboarding/welcome.md:49; services/avrana-audible-connector/README.md:5-6, :58-59, :138-144 -->
<!-- endif -->

## Privacy: what is recorded, who can see it, how long, how to leave

The owner can see everything described here, because the owner runs the services. The entries below
therefore say who else can see each thing. "Not established" means that the owner has not yet confirmed
the answer, and the entry says what will be checked.

### Your Avrana account and sign-in

- **Recorded:** your username, name and e-mail address, your password, the groups that decide what you
  can use, whether your e-mail address was verified, any passkeys you add, your active sessions, and a
  record of sign-in events.
  <!-- src: docs/services/authentik.md:37, :27, :45-64; docs/services/authentik-sessions-passkeys.md:21-33, :60, :75-83 -->
- **Who can see it:** the owner. You can see your own details, devices and sessions on the Account page.
  <!-- src: services/avrana-portal/portal.py:730-747; docs/services/authentik-sessions-passkeys.md:120-124 -->
- **How long:** the account is kept until it is removed. A sign-in lasts 30 days, or 180 days if you
  choose to stay signed in. [UNVERIFIED U-12: what the sign-in event record contains and how long it is kept]
  <!-- src: docs/services/authentik-sessions-passkeys.md:21-33 -->
- **Leaving:** see "Leaving Avrana" below.

### The Avrana home page

The home page reads which groups you belong to in order to show your tiles. It stores nothing about you
and writes no per-visit log.
<!-- src: services/avrana-portal/portal.py:1-8, :979-980 -->

### Backups

- **Recorded:** every night a copy is made of the data Avrana keeps, which includes the account details
  and the records described on this page. The media files themselves are not part of it.
  <!-- src: services/backups/README.md:12-20 -->
- **Who can see it:** the owner. A second, encrypted copy is sent to outside storage. File names and
  contents are encrypted before they leave the machine.
  <!-- src: services/backups/OFFHOST.md:6-26 -->
- **How long:** the newest seven complete copies are kept on the machine. Outside storage keeps daily
  copies for about 90 days, plus 30 days after that during which a removed copy can still be restored.
  A small number of copies are marked to be kept much longer. [UNVERIFIED U-15: that the outside storage rule is actually set, and which long-kept copies exist]
  <!-- src: services/backups/README.md:31-33; services/backups/OFFHOST.md:28-37 -->
- **Removal:** backup copies are never edited. If your data is deleted from a service, it stays in older
  backup copies until they expire. [OWNER DECISION D-17: whether to state this plainly as it is, and the owner's promise on removal requests]
  <!-- src: services/backups/OFFHOST.md:18-20 (add-only), docs/DECISIONS.md:32 -->

### Logs

Logs are kept, limited in size and overwritten as they fill. The home page
writes no request log. [UNVERIFIED U-14: what the logs contain about members, and how long entries last]
<!-- src: services/avrana-portal/portal.py:979-980; services/avrana-portal/docker-compose.yml:32; services/authentik/docker-compose.yml:35; services/avrana-kindle-connector/docker-compose.yml:60 -->

<!-- if: avrana-videos -->
### Movies and TV: viewing

- **Recorded:** your account in the Movies and TV service (your username and a copy of your password;
  no e-mail address), what you have watched and where you stopped, and an activity log of when playback
  started and stopped.
  <!-- src: scripts/offboard.py:14-15, :23; docs/services/authentik.md:34; docs/onboarding/admin-onboarding.md:68-69; docs/services/jellyfin.md:175-176 -->
- **Who can see it:** the owner. [UNVERIFIED U-4: whether other members can see your watch history or activity]
- **How long:** until your account there is deleted. Switching an account off keeps the history.
  [UNVERIFIED U-4: whether activity entries are cleared on a schedule]
  <!-- src: scripts/offboard.py:23 -->

### Movies and TV: how playback went

- **Recorded:** the owner also uses a monitoring tool that records how each stream played: whether the
  video played as it is or was converted, the video and audio formats, the picture size, the bitrate,
  the quality, and which app, device and platform you used, plus location-related fields.
  It only records because an add-on in the Movies and TV service reports each session to it.
  [OWNER DECISION D-7: confirm this wording of what the monitoring tool records]
  [UNVERIFIED U-5: whether the record carries your username, what the location fields hold, and how long history is kept]
  <!-- src: docs/services/tracearr.md:10-16, :33-52 -->
- **Who can see it:** the owner. The tool is reachable only on the home network, not from the internet.
  <!-- src: docs/services/tracearr.md:24-25 -->
- **Why:** to find out why a device cannot play something, not to review what individuals watch.
  [OWNER DECISION D-7: confirm that purpose statement, which the repository supports only as the tool's stated purpose]
  <!-- src: docs/services/tracearr.md:10-16 -->

### Movies and TV: requests

- **Recorded:** a request account that is created automatically the first time you sign in, and the
  films and shows you ask for.
  <!-- src: docs/onboarding/welcome.md:45-46; docs/services/authentik.md:12, :34 -->
- **Who can see it:** the owner. [UNVERIFIED U-6: whether other members can see who requested what]
- **How long:** [UNVERIFIED U-6: retention of request history]
<!-- endif -->

<!-- if: avrana-audiobooks -->
### Audiobooks

- **Recorded:** an audiobook account with your name and e-mail address, your listening progress and
  bookmarks, and your listening history.
  <!-- src: docs/services/authentik.md:25; docs/onboarding/admin-onboarding.md:61 -->
- **Who can see it:** the owner. [UNVERIFIED U-9: whether other members can see your progress or history]
- **How long:** until your account there is removed. [UNVERIFIED U-9: any automatic clearing of history]
<!-- endif -->

<!-- if: avrana-comics -->
### Comics and manga

- **Recorded:** a comics account with your e-mail address and a copy of your password, and your reading
  progress.
  <!-- src: docs/services/komga.md:19-31, :75 -->
- **Who can see it:** the owner. Other members cannot list accounts or change anything in the library.
  <!-- src: docs/services/komga.md:61-74 -->
  [UNVERIFIED U-10: whether the owner-side view shows individual reading progress, and any automatic clearing]
- **How long:** until your account there is removed.

### Comics and manga: requests

- **Recorded:** the comics you ask for, the series you follow, and the approval state of your requests.
  <!-- src: docs/services/omnibus.md:60-67, :172-179 -->
- **Who can see it:** the owner approves requests. [UNVERIFIED U-8: whether other members can see your requests or follows]
- **How long:** [UNVERIFIED U-8: retention of request history]
<!-- endif -->

<!-- if: avrana-books -->
### Ebooks and your Kindle address

- **Recorded:** an account in the ebook library, created the first time you sign in. The library checks
  your password with Avrana and does not keep a usable copy of it. If you use Send to Kindle, your Kindle
  address is stored, in plain form, in each of your libraries that can send to a Kindle. The Kindle setup
  page itself stores nothing.
  <!-- src: docs/onboarding/admin-onboarding.md:105-107; docs/services/calibre-web-automated.md:77-78, :92-107; services/avrana-kindle-connector/README.md:100-106 -->
- **Who can see it:** the owner. The address is attached to your account only, so other members do not
  see it. [UNVERIFIED U-11: whether the ebook library keeps other per-member data such as reading state or shelves, and who can see it]
  <!-- src: docs/services/calibre-web-automated.md:96-103; services/avrana-kindle-connector/README.md:22-40 -->
- **How long:** until you remove the address on the Kindle setup page or your account is removed.
  [UNVERIFIED U-16: that deleting an account also deletes its stored Kindle address in every library]
<!-- endif -->

<!-- if: avrana-books | avrana-audiobooks -->
### Ebook and audiobook requests

- **Recorded:** the books you ask for.
  <!-- src: docs/services/shelfarr.md:7-10 -->
- **Who can see it:** the owner. [UNVERIFIED U-7: whether other members can see your requests]
- **How long:** [UNVERIFIED U-7: retention of request history]
<!-- endif -->

<!-- if: library-contributors -->
### Adding Audible books

- **Recorded:** which Avrana account is linked to which connected Audible account, the books you own that
  you chose to add, the progress of each import, and an event log of connecting, importing and
  disconnecting. The log holds no secrets. Your Audible sign-in details are kept in a separate folder
  for your account only. Your Amazon password is never seen or stored, and the link you paste back from
  Amazon is used once and discarded.
  <!-- src: services/avrana-audible-connector/README.md:5-6, :40-56, :58-59, :67-69 -->
- **Who can see it:** the owner. Other contributors cannot scan, list or import against your account.
  <!-- src: services/avrana-audible-connector/README.md:40-56 -->
- **How long:** your Audible sign-in details are deleted when you press Disconnect, and automatically
  after a one-time import finishes. [UNVERIFIED U-13: whether the event log and import records are also deleted on disconnect]
  The sign-in details are not part of backups. The records database is.
  <!-- src: services/avrana-audible-connector/README.md:127-144; services/backups/avrana-backup.sh:153-156 -->
<!-- endif -->

## Leaving Avrana

To leave, contact an admin by the contact route: [OWNER DECISION D-1: the support contact route].

[OWNER DECISION D-17: what leaving does to each account and record, whether accounts are switched off or deleted, how quickly a request is carried out, and exactly what is removed]

Until that is decided, this page states nothing specific about what happens to accounts or records
after a request to leave. Backup copies are not edited; see Backups above.
<!-- src: docs/runbooks/offboarding.md (the tool covers some services, the rest is manual, and some history survives); scripts/offboard.py:21-27; services/backups/OFFHOST.md:18-20 -->
