#!/usr/bin/env bash
# Bug hunt A6 and A14. Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/02-host-hardening.sh
#
# 1. `nofail` on the mergerfs line in /etc/fstab, so a failed comics_merged mount no longer drops
#    the console into emergency mode at boot. The 15-minute health check now reports the mount
#    itself (scripts/services-health.sh). Docker is deliberately NOT made to require this mount:
#    that would turn an empty Komga library into a whole-stack outage.
# 2. Docker packages and cloudflared are excluded from unattended upgrades, so an automatic
#    docker.io update cannot restart all 40 containers at 06:00. Manual `apt upgrade` still works.
# Takes effect: 1 at the next boot; 2 immediately. Rollback: /etc/fstab.batch3 and remove the
# apt.conf.d file.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

echo "== 1/2 fstab: nofail on the mergerfs line"
cp -p /etc/fstab /etc/fstab.batch3
if grep -qE '^[^#].*fuse\.mergerfs.*\bnofail\b' /etc/fstab; then
  echo "   already has nofail"
else
  sed -i -E '/^[^#].*fuse\.mergerfs/ s/(\s)(ro,allow_other)/\1nofail,\2/' /etc/fstab
  grep -qE '^[^#].*fuse\.mergerfs.*\bnofail\b' /etc/fstab || { echo "   edit did not apply; restoring"; cp -p /etc/fstab.batch3 /etc/fstab; exit 1; }
  echo "   added"
fi
findmnt --verify --tab-file /etc/fstab >/dev/null && echo "   fstab verifies" || { echo "   fstab does NOT verify; restoring"; cp -p /etc/fstab.batch3 /etc/fstab; exit 1; }
grep -E 'fuse\.mergerfs' /etc/fstab | sed 's/^/   /'
install -m 644 /etc/fstab /home/cody/avrana/deploy/host/fstab && chown cody:cody /home/cody/avrana/deploy/host/fstab
echo "   (deploy/host/fstab updated in the live tree; commit it)"

echo "== 2/2 unattended-upgrades: blacklist Docker and cloudflared"
cat > /etc/apt/apt.conf.d/52avrana-unattended-blacklist <<'EOF'
// Batch 3 (bug hunt A14). These restart every container when upgraded; do it in a chosen window.
Unattended-Upgrade::Package-Blacklist {
    "docker.io";
    "docker-ce";
    "containerd";
    "containerd.io";
    "runc";
    "cloudflared";
};
EOF
apt-config dump | grep -A8 'Unattended-Upgrade::Package-Blacklist' | sed 's/^/   /' | head -10
install -m 644 /etc/apt/apt.conf.d/52avrana-unattended-blacklist /home/cody/avrana/deploy/host/apt/ && chown cody:cody /home/cody/avrana/deploy/host/apt/52avrana-unattended-blacklist
echo "done"
