FROM node:22-bookworm

# Virtual display for the "victim" (headful) browser profile
RUN apt-get update && apt-get install -y --no-install-recommends xvfb fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /t

# Playwright + Chromium (probe.mjs)
RUN npm init -y >/dev/null && npm i playwright@1 && npx playwright install --with-deps chromium

# agent-browser (Vercel Labs) + its Chrome for Testing
RUN npm i -g agent-browser && (agent-browser install --with-deps || echo "agent-browser install failed")

COPY probe.mjs entry.sh ./
RUN chmod +x entry.sh
ENTRYPOINT ["./entry.sh"]
