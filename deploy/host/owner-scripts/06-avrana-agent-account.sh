#!/usr/bin/env bash
# The agent containment account (bug hunt section E, approved in principle 2026-10-03). Run as root:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/06-avrana-agent-account.sh
#
# Creates `avrana-agent`: own home (0700), no sudo, not in `docker`, not in group `cody`, so it
# cannot list or write /home/cody (mode 750) and cannot reach the Docker socket. Its SSH key is
# the laptop key already in cody's authorized_keys. A memory ceiling on its user slice stops a
# runaway process (the 26 GB bash of 2026-09-20 would have been killed in its own cgroup).
# `avrana-ro` (deploy/host/avrana-ro) is installed as the only privileged thing the account can
# run: fixed read-only subcommands, executed as cody through sudo, every use in the journal.
#
# After this, add to the laptop's ~/.ssh/config a host `avrana-agent` with User avrana-agent and
# keep `avrana` (User cody) for admin work. Rollback: `userdel -r avrana-agent`, remove the
# sudoers file, the slice drop-in and /usr/local/bin/avrana-ro.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
A=avrana-agent
id "$A" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --comment "Avrana coding agent (unprivileged)" "$A"
chmod 700 "/home/$A"
groups "$A" | grep -qE '\b(docker|cody|sudo)\b' && { echo "REFUSING: $A is in docker, cody or sudo"; exit 1; }
install -d -m 700 -o "$A" -g "$A" "/home/$A/.ssh"
install -m 600 -o "$A" -g "$A" /home/cody/.ssh/authorized_keys "/home/$A/.ssh/authorized_keys"
echo "authorized_keys copied from cody ($(wc -l < /home/cody/.ssh/authorized_keys) key(s))"

uid=$(id -u "$A")
install -d /etc/systemd/system/user-"$uid".slice.d
cat > /etc/systemd/system/user-"$uid".slice.d/memory.conf <<'EOF'
[Slice]
MemoryMax=6G
MemoryHigh=5G
TasksMax=2048
EOF
systemctl daemon-reload

install -m 755 /home/cody/avrana/deploy/host/avrana-ro /usr/local/bin/avrana-ro
cat > /etc/sudoers.d/avrana-agent <<'EOF'
# The agent account may run the read-only wrapper as cody, nothing else. Logged by sudo.
avrana-agent ALL=(cody) NOPASSWD: /usr/local/bin/avrana-ro
EOF
chmod 440 /etc/sudoers.d/avrana-agent
visudo -cf /etc/sudoers.d/avrana-agent

echo "== checks"
sudo -u "$A" ls /home/cody >/dev/null 2>&1 && { echo "FAIL: $A can list /home/cody"; exit 1; } || echo "ok: $A cannot list /home/cody"
sudo -u "$A" docker ps >/dev/null 2>&1 && { echo "FAIL: $A can use Docker"; exit 1; } || echo "ok: $A cannot use Docker"
sudo -u "$A" sudo -n -u cody /usr/local/bin/avrana-ro status | head -3 | sed 's/^/   /'
echo "ok: avrana-ro works through sudo"
