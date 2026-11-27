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

# Chrome flags and TZ hold from the first request in every tab; the recorder's CDP overrides arrive too late for that.
if [ "${PD_PROFILE:-victim}" = victim_mobile ]; then
  major=$(pd-chrome --version | sed 's/^[^0-9]*\([0-9]*\)\..*/\1/')
  set -- --window-size=412,915 --touch-events=enabled \
    "--user-agent=Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$major.0.0.0 Mobile Safari/537.36"
else
  set -- --window-size=1920,1080
fi

TZ=Europe/Stockholm LANGUAGE=sv-SE pd-chrome --no-sandbox --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 --disable-blink-features=AutomationControlled "$@" --lang=sv-SE \
  --user-data-dir=/tmp/profile --no-first-run --no-default-browser-check about:blank >/tmp/chrome.log 2>&1 &
i=0
until curl -sf http://127.0.0.1:9222/json/version >/dev/null; do
  i=$((i + 1)); [ "$i" -lt 150 ] || { echo "Chrome CDP did not open" >&2; exit 1; }
  sleep 0.2
done

exec node /opt/pd/recorder.mjs >/tmp/recorder.log 2>&1
