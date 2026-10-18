# Proposed Jellyfin hardware placement and validation

Status: **architecture candidate / bench-only**. Updated 2026-10-14.
No production migration, user/account changes, host/container changes, network exposure or downtime are authorized by this document.

**Authoritative physical inventory and RAM assignment:** [Avrana Studios mini-PC register](https://docs.google.com/document/d/1wFu3skWP2M7X95tP19C_NELkDnFYdXr4jBN6uuRtZek/edit?usp=drivesdk) (private Drive reference). This repository describes the *technical proposal*, testing evidence requirements and rollout gate; avoid maintaining a second mutable inventory here.

## Objective

Use the existing seventh-generation Intel HP EliteDesk 800 G3 Mini (reported 8 GB RAM) as a candidate Jellyfin server with Intel Quick Sync hardware transcoding, while retaining the Lenovo M700 (reported 32 GB and ~8 TB media) for storage and the other Avrana infrastructure services. Reserve the AMD HP EliteDesk 705 G3 Mini (reported 16 GB) primarily for Fabian. Preserve all three current memory allocations until usage proves otherwise.

The HP 800 G3's exact CPU/iGPU, driver support, SSD configuration and real decode/encode performance remain **unverified**. Hardware model and marketing capabilities are not benchmark evidence. NetBox/Ansible remains secondary to a proven Jellyfin role, and may need another host if resources conflict.

## Proposed topology (not deployed)

```text
                       Avrana members
                           |
                  existing approved entry
                           |
                      Jellyfin on HP
                      800 G3 / 8 GB
                    Quick Sync via /dev/dri
                    local SSD transcode temp
                           |
                      wired LAN
                  read-only media mount
                           |
                 Lenovo M700 / 32 GB
                   media disks / other
                   production services

                  HP 705 G3 / 16 GB
                  Fabian (independent)
```

Jellyfin transcodes on the host running Jellyfin. There is **no native distributed transcode offload** to another Jellyfin machine; the pilot therefore runs a *separate Jellyfin server* on the HP, with no impact to the production instance on the M700. Confirm that the HP's OS, Docker device passthrough and Intel driver actually support the required codecs before making a deployment decision.

## Non-destructive discovery

- Record exact processor / iGPU model, PCI device ID, microcode, OS, kernel, `/dev/dri`, RAM, storage, SMART, thermals, and wired network capabilities.
- Verify Intel hardware decode/encode by the actual FFmpeg/Jellyfin path and logs; don't infer GPU acceleration from `vainfo` alone.
- Confirm M700 media mount stability, UID/GID and read-only access, path mapping, filesystem and network saturation behavior.
- Determine a reliable local SSD path for temporary transcoding and acceptable capacity/cleanup; never put transient cache on a media share without evidence.
- Capture baseline Jellyfin configuration, user accounts, libraries and path mappings, watch history, plugins, device compatibility, backups and rollback material.
- Keep current Media 2.0 trust, authentication, member-entitlement, backup and approval gates intact.

## Pilot playback matrix / evidence

Test from a private, isolated HP Jellyfin with disposable/test accounts and copies or read-only mounts of representative media:

| Scenario | Required observations |
| --- | --- |
| Direct play on compatible 4K client | Is any unnecessary transcode occurring? Playback stability and throughput |
| 4K HEVC SDR to 1080p H.264 | Hardware decode/encode confirmed, playback speed relative to realtime, quality and stalls |
| 4K HEVC 10-bit and HDR | Codec availability, tone mapping path, performance/limitations, CPU fallback |
| Subtitle modes | Text subtitles, image-based subtitles, forced burn-in and CPU cost |
| 1080p/common-browser streams | Direct play compatibility and fallback behavior |
| Two concurrent streams | GPU/CPU/temperature/network/IO headroom, startup latency and frame drops |
| External member flow | Upload bandwidth and actual remote route, auth and device compatibility, without changing production exposure |

Optional stress media: the owner-mentioned ~65 GB / ~95-minute `Troll 2` example is an *uninspected hypothetical test source*, not a confirmed asset or proven bitrate. Inspect `ffprobe` results including bitrate peaks and format before drawing conclusions.

Record: source codec/profile/HDR, requested output, hardware transcode proof, transcode speed (must exceed 1.0x under sustained representative loads), GPU/CPU and thermals, LAN/upload throughput, buffer events, subtitle behavior, and observed client UX. Set go/no-go using recorded measurements rather than promised stream counts.

## Decision gates

1. **Bench approval only:** create isolated test plan and non-production setup; do not touch the live M700 Jellyfin, Authentik, Cloudflare, DNS, user accounts or proxy.
2. **Proof:** attach repeatable measurement logs, failure cases and compatibility matrix to the Linear validation issue.
3. **Migration design:** only if proof is good, document data/config and user-history migration, service routing, privacy, backups, media path mapping and rollback. Account for [proposed streaming-route evaluation](https://linear.app/avranakern/issue/AVR-464) as a **separate** owner decision, not an automatically approved side effect.
4. **Owner gate:** an explicit production change approval with maintenance window, backup/restore rehearsal, independent rollback and post-cutover verification is mandatory before migration. The original instance remains available for rollback until the new path is proven.

This proposal is a performance/operations experiment. It is **not** an M3 launch prerequisite unless the owner deliberately chooses to make it one.

## Tracking

- [Avrana Media 2.0 project](https://linear.app/avranakern/project/avrana-media-20-d76a735b6f0a)
- [Canonical Media 2.0 design](../design/MEDIA-2.0.md)
- [Media operations roadmap](../ROADMAP.md)
- [Physical inventory and memory allocation](https://docs.google.com/document/d/1wFu3skWP2M7X95tP19C_NELkDnFYdXr4jBN6uuRtZek/edit?usp=drivesdk)
