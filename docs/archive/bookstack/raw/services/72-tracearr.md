---
bookstack_page_id: 72
title: "Tracearr"
shelf: "Avrana Homelab"
book: "Services"
chapter: "Video and Requests"
created: 2026-08-21 17:15:00
updated: 2026-08-24 20:22:00
last_editor: "Cody"
revisions: 2
tags: []
source_format: markdown
classification: PROMOTE
destination: "docs/services/tracearr.md"
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-24; exported 2026-10-04. Classified PROMOTE; current information is in `docs/services/tracearr.md`.

# Tracearr
# Tracearr — Jellyfin playback analytics

**Status: deployed 2026-08-20.** Avrana's Jellyfin analytics layer. Chosen over Jellystat and
Streamystats deliberately — do not install those alongside.

## Purpose

Jellystat counts what was watched. Tracearr records **how it played** — direct play vs direct
stream vs transcode, codecs, source/output resolution, HDR, bitrate, client and device. That is
the data needed to diagnose client compatibility and transcoding problems on an i3-6100T, which
cannot transcode 4K HDR.

## Deployment

`ghcr.io/hankscafe/tracearr:supervised` pinned by digest (upstream v2.1.0). The **supervised**
image bundles PostgreSQL + TimescaleDB + Redis in one container via supervisord. The
alternative (`:latest`) needs three more containers on a 4-thread host. TimescaleDB matters —
upstream warns plain Postgres "works initially but long query histories kill performance".

- **http://10.0.0.218:5057** — LAN only, not on the tunnel (admin/analytics surface)
- Port 5057 because upstream's default 3000 is Homepage

## Storage — on the SSD, deliberately

Named volumes land on `/mnt/avrana_media/docker`, i.e. the **spinning array**. That is fatal for
a database here: measured fsync **775 ms on the array vs 1.33 ms on the SSD**. Volumes are bind
mounts under `/home/cody` instead. See the *SSD migration* change-log entry.

## Jellyfin integration — the SSE plugin is REQUIRED

Server "Avrana" → `http://10.0.0.218:8096`, own API key (not Homepage's).

> ⚠ **Upstream's docs are wrong on this point.** They say *"without it, Tracearr keeps working
> through polling; the plugin only removes the short polling delay."* On v2.1.0 that is false:
> **without the plugin, sessions are never persisted at all.** Live view works (polling reads
> Jellyfin directly), history stays permanently empty. `sessions` had `inserts_ever: 0`.

Fix: install **Tracearr SSE** (v0.4.1.0) in Jellyfin and restart it. Repository
`https://raw.githubusercontent.com/Tracearr/Media-Server-SSE/main/manifest.json`. Confirm with
`[PluginSSE] Connected to Avrana` and `exiting fallback mode` in the log.

This is the only Jellyfin-side modification made.

## Metrics captured

`is_transcode`, `video_decision`, `audio_decision`, `source_video_codec/width/height`,
`stream_video_codec`, `transcode_info`, `subtitle_info`, `bitrate`, `quality`, `device`,
`platform`, `product`, plus geo fields.

## Caveats

- **60-second startup crash loop.** `start-tracearr.sh` waits `30 × 2s` for Postgres then
  `exit 1`. On a slow disk it can burn 1–3 cycles before winning. Self-recovering, but it means
  brief downtime on every restart — and the container can report healthy while doing nothing.
- **`DATABASE_POOL_MAX` defaults to 95** against `max_connections=100`. Set to 50.
- **TimescaleDB telemetry** (`policy_telemetry`) is registered and runs daily.
- Health `/health` reports db/redis/geoip and TimescaleDB hypertable state.

## Backup

`./config` holds the DB. Not yet wired into `avrana-backup.sh` — **outstanding**.

## Case study — Galaxy Tab A SM-T510 playback failures (2026-08-24)

The first real diagnosis Tracearr produced, and one Jellystat could not have: the answer lives
entirely in `audio_decision`, `source_audio_codec` and `short_session`.

### Symptom

Playback on `cody's Tab A` died after 14–84 seconds, repeatedly. Sixteen start/stop entries in
Jellyfin's activity log across ~90 minutes. Three different clients registered on the tablet
(Findroid 1.1.0, Jellyfin for Android 2.7.1, Streamyfin 0.54.1) — app-swapping is itself a
signal that someone is fighting a codec problem.

### What the data showed

```text
file:     Batman: Caped Crusader - Brute Force (mkv)
video     h264 High, 1080p, 9.63 Mbps
audio     eac3, 6 channels, 640 kbps, English  <- the ONLY audio track

sessions  source EAC3 -> audio_decision = directplay  (no transcode)
          watched 84s / 67s / 62s / 14s, every one short_session = true
```

### Cause

The **SM-T510 has no E-AC-3 / Dolby Digital Plus decoder** — Dolby licensing is per-device and
budget Samsung tablets omit it. Findroid's device profile nevertheless claims EAC3 support, so
Jellyfin honours it and hands over the stream untouched. Video decodes fine; audio does not.

With only one audio track in the file there is no AAC fallback for the client to fall back to,
and the client never asks the server to transcode because it believes it can cope. **The server
was never involved** — this is a client capability mis-declaration, not a bandwidth or
transcoding problem.

### Fix — use Streamyfin on this device

| | Findroid | Streamyfin |
|---|---|---|
| Play method | `DirectPlay` | `DirectStream` |
| Tracearr `audio_decision` | `directplay` | `copy` |
| Result | dies at 14–84 s | sustained, smooth |

Streamyfin requests a **remux** (same codecs, different container) and decodes in its own bundled
software player rather than relying on the tablet's hardware Dolby licence.

**Verified 2026-08-24:** playback advanced **152 s over 150 s of wall clock** — real time, no
stalling — with `short_session = false`. Server cost: **zero ffmpeg processes**, Jellyfin at
16.8% CPU. `copy/copy` means no re-encode, only container repackaging, so there is no reason to
avoid this path on the i3.

### Durable fixes, if the same thing recurs elsewhere

1. **Add an AAC stereo track** so any client can pick a track it supports — video untouched, so
   it is fast:
   `ffmpeg -i in.mkv -map 0 -c copy -c:a:1 aac -ac 2 -metadata:s:a:1 title="Stereo" out.mkv`
2. **Penalise EAC3-only TV releases in Recyclarr**, alongside the existing compatibility-first
   "Avrana Compatible" profiles. This episode arrived EAC3-only.

### Diagnostic recipe worth reusing

`short_session = true` plus `audio_decision = directplay` on a budget Android device is the
signature of a codec the hardware cannot decode. Check the file's audio track count first: a
single non-AAC track means the client has nothing to fall back to.
