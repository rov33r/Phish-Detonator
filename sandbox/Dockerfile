# Sandbox image (docs/SPEC.md 5.1). Runs as uid 10001 with a read-only root and a tmpfs over /home/pd,
# so nothing the visit needs may be installed under /home/pd.
FROM node:22-bookworm

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends xvfb fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pd
RUN npm init -y >/dev/null && npm i playwright@1 && npx playwright install --with-deps chromium

# agent-browser installs its Chrome for Testing under $HOME, so point HOME at a world-readable directory.
# pd-chrome is the stable path victim-start.sh uses.
RUN npm i -g agent-browser@0.43.0 \
    && HOME=/opt/agent-browser agent-browser install --with-deps \
    && chmod -R a+rX /opt/agent-browser /ms-playwright \
    && chrome="$(find /opt/agent-browser -type f -name chrome -perm -u+x | head -n 1)" \
    && test -n "$chrome" && ln -s "$chrome" /usr/local/bin/pd-chrome

COPY bot.mjs recorder.mjs victim-start.sh ./
RUN chmod 755 victim-start.sh && chmod 644 bot.mjs recorder.mjs \
    && useradd --uid 10001 --create-home --home-dir /home/pd pd

USER 10001:10001
ENV HOME=/home/pd
