"""Laptop dev scan: the real agent, model and verdict against the local fixtures, no Docker.

Stands in for Lane A's pieces with local equivalents, so Lane B can test end to end today:
  robot visit   -> headless Playwright (like bot.mjs)
  victim Chrome -> headful Chrome for Testing with the victim flags (like victim-start.sh)
  recorder      -> Playwright over CDP writing network/navigations/probes/blocked.jsonl
  exec_in       -> runs agent-browser on this machine; /out maps to the visit folder

Usage (needs VULTR_INFERENCE_KEY and PD_MODEL in .env):
  set -a; . ./.env; set +a
  .venv/bin/python scripts/dev_scan.py            # kit
  .venv/bin/python scripts/dev_scan.py legit      # legit Vexalo
  .venv/bin/python scripts/dev_scan.py mobile     # mobile-only kit (desktop victim; investigator not wired yet)
A Chrome window opens: that is the victim browser. Never point this at real phishing links:
the laptop has no gVisor and no network lock.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from app import agent, verdict  # noqa: E402

PORT = 8081
SESSION = f"pd-dev-{uuid.uuid4().hex[:6]}"
TARGETS = {
    "kit": f"http://vexalo-docs.localhost:{PORT}/",
    "legit": f"http://vexalo.localhost:{PORT}/",
    "mobile": f"http://vexalo-docs.localhost:{PORT}/m/",
}
PROBE_SCRIPT = """
(() => {
  const log = (name) => console.debug('__PD_PROBE', name);
  Object.defineProperty(Navigator.prototype, 'webdriver', {get() { log('webdriver'); return false; }});
})();
"""
COLORS = {"agent_step": "36", "approval": "33", "decoy_sent": "31", "hypothesis_update": "35",
          "verdict": "1;32", "claim_rejected": "31", "error": "1;31"}


def say(kind: str, text: str) -> None:
    print(f"\033[{COLORS.get(kind, '0')}m[{kind}]\033[0m {text}", flush=True)


def emit(scan_id: str, type: str, payload: dict) -> None:
    if type == "agent_step":
        say(type, f"{payload['step']:>2} {payload['action']:<6} {payload.get('ref') or '':<5} "
                  f"{payload['reason']}  ({payload['model']})")
    elif type == "approval":
        say(type, f"{payload['decision']}: " + ", ".join(f"{c['name']} {'ok' if c['ok'] else 'FAIL'}"
                                                         for c in payload["checks"]))
    elif type == "decoy_sent":
        say(type, f"{payload['field']} -> {payload['host']} ({payload['encoding']})")
    elif type == "hypothesis_update":
        say(type, f"{payload['id']} {payload['status']}: {payload['reason']}")
    elif type == "verdict":
        say(type, f"{payload['verdict']}  action={payload['action_taken']}")
        for r in payload["reasons"]:
            print(f"      {r['signal']:<3} {r['text']}")
    elif type != "screenshot":
        say(type, json.dumps(payload)[:300])


def wait_port(port: int, timeout: float = 15) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise SystemExit(f"nothing listening on {port}")


def robot_visit(url: str, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        status = {}
        page.on("response", lambda r: status.update(code=r.status)
                if r.request.is_navigation_request() and r.frame == page.main_frame else None)
        page.goto(url, wait_until="load")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(out / "final.png"))
        robot = {"final_url": page.url, "title": page.title(), "text": page.inner_text("body")[:4000],
                 "status": status.get("code"), "has_password_field": page.query_selector("input[type=password]") is not None}
        browser.close()
    (out / "robot.json").write_text(json.dumps(robot, indent=2))
    say("robot", f"saw {robot['final_url']} '{robot['title']}' password field: {robot['has_password_field']}")


class Recorder(threading.Thread):
    """Subset of sandbox/recorder.mjs (SPEC 5.5) over CDP."""

    def __init__(self, out: pathlib.Path):
        super().__init__(daemon=True)
        self.out, self.ready, self.stop = out, threading.Event(), threading.Event()

    def log(self, name: str, item: dict) -> None:
        with (self.out / f"{name}.jsonl").open("a") as f:
            f.write(json.dumps({"ts": time.time(), **item}) + "\n")

    def watch(self, page) -> None:
        page.on("framenavigated", lambda f: self.log("navigations", {"url": f.url}) if f == page.main_frame else None)
        page.on("console", lambda m: self.log("probes", {"name": m.args[1].json_value()})
                if m.text.startswith("__PD_PROBE") and len(m.args) > 1 else None)

    def run(self) -> None:
        from urllib.parse import urlsplit
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            ctx = browser.contexts[0]
            ctx.add_init_script(PROBE_SCRIPT)
            ctx.on("request", lambda r: self.log("network", {
                "method": r.method, "url": r.url, "host": urlsplit(r.url).hostname,
                "resourceType": r.resource_type, "postData": (r.post_data or "")[:4096] or None}))
            ctx.on("requestfailed", lambda r: self.log("blocked", {
                "url": r.url, "host": urlsplit(r.url).hostname, "error": r.failure}))
            for page in ctx.pages:
                self.watch(page)
            ctx.on("page", self.watch)
            self.ready.set()
            while not self.stop.is_set():
                (ctx.pages[0] if ctx.pages else ctx.new_page()).wait_for_timeout(200)


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "kit"
    url = TARGETS[target]
    for var in ("VULTR_INFERENCE_KEY", "PD_MODEL"):
        if not os.environ.get(var):
            raise SystemExit(f"{var} is not set: run `set -a; . ./.env; set +a` first")
    os.environ.pop("PD_PUBLIC_IP_DASHED", None)  # fixtures derive *.localhost siblings

    scan_id = f"dev-{target}-{uuid.uuid4().hex[:6]}"
    scan_dir = ROOT / "scans" / scan_id
    scan_dir.mkdir(parents=True)
    decoy = agent.make_decoy()
    (scan_dir / "decoy.json").write_text(json.dumps(decoy))
    say("scan", f"{scan_id} -> {url}  decoy {decoy['email']}")

    env = {**os.environ, "PD_COLLECTOR_LOG": str(scan_dir / "collector.log")}
    fixtures = subprocess.Popen([sys.executable, "-m", "uvicorn", "fixtures.app:app", "--port", str(PORT),
                                 "--log-level", "warning"], cwd=ROOT, env=env)
    chrome = None
    try:
        wait_port(PORT)
        robot_visit(url, scan_dir / "robot")

        with sync_playwright() as p:
            chrome_path = p.chromium.executable_path
        profile = tempfile.mkdtemp(prefix="pd-victim-")
        chrome = subprocess.Popen([
            chrome_path, "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222",
            "--disable-blink-features=AutomationControlled", "--window-size=1280,900", "--lang=sv-SE",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_port(9222)

        victim_out = scan_dir / "victim"
        victim_out.mkdir()
        recorder = Recorder(victim_out)
        recorder.start()
        recorder.ready.wait(15)

        def exec_local(container: str, args: list[str], timeout: int = 30) -> tuple[int, str]:
            args = [a.replace("/out/", f"{victim_out}/") if a.startswith("/out/") else a for a in args]
            args = [args[0], "--session", SESSION, *args[1:]]  # never touch the user's own agent-browser session
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout + (r.stderr if r.returncode else "")

        agent._exec = exec_local
        agent._emit = emit
        agent._out_dir = lambda s, v: scan_dir / v
        verdict._emit = emit
        verdict._update = lambda s, **f: None
        brands = verdict.load_brands()
        brands["brands"]["Vexalo"].append("vexalo.localhost")
        verdict.load_brands = lambda path=None: brands

        summary = agent.run_victim(scan_id, url, f"pd-{scan_id}-victim", decoy)
        time.sleep(1)
        recorder.stop.set()
        say("summary", json.dumps(summary))
        result = verdict.decide(scan_id, scan_dir=scan_dir)
        say("done", f"evidence in {scan_dir.relative_to(ROOT)}  ({result['verdict']})")
    finally:
        subprocess.run(["agent-browser", "--session", SESSION, "close"], capture_output=True)
        if chrome:
            chrome.terminate()
        fixtures.terminate()


if __name__ == "__main__":
    main()
