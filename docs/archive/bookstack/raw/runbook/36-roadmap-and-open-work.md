---
bookstack_page_id: 36
title: "Roadmap and Open Work"
shelf: "Avrana Homelab"
book: "Runbook"
chapter: ""
created: 2026-08-13 21:28:53
updated: 2026-08-29 04:42:36
last_editor: "Cody"
revisions: 41
tags: []
source_format: markdown
classification: STALE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-29; exported 2026-10-04. Classified STALE. Roadmap frozen on 2026-08-29; superseded by docs/ROADMAP.md.

# Roadmap and Open Work
# Roadmap and Open Work

## Current Priorities / Open Work

*Triaged 2026-08-16. Grouped by what actually gates each item, so the next action is visible
without reading the whole list.*

### Blocked on Cody (a credential or a decision, not work)

*Added 2026-08-21 (see Change Log → Session 2026-08-18 to 2026-08-21).*

- ~~**`sudo systemctl daemon-reload`**~~ **DONE, verified 2026-08-28.**
  `systemctl show docker.service -p After` now lists `mnt-avrana_media-comics_merged.mount`, so
  the union is guaranteed to mount before Docker starts. Komga is reboot-safe. Re-check with:
  `systemctl show docker.service -p After | tr ' ' '\n' | grep comics_merged`
- **Delete the "Requested Comics" Komga library** — it now holds 0 series after the union
  cutover. Needs the UI or an admin API key; the Homepage key is guest-level and 403s.

- **Two Alexa routines, by hand.** `Bookshelf Lights ON` / `OFF`, action Smart Home → Amazon
  Smart Plug → power, **no speech action**, both enabled. There is no supported API to create
  Alexa routines. Until they exist the Echo chimes on every voice command, because the fallback
  path is `send_text_command`, which feeds an utterance to the speech engine. Once created,
  repoint `automation.kern_hq_bookshelf_lights_legacy_text_command_bridge` to `button.press`
  and delete the legacy bridge plus `switch.bookshelf_lights_on_off`.
- **Physically double-press the Voice PE dial.** The action half is proven; the trigger half has
  never fired (`event.…button_press` is still `unknown`). Watch whether it also wakes the
  assistant.
- **Komga library for Omnibus.** Root `/avrana_media/avrana_media/comics_omnibus/library`
  (Komga's *internal* view, not the host path). The Homepage API key belongs to Komga's guest
  user and cannot create libraries — needs an admin key or a click in the UI. Until then
  completed comics will not surface to users.
- **SABnzbd as a download client inside Omnibus.** Its credential fields are encrypted with the
  DB master key, so this genuinely needs the UI rather than a SQL insert.
- **Extend the root LV.** ~58 GB of the SSD is unallocated:
  `sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv && sudo resize2fs /dev/ubuntu-vg/ubuntu-lv`
  Online, seconds, no data risk. Root is 57 GB at 63%.

### Known-bad, added 2026-08-21

- **Komga's 8 read lists are all empty**, and an empty read list pegs a CPU core forever the
  moment its thumbnail is requested (upstream loop bug — see the Change Log entry). A restart
  clears it; only populating or deleting the lists prevents recurrence. Worth reporting upstream.
- **`services/home-assistant/config/` and Tracearr's `config/` are not in the nightly backup.**
  The HA directory holds the whole Kern HQ build including the Voice PE encryption key.
- **`cloudflared-comics.service` and `cloudflared-health.service` are both in `failed` state**
  (`comics.avrana.media`, `health.avrana.media`). Pre-existing, unrelated to this session.
- **Docker is near its default network address-pool limit.** Four unused networks were reclaimed
  to fit Omnibus; the real fix is `default-address-pools` in `daemon.json` (needs sudo + daemon
  restart).

- ~~**`ops.avrana.net` is one command from live**~~ **DONE 2026-08-17.** The tunnel was
  restarted; `ops.avrana.net` and `kindle.avrana.net` both serve (302 to Authentik sign-in).
  Restarting the tunnel is now a button in OliveTin, so future hostnames do not need this step.
- ~~**Commits held locally, unpushed**~~ **DONE 2026-08-17.** All pushed through
  `18b20bc`; working tree clean apart from the untouched `filing_cabinet/` files.
- **Off-host backup copy**: the **only remaining single point of total loss**. Backups live on
  `/dev/sdb1` *alongside the media*, so one array failure takes both. What is in there is not
  reproducible: Authentik's whole identity provider, the BookStack wiki, ABS listening progress,
  the connector DB, Radarr's 62 custom formats and two TRaSH profiles, and the cloudflared tunnel
  credentials. A run is **~109 MB** and retention is 7, so the entire tree is **under 1 GB** :
  cents per month on B2/R2. Restore discipline already exists and is tested; only the off-host leg
  is missing. **Needs: a B2 or R2 key.** See *Backups & Recovery*.
- ~~**Postmark SMTP token**~~ **SUPERSEDED 2026-08-17: the stack moved to SMTP2GO** (`avrana-mail` SMTP user; CWA, ABS and Authentik all send). Neither item below is blocked on an SMTP credential any more:
  - **CWA Send-to-Kindle.** Clean-title MIME patch DONE + verified (custom image, Cibola Burn →
    `Cibola Burn.epub`); ingest pipeline on. Remaining: enter the token + verified sender in
    Admin → Email Server Settings, add the sender to Amazon's approved list, set a `@kindle.com`,
    then one real test send.
  - ~~**Self-service password recovery**~~ **DONE: verified 2026-08-17.** The `avrana-recovery`
    flow exists (identification -> email -> prompt -> write) and the brand's `flow_recovery` is set,
    so this no longer blocks on an SMTP credential. **Not yet verified:** a real end-to-end reset in
    a browser, and whether a reset propagates to the separate Jellyfin credential copy: if it does
    not, Cody is still the reset service for Jellyfin specifically.
- **Rotate three credentials that passed through a chat transcript**: the SMTP2GO API key (no
  longer used by anything; CWA, ABS and Authentik all use the `avrana-mail` SMTP user), and the
  **Komga admin password**, which lives in `services/komf/config/application.yml` AND is used by
  the enrollment policy, so rotating means updating both and re-applying the enrollment blueprint.
- **Komga accounts are not backfilled**: members who enrolled before 2026-08-17 have no Komga
  account, and their Avrana password is hashed so it cannot be replicated retroactively. Either
  they set a Komga password once, or a small backfill tool creates accounts with a generated
  password. Affects Andrewdean, Collinyourmom, DeaW, Monkey, Tdogteeth, Test123.
- ~~**Komga per-user library scoping**~~ **CLOSED 2026-08-17, not needed.** Cody is happy for
  every member to see every library; the requirement is read-only, and that was verified:
  a normal account gets 403 on every write including self-promotion to ADMIN, while reads
  and its own read progress work. See *Komga*.
- **Send-to-Kindle needs the Amazon side**: add `cody@avrana.net` to the Approved Personal
  Document E-mail List, and supply a `@kindle.com` address for a real end-to-end test send.
  SMTP delivery itself is proven.
- **Assign titles to the new Recyclarr profiles**: `UHD Bluray + WEB` and `Remux + WEB 2160p` exist
  but **nothing is assigned to them**, deliberately. Assigning is what makes a title upgrade-eligible,
  and indexer RSS + automatic search are both on, so expect grabs. Do the controlled end-to-end test
  first. See *Radarr / Sonarr*.
- **Plex retirement**: confirm authorization before stopping `plexmediaserver.service`.
- **Cloudflare "Always Use HTTPS"**: prevents `http` OIDC scheme mismatches. Needs the Cloudflare
  dashboard; there is no CF API token on this host.
- **Global Docker daemon log rotation**: needs interactive sudo. Per-container rotation covers it.

### Ready to build (no blocker)

- **Revert to the premium Radarr/Sonarr profiles once transcoding hardware exists**: the
  `Avrana Compatible - 4K SDR` profiles (Radarr 10, Sonarr 9) are a **workaround for a hardware
  limit, not a preference**: this host cannot hardware-decode 10-bit HEVC, so one 4K HDR stream
  pins the CPU. The pre-existing premium profiles (`UHD Bluray + WEB`, `Remux + WEB 2160p` with
  IMAX, `Avrana TV - 1080p/4K`) are **preserved, not deleted**, and the exact revert steps are
  written down. Trigger is either a better client (Shield / Apple TV 4K, ~$200, fixes ~10 of the
  12 incompatible titles) or a newer iGPU/GPU host. See
  [Radarr / Sonarr](http://10.0.0.218:6875/books/services/page/radarr-sonarr) and
  [Jellyfin](http://10.0.0.218:6875/books/services/page/jellyfin).
- **Radarr still boosts HDR10+** (`[HDR Formats] HDR10+ Boost`) on the two premium profiles: the
  exact range the main TV rejects. Harmless while those profiles are opt-in; remove it if they
  become the default again before the hardware changes.


- ~~**Automated offboarding**~~ **BUILT: `scripts/offboard.py`, used in anger 2026-08-17.**
  Dry-run by default, `--purge` to delete, `--audit` for a cross-system report, protected accounts
  refused. A silent-failure bug was fixed the same day (commit `1be9a12`): the Authentik delete ran
  raw SQL that postgres refuses whenever the user is in a group, and reported success anyway: it
  now deletes through Django's ORM and reports FAILED if the row survives. **Two known limits:** it
  cannot act on Komga, and it matches ABS by email, so accounts sharing an address all match.
  Original rationale, still true: **deleting an Authentik user does NOT offboard them.** Jellyfin keeps a replicated
  password, so the account stays loginable until deleted separately; a stale ABS record is also left.
  The manual steps are documented and proven, but they are manual and easy to half-complete under
  time pressure: which is exactly when someone leaves. Also covers token/API-key revocation and
  Jellyfin returning-user reconciliation.
- **"IMAX Priority" quality profile: designed and simulated, not built.** Verified 2026-08-16
  that Radarr sorts by **quality tier first**, so the +800 IMAX bonus can never cross a tier: a
  non-IMAX Blu-ray beat an IMAX Enhanced WEB-DL even when the Blu-ray carried a **-10000** LQ
  penalty. To make IMAX decisive needs BOTH (a) all three 2160p qualities in **one quality group**
  so tier stops dominating, and (b) IMAX / IMAX Enhanced raised to **+10000**: grouping alone was
  simulated and does **not** work. At +10000 every IMAX release outranks every non-IMAX one *and*
  the IMAX Remux still beats the IMAX WEB-DL. Deliberately opt-in per title: it trades bitrate for
  framing. See *Radarr / Sonarr*.
- **Kavita**: repoint its compose at the array before starting.
- **Complete Series (:8085)**: run it to find series missing books (fill via Shelfmark/Libation),
  **and** decide whether to keep it deployed long-term.
- **mylar3 patch**: recover the patch specifics and document them.

### OliveTin follow-ups (deferred on purpose, 2026-08-17)

The console is live internally and fully tested. These were each considered and consciously left
out rather than forgotten:

- **Media-permissions repair**: deferred. No safe existing script to wrap, and a permissions
  fixer is exactly the kind of thing that should not be invented behind a one-click button.
- **Wake-on-LAN**: deferred until a second compute node exists. Nothing to wake.
- **Audible import retry**: the connector exposes no safe, idempotent single-shot retry
  interface, so none was invented. Revisit if one is added. See *Audible Sync Connector*.
- **SABnzbd cannot be in the restart allowlist**: it is a **host systemd service, not a
  container**, so a Docker restart wrapper cannot reach it. Restarting it would need a separate
  mechanism with its own privilege question. Currently omitted entirely.
- **Bazarr is absent from the restart allowlist** because it is not deployed. Add it to
  both `ALLOWED` in `scripts/restart-service.sh` **and** the `choices` block in
  `config/config.yaml` when it lands.
- **Restore is not, and should not become, a button.** Destructive, needs judgement about which
  run and which components, belongs in a terminal with the runbook open.
- **Control-plane services are excluded from restarts on purpose**: Authentik, the socket
  proxies, OliveTin itself, BookStack + MariaDB, Homepage, cloudflared. Restarting the thing that
  authenticates the button is how you lock yourself out.

### Shelved (planned, deliberately not started)

- **Bazarr: PLANNED, SHELVED 2026-08-16 (not deployed).** Verified absen: no container, image,
  config dir, unit, or listener on 6767. Subtitle automation for Radarr + Sonarr, English **full +
  forced** SRT. Design decisions already settled, so this can be resumed without re-deriving:
  - **Bazarr has no Jellyfin connector.** It syncs its library from Radarr/Sonarr and writes `.srt`
    sidecars next to the media; Jellyfin just discovers them on scan. Nothing to configure on the
    Jellyfin side. Jellyfin's `SkipSubtitlesIfEmbeddedSubtitlesPresent=false` and
    `RequirePerfectSubtitleMatch=true` are already compatible with Bazarr's `<media>.en.srt` /
    `<media>.en.forced.srt` naming.
  - **Mount ONLY `/mnt/avrana_media/movies` and `/mnt/avrana_media/tv` (rw), never the array root** :
    the root would re-expose `/data/.backups` (Authentik `pg_dump`, `APP_KEY`, service secrets) to an
    internet-facing service. The EXDEV single-mount constraint that binds the \*arr does **not** apply:
    Bazarr writes sidecars beside the media and needs no hardlinks. Paths must match what Radarr and
    Sonarr report (`/data/movies`, `/data/tv`) or Bazarr cannot locate files.
  - **Jellyfin stays read-only.** This supersedes the "installing a subtitle fetcher means making
    Jellyfin's mounts writable again" note in *Docker Hardening & Networking*: Bazarr is the writer,
    in its own container; Jellyfin only reads.
  - LAN-only on `10.0.0.218:6767` (no Authentik integration, so it must not be tunneled), joins
    `docker_arr-core` only, digest-pinned `ghcr.io/linuxserver/bazarr`, house hardening baseline.
    `read_only: true` needs validating: LinuxServer images usually want writable `/run` and `/tmp`.
  - **Open decisions before building:** which subtitle providers (OpenSubtitles.com needs an account);
    deploy with scheduled search **disabled** so first sync does not fetch for the whole library; and
    extend `backup_arr` + `restore-test.sh` to cover `bazarr.db`, or it repeats the gap just closed.
  - Sequencing note: Radarr renaming is now on but the existing 21 files are unrenamed. Rename first,
    then let Bazarr populate, to avoid churning sidecars.


## Product & Platform Roadmap

1. **Avrana Portal v1**: **LIVE 2026-08-16** at `avrana.net`, gated by Authentik's embedded proxy outpost, rendering only the tiles a user's groups permit (`services/avrana-portal/`). **Slice 2 also done:** single-domain routes `/watch`, `/listen`, `/comics`, `/books`, `/requests`, `/contribute` (aliases `/read`, `/request`), each gated on the same group as its tile and then redirecting to the service's own hostname, plus an `/account` page showing identity and granted services with links to Authentik for password, MFA and sign-out. A missing group returns **404, not 403**, so nothing hints at services a user does not have. Service subdomains stay for native clients. **Still open:** preferences beyond what Authentik owns. See *Avrana Portal: avrana.net*.
2. **Identity lifecycle cleanup**: granular invite/access classes, permission changes, complete
   offboarding, token/API-key revocation, and Jellyfin password / returning-user reconciliation.
3. **Unified catalog & metadata layer**: ingest Jellyfin, Audiobookshelf, Komga, and CWA
   catalogs; pick metadata authorities per medium (especially CWA); normalize ISBN, ASIN, TMDB,
   comic IDs, editions, and adaptations.
4. **Discover v1**: cross-media browse/search with availability status and Play / Listen / Read /
   Request actions routed to the right service.
5. **Client handoff / deep links**: open the exact item in Jellyfin, AudioBooth, Komga clients,
   CWA, or Kindle. Do it through the portal/PWA before considering a native app.
6. **History, ratings & reviews**: prototype Ryot (or equivalent) as the canonical backend;
   import progress/history; support Avrana ratings, reviews, and community scores, with write-back
   where APIs permit.
7. **Social recommendations**: recommend a title with a note to one person, a group, or everyone;
   private activity feed + visibility controls.
8. **Notification system**: Postmark for account mail; personal push for approvals/availability/
   recommendations; Discord for shared-library activity; per-user preferences, no ntfy requirement.
9. **Contributor controls**: Audible one-time vs continuous sync, per-title selection, visible
   status, reconnect/disconnect, and credential/data removal.
10. **Security & operations completion**: container-hardening audit, service dependency /
    public-exposure topology, alerting, encrypted off-host backup, and a verified restore drill.

## Blocked / Watchlist

- **Seerr real OIDC**: blocked upstream (PR `seerr-team/seerr#2715` unmerged); only an
  experimental `preview-new-oidc` image exists. Recheck the PR before attempting. Currently rides
  on Jellyfin credential replication.

## Later

- **VLAN/DMZ / host firewall**: deliberately deferred (Jellyfin still on host networking); a
  separate disruptive project needing design approval.
- **Letterboxd & Goodreads imports.**
- **Spotify history / audiobook data.**
- **AI / embedding recommendations + self-hosted LLM integration.**
- **Immich user quotas.**
- **Full native Avrana companion app / App Store release.**

## Done

**Onboarding + offboarding beta: HUMAN-TESTED 2026-08-15.** A real invitee (`Tdogteeth`)
went invite → enrollment → correct app visibility → app login, and the precreate-but-disabled
Jellyfin path worked in production. Offboarding was manually verified (a test account removed from
all six systems, shared media intact): which is also how the gap now tracked under *Automated
offboarding* was found. See *Authentik & SSO* and *Member Onboarding*.

**Done 2026-08-17:** **OliveTin operations console** built and verified (27/27 tests) - admin-only,
default-deny, behind Authentik's embedded outpost, with a **two-proxy Docker model that avoids
root-equivalent access** (`ALLOW_RESTARTS=1` with `CONTAINERS=0`, so `/containers/create` and
`/exec` stay denied) and a **file-trigger backup button** rather than `docker exec`; the backup
trigger path unit is enabled and the button was proven end to end against the real
`avrana-backup.service`. **Radarr/Sonarr/Prowlarr added to the backup** with restore verification.
**Encrypted off-host backup built** (awaiting a key). **Admin-only Operations tile** on the portal.
Roadmap triaged into Blocked / Ready / Shelved.

**Done 2026-08-16:** **Avrana Portal v1 live** (role-aware front door + single-domain routes +
`/account`); **media containers can no longer read or delete the backup tree** (tmpfs shadow for the
\\*arr, narrowed read-only mounts for Jellyfin/Komga); **cloudflared config + tunnel credentials
added to the backup**; **Audible Connector restyled** to the portal look with the first-person voice
removed, plus a stylesheet cache-bust so restyles actually reach the public URL; **Jellyfin's
published-URL setting fixed** (was an unparseable bare `http://watch.avrana.com`, a silent no-op);
**enrollment now redirects finished invitees to the portal**; **Recyclarr deployed** with two TRaSH
profiles, IMAX preferences and an HDR safeguard; **Seerr's default movie profile moved** to
`UHD Bluray + WEB`, resolved by name; **Radarr + Sonarr recycle bins** on the array with 30-day
retention; and **Radarr/Sonarr/Prowlarr added to the backup** with restore verification.

**Done 2026-08-15:** **epub↔audiobook matcher built** (`scripts/epub_audiobook_matcher.py`, ID/exact/prefix tiers, hard-links, dry-run+idempotent, 9 tests): links owned EPUBs into audiobook folders for the ABS Read button (also flipped ABS `audiobooksOnly=false`; see *Pipelines*). CWA metadata → **Hardcover primary, Kobo fallback** (token via gitignored
`.env`, reused from Shelfmark); CWA **clean-title Kindle patch** built + locally verified (custom
image, awaiting Postmark for a real send); **Homepage Calibre-Web widget fixed** (local-account
OPDS/API auth restored in LDAP mode: the "API Error Info" bug); **OPDS speedup** via LDAP
`cached` mode (~3 s → ~5 ms/request); CWA default-role fix (LDAP users can read/download).

**Audible Connector hardening: DONE 2026-08-14:** *Auto* first-connect baseline (`baselined`
flag), companion jobs persist to SQLite + reconcile `running`→interrupted on restart, base images
digest-pinned. Connector is production-solid. See *Audible Sync Connector*.

**Done 2026-08-14:** Komga OIDC SSO; Calibre-Web LDAP SSO + public `books.avrana.net`; **CWA
default admin password rotated** (was `admin123`); Authentik invite-enrollment flow (one invite →
all apps); Jellyfin/Seerr credential replication at enrollment; Audible Sync Connector built, then
**live-proven against a real account** (56 books imported; five real bugs + a "session not found"
onboarding trap fixed: see *Audible Sync Connector*); `contribute.avrana.net` +
`books.avrana.net` tunnels; whole SSO story documented in *Authentik & SSO*; **exposed reusable
invite revoked**; **automated whole-stack backups with a tested ABS restore** (see *Backups &
Recovery*): closes the long-standing "enable ABS auto-backups" top item.

**Done 2026-08-13:** second Audible account added + library liberated (196/212); Libation OOM
fixed; `libation-status` widget; ABS mobile SSO verified; BookStack stood up.

---

## Where Avrana sits in the larger project

Avrana is the **media subsystem** of a larger umbrella called **Kern**. Kern is planned, not
built; Avrana is the running part and keeps its own name and documentation.

Architecture, boundaries and roadmap for the wider project live on the separate
[Kern shelf](http://10.0.0.218:6875/shelves/kern). Relevant here: **Avrana stabilises first** :
Kern does not gain authority over it until the items on this page are closed.


### Open after the 2026-08-19 compatibility swap

- **Supergirl and Transformers One never swapped**: every candidate failed with
  `Aborted, cannot be completed`, and each automatic retry picked a **DV** release. Both still
  carry the original DV files and remain Tier 1 transcode triggers. Needs a hand-picked release
  when better ones appear.
- **Decide whether `Avrana Compatible` should permit DV at all.** DV scores −5000 against
  `min_format_score` −6000, so automatic and failed-redownload searches can select DV even though
  the manual selection filtered it out. Either drop DV below −6000 or turn off
  `autoRedownloadFailedFromInteractiveSearch`. See
  [Radarr / Sonarr](http://10.0.0.218:6875/books/services/page/radarr-sonarr).
- **The Dark Knight Rises lost ~55 min of measured IMAX expanded framing** in the swap; the 4K
  original is recoverable from the recycle bin until ~2026-09-18. Decide: restore, re-grab an IMAX
  release, or accept the 1080p.
- **IMAX verifier classifier fix**: AR-based shares swing 26 points with sample count while the
  height-based reading is stable. Threshold is 10%. See
  [IMAX framing verification](http://10.0.0.218:6875/books/services/page/imax-framing-verification).
- **Jellyfin: test `EnableIntelLowPowerH264HwEncoder`** (biggest remaining CPU win) and
  **`KnownProxies`** (root cause of every client appearing as 127.0.0.1, which is why
  `RemoteClientBitrateLimit` is inert). Both need a deliberate test window. See
  [Jellyfin](http://10.0.0.218:6875/books/services/page/jellyfin).
- **Verify the Tier 3 client-profile theory.** Supergirl / The Invite / Avatar Aang /
  Mandalorian & Grogu were DV Profile 8 with clean HDR10 fallback: if they were transcoding, it
  was likely the Roku client profile, not the files. Confirm with Jellyfin's `PlaybackInfo`.
- **SABnzbd 4.2.2 has an unpatched `save_data` race** that can wedge the whole queue under
  concurrent load with heavy article loss. Recovery is to remove the stuck job, not to restart.


### Security audit action items (2026-08-20)

Full findings: [Security audit, 2026-08-20](http://10.0.0.218:6875/books/runbook/page/security-audit-2026-08-20).
Radarr auth and Jellyfin `KnownProxies` were fixed during the audit. Everything below needs Cody.

- ~~**FIRST: `sudo ufw status verbose`.**~~ **Answered 2026-08-28 — and it does not help.**
  `/etc/ufw/ufw.conf` has **`ENABLED=no`** while `ufw.service` reports `active (enabled)`; that
  combination starts the unit but installs no rules. ufw is **not** filtering the LAN, so the
  Critical items below do **not** drop to Medium. *(The live nftables ruleset still could not be
  read without sudo, so confirm with `sudo ufw status verbose`.)* **Turning ufw on is a firewall
  change and is awaiting Cody's approval — it is not safe to enable blind, because a default-deny
  with no allow rules would cut SSH and every LAN service at once.**
- ~~**CRITICAL, SABnzbd has no login.**~~ **DONE 2026-08-28.** Username and password set via
  SABnzbd's own `set_config` API (live, no root, no restart). Anonymous `/config/` and
  `/config/switches/` now 303 to `/login/`. `api_key`/`nzb_key` byte-identical, so Radarr,
  Sonarr, Prowlarr, Shelfmark and Homepage were unaffected — all five re-tested and pass.
  Credentials in `services/bare-metal-auth.env` (mode 600).
- **CRITICAL, mylar3 has authentication disabled.** `authentication = 0` on `0.0.0.0:8090`, also
  running as `cody`. Set `authentication = 1` with credentials, then
  `sudo systemctl restart mylar3`. Do not rebind it to loopback: it is a system unit and Homepage's
  widget reaches it over the LAN address.
- **Restart Jellyfin** to activate the `KnownProxies` fix. It is written to `network.xml` but
  Jellyfin only reads network config at startup, so until then every client still appears as
  `127.0.0.1`.
- **Off-host backups.** Unchanged and still the only unrecoverable risk. Needs a B2 or R2 key.
- **Reboot** for the pending security update, **remove** the dead
  `/etc/nginx/sites-enabled/homeassistant` site (502 to a libvirt VM that no longer exists), and
  **stop Plex** (`*:32400`, still awaiting authorization).
- **Decisions, not tasks:** `cody` holds `docker`, `lxd` and `libvirt`, each root-equivalent and
  each turning any RCE as `cody` into host compromise. ~~The health API on `0.0.0.0:8240`~~ —
  **retired 2026-08-28, H1 closed.** The "every fix breaks the phone's health export" premise was
  wrong: the last genuine POST was 2025-09-18 and the parser had been missing for ~14 months.


### TV / Sonarr, after the 2026-08-20 pre-HD work

- **Aladdin and House of Mouse are still on `Avrana Compatible` (9), and should move to
  `Avrana Legacy` (10).** Both are complete right now only because every episode was grabbed by
  hand. If either ever needs another episode, profile 9 will reject anything under 1080p exactly as
  it did originally. Moving them changes nothing on disk.
- **Mark Aladdin available in Seerr by hand.** It will otherwise show "processing" forever: Sonarr
  organises by TVDB (S1=65, S2=13, S3=8) and Seerr checks TMDB (S1=9, S2=69, S3=8). Nothing is
  missing. See [Radarr / Sonarr](http://10.0.0.218:6875/books/services/page/radarr-sonarr).
- **Ted Lasso is 3/53** on stock profile 4. A 2020 show, so this is NOT the pre-HD problem.
  Unexplained and the largest gap in the TV library.
- **Consider a second indexer.** There is exactly one, NZBgeek, Usenet only. That is why
  The Legend of Tarzan had no English copy at all and was deleted. Old cartoons are precisely where
  a single Usenet indexer is weakest. Torrent support would need a client container, which is new
  attack surface (see the security audit).
- **Stalled-request alerting is not built.** Sonarr has no event for "searched and found nothing
  acceptable", so no notification can cover it. A periodic check (monitored, added > N hours, zero
  files, nothing queued) belongs in `scripts/services-health.sh`, delivered over SMTP2GO. Key it on
  **Sonarr** file counts, never Seerr status.
- **`Avrana Legacy` blind spot:** it mis-picks Spanish rips tagged `[English, Spanish]` (4 episodes
  of House of Mouse). Fixing it needs a hand-made custom format and
  `reset_unmatched_scores: false` on that profile.

### Shelfarr (deployed 2026-08-20, setup incomplete)

Full page: [Shelfarr](http://10.0.0.218:6875/books/services/page/shelfarr). Container is healthy at
`http://10.0.0.218:5056`, LAN only, backed up. **Not yet usable** -- needs a one-time admin pass:

- **Create the first account** at `/sign_up` (becomes admin), then enter Prowlarr and
  Audiobookshelf credentials in Admin -> Settings, and **add SABnzbd as a download client**. None
  of those are env-settable; only `oidc_*`/`webhook_*` are. Credentials are staged in
  `services/shelfarr/.env`.
- **Decide on OIDC.** Supported, but the callback would be plaintext
  `http://10.0.0.218:5056/auth/oidc/callback`, the same pattern recorded as finding M1 in the
  security audit. Left unconfigured rather than repeating it silently.
- **Shelfmark stays in service** pending evaluation. Both write to the same inboxes, so a title
  requested in both is fetched twice.
- **"QuarterMaster" could not be identified.** The deployment brief asked for Shelfarr to be
  "reachable in the manner required for QuarterMaster"; that name appears nowhere in the repo,
  memory, this wiki, or the running stack. Defaulted to LAN-only.
- Upstream is **v0.1.0**. Pinned by tag and digest; `latest` is already ahead of it.

> **Docker's root dir is `/mnt/avrana_media/docker`,** so every container's writable layer lives on
> the media array. A trivial recursive chown in Shelfarr's entrypoint drove `sdb` to 99% at
> 0.1 MB/s and looked exactly like a failing disk. Worth knowing before diagnosing the next one.

### Kern Tablet (SM-T510) desk companion

Proposed sub-project, nothing built. Full plan:
[Kern Tablet: SM-T510 desk companion](http://10.0.0.218:6875/books/kern-roadmap-and-infrastructure/page/kern-tablet-sm-t510-desk-companion).

Avrana-side items it depends on:

- **Stuttering Jellyfin playback on the SM-T510 is unresolved and blocking.** Direct Play is
  reported, so this is not obviously the known transcoding problem. Next step is offline playback
  of a fully downloaded file in standalone MPV with airplane mode on, to take the network out of
  the experiment entirely. Do not attribute it to Cloudflare until that has been run.
- The tablet interface will consume Jellyfin, Avrana service health and Home Assistant through a
  **backend that holds the credentials**. No API keys reach the tablet browser.

## Status deltas, 2026-08-28

Verified against the live host. Only items whose **state changed** are listed; everything else on
this page was re-checked and still stands.

**Closed**

- **mergerfs / `daemon-reload`** — done, see above. Docker now orders after the union mount.
- **The dormant `haos` VM** — deleted, ~12 GB reclaimed from the root filesystem. Home Assistant
  was already the container; the VM had been shut off and superseded.

**Still open after 8 days — the three security items are unchanged**

- **SABnzbd still has no login** (`username = ""`; `/config/` returns 200 unauthenticated). It has
  **moved to `:8082`**, so the remediation instruction on the security-audit page points at the
  wrong port.
- ~~**mylar3 authentication is still disabled**~~ **DONE 2026-08-28** — `authentication = 2`
  (forms login; `/api` stays exempt so Homepage's key still works). Restarted via Mylar's own
  `cmd=restart`, which re-execs in place, so no root was needed.
- ~~**The health API is still unauthenticated** on `0.0.0.0:8240`.~~ **Closed 2026-08-28 — retired entirely.** Nothing listens on 8240; the `health.avrana.media` connector is gone. See *Services → Health API*.
- ~~**`sudo ufw status verbose` has still not been run.**~~ **Answered 2026-08-28: `ufw.conf`
  has `ENABLED=no`, so ufw installs no rules despite the unit reading `active`.** A **complete
  two-layer design now exists and is staged but NOT applied** — `deploy/ufw/` (commit
  `4db6c17`) and *Infrastructure → Host firewall (ufw)*. ufw/INPUT covers the bare-metal
  services; `DOCKER-USER` covers the ~22 container ports that ufw structurally cannot touch.
  Rollback is three nets: immediate verification, a deadman timer (`AccuracySec=1s` — the
  systemd default of 1min was measured firing late), and a verbatim `iptables-save` snapshot.
  **Apply only after the Docker address-pool migration completes**; the apply script refuses
  to run before it.
- **Reboot still pending** — now 9 days outstanding and covering `libc6` plus kernels 137 and 138
  (running 136). Uptime is 32 days, which also means the boot path has **not** been exercised
  since the mergerfs union, the Docker ordering fix, three new services and UniFi OS Server were
  added. The reboot validates all of that at once.
- **Root LV still unextended** — ~58 GB of the SSD remains unallocated.
- **Off-host backup** — unchanged, still the only unrecoverable risk, still needs a B2/R2 key.
- **Plex still listening** on `*:32400`.

**New**

- **`default-address-pools` is still unset** and pressure is now real: **28 bridge networks** are
  in use, all attached, out of roughly 31 slots in Docker's default pools. `/etc/docker/daemon.json`
  contains **only** `data-root`. Roughly three more services and Compose starts failing to create
  networks.
- **Shelfarr is rate-limiting the shared Hardcover token.** Its `HealthCheckJob` produces ~3,600
  log lines a day of `Rate limit exceeded`. The JWT is shared with CWA and Shelfmark, so this is
  not confined to Shelfarr.
- **Backup grew to 14 components** (`beszel`, `shelfarr`, `omnibus` added) — see
  *Backups and Recovery*. **Home Assistant and Tracearr config remain uncaptured.**
- **UniFi OS Server is deployed** — see *UniFi OS Server* under Services. The abandoned Dockerised
  UniFi attempt was removed entirely.
- **13 systemd units are failed**, not 2 — see *Known Issues*. Root cause of the invisibility is
  that `services-health.sh` does not check `systemctl --failed`; adding that one check closes the
  whole class.
