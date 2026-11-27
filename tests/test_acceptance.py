"""scripts/acceptance.py checks, run against the recorded real investigations."""
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("acceptance", ROOT / "scripts" / "acceptance.py")
acc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acc)

RECORDINGS = ROOT / "fixtures" / "recordings"
RUNS = {"kit": "dev-kit-161e89", "mobile": "dev-mobile-80d800", "legit": "dev-legit-f1af13", "inject": "dev-inject-e9ec6b"}


def events(preset):
    return [json.loads(line) for line in (RECORDINGS / RUNS[preset] / "events.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("preset", RUNS)
def test_recorded_runs_pass(preset):
    failed = [c for c in acc.check(preset, events(preset)) if not c[1]]
    assert not failed, failed


def test_checks_cover_the_right_tests():
    ids = {c[0] for c in acc.check("kit", events("kit"))}
    assert {"verdict", "A2", "A3", "A6", "A12", "A20"} <= ids
    assert "A11" in {c[0] for c in acc.check("mobile", events("mobile"))}
    assert "INJ" in {c[0] for c in acc.check("inject", events("inject"))}


def test_wrong_verdict_fails():
    ev = events("kit")
    for e in ev:
        if e["type"] == "verdict":
            e["payload"] = {**e["payload"], "verdict": "Suspicious"}
    assert not dict((c[0], c[1]) for c in acc.check("kit", ev))["A6"]


def test_gate_after_leak_fails():
    ev = [e for e in events("kit") if e["type"] != "approval"]
    assert not dict((c[0], c[1]) for c in acc.check("kit", ev))["A20"]


def test_leftover_sandboxes_fail():
    ev = [{"type": "sandbox_created", "payload": {}}] * 2 + [{"type": "sandbox_destroyed", "payload": {}}]
    assert not dict((c[0], c[1]) for c in acc.check("legit", ev))["A7"]


def test_no_verdict_fails():
    assert not acc.check("legit", [])[0][1]
