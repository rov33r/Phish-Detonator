#!/bin/sh
# Starts the victim browser (docs/SPEC.md 5.4), then stays alive as the recorder (5.5).
# Host: docker exec -d <container> ./victim-start.sh, then wait for /tmp/recorder.ready.
set -eu
export DISPLAY=:99

Xvfb :99 -screen 0 1920x1080x24 >/tmp/xvfb.log 2>&1 &
i=0
until [ -e /tmp/.X11-unix/X99 ]; do
  i=$((i + 1)); [ "$i" -lt 100 ] || { echo "Xvfb did not start" >&2; exit 1; }
  sleep 0.1
done

LANGUAGE=sv-SE pd-chrome --no-sandbox --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --disable-blink-features=AutomationControlled --window-size=1920,1080 --lang=sv-SE \
  --user-data-dir=/tmp/profile --no-first-run --no-default-browser-check about:blank >/tmp/chrome.log 2>&1 &
i=0
until curl -sf http://127.0.0.1:9222/json/version >/dev/null; do
  i=$((i + 1)); [ "$i" -lt 150 ] || { echo "Chrome CDP did not open" >&2; exit 1; }
  sleep 0.2
done

exec node /opt/pd/recorder.mjs >/tmp/recorder.log 2>&1
