#!/usr/bin/env bash
# Network lock for sandboxes (docs/SPEC.md 5.7). VM only. Safe to re-run; run again after a reboot.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

SUBNET=172.30.0.0/24
docker network inspect pd-net >/dev/null 2>&1 || docker network create --driver bridge --subnet "$SUBNET" pd-net

# Docker's embedded resolver (127.0.0.11) on a user-defined network does not answer under gVisor,
# even with --dns. Sandboxes mount this file over /etc/resolv.conf instead.
install -d -m 755 /etc/phishdet
printf 'nameserver 1.1.1.1\n' > /etc/phishdet/resolv.conf
chmod 644 /etc/phishdet/resolv.conf

insert() { # insert <chain> <rule...>: delete any copy, then put it on top
  local chain=$1; shift
  while iptables -D "$chain" "$@" 2>/dev/null; do :; done
  iptables -I "$chain" "$@"
}

# Forwarded traffic to private, link-local and metadata ranges.
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
  insert DOCKER-USER -s "$SUBNET" -d "$net" -j REJECT
done

# Traffic to the host itself goes through INPUT. ACCEPT is inserted last, so it is checked first.
insert INPUT -s "$SUBNET" -j REJECT
insert INPUT -s "$SUBNET" -p tcp --dport 80 -j ACCEPT

iptables -L INPUT -n --line-numbers | head -5
iptables -L DOCKER-USER -n --line-numbers
