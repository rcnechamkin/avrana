# Avrana Disaster-Recovery Tabletop

**Date:** 2026-08-30 · **Method:** paper exercise against the repository, the live host, the actual
backup artifacts on the array, and Git history.
**Mutations:** none. Read-only inspection only.
**Sources:** `docs/audits/2026-08-30-forensic-audit.md`,
`docs/audits/2026-08-30-forensic-audit-verification.md`.

Two components named in the brief do not exist in this stack and are not analysed further:
**QuarterMaster** has no container, service directory, unit or binary. **Caddy** is installed
(`/usr/bin/caddy`) but `caddy.service` and `caddy-api.service` are both **disabled**, and it carries
no configuration for Avrana. The real ingress is a single Cloudflare tunnel; `nginx` holds `:80`
locally with a dead upstream and is not part of the serving path.

---

## SCENARIO A — DISASTER TODAY

### A.0 The first blocking dependency

**There is no off-host copy of anything.** `OFFHOST_LAST_RUN.json` does not exist,
`avrana-offhost.timer` is not installed, and `services/backups/rclone.conf` has never been created.
Every byte of `/mnt/avrana_media/.backups` dies with the array it sits on.

So the recovery chain does not begin at "download the backup". It begins at "clone the Git
repository", and everything that is not in Git is gone.

### A.1 What survives

**Git (`origin/main`, GitHub, private).** This is the entire surviving technical estate:

- 22 tracked `docker-compose.yml` files, plus `deploy/compose/{komga,komf}.yml` mirroring the two
  that are gitignored.
- `deploy/` in full: the `ufw` design, the Docker recovery scripts, `daemon.json.proposed`,
  `INCIDENT-2026-08-29.md`, and 11 systemd unit files.
- `scripts/`, including `services-health.sh` and `known-failed-units.txt`.
- All custom application source: `avrana-portal/portal.py`, `avrana-imax-verify/`,
  `avrana-kindle-connector/kindle.py`, the whole Audible connector including its 11 test files, and
  the CWA build patch.
- `CLAUDE.md`, `docs/`, `bin/bs`, three Dockerfiles.
- The legacy Kern Prime tree.

**External providers (accounts, not data).** Cloudflare (DNS and the ability to create a new
tunnel), Backblaze/Cloudflare R2, GitHub, Amazon/Audible, Newshosting, NZBgeek, NZBFinder, SMTP2GO,
Hardcover.

### A.2 What is permanently lost

Everything below existed only on the destroyed hardware. No copy exists in Git, off-host, or at any
provider.

| Artifact | Consequence |
|---|---|
| **Authentik Postgres** (users, groups, applications, OIDC providers and client secrets, invite flows, enrollment blueprints state) | Every account gone. The identity provider is rebuilt from scratch and every member re-enrolls. |
| **Jellyfin `data/jellyfin.db`** | Users, the replicated password store, watch history, resume positions, library setup. |
| **Audiobookshelf `absdatabase.sqlite` + metadata** | 293 library items, 8 users, all listening progress, manual metadata edits, the `allowedOrigins` whitelist. |
| **Komga `database.sqlite`** | Series, read progress, the 8 read lists, users. |
| **Calibre-Web `app.db` / `cwa.db` / `calibre-metadata.db`** | Users, settings, the ebook catalogue index. |
| **Seerr `db.sqlite3` + `settings.json`** | Request history, user mapping, routing rules. |
| **Radarr / Sonarr / Prowlarr databases + `config.xml`** | 10 quality profiles, **70 custom formats**, 62 movies, 12 series, both indexer definitions with their API keys, and all three API keys. This is the single largest body of hand-tuned configuration in the stack. |
| **BookStack MariaDB + `APP_KEY` + uploads** | 65 pages across 11 books. **The wiki that documents how to rebuild everything above dies with it.** |
| **Home Assistant `config/.storage`** | Auth store, device and entity registries, and the **ESPHome pairing key for the Voice PE puck**, which cannot be regenerated without re-provisioning the hardware. |
| **Tracearr Postgres**, **Shelfarr**, **Omnibus**, **Beszel**, **connector.db** | All service state. |
| **Cloudflared tunnel credentials, `cert.pem`, ingress `config.yml`** | The tunnel identity and the public-hostname to local-service map. |
| **All 12 service `.env` files, `services/*/secrets/`** | Every service secret, including the connector's `oidc_client_secret`, `session_key` and `companion_token`. |
| **`~/.sabnzbd/sabnzbd.ini`** | API key, LAN credentials, the `news.newshosting.com` server block, categories, post-processing wiring. |
| **`services/mylar3/`** (fully gitignored) | `mylar.db`, `config.ini`, and the local patch that BookStack says must be re-applied after every upgrade but whose specifics were never recorded. |
| **`services/bare-metal-auth.env`, `services/smtp2go.env`** | SABnzbd/mylar3 logins and SMTP credentials. |
| **`services/libation/config/`** | `libation-master.key`, `AccountsSettings.json` (encrypted Audible tokens), `LibationContext.db`. |
| **`services/shelfmark/config/`** | `users.db`, `settings.json`, `.flask_secret`. |
| **`services/calibre-web-automated/config/.key`** | The Fernet key for CWA's stored SMTP password. |
| **`services/komf/` config** | `application.yml`, which holds the Komga admin password. |
| **~2.6 TB of media** | See A.3. |
| **Docker images, volumes, every container writable layer** | Rebuilt from registries; the two locally built images rebuild from Git. |

### A.3 Media, honestly

Media is deliberately excluded from backup, and BookStack calls it "re-obtainable". That is true
unevenly:

- **Movies and TV:** re-acquirable through Radarr/Sonarr, *if* the profiles are rebuilt by hand and
  *if* Usenet retention still covers the titles. 70 custom formats and the IMAX work are gone, so
  what returns will not match what was there.
- **Audiobooks:** re-downloadable through Libation, but only after re-authenticating to Audible,
  because `libation-master.key` is gone and the stored tokens are undecryptable without it.
- **Comics (~134 GB):** effectively **not** recoverable. Mylar3's only download path is documented
  as dead, with zero comics added in 30+ days, and `mylar.db` recording what was held is gone.
- **Ebooks:** the Calibre library files are on the array. `metadata.db` is gone with them. Not
  systematically re-obtainable.

### A.4 Scenario A verdict

**Avrana cannot be rebuilt. It can only be rebuilt-as-a-new-system that resembles Avrana.**

What Git gives is the *shape*: every compose file, every custom application, the hardening posture,
the deploy tooling, the operational documentation. A competent operator could stand up a structurally
identical stack.

What is unrecoverable is everything that made it *this* installation: the identities, the accounts,
the tuned automation, the reading and listening progress, the request history, and the wiki
recording why each decision was made. The correct label is **catastrophic, partial reconstruction**.

Time to a structurally similar stack: days. Time to the same stack: never.

---

## SCENARIO B — AFTER TASKS 1 AND 3 PLUS ONE VERIFIED OFF-HOST SYNC

Assumed: the bare-metal gap (N1) is closed, the stale restore-test assertion (C1) is fixed, a
nightly run completed, `restore-test.sh` exited 0 on it, and `offhost-sync.sh` copied that exact run
to encrypted object storage.

### B.1 Attempting to falsify sufficiency

Task 1 as scoped adds `services/*.env`, `~/.sabnzbd/sabnzbd.ini` and `services/mylar3/config.ini`.
That closes the finding as written. It does **not** close the rebuild. Five artifacts were found on
disk that a real recovery needs and that neither the current backup nor Task 1 captures:

| Artifact | Size / mode | Why it matters | Fixed by Task 1? |
|---|---|---|---|
| `services/calibre-web-automated/config/.key` | 44 B | Fernet key for the SMTP password inside `app.db`. Restored without it, CWA's stored mail credential is undecryptable and Send-to-Kindle must be reconfigured. | **No** |
| `services/libation/config/libation-master.key` | 32 B, 0600 | Its own `NOTICE.txt` states: *"It will not decrypt tokens encrypted under a different machine's key."* Without it `AccountsSettings.json` is dead and Audible must be re-authenticated. | **No** |
| `services/libation/config/AccountsSettings.json` + `LibationContext.db` | 9.9 KB + 786 KB | Audible account binding and the record of what has been downloaded. | **No** |
| `services/shelfmark/config/users.db` + `settings.json` + `.flask_secret` | 344 KB | Shelfmark's user accounts and its Prowlarr/SABnzbd/Hardcover wiring. | **No** |
| `services/komf/application.yml` | — | Holds the Komga admin password, and `services/komf/` is fully gitignored. | **No** |
| `services/mylar3/mylar.db` | — | Task 1 covers `config.ini`; the comic database is separate. | Partially |

Twelve running services have **no backup component at all**: shelfmark, libation, libation-status,
completeseries, recyclarr, avrana-imax-verify, avrana-portal, avrana-kindle-connector, olivetin,
homepage, komf, kavita. Most are genuinely stateless and rebuild from Git. Three are not:
**shelfmark**, **libation** and **komf**.

**Verified as already sufficient**, contrary to what might be assumed: all **12** per-service `.env`
files are captured, `services/*/secrets/` is captured including the connector's three secret files,
Jellyfin's `data/jellyfin.db` **is** inside the config tar so users and watch history survive, and
Prowlarr's indexer API keys for both NZBgeek and NZBFinder live inside `prowlarr.db`, which is
captured.

### B.2 Bootstrap and circular dependencies

**The one that matters.** Reading the off-host backup requires `services/backups/rclone.conf`, which
holds both the object-store credentials and the two crypt passwords. That file is correctly **not**
in the backup: putting the decryption key inside the encrypted archive would defeat the encryption.
Confirmed absent from `stack-config.tar.zst`.

So the bootstrap chain is:

```
Backblaze account (survives, external)   -> new application key, freely re-issued
Two rclone crypt passwords               -> PASSWORD MANAGER ONLY
        |
        +-> reconstruct rclone.conf -> decrypt and download the backup
```

`offhost-setup.md` anticipates this exactly: *"Store the two crypt passwords in your password
manager, off this machine, before you finish. ... A backup you cannot decrypt is not a backup."*

**This is not a circular dependency, provided that instruction was followed.** If it was not, the
off-host copy is unreadable noise and Scenario B collapses into Scenario A with extra steps. It is
the highest-stakes single point in the entire plan, and it is a human process step, not a technical
control. Nothing in the system verifies it was done.

**No true circular dependencies were found.** Two near-misses worth naming:

- The Cloudflare tunnel credentials are *inside* the backup, but retrieving the backup needs only
  Backblaze plus the crypt passwords, not the tunnel. Not circular.
- Authentik gates every application, but restoring Authentik needs only its `pg_dump` and its
  `.env`, both in the backup, and is done over a local port before any SSO exists. Not circular.

**Documentation bootstrap.** BookStack is the recovery documentation *and* a restored component. In
Scenario B its dump is in the backup, but it cannot be read until MariaDB is running. The recovery
runbook must therefore live outside BookStack. It does: `CLAUDE.md`,
`services/backups/README.md`, `offhost-setup.md` and these audit files are all in Git. This works
today, and only because those files were written down.

### B.3 Credentials that must be restored *identically*, not merely replaced

| Credential | Captured? | If it differs |
|---|---|---|
| BookStack `APP_KEY` (`bookstack.env`) | yes | Encrypted DB fields unrecoverable |
| Omnibus `NEXTAUTH_SECRET` (`omnibus.env`) | yes | Upstream uses it as the DB encryption master key; `omnibus.db` becomes worthless |
| Shelfarr `.encryption_keys` + `.secret_key_base` | yes | `production.sqlite3` undecryptable |
| Authentik `SECRET_KEY` (`services/authentik/.env`) | yes | Sessions and signed tokens invalidated |
| Authentik OIDC client secrets ↔ each app's `.env` | both sides | Every SSO integration fails until re-paired by hand |
| Connector `session_key`, `oidc_client_secret`, `companion_token` | yes | Connector auth breaks |
| **CWA `.key`** | **no** | Stored SMTP password undecryptable |
| **Libation master key** | **no** | Audible tokens undecryptable |
| **uid/gid 1000** | documented in `CLAUDE.md` | Every bind mount and the entire backup tree mis-owned |

### B.4 Credentials requiring recreation even in Scenario B

- **Newshosting (Usenet provider) login.** In Scenario B `sabnzbd.ini` is captured, so the server
  block returns. But if the restore is to a genuinely new install the provider password should be
  re-fetched from the account rather than trusted from a file. Classification: external provider.
- **Backblaze application key.** Re-issued from the account; the old one need not survive.
- **Audible session.** Re-authenticated at Amazon unless the Libation key gap is closed.
- **Voice PE pairing**, only if the ESPHome key fails to restore. The key is captured and
  restore-test asserts it, so this should not be needed.

### B.5 Configuration existing only in human memory

- **The two rclone crypt passwords.** The whole plan rests on them.
- **The mylar3 local patch.** BookStack states it must be re-applied after every upgrade and that
  its specifics "need recovery". They were never written down. Not in Git, not in any backup.
- **Which physical device is which.** The Voice PE puck at `10.0.0.71`, the Amazon smart plug, and
  the two Alexa routines that must be created by hand because no API exists.
- **The Hardcover token's `Bearer` prefix trap**, the ABS `allowedOrigins` fix, and similar traps.
  These *are* written down, in BookStack, which is unavailable until Phase 5. They should be
  mirrored into Git.

### B.6 Scenario B verdict

**Substantially recoverable, but not fully, and the gap is narrow and cheap to close.**

Tasks 1 and 3 plus a verified off-host sync genuinely cross the line from "we have backups" to "we
can rebuild the system". Identity, all media-service state, the automation configuration, the
tunnel, the systemd layer and every service secret return. That is the difference between
catastrophe and a long weekend.

What remains broken after that rebuild: CWA cannot send mail until reconfigured, Libation must be
re-authenticated to Audible and loses its download ledger, Shelfmark loses every user account, komf
loses the Komga admin password, and mylar3 loses its comic database. None is fatal. All are
avoidable for roughly thirty lines of additional backup coverage.

**Media remains lost in Scenario B exactly as in Scenario A.** That is a deliberate, documented
decision, but it should be stated plainly in any recovery-time estimate: comics and ebooks in
particular are not systematically re-obtainable.

---

## C. Survival matrix

| Artifact | Scenario A | Scenario B | Authoritative source |
|---|---|---|---|
| Compose files, deploy tooling, custom app source | survives | survives | **Git** |
| `CLAUDE.md`, docs, audit reports | survives | survives | **Git** |
| Authentik Postgres | **LOST** | survives | off-host backup |
| Jellyfin users + watch history | **LOST** | survives | off-host backup |
| ABS DB + progress, Komga DB, Seerr DB | **LOST** | survives | off-host backup |
| Radarr/Sonarr/Prowlarr DBs + `config.xml` | **LOST** | survives | off-host backup |
| BookStack DB + `APP_KEY` + uploads | **LOST** | survives | off-host backup |
| Home Assistant `.storage` + ESPHome key | **LOST** | survives | off-host backup |
| Cloudflared tunnel credentials + ingress | **LOST** | survives | off-host backup |
| 12 service `.env` + `secrets/` | **LOST** | survives | off-host backup |
| systemd units, `fstab`, enablement | **LOST** | survives | off-host backup |
| `sabnzbd.ini`, `services/*.env`, mylar3 `config.ini` | **LOST** | survives (Task 1) | off-host backup |
| **CWA `.key`** | **LOST** | **LOST** | none |
| **Libation key + accounts + ledger** | **LOST** | **LOST** | none |
| **Shelfmark `users.db` + settings** | **LOST** | **LOST** | none |
| **komf `application.yml`** | **LOST** | **LOST** | none |
| **mylar3 `mylar.db`** | **LOST** | **LOST** | none |
| **mylar3 local patch** | **LOST** | **LOST** | human memory, already lost |
| rclone crypt passwords | n/a | required | **human / password manager** |
| Provider accounts, DNS | survives | survives | **external provider** |
| `daemon.json` | recreatable | recreatable | Git (`daemon.json.proposed`) |
| Media (~2.6 TB) | **LOST** | **LOST** | partially re-acquirable |

---

## D. Permanent-loss inventory

**Scenario A:** all service state, all identity, all secrets, all bare-metal configuration, the
wiki, and the media. Only Git survives.

**Scenario B:** CWA's mail key, Libation's Audible binding and ledger, Shelfmark's users, komf's
Komga admin password, mylar3's database and patch, and the media.

---

## E. Bootstrap and circular dependencies

1. **Crypt passwords (critical, unverified).** Off-host bytes are worthless without them, they live
   only in a password manager, and nothing in the system checks that they were ever stored.
2. **Documentation lives in the thing being restored.** Mitigated because the runbooks are in Git.
   Do not move them into BookStack.
3. **Compose plugin location.** The 2026-08-29 incident proved `docker compose` exists only under
   `/home/cody/.docker/cli-plugins`. A rebuild that installs it only for root, or only for `cody`,
   reproduces a fault that has already caused an outage.
4. **uid/gid must be 1000 before any restore.** If the first user on the new host is not 1000, every
   bind mount and the entire restored tree is mis-owned. This must happen in Phase 1, not be
   discovered in Phase 8.
5. **Authentik must precede every relying application**, and each app's `.env` must be restored from
   the *same* backup run so client secrets match on both sides.

---

## F. Dependency-aware rebuild procedure

Exit criteria are deliberately behavioural. A running container is never sufficient.

**Phase 0 — Credentials and bootstrap access.**
Retrieve the two crypt passwords from the password manager. Create a fresh Backblaze application
key. Reconstruct `rclone.conf` from `offhost-setup.md`. Download the newest verified run.
*Exit:* `sha256sum -c MANIFEST.txt` passes on the downloaded tree. **If the crypt passwords cannot
be produced, stop. Scenario B has become Scenario A.**

**Phase 1 — Blank host preparation.**
Ubuntu; create user `cody` with **uid and gid exactly 1000**; install docker-ce, the compose v2
plugin **for both `cody` and root**, `zstd`, `python3`, `mergerfs`, `rclone`. Add `cody` to `docker`.
*Exit:* `id cody` reports 1000:1000, and `docker compose version` succeeds as `cody` **and** as root.

**Phase 2 — Repository.**
`git clone https://github.com/rcnechamkin/Kern-Ecosystem.git /home/cody/avrana`.
*Exit:* `CLAUDE.md` is readable and `bin/bs` exists. Recovery instructions are now on hand.

**Phase 3 — Storage and filesystem layout.**
Attach and format replacement storage; mount at `/mnt/avrana_media`; restore `/etc/fstab` from
`systemd/fstab` including the mergerfs union line; `chown -R 1000:1000`. Recreate
`/home/cody/docker/` and the `docker-compose.yml` symlink to `services/media/docker-compose.yml`.
*Exit:* the array mounts on boot, the mergerfs union is present, and everything under it is owned
1000:1000.

**Phase 4 — Docker and host infrastructure.**
Write `/etc/docker/daemon.json` with `data-root: /mnt/avrana_media/docker` from
`deploy/docker/daemon.json.proposed`. Restore systemd units from the backup, `daemon-reload`, and
confirm `docker.service` orders `After=` the mergerfs mount.
*Exit:* `docker info | grep "Root Dir"` reports the array path, and `systemctl show docker.service -p
After` lists the union mount.

**Phase 5 — Databases and identity.**
Restore `services/authentik/.env` and the Postgres dump **first**. Then BookStack, including its
`APP_KEY` and uploads, so the wiki is readable for the rest of the rebuild.
*Exit:* an **existing** user authenticates against Authentik on its local port; the OIDC providers
and client secrets in the database match the values in the restored per-service `.env` files;
BookStack renders a page.

**Phase 6 — Proxy, tunnel and network exposure.**
Restore `~/.cloudflared` (credentials, `cert.pem`, ingress `config.yml`), start the tunnel. Leave
`ufw` disabled to match the current documented state rather than introducing an untested change
mid-recovery.
*Exit:* all 12 public hostnames resolve and answer; `avrana.net` returns the portal behind
Authentik; an existing user completes SSO end to end from outside the LAN.

**Phase 7 — Media acquisition pipeline.**
Restore `sabnzbd.ini` (Scenario B) and re-verify the Newshosting credentials against the provider
account. Restore Prowlarr, then Radarr and Sonarr, each with its `config.xml`. Re-point the download
client and confirm the API keys match on both sides.
*Exit:* `GET /api/v3/health` on Radarr **and** Sonarr returns an empty array; a real interactive
search returns results from both indexers; a test grab reaches SABnzbd, completes, and imports as a
**hardlink**, not a copy.

**Phase 8 — User-facing services.**
Jellyfin, Audiobookshelf, Komga, Calibre-Web, Seerr, Shelfmark, Omnibus, Shelfarr, Homepage, the
portal, the connectors.
*Exit:* an existing user signs in through SSO to Jellyfin, ABS and Komga and sees **preserved watch
position, listening progress and read progress**. Portal tiles render per group membership, and a
user lacking a group gets 404 rather than 403.

**Phase 9 — Kern HQ and auxiliary services.**
Restore Home Assistant config and recorder; verify the ESPHome key restored rather than re-pairing.
Bring up the wyoming containers, Tracearr, Beszel, OliveTin, recyclarr, imax-verify.
*Exit:* a spoken command to the Voice PE puck at `10.0.0.71` completes locally, with no cloud
dependency.

**Phase 10 — Monitoring and backup.**
Install `services-health.timer`, `avrana-backup.timer`, `avrana-offhost.timer`. Recreate
`rclone.conf`.
*Exit:* a **new** backup completes with `status: ok`, `restore-test.sh` exits **0** against it, and
`offhost-sync.sh` completes with its manifest round-trip verified. Recovery is not finished until
the new system can itself be recovered.

**Phase 11 — End-to-end validation.**
Run both operational chains in full:

```
request -> Seerr -> Radarr/Sonarr -> Prowlarr -> indexer -> SABnzbd
        -> filesystem -> hardlink import -> Jellyfin -> authenticated playback
```
```
user -> Cloudflare -> Authentik outpost -> portal (correct groups)
     -> application -> preserved user state
```

*Exit:* both complete for a real user with a real title, and `deploy/docker/verify-baseline.sh`
passes all 26 probes.

---

## G. False-green traps

Every one of these leaves `services-health.sh` fully green, because eleven of its thirteen checks
are liveness endpoints and two are bare root pages.

| Trap | Looks like | Actually |
|---|---|---|
| SABnzbd config not restored | Radarr/Sonarr `/ping` OK | Searches succeed, nothing ever downloads |
| Indexer backoff after a staged restore | all containers healthy | Sonarr dark for hours; only `/api/v3/health` shows it |
| Authentik restored, app `.env` from a different run | Authentik healthy, apps healthy | Every SSO login fails at the token exchange |
| Jellyfin restored, media absent | Jellyfin healthy, users present | Every library empty, every resume point orphaned |
| CWA restored without `.key` | CWA 200 on `/` | Send-to-Kindle fails at send time only |
| Libation restored without its master key | container running | Silently downloads nothing; no Audible session |
| Shelfmark restored from Git only | `/api/health` OK | Zero user accounts |
| Komga restored, mergerfs union not mounted | Komga healthy | Libraries empty, and an empty read list pegs a CPU core |
| Array mounted read-only | all containers healthy | Imports fail; backup aborts; only `/api/v3/health` and backup staleness reveal it |
| Backup runs `partial` for days | timer green, files present | Retention rotates away the last good run (finding C8) |

The single highest-value monitoring change for recovery confidence is adding `/api/v3/health` for
the three \*arr and a real probe for SABnzbd. Four of the ten rows above become visible immediately.

---

## H. Remaining gaps after the proposed remediation

After Tasks 1 and 3 plus a verified off-host sync, these remain:

1. CWA `.key`, Libation key/accounts/ledger, Shelfmark config, komf `application.yml`, mylar3
   `mylar.db` — none captured.
2. Nothing verifies the crypt passwords were ever stored off-machine.
3. The mylar3 patch exists nowhere.
4. Media is not backed up, and comics and ebooks are not realistically re-obtainable.
5. `restore-test.sh` will still assert nothing about Authentik or BookStack (verification finding
   C3 residue), so the two most consequential dumps stay unverified.
6. No alert transport, so a degraded backup depends on a human reading a journal.

---

## I. What "fully recoverable" should mean for Avrana

> Avrana is fully recoverable when, starting from a blank Linux machine, a Backblaze account, the
> Git remote, DNS ownership, and two passwords from a password manager, an operator following
> written instructions **that live outside BookStack** can reach a state where:
>
> 1. an **existing** user signs in through `avrana.net` with their original credentials and group
>    memberships;
> 2. that user's watch position, listening progress, read progress and request history are intact;
> 3. a **new** media request travels request → Seerr → \*arr → Prowlarr → indexer → SABnzbd →
>    hardlink import → Jellyfin playback without any credential being recreated by hand;
> 4. Kern HQ answers a spoken command locally, without re-pairing hardware;
> 5. the rebuilt system takes its own backup, that backup passes `restore-test.sh` with exit 0, and
>    it reaches the off-host remote with its manifest verified;
>
> and no step required a value that existed only on the destroyed machine.

Against that definition, Scenario A fails at (1). Scenario B satisfies (1), (2), (3) and (4), and
satisfies (5) only after the restore test is fixed. It fails the final clause on five artifacts.

---

## J. Minimal work to get there

1. **Extend the backup by roughly thirty lines** to add `backup_libation` (master key,
   `AccountsSettings.json`, `LibationContext.db`, `Settings.json`), `backup_shelfmark` (`users.db`,
   `settings.json`, `.flask_secret`), CWA's `.key` inside `backup_calibreweb`, komf's
   `application.yml`, and mylar3's `mylar.db`. All 0600. Fold this into Task 1 rather than treating
   it as a second project.
2. **Add restore-test assertions** for each, plus the Authentik and BookStack dump markers that
   verification finding C3 left open.
3. **Confirm out loud that the two crypt passwords are in the password manager**, and record in
   `offhost-setup.md` the date that was verified. This costs one minute and is the highest-stakes
   item in the plan.
4. **Write a one-page bootstrap card in Git** naming, in order: the Backblaze account, where the
   crypt passwords live, the Git URL, the uid/gid requirement, and the compose-plugin trap. It must
   be readable with no infrastructure running.
5. **Recover or delete the mylar3 patch.** It is either important, in which case it belongs in Git,
   or it is not, in which case the note should stop claiming it must be re-applied.
6. **Add `/api/v3/health` and a SABnzbd probe** to `services-health.sh`, which removes four
   false-green traps from the recovery path.

Items 1 through 4 are a single session's work and move Scenario B from "substantially recoverable"
to meeting the definition in section I.
