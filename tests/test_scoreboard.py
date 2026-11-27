"""app/scoreboard.py with a fake sandbox (A9 logic). No Docker."""
import json
import sys
import types

import pytest

from app import scoreboard as sb

ROBOT_OUT = '{"bot":true,"botKind":"headless_chrome"}'
VICTIM_EVALS = ('"loading"', json.dumps('{"bot":false}'))


class FakeSandbox:
    def __init__(self, victim_evals=VICTIM_EVALS):
        self.started, self.stopped, self.calls = [], [], []
        self.evals = list(victim_evals)

    def start_visit(self, scan_id, visit, profile):
        self.started.append(profile)
        return f"pd-{scan_id}-{visit}"

    def stop_visit(self, container):
        self.stopped.append(container)

    def exec_in(self, container, args, timeout=30):
        self.calls.append(args)
        if args[0] == "node":
            return 0, "some log line\n" + ROBOT_OUT + "\n"
        if args[-2] == "open":
            return 0, "ok"
        return 0, self.evals.pop(0)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    box = FakeSandbox()
    monkeypatch.setitem(sys.modules, "app.sandbox", types.SimpleNamespace(
        start_visit=box.start_visit, stop_visit=box.stop_visit, exec_in=box.exec_in))
    import app
    monkeypatch.setattr(app, "sandbox", sys.modules["app.sandbox"], raising=False)
    monkeypatch.setattr(sb, "_sleep", lambda s: None)
    box.path = tmp_path / "scoreboard.json"
    return box


def test_pass_when_robot_caught_and_victim_passes(fake):
    r = sb.run("sc1", "http://vexalo-docs.x.nip.io/botd", save_to=fake.path)
    assert r["robot"]["bot"] is True and r["robot"]["botKind"] == "headless_chrome"
    assert r["victim"]["bot"] is False and r["pass"] is True
    assert fake.started == ["robot", "victim"] and len(fake.stopped) == 2
    assert json.loads(fake.path.read_text())["pass"] is True
    assert sb.latest(fake.path)["victim"]["bot"] is False


def test_url_is_an_argument_not_code(fake):
    sb.run("sc1", "http://vexalo-docs.x.nip.io/botd", save_to=fake.path)
    node = next(c for c in fake.calls if c[0] == "node")
    assert node[:2] == ["node", "-e"] and node[3] == "http://vexalo-docs.x.nip.io/botd"
    assert "vexalo-docs" not in node[2]


def test_one_side_failing_still_reports_and_cleans_up(fake):
    fake.exec_in = lambda c, a, timeout=30: (1, "chrome crashed") if a[0] == "node" else FakeSandbox.exec_in(fake, c, a)
    import app
    app.sandbox.exec_in = fake.exec_in
    r = sb.run("sc1", "http://x/botd", save_to=fake.path)
    assert r["robot"]["bot"] is None and "chrome crashed" in r["robot"]["error"]
    assert r["victim"]["bot"] is False and r["pass"] is False and len(fake.stopped) == 2


def test_victim_timeout(fake, monkeypatch):
    fake.evals = ['"loading"'] * 100
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(sb, "_now", lambda: next(clock))
    r = sb.run("sc1", "http://x/botd", save_to=fake.path)
    assert "did not answer" in r["victim"]["error"]


def test_parse_result_handles_double_quoted_json():
    assert sb.parse_result(json.dumps('{"bot": false}')) == {"bot": False}
    with pytest.raises(ValueError):
        sb.parse_result("nope")


def test_botd_url_uses_public_ip(monkeypatch):
    monkeypatch.setenv("PD_PUBLIC_IP_DASHED", "203-0-113-5")
    assert sb.botd_url() == "http://vexalo-docs.203-0-113-5.nip.io/botd"


def test_latest_missing_is_none(tmp_path):
    assert sb.latest(tmp_path / "none.json") is None
