#!/usr/bin/env bash
# Capture EVERYTHING needed to put the firewall back exactly as it was.
# Run as root. Prints the snapshot directory on the last line -- callers parse that.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
D="/home/cody/backups/firewall-$STAMP"
mkdir -p "$D"

# Both backends: this host is iptables-nft, so iptables-save is the restore path,
# but capture the raw nft ruleset too in case anything was added natively.
iptables-save            > "$D/iptables.v4"        2>"$D/iptables.v4.err"
ip6tables-save           > "$D/iptables.v6"        2>"$D/iptables.v6.err"
nft list ruleset         > "$D/nftables.ruleset"   2>"$D/nftables.err"

# ufw's own state: config, rule files, and the rendered status.
cp -a /etc/ufw           "$D/etc-ufw"              2>/dev/null
cp -a /etc/default/ufw   "$D/default-ufw"          2>/dev/null
ufw status verbose       > "$D/ufw-status.txt"     2>&1
ufw status numbered      > "$D/ufw-numbered.txt"   2>&1
systemctl is-enabled ufw > "$D/ufw-unit.txt"       2>&1
systemctl is-active  ufw >>"$D/ufw-unit.txt"       2>&1

# Reachability + fleet state at snapshot time, so a restore can be compared against it.
ss -tlnp                 > "$D/listeners-tcp.txt"  2>/dev/null
ss -ulnp                 > "$D/listeners-udp.txt"  2>/dev/null
docker ps --format '{{.Names}}\t{{.Status}}' > "$D/containers.txt" 2>/dev/null
docker network ls -q | xargs -r docker network inspect \
  --format '{{.Name}}|{{range .IPAM.Config}}{{.Subnet}}{{end}}' > "$D/docker-subnets.txt" 2>/dev/null
cp -a /etc/docker/daemon.json "$D/docker-daemon.json" 2>/dev/null

chmod -R go-rwx "$D"
{
  echo "snapshot: $STAMP"
  echo "restore:  bash /home/cody/avrana/deploy/ufw/rollback-firewall.sh $D"
} > "$D/README.txt"

echo "$D"
