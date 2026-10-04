---
bookstack_page_id: 90
title: "Decisions & Current State"
shelf: "Avrana Party"
book: "Avrana Party"
chapter: ""
created: 2026-09-20 00:39:18
updated: 2026-09-20 00:39:18
last_editor: "claude-mcp"
revisions: 1
tags: []
source_format: markdown
classification: OWNER REVIEW
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-20; exported 2026-10-04. Classified OWNER REVIEW. As above.

# Decisions & Current State
## Current state (2026-09-19)

Source: read-only inspection of `party` plus the repo. Pi had been up about 50 minutes.

**Verified**
- nginx, NetworkManager, avahi-daemon, avranaparty-games and avranaparty-arcade active and enabled. The arcade started at boot with 0 restarts, so **service startup after boot is verified**.
- Live nginx site, portal HTML, captive DNS config and arcade unit match the repo. The Pi checkout is at commit `1474003` with a clean tree.
- Portal probe returns 200 with `no-store`. Both Apple captive names resolve to 10.42.0.1. The owner confirmed the portal works on an iPhone.
- Arcade: P1 is verified for basic gameplay and streaming on a real iPhone. It encoded about 60 fps with 0 viewers. LAN Games `/health` returns ok.

**Enabled but not verified**
- `MAX_PLAYERS = 2`: two slots are enabled. **Two-phone behavior is not verified.** Do not raise the limit until a two-phone test passes.

**Not verified**
- **Input-to-photon latency and gameplay performance have not been formally measured.** An earlier report called the experience "super laggy"; P1 has since been verified playable, but no median/p95 latency figure exists.
- Phone-side behavior after a reboot, and true offline operation.
- 3-4 phone scaling (CPU, RAM, Wi-Fi, encoder count).
- Android, Microsoft and Firefox captive flows.

## Open issues

| # | Issue | Notes |
|---|---|---|
| 1 | **Power / throttling (current, open)** | `vcgencmd get_throttled` = `0x50000` about 50 min after boot: under-voltage and throttling have occurred since boot. Check the power supply, cable and USB load. Re-read under load before attributing lag to software. |
| 2 | Latency unmeasured | Measure input-to-photon by high-frame-rate filming of touch and screen; report median and p95. RTT and jitter-buffer stats are not input-to-photon latency. |
| 3 | Audio capture age | `/stats` showed audio `capture_age_ms` p50 about 152 ms against about 10 ms for video. Cause unknown; investigate audio buffering and A/V sync. |
| 4 | Two-phone test | Independent slots, coin/start, reconnect, screen lock. |
| 5 | Robustness | A fatal pipeline error may not exit the process, so `Restart=on-failure` may not fire. Normal stop logs exit 143. Emulator and encoder run continuously with 0 viewers. |
| 6 | No defined deploy method | The Pi checkout has no git remote; laptop tracks `origin`. |
| 7 | Emulator license | MAME 2010's old non-commercial license: private prototype only. |

## Decisions

| Decision | Why |
|---|---|
| Keep the existing browser-native LAN Games platform; add the arcade separately | Preserve the working AP, portal, nginx, Avahi and management access. |
| One emulator, one hardware encode (`v4l2h264enc`), per-phone WebRTC | Low Pi CPU. Never one emulator session per phone. |
| RetroArch + MAME 2010, not MAME 0.276 or FBNeo | The only exact match for the supplied `gaunt2.zip` (26/26). ROM files are never patched or replaced. |
| GStreamer appsink/appsrc fan-out, not a tee | The dynamic tee stalled on connect/disconnect. |
| Sunshine, Wolf, Selkies not used | No demonstrated shared Pi hardware-encode path. |
| Software GL in Xvfb, not SDL2 video | SDL2 segfaulted at display init. |
| Same-origin WebSocket for input | Simple; a WebRTC data channel is a candidate only if measurement shows input transport is the bottleneck. |
| Intercept both Apple captive names | Packet capture proved iPhones fetch Apple's real Success page otherwise. |
| `party.local` hostname via Avahi | `avrana.local` belongs to another real server. |
| No public STUN/TURN, no Docker, no HTTPS cert hacks | Local network only; no concrete need. |
| Repo docs and BookStack must agree | BookStack is the source of truth for architecture, decisions and runbooks; the live system wins any conflict. |
