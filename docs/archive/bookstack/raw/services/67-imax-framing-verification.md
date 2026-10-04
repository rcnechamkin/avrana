---
bookstack_page_id: 67
title: "IMAX framing verification"
shelf: "Avrana Homelab"
book: "Services"
chapter: ""
created: 2026-08-18 20:23:04
updated: 2026-08-21 00:15:15
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/imax-verify.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/imax-verify.md`.

# IMAX framing verification
# IMAX framing verification

**`services/avrana-imax-verify/`**, LAN-only on `10.0.0.218:8099`.
Commits `cc86382`, `ebe359c`, `816201c`.

Two halves that must not be confused:

| | |
|---|---|
| **Selection** | Recyclarr scores TRaSH's `IMAX` / `IMAX Enhanced` at **+500** so likely IMAX releases win. Reads the **filename**. |
| **Verification** | This service decodes the file that actually arrived and measures the picture. Reads **frames**. |

**The file is the final authority.** A release named `.IMAX.` proves nothing, and neither does a
`3840x2160` container: scope films are routinely stored 2160-high with the bars encoded in.

## Workflow

```
Radarr imports a release that matched IMAX/IMAX Enhanced
        -> webhook (returns immediately; Radarr is never blocked)
        -> queued, one job at a time
        -> defer while Jellyfin is transcoding
        -> ffprobe + ffmpeg cropdetect on 60 samples
        -> PASS / FAIL / UNKNOWN
        -> Radarr tag + history + (FAIL only) optional notification
```

**Only IMAX-matched imports are verified.** The gate reads Radarr's own `customFormats` where
present and falls back to the release name. Anything else is acknowledged and dropped, so this
never becomes a library scanner. There is no scheduled or bulk scan.

## Verdicts

| | |
|---|---|
| **PASS** | substantial expanded framing (**1.40-1.96**), constant or in sequences |
| **FAIL** | IMAX claimed, but scope (>=2.30) throughout |
| **UNKNOWN** | inconclusive, too few usable samples, or nothing claimed. **A real answer.** |

Thresholds: expanded share >= **10%** to pass; scope >= **90%** with < 3% expanded to fail;
at least 8 usable samples and >= 50% of those requested, or the run is inconclusive.

> The expanded band has a **floor at 1.40** as well as a ceiling. Without it, 4:3 academy content
> (1.33) counts as expansion and a 1440x1080 cartoon falsely PASSES -- which is exactly what
> happened on Batman Beyond before the floor existed.

## Optional sourced expectations

`expectations.json`, keyed by TMDB id. **Not the primary mechanism, and not meant to grow.**
It ships with **zero entries**: the normal path needs none, and inventing one is worse than
UNKNOWN.

An entry has authority only with **`source_url` AND `confidence` (high/medium)**. Anything else
is advisory: recorded and displayed, but it can **never cause a FAIL**. Fields also carry
`edition` (a Disney+ IMAX Enhanced stream and a disc can differ for the same film),
`mode` (`variable` / `full` / `none`), `expected_ratio`, `base_ratio`, `min_expanded_share`,
`tolerance` and `notes`.

Prefer official IMAX or studio information. **No disc-database scraping** -- brittle and not worth
the coupling. The verifier works identically for disc-derived files and WEB-DLs.

## Surfacing results

**Radarr tags**, mutually exclusive: `imax-verified`, `imax-failed`, `imax-unknown`. Written back
after each run; the other two are cleared.

**History** in `results/history.jsonl`, one row per verification: TMDB and Radarr ids, filename,
verdict and reason, claimed/expected ratios, full ratio distribution with share and approximate
runtime, usable vs requested samples, elapsed time, timestamp. Per-movie detail in
`results/<tmdb>.json`. Served from `/history` and `/results`.

**Notifications: FAIL only, never routine PASS.** Avrana has no notification platform, so none was
built. `IMAX_NOTIFY_CMD` is a command template (`{json}`, `{title}`, `{reason}` substituted),
empty by default.

## Resource behaviour

This box cannot transcode and analyse at the same time, so verification always yields:

- ffmpeg pinned to **one thread** (`-threads` and `-filter_threads`)
- every child at **nice 19** and **I/O class idle**
- **one job at a time**, container capped at `cpus: 1.0`
- **defers while Jellyfin is transcoding** -- polls `/Sessions`, ignores direct-play sessions,
  gives up after 3h so a stuck session cannot stall the queue forever
- Radarr is never blocked; the webhook returns before analysis starts

Measured: ~70s for a 1080p file, ~3-9 min for a 4K HEVC remux, at 60 samples.

## Safety (unchanged, deliberate)

Nothing is **deleted**, **blocklisted** or **re-searched**, and no library-wide check runs.
Automatic remediation is left for later, once FAIL has demonstrated reliability in the history.

## Validation

| Case | File | Result |
|---|---|---|
| Fixed 2.39, falsely claimed IMAX | Wicked (1080p) | **FAIL** -- 100% scope, tagged `imax-failed` |
| Baked-in bars in a 3840x2160 frame | Troy (4K remux) | **FAIL** -- 100% scope, dominant 2.39 |
| Variable ratios | The Dark Knight | **PASS** -- 17% expanded ~25 min, tagged `imax-verified` |
| 4:3 academy | Batman Beyond | **UNKNOWN** -- correctly not a false PASS |
| Selection gate | synthetic imports | `["WEB Tier 01","SDR"]` skipped; `["IMAX"]` queued |
| Dark scenes / fades / credits | all runs | head 4% + tail 8% skipped, dark frames rejected, lone buckets excluded |

16/16 verdict unit tests pass (`tests/test_classify.py`, synthetic distributions, no media).

## Known limitations

- **Runtime.** Minutes per 4K file. Fine post-import, far too slow to sweep a library.
- **`cropdetect`'s limit is scaled to the pixel format, not 0-255.** At the usual 24 on 10-bit HDR
  the bars are never found, every file looks full-frame and every title falsely PASSES. Scaled by
  bit depth (10-bit -> 96). **Re-check on new pixel formats or ffmpeg versions.**
- **Isolated samples are ignored by design**, and shares are renormalised afterwards. An expanded
  sequence shorter than ~5% of runtime may be missed.
- **It cannot tell IMAX from open matte** -- both use a taller picture.
- **Framing only.** Says nothing about HDR, Dolby Vision, bitrate or audio.
- **Radarr's path must match the mount** (both `/data`).

## Running it by hand

```bash
cd /home/cody/avrana/services/avrana-imax-verify
docker run --rm --user 1000:1000 \
  -v /mnt/avrana_media:/data:ro -v "$PWD":/config \
  -e IMAX_EXPECTATIONS=/config/expectations.json -e IMAX_RESULTS=/config/results \
  --cpus 1 avrana-imax-verify:1 \
  python3 /app/imax_verify.py --tmdb 155 --samples 60 --claimed-imax --save \
  "/data/movies/The Dark Knight (2008)/<file>.mkv"
```

`--json` prints per-sample detail; `--samples` trades runtime for resolution.

> **Always pass `--user 1000:1000`.** Without it the container writes root-owned files into
> `results/` that the service (uid 1000) cannot overwrite -- an 8-minute analysis once completed
> and failed to save exactly this way.

Endpoints: `/health` (includes `jellyfin_busy`), `/results`, `/history`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `IMAX_SAMPLES` | 60 | samples across the runtime |
| `IMAX_FFMPEG_THREADS` | 1 | ffmpeg threads per invocation |
| `JELLYFIN_URL` / `JELLYFIN_API_KEY` | set | transcode deferral; blank disables |
| `IMAX_DEFER_POLL_S` / `IMAX_DEFER_MAX_S` | 60 / 10800 | deferral poll and give-up |
| `RADARR_URL` / `RADARR_API_KEY` | set | tag write-back only |
| `IMAX_NOTIFY_CMD` | empty | FAIL hook |

Credentials live in the gitignored `services/avrana-imax-verify/.env` (mode 600).

## Classifier defec: the verdict is sound, the numbers are not (2026-08-19)

**The tool classifies on aspect ratio. The reliable signal for letterboxing is crop HEIGHT at full
width.** Width is contaminated by dark scene content pulling `cropdetect` inward, and those
contaminated samples carry noisy ratios that drift in and out of the 1.40-1.96 expanded band
depending on which frames happen to be sampled.

Demonstrated on Project Hail Mary: same file, same code, same day, only the sample count changed:

| | 60 samples | 150 samples | swing |
|---|---:|---:|---:|
| Tool's AR-based expanded share | 75% | **49%** | **26 pts** |
| Tool's "expanded runtime" | ~50 min | **~23 min** | 2.2× |
| Height-based share (full-height ÷ clean samples) | 66% | **68%** | 2 pts |

Mechanism: **31 of 142 samples (22%) had geometry that was neither full-height nor scope**: e.g.
`1652x1080`, `1594x1080`, `1072x702`. Only 20 of the 79 band-matching samples were clean full
width. Letterboxing reduces *height*; a reduced *width* is content, not framing.

> **Why this matters: the PASS threshold is 10% expanded, and the instability is 26 points.** On
> any title whose true share sits near the threshold: the exact ambiguous case the tool exists to
> adjudicate: the verdict is decided by sampling luck. The Dark Knight, an existing PASS, sits at
> **17%**, inside that band.

**Proposed fix (not implemented):** classify on crop height at full width, and exclude
contaminated samples from the denominator rather than letting their ratios vote. This changes
verdict logic, so it needs the 16 verdict unit tests re-run and the existing results re-verified.

### Measurements taken 2026-08-19

| Title | Verdict | Geometry | Reading |
|---|---|---|---|
| Project Hail Mary (1080p BluRay) | PASS | mixed, 22% contaminated | genuine variable framing, ~⅔ expanded; height-based 66-68% |
| The Mandalorian and Grogu (1080p IMAX BluRay) | PASS |: | 68% expanded, ~56 min |
| **The Dark Knight Rises** (4K DV remux) | UNKNOWN* | **34× `3840x1600`, 20× `3840x2160`, 6 noise** | textbook variable IMAX, **33-38% expanded, ~55 min** |
| **Superman** (1080p AV1) | UNKNOWN* | **43× `1920x1012`** | **constant 1.90:1**: the digital IMAX ratio, ~97 min |

\* UNKNOWN only because the release name carried no IMAX marker and no sourced expectation exists :
the *measurement* in both cases is unambiguous. The verdict gate and the measurement are separate
things, and a lack of an IMAX claim should not be read as a lack of IMAX framing.

**Superman also exposed a limit of the height heuristic itself:** a constant 1.90 presentation is
neither 1.78-full-height nor 2.39-scope, so a naive height classifier scores it 100% contaminated.
The underlying data was in fact exceptionally clean (43 identical crops). Any fix must handle
constant non-1.78 presentations, not just the 1.78-vs-2.39 variable case.

> Both of those files have since been replaced (see
> [Radarr / Sonarr](http://10.0.0.218:6875/books/services/page/radarr-sonarr)); the originals are
> in the Radarr recycle bin for 30 days.
