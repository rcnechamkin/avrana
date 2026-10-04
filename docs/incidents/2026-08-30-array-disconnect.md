# Incident 2026-08-30 - array disconnected while mounted, and the mount guards that did not exist

**Impact.** The USB-attached 8TB array was disconnected at 18:17 while mounted with 40 containers
holding databases open. EXT4 aborted its journal and remounted read-only; the disk's write cache
never flushed. The host was powered off deliberately. On the following boot the enclosure did not
re-enumerate at all, and **Docker started anyway** and initialised an empty data-root on the root
LV. Total service outage ~80 minutes, all of it after the disconnect.

**Resolved.** 40/40 containers Up, 0 unhealthy, 26/26 reachability checks, 12/12 public hostnames
healthy, 0 orphan bridges, 0 duplicate subnets, 0 stale network IDs, 0 failed system units, all 7
SQLite databases `integrity_check = ok`. The array preflight passes and boot verification is armed.

**Nothing was lost.** Two `e2fsck` passes recovered the journal, optimised one extent tree and
corrected the free-block count by 6 blocks; the second pass was clean with exit 0. The Docker
estate on the array was untouched - 41 containers, 416 image layers, 13 volumes.

**The disconnect was not the interesting fault.** Three latent faults were exposed by it, and two
of them are the same shape: **a mountpoint is a plain directory when nothing is mounted on it, and
nothing in this stack checked.**

---

## Timeline (all times PDT)

| Time | Event |
|---|---|
| 18:17:26 | `JBD2: I/O error when updating journal superblock for sdb1-8`. |
| 18:17:27 | `EXT4-fs error (device sdb1): Detected aborted journal` -> remounted read-only. |
| 18:17:34 | `sd 6:0:0:0: [sdb] Synchronize Cache(10) failed: hostbyte=DID_ERROR`. **Write cache never flushed.** |
| 18:17:37 | Enclosure re-enumerates as `/dev/sdc`. |
| 18:27:46 | Last journal entry of boot `-1`. Host powered off deliberately. |
| 18:41:50 | Boot `0`. **Enclosure absent from the USB bus entirely** - only the two root hubs present. |
| 18:41:53 | `mnt-avrana_media.mount` fails its device dependency. `nofail` means the boot proceeds. |
| 18:43:32 | **`docker.service` starts regardless** and initialises an empty data-root at `/mnt/avrana_media/docker` - on the root LV. `Containers: 0, Images: 0`. **Fault 1.** |
| 18:46:30 | Enclosure re-seated. Re-enumerates cleanly as `/dev/sdb1`, 8.00 TB, driver `uas`, zero I/O errors. |
| 18:50:58 | Docker stopped. `avrana-backup.timer` stopped - it was 7h from firing against an unmounted mountpoint. **Fault 2.** |
| ~18:55 | `e2fsck -f` pass 1: journal recovered, one extent tree optimised, free-block count corrected by 6. Filesystem modified. |
| ~19:00 | `e2fsck -f` pass 2: five passes, no repairs, **exit 0**. |
| 19:04 | Synthetic stub (3.9M, 0 containers, 0 images) moved to `/root/orphan-docker-root-2026-08-30`. Mountpoint left empty. |
| ~19:05 | `mnt-avrana_media.mount` started. `sdb1`, UUID verified, 7.3T, device-id 2065. |
| 19:09:55 | Docker starts on the real data-root. `Loading containers: done` at 19:11:51. |
| ~19:14 | **54 `br-*` bridges for 27 bridge networks.** 27 orphans, 20 of them duplicating a live subnet. 18 of 22 published services blackholed. **Fault 3.** |
| 19:18:25 | `clean-orphan-bridges.sh` - 27 links deleted, Docker restarted. Single restart yields exactly 27 bridges for 27 networks. |
| 19:35:18 | `mylar3.service` restarted after `reset-failed`. **Fault 4.** |
| ~19:40 | Baseline 25/26, `services-health.sh` clean, backup timer re-armed. Recovery complete. |
| 19:46 | `RequiresMountsFor=/mnt/avrana_media` installed on `docker.service`. |
| 19:54 | `verify-array.sh`, `boot-verify.sh` and `avrana-boot-verify.timer` added and enabled. |
| later | `sabnzbd.service` and `mylar3.service` drop-ins installed; `jellyfin-stale-2025spec` removed. Baseline **26/26**. |

---

## Root cause - three faults, plus one straggler

### 1. `nofail` lets Docker start without the array

`/etc/fstab`:

```
UUID=f2276a43-a56c-4e18-80a1-1845918243d4 /mnt/avrana_media ext4 defaults,nofail 0 2
# (mergerfs line, source paths abbreviated for width)
/mnt/avrana_media/comics:... /mnt/avrana_media/comics_merged fuse.mergerfs ro,...,x-systemd.requires=/mnt/avrana_media,x-systemd.before=docker.service 0 0
```

Only the **mergerfs** line carries `x-systemd.before=docker.service`. The array mount itself has no
declared relationship to Docker at all. When the array is absent, the mergerfs mount fails its
dependency and drops out of the transaction - taking the only ordering edge with it - and
`docker.service` starts on schedule. Docker's data-root is `/mnt/avrana_media/docker`, which
without the mount is a plain directory on the root LV, so Docker creates a fresh empty state there
and the stack appears catastrophically empty while the real data sits fine on an unmounted disk.

Ordering existed. A **requirement** never did.

**This was not the first time.** The stub preserved at `/root/orphan-docker-root-2026-08-30`
contains files that predate both this boot and the incident:

```
2026-08-28 20:03:25   buildkit/metadata_v2.db
2026-08-28 10:01:16   buildkit/history.db
```

Files can only be written there while the array is unmounted. Docker ran against the stub on
August 28 as well, twice, and nobody noticed. The directory itself dates to 2026-03-30.

### 2. The backup has no mount guard, and its only guard measures the wrong filesystem

`avrana-backup.sh` writes to `DEST_ROOT=/mnt/avrana_media/.backups/avrana` and never checks that
anything is mounted there. Its one safety is:

```bash
avail_gb() { df -PB1G "$1" | awk 'NR==2{print $4+0}'; }
free_gb="$(avail_gb "$DEST_ROOT")"
if (( free_gb < MIN_FREE_GB )); then ...abort... fi
```

With the array unmounted that `df` measures the **root LV**, which had exactly 20G free against a
`MIN_FREE_GB` of 20 - the abort is `<`, so it was a rounding coin flip. Had it proceeded at 02:31 it
would have written a backup to the root LV and, worse, written `LAST_RUN.json` there reporting
**success**. The dashboard would have shown a healthy recent backup that did not exist.

Rotation was not at risk: `ls -1d "$DEST_ROOT"/*/ | head -n -7` finds nothing to prune in an empty
directory, so no real backup could have been deleted.

### 3. An unclean shutdown regenerates orphan bridges - a new trigger for a known fault

The 2026-08-29 incident attributed orphan bridges to *two rapid dockerd restarts* recreating
networks. That is not what happened here. Bridges are kernel objects that do not survive a reboot,
and boot `-1` (Aug 29 10:14:57 -> Aug 30 18:27:46) was verified at 0 orphan bridges. Tonight,
**one** dockerd start at 19:09:55 produced 54 `br-*` interfaces for 27 networks.

The leading explanation is that libnetwork's persistent store on the array was left inconsistent by
the 18:17 abort - the filesystem went read-only mid-write and the cache never flushed - so the
restore materialised bridges for stale records alongside the live ones. dockerd logs no
bridge/network events at default verbosity, so the precise internal mechanism is **not proven from
the logs**; what is certain is the count, the single start, and that the fault did not recur after
the stale links were deleted.

The consequence is the part that matters for remediation: **this fault class is reachable from an
unclean shutdown alone**, not only from migration work.

Symptom and blast radius, measured before and after:

| | route via UP bridge | route via DOWN orphan |
|---|---|---|
| before cleanup | 4 responding | **18 returning `000`** |
| after cleanup | 21 responding | 0 |

Every affected container showed `Up`, most `healthy`, with its port bound. `ip route get` returned
the `linkdown` orphan for every contested subnet - and
`net.ipv4.conf.all.ignore_routes_with_linkdown = 0`, so the kernel selects those routes rather than
skipping them. Affected: bookstack, komga, homepage, seerr, prowlarr, radarr, sonarr, shelfmark,
shelfarr, tracearr, omnibus, beszel, completeseries, libation-status, audible-connector,
speech-to-phrase, wyoming-piper, beszel-socket-proxy.

### 4. `mylar3.service` crash-looped past its rate limiter

Mylar3 starts before the array is available and calls `validateAndCreateDirectory()` on
`mega_ddl_path`. With the array missing it raises
`UnboundLocalError: cannot access local variable 's_perms'` - an upstream bug in
`filechecker.py:1927` that masks the real error, since `s_perms` is never assigned when the path
cannot be stat'd. Five restarts in, systemd hit `Start request repeated too quickly` and stopped
trying, so it stayed down after the array came back and needed `reset-failed` before `start`.

---

## What was verified undamaged

- **Filesystem** - two `e2fsck -f` passes, second clean, exit 0.
- **Docker estate** - checked *on disk before starting the daemon*: 41 containers, 416 image
  layers, 511 overlay2 dirs, 13 volumes, `repositories.json` 12,083 bytes, all on device-id 2065.
- **All 7 SQLite databases** - ABS, Komga, CWA, Seerr, Radarr, Sonarr, Prowlarr: `ok`.
- **Postgres** - Authentik and Tracearr came up and accept connections.
- **`~/.sabnzbd/sabnzbd.ini`** - intact, 7543 bytes, mtime Aug 28 21:15 (predates the disconnect),
  21 sections, `api_key` and the newshosting block present, no null bytes. Still finding **N1**:
  intact but in no backup.
- **Backups** - last run `status: ok`, 163M, 17/17 components, 0 failed.

---

## Fixes applied

| # | Fix | Where |
|---|---|---|
| 1 | Synthetic data-root preserved, not deleted, and the mountpoint left empty before mounting. | `/root/orphan-docker-root-2026-08-30` |
| 2 | 27 orphan bridges deleted and Docker restarted to rebuild bridges and NAT. | `deploy/docker/clean-orphan-bridges.sh` |
| 3 | `mylar3.service` `reset-failed` then started; authenticates (200) and rejects bad creds (303). | live |
| 4 | `services-health.service` stale failed state cleared; unit re-run, `result: success`. | live |
| 5 | `jellyfin-stale-2025spec` removed. Created 2025-07-13, stopped cleanly 05:21 on Aug 30, `restart: unless-stopped` so it never came back. It was the sole cause of both remaining baseline failures and the only thing keeping `avrana-boot-verify` red. | live |

---

## Remediation - hard guards, not documentation

Documentation-only safeguards had already failed twice: the handoff said "do not let Docker start if
the array did not mount," and Docker had started before anyone read it. All of the following are
installed and verified except where marked deferred.

1. **`RequiresMountsFor=/mnt/avrana_media`** as a systemd drop-in on **`docker.service`**,
   **`sabnzbd.service`** and **`mylar3.service`**. systemd now refuses to start any of them without
   the array, instead of relying on an fstab ordering edge that disappears when the mount fails.
   SABnzbd mattered most: it *creates* a missing `download_dir` rather than refusing to start, so
   with the array absent it would have written Usenet downloads into the root LV's ~20G.
   Sources: `deploy/docker/docker-require-array.conf`, `deploy/storage/dropins/`.
2. **A `mountpoint -q` guard at the top of `avrana-backup.sh`**, before any `mkdir`, exiting 4 and
   writing nothing at all. It checks the **array root** (`/mnt/avrana_media`), not
   `dirname "$DEST_ROOT"` - the latter is `/mnt/avrana_media/.backups`, which is not a mount point
   even when the array is mounted, and would never have fired. The `df` headroom check measures
   whatever filesystem it lands on and cannot be the thing standing between an unmounted array and
   a fabricated success record.
3. **`deploy/storage/verify-array.sh`**, a read-only preflight: mount point, UUID, ext4,
   read-write-not-ro, capacity, expected directories, and that Docker's data-root physically
   resides on the array rather than the root LV.
4. **`avrana-boot-verify.timer`** runs `boot-verify.sh` five minutes after every boot: the preflight
   as a hard gate, then `verify-baseline.sh`, then `services-health.sh`. Every fault in this report
   presented as a healthy-looking stack; the orphan-bridge blackhole in particular is undetectable
   from `docker ps`, and `services-health.sh` does not check bridges.
5. **Deferred: `chattr +i` on the empty `/mnt/avrana_media` mountpoint.** An immutable empty
   directory cannot be written into when nothing is mounted, blocking the fault class beneath
   systemd. It is only applicable **while the array is unmounted** - applied to a mounted path it
   sets the flag on the array's own root inode instead. Evaluate during the enclosure swap's
   unmounted window. See `deploy/storage/ENCLOSURE-MIGRATION.md`.

## Still open

- **Off-host backups.** Unchanged and now argued for by two consecutive incidents: the only copy of
  every backup lives on the disk that dropped. Blocked on a B2/R2 key. **The two rclone crypt
  passwords have still not been confirmed to exist in a password manager** - if they do not, the
  plan produces bytes nobody can decrypt.
- **`tag_all.service`** - failing hourly since **Aug 20 11:45, 246 logged failures**. The unit runs
  `filing_cabinet/taggers/tag_all.py`; the script is at `filing_cabinet/utils/tag_all.py`. Wrong
  directory in the unit. Unrelated to this incident.
- **JMS578 / UAS as the disconnect's root cause.** The bridge binds to `uas`, and
  `Synchronize Cache(10) failed: hostbyte=DID_ERROR` followed by re-enumeration is the textbook
  presentation of that chipset dropping under load. `usb-storage.quirks=152d:0578:u` forces the
  slower, stabler `usb-storage` driver. **Deliberately not applied** - baseline first, one change at
  a time. Cable and power are not excluded.
