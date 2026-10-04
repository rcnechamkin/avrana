---
bookstack_page_id: 88
title: "Architecture"
shelf: "Avrana Party"
book: "Avrana Party"
chapter: ""
created: 2026-09-20 00:39:17
updated: 2026-09-20 00:39:17
last_editor: "claude-mcp"
revisions: 1
tags: []
source_format: markdown
classification: OWNER REVIEW
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-20; exported 2026-10-04. Classified OWNER REVIEW. As above.

# Architecture
## Hardware and OS

Raspberry Pi 4 Model B Rev 1.5, about 4 GB RAM, Debian 13 (trixie), kernel 6.18.39+rpt-rpi-v8. Headless (both HDMI ports disconnected).

## Network

| Interface | Role |
|---|---|
| `wlan1` | USB Realtek adapter, dedicated AP. SSID **Avrana Party**, NetworkManager shared mode, 10.42.0.1/24, 5 GHz channel 149 (from the NM profile), autoconnect. NM's dnsmasq provides DHCP, DNS and NAT. |
| `wlan0` | Home Wi-Fi: management and upstream, default route. **Never drop it during a remote session.** |
| `eth0` | No active connection. |

System hostname stays `RaspberryPi`. Avahi advertises `party.local` (`host-name=party` in `/etc/avahi/avahi-daemon.conf`).

## nginx (port 80, site `avrana-party`)

| Route | Target |
|---|---|
| `= /hotspot-detect.html` | Static `/var/www/avrana-portal/index.html`, `Cache-Control: no-store`, `etag off`, `if_modified_since off` |
| `/arcade/` | 127.0.0.1:8097, WebSocket, proxy buffering off |
| `/` | 127.0.0.1:8096, LAN Games, WebSocket |

## Captive portal DNS

`/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf` answers **both** `captive.apple.com` **and** `captive.g.aaplimg.com` with 10.42.0.1, plus `local=` rules so no AAAA/HTTPS answers leak upstream. Without the second name an iPhone queries Apple's alias directly and gets Apple's real Success page (proven by packet capture). Do not remove either. Android, Microsoft and Firefox probe names are also intercepted but untested.

## Arcade streaming prototype

One emulator, one hardware video encode, per-phone WebRTC transports. Never one session per phone.

```
avranaparty-arcade.service (user cody; groups input video render)
 -> run-stream.sh -> with-audio.sh (private PulseAudio null sink)
 -> xvfb-run (private 640x480 display) -> stream.py (aiohttp, 127.0.0.1:8097)
      - one virtual uinput pad per slot, created before RetroArch starts
      - one RetroArch + MAME 2010 (0.139) running gaunt2
      - one capture pipeline:
          ximagesrc 60 fps -> I420 -> v4l2h264enc (/dev/video11, 2.5 Mbit/s,
          constrained baseline 3.1, IDR every 60) -> appsink
          pulsesrc monitor -> Opus 64 kbit/s, 10 ms frames -> appsink
      - per phone: bounded, dropping appsrc queues -> RTP -> webrtcbin
```

- **Signaling and controls:** same-origin WebSocket (`/arcade/ws`). Wrong-Origin requests get 403. No public STUN/TURN.
- **Input:** full held-button snapshots at 20 Hz plus immediate touch changes. The server assigns the player slot. Held inputs release after about 300 ms without updates and on disconnect.
- **Browser:** `arcade/index.html`. Tap Play to connect, then Enable sound (separate gesture), then Add coin.
- **`/stats`:** `http://party.local/arcade/stats` (players, max_players, fps, capture age percentiles). `video_encoders: 1` is hardcoded metadata, not a measurement.
- **Boot prerequisites:** `uinput` module (`/etc/modules-load.d/avrana-uinput.conf`), udev rule `70-avrana-uinput.rules` (group `input`, mode 0660). Nothing runs as root.

## ROM and emulator

The supplied `gaunt2.zip` (`/srv/avrana/roms/arcade/`, SHA-256 `ba854a6494fde461138f00550bd2fd38e6afe4cb93bc8e42a15245a0bc8d090e`) is kept unchanged. It matches the MAME 2010 core exactly (26/26 files by name, size, CRC, SHA-1). Standalone MAME 0.276 rejects it. The core is not committed; provenance is in `arcade/evidence/selected-core.json`. Re-run the audit with `arcade/audit-legacy-rom.py`. The old MAME license makes this a private prototype, not a cleared distribution choice.
