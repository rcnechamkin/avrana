# Jellyfin: 8096 (Tunnel)

> Promoted from the BookStack wiki on 2026-10-04 (page 22, "Jellyfin", last edited 2026-08-24) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: media mounts are read-only today; read docs/findings/2026-09-23-jellyfin-artwork.md before maintenance.
> Original: [archive](../../docs/archive/bookstack/raw/services/22-jellyfin.md).

Movie/TV player. Container `jellyfin`, **host networking** (exposure controlled by host firewall, not a compose port map). Read-only rootfs; media writable for subtitle sidecars; render group 993 for HW accel.
- The active player going forward (Plex is being retired).

## Auth: credential replication (NOT OIDC)
Jellyfin's TV/phone apps can't do OIDC, so it is **not** an Authentik OIDC app. Instead, at **enrollment** an Authentik expression policy (`avrana-jellyfin-create`, gated on the **`avrana-videos`** group) calls Jellyfin `POST /Users/New` with the username + password the person typed at signup: creating a Jellyfin account with the **same password**, usable in the native apps. **Seerr** then auto-creates on that user's first Jellyfin login (no config needed).
- ⚠️ **A password change in Authentik does NOT propagate to Jellyfin** (the copy is frozen at signup). Verified 2026-08-14. Same for Seerr.
- The policy reaches Jellyfin by **host IP `10.0.0.218:8096`** (host networking: `jellyfin:8096` does not resolve from the Authentik container). API key stored in the enrollment blueprint (gitignored).
- A **pre-existing same-username** Jellyfin account is left untouched: it keeps its old password; the new signup password does not apply. Delete the old account first if you want the new password to take.
- An admin-created API key ("Authentik") powers the account creation; there is no OIDC login button in Jellyfin.


## Sign-in, and why it is not SSO (verified 2026-08-17)

Jellyfin has **no OIDC plugin installed**: the plugins directory holds only `configurations`.
It authenticates with a **local username and password**, replicated from Authentik at enrollment
by the `avrana-jellyfin-create` policy.

Consequences worth remembering:

- A **password change in Authentik does not propagate** to Jellyfin.
- **Deleting the Authentik user does not revoke Jellyfin access**: the local account keeps
  working. This is why `scripts/offboard.py` treats Jellyfin as the real revocation point.
- The help pages therefore say "sign in with the Avrana username and password", **not** "choose
  SSO", which would send members to a button that does not exist.

## Clients

Documented at `avrana.net/help/movies`: Swiftfin and Jellyfin Mobile on iOS, Jellyfin on
Android, **Roku / Fire TV / Google TV / Apple TV / Samsung and LG** (installed from the
television's own store, so no phone-store links), **Jellyfin Media Player on Windows**
(<https://jellyfin.org/downloads/windows/>), and the browser as the least reliable option.

`avrana.net/watch` shows a playback warning before handing off; see *Avrana Portal*.

## Transcoding reality on this hardware (measured 2026-08-17)

A single 4K HDR stream saturates the host. Measured during a live session: **ffmpeg ~326% CPU,
90.9% user, 0% idle, load average 7.6 on 4 threads**, with authentik, shelfmark and libation all
visibly slowed.

### Why it is so expensive

Only the **encode** is hardware. From the live ffmpeg command line:

- `-codec:v h264_qsv`: hardware encode
- **no `-hwaccel` flag at all**: decoding is software
- `setparams=...,scale=...,format=nv12`: software scale and pixel conversion

So the box software-decodes a 27.9 Mbps 4K HEVC **10-bit** stream, software-scales to 1080p and
converts 10-bit to 8-bit. `encoding.xml` has `HardwareDecodingCodecs` empty and
`EnableDecodingColorDepth10Hevc: false`: and **that is correct for this hardware**: the i3-6100T
is Skylake/Gen9, whose decoder handles HEVC 8-bit only. 10-bit HEVC decode arrived with Kaby Lake
(Gen9.5). Enabling it would fail, not help.

`EnableTonemapping` and `EnableVppTonemapping` are both **false**, so the filter chain only
*relabels* BT.2020/PQ as BT.709 rather than converting it. **Viewers get a washed-out, grey
picture** on top of the CPU cost. Enabling tone-mapping would fix the colour and make the CPU
situation worse.

### The actual trigger is a label mismatch, not a capability gap

The Roku (TCL 55S41R) publishes exactly what it accepts:

```
hevc:  VideoProfile   = main | main 10
       VideoBitrate  <= 40,000,000
       VideoRangeType = SDR | DOVIWithSDR | HDR10 | DOVIWithHDR10 | HLG | DOVIWithHLG
```

The file was `DOVIWithHDR10Plus`. Every other condition passed. **HDR10+ is backward compatible
with HDR10** (dynamic metadata over a static HDR10 base), so the panel could almost certainly have
displayed i: Jellyfin matches the range string, not the content.

### Library-wide compatibility audit

**12 of 24 movies** would transcode on that client, for three unrelated reasons:

| Reason | Count | Titles |
|---|---|---|
| HDR10+ | 5 | Mandalorian and Grogu, Avatar Aang, Supergirl, The Invite, Event Horizon |
| DV without HDR10 fallback / DV P7 | 4 | Minions & Monsters, Transformers One, Obsession, Troy |
| Bitrate over 40 Mbps | 4 | The Dark Knight (62), Dark Knight Rises (61), Obsession (73), Troy (63) |
| VC-1 codec | 1 | Batman: Under the Red Hood |

Every HDR title in the library transcodes on that TV. All 12 direct-playing titles are SDR.

> **Note the bitrate cases.** No HDR fix and no server upgrade changes those: the client refuses a
> stream that fat. Only a smaller copy or a better client will.

### Fixes, cheapest first

1. **Update the Jellyfin Roku app** (was 3.2.3): free if a newer build advertises HDR10+.
2. **Remux to drop HDR10+ metadata**, leaving DV+HDR10. Lossless, minutes per title, converts a
   permanent transcode into a permanent direct play *and* fixes the colour.
3. **Stop acquiring the format**: this is what the compatibility-first profiles do. See
   [Radarr / Sonarr](../../docs/services/radarr-sonarr.md).
4. **A better client** (Shield / Apple TV 4K / Roku Ultra): around $100-200, fixes roughly 10 of
   the 12, and removes the server from the path entirely. Cheaper and more effective than a server
   GPU, which would require replacing the M700 outright.

### Operational gaps noticed

- **No `MaxConcurrentTranscodes` limit.** One transcode already saturates the box; two would make
  the whole stack unusable. A limit of 1 is cheap insurance.
- `EnableThrottling` is on (180s), which is correct.
- **`RemoteEndPoint` reports `127.0.0.1`** for every client, because traffic arrives via the
  tunnel. Jellyfin therefore cannot distinguish LAN from WAN, so `RemoteClientBitrateLimit` and
  any remote-quality rule will not behave as expected.

## Encoding settings audit (2026-08-19)

Full read of `encoding.xml` / `system.xml` / `network.xml` against the actual silicon. **The
hardware setup was already correc: the HDR limit is real, not a misconfiguration.**

**Hardware:** Intel Core i3-6100T, Skylake / HD Graphics 530, **2 cores / 4 threads**. GPU
passthrough is properly done: `/dev/dri` mapped, `GroupAdd 993` (render), container user
`1000:1000`, devices visible in-container, and ffmpeg reports `qsv`/`vaapi`/`opencl`/`vulkan`
available.

> **`EnableDecodingColorDepth10Hevc=false` is CORRECT, not an oversight.** 10-bit HEVC hardware
> decode arrived with Kaby Lake; Skylake does not have it. Setting it true only makes Jellyfin
> attempt something the silicon cannot do. **This is why every 4K HDR title falls to software
> decode at ~326% CPU**: a hardware ceiling, not a setting to tune. Do not "fix" this.

### Applied 2026-08-19 (via the API, so in-memory and on-disk config agree)

| Setting | Was | Now | Why |
|---|---|---|---|
| `EnableSegmentDeletion` | `false` | `true` | **The important one.** `/transcode` is an 8 GB tmpfs. With deletion off the entire transcoded output accumulates in RAM: a 156-min film at even ~7 Mbps exceeds 8 GB, so long transcodes would die partway with "no space left". Now bounded to ~12 min (`SegmentKeepSeconds` 720). |
| `HardwareDecodingCodecs` | `h264, hevc` | `+ vc1, mpeg2video` | Skylake decodes both in fixed function. The one VC-1 title was software-decoding for no reason. |
| `EncodingThreadCount` | `-1` (all 4) | `3` | Jellyfin has **no `MaxConcurrentTranscodes`** (that is an Emby setting), so thread count is one of the only throttles available. Leaves a thread for the server. |
| `EnableDecodingColorDepth10Vp9` | `true` | `false` | VP9 10-bit decode is also Kaby Lake+; was inconsistent with the HEVC setting. |

Trade-off accepted: segment deletion means seeking backwards more than 12 minutes into an
in-progress transcode can restart the stream on some clients. `SegmentKeepSeconds` is the dial.

### Deliberately NOT applied

- **Tone-mapping stays off.** The filters exist (`tonemap_opencl`, `tonemap_vaapi`, `vpp_qsv`,
  `tonemapx`): but **VPP tone-mapping requires hardware decode**, which cannot happen for 10-bit
  HEVC on this chip, so the cheap path can never engage on the actual HDR content. OpenCL would
  work but means uploading software-decoded frames on an already-saturated box. The consequence is
  that HDR transcodes look washed out; **the fix is to not transcode HDR at all**, which is what
  the compatibility profiles do. This is a decision, not an omission.
- **`EnableIntelLowPowerH264HwEncoder`**: likely the biggest remaining CPU win (H.264 is the only
  output codec, and VDENC is fixed-function), but Skylake is exactly where the quirks are. Needs
  one real transcode watched afterwards.
- **`KnownProxies`**: see below.
- `DownMixStereoAlgorithm`: changes how audio sounds; a taste call, not a correctness fix.

### The 127.0.0.1 problem is a settings bug, and it is fixable

`network.xml` has **`KnownProxies` empty** (and `LocalNetworkSubnets` empty). Traffic arrives from
cloudflared on loopback; because loopback is not declared a known proxy, Jellyfin ignores
`X-Forwarded-For` and attributes **every** session to 127.0.0.1. That is the root cause of
`RemoteClientBitrateLimit` being inert, not a separate mystery. Declaring the tunnel's loopback
address as a known proxy restores real client IPs and makes remote bitrate caps work. It
reclassifies every session's remote/local status, so test it deliberately.

> **These settings are NOT version controlled.** Jellyfin's config lives at
> `/home/cody/docker/jellyfin/config/config/`, outside the git repo. The only copy of the
> pre-change state is `/mnt/avrana_media/.backups/jellyfin-encoding-20260819T001727Z/`.

## Unresolved: stuttering playback on the SM-T510 tablet

**Open investigation, no conclusion.** A Batman: Caped Crusader episode (WEB-DL 1080p, H.264
1920x1080 at roughly 9.6 Mbps, EAC3 5.1, SRT) stutters on the Samsung SM-T510 tablet in both the
native Jellyfin client and Findroid with MPV, **while Jellyfin reports Direct Play**.

Because the server reports Direct Play, **the transcoding analysis above does not obviously apply**
and should not be assumed to. Cloudflare, Wi-Fi, the codec and the client have none of them been
isolated yet. An apparent fix when switching to the local Jellyfin IP failed after roughly three
minutes and may simply have been pre-buffered content.

The diagnostic plan, which deliberately removes the network from the experiment, is on
[Kern Tablet: SM-T510 desk companion](../../docs/archive/bookstack/raw/kern-roadmap-and-infrastructure/75-kern-tablet-sm-t510-desk-companion.md).
