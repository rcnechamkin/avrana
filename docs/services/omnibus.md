# Omnibus — comic discovery and requests

> Promoted from the BookStack wiki on 2026-10-04 (page 71, "Omnibus", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/71-omnibus.md).

**Status: deployed 2026-08-21, in evaluation.** Runs alongside Mylar3, which remains the
admin tool. Omnibus is the *user-facing* half: discovery, requests, approvals, acquisition.

## Purpose

Mylar3 is an admin tool — powerful, but not something you hand to a household member. Omnibus
gives users a browsable catalogue, a request button, and an approval queue, then acquires what
was approved. Think Seerr, but for comics and manga.

## Architecture

```text
Admin  → Mylar3 (bare metal, :8090) → /mnt/avrana_media/comics          ─┐
                                                                          ├→ Komga
Users  → Authentik → Omnibus → Prowlarr → SABnzbd → comics_omnibus/     ─┘
```

Three containers, per upstream's required layout:

| Container | Role | Exposed |
|---|---|---|
| `omnibus` | Next.js web UI + API | `10.0.0.218:5058` |
| `omnibus-engine` | Rust sidecar: scans, downloads, conversion, metadata | no ports, deliberately |
| `omnibus-redis` | job queue | no ports |

Pinned to **v1.4.4** by tag *and* digest. Upstream's README documents only `latest`, but real
`vX.Y.Z` tags do exist on GHCR (795 on the web image, 243 on the engine). `latest` is not used.

## URL and access

- **https://requestacomic.avrana.net** (cloudflared → `10.0.0.218:5058`)
- LAN: `http://10.0.0.218:5058`

The hostname follows the request-service convention: `request.avrana.net` (Seerr),
`requestabook.avrana.net` (Shelfarr). `comics.avrana.net` was deliberately **avoided** —
`read.avrana.net` is already the Komga reader, and `comics.avrana.media` is a separate tunnel
pointing at Komga. Either would have been confusing.

## Authentik integration

Native OIDC, not a proxy-auth hack. Blueprint at
`services/authentik/blueprints/omnibus.yaml`.

- Application slug **`omnibus`** → issuer `https://auth.avrana.net/application/o/omnibus/`
- Callback **`/api/auth/callback/oidc`** — Omnibus is NextAuth with its OIDC provider
  registered as `id:"oidc"`, so this path is **fixed, not configurable**
- Access gated on the existing **`avrana-comics`** group — no redundant identity group created
- Admin mapping: `authentik Admins`
- `oidc_auto_approve = true`; the group binding is the real gate

**The slug is the issuer path.** Renaming the app in the Authentik UI breaks SSO. Keep it
declarative in the blueprint.

## Roles

| Role | Capability |
|---|---|
| Admin | approvals, settings, indexers, download clients, all libraries |
| User | browse, request, follow series; downloads subject to approval |

Per-user flags exist for `autoApproveRequests`, `canRequest`, `canDownload`.

## Prowlarr / downloader flow

```text
request → Prowlarr search (cat 7030) → release selected → SABnzbd → import → comics_omnibus/library
```

Prowlarr at `http://10.0.0.218:9696`, verified reachable from inside the container (200, 2
indexers). `download_path = /mnt/avrana_media/incoming` — SABnzbd runs bare metal and reports
HOST paths, so that directory is **identity-mounted** at the same path inside the container.
No Remote Path Mapping needed, and the import stays a same-filesystem rename.

## Storage ownership — the safety boundary

```text
/mnt/avrana_media/comics           MYLAR writes    → Omnibus mounts :ro
/mnt/avrana_media/comics_omnibus   OMNIBUS writes  → Mylar never sees it
```

**Mylar's `destination_dir` is the entire `comics/` root**, with
`folder_format = $Publisher/$Series ($Year)`. It does not own a subfolder — it owns the tree.
Nesting Omnibus inside it was therefore unsafe, so Omnibus gets a **sibling** directory,
matching the existing `comics_incoming` / `comics_old` / `comics_quar` naming.

Verified non-overlapping at deploy time. Mylar also has `enable_check_folder = False`, so it
scans no watch directory and cannot pick up Omnibus output.

> ⚠ **Mylar and Omnibus must never manage the same writable series or directory.** Mylar has
> `post_processing = True` and actively tracks **109 series**. If both manage one series, two
> downloaders fetch the same issue and two renamers fight over the result. The `:ro` mount is
> the hard guarantee — writes to Mylar's tree are refused by the kernel, not by policy.

## Relationship with Komga

Komga mounts **both** trees read-only and serves them to users:

- `/mnt/avrana_media/comics` → the five existing publisher libraries
- `/mnt/avrana_media/comics_omnibus` → its own library, root
  `/avrana_media/avrana_media/comics_omnibus/library`

**Superseded 2026-08-21** — see *Unified library via mergerfs* below. Both trees are now
merged into one read-only view and served through the existing publisher libraries.

Note the existing five libraries only cover 5 of 11 publisher folders — `Dark Horse Comics`,
`IDW Publishing`, `Manga`, `Panini Verlag` and `StoryArcs` have no library at all.

## Unified library via mergerfs (2026-08-21)

Omnibus output originally landed in a separate **Requested Comics** Komga library. That was
replaced with a **union mount**, so both tools' comics appear in the existing publisher
libraries while storage ownership stays fully separated.

```text
/mnt/avrana_media/comics                  <- MYLAR writes only here
/mnt/avrana_media/comics_omnibus/library  <- OMNIBUS writes only here
                    |  mergerfs, read-only
/mnt/avrana_media/comics_merged           <- KOMGA reads only this
```

This works cleanly because **Omnibus already uses Mylar's exact folder convention**,
`$Publisher/$Series ($Year)` — so Marvel-from-Mylar and Marvel-from-Omnibus merge into one
Marvel folder. Verified at cutover: 31 Marvel series = 29 + 2, zero publisher/series
collisions across the two branches.

**Komga's internal path is deliberately unchanged** (`/avrana_media/avrana_media/comics`).
Only the bind mount *source* moved, so all five library roots kept working with no re-scan,
nothing flagged missing, and **no admin API call** — which mattered, because the Homepage
API key is guest-level and 403s on library edits.

### fstab entry

```
/mnt/avrana_media/comics:/mnt/avrana_media/comics_omnibus/library \
  /mnt/avrana_media/comics_merged fuse.mergerfs \
  ro,allow_other,use_ino,category.create=epff,\
  x-systemd.requires=/mnt/avrana_media,x-systemd.before=docker.service 0 0
```

> ⚠ **`x-systemd.before=docker.service` is load-bearing.** If the union is not mounted when
> Komga starts, Komga binds an **empty directory** and flags the entire library as gone. Run
> `sudo systemctl daemon-reload` after editing fstab so systemd honours the ordering.

**It must be root-mounted.** Unprivileged FUSE fails on this host: `fusermount3` is correctly
setuid and `/dev/fuse` is world-writable, but the mount returns `Operation not permitted`
(AppArmor), and `/etc/fuse.conf` has `user_allow_other` **commented out** — so `allow_other`,
which Docker needs to see the mount, is unavailable to a normal user anyway.

`ro` on the union means Komga can never write to either branch. Mylar and Omnibus are unaware
the union exists.

### Deleting the old library

**Requested Comics** now holds **0 series** and should be deleted in the Komga UI.

## Discovery of the existing collection

Mylar's tree is registered inside Omnibus as **`Mylar Collection (read-only)`** at
`/mylar-library`, giving "you already own this" awareness across ~1,665 files.

Omnibus's `Library` model has **no read-only flag** — it assumes libraries are writable, and
its health check tests for writability. Expect `EMBED_METADATA` (which writes `ComicInfo.xml`
into archives) to fail against this mount. Files are safe regardless; the mount is `:ro` at
the kernel level. Remove the Library row and restart to back it out.

## Following Mylar's series

All 98 of Mylar's tracked series that Omnibus has records for are followed by Cody, with
**auto-download off**. Matched by **ComicVine ID** (`mylar.comics.ComicID` = `Series.cvId`),
never by title — there are two distinct series called "Batman".

`SeriesFollow` (per-user subscription) and `Series.monitored` (auto-download) are independent.
Following changes nothing about acquisition.

Requires the read-only Mylar library to have been scanned first, otherwise there are no Series
rows to attach a follow to. 11 Mylar-tracked series have no files on disk and so have no
Omnibus record.

## Health checks

Omnibus ships its own health system — 21 checks covering engine sync, engine auth, ComicVine
key and rate limit, download directory, download clients, library accessibility, cache dir,
watched/unmatched dirs, Cloudflare blocks, stalled downloads, duplicates and backup age.
Visible in the UI and cached in `SystemSetting.system_health_cache`.

**The cache is scheduled, not live.** After changing settings it can report stale errors for
some minutes. Do not chase them immediately — confirm against the DB first.

Container healthcheck is node-based against the container's own hostname:

- The image has **no `wget` and no `curl`** — only `node`
- Next.js binds **only to the eth0 address**, so `127.0.0.1:3000` gives ECONNREFUSED even
  while the published port serves fine
- `/api/health` returns 401 unauthenticated, which still proves the app is routing, so
  anything under 500 counts as healthy

## Backup and restore

`backup_omnibus()` in `services/backups/avrana-backup.sh` captures:

- `services/omnibus/config/omnibus.db` (SQLite)
- `services/omnibus/.env` at 0600

> ⚠ **`NEXTAUTH_SECRET` is the database encryption master key**, not just a session key. A
> restore of `omnibus.db` without it is undecryptable and worthless. Both must be restored
> together.

Not backed up: `config/cache`, `config/logs` (regenerable) and the comics themselves, matching
how the Mylar/Komga libraries are treated.

**Restore:** stop the stack, put `omnibus.db` back at `config/omnibus.db`, restore `.env` with
the original `NEXTAUTH_SECRET`, start. Media is not part of the restore.

## Upgrade procedure

1. Read the upstream changelog — this is young software.
2. Pull the new `vX.Y.Z` for **both** `omnibus` and `omnibus-engine`; their versions must
   match or the `engine_version` health check fails.
3. Update tag **and** digest in `docker-compose.yml`.
4. `docker compose up -d`, confirm health, confirm a test request still searches.

## Known caveats

- **Storage on the SSD, not the array.** Docker's data root is `/mnt/avrana_media/docker`
  (the spinning array). `./config` is a bind mount under `/home/cody` instead. A database on
  that array is what broke Tracearr — fsync 775 ms vs 1.33 ms.
- **One Docker network, not two.** The host sits at Docker's default address-pool limit;
  requesting a second subnet failed outright.
- **Redis runs as uid 999.** Its entrypoint drops root via `setpriv`, which `cap_drop: ALL`
  forbids; starting non-root lets all capabilities stay dropped.
- **Anna's Archive** ships as a download source. Decide deliberately.
- **Blueprints are gitignored** (`services/*/*`), so the OIDC config lives only on disk.

## Future: if Omnibus replaces Mylar3

Nothing here forecloses it. The migration would be: stop Mylar, point Omnibus's library at
`/mnt/avrana_media/comics` read-write, import the existing tree, retire the separate Komga
library. Moving files *into* Mylar's tree is easy; untangling a collision is not — which is
why the boundary exists during evaluation.
