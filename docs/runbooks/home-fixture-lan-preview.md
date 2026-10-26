# Home fixture LAN preview (temporary, HTTPS, synthetic data only)

AVR-585 step B1, owner decision 2026-10-26. **Do not run until the owner has approved this PR and the session.**
`services/avrana-home/dev/run_lan_preview.py` serves the Concept K Home UI with synthetic fixtures to the owner's
iPhone on the home Wi-Fi, over HTTPS, so Safari treats it as a secure context and runs the service worker. The M3
device-review packet (`docs/design/M3-DEVICE-REVIEW.md`, PR #85) refers to this as step B1.

What it is: the `run_dev.py` stack unchanged (mock Jellyfin, Audiobookshelf, Komga, Calibre-Web on `127.0.0.1`
only, plus the synthetic `/_dev/identity` switch) behind a one-time passphrase gate, bound to ONE private address of
the laptop. It never reads real libraries, member data, secrets or production configuration. It changes nothing in
Cloudflare, DNS, the router, Authentik or host `avrana`. Foreground only: no service, no scheduled task, no autostart.

## Refusals (exit 2, nothing bound)

- no `--i-understand-lan`;
- `--host` not ONE RFC 1918 IPv4 literal (10/8, 172.16/12, 192.168/16): 0.0.0.0, `::`, names, loopback,
  link-local, CGNAT and public addresses are refused;
- `--cert`/`--key` missing, unreadable, not PEM, not a matching pair, or the key inside any Git working tree;
- `JELLYFIN_*`, `AUDIOBOOKSHELF_*`, `KOMGA_*`, `CALIBRE_WEB_*`, `PREVIEW_*` or `HOME_*` (except `HOME_PWA_SW`,
  `HOME_MOTION_PROPOSAL`) set in the shell, or any upstream that is not one of the loopback mocks;
- `--minutes` outside 1..240 (default 60).

## Prerequisites (owner, once per review)

1. Install mkcert (for example `winget install FiloSottile.mkcert`) and run `mkcert -install`. This creates a local
   certificate authority in `mkcert -CAROOT` and makes this laptop trust it.
2. Find the laptop's Wi-Fi address: `ipconfig`, "Wireless LAN adapter Wi-Fi", "IPv4 Address" (say `192.168.1.23`).
   Optional name: `hostname` (say `laptop`, used as `laptop.local`; the IP address is the reliable URL).
3. Make the certificate in a folder OUTSIDE every repository. Every command in this runbook is **PowerShell**:

   ```
   mkdir "$env:USERPROFILE\avrana-preview"
   mkcert -cert-file "$env:USERPROFILE\avrana-preview\preview.pem" -key-file "$env:USERPROFILE\avrana-preview\preview-key.pem" 192.168.1.23 laptop.local
   ```

4. iPhone: send `rootCA.pem` from the `mkcert -CAROOT` folder (never `rootCA-key.pem`) by AirDrop or Files. Install
   it in Settings > General > VPN & Device Management, then turn on full trust in Settings > General > About >
   Certificate Trust Settings.

## Start

From the repository root (`avrana-homelab\avrana`; the venv is one level up), in a PowerShell window without the
real preview's variables and without `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` (the launcher refuses them):

```
..\.venv-media\Scripts\python.exe services\avrana-home\dev\run_lan_preview.py --i-understand-lan --host 192.168.1.23 --cert "$env:USERPROFILE\avrana-preview\preview.pem" --key "$env:USERPROFILE\avrana-preview\preview-key.pem" --hostname laptop.local --minutes 60
```

Options: `--port` (default 8443), `--minutes` (1..240), `--mode` (mock state at start: ok, slow, down, 500, ...).
It prints the URL, a one-time passphrase, the stop time and how to stop. The passphrase appears only in this window.

Windows Firewall asks on the first bind: tick **Private networks** only, never Public. If this Wi-Fi is set to
**Public** in Windows, the iPhone cannot connect: stop here and do the review on a trusted home network instead; do
not change the network profile or the firewall for this. On the iPhone (same Wi-Fi)
open `https://192.168.1.23:8443/`, enter the passphrase, then pick a member at `/_dev/identity` (use `member-b`).
The installed Home Screen app keeps its own cookies: enter the passphrase there once too.
Mock failure modes, from the laptop: `curl -X POST http://127.0.0.1:18096/__mock/mode/down` (then `ok`).

## Stop and expiry

- Ctrl+C in that window stops the app and every mock.
- It stops by itself at the printed time (60 minutes by default, 4 hours at most), and is force-ended 60 s later if
  a connection holds it open. Closing the window also stops it. Nothing keeps running afterwards.
- The session cookie dies with the process; a new run prints a new passphrase.
- Wrong passphrases: 5 from one address lock it out for 5 minutes; 25 in total lock the run (restart it).

## Cleanup after the review

1. iPhone: Settings > General > VPN & Device Management, remove the mkcert profile (this also removes its trust).
   Delete the Home Screen icon; Settings > Apps > Safari > Advanced > Website Data, delete the laptop address.
2. Laptop: `mkcert -uninstall`, then delete the `mkcert -CAROOT` folder and `$env:USERPROFILE\avrana-preview`.
3. Firewall rule, in an administrator PowerShell. Only the rule for this venv's interpreter; other Python rules
   stay. List first, check it is the one created on the review day, then remove:

   ```
   Get-NetFirewallApplicationFilter | Where-Object Program -like '*\avrana-homelab\.venv-media\Scripts\python.exe' | Get-NetFirewallRule | Format-Table Name, DisplayName, Profile, Direction, Action
   Get-NetFirewallApplicationFilter | Where-Object Program -like '*\avrana-homelab\.venv-media\Scripts\python.exe' | Get-NetFirewallRule | Remove-NetFirewallRule
   ```

   Or Windows Security > Firewall & network protection > Allow an app through firewall: remove only the entry whose
   path is `...\avrana-homelab\.venv-media\Scripts\python.exe`.
4. Optionally `winget uninstall FiloSottile.mkcert`.

## What this tests, and what it does not

| Tested | Not tested |
|---|---|
| iPhone Safari layout, text size, VoiceOver, Reduce Motion, dark/light, safe areas | Real libraries or real member data (never) |
| Installed PWA: install, standalone, service worker, `/offline`, update path (trusted HTTPS) | TV browsers and TV apps (step 5 of M3) |
| Synthetic identities and isolation (`/_dev/identity`) | Authentik sign-in, the outpost, G1/G2, sign-out to the outpost |
| Hand-off links, copy and the way back | Playback: links go to the real `*.avrana.net` apps with synthetic ids, so they show sign-in or "not found" |

## Security notes

- The gate is outermost: without the cookie every path returns the passphrase form (403) and no fixture data; a
  Host header other than the bound address (or the `.local` name) gets 421.
- Cookie `__Host-avrana_lan`: HttpOnly, Secure, SameSite=Strict, scoped to this run, in memory only.
- Anyone on the same Wi-Fi can reach the form while it runs; the passphrase (about 120 bits) and the throttle stand
  between them and synthetic data. Run it only on the home network, only for the review, for as short as possible.
- The mkcert CA can sign a certificate for any name while it is trusted: keep `rootCA-key.pem` on the laptop only
  and remove the CA from both devices after the review (Cleanup).
