---
bookstack_page_id: 68
title: "2026-08-18: Profiles and IMAX Verification"
shelf: "Avrana Homelab"
book: "Change Log (Archive)"
chapter: ""
created: 2026-08-18 20:53:25
updated: 2026-08-21 00:16:00
last_editor: "Cody"
revisions: 4
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Change log.

# 2026-08-18: Profiles and IMAX Verification
# 2026-08-18: Profiles and IMAX Verification

Continue the Avrana homelab (`/home/cody/avrana`, host `10.0.0.218`). This session covered
**Radarr/Sonarr quality profiles** and a new **IMAX framing verifier**, plus fixes to several
unrelated services. Read this before touching quality profiles or the verifier.

Canonical docs: BookStack `Radarr / Sonarr` (page 23), `IMAX framing verification` (page 67),
`Jellyfin` (page 22), `Calibre-Web-Automated` (page 15), `Roadmap / Open TODOs` (page 36).
The wider project frame lives on the separate **Kern** shelf (created this session, docs only).

---

## 1. Where quality profiles ended up

All profile work is Recyclarr-managed in `services/recyclarr/config/recyclarr.yml`, one instance,
nightly sync at 04:00. **Nothing is assigned to any profile by that file**: a sync can never
start an upgrade.

| Service | Profile | id | Role |
|---|---|---|---|
| Radarr | `UHD Bluray + WEB` | 8 | premium, untouched |
| Radarr | `Remux + WEB 2160p` | 9 | premium + IMAX, untouched |
| Radarr | **`Avrana Compatible`** | **10** | **default** |
| Sonarr | `Avrana TV - 1080p` | 7 | earlier profile, kept |
| Sonarr | `Avrana TV - 4K` | 8 | opt-in, kept |
| Sonarr | **`Avrana Compatible`** | **9** | **default** |

Seerr defaults point at Radarr 10 and Sonarr 9. Premium profiles remain selectable.

### What `Avrana Compatible` encodes

Final hierarchy: **4K HEVC SDR or HDR10 → good source → 1080p H.264 SDR fallback**, with
Dolby Vision / HDR10+ / HLG pushed to last resort and premium profiles as the opt-in path.

Measured scores (both services):

| Release | Score |
|---|---:|
| 2160p SDR x265 tier 1 | +2650 |
| 2160p HDR10 x265 tier 1 | +2150 |
| 1080p SDR x264 tier 1 | +1850 |
| 2160p DV / HDR10+ | −2850 (last resort) |
| DV+HDR10+ / HLG / 1080p x265 | −7850 (blocked) |
| 2160p DV-only | −14550 (blocked) |

`min_format_score` −6000. IMAX / IMAX Enhanced +500 (Radarr only).

**Three mechanisms worth understanding before editing:**

1. **All allowed qualities sit in ONE quality group.** Radarr and Sonarr sort by **quality tier
   first** and custom-format score only second. With separate tiers a 2160p HDR release always
   beats a 1080p SDR one no matter how negative its score. Collapsing them is what lets scoring
   decide. Remux tiers are excluded outright.
2. **The broad TRaSH `HDR` format is one lever for six ranges** (DV-with-fallback, HDR, HDR10,
   HDR10+, HLG, PQ). It is deliberately held at **0** so HDR10 is not punished; DV, HDR10+ and
   HLG are penalized individually.
3. **Custom-named profiles need explicit `assign_scores_to`.** CF groups bind to trash-template
   profiles via a compatibility list, so a locally-named profile silently gets **no scores at
   all** and the sync still exits 0. A `--preview` run is what catches this.

---

## 2. IMAX: selection + verification

**Two halves. Do not conflate them.**

- **Selection**: Recyclarr scores `IMAX` / `IMAX Enhanced` at +500 on Radarr's `Avrana
  Compatible`. This reads the **filename**. +500 beats an equivalent non-IMAX release but cannot
  rescue anything excluded (IMAX + DV-only is still −14050).
- **Verification**: `services/avrana-imax-verify/`, LAN-only on `10.0.0.218:8099`, decodes the
  file that actually arrived. **The file is the final authority.**

Flow: Radarr imports a release that **matched IMAX** → webhook (returns immediately) → queued,
one job at a time → defers while Jellyfin transcodes → ffprobe + ffmpeg `cropdetect` on 60
samples → PASS / FAIL / UNKNOWN → Radarr tag + history + optional FAIL hook.

- Verdicts: expanded framing **1.40-1.96** ≥10% → PASS; scope ≥2.30 throughout → FAIL;
  otherwise UNKNOWN.
- Tags: `imax-verified` / `imax-failed` / `imax-unknown`, mutually exclusive.
- History: `results/history.jsonl` + per-movie `results/<tmdb>.json`; `/health`, `/results`,
  `/history`.
- `expectations.json` is **optional, ships empty**, and an entry needs `source_url` +
  `confidence` to have authority. Unsourced entries can never cause a FAIL.

**Safety, deliberate and unchanged: nothing is deleted, blocklisted or re-searched, and there is
no library-wide scan.** Automatic remediation is intentionally unimplemented behind
`IMAX_ACTION_ON_FAIL` until FAIL proves reliable.

Validated on real files: Wicked (fixed 2.39, falsely claimed) → FAIL; Troy (baked-in bars in a
3840x2160 frame) → FAIL; The Dark Knight (variable) → PASS, 17% expanded ~25 min; Batman Beyond
(4:3) → UNKNOWN. 16/16 verdict unit tests.

---

## 3. Bugs found this session

### In my own new code (all found by testing against real files)

| Bug | Effect | Status |
|---|---|---|
| `cropdetect` limit not scaled to pixel format | On 10-bit HDR the bars are never detected, every file looks full-frame and **every title falsely PASSES**. limit 24 → 3840x2160; limit 96 → 3840x1600 | fixed (scale by bit depth) |
| No noise floor on the ratio histogram | Three lone dark-frame buckets summed to 25% and produced a **false FAIL** on a scope-only film | fixed (floor + report-but-exclude) |
| Expanded band had no lower bound | 4:3 academy (1.33) counted as IMAX expansion; a 1440x1080 cartoon **falsely PASSED** | fixed (band 1.40-1.96) |
| De-noised shares not renormalised | Thresholds silently understated; scope-throughout read 69% and returned UNKNOWN instead of FAIL | fixed (renormalise) |
| Results written by root | CLI runs without `--user` created root-owned files; the service (uid 1000) then could not save. An 8-minute analysis completed and was lost | fixed (+ atomic write; always run CLI with `--user 1000:1000`) |
| Audio at TRaSH guide defaults | Including only the compatible subset left TrueHD at 0 and DD+ at 1750; a 2160p SDR TrueHD release scored 800 and **lost to a 1080p DD+ release at 3450** | fixed (100/100/150 tiebreaker) |
| HDR/LQ score band collision | At HDR −8000 an untiered HDR release and an LQ release both landed at −7700; no threshold could separate them | fixed (HDR re-banded to −5000) |
| `services/*/*` gitignore | First commit captured only `docker-compose.yml`; the verifier source was untracked | fixed (whitelist) |

### In upstream software

| Bug | Detail | Status |
|---|---|---|
| CWA: missing `book_format_checksums` | 120 errors/3h; `models.py` defines it, migration never ran. Belongs in **metadata.db** | fixed (table + indexes created) |
| CWA: `CWA_DB.close()` undefined | Every book deletion raised AttributeError and leaked a connection | fixed, commit `afe1d5b` |
| CWA: `CWA_DB.execute_write()` undefined | Hardcover auto-fetch ran successfully but **never saved stats**: an empty stats table looked like "the job never ran" | fixed, commit `c3dd499` |
| CWA: `books.author_sort` vs `authors.sort` | 29 of 104 books; case, inversion, and different-name mismatches | fixed (44 rewritten) |
| CWA: 5s self-request timeout | One skipped duplicate scan under bulk load | **not fixed, accepted** |
| `offboard.py`: silent delete failure | Raw SQL DELETE is refused by an FK whenever the user is in a group, and it reported success anyway. Would have hit **every real offboarding** | fixed, commit `1be9a12` |
| Seerr: TV library never enabled | Only the Movies library was scanned, so every TV request sat at "processing" forever | fixed |

### Traps worth remembering

- **`metadata.db` is WAL.** Copying it without `-wal`/`-shm` gives a stale snapsho: it read
  1 book when there were 122, which looked exactly like a failed import.
- **ABS/Radarr report *container* paths** (`/audiobooks/...`, `/data/movies/...`). Translate
  before any host-side file check.
- **Quality tier beats CF score** in both Radarr and Sonarr. This is the single most important
  rule in the profile design.
- **Renaming a Recyclarr profile:** rename in the **app first** (PUT on the existing id), then the
  config. Editing the config alone creates a duplicate and orphans the Seerr mapping.
- **Seerr caches service profile lists** for ~20s after a rename; check the app, not Seerr.

---

## 4. Hanging threads

### Needs something only Cody can provide

1. **Off-host backup: the only unrecoverable risk.** Verified still **not configured**: no
   `services/backups/offhost.env`, no timer. Backups sit on `/dev/sdb1` beside the media. Under
   1 GB total. **Needs a B2 or R2 key.**
2. **SMTP2GO API key is still live.** Removed from `services/smtp2go.env` and unused, but
   **removal is not revocation**: revoke it in the SMTP2GO dashboard.
3. **MyJDownloader password is compromised.** It was the *same string* as the old Komga admin
   password, which passed through a transcript. Komga's was rotated; MyJD's cannot be rotated
   from here. Use a distinct password.
4. **Plex is still `active`** and awaiting authorization to stop.
5. **Send-to-Kindle** needs the Amazon side: approve `cody@avrana.net` and supply a `@kindle.com`
   address.
6. **Bazarr** is shelved pending a subtitle-provider decision (OpenSubtitles.com needs an account).

### Decisions waiting

7. **Sonarr existing media was NOT migrated** to `Avrana Compatible`, deliberately. A test showed
   Sonarr would treat x264 replacements as upgrades and re-download ~150 episodes (Parks 122,
   Raised by Wolves 18, Batman 10). **Future-downloads-only.** There is no scheduled cutoff-unmet
   search, so nothing bulk-searches on its own: do not run one by hand without accepting that cost.
8. **Radarr still boosts HDR10+** (`[HDR Formats] HDR10+ Boost`, 1 reference remaining) on the two
   **premium** profiles: the exact range the household's main TV rejects. Harmless while premium
   is opt-in; remove it if premium ever becomes default on current hardware.
9. **Sonarr's 4K profile has no DV-without-fallback guard.** Radarr has one; Sonarr has no HDR
   custom formats at all. Add before anyone uses `Avrana TV - 4K`.
10. **~41 epubs sit in CWA unlinked** to their audiobooks (filename match too weak to auto-link).
    A loosened matcher pass was offered but not run.
11. **Komga backfill turned out to be a docs task, not an engineering one.** 5 of 6 members lack
    accounts, but Komga auto-creates on first SSO login with all libraries shared. Only OPDS needs
    a local password or API key, both self-service. Nothing was built.
12. **Hardcover auto-fetch left ENABLED** (weekly, Sunday 02:00). It was `0` before this session :
    a persistent behaviour change, flagged and not reverted. 90 of 91 books have Hardcover ids.

### Known-bad, documented, not acted on

13. **Jellyfin cannot transcode 4K HDR on this hardware.** One stream = ~326% CPU, load 7.6, zero
    idle. **12 of 24 movies** transcode on the main Roku: 5 HDR10+, 4 DV-without-fallback/P7,
    4 over the client's 40 Mbps ceiling, 1 VC-1.
14. **Tone-mapping is disabled**, so transcodes are *relabelled* rather than converted: viewers
    get a washed-out picture on top of the CPU cost.
15. **No `MaxConcurrentTranscodes` limit.** One transcode already saturates the box.
16. **Jellyfin sees every client as `127.0.0.1`** (traffic arrives via the tunnel), so
    `RemoteClientBitrateLimit` and any LAN/WAN rule cannot work.
17. **The compatibility profiles are a workaround for that hardware, not a preference.** The
    revert plan to the premium profiles is written on page 23; trigger is a better client
    (Shield / Apple TV 4K, ~$200, fixes ~10 of the 12) or a newer iGPU/GPU host.
18. **Do not replace The Dark Knight / The Dark Knight Rises.** Both are IMAX-expanded
    (3840x2160, 1.78 full-height, confirmed by frame analysis). Troy and Obsession (152 GB,
    DV Profile 7 with enhancement layer) are the better space-reclamation targets.

### From earlier in the session

19. **One real browser enrollment has never been done.** Verified-email enrollment + optional
    passkey is built and unit-tested, but the emailed-link click-through was never exercised by a
    human. Invite `avrana-full-access-2026-09` is waiting.
20. **`komf` is not deployed**: its config exists and now holds the rotated Komga password, but
    no container runs.
21. **Kern shelf** (BookStack, 5 books / 12 pages) is documentation only. Nothing named Kern is
    deployed, and Home Assistant is not installed.

---

## 5. Ground rules that held all session

- No mass searches, redownloads or replacements. Both queues empty throughout.
- Premium/IMAX profiles never deleted or modified.
- Every change diffed against a pre-change export before and after.
- Backups taken before every destructive or schema-level change, under
  `/mnt/avrana_media/.backups/`.
- Verify with the service's own API (`/api/v3/parse`, interactive search) rather than reasoning
  about what *should* happen.
