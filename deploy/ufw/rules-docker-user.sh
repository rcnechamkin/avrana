#!/usr/bin/env bash
# Layer 2: DOCKER-USER. This is the ONLY place a firewall can constrain Docker-published
# ports -- ufw's INPUT chain never sees them, because Docker DNATs in nat/PREROUTING and
# accepts through its own FORWARD chains.
#
# Design note, and the reason this file contains no subnet literals for the bridges:
# the pending default-address-pools migration (deploy/docker/apply-address-pools.sh)
# renumbers every Docker bridge into 10.210.0.0/16 and 10.211.0.0/16. Rules keyed on
# bridge subnets would silently stop matching the moment that runs. These rules are keyed
# on the INGRESS INTERFACE instead (br0 = the physical LAN), which is unaffected by any
# renumbering.
#
# Idempotent: flushes and rebuilds the chain each time. Run as root.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }

LAN_IF=${LAN_IF:-br0}
LAN_NET=${LAN_NET:-10.0.0.0/24}

# Docker creates DOCKER-USER itself; create it only if Docker has not started yet.
iptables -N DOCKER-USER 2>/dev/null || true
iptables -F DOCKER-USER

# 1. Replies to connections the host/containers initiated must always pass.
iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN

# 2. Traffic that did NOT arrive on the physical LAN is none of our business: this is
#    container-to-container, docker0, libvirt and loopback-sourced traffic. Returning
#    early is what keeps inter-service calls, Cloudflare tunnel egress and the -arr
#    stack's internal chatter working.
iptables -A DOCKER-USER ! -i "$LAN_IF" -j RETURN

# 3. From the LAN, the trusted home subnet reaches the published services.
iptables -A DOCKER-USER -i "$LAN_IF" -s "$LAN_NET" -j RETURN

# 4. Anything else arriving on the LAN interface for a container is dropped. This is what
#    closes off other VLANs, a guest network, or a router forwarding foreign sources.
iptables -A DOCKER-USER -i "$LAN_IF" -j DROP

# 5. Default: fall through to Docker's own rules.
iptables -A DOCKER-USER -j RETURN

echo "DOCKER-USER installed ($LAN_IF / $LAN_NET):"
iptables -S DOCKER-USER
