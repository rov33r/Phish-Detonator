"""Static guards for the robot visit (SPEC 5.3); the behavior itself is checked under gVisor (A1)."""
import json
import pathlib
import shutil
import subprocess

import pytest

SANDBOX = pathlib.Path(__file__).resolve().parents[1] / "sandbox"
BOT = (SANDBOX / "bot.mjs").read_text()


def test_robot_has_no_evasion():
    assert "chromium.launch({ headless: true, args: ['--no-sandbox'] })" in BOT
    for trick in ("AutomationControlled", "addInitScript", "userAgent", ".click("):
        assert trick not in BOT


def test_robot_writes_what_verdict_and_investigator_read():
    for key in ("final_url:", "title:", "text:", "status,", "has_password_field:"):
        assert key in BOT
    for artifact in ("robot.json", "final.png", "log('network'", "log('navigations'", "'blocked' : 'failed'", "log('crash'"):
        assert artifact in BOT


def test_image_ships_the_robot():
    dockerfile = (SANDBOX / "Dockerfile").read_text()
    assert "COPY bot.mjs " in dockerfile
    assert " netlock.mjs " in dockerfile


def test_both_recorders_filter_blocked_through_netlock():
    for name in ("bot.mjs", "recorder.mjs"):
        source = (SANDBOX / name).read_text()
        assert "import { isLockBlock } from './netlock.mjs';" in source
        assert "isLockBlock(request.url(), error) ? 'blocked' : 'failed'" in source


# Only network-lock hits may reach blocked.jsonl; anything else made M5 fire on ordinary sites.
LOCK_CASES = [
    ("http://169.254.169.254/latest/meta-data/", "net::ERR_CONNECTION_REFUSED", True),
    ("http://172.30.0.1:8000/api/health", "net::ERR_CONNECTION_REFUSED", True),
    ("http://70.34.206.32:443/", "net::ERR_CONNECTION_REFUSED", True),
    ("http://[::1]:8000/", "net::ERR_ADDRESS_UNREACHABLE", True),
    ("http://localhost:8000/", "net::ERR_CONNECTION_REFUSED", True),
    ("https://ads.example.com/pixel.gif", "net::ERR_CONNECTION_REFUSED", False),
    ("http://10.0.0.5/", "net::ERR_ABORTED", False),
    ("https://cdn.example.com/a.js", "net::ERR_NAME_NOT_RESOLVED", False),
    ("https://api.example.com/x", "net::ERR_FAILED", False),
    ("not a url", "net::ERR_CONNECTION_REFUSED", False),
]


def test_lock_filter_counts_only_lock_hits():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = (
        f"import {{ isLockBlock }} from {json.dumps((SANDBOX / 'netlock.mjs').as_uri())};"
        "const cases = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(cases.map(([u, e]) => isLockBlock(u, e))));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(LOCK_CASES)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert json.loads(result.stdout) == [expected for _, _, expected in LOCK_CASES]
