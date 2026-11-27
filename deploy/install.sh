#!/usr/bin/env bash
# Installs or updates the app on the VM from the code in /opt/phishdet. Safe to re-run.
# From a laptop: git archive origin/main | ssh root@<vm> 'tar -x -C /opt/phishdet' && ssh root@<vm> 'bash /opt/phishdet/deploy/install.sh'
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
cd /opt/phishdet

ip=$(sed -n 's/^PD_PUBLIC_IP_DASHED=//p' /etc/phishdet/env)
[ -n "$ip" ] || { echo "PD_PUBLIC_IP_DASHED missing in /etc/phishdet/env" >&2; exit 1; }

[ -x .venv/bin/python ] || python3.12 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
docker build -q -t pd-sandbox:latest sandbox/
install -d -m 700 /var/lib/phishdet /var/lib/phishdet/scans

install -m 644 deploy/phishdet.service deploy/phishdet-fixtures.service deploy/phishdet-netlock.service /etc/systemd/system/
sed "s/PD_IP/$ip/g" deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable -q phishdet-netlock phishdet-fixtures phishdet
systemctl restart phishdet-netlock phishdet-fixtures phishdet
systemctl reload caddy
echo "install ok: https://app.$ip.sslip.io"
