---
bookstack_page_id: 75
title: "Kern Tablet: SM-T510 desk companion"
shelf: "Kern"
book: "Kern: Roadmap and Infrastructure"
chapter: ""
created: 2026-08-24 20:10:21
updated: 2026-08-24 20:10:21
last_editor: "Cody"
revisions: 1
tags: ["status=proposed", "type=project", "device=SM-T510"]
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-24; exported 2026-10-04. Classified ARCHIVE. Kern project design (tablet).

# Kern Tablet: SM-T510 desk companion
# Kern Tablet: SM-T510 desk companion

**Status: proposed, nothing built.** No code, no dock, no ROM decision. One blocking problem is
under active investigation and is not yet understood. This page is the agreed shape of the project,
not a record of work done.

## Scope

Repurpose a 2019 Samsung Galaxy Tab A 10.1 (**SM-T510**) as a semi-permanent desk companion in the
home office, **without giving up its use as an ordinary tablet**. Docked, it becomes a Kern surface.
Undocked, it is a normal Android tablet for comics, Jellyfin and browsing.

That dual role is the constraint that shapes everything below. A kiosk-locked appliance would be
easier and is explicitly not what this is.

The tablet is a **client**. It does not orchestrate, hold credentials, or own state. This follows
the same boundary Kern HQ is held to; see
[Architecture and Boundaries](http://10.0.0.218:6875/books/kern-overview/page/architecture-and-boundaries)
and [Kern HQ: Home Assistant](http://10.0.0.218:6875/books/kern-hq-home-assistant/page/kern-hq-home-assistant).

## Target experience

Docking triggers **Desk Mode**: a custom Kern Tablet interface with five lightweight pages.

| Page | Shows |
|---|---|
| Home | Time, at-a-glance status, entry points to the rest |
| Media | Jellyfin and Avrana library state, now playing, recent additions |
| Kern HQ / Home Assistant | Lights, plugs, voice pipeline state, sensors |
| Avrana | Service health, requests, downloads |
| Infrastructure | Host health, disks, backups, containers |

Undocking returns the device to normal Android. Nothing about Desk Mode should make the tablet
worse as a tablet.

**Design language: Avrana's existing monochrome retro-futurist aesthetic.** Black and white, Times
New Roman, square rules, no shadows, hover inverting to white-on-black. Sparse rather than
information-dense. Large touch targets. Minimal animation. Subtle orbital and radar motifs.

This is the same language as the portal and the Authentik login, so it should be inherited rather
than reinvented.

## Software architecture

**Preferred direction, not a decision yet.**

- **HoaryDash is the strongest candidate foundation**, because it is
  explicitly optimised for old Android tablets. That is exactly the constraint here.
- **Nidus** and the lightweight Home Assistant tablet dashboards are worth reading as
  **references**, not necessarily as foundations.
- **Go plus static HTML/CSS and minimal JS, not a heavy React application.** On a 2019 tablet with
  2 to 3 GB of RAM, framework overhead is the difference between usable and not.

Shape:

> **The tablet stays a thin client. The backend aggregates and proxies.**
> Jellyfin, Home Assistant, Avrana services and system health are fetched, combined and cached
> server-side. The tablet renders what it is given.

Rules that follow from that:

- **Never expose service API keys or tokens to browser JavaScript.** Every credential stays on the
  backend. This is the same rule the portal already follows, and the reason the portal holds no
  secrets of its own.
- Render only the active page. Do not keep five pages live.
- Cache artwork server-side. Do not re-fetch posters on every refresh.
- Avoid heavy animation and avoid iframes.
- Conservative refresh intervals. Nothing on this display needs to be a second fresh.

## Android modernisation

| | |
|---|---|
| Device | Samsung Galaxy Tab A 10.1 (2019), SM-T510 |
| Candidate ROM | LineageOS 20 / Android 13 |
| Root | **Not assumed necessary.** Add Magisk only for a demonstrated need |

> **TWRP or any custom ROM only after exact model compatibility is verified.** SM-T510 has
> variants, and "close enough" is how tablets get bricked.

> **Bootloader unlocking wipes the tablet.** Treat it as destructive and irreversible for the data
> on the device.

**Division of labour:** an assistant can drive ADB-side work, inventory, debloat lists, package
queries and configuration. **Bootloader unlocks, wipes, flashing and any other destructive
operation require explicit human approval at the time.** Do not batch them into an automated run.

Whether to modernise at all is still open. Stock, debloated, may be sufficient.

## Physical dock

The goal is a **real dock, not a charger on the desk**.

| Element | Intent |
|---|---|
| Powered USB-C hub | Single connection carries power and Ethernet |
| Ethernet | Wired, to take Wi-Fi out of the variable set |
| Charging | Continuous while docked, subject to the battery policy below |
| Cable management | Hidden, exits the back or base |
| Enclosure | Weighted custom cradle, stable enough for one-handed touch |
| Removal | Easy. Lifting the tablet out must not be a two-hand operation |

Connector approach:

- **First revision: a short flexible USB-C pigtail.** Simple, forgiving of alignment error.
- **Later revision: a carefully designed floating USB-C connector**, only once the geometry is
  known from the working first version.
- **Avoid magnetic USB-C adapters.** The cheap ones are electrically questionable and this is a
  connector that will be cycled daily.

> **The connector must not mechanically stress the tablet's USB-C port.** The port is soldered to a
> 2019 board and is not replaceable in any pleasant way. Compliance in the cable is a design
> requirement, not a nicety.

**SM-T510's USB-C is USB 2.0.** Ethernet through the hub will not reach gigabit. For dashboard
traffic and Jellyfin playback this is irrelevant, and wired is still worth having for stability
rather than throughput.

### Dock-state detection

Desk Mode should trigger on evidence that the tablet is in *this* dock, not merely charging.

1. **External power present**, and
2. **the known USB hub or Ethernet adapter is present**, ideally matched on **USB VID/PID**, with
3. **Ethernet link** as supporting evidence.

> **A regular charger must not trigger Desk Mode.** Charging alone is not docking. This is the
> single requirement most likely to be got wrong by a naive power-state trigger.

## Battery

The tablet may sit docked most of the time, and the battery is from 2019.

- **Do not leave it pinned at 100%.** Continuous full charge is the fastest way to finish off an
  aging cell.
- **Investigate kernel-supported charge limiting** first. If the ROM exposes a charge control
  sysfs node, that is the clean answer.
- **Otherwise use a smart plug and automation to hold roughly 40 to 80%.** Home Assistant already
  has the smart plug bridge for this; see
  [Kern HQ](http://10.0.0.218:6875/books/kern-hq-home-assistant/page/kern-hq-home-assistant).

## Jellyfin playback: unresolved

> **This is an open investigation, not a conclusion. Nothing below has been isolated.**
> The tablet is unusable as a Jellyfin client until this is understood, which is why it sits early
> in the roadmap.

### Observed

| | |
|---|---|
| Content | Batman: Caped Crusader, one episode |
| Source | WEB-DL 1080p |
| Video | H.264, 1920x1080, approximately 9.6 Mbps |
| Audio | EAC3 5.1 |
| Subtitles | SRT |
| Jellyfin reports | **Direct Play** |

Symptoms:

- Native Jellyfin Android client stutters and buffers.
- **Findroid with MPV also eventually stutters.**
- The public Cloudflare URL initially appeared worse.
- The local Jellyfin IP initially appeared to fix it, **but playback began stuttering after roughly
  three minutes.**

> **The apparent initial success may simply have been locally pre-buffered or already-downloaded
> content.** If so, it proves nothing about the network path.

**Therefore Cloudflare, Wi-Fi, the codec and the Jellyfin client have all NOT been ruled out.** Any
statement that "it is Cloudflare" or "it is the Wi-Fi" is currently unsupported.

### Next definitive diagnostic

Run in this order. The point is to remove the network from the experiment entirely.

1. **Fully copy the actual media file to local tablet storage.** Not a stream, not a partial cache.
2. **Enable airplane mode.**
3. **Play the file directly in standalone MPV or VLC**, outside Jellyfin and Findroid.
4. If it **still** stutters, the problem is local decode. Inspect decoder behaviour and run
   `ffprobe` for H.264 profile, level, pixel format, framerate and bitrate.
5. **Verify hardware MediaCodec decoding is actually being used**, rather than silently falling back
   to software.
6. **Only if offline playback is smooth** does it become worth investigating Cloudflare, Wi-Fi or
   the server path.

Server-side transcoding behaviour and its limits are documented separately on
[Jellyfin](http://10.0.0.218:6875/books/services/page/jellyfin). Note that the host is reported as
**Direct Play** here, so that page's transcoding analysis does not obviously apply, and should not
be assumed to.

## Roadmap

Ordered. Several steps only make sense once earlier ones are done.

1. Document current tablet and Android state via ADB.
2. **Resolve the Jellyfin / local playback problem.** Blocking.
3. Decide stock versus LineageOS.
4. Modernise and debloat.
5. Prototype the Kern Tablet shell against mock data.
6. **Validate smooth performance on the actual SM-T510**, not on a desktop browser.
7. Home page and navigation.
8. Jellyfin and Avrana media integration.
9. Home Assistant and Kern HQ integration.
10. Avrana and infrastructure status.
11. Automatic dock and undock behaviour.
12. Build and test the powered USB-C Ethernet dock.
13. Design the final custom enclosure.
14. Battery charge management.
15. Document the final recovery and rebuild procedure.

Step 6 is a real gate. A shell that is pleasant in a desktop browser and sluggish on the tablet has
failed, and it is cheaper to learn that at step 6 than at step 10.

## Pitfalls and guardrails

- **2 to 3 GB of RAM depending on variant.** This is the governing constraint. Confirm which
  variant this is before sizing anything.
- **Avoid heavy frontend frameworks and features until proven performant on the device.**
- **USB-C here is USB 2.0.** Do not design around gigabit.
- **Custom ROM support is unofficial.** No vendor recourse.
- **Bootloader operations can wipe or brick the device.**
- **No credentials in the frontend, ever.**
- **Do not conflate Jellyfin buffering with Cloudflare** until offline playback has been tested.
- **Jellyfin's earlier HEVC / Main10 Android issue is real, but it does not by itself explain an
  H.264 file.** Do not reach for it as the explanation here.
- **The dock connector must not stress the USB-C port.**
- **The battery is aging and will be docked continuously.**

## Open decisions

- Stock Android versus LineageOS 20.
- HoaryDash as foundation versus a purpose-built Go service.
- Whether root is needed at all, and for what specifically.
- Whether charge limiting is available in-kernel, or must be done with a smart plug.
- Exact SM-T510 variant and its RAM.

Related: [Hardware and Infrastructure Strategy](http://10.0.0.218:6875/books/kern-roadmap-and-infrastructure/page/hardware-and-infrastructure-strategy),
[Roadmap and Order of Operations](http://10.0.0.218:6875/books/kern-roadmap-and-infrastructure/page/roadmap-and-order-of-operations),
[Risks and Known Issues](http://10.0.0.218:6875/books/kern-risks-and-open-questions/page/risks-and-known-issues),
[Open Decisions and Future Research](http://10.0.0.218:6875/books/kern-risks-and-open-questions/page/open-decisions-and-future-research).
