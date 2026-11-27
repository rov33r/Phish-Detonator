#!/usr/bin/env bash
# One-time VM setup on Ubuntu 24.04: Docker, gVisor, Caddy (docs/KICKOFF.md section 3). Safe to re-run.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https

command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
[ -z "${SUDO_USER:-}" ] || usermod -aG docker "$SUDO_USER"

curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor --yes -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
  > /etc/apt/sources.list.d/gvisor.list

curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list

apt-get update
apt-get install -y runsc caddy python3.12-venv git
runsc install
systemctl restart docker
docker run --rm --runtime=runsc hello-world
# The Vultr Ubuntu image enables ufw with only port 22 open.
if command -v ufw >/dev/null; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi
echo "bootstrap ok"
