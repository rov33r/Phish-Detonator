#!/bin/sh
# Usage: entry.sh <bot|victim|ab> <runtime-label>
mode="$1"; rt="$2"

case "$mode" in
  victim)
    exec xvfb-run -a -s "-screen 0 1920x1080x24" node probe.mjs victim "$rt"
    ;;
  ab)
    agent-browser open https://example.com \
      && agent-browser screenshot "/out/$rt-agent-browser.png" \
      && agent-browser eval "navigator.webdriver"
    status=$?
    agent-browser close >/dev/null 2>&1
    exit $status
    ;;
  *)
    exec node probe.mjs bot "$rt"
    ;;
esac
