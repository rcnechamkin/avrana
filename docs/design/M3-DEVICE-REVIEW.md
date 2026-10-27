# M3 real-device review packet: Concept K Home (AVR-585)

> **Status: written 2026-10-26. Nothing in this packet has been run on a phone or a TV.** It is the owner's
> checklist for AVR-585, coordinated with AVR-455 (Party and Media phone approval) and AVR-479 (handoff and TV).
> Fixture-only: synthetic members and synthetic items, no real member data.

## 1. What is under review, and what is not claimed

| PR (`rcnechamkin/avrana`, all drafts) | Head | What |
|---|---|---|
| #74 Concept K integration (MK-1 to MK-7) | `27381c6` | The Concept K shell, Home, Library, Search, title, Request, Me, PWA |
| #80 OSS reuse R2 + R3 on top of #74 | `847b8d4` | **The revision to review** (synopsis/About, `dir=auto`, identity) |
| #81 AVR-732 (pending fix, not in `847b8d4`) | `26a7a60` | Header blocks over 16 KiB refused whatever the read size |
| #82 AVR-733 (pending fix, not in `847b8d4`) | `e4957cb` | Cool-off recovery test race |

Not claimed: not merged, not deployed, not on host `avrana`; synthetic fixtures only; no GitHub CI (billing
blocked; evidence is local runs); no Authentik sign-in, outpost, G1/G2 or production integration proof; no member
beta. **A phone opening a library link is not TV playback**, and Avrana never reports that anything played.

## 2. Candidate temporary preview plan (FOR OWNER APPROVAL, not executed)

**Step A, loopback (default).** The fixture stack documented in `services/avrana-home/dev/README-DEMO.md`, from
the repository root on the owner's computer, with the venv that has the pinned requirements:

```
.venv-media/Scripts/python services/avrana-home/dev/run_dev.py --dev-identity --abs-mock-port 13378 --komga-mock-port 25600 --calibre-mock-port 18083
```

It serves `http://127.0.0.1:8096/` (members at `/_dev/identity`) with mocks on `127.0.0.1`. Stop: Ctrl+C in
that window (the mocks stop with it). Useful for a desktop look and the identity checks in section 6.

**Gap: no fixture-only LAN path exists in the tree.** An iPhone cannot reach Step A: `127.0.0.1` on the phone
is the phone (AVR-455). `run_dev.py` refuses any non-loopback bind (`dev/dev_identity.py`, `check_startup`), and
the shim must never be deployed. The only LAN tooling, `docs/runbooks/home-owner-preview.md`
(`python -m preview.run_preview` in `docker-compose.preview.yml`, on `avrana` at `10.0.0.218:8197`, password
gated by `preview/gate.py`), shows the **owner's real libraries**, so it is not fixture-only and is outside this
packet. Owner choices for the phone and TV steps:

- **Step B1 (needs its own approval and a reviewed PR first):** a fixture-only LAN variant that reuses
  `preview/gate.py` (one password from a file, identity headers stripped) in front of the mock stack, bound to
  one LAN address of the owner's computer on the home Wi-Fi, started by hand for the session and stopped with
  Ctrl+C. Plain http: the password crosses the Wi-Fi unencrypted, and Safari does not run the service worker
  outside a secure context, so the offline page and update banner cannot be checked this way.
- **Step B2:** decline the LAN preview; review only the desktop loopback, screenshots and automated evidence,
  and leave AVR-585's physical acceptance open.

Either way: no Cloudflare tunnel, DNS name, router forward or Authentik change; no step touches `avrana`.

**Owner choice, 2026-10-27: B2 now, the phone pass on the beta hostname later.** Step B1 was built (#88) and
dropped as too fiddly for a review (a private certificate on the phone, a passphrase, a firewall prompt). The
owner approved the look from iPhone-size screenshots of Step A (Chrome, iPhone 15 viewport): Home, Library,
Search and Me, dark and light. Nothing was installed on any device.

**Step C, the phone pass (when the beta hostname of AVR-373 is live).** No setup: the beta hostname has a real
certificate and Authentik sign-in, so it is just a link.

1. On the iPhone, open the beta link and sign in as usual.
2. Walk the journeys in section 3 and the checks in section 4 (Add to Home Screen, VoiceOver, Reduce Motion,
   text size, offline page). The beta shows synthetic data only (`Dockerfile.beta`), so nothing real is at risk.
3. Tell the agent "looks good" or what is off; it records the result here and on AVR-585.

## 3. Journeys (record P pass, F fail, S skipped, with notes)

Use `member-b` (every library) unless stated. Hand-off links go to the real public library hosts
(`watch.avrana.net` and the like) carrying **synthetic** item ids, so the library shows its sign-in or "not
found": judge the link, the copy and the way back, not playback. Real playback is AVR-479 (section 5).

| # | Step | Expected | P/F/S, notes |
|---|---|---|---|
| J1.1 | Open Home | L3 Media lockup top left; places bar; hero "Continue: <title>" with yellow bar; tab bar Home · Library · Search · Me | |
| J1.2 | Tap the hero's "Resume in Jellyfin" (or "Open in <app>") | One link to the library item page; no "playing" or "opening" claim | |
| J1.3 | Back | Home again, same cards | |
| J1.4 | Hero's Details | `/title/<service>/<id>`: art, title, one Cream action, "Opens in" panel | |
| J2.1 | Library tab, then a library chip | Chosen chip tinted with a check; shelves; "Open <app>" | |
| J2.2 | Open an item, read About/synopsis | Title page with the About/synopsis block (the fixtures have no right-to-left text, so `dir=auto` is not exercised here) | |
| J2.3 | Title action, then Back | Hand-off link; Back returns to the title page | |
| J3.1 | Search a word from a fixture title | One panel per library, title links to the title page | |
| J3.2 | Search `zzqxnothingzz` | "No results"; "Ask for it" rows, each "Opens the request website" | |
| J3.3 | Run mock mode `down`, search again | Warning: glyph, "unavailable right now", Try again; other libraries still listed | |
| J4.1 | Request place (`/request`) | "Ask for something" rows; no in-app request form | |
| J4.2 | Tap "Ask for a film or show" | Seerr's site opens (`request.avrana.net`); Avrana submits nothing | |
| J5.1 | Me tab | Initial circle, name, "Signed in as", Account, Help, Sign out | |
| J5.2 | Account, then Help, then a topic | Grouped rows; Home button on topic pages; Me tab marked current | |
| J5.3 | Sign out | `/signout` 303 hop; in the dev stack the outpost URL will not resolve: record what Safari shows | |
| R1 | Hand-off with the library app not installed | Web page opens; no blocking Safari alert; Help "If it opens in the browser" matches | |
| R2 | Hand-off while signed out of the library | Library sign-in; Help "If you are asked to sign in" matches | |
| R3 | `curl -X POST http://127.0.0.1:18096/__mock/mode/down`, reload Home three times | One notice, Watch struck through to `/help/trouble#unavailable`; after `ok`, recovery within about 60 s (cool-off) | |
| R4 | Installed app, Wi-Fi and data off, reload | `/offline`: one sentence, Try again (secure context only; S on plain http) | |
| R5 | Safari JavaScript off, repeat J1 to J5 | Every page works; lens printed by the server; Search is a plain form | |

## 4. iPhone Safari and installed PWA checks

| Check | How | Expected | P/F/S, notes |
|---|---|---|---|
| Widths | Portrait on the phone; 360 and 390 via Safari zoom or an SE/standard model | No sideways scroll; places bar one row at 390 with five places | |
| Text 200 % | Settings Larger Text to max, and Safari page zoom 200 % | Reflows, no clipped words, tab bar edge to edge with its own capsule | |
| VoiceOver headings | Rotor, Headings | One `h1` per page ("Avrana Media" hidden on non-Home pages); eyebrow `h2`s | |
| VoiceOver landmarks | Rotor, Landmarks | Skip link first; one main; nav "Sections" last | |
| Tab bar state | Swipe to each tab | Current tab announced (`aria-current` page; "true" on deeper pages) | |
| Card names | Swipe through Continue | One link per card: title, line, time left, action; no upstream product names | |
| Reduce Motion | Accessibility, Motion | No page fade, no art flight, no lens slide | |
| Dark and light | Control Centre appearance | Both readable; status in words, never colour alone | |
| Safe areas | Installed app, portrait, notch/Island device | Content clear of the notch and home indicator; tab bar above it | |
| Artwork | Covers and posters | Original colour and aspect; title always beside in words | |
| Install | Share, Add to Home Screen | Named "Avrana Media"; record standalone or Safari behaviour on hand-off | |

## 5. TV checks, kept distinct

- **5a TV browser Home (only if the owner has a TV browser and Step B1 is approved).** D-pad through Home,
  Library and Search: the yellow focus ring is visible on every control, nothing focused hides under the tab bar,
  Select opens the focused link, Back returns. Record the TV, browser and version.
- **5b Native Jellyfin TV app (AVR-479).** On the TV's own Jellyfin client, with the owner's own account, open
  and play one item, then return. This records the TV app's sign-in boundary and playback, independent of Avrana.
- **Not tested and not claimed:** a phone controlling or starting playback on a TV (AVR-754).

## 6. Identity and isolation spot checks (synthetic identities only)

At `/_dev/identity` (Step A or B1), switch between pairs; every page carries the "DEVELOPMENT IDENTITY" banner.

| # | Check | Expected | P/F/S, notes |
|---|---|---|---|
| I1 | `member-a`, then `member-b`: compare Home and Continue | Different items; only the one shared recent title in both | |
| I2 | `member-nolib`: Home, Library, Search, Me | Movies and TV never named, counted, linked or searched | |
| I3 | Copy a `member-a` title URL, open it as `member-nolib` | 404, not 403; nothing about the title shown | |
| I4 | `member-c` | "Not set up yet" block and "What to do next" | |
| I5 | `comics-a` vs `comics-b` | Identical Comics items (shared view by owner decision) | |

## 7. Evidence already available vs physically untested

Automated, Linux, 2026-10-26, on #80 (`847b8d4`), local runs, not GitHub CI:

- `python -B tests/ui/harness/run_ui.py`: 39 pages x 2 viewports (390x844, 1280x800), 0 axe serious/critical.
- `python -B tests/ui/harness/pwa_run.py`: 56 passed / 0 failed and 44 / 0.
- `python -B tests/ui/harness/motion_run.py`: 20 / 0.
- Static export (`tests/ui/export_home_static.py`, `tests/ui/check_home_export.mjs`): 978 views, 0 findings.
- Known open: AVR-756 intermittent `/readyz` result; #81 and #82 above are not in this revision.

All of that is Chromium with emulated widths and doubled root font size. **Physically untested:** WebKit and
Safari, VoiceOver, iOS Larger Text, the installed iOS app and its safe areas, the service worker on iOS, the
`Clear-Site-Data` sign-out in Safari (Q6), real hand-offs, no-app and signed-out recovery, TV focus, and any TV
playback.

## 8. Owner decisions

| Decision | Choice |
|---|---|
| LAN preview: approve Step B1 (fixture-only, password gated, own PR first) or B2 (no LAN preview) | B2 (2026-10-27); phone pass moves to Step C on the beta hostname |
| Visual: approve or reject the Concept K Home at `847b8d4`, with notes | Approved from iPhone-size screenshots of main (2026-10-27): "looks great" |
| AVR-729: should Library show the member's in-progress items (F-8, Q2)? | |
| AVR-730: which surfaces name the upstream app ("Resume in Jellyfin" vs "Resume") (F-9, Q1)? | |
