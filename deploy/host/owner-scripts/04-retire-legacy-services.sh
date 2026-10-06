#!/usr/bin/env bash
# Retire what the owner decided to retire (docs/DECISIONS.md, 2026-10-03). Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/04-retire-legacy-services.sh
#
#   - the comics.avrana.media tunnel (`cloudflared.service`, config-comics.yml); the 12 current
#     hostnames stay on cloudflared-avrana.service
#   - nine dead unit files for services that no longer exist (Kern Prime API, health tunnel,
#     comic watcher, JDownloader, Whisper, health watcher, duplicate summarize_lastfm)
#   - nginx (answered on :80 for a VM that no longer exists), libvirt (no VMs)
#   - Plex Media Server: stopped, disabled and the package removed; its library data under
#     /var/lib/plexmediaserver is KEPT until you purge it by hand
# Every unit file is saved first. Health and baseline checks derive the tunnel count from the
# enabled units, so nothing else needs editing. Rollback: copy the saved units back,
# daemon-reload, enable. Plex: apt-get install plexmediaserver (the data is still there).
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
B=/mnt/avrana_media/.backups/batch3-20261006/rollback/system-units
mkdir -p "$B"; chmod 700 "$B"
systemctl list-unit-files --no-legend 'cloudflared*' 'nginx*' 'libvirt*' 'virt*' 'plexmediaserver*' > "$B/UNIT-STATES-BEFORE.txt"

echo "== comics tunnel"
systemctl disable --now cloudflared.service && echo "   cloudflared.service (comics) stopped and disabled"
for u in cloudflared.service cloudflared-comics.service cloudflared-health.service comic-watcher.service \
         jdownloader2.service whisper.service remote-faster-whisper.service watch-health.service \
         avrana.service summarize_lastfm.service; do
  f=/etc/systemd/system/$u
  [[ -f "$f" ]] || continue
  systemctl disable "$u" >/dev/null 2>&1 || true
  mv "$f" "$B/" && echo "   saved and removed $u"
done
systemctl daemon-reload; systemctl reset-failed

echo "== nginx, libvirt"
systemctl disable --now nginx.service && echo "   nginx stopped and disabled"
systemctl disable --now libvirtd.service libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket \
  libvirt-guests.service virtlogd.service virtlogd.socket virtlogd-admin.socket \
  virtlockd.service virtlockd.socket virtlockd-admin.socket 2>&1 | grep -v '^$' | sed 's/^/   /'
echo "   libvirt disabled"

echo "== Plex"
systemctl disable --now plexmediaserver.service && echo "   plexmediaserver stopped and disabled"
apt-get remove -y plexmediaserver >/dev/null && echo "   package removed; /var/lib/plexmediaserver kept ($(du -sh /var/lib/plexmediaserver 2>/dev/null | cut -f1))"

echo "== verify"
echo "   tunnels running: $(ps -eo args --no-headers | awk '$1 ~ /cloudflared$/ && $2=="tunnel"' | wc -l) (want 1)"
echo "   port 80 listener: $(ss -ltn | grep -c ':80 ') (want 0)"
echo "   failed system units: $(systemctl --failed --no-legend | wc -l)"
sudo -u cody /home/cody/avrana/scripts/services-health.sh >/tmp/h.txt 2>&1; echo "   services-health rc=$? ($(grep -c '^FAIL' /tmp/h.txt) FAIL lines)"
echo "Then run deploy/docker/verify-baseline.sh as cody; it should say 1 tunnel and BASELINE CLEAN."
