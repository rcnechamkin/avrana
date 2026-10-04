# Radarr: 7878 · Sonarr: 8989 (LAN)

> Promoted from the BookStack wiki on 2026-10-04 (page 23, "Radarr / Sonarr", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: see Phase 2 finding A13 (Supergirl download loop) for a profile problem found later.
> Original: [archive](../../docs/archive/bookstack/raw/services/23-radarr-sonarr.md).

Movie/TV automation. Containers `radarr`, `sonarr`. On the `arr-core` and `request-backend` networks.
- Atomic import from `/mnt/avrana_media/incoming` into `movies/` and `tv/`.
- Run non-root + read-only (validated).

## Recyclarr (TRaSH guide sync) - added 2026-08-16

`services/recyclarr/` syncs the TRaSH guides into Radarr nightly at **04:00** (clear of the 02:30
stack backup). It only ever writes Radarr *configuration* over the API; it never touches media,
never searches, and never downloads.

### What Radarr looked like before

Worth recording, because it explains why sizes were so inconsisten: **zero custom formats**, all
seven profiles stock with **`upgradeAllowed=false`**, quality definitions at Radarr defaults with
**no size floor on any tier** (a 4 GB fake-2160p and a 90 GB remux both scored as acceptable), and
**renaming switched off**, so filenames carried no quality, HDR or release-group information.

### The two profiles

| Profile | Role | Cutoff | Allowed |
|---|---|---|---|
| **UHD Bluray + WEB** | the normal high-quality profile | `Bluray-2160p` | WEB 2160p group, Bluray-2160p |
| **Remux + WEB 2160p** | opt-in **Reference** profile for favourites and IMAX titles | `Remux-2160p` | WEB 2160p group, Remux-2160p |

Both have `upgradeAllowed=true` and `cutoffFormatScore=10000`, 62 custom formats synced with 44
scored. Radarr's seven stock profiles are **untouched**.

Notable scores (identical in both): `TrueHD ATMOS` +5000, `DTS X` +4500, **`IMAX` +800**,
**`IMAX Enhanced` +800**; `BR-DISK`, `LQ`, `Upscaled`, `AV1`, `3D`, `Bad Dual Groups`,
`Generated Dynamic HDR`, `x265 (no HDR/DV)` all **-10000**.

### HDR compatibility safeguard

The **`[HDR Formats] DV (w/o HDR fallback)`** group is enabled. Dolby Vision releases with no HDR10
fallback render washed-out or green/purple on hardware that cannot decode DV, and this host's
Jellyfin (Skylake / Gen9 QuickSync) **cannot usefully transcode 4K HDR** to rescue them, so those
releases are scored heavily negative and lose to a safe HDR10 copy. `HDR10+ Boost` is also on.

### Quality definitions: floors, not ceilings

TRaSH sets a **minimum** size per tier and deliberately leaves preferred/max uncapped, relying on
custom-format scoring rather than size caps. In MB/min:

| Quality | before (min/pref/max) | after |
|---|---|---|
| WEBDL-1080p | 0 / 95 / 100 | **12.5** / none / none |
| Bluray-1080p | 0 / none / none | **50.8** / none / none |
| Remux-1080p | 0 / none / none | **102** / none / none |
| WEBDL-2160p | 0 / none / none | **34.5** / none / none |
| Bluray-2160p | 0 / none / none | **102** / none / none |
| Remux-2160p | 0 / none / none | **187.4** / none / none |

For a 110-minute feature that is roughly: WEBDL-2160p **>= 3.7 GB**, Bluray-2160p **>= 11 GB**,
Remux-2160p **>= 20 GB**. Note WEBDL-1080p previously had a 100 MB/min ceiling and is now uncapped.

### Naming

Now **on** (`renameMovies: true`), using the `jellyfin-tmdb` preset because Jellyfin is the media
server and Radarr is TMDB-native:

```
{Movie CleanTitle} {(Release Year)} [tmdbid-{TmdbId}] - {{Edition Tags}} {[MediaInfo 3D]}{[Custom Formats]}{[Quality Full]}{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{[MediaInfo VideoDynamicRangeType]}{[Mediainfo VideoCodec]}{-Release Group}
```

This governs **future imports**. Existing files are renamed only when a Rename operation is run by
hand.

> **Nothing is assigned to the new profiles.** All 26 movies keep the profile they already had, so
> the sync cannot trigger an upgrade. Verified after syncing: download queue empty, zero active
> search commands, assignment counts unchanged (Ultra-HD 15, HD-1080p 9, HD-720p 1, Any 1).
> **Moving a title onto UHD Bluray + WEB is the deliberate step that makes it eligible for an
> upgrade** - and both indexer RSS and automatic search are enabled, so expect grabs once you do.

> **Pinned to a pre-release digest on purpose.** Recyclarr stable (7.4.0) implements an older config
> schema and cannot parse the current TRaSH templates (`Property 'trash_id' not found on type
> QualityProfileConfigYaml`); config-templates has only a `master` branch, already migrated. The
> compose file pins **v8.7.2-dev.10** by digest and records why. Revisit when 8.x ships stable.

```bash
cd /home/cody/avrana/services/recyclarr
docker compose -p recyclarr exec recyclarr recyclarr sync radarr --preview   # dry run
docker compose -p recyclarr exec recyclarr recyclarr sync radarr             # apply
```

> **Radarr/Sonarr/Prowlarr are NOT in the nightly stack backup** (confirmed 2026-08-16). A
> pre-change snapshot lives at `/mnt/avrana_media/.backups/radarr-pre-recyclarr-20260817T022447Z/`
> (Radarr's native zip + SQLite online copy + config.xml + JSON of every setting + manifest).
> Radarr also keeps its own scheduled backups in `/config/Backups`. Adding the \*arr to
> `avrana-backup.sh` is an open item. Radarr also has **no recycle bin configured**, so deletions
> there are immediate and unrecoverable.

## Recycle bins (added 2026-08-16)

Both Radarr and Sonarr had **`recycleBin` empty**, so every delete was immediate and
unrecoverable. Both now have one, with **30-day retention** (was the 7-day default):

| Service | Recycle bin (container path) | Host path |
|---|---|---|
| Radarr | `/data/.recycle/radarr` | `/mnt/avrana_media/.recycle/radarr` |
| Sonarr | `/data/.recycle/sonarr` | `/mnt/avrana_media/.recycle/sonarr` |

**Deliberately inside `/data`.** The bin must sit on the *same filesystem* as the library or a
"delete" becomes a full copy instead of a rename, which is slow and non-atomic. Verified by
comparing device ids inside each container: `/data/.recycle/<svc>` and `/data/movies` (resp.
`/data/tv`) are both on `/dev/sdb1`, so the move is an atomic rename.

This changed **no mounts**. The single `/mnt/avrana_media:/data` mount and the read-only tmpfs
shadowing `/data/.backups` are both intact and were re-verified afterwards; see
*Docker Hardening & Networking* for why neither may be altered.

## Seerr integration (updated 2026-08-16)

Seerr 3.4.1, **one** Radarr server (`Movies`, id 0), `is4k=false`, `isDefault=true`. Its default
movie profile was the stock **`Ultra-HD` (id 5)** and is now **`UHD Bluray + WEB` (id 8)**, resolved
**by name** from Radarr rather than by a hard-coded id.

Preserved and re-verified unchanged: root folder `/data/movies`, `minimumAvailability=released`,
`syncEnabled=false`, `preventSearch=false`, `tagRequests=false`, `is4k=false`, `isDefault=true`,
tags `[]`. Still exactly one Radarr server; no 4K server was created.

> **Profile ids survive a Recyclarr sync.** Recyclarr keeps a state mapping and updates profiles in
> place rather than deleting and recreating them, so Seerr's saved id does not go stale. Re-verified
> after a sync: Radarr still reports id 8 = `UHD Bluray + WEB` and id 9 = `Remux + WEB 2160p`, and
> Seerr resolves both. **Re-check this after any Recyclarr upgrade**, since it is the assumption
> that would break silently.

### Who can pick Remux, and how

Seerr's **Advanced Requests** chooser lists **every** Radarr profile; it cannot be restricted to a
subset. So ordinary users are deliberately left on the default and are never granted the permission:

| User | permissions | admin | REQUEST_ADVANCED (8192) |
|---|---|---|---|
| Cody | 2 | yes | via admin |
| Jared | 32 | no | no |
| Audrey | 160 (REQUEST + AUTO_APPROVE) | no | no |
| Tyler | 32 | no | no |

Cody does not carry bit 8192 explicitly; **ADMIN implies it**, which is what gives him the chooser.
Everyone else gets `UHD Bluray + WEB` automatically with no way to choose.

**Admin workflow for a Reference-grade title:** request or open the movie in Seerr, use
**Advanced Requests** and select **`Remux + WEB 2160p`**; or, for a title already in the library,
change its profile in Radarr directly. Remux stays opt-in per title, never a default.

## Sonarr TRaSH profiles (2026-08-18)

Managed by the same Recyclarr instance as Radarr, in the `sonarr:` section of
`services/recyclarr/config/recyclarr.yml`. Commit `d0e1982`. Nightly sync at 04:00.

### Starting point

Sonarr had **zero custom formats** and `upgradeAllowed=false` on all six stock profiles, so no
existing tuning was overwritten. The stock profiles are untouched and still carry 0 CFs.

### What was created

| Profile | Ladder (worst -> best) | Cutoff | Assigned to |
|---|---|---|---|
| **Avrana TV - 1080p** | HDTV-1080p -> WEBRip/WEBDL-1080p -> Bluray-1080p | Bluray-1080p | nothing |
| **Avrana TV - 4K** | WEB 2160p only | WEB 2160p | nothing (opt-in) |

`upgradeAllowed=true`, `minUpgradeFormatScore=1`, `cutoffFormatScore=10000` on both. 38 custom
formats and 14 series quality-size definitions synced.

**Nothing is assigned to either profile**, matching the Radarr convention: a sync can never start
an upgrade. Moving a series is a separate, deliberate act.

### DEVIATION from the TRaSH template, and why

TRaSH's stock Sonarr profile **WEB-1080p** (`72dae194fc92bf828f32cde7744e51a1`) allows **only**
`WEB 1080p`: both `HDTV-1080p` and `Bluray-1080p` are `allowed: false` in the guide JSON. That
cannot deliver two requirements of this deployment:

- **grab promptly on release**: for broadcast shows HDTV-1080p is often the only thing available
  for hours or days, so excluding it means waiting,
- **upgrade toward Bluray-1080p**: impossible if Bluray-1080p is not an accepted quality.

So the **quality ladder is Avrana's**; **every score is TRaSH's guide default**. No score was
invented. The 4K profile copies TRaSH's WEB-2160p ladder exactly and only differs in name.

### Custom format groups (all at guide defaults)

| Group | Purpose |
|---|---|
| `[Required] Repack/Proper` | repack/proper handling |
| `[Release Groups] HQ` | WEB Tier 01-03, WEB Scene, **HD Bluray Tier 01-02** |
| `[Streaming Services] General` | AMZN, ATVP, DSNP, NF ... source CFs |
| `[Streaming Services] HD/UHD boost` | HD Streaming Boost (UHD boost only matches 2160p) |
| `[Unwanted] Unwanted Formats` | AV1, BR-DISK, LQ, LQ (Release Title), Upscaled, Extras, Bad Dual Groups |
| `[Optional] Golden Rule HD` | **x265 (HD)** at -10000 |

The HD Bluray tiers are included because this ladder ends at Bluray-1080p, unlike the stock
WEB-only profile.

**x265 (HD) is the codec-compatibility guard.** Jellyfin runs on an i3-6100T (Skylake / Gen9
QuickSync); 1080p HEVC is the usual cause of needless transcoding for clients that cannot
direct-play it. This is TRaSH's own mechanism at its own score, not a local invention.

> **Trap: custom-named profiles need `assign_scores_to`.** CF groups bind to trash-template
> profiles through a compatibility list. Because these profiles are named locally rather than
> generated from a `trash_id`, every group was **skipped** on the first run with
> *"none of your quality profiles are in its compatibility list"*: producing two profiles with
> no scores at all. Each group entry now carries an explicit `assign_scores_to`. **A preview run
> is what caught this**; the sync still exits 0.

### Validation (via Sonarr's own `/api/v3/parse`, read-only)

| Release | Quality | CF score |
|---|---|---|
| `1080p AMZN WEB-DL DDP5.1 H.264-NTb` | WEBDL-1080p | **+1775** (AMZN 75 + WEB Tier 01 1700) |
| `1080p NF WEB-DL DDP5.1 x264-FLUX` | WEBDL-1080p | **+1775** |
| `1080p HDTV x264-GROUP` | HDTV-1080p | 0 (accepted floor) |
| `1080p WEB-DL x265-RANDOM` | WEBDL-1080p | **-10000** (x265 HD) |
| `1080p AV1 WEB-DL-GROUP` | WEBDL-1080p | **-10000** (AV1) |
| `2160p WEB-DL H.265-NTb` | WEBDL-2160p | not an accepted quality here |

Accepted leaf qualities confirmed as exactly: HDTV-1080p, WEBRip-1080p, WEBDL-1080p,
Bluray-1080p.

### Seerr

The default (non-4K) Sonarr server now uses **Avrana TV - 1080p** (`activeProfileId` 4 -> 7) for
normal TV requests. `monitorNewItems=all` and season folders were left as they were. The **anime**
profile is still stock `HD-720p` (id 3): TRaSH publishes separate anime profiles and none were
applied here.

### NOT done, on purpose

- **No series was reassigned.** All 4 remain on stock `HD-1080p`, which has upgrades **off**.
  Until a series is moved, none of this affects existing shows. Sonarr's RSS sync is every 15 min
  with automatic search on and SABnzbd enabled, so moving a series **will** cause grabs: do it
  deliberately, ideally one title first.
- **No naming change.** The Radarr section sets `media_naming`; Sonarr's was left alone to avoid
  churning existing files. Worth revisiting separately.
- **No audio-format CF groups.** TRaSH's audio boosts favour TrueHD/DTS-HD, which pull toward
  releases more likely to need transcoding on this hardware: the opposite of the direct-play goal.

### Controlled tes: Parks and Recreation (2026-08-18)

Moved from stock `HD-1080p` to **Avrana TV - 1080p**. Resul: **zero grabs**: queue stayed empty
and history stayed at 330 records.

**Why no cascade.** Sonarr has **no scheduled "Cutoff Unmet" search** (only `Rss Sync`, every 15
min, plus `Refresh Monitored Downloads`). RSS only evaluates releases newly appearing in the
feed; it does not go hunting for upgrades to old episodes. A bulk upgrade happens only if someone
runs a cutoff-unmet search **by hand**. Do not run one against this library without checking the
numbers below first.

**The important resul: quality tier beats custom format score.** An interactive search on
S01E01 returned:

| Release | Quality | Score | Sonarr's verdict |
|---|---|---|---|
| `1080p.AMZN.WEBRip` (AMZN + WEB Tier 01) | WEBRip-1080p | **+1775** | **rejected**: *"Existing file on disk is of equal or higher preference: Bluray-1080p"* |
| `720p.AMZN.WEB-DL` | WEBDL-720p | +1725 | rejected: *"not wanted in profile"* |
| `1080p.WEB.H264-DEFLATE` | WEBDL-1080p | +1600 | rejected: existing file preferred |
| `BluRay-1080p` (non-x265) | Bluray-1080p | 0 | **GRABBABLE** |

This is the same rule already documented for Radarr's IMAX case: **tier first, score second**. A
+1775 WEB release cannot displace a −10000 Bluray file, because Bluray-1080p sits above WEB 1080p
in the ladder.

Two consequences:

1. **The 122 existing x265 files are not at risk of a mass re-download.** They sit at the top
   quality tier, so nothing in a lower tier can replace them regardless of score.
2. **The x265 penalty only steers choices *within* a tier.** It does not retroactively fix a
   library that is already HEVC. The only releases that can displace these files are *other*
   Bluray-1080p releases: which is exactly what the GRABBABLE row shows, and is the correct
   upgrade: same quality, better codec for direct play.

**Library-wide exposure if a cutoff-unmet search is ever run by hand:**

| Series | Files | Size | Format score | Notes |
|---|---|---|---|---|
| Parks and Recreation | 122 | 69.2 GB | −10000 | all x265 |
| Raised by Wolves | 18 | 17.9 GB | −20000 | x265 + LQ |
| Batman: Caped Crusader | 20 | 22.0 GB | −20000 .. +80 | 10 files x265 + LQ |
| Ted Lasso | 2 | 7.1 GB | +5 | clean |

### Why episode renaming matters here

`renameEpisodes` is **false**, and that is currently load-bearing.

Sonarr derives quality *and* custom formats from the release name. These files are named
`Parks.And.Recreation.S01E01...1080p.Bluray.x265-SiQ.mkv`, which is precisely why Sonarr detects
`Bluray-1080p` **and** matches the `x265 (HD)` custom format.

The configured `standardEpisodeFormat` is:

```
{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}
```

It contains **no `{MediaInfo VideoCodec}` and no `{Release Group}` token**. Turning renaming on
with this format would rewrite those filenames without `x265` or `-SiQ`, so a future re-import or
database rebuild would no longer detect the codec, the −10000 would not apply, and upgrade
decisions would silently change.

If renaming is ever enabled, adopt TRaSH's Sonarr naming scheme **first**: it exists to keep
codec, dynamic range, audio and release group in the filename. Renaming also changes paths, which
can cost Jellyfin watch state, so it is not a free operation on an existing library.

## Compatibility-first defaul: "Avrana Compatible - 4K SDR" (2026-08-18)

Commit `412556f`. Added to the **same** Recyclarr instance and file as the existing work; the
premium profiles are untouched.

**Policy:** 4K when practical, but SDR and client compatibility outrank HDR. 1080p SDR is the
fallback. HDR remains available deliberately, via the premium profiles.

Driven by a real measuremen: a single 4K DV/HDR10+ stream pinned this host at ~326% CPU with
zero idle, because the Roku rejects that video range and the Skylake iGPU cannot hardware-decode
10-bit HEVC. See *Jellyfin*.

### The profile

| | |
|---|---|
| Radarr id | 10 |
| Sonarr id | 9 |
| Qualities | **one group**: Bluray-2160p, WEBDL/WEBRip-2160p, Bluray-1080p, WEBDL/WEBRip-1080p |
| Sonarr extra | `HDTV-1080p` as a genuinely lower tier **below** the group, so broadcast shows still grab promptly |
| Cutoff | the group |
| `min_format_score` | **0** |
| Remux | excluded entirely |

> **Why one quality group.** Radarr and Sonarr sort by **quality tier first** and custom-format
> score only second. With 2160p and 1080p as separate tiers, a 2160p HDR release beats a 1080p SDR
> one *no matter how negative its score*: which would defeat the entire policy. Collapsing them
> into a single group is what lets scoring decide. This is the same mechanism documented for the
> IMAX case, applied deliberately.

### Scoring: established TRaSH formats only

| Format | Score | Why |
|---|---|---|
| `SDR` | **+2000** | TRaSH's SDR matches 2160p releases carrying no HDR marker: exactly the target |
| `HDR` | **-8000** | matches DV-with-fallback, HDR, HDR10, HDR10+, HLG **and** PQ in one format |
| `DV (w/o HDR fallback)` | **-10000** | worst case; wrong colours anywhere that cannot decode DV |
| `x265 (HD)` | **-10000** | the 1080p fallback prefers x264 for direct play |
| `x265` | **+300** | prefers HEVC at 2160p; net still deeply negative at 1080p |

Repack/Proper, release-group tiers, streaming-service sources and the unwanted/LQ filters are all
included at **guide default** scores. Remux tiers are omitted because remux is excluded.

**`min_format_score: 0` makes the HDR scores an exclusion, not a preference.** An HDR release is
*rejected*, not merely outranked. That is intentional: the fallback is 1080p SDR, and titles that
genuinely want HDR belong on a premium profile.

### Verified scoring (each service's own `/api/v3/parse`)

| Release | Score | Result |
|---|---|---|
| 2160p SDR WEB-DL x265 | +4000 | accepted, top |
| 1080p SDR WEB-DL x264 | +1700 | accepted, fallback |
| 2160p DV+HDR10+ | -6000 | **rejected** |
| 2160p HDR10 | -6000 | **rejected** |
| 2160p DV only | -9700 | **rejected** |
| 1080p x265 | -9700 | **rejected** |

### Sonarr limitation: existing media was NOT migrated

The brief asked to verify how Sonarr behaves before moving existing series. It was tested by
temporarily assigning Parks and Recreation, running one read-only interactive search, and
reverting.

**Resul: Sonarr would replace existing files.** For a single episode, **10 releases were
grabbable**. The existing `Bluray-1080p x265` files score **-9700** under this profile, and
because the single quality group removes the resolution-tier protection that previously kept
them in place, any x264 release at +1775 counts as an upgrade.

Sonarr never *downgrades*, but that is not the relevant risk here: the swap is scored as an
upgrade. Migrating the library would re-download roughly **150 episodes** (Parks 122, Raised by
Wolves 18, Batman 10). That is not a safe automatic migration, so per the brief this is
**future-downloads-only** and existing media is untouched.

Queue and history were unchanged throughout the test (0 items, 330 records before and after), and
the assignment was reverted to profile 7.

> Migration is still possible later as a deliberate, paced ac: move one series, let RSS trickle,
> confirm. There is **no scheduled cutoff-unmet search** in Sonarr, so nothing bulk-searches on
> its own. Do not run one by hand against this library without accepting the ~150 episode cost.

### Seerr

| Server | Was | Now |
|---|---|---|
| Movies (default, non-4K) | `UHD Bluray + WEB` (8) | **`Avrana Compatible - 4K SDR` (10)** |
| TV (default, non-4K) | `Avrana TV - 1080p` (7) | **`Avrana Compatible - 4K SDR` (9)** |

Confirmed Seerr resolves both ids to the right profile names and persisted them to
`settings.json`. Premium profiles remain selectable: `UHD Bluray + WEB`, `Remux + WEB 2160p`,
`Avrana TV - 1080p`, `Avrana TV - 4K`.

**Radarr and Sonarr have no server-wide "default profile" setting**: the Add screens remember a
per-browser choice. Seerr is therefore the real default for everything entering the library, which
is what was changed.

### Not changed, on purpose

- No existing movie or series was reassigned (verified against a pre-change export).
- No custom formats were deleted. Radarr updated 3 and Sonarr 1 existing CF *definitions* to
  current guide versions; all pre-existing profile scores were diffed against the backup and are
  **identical**.
- The premium/IMAX profiles are intact.
- Nothing was searched or downloaded; both queues were empty before and after.

Pre-change export of all three services:
`/mnt/avrana_media/.backups/sdr-policy-20260818T181446Z/`

### HDR admitted as a last resort (2026-08-18, commit `a1a3d95`)

`min_format_score` **0 -> -6000**. An HDR-only title now gets an HDR release rather than nothing.
SDR still outscores HDR by roughly 7000, so whenever both exist SDR wins outright; the threshold
only decides the HDR-only case.

**The HDR score also moved, -8000 -> -5000, and the reason matters.** At -8000, an HDR release
with no release-group tier scored **-7700**: the *exact same band* as an LQ release rescued by
the SDR bonus (`LQ -10000 + SDR +2000 + x265 +300 = -7700`). No threshold could admit one and
refuse the other. -5000 separates the bands.

Final verified scoring, both services:

| Release | Score | Result |
|---|---:|---|
| 2160p SDR x265 | +4000 | accepted, preferred |
| 1080p SDR x264 | +1700 | accepted, fallback: **still beats any HDR** |
| 2160p HDR tiered | -3000 | accepted, last resort |
| 2160p HDR no tier | -4700 | accepted, last resort |
| LQ + SDR + x265 | -7700 | rejected |
| 2160p DV-only | -9700 | rejected |
| 1080p x265 | -9700 | rejected |
| BR-DISK | -10000 | rejected |

> A test using `HDCAM` appeared to show an LQ release passing on Sonarr. It did no: Sonarr's LQ
> format matches **release groups**, not `HDCAM`, so the format never triggered. Re-tested with a
> real LQ group (`BRiNK`): **-7700, rejected**. Radarr's LQ definition is broader than Sonarr's;
> that is TRaSH's own difference between the two services, not a local gap.

Only the two compatibility profiles were touched. `Avrana TV - 1080p`, `Avrana TV - 4K` and both
premium Radarr profiles keep their original `min_format_score`.

---

## THIS IS TEMPORARY: revert plan when transcoding hardware arrives

**Everything above is a workaround for a hardware limitation, not a preference.** The i3-6100T's
Gen9 iGPU cannot hardware-decode 10-bit HEVC and cannot tone-map efficiently, so a single 4K HDR
stream saturates the host (measured: ~326% CPU, load 7.6, zero idle). The compatibility profiles
avoid acquiring media this box cannot serve.

**When better transcoding hardware is in place, revert to the pre-compatibility profiles.** They
were built to current TRaSH guidance and are deliberately preserved, not deleted:

| Service | Revert target | Notes |
|---|---|---|
| Radarr | `UHD Bluray + WEB` (id 8) | the previous Seerr default |
| Radarr | `Remux + WEB 2160p` (id 9) | opt-in Reference profile, keeps the IMAX preferences |
| Sonarr | `Avrana TV - 1080p` (id 7) | the previous Seerr default |
| Sonarr | `Avrana TV - 4K` (id 8) | opt-in |

### How to revert

1. Point Seerr back: default **Movies** server to profile **8**, default **TV** server to profile
   **7** (Settings -> Services, or `PUT /api/v1/settings/{radarr,sonarr}/{id}`: note `id` is
   read-only and must be omitted from the body).
2. Optionally re-enable `[HDR Formats] HDR10+ Boost` in Radarr. **It is currently still present in
   the Radarr config and still prefers HDR10+**: see the note below.
3. Leave `Avrana Compatible - 4K SDR` in place. It stays useful for anything that must reach a
   weak client, and costs nothing unassigned.
4. Media acquired while the compatibility policy was active stays SDR. Nothing re-downloads
   itself; upgrading those titles later is a deliberate, per-title act.

### What counts as "the hardware for better transcoding"

Any of these removes the constraint:

- **A better client** (Shield / Apple TV 4K / Roku Ultra). Cheapest fix and it eliminates
  transcoding rather than accelerating it. Would fix ~10 of the 12 currently-incompatible movies.
- **A newer server iGPU or a GPU** (Intel Arc A310/A380, or Gen11+ integrated). The M700 is a Tiny
  with no slot, so this means a new hos: the "separate, accelerator-shaped decision" recorded on
  the Kern shelf.

See *Jellyfin* for the measured transcode analysis and the per-title compatibility breakdown.

### Known inconsistency left in place, on purpose

Radarr's `custom_format_groups` still includes **`[HDR Formats] HDR10+ Boost`**, which *prefers*
HDR10+: the exact range the household's main TV rejects. It applies only to the two **premium**
profiles, which are opt-in, so it does not affect the new default. It was left alone to avoid
changing premium behaviour in a change that was scoped to the default. **Remove it if the premium
profiles ever become the default again while the current hardware is still in use.**

### Revision: HDR10 accepted as a peer of SDR (2026-08-18, commit `63e9a14`)

The first version was too aggressive: it penalized **all** HDR. HDR10 direct-plays on the
household's main client (it is in the Roku's own accepted `VideoRangeType` list), so penalizing it
cost 4K picture quality for no compatibility benefit.

**The blocker was that TRaSH's `HDR` format is one lever for six ranges**: it matches
DV-with-fallback, HDR, HDR10, HDR10+, HLG and PQ together. Keeping HDR10 while refusing the others
required splitting it into TRaSH's individual formats.

Adjusted **in place**; the profiles were not recreated and keep their ids (Radarr 10, Sonarr 9).

| Format | Was | Now | Why |
|---|---:|---:|---|
| `HDR` (broad) | -5000 | **0** | matches HDR10 too; held at 0 so HDR10 is not punished |
| `SDR` | +2000 | **+500** | HDR10 is now a peer, so only a slight nudge remains |
| `DV Boost` |: | **-5000** | Dolby Vision penalized as a class |
| `HDR10+ Boost` |: | **-5000** | the exact range the main TV refuses |
| `HLG` |: | **-10000** | guide default; the format explicitly excludes HDR10/HDR10+ |
| `AAC` / `DD` / `DD+` |: | **100 / 100 / 150** | broadly-supported audio, tiebreaker only |

`DV (w/o HDR fallback)` -10000, `x265 (HD)` -10000, `x265` +300 and `min_format_score` -6000 are
all unchanged.

#### Final measured hierarchy

| Release | Score | |
|---|---:|---|
| 2160p SDR x265, tier 1 | **+2650** | preferred |
| 2160p SDR BluRay, tier 1, TrueHD | +2600 | |
| 2160p HDR10 x265, tier 1 | **+2150** | **accepted peer** |
| 1080p SDR x264, tier 1 | **+1850** | fallback |
| 2160p HDR10, no tier | +450 | accepted, weak source |
| 2160p DV / HDR10+ | -2850 | last resort only |
| 2160p DV+HDR10+ / HLG / 1080p x265 | -7850 | blocked |
| 2160p DV-only | -14550 | blocked |

#### Audio: a deliberate deviation from guide defaults

TRaSH's defaults are AAC 1000 / DD 750 / DD+ 1750, calibrated for a profile that **also** scores
TrueHD and DTS-HD highly. Including only the compatible subset at those numbers leaves TrueHD at 0
and DD+ at 1750: an implicit ~1750 penalty on lossless audio TRaSH never intended.

**This was measured, not theorised:** a `2160p SDR TrueHD` release scored **800** and lost to a
`1080p DD+` release at **3450**, which is exactly the "sacrificing a substantially better release
on audio" the standard forbids. Rescored to 100/100/150, then re-verified against a properly
tiered UHD Bluray group: TrueHD **2600**, DD+ **2750**, 1080p WEB **1850**. The preference now
survives only as a tiebreaker and can never outweigh a tier step (~1700).

#### Items in the standard that were not implemented

- **Subtitles (prefer SRT over burn-in).** TRaSH publishes no custom format for subtitle format or
  hardcoded subs in either service. Expressing it would mean inventing a format, which the standard
  says to avoid. **Not implemented**, deliberately.
- **Low-bitrate 4K.** Handled by TRaSH's own **quality-size definitions** (already synced,
  `type: movie` / `type: series`) plus the `LQ` and `LQ (Release Title)` formats: established
  guidance rather than an invented bitrate floor.
- **Container format** was correctly ignored; nothing scores it.

#### Verified after the revision

- Seerr defaults unchanged and still correc: Movies -> id 10, TV -> id 9.
- Premium profiles still selectable in Seerr: `UHD Bluray + WEB`, `Remux + WEB 2160p`,
  `Avrana TV - 1080p`, `Avrana TV - 4K`.
- **No pre-existing profile's scores changed**, diffed against the pre-change export.
- **No movie or series was reassigned.** Both queues empty; nothing searched or downloaded.
- Sonarr was not upgraded, and no episode replacement was triggered. The
  future-downloads-only constraint from the previous task still holds.

### Renamed to "Avrana Compatible" (2026-08-18, commit `b4231a5`)

`Avrana Compatible - 4K SDR` -> **`Avrana Compatible`**. The old name undersold the profile once
HDR10 became an accepted peer of SDR. This supersedes the naming caveat previously recorded here.

> **Order matters, and getting it wrong creates a duplicate.** Recyclarr keys quality profiles
> **by name**. Editing `recyclarr.yml` alone would have made the next sync create a *second*
> profile under the new name and orphan the original: along with Seerr's mapping to it.

The rename that was actually performed:

1. `PUT` the existing profile in **Radarr (id 10)** and **Sonarr (id 9)** with the new name, so the
   ids survive and nothing downstream has to be repointed.
2. Update all **32** references in `recyclarr.yml` (the profile plus every `assign_scores_to`).
3. Sync: both reported **"All quality profiles are up to date!"**, confirming recyclarr *matched*
   the renamed profile rather than creating one.
4. Refresh Seerr's cached `activeProfileName`. Cosmetic only: Seerr stores the profile **id**, which
   never changed, so requests were correct throughout.

> Seerr's `/api/v1/service/{radarr,sonarr}/{id}` briefly kept serving the **old** name from its
> cached copy of the service's profile list. It cleared on its own within ~20s. If a rename looks
> like it did not take in Seerr, check the app itself before assuming anything is wrong.

**Verified after the rename:** exactly one profile named `Avrana Compatible` per service, ids
unchanged (Radarr 10, Sonarr 9), profile counts unchanged (10 and 9), all policy scores intact
(`SDR +500`, `DV Boost -5000`, `HDR10+ Boost -5000`, `HLG -10000`, `DV (w/o HDR fallback) -10000`,
`x265 (HD) -10000`, `x265 +300`, `AAC/DD/DD+ 100/100/150`, `min_format_score -6000`), Seerr resolves
both defaults to the new name, no assignment moved, both queues empty.

### IMAX preference added to `Avrana Compatible` (2026-08-18, commit `cc86382`)

`IMAX` and `IMAX Enhanced` score **+500** on the Radarr compatibility profile. Sonarr is
unchanged.

It is an **independent preference layered on top of** the compatibility rules, never an override:
big enough to beat an otherwise-equivalent non-IMAX release (and the 100-150 audio tiebreaker),
far too small to rescue anything excluded. Verified:

| Release | Score | |
|---|---:|---|
| 2160p SDR IMAX tier 1 | +3150 | preferred |
| 2160p SDR non-IMAX tier 1 | +2650 | |
| IMAX + DV+HDR10+ | -7350 | still blocked |
| IMAX + DV-only | -14050 | still blocked |
| IMAX + 1080p x265 | -7350 | still blocked |

**This is a filename heuristic only.** Whether the downloaded file really contains expanded
framing is decided by frame analysis in
[IMAX framing verification](../../docs/services/imax-verify.md),
which is wired to Radarr as a post-import webhook and reports PASS / FAIL / UNKNOWN without
actioning anything.

### DV-without-fallback guard added to `Avrana TV - 4K` (2026-08-18, commit `da08981`)

**The defect.** Sonarr's opt-in 4K profile (id 8) scored `DV (w/o HDR fallback)` at **0** instead of
TRaSH's **-10000**. A Dolby Vision release carrying no HDR10 base layer therefore graded identically
to a safe HDR10 copy and cleared the profile's `min_format_score` of 0.

This is the one HDR case that is a **correctness** problem rather than a compatibility preference.
With no base layer the picture is washed-out or green/purple on every client that cannot decode DV,
and this host's Jellyfin (Skylake / Gen9 QuickSync) cannot transcode 4K HDR to rescue it. It is
wrong on the premium path too, not merely non-ideal: which is why it is guarded here even though
`Avrana TV - 4K` is the opt-in profile.

**The cause is structural, not a missed line.** `reset_unmatched_scores` resets every custom
format a profile does not explicitly claim in `assign_scores_to` to **0**: and that includes guide
defaults that exist as *safeguards* rather than preferences. Radarr's two premium profiles were
unaffected only because they are *trash-template* profiles, where the `[HDR Formats]` group binds
automatically. Anything locally named gets nothing it did not ask for.

> **Rule: a locally-named profile inherits nothing: audit it against the guide defaults, do not
> assume the safeguards came along.** The audit is cheap: pull `/api/v3/qualityprofile/{id}` and
> compare each `formatItems` score against `trash_scores.default` in the guide's CF JSON
> (`config/repositories/trash-guides/docs/json/{sonarr,radarr}/cf/`), flagging anything strongly
> negative that sits at 0. This is the same class of trap as *"custom-named profiles need explicit
> `assign_scores_to`"*, and it also fails silently with a clean exit 0.

#### Not mirrored onto this profile, on purpose

Three other formats also sit at 0 against a -10000 guide default. All three were left alone, and the
reasons are not the same:

| Format | Guide | Why it stays at 0 |
|---|---:|---|
| `HLG` | -10000 | Broadcast-origin HDR, effectively unreachable through this profile's WEB-2160p-only ladder. Radarr's premium profiles also leave it at 0, so this stays consistent with them. |
| `x265 (HD)` | -10000 | Penalizes 1080p HEVC. The profile allows no 1080p quality at all, so it can never fire. |
| `SDR` | -10000 | **Must stay at 0.** TRaSH penalizes SDR because its 2160p profiles want HDR; here SDR is the preferred outcome, so the guide default would invert the entire point of this deployment. The format also hard-requires 2160p, so it is inert on `Avrana TV - 1080p` regardless. |

DV *with* an HDR10 fallback stays unpenalized. Premium remains the DV path: the guard removes the
broken variant, not Dolby Vision.

#### Verified (Sonarr's own `/api/v3/parse`, read-only)

Profile totals for the parsed release, against `min_format_score: 0`:

| Release title | Guard | Score | |
|---|---|---:|---|
| `2160p.AMZN.WEB-DL.DV.HEVC` | hit | -8225 | **rejected** |
| `2160p.NF.WEB-DL.DoVi.HEVC` | hit | -8150 | **rejected** |
| `2160p.ATVP.WEB-DL.Dolby.Vision.H265` | hit | -8225 | **rejected** |
| `2160p.AMZN.WEB-DL.DV.HDR10.HEVC` |: | +1775 | accepted |
| `2160p.AMZN.WEB-DL.HDR10.HEVC` |: | +1775 | accepted |
| `2160p.AMZN.WEB-DL.HEVC` (SDR) |: | +1775 | accepted |

All three DV spellings the custom format recognises (`DV`, `DoVi`, `Dolby.Vision`) are caught. The
margin is safe rather than marginal: the largest positive total reachable in this profile is roughly
**+1782** (WEB Tier 01 1700 + streaming service 75 + repack 7), so a -10000 penalty cannot be
climbed back over.

#### Scope and verification method

**Zero series use profile 8** and both queues were empty, so nothing could be re-graded or
re-grabbed by this change. `recyclarr sync sonarr -i avrana --preview --log debug` was run first and
printed exactly one line: `DV (w/o HDR fallback) (41): 0 -> -10000 (Updated)`: which is also the
check that catches the silent-no-scores trap. After the real sync, a field-by-field diff of
`/api/v3/qualityprofile/{7,8,9}` against the pre-change export confirmed **one** score change in
total and no setting changes anywhere.

Pre- and post-change exports (all three profiles and both copies of `recyclarr.yml`):
`/mnt/avrana_media/.backups/sonarr-dvguard-20260818T212449Z/`

#### Extended to `Avrana TV - 1080p` (2026-08-18, commit `4481823`)

The sibling profile had the identical defect and was closed out the same day. `Avrana TV - 1080p`
(id 7) is locally named too, so `reset_unmatched_scores` had left **both** `DV (w/o HDR fallback)`
**and** `HLG` at 0 against a -10000 guide default. Both are now scored -10000 there.

DV is rare at 1080p and HLG rarer still, so in practice both guards are close to inert. That is not
a reason to leave known-broken formats admissible on the one Sonarr profile that **has a series
assigned to it** (Parks and Recreation, 125/138 episodes, monitored). The safety argument is what
makes this cheap: **a negative custom format score can only reject a candidate release: it can
never make an existing file upgrade-eligible.** So unlike migrating the profile outright, this
cannot trigger the ~122-episode re-download that the earlier migration test predicted.

`HLG` is scored **explicitly** here rather than inheriting TRaSH's -10000 the way the
`Avrana Compatible` entry does. The lesson of this profile's DV gap is that anything a
locally-named profile does not claim outright silently becomes 0.

| Release title (profile 7, `min_format_score: 0`) | Score | |
|---|---:|---|
| `1080p.AMZN.WEB-DL.DV.H264` | -8225 | **rejected** |
| `1080p.AMZN.WEB-DL.HLG.H264` | -8225 | **rejected** |
| `1080p.AMZN.WEB-DL.DV.HDR10.H264` | +1775 | accepted |
| `1080p.AMZN.WEB-DL.H264` | +1775 | accepted |
| `1080p.BluRay.x264` | 0 | accepted |

Preview showed exactly two lines, both on profile 7; the post-sync API diff confirmed 2 score
changes and 0 setting changes there, with profiles 8 and 9 untouched. Exports:
`/mnt/avrana_media/.backups/sonarr-dvguard-1080p-20260818T215924Z/`

> **The remaining asymmetry is intended, not an oversight.** `Avrana TV - 4K` guards
> `DV (w/o HDR fallback)` but **not** `HLG`. DV without a base layer is broken on every client that
> cannot decode DV, so it is wrong everywhere. HLG is a *valid* HDR format that is merely wrong for
> this household's TV: and the opt-in 4K profile is precisely the path that knowingly accepts
> compatibility risk, the same way Radarr's premium profiles do. If `Avrana TV - 4K` ever becomes a
> default rather than an opt-in, revisit this along with the HDR10+ boost on the Radarr premium
> profiles.


## Library-wide compatibility swap (2026-08-19)

**426.7 GiB → 178.8 GiB, a net −247.9 GiB**, and Dolby Vision / HDR10+ removed from 11 of 13
titles. This deliberately overrode the standing "no mass replacement" ground rule, on Cody's
explicit instruction after the risk was stated.

### Method

For each red-flag title, an interactive search was scored **against `Avrana Compatible` (Radarr
10)**: computing scores locally from each release's matched custom formats, because Radarr's
`customFormatScore` in a search response is relative to the movie's *current* profile, not the one
you intend. Candidates were then filtered to: quality inside the profile's allowed set, score
above `min_format_score`, **no DV, no HDR10+, and under 40 Mbps**. Every movie was moved to profile
10 before grabbing.

> **12 of the 13 were on stock profile 5 (`Ultra-HD`)**: almost none of this library had ever
> been under a managed profile. That is now fixed as a side effect.

### Outcome

| Result | Titles |
|---|---|
| **Swapped clean** (DV/HDR10+ gone) | Troy, The Dark Knight, The Dark Knight Rises, Obsession, Event Horizon, Mandalorian & Grogu, Batman: Under the Red Hood, Minions & Monsters, The Invite, Avatar Aang, Superman |
| **Unchanged: every candidate failed** | **Supergirl** (still DV HDR10+), **Transformers One** (still DV) |

All 11 replaced originals are in `/data/.recycle/radarr` with **30-day retention**.

### Four things went wrong. All are worth knowing.

**1. SABnzbd wedged the entire queue.** Troy's NZB (150 days old) shed **15,265 articles**
(`unavailable on all servers`), and that churn raced SAB's state writer:

```
File "sabnzbd/filesystem.py", line 1138, in save_data
    pickle.dump(data, data_file, protocol=pickle.HIGHEST_PROTOCOL)
RuntimeError: set changed size during iteration
```

The job's admin file could not be saved, so it sat at **100% / 0 MB left** and never finalised,
looping `Ending job → Found idle job → Resetting bad trylist` every 30 s. SAB reported `Idle`,
0 KB/s, zero connections: **with 163 GB still queued**. It is a SAB bug, not a disk problem
(5.7 T free, 1% inodes, filesystem rw, write test passed, no kernel I/O errors).
**Fix: remove the stuck job. The queue resumed instantly at 42 MB/s with no restart needed.**

**2. Prowlarr guids drift between search and grab.** Supergirl was grabbed as
`...YKW...HONE` (20.1 G) when `...BYNDR` (16.3 G) had been selected: the guid captured at 00:20
resolved to a different result at 00:40. **Always verify against Radarr history what was actually
grabbed; do not assume the plan held.**

**3. `Not a quality revision upgrade for existing movie file(s)`** blocks import when the
replacement is the same quality tier and there is no PROPER/REPACK bump (hit Avatar Aang,
2160p→2160p). Cleared with a `ManualImport` command. Not universal: Mandalorian's
2160p→1080p downgrade imported by itself.

**4. Failed-download handling silently substituted different releases: and reintroduced DV.**
`autoRedownloadFailed: True` **and `autoRedownloadFailedFromInteractiveSearch: True`** mean that
when a hand-picked release fails, Radarr immediately searches and grabs something else without
asking. Both the TDKR IMAX release (809 days old) and the Superman 4K release failed with
`Aborted, cannot be completed`, and substitutes were grabbed and imported within ~10 seconds:

| Intended | Actually imported |
|---|---|
| `TDKR.2012.IMAX.UHD.BluRay.2160p...DV.HDR.x265-hallowed` (19.4 G, 4K, IMAX) | `TDKR.2012.PROPER.1080p.UHD.BluRay...x264-LoRD` (15.4 G, 1080p, no IMAX) |
| `Superman.2025.2160p.AMZN.WEB-DL...H.265-BYNDR` (15.0 G, 4K) | `Superman.2025.REPACK.1080p.BluRay.x264-KNiVES` (14.8 G, 1080p) |

Supergirl and Transformers One then entered a **retry storm**: repeated grab/fail cycles roughly
once a minute: and every automatic pick was a **DV** release
(`Supergirl...DV.HDR.H.265`, `Transformers.One...DV.HDR.H.265`). Both titles ended unchanged.

> **The structural lesson: `Avrana Compatible` PERMITS Dolby Vision as a last resort**: DV scores
> −5000 against `min_format_score` −6000, so a DV release with normal positives still clears the
> gate. The manual selection filtered DV out explicitly; **Radarr's automatic search does not and
> will happily grab DV when the clean options fail.** If DV must never be auto-selected, DV has to
> score below −6000 on its own, or `autoRedownloadFailedFromInteractiveSearch` has to be off.

### Consequence worth flagging

The Dark Knight Rises' original file was measured at **~55 minutes of genuine IMAX expanded
framing** (see [IMAX framing verification](../../docs/services/imax-verify.md))
and has been replaced by a 1080p release with no IMAX marker. The original is recoverable from the
recycle bin until roughly 2026-09-18.


## Pre-HD series, and the language gate that was missing (2026-08-20)

Three separate faults, all found by trying to grab two Disney cartoons.

### 1. `Avrana Compatible` has no rung below 1080p

A series predating HD broadcast returns **zero approved releases** and sits silently at 0 episodes
with **no history entries at all**, which reads as a failure rather than an absence. Measured:

| Series | Releases found | Approved | Ceiling that exists |
|---|---:|---:|---|
| House of Mouse (2001) | 111 | 0 | 720p |
| Aladdin (1994) | 139 | 0 | SD |

The rejection reasons say it plainly, and this is the diagnostic to run first:

    13x  SDTV is not wanted in profile
    13x  HDTV-720p is not wanted in profile
    14x  Unknown is not wanted in profile

### 2. Lowering the floor alone would have made it worse

For both shows the **higher quality tier is the wrong language**, and Sonarr ranks quality tier
above custom format score:

| Series | Higher tier | Lower tier |
|---|---|---|
| House of Mouse | 720p **Spanish** | SD English |
| Aladdin | 480p **Greek / Japanese** | SD English |

A permissive profile would have systematically grabbed the foreign copy. The fix is not a lower
floor, it is a language constraint plus a single quality group.

### 3. NEW: `Avrana Legacy` (Sonarr profile 10)

Opt-in, assigned per series, nothing uses it by default.

| | |
|---|---|
| Quality | ONE group `Legacy 720p/SD`: Bluray/WEBDL/WEBRip/HDTV-720p, SDTV, 480p, DVD, Bluray-480p/576p |
| `min_format_score` | 0 |
| `Language: Not English` | **-10000** (hard rejection) |
| `720p` | **+100** |

The single group is the poin: inside it every quality ranks equally, so **custom format score
decides instead of resolution**. Same mechanism `Avrana Compatible` uses for 1080p/2160p. `720p` is
scored +100 rather than the guide's +5 so it is decisive inside that group.

**Validated by replaying it over 344 real releases before assigning it to anything:** Aladdin would
have been fully automatic (86 of 86 correct); House of Mouse 48 of 52.

**Known blind spot:** the 4 it misses are Spanish rips Sonarr tags `[English, Spanish]`. English is
present, so the negated language spec does not fire, and the +100 for 720p then beats the English
SD copy. No TRaSH format catches them (`MULTi` keys on the literal word "Multi", which their titles
lack). The fix would be a hand-made CF (non-negated `LanguageSpecification` on Spanish, OR-ed with
other languages) at -10000, which also means `reset_unmatched_scores: false` on that profile so
Recyclarr stops zeroing it. Not implemented: one series' worth of edge case, and unmanaged formats
are their own maintenance burden.

### 4. `Avrana Compatible` had NO language gate, and it cost real files

**The Legend of Tarzan imported 27 DANISH episodes.** For a 2001 show the Danish 1080p WEB-DL was
the only 1080p in existence, and the profile judged it on quality alone. A further **36 queue items
were the same release's `.iNCOMPLETE.` pack**, permanently stuck on "No files found are eligible
for import".

`Language: Not English` **already existed** in Sonarr (created when Avrana Legacy was added) and
sat at score **0**, because `reset_unmatched_scores` zeroes anything the config does not explicitly
claim. It looked like protection and rejected nothing.

> **This is the third time this exact failure has occurred.** `DV (w/o HDR fallback)` at 0 on
> `Avrana TV - 4K`, the same on `Avrana TV - 1080p`, and now `Language: Not English` at 0 on
> `Avrana Compatible`. **A custom format existing in Sonarr means nothing. Only an explicit
> `assign_scores_to` entry does.** Audit any locally-named profile against the guide defaults
> rather than assuming.

Now scored **-10000** on both profiles. Against Compatible's `min_format_score` of -6000 that is a
hard rejection. Without it, ANY foreign-language 1080p or 2160p release is grabbable for ANY series
on that profile. Not an old-cartoon problem.

### What was actually grabbed

Manual override grabs, profile untouched at the time, English-only filtering done in the grab
script rather than the profile:

| Series | Result |
|---|---|
| House of Mouse | **52/52** regular episodes (25 x 720p English, 27 x SDTV). 2 season-0 specials have no English release |
| Aladdin | **86/86** regular episodes (85 x SDTV, 1 x WEBRip-480p). 4 season-0 specials have no English release |
| The Legend of Tarzan | **removed entirely**, see below |

Two files needed replacing afterwards: Aladdin S01E12 was **Greek** despite Sonarr tagging it
English (title said `GREEK`), and House of Mouse S04E02 had failed and was `monitored=False`, so
nothing retried it. Both replaced. Aladdin S01E12 required a forced `ManualImport` because the
Greek file was `WEBRip-480p` and the English replacement `SDTV`, so Sonarr refused it as a
downgrade: **quality tier outranking correctness, again.**

### Tarzan: removed

**No English copy exists on NZBgeek**, verified three ways: season search (31 releases, all
Danish), episode-level searches for S01E28 / S01E36 / S02E01 (0 releases each), and raw Prowlarr
searches on three title variants. Every non-Danish hit is a different work (the 2016 live-action
film, the 1999 animated film, a 1996 Spanish series).

> **Scope limit worth remembering: there is ONE indexer, NZBgeek, Usenet only.** The accurate
> statement is "no English copy on NZBgeek", not "none exists". Usenet retention favours recent
> content, and a 2001 Disney Channel series depends entirely on whether anyone backfilled it. If a
> second indexer or torrent support is ever added, this show is the first thing to re-check.

Series deleted with files. 27 files / 23 GB recoverable from `/data/.recycle/sonarr/The Legend of
Tarzan` for 30 days; series metadata in
`/mnt/avrana_media/.backups/tarzan-remove-20260820T202200Z/`. Also cleared from Jellyfin (library
refresh) and Seerr (request 24 and media 34 deleted), so it does not linger as a half-fulfilled
request.

### Seerr shows Aladdin as "processing" forever, and that is not a fault

**Sonarr organises by TVDB, Seerr checks availability against TMDB, and they disagree about this
show's seasons:**

    TVDB (Sonarr + Jellyfin):  S1=65  S2=13  S3=8      total 86
    TMDB (Seerr):              S1=9   S2=69  S3=8   (+ S0=3)

Same 86 episodes, different season split. Seerr sees 13 of an expected 69 in season 2 and never
marks the request available. Nothing is missing. Mark it available by hand.

House of Mouse proves the mechanism: there TMDB and TVDB agree, and Seerr correctly reported
`S1 AVAILABLE, S2 AVAILABLE, S3 PARTIAL`, the partial being the one genuinely failed episode.

> **Any future stalled-request alerting should key off Sonarr's file counts, not Seerr's status.**
> A Sonarr-based check stays correctly quiet for Aladdin; a Seerr-based one would alert forever.

### Sonarr cannot notify on this

The complete event list is `onGrab, onDownload, onUpgrade, onImportComplete, onRename,
onSeriesAdd, onSeriesDelete, onEpisodeFileDelete, onEpisodeFileDeleteForUpgrade, onHealthIssue,
onHealthRestored, onApplicationUpdate, onManualInteractionRequired`. **There is no event for
"searched and found nothing acceptable"**, so no Connect notification can cover it. The failure is
defined by absence. Detecting it needs a periodic check (monitored, added more than N hours ago,
zero files, nothing in queue), which `scripts/services-health.sh` is the natural host for. Not
built.
