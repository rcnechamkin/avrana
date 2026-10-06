#!/usr/bin/env bash
# Bring cloudflared under package management and up to date (bug hunt C3: 2025.6.1, a manually
# installed binary at /usr/local/bin, 15 months old, the only internet-facing component).
# Run as root on avrana, after 04-retire-legacy-services.sh:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/07-update-cloudflared.sh
#
# Adds Cloudflare's apt repository (key pinned by fingerprint check), installs the package to
# /usr/bin/cloudflared, points cloudflared-avrana.service at it, restarts the tunnel (about 10 s
# of public downtime), and verifies 12/12 hostnames. The old binary is kept as
# /usr/local/bin/cloudflared.2025.6.1 for rollback. Package upgrades are excluded from unattended
# upgrades by 02-host-hardening.sh, so later updates happen when you run `apt upgrade`.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
UNIT=/etc/systemd/system/cloudflared-avrana.service
B=/mnt/avrana_media/.backups/batch4-20261006/rollback/cloudflared
mkdir -p "$B"; chmod 700 "$B"; cp -p "$UNIT" "$B/"
echo "before: $(cloudflared --version 2>/dev/null | head -1)"

echo "== apt repository"
install -d -m 755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo "key fingerprint: $(gpg --no-default-keyring --keyring /usr/share/keyrings/cloudflare-main.gpg --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr/{print $10; exit}')"
echo "   (compare with https://pkg.cloudflare.com before continuing; Ctrl-C now aborts with nothing changed)"
read -rp "   continue? [y/N] " yn; [[ "$yn" == y ]] || exit 1
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
apt-get update -qq
apt-get install -y cloudflared
NEW=$(command -v cloudflared); [[ "$NEW" == /usr/bin/cloudflared ]] || { echo "unexpected path $NEW"; exit 1; }
echo "installed: $(/usr/bin/cloudflared --version | head -1)"

echo "== unit"
mv /usr/local/bin/cloudflared /usr/local/bin/cloudflared.2025.6.1
sed -i 's#^ExecStart=/usr/local/bin/cloudflared #ExecStart=/usr/bin/cloudflared #' "$UNIT"
grep -n '^ExecStart' "$UNIT"
systemctl daemon-reload
systemctl restart cloudflared-avrana.service
sleep 8
systemctl is-active cloudflared-avrana.service

echo "== hostnames"
bad=0
for h in auth avrana books contribute kindle listen ops read requestabook requestacomic request watch; do
  [[ "$h" == avrana ]] && u=https://avrana.net/ || u=https://$h.avrana.net/
  c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$u")
  case "$c" in 200|204|301|302|303|307|308|401|403) ;; *) echo "   $u -> $c"; bad=$((bad+1));; esac
done
if [[ $bad -eq 0 ]]; then echo "   12/12 hostnames answer"; else
  echo "   $bad hostname(s) failed: rolling back"
  cp -p "$B/cloudflared-avrana.service" "$UNIT"; mv /usr/local/bin/cloudflared.2025.6.1 /usr/local/bin/cloudflared
  systemctl daemon-reload; systemctl restart cloudflared-avrana.service; exit 1
fi
install -m 644 "$UNIT" /home/cody/avrana/deploy/host/cloudflared/cloudflared-avrana.service && chown cody:cody /home/cody/avrana/deploy/host/cloudflared/cloudflared-avrana.service
echo "done; commit deploy/host/cloudflared/cloudflared-avrana.service"
