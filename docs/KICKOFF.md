# Kickoff: Start Development

## 1. Event Facts

| Item | Answer |
|---|---|
| Submission deadline | 19:00 (event runs 09:00 to 21:00, hacking from 10:00) |
| Judging criteria | Execution and innovation; containment first is required. Recommended: dashboard of the execution loop, retries and screenshot trail; approve-before-submit gate on irreversible browser actions (SPEC 6.6) |
| Pitch length and format | Recorded demo video with one containment moment; how to submit: ask the organizers |
| Pre-written code allowed | Yes |
| Credits working | ___ |

## 2. Vultr Console Setup (Lane A, first 20 minutes)

1. Apply the gift code at Billing, or confirm credits with the organizers.
2. **Cloud Compute:** region Stockholm, Ubuntu 24.04, 4 vCPU / 8 GB. Add the team's SSH keys.
3. **Firewall Group:** inbound 22 (team IPs), 80, 443. Attach to the VM.
4. **Serverless Inference:** subscribe, copy the inference API key (not the account API key).
5. **Object Storage:** create a subscription and bucket `phishdet-evidence`, copy endpoint, access key, secret key.
6. Account API key (for high-risk mode later): Account, API, enable, restrict to the VM IP.

## 3. VM Bootstrap (Lane A)

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# gVisor
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt-get update && sudo apt-get install -y runsc python3.12-venv
sudo runsc install && sudo systemctl restart docker
docker run --rm --runtime=runsc hello-world

# Caddy
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy
```

Host names (replace `IP-DASHED`, for example `203-0-113-5`):

| Host | Role |
|---|---|
| `app.IP-DASHED.sslip.io` | Product UI (HTTPS) |
| `vexalo.IP-DASHED.sslip.io` | Legit test site (HTTP) |
| `vexalo-docs.IP-DASHED.nip.io` | Phishing kit test site (HTTP) |
| `cdn-metrics.IP-DASHED.sslip.io` | Collector (HTTP) |

## 4. Model Check (Lane B, first 20 minutes)

```bash
curl -s https://api.vultrinference.com/v1/models -H "Authorization: Bearer $VULTR_INFERENCE_KEY" | python3 -m json.tool
```
Candidates: `glm-5.3`, `deepseek-v4.1-flash-1017` (text), `qwen3.8-flash-next` (vision); see SPEC 6.5. Send 10 test calls with the action schema (SPEC 6.3). Keep the model with 10 of 10 valid JSON. Put its ID in `PD_MODEL`, the second best in `PD_MODEL_FALLBACK`.

## 5. First Test: agent-browser Attach (Lane A, right after the image builds)

```bash
docker run -d --name cdptest --runtime=runsc --shm-size=1g pd-sandbox:latest sleep infinity
docker exec cdptest sh -c 'find / -type f \( -name chrome -o -name chromium \) 2>/dev/null'   # note the Chrome path
docker exec -d cdptest sh -c 'Xvfb :99 -screen 0 1920x1080x24'
docker exec -d -e DISPLAY=:99 cdptest <CHROME_PATH> --no-sandbox --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 --disable-blink-features=AutomationControlled --window-size=1920,1080 \
  --user-data-dir=/tmp/profile --no-first-run about:blank
sleep 3
docker exec cdptest agent-browser --cdp 9222 open https://example.com
docker exec cdptest agent-browser --cdp 9222 snapshot -i
docker exec cdptest agent-browser --cdp 9222 eval "navigator.webdriver"
docker rm -f cdptest
```
Pass: snapshot prints elements with refs, `navigator.webdriver` is `false`. Fail: build `sandbox/act.mjs` (SPEC 5.6) and tell Lane B the action names do not change.

## 6. First Prompt for Lane A (paste into Claude Code)

```
Read CLAUDE.md, then docs/SPEC.md sections 4, 5, 6A.2, 6A.4, 13 and 16.
1. Create app/db.py, app/config.py and the interface stubs from CLAUDE.md section 7. Open a PR and merge it first, so lanes B and C can build on it.
2. Build sandbox/Dockerfile from reference/spike/Dockerfile: non-root user pd (uid 10001),
   PLAYWRIGHT_BROWSERS_PATH=/ms-playwright, agent-browser with Chrome readable by pd.
3. Write sandbox/bot.mjs, sandbox/victim-start.sh, sandbox/recorder.mjs (SPEC 5.3 to 5.5).
4. Implement app/sandbox.py (SPEC 5.2) with PD_RUNTIME from env.
5. Write deploy/netlock.sh (SPEC 5.7).
Stop after acceptance tests A1, A7 and A8 pass and show the output.
```

## 7. First Prompt for Lane B (paste into Claude Code)

```
Read CLAUDE.md, then docs/SPEC.md sections 6, 6A, 8, 9 and 10, and docs/EVENTS.md.
Wait for the interface stubs on main (CLAUDE.md section 7), then:
1. Build fixtures/app.py: legit Vexalo site, phishing kit (all 5 stages, landing bot check,
   collector CORS, mobile-only variant /m/), /news, collector, /botd (SPEC 9).
   Route by Host header. Run locally on port 8081.
2. Build app/llm.py (OpenAI SDK, Vultr base URL, JSON parse with one repair retry).
3. Build app/agent.py (SPEC 6) using sandbox.exec_in. Test against the kit with a local runc container.
4. Build app/verdict.py (SPEC 8.2 to 8.4) and app/brands.json.
Stop after acceptance tests A2, A5 and A6 pass and show the output.
```

## 7b. First Prompt for Lane C (paste into Claude Code)

```
Read CLAUDE.md, then docs/SPEC.md sections 10, 11 and 17, and docs/EVENTS.md.
1. Build app/main.py: routes from SPEC 10, SSE that replays stored events then streams live ones.
   Until the orchestrator exists, POST /api/scans starts a fake scan that emits a scripted
   sequence of events matching docs/EVENTS.md (behind PD_FEATURE_FAKE_SCAN=1).
2. Build the UI (SPEC 11): a visible workflow timeline (plan, sandboxes created, each agent step
   with its reason and screenshot, evidence, verdict, sandboxes destroyed), Scanner saw vs
   Victim saw split screen, password trail, verdict with linked evidence, live footer counters.
3. Add tests for the routes and the SSE replay in tests/test_main.py.
Stop when a fake scan plays end to end in the browser; show a screenshot.
```

## 8. Second Prompts (after the first stop)

- **All lanes:** SPEC 11A showcase features for your lane (owners in CLAUDE.md section 6), after your core acceptance tests pass.
- **Lane A:** orchestrator (round 1 in parallel, `dispatch` for investigator tools, profiles incl. `victim_mobile`, cleanup in finally), caps and rate limit (SPEC 10), Object Storage, Caddyfile and systemd units, deploy to the VM. Target: public URL by 15:00 (A7, A8, A12, A14).
- **Lane B:** investigator (SPEC 6A), claim checks (SPEC 8.4), vision brand check (8.3), `/api/scoreboard` job (A9); tune prompts until A2 and A11 pass 3 of 3 (A13 as a unit test).
- **Lane C:** investigation board, containment panel, swap the fake scan for `orchestrator.run_scan`, scoreboard page, three demo presets, polish, README, architecture diagram, video.
