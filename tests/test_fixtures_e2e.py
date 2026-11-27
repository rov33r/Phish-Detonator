"""Real-browser test of the fixtures (SPEC 9): proves the kit works in Chromium, not only in strings.

- Robot (plain headless Chromium) is sent to /news by the landing-page bot check (A1 logic).
- A desktop "victim" walks share page, gate, login; the decoy reaches the collector through
  the CORS preflight (S1 logic) and the browser lands on the legit site (M4 logic).
- The hostile script fires its three internal requests (A12 logic).
- The mobile-only variant blocks desktop and opens for a phone.

Hosts are *.localhost, which Chromium resolves to 127.0.0.1. Skipped without Playwright.
"""
import json
import os
import socket
import threading
import time

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

DECOY = {"email": "nora.berg.4c1d2e@fjord-mail.com", "password": "Kq8!vT2mZr5pLx9w"}
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
PHONE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")
# The victim profile sets these through CDP in the sandbox (SPEC 5.5); here an init script does it.
LIKE_A_PERSON = """
Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => false});
Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {get: () => 8});
if (navigator.plugins.length === 0)
  Object.defineProperty(Navigator.prototype, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    log = tmp_path_factory.mktemp("fx") / "collector.log"
    mp = pytest.MonkeyPatch()
    mp.delenv("PD_PUBLIC_IP_DASHED", raising=False)
    mp.setenv("PD_COLLECTOR_LOG", str(log))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config("fixtures.app:app", host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield {"kit": f"http://vexalo-docs.localhost:{port}", "legit": f"vexalo.localhost:{port}", "log": log}
    srv.should_exit = True
    thread.join(5)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        except Exception as e:  # browser binary not installed
            if os.environ.get("PD_E2E_REQUIRED") == "1":
                raise
            pytest.skip(f"chromium not available: {e}")
        yield b
        b.close()


def test_robot_is_cloaked_to_news(server, browser):
    page = browser.new_page()
    page.goto(server["kit"] + "/")
    page.wait_for_url("**/news", timeout=5000)
    assert "Stockholm today" in page.content()
    page.close()


def test_victim_walks_kit_and_decoy_reaches_collector(server, browser):
    ctx = browser.new_context(user_agent=DESKTOP_UA)
    ctx.add_init_script(LIKE_A_PERSON)
    page = ctx.new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    page.goto(server["kit"] + "/")
    page.get_by_text("Review document").click()
    page.get_by_label("I am not a robot").check()
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url("**/login")
    page.get_by_label("Email").fill(DECOY["email"])
    page.get_by_label("Password").fill(DECOY["password"])
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"http://{server['legit']}/login", timeout=5000)

    posted = [json.loads(json.loads(line)["body"]) for line in server["log"].read_text().splitlines()]
    assert DECOY in posted
    for target in ("169.254.169.254", "172.30.0.1:8000", "127.0.0.1:443"):
        assert any(target in u for u in seen), f"hostile request to {target} not attempted"
    ctx.close()


def test_mobile_kit_blocks_desktop(server, browser):
    ctx = browser.new_context(user_agent=DESKTOP_UA)
    ctx.add_init_script(LIKE_A_PERSON)
    page = ctx.new_page()
    page.goto(server["kit"] + "/m/")
    assert page.get_by_text("only be opened on a phone").is_visible()
    assert not page.get_by_text("Review document").is_visible()
    ctx.close()


def test_mobile_kit_opens_for_phone(server, browser):
    ctx = browser.new_context(user_agent=PHONE_UA, is_mobile=True, has_touch=True,
                              viewport={"width": 412, "height": 915}, device_scale_factor=2.625)
    ctx.add_init_script(LIKE_A_PERSON)
    page = ctx.new_page()
    page.goto(server["kit"] + "/m/")
    page.get_by_text("Review document").click()
    page.wait_for_url("**/m/gate")
    ctx.close()
