#!/usr/bin/env bash
# Layer 1: ufw / INPUT. Covers the BARE-METAL host services only -- ufw cannot filter
# Docker-published ports (see rules-docker-user.sh for those).
#
# Stages rules only. Does NOT enable ufw; apply-firewall.sh owns that step.
# Revalidated against the live listener set on 2026-08-28 21:30.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }

LAN=${LAN_NET:-10.0.0.0/24}

ufw --force reset >/dev/null 2>&1 || true   # start from a known-empty rule set
ufw default deny incoming  >/dev/null
ufw default allow outgoing >/dev/null       # Cloudflare tunnel dials OUT; this is what keeps it up

# ---- SSH FIRST ------------------------------------------------------------------------
# Every login on record comes from the LAN (10.0.0.129/130/146).
ufw allow from "$LAN" to any port 22 proto tcp comment 'SSH from LAN'

# ---- bare-metal services that ufw genuinely filters ------------------------------------
ufw allow from "$LAN" to any port 8082 proto tcp comment 'SABnzbd (login required)'
ufw allow from "$LAN" to any port 8090 proto tcp comment 'Mylar3 (login required)'
ufw allow from "$LAN" to any port 8096 proto tcp comment 'Jellyfin (host networking)'
ufw allow from "$LAN" to any port 8123 proto tcp comment 'Home Assistant / Kern HQ'
ufw allow from "$LAN" to any port 7359 proto udp comment 'Jellyfin client discovery'
ufw allow from "$LAN" to any port 1900 proto udp comment 'SSDP/DLNA (Jellyfin + UniFi)'
ufw allow from "$LAN" to any port 5353 proto udp comment 'mDNS (Jellyfin, HA, UniFi)'

# ---- UniFi OS Server: console + device adoption ----------------------------------------
# NOTE: 80 is deliberately NOT in this list. It is not UniFi -- it is a host
# nginx (nginx/1.24.0 Ubuntu) whose only enabled site, `homeassistant`, proxies to
# http://192.168.122.108:8123, a libvirt VM that no longer exists. It answers 502. That is
# the "dead nginx site" the 2026-08-20 audit flagged. Home Assistant now runs as a
# container on host networking at :8123, which IS allowed above. Opening 80 would publish
# a broken proxy for no one.
for p in 8080 8444 8880 8881 8882 6789 9543 11443 28082 18555 5671; do
  ufw allow from "$LAN" to any port "$p" proto tcp comment 'UniFi OS Server' >/dev/null
done
for p in 3478 10001 5514; do
  ufw allow from "$LAN" to any port "$p" proto udp comment 'UniFi OS Server' >/dev/null
done
echo "UniFi rules staged (tcp 8080,8444,8880-8882,6789,9543,11443,28082,18555,5671; udp 3478,10001,5514)"

# ---- deliberately NOT opened ------------------------------------------------------------
# Plex 32400/tcp + 32410-32414/udp : untouched by request. Plex will lose LAN reach when
#   ufw is enabled. If Plex must keep serving until it is retired, uncomment:
#     ufw allow from "$LAN" to any port 32400 proto tcp comment 'Plex (pending retirement)'
# whisper-flask 5005 : service retired 2026-08-28, no longer listening. No rule.
# nginx :80          : dead `homeassistant` site proxying to a libvirt VM that is gone
#   (502). Recommend `systemctl disable --now nginx` -- awaiting approval. No rule.
# Health API 8240    : retired 2026-08-28. No rule.
# Loopback-only ports (2376, 10200, 10300, 20241, 20243, 11002, 11084, 18554, 32401,
#   32600, 36605, 45355) are unreachable off-host by binding. No rule, by design.
# Cloudflare-tunnelled hostnames need NO inbound rule: cloudflared dials outbound.

echo "INPUT rules staged. ufw NOT enabled yet."
ufw status numbered 2>/dev/null || true
