---
bookstack_page_id: 87
title: "Overview"
shelf: "Avrana Party"
book: "Avrana Party"
chapter: ""
created: 2026-09-20 00:39:16
updated: 2026-09-20 00:39:17
last_editor: "claude-mcp"
revisions: 1
tags: []
source_format: markdown
classification: OWNER REVIEW
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-20; exported 2026-10-04. Classified OWNER REVIEW. Avrana Party is a separate Raspberry Pi project (rcnechamkin/avrana-party); decide whether these move there.

# Overview
Avrana Party is a portable local-multiplayer appliance. A Raspberry Pi 4 hosts the games. Phones join its Wi-Fi (**Avrana Party**) and act as screens and controllers. Core play needs no internet, accounts or app installs.

**Not the homelab.** The media server on `avrana` (10.0.0.218) is a separate system, documented on the Avrana Homelab shelf. The `avrana.local` name belongs to that server. This device is `party.local`.

## What players use

| URL | What it is |
|---|---|
| `http://party.local/` | LAN Games (browser-native party games) |
| `http://party.local/arcade/` | Gauntlet II streamed to phones (private prototype) |
| `http://party.local/hotspot-detect.html` | Captive-portal landing page shown on joining the Wi-Fi |

## Where things live

| What | Where |
|---|---|
| Code, deploy configs | Git repo `rcnechamkin/avrana-party` (edited on the laptop) |
| Device | `party` (SSH), Pi 4, checkout at `/home/cody/avrana-party` |
| LAN Games source | `/home/cody/LAN-Games` on the Pi (not in the repo) |
| Detailed technical notes | `README.md`, `CLAUDE-HANDOFF.md`, `arcade/README.md` in the repo |

## Status at a glance (2026-09-19)

- Services start at boot: **verified**.
- Captive portal: works on an iPhone (owner-confirmed).
- Arcade: P1 verified for basic gameplay and streaming on a real iPhone; 2 slots enabled.
- **Not verified:** input-to-photon latency and performance (never formally measured), two-phone play, phone-side behavior after a boot, true offline operation.
- **Open hardware issue:** power/throttling flags set (see Decisions & Current State).
