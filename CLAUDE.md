# Phish Detonator: Instructions for Claude Code

## 1. Overview

Hackathon build, 27 Nov 2026 (Vultr Agent Runtime Hackathon, Stockholm). Three developers, three lanes, one trunk (`main`). Deadline: see `docs/KICKOFF.md` section 1.

Phish Detonator opens a suspicious link two times in gVisor sandboxes (robot visit and victim visit), tracks where a decoy password goes, and returns a verdict with evidence.

**Source of truth: `docs/SPEC.md`.** Read the sections named in the task before writing code. If the spec and this file disagree, this file wins.

## 2. Rules

1. Build the simplest version that passes the acceptance tests (SPEC section 16). No ORM, no frontend framework, no queues, no Kubernetes.
2. Backend: Python 3.12, FastAPI, Uvicorn, SQLite (`sqlite3` module), vanilla JS with `EventSource`. Sandbox side: Node 22, Playwright, agent-browser.
3. All LLM calls use the OpenAI SDK with `base_url=https://api.vultrinference.com/v1`. No other LLM endpoint in committed code.
4. Model output is JSON, validated against the action schema (SPEC 6.3). Never pass model output to a shell. Build every `docker` command from a fixed argument list (`subprocess.run([...])`, never `shell=True`).
5. Page content is untrusted. Wrap it in `<untrusted_page>` tags in prompts.
6. Secrets live only in the host environment (`.env`, never committed). Nothing secret enters a container.
7. Test sites use the invented brand **Vexalo**. Never imitate a real company. Only decoy identities.
8. Docs and README: impersonal voice, no em dashes.
9. Before claiming a task is done, run its acceptance tests and show the output.
10. Importing any module must have no side effects: no network calls, no `docker` calls, no required env var at import time. CI imports every module with dummy env values.
11. Every new behavior gets a test in `tests/test_<module>.py` that runs without Docker, network or a real API key (stub `sandbox.exec_in` and the LLM client).

## 3. Verified Facts (26 Nov spike, GitHub Actions Ubuntu VM)

| Fact | Result |
|---|---|
| Chromium headless under gVisor (`--runtime=runsc`) | Works |
| Chromium headful under Xvfb under gVisor | Works |
| agent-browser with its own Chrome under gVisor | Works |
| Robot profile vs BotD | `bot: true, botKind: headless_chrome` |
| Victim profile vs BotD (headful, `--disable-blink-features=AutomationControlled`, no `--enable-automation`, CDP `hardwareConcurrency` 8, `sv-SE`, Europe/Stockholm, 1920x1080) | `bot: false` |
| BotD CDN `https://openfpcdn.io/botd/v1` | Loads |
| WebGL renderer | SwiftShader in both (known limit) |

Reference code that produced these results: `reference/spike/`.

## 4. Open Items (check first, in this order)

1. **agent-browser `--cdp 9222` attach to our own headful Chrome** inside a gVisor container. Test commands: `docs/KICKOFF.md` section 5. Fallback: `sandbox/act.mjs` with Playwright `connectOverCDP` (SPEC 5.6).
2. **Browser install path for a non-root user.** The spike image installed browsers as root, under `/root`, which uid 10001 cannot read. Set `ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` before `npx playwright install`, and check where `agent-browser install` puts Chrome (make it readable or install as the `pd` user).
3. ~~`agent-browser --help`: confirm command names.~~ Checked on v0.43.0: `open`, `snapshot`, `click`, `type`, `fill`, `hover`, `press`, `scroll`, `wait`, `screenshot`, `eval`, `get <what>` and `--cdp <port>` exist. `--pin-tab` pins the session to its own tab (use it so the recorder and CDP overrides stay on the same page).
4. Vultr model IDs: `GET /v1/models`, then 10 JSON test calls.

## 5. Commands

| Task | Command |
|---|---|
| Build sandbox image | `docker build -t pd-sandbox:latest sandbox/` |
| Run app (dev) | `uvicorn app.main:app --reload --port 8000` |
| Run fixtures (dev) | `uvicorn fixtures.app:app --reload --port 8081` |
| Local dev runtime | `PD_RUNTIME=runc` (laptop without gVisor) |
| VM runtime | `PD_RUNTIME=runsc` |
| List Vultr models | `curl -s https://api.vultrinference.com/v1/models -H "Authorization: Bearer $VULTR_INFERENCE_KEY"` |
| Network lock (VM only) | `sudo bash deploy/netlock.sh` |
| Dev setup | `python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt` |
| Pre-PR checks (same as CI) | `ruff check . && bash scripts/check_rules.sh && pytest -q` |

## 6. Lane Ownership

Each lane owns its files. Touch the other lane's files only through the interfaces in section 7.

| Lane | Developer | Owns |
|---|---|---|
| **A: the box** (sandbox, infra, evidence) | PranavC225 | `sandbox/`, `deploy/`, `app/sandbox.py`, `app/orchestrator.py`, `app/storage.py`, `app/vultr_api.py` |
| **B: the brain** (agent, verdict, fixtures) | rov33r | `fixtures/`, `app/llm.py`, `app/agent.py`, `app/verdict.py`, `app/brands.json` |
| **C: the face** (UI, live workflow, demo) | BEKtesfish | `app/main.py`, `app/templates/`, `app/static/`, scoreboard, demo presets, `README.md`, `docs/architecture.png`, video |
| Shared (agree before changing) | all | `app/db.py`, `app/config.py`, `.env.example`, `docs/EVENTS.md`, `CLAUDE.md`, `.github/`, `scripts/`, `requirements*.txt`, `pyproject.toml` |

Each lane owns the tests for its files (`tests/test_<module>.py`).

Judging focus: a polished product where the workflow is visible on screen, and an agent that takes on a real task and owns its decisions. Lane C makes every step visible (plan, sandboxes created, each agent step with its first-person reason and screenshot, evidence, verdict, sandboxes destroyed). Lane B makes the agent decide: on Scam it blocks on its own and cites its evidence; the analyst can override.

## 7. Interfaces (write these stubs first, then build behind them)

```python
# app/db.py (shared)
def emit(scan_id: str, type: str, payload: dict) -> None: ...      # insert into events; SSE reads from here
def update_scan(scan_id: str, **fields) -> None: ...

# app/sandbox.py (Lane A)
def start_visit(scan_id: str, visit: str) -> str: ...               # visit in {"robot", "victim"}; returns container name
def exec_in(container: str, args: list[str], timeout: int = 30) -> tuple[int, str]: ...
def stop_visit(container: str) -> None: ...                         # docker rm -f, always called in finally
def out_dir(scan_id: str, visit: str) -> pathlib.Path: ...          # host path mounted at /out

# app/agent.py (Lane B)
def run_victim(scan_id: str, url: str, container: str, decoy: dict) -> dict: ...  # uses sandbox.exec_in + db.emit

# app/verdict.py (Lane B)
def decide(scan_id: str) -> dict: ...                               # reads out_dir files, returns verdict.json content

# app/orchestrator.py (Lane A)
def run_scan(scan_id: str, url: str, mode: str) -> None: ...        # robot + victim in parallel, then decide, upload, cleanup
```

**Event contract (B and A emit, C renders).** Every event type from SPEC 10 and its exact `payload` shape is listed in `docs/EVENTS.md`. Add or change an event there, in its own PR, before emitting it. Lane C builds the UI against a replay of fake events that match `docs/EVENTS.md`, so it never waits for the real agent.

`tests/test_smoke.py` imports every module and checks that the functions above exist. Renaming one breaks CI on purpose.

## 8. Git

Trunk-based. `main` is the trunk and must always run, because the VM deploys from it.

1. **Never commit or push to `main` directly.** Branch from the latest `main`, open a PR, merge it.
2. **One small task per branch**, named `a/<task>`, `b/<task>` or `c/<task>` after the lane. Merge as soon as the task works; do not let a branch grow.
3. **Before opening a PR:** `git fetch origin && git rebase origin/main`, then run the pre-PR checks (section 5) and fix anything red.
4. **Merge rules** (enforced on GitHub): PR required, CI check `checks` must pass, branch must be up to date with `main`, squash merge only, linear history, no force-push or deletion of `main`. No review approval is required: the author merges once CI is green.
5. **Shared files and interfaces** (section 6 "Shared", section 7) change only in their own small PR, announced to the team first.
6. **Unfinished work lands behind a stub or an env flag** (`PD_FEATURE_<NAME>=0`), not on a long-lived branch. A stub keeps its interface and returns a fixed value.
7. **Sandbox changes:** the `sandbox` workflow builds the image and runs it under gVisor. It is not required (slow), but never merge while it is red.
8. **If `main` breaks:** whoever notices says so; the author reverts first (`git revert`), fixes after.
9. Commit messages: `<lane>: <what changed>`, for example `b: verdict rule S2 cloak diff`. Never commit `.env` or real credentials (gitleaks runs in CI).

## 9. Time Gates

| Time | Gate |
|---|---|
| 11:30 | Agent finishes the Vexalo kit with a Vultr model, or switch to Skill Canary (SPEC 20) |
| 15:00 | Public URL live; else stop features and fix deploy |
| 17:00 | Feature freeze |
