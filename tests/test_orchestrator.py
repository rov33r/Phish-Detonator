"""app/orchestrator.py with sandbox, agent, investigator and verdict stubbed: no Docker, network or key."""
import json
import threading
import time

import pytest

from app import db, orchestrator, sandbox


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("PD_SCANS_DIR", str(tmp_path))
    monkeypatch.setattr(orchestrator, "_slots", {})
    w = {"started": [], "stopped": [], "exec": [], "victims": [], "steps": [], "decide": None}

    def start_visit(scan_id, visit, profile):
        sandbox.out_dir(scan_id, visit).mkdir(parents=True, exist_ok=True)
        name = f"pd-{scan_id}-{visit}"
        w["started"].append((name, profile))
        return name

    def exec_in(container, args, timeout=30):
        w["exec"].append(args)
        scan_id, visit = container.split("-", 2)[1:]
        robot = {"final_url": args[-1] + "news", "title": "News", "has_password_field": False}
        (sandbox.out_dir(scan_id, visit) / "robot.json").write_text(json.dumps(robot))
        return 0, "{}"

    def run_victim(scan_id, url, container, decoy, goal=None, *, visit=None):
        w["victims"].append((visit, goal, decoy["email"]))
        return {}

    def investigate(scan_id, round1, dispatch):
        w["round1"] = [s["visit"] for s in round1]
        for step in w["steps"]:
            dispatch(step)
        return {"claims": [{"signal": "S1"}], "action": "block", "untested": []}

    def decide(scan_id, claims=None, *, action="block", untested=None):
        w["decide"] = (claims, action, untested)
        return {"verdict": "Phishing"}

    monkeypatch.setattr(sandbox, "start_visit", start_visit)
    monkeypatch.setattr(sandbox, "exec_in", exec_in)
    monkeypatch.setattr(sandbox, "stop_visit", lambda c: w["stopped"].append(c))
    monkeypatch.setattr(orchestrator.agent, "run_victim", run_victim)
    monkeypatch.setattr(orchestrator.investigator, "plan", lambda scan_id, url: {"hypotheses": []})
    monkeypatch.setattr(orchestrator.investigator, "investigate", investigate)
    monkeypatch.setattr(orchestrator.verdict, "decide", decide)
    return w


def wait_for(cond, timeout=5):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def types(scan_id):
    return [e["type"] for e in db.events(scan_id)]


def test_full_scan_runs_round1_and_followups_and_destroys_every_sandbox(world, tmp_path):
    world["steps"] = [{"tool": "victim_mobile", "args": {"reason": "r"}, "reason": "I test a phone."},
                      {"tool": "robot_followup", "args": {"host": "collect.vexalo.test", "reason": "r"}, "reason": "x"},
                      {"tool": "victim_retry", "args": {"goal": "open the file", "reason": "r"}, "reason": "y"}]
    orchestrator.run_scan("s1", "http://kit.test/share", "standard")

    assert sorted(c for c, _ in world["started"]) == sorted(world["stopped"])
    assert [p for _, p in world["started"]][2:] == ["victim_mobile", "robot", "victim"]
    assert world["round1"] == ["robot", "victim"]
    assert ["node", "bot.mjs", "http://collect.vexalo.test/"] in world["exec"]
    assert ("victim-5", "open the file", world["victims"][0][2]) in world["victims"]
    assert world["decide"] == ([{"signal": "S1"}], "block", [])

    events = db.events("s1")
    dispatches = [e["payload"] for e in events if e["type"] == "dispatch"]
    assert [(d["visit"], d["round"]) for d in dispatches] == [
        ("robot", 1), ("victim", 1), ("victim_mobile-3", 2), ("robot-4", 3), ("victim-5", 4)]
    assert dispatches[-1]["budget_left"]["sandboxes"] == 0
    assert types("s1").count("sandbox_destroyed") == 5
    assert types("s1").count("robot_done") == 2
    done = next(e["payload"] for e in events if e["type"] == "robot_done")
    assert done["screenshot"] == "robot/final.png"
    assert db.get_scan("s1")["status"] == "finished"
    assert db.get_scan("s1")["verdict"] == "Phishing"
    decoy = json.loads((tmp_path / "s1" / "decoy.json").read_text())
    assert next(e for e in events if e["type"] == "scan_started")["payload"]["decoy_email"] == decoy["email"]


def test_visit_error_still_destroys_sandbox_and_scan_finishes(world, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("agent crashed")

    monkeypatch.setattr(orchestrator.agent, "run_victim", broken)
    orchestrator.run_scan("s2", "http://kit.test/", "standard")
    assert sorted(world["stopped"]) == ["pd-s2-robot", "pd-s2-victim"]
    errors = [e["payload"] for e in db.events("s2") if e["type"] == "error"]
    assert errors == [{"where": "visit:victim", "message": "RuntimeError: agent crashed"}]
    assert db.get_scan("s2")["status"] == "finished"


def test_investigator_failure_falls_back_to_rules(world, monkeypatch):
    def broken(*a, **k):
        raise TimeoutError("model down")

    monkeypatch.setattr(orchestrator.investigator, "investigate", broken)
    monkeypatch.setattr(orchestrator.investigator, "fallback_conclude",
                        lambda scan_id: {"args": {"claims": [], "action": "none", "untested": ["rules only"]}})
    orchestrator.run_scan("s3", "http://kit.test/", "standard")
    assert world["decide"] == ([], "none", ["rules only"])
    assert "error" in types("s3")


def test_plan_failure_does_not_stop_round1(world, monkeypatch):
    def broken(scan_id, url):
        raise KeyError("VULTR_INFERENCE_KEY")

    monkeypatch.setattr(orchestrator.investigator, "plan", broken)
    orchestrator.run_scan("s6", "http://kit.test/", "standard")
    assert world["round1"] == ["robot", "victim"]
    assert db.get_scan("s6")["status"] == "finished"


def test_unknown_tool_is_rejected(world):
    orchestrator._context["s4"] = {"url": "http://x/", "decoy": {}, "n": 2}
    try:
        with pytest.raises(ValueError):
            orchestrator.dispatch("s4", {"tool": "shell", "args": {}})
    finally:
        orchestrator._context.pop("s4")
    assert world["started"] == []


def test_time_limit_kills_the_sandbox(world, monkeypatch, tmp_path):
    monkeypatch.setitem(sandbox.LIMITS, "seconds", 0.05)
    monkeypatch.setattr(orchestrator, "TIME_LIMIT_GRACE", 0)
    monkeypatch.setattr(orchestrator.agent, "run_victim", lambda *a, **k: time.sleep(0.3))
    orchestrator.run_scan("s5", "http://kit.test/", "standard")
    hit = [e["payload"] for e in db.events("s5") if e["type"] == "resource_limit_hit"]
    assert {"visit": "victim", "kind": "time", "peak_mb": 0, "limit_mb": 2048} in hit
    assert (tmp_path / "s5" / "victim" / "resource_limit.json").exists()


def test_scans_over_the_cap_queue(world, monkeypatch):
    monkeypatch.setenv("PD_MAX_SCANS", "1")
    gate = threading.Event()
    monkeypatch.setattr(orchestrator.investigator, "plan", lambda scan_id, url: gate.wait(5))
    first = threading.Thread(target=orchestrator.run_scan, args=("q1", "http://kit.test/", "standard"))
    first.start()
    wait_for(lambda: db.events("q1"))
    second = threading.Thread(target=orchestrator.run_scan, args=("q2", "http://kit.test/", "standard"))
    second.start()
    wait_for(lambda: db.events("q2"))
    assert db.events("q2")[0]["type"] == "scan_queued"
    assert db.events("q2")[0]["payload"] == {"position": 1}
    gate.set()
    first.join(5)
    second.join(5)
    assert db.get_scan("q2")["status"] == "finished"
