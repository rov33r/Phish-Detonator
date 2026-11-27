"""BotD scoreboard (SPEC 7, 9.4, A9): proof that the victim browser passes for a person.

Runs the robot profile (plain headless Playwright) and the victim profile (headful Chrome with
the recorder's overrides) in fresh sandboxes against the fixture's /botd page and returns what
BotD said about each. Pass: robot `bot: true`, victim `bot: false`. Lane C serves it at
POST /api/scoreboard and shows it on the scoreboard page.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

POLL_SECONDS = 25
# Fixed script, run with `node -e` in /opt/pd (the image's workdir, where Playwright lives).
# The URL arrives as an argument, never inside the code.
ROBOT_JS = """
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto(process.argv[1], { waitUntil: 'load', timeout: 30000 });
  await page.waitForFunction(() => {
    const r = document.getElementById('result');
    return r && r.textContent !== 'loading';
  }, null, { timeout: 25000 });
  console.log(await page.textContent('#result'));
  await browser.close();
})().catch((e) => { console.error(String(e)); process.exit(1); });
"""
RESULT_JS = "document.getElementById('result') ? document.getElementById('result').textContent : 'loading'"

_sleep = time.sleep
_now = time.monotonic


def botd_url() -> str:
    ip = os.environ.get("PD_PUBLIC_IP_DASHED", "")
    return f"http://vexalo-docs.{ip}.nip.io/botd"


def parse_result(text: str) -> dict:
    """BotD's detect() JSON as printed by node or agent-browser (which may quote it once more)."""
    value = text.strip()
    for _ in range(2):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            break
        if isinstance(value, dict):
            return value
    raise ValueError(f"no BotD result in {text.strip()[:120]!r}")


def _robot(sandbox, container: str, url: str) -> dict:
    code, out = sandbox.exec_in(container, ["node", "-e", ROBOT_JS, url], timeout=60)
    if code != 0:
        raise RuntimeError(f"robot BotD run failed: {out.strip()[:200]}")
    return parse_result(out.strip().splitlines()[-1])


def _victim(sandbox, container: str, url: str) -> dict:
    browser = ["agent-browser", "--cdp", "9222", "--pin-tab"]
    code, out = sandbox.exec_in(container, [*browser, "open", url], timeout=45)
    if code != 0:
        raise RuntimeError(f"victim could not open BotD: {out.strip()[:200]}")
    deadline = _now() + POLL_SECONDS
    while _now() < deadline:
        code, out = sandbox.exec_in(container, [*browser, "eval", RESULT_JS], timeout=15)
        if code == 0 and "loading" not in out:
            return parse_result(out)
        _sleep(1)
    raise RuntimeError("BotD did not answer in the victim browser")


def run(scan_id: str | None = None, url: str | None = None, *, save_to: pathlib.Path | None = None) -> dict:
    """{robot: {bot, botKind, ...}, victim: {...}, pass, url, ran_at}. Sandboxes are always destroyed."""
    from app import sandbox
    scan_id = scan_id or f"scoreboard-{int(time.time())}"
    url = url or botd_url()
    result: dict = {"url": url, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for profile, measure in (("robot", _robot), ("victim", _victim)):
        container = None
        started = _now()
        try:
            container = sandbox.start_visit(scan_id, profile, profile)
            botd = measure(sandbox, container, url)
            result[profile] = {"bot": bool(botd.get("bot")), "botKind": botd.get("botKind"),
                               "seconds": round(_now() - started, 1), "runtime": os.environ.get("PD_RUNTIME", "runsc")}
        except Exception as e:  # one side failing still shows the other on the page
            result[profile] = {"bot": None, "error": str(e)[:300]}
        finally:
            if container:
                sandbox.stop_visit(container)
    result["pass"] = result["robot"].get("bot") is True and result["victim"].get("bot") is False
    path = save_to or pathlib.Path(os.environ.get("PD_SCANS_DIR", "scans")) / "scoreboard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return result


def latest(path: pathlib.Path | None = None) -> dict | None:
    """Last saved scoreboard, for GET on the scoreboard page."""
    path = path or pathlib.Path(os.environ.get("PD_SCANS_DIR", "scans")) / "scoreboard.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
