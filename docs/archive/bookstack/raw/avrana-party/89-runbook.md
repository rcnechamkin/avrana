---
bookstack_page_id: 89
title: "Runbook"
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

# Runbook
Run these on `party` (`ssh party`). Read-only unless noted.

## Health check

```sh
systemctl is-active nginx NetworkManager avahi-daemon avranaparty-games avranaparty-arcade
nmcli -t -f NAME,DEVICE,STATE con show --active     # Avrana Party on wlan1, home Wi-Fi on wlan0
curl -s http://127.0.0.1:8097/stats                  # arcade: players, max_players, fps, error
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/          # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/arcade/   # 200
curl -s -o /dev/null -w '%{http_code} %header{cache-control}\n' \
  -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html  # 200 no-store
vcgencmd get_throttled; vcgencmd measure_temp        # see Decisions & Current State
```

## Logs

```sh
sudo journalctl -u avranaparty-arcade -n 100 --no-pager
tail -n 50 /home/cody/avrana-party/arcade/runtime/emulator.log   # capped at 20 MB, one rotation
```

## Arcade control (changes state; ask first if a game is in progress)

```sh
sudo systemctl restart avranaparty-arcade
sudo systemctl disable --now avranaparty-arcade   # stop only the arcade; /arcade/ then returns 502
python3 /home/cody/avrana-party/arcade/audit-legacy-rom.py   # ROM audit
```

LAN Games, the AP and the portal are unaffected by arcade restarts. Do not run `test-receiver.py --controls` while someone holds P1.

## Config drift check

The nginx trio must be byte-identical, and live files must match the repo:

```sh
cd /home/cody/avrana-party
cmp /etc/nginx/sites-available/avrana-party avrana-party.nginx
cmp avrana-party.nginx arcade/nginx-site
cmp /var/www/avrana-portal/index.html portal/index.html
cmp /etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf avrana-captive.conf
cmp /etc/systemd/system/avranaparty-arcade.service arcade/avranaparty-arcade.service
git status --short
```

## Changing live config

1. Edit locally, commit, then deploy to `party` and test. (No sync method is defined yet: the Pi checkout has no git remote. Confirm the method before deploying.)
2. Back up the live file first. The installers write to `/home/cody/avrana-party/backups/<UTC-timestamp>/`.
3. Validate nginx (`sudo nginx -t`) before `sudo systemctl reload nginx`.
4. Ask before touching networking, the captive portal, systemd units or nginx.

## Do not

- Rerun `install-*.py` or `arcade/install-service.py` blindly. `install-service.py` overwrites the live nginx site from `arcade/nginx-site`, then copies it over `avrana-party.nginx`.
- Restore old nginx backups over newer edits.
- Disable `wlan0`, rename the host to `avrana.local`, or remove either captive-DNS name.
- Commit ROMs, emulator cores, runtime data or secrets.

## Acceptance checks

**Portal:** the probe request above returns 200, `text/html`, `no-store` and the Avrana page (200, not 304, with a future `If-Modified-Since`). On the iPhone, forget any old Avrana Party network, rejoin, confirm the landing page, tap Let's play, and check name entry, room join and reconnect after screen lock.

**Arcade:** in a regular phone browser open `http://party.local/arcade/`, tap Play, Enable sound, Add coin, then check controls and reconnect after screen lock. Two-phone test (not yet done): confirm each phone controls its own player and coin/start work independently.

**Offline (not yet done):** requires a planned test with management access kept available. Ethernet being idle is not an offline test, because `wlan0` still provides internet.
