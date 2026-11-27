"""app/investigator.py with a scripted model over real evidence files (SPEC 6A, A11, A13)."""
import json

import pytest

from app import investigator as inv
from app import llm

IP = "203-0-113-5"
KIT = f"vexalo-docs.{IP}.nip.io"
LEGIT = f"vexalo.{IP}.sslip.io"
COLLECTOR = f"cdn-metrics.{IP}.sslip.io"
DECOY = {"email": "nora.berg.4c1d2e@fjord-mail.com", "password": "Kq8!vT2mZr5pLx9w"}


def jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


@pytest.fixture
def scan(tmp_path, monkeypatch):
    """A kit scan after round 1: robot cloaked, victim submitted the decoy to the collector."""
    monkeypatch.setenv("PD_PUBLIC_IP_DASHED", IP)
    d = tmp_path / "s1"
    (d / "robot").mkdir(parents=True)
    (d / "victim").mkdir()
    (d / "decoy.json").write_text(json.dumps(DECOY))
    (d / "robot" / "robot.json").write_text(json.dumps({
        "final_url": f"http://{KIT}/news", "title": "Stockholm news", "text": "Nothing to see",
        "status": 200, "has_password_field": False}))
    (d / "victim" / "agent.jsonl").write_text(jsonl([
        {"step": 1, "url": f"http://{KIT}/", "reason": "I click Review document", "password_field": False},
        {"step": 2, "url": f"http://{KIT}/login", "reason": "I fill the email", "password_field": True,
         "brand_seen": "Vexalo", "title": "Sign in - Vexalo"}]))
    (d / "victim" / "network.jsonl").write_text(jsonl([
        {"ts": 1, "method": "GET", "url": f"http://{KIT}/", "host": KIT},
        {"ts": 9, "method": "POST", "url": f"http://{COLLECTOR}/v1/collect", "host": COLLECTOR,
         "postData": json.dumps(DECOY)}]))
    (d / "victim" / "navigations.jsonl").write_text(jsonl([
        {"ts": 1, "url": f"http://{KIT}/"}, {"ts": 10, "url": f"http://{LEGIT}/login"}]))
    (d / "victim" / "probes.jsonl").write_text(jsonl([{"ts": 2, "name": "webdriver"}]))
    return d


@pytest.fixture
def model(monkeypatch):
    script, prompts, events = [], [], []

    def fake(messages, schema, *, name, validate=None, **kw):
        prompts.append(messages)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        data = json.loads(json.dumps(item))
        if validate:
            try:
                validate(data)
            except ValueError as e:
                raise llm.InvalidOutput(str(e)) from None
        return llm.Reply(data, "main-model")

    monkeypatch.setattr(inv.llm, "chat_json", fake)
    monkeypatch.setattr(inv, "_emit", lambda s, t, p: events.append((t, p)))
    return {"script": script, "prompts": prompts, "events": events}


def step(tool, reason="I check the next thing", host=None, goal=None, updates=(), claims=(), action=None):
    return {"tool": tool, "reason": reason, "host": host, "goal": goal, "updates": list(updates),
            "claims": list(claims), "action": action, "untested": []}


def summaries(scan):
    return [inv.visit_summary(scan, "robot"), inv.visit_summary(scan, "victim")]


# ---------- plan ----------

def test_plan_has_fixed_hypotheses_and_extra(scan, model):
    model["script"].append({"text": "I compare a robot and a victim.", "extra_hypothesis": "The kit targets Vexalo staff"})
    p = inv.plan("s1", f"http://{KIT}/", scan_dir=scan)
    assert [h["id"] for h in p["hypotheses"]] == ["H1", "H2", "H3", "H4", "H5"]
    assert all(h["status"] == "open" for h in p["hypotheses"])
    assert model["events"][0] == ("plan", p)
    assert inv.hypotheses(scan)[4]["text"] == "The kit targets Vexalo staff"


def test_plan_survives_model_failure(scan, model):
    model["script"].append(llm.LLMError("down"))
    p = inv.plan("s1", f"http://{KIT}/", scan_dir=scan)
    assert [h["id"] for h in p["hypotheses"]] == ["H1", "H2", "H3", "H4"] and p["text"]


# ---------- review ----------

def test_visit_summaries(scan):
    robot, victim = summaries(scan)
    assert robot["kind"] == "robot" and robot["has_password_field"] is False and robot["title"] == "Stockholm news"
    assert victim["login_reached"] and victim["decoy_sent_to"] == [COLLECTOR] and victim["probes"] == ["webdriver"]


def test_evidence_index_lists_citable_signals(scan):
    index, _ = inv.evidence_index(scan)
    assert index["signals"]["S1"]["cite"] == ["victim/network.jsonl:2"]
    assert index["h4"]["status"] == "refuted" and index["verdict_if_concluded_now"] == "Scam"


# ---------- next step ----------

def test_next_step_dispatches_mobile_and_updates(scan, model):
    model["script"] += [{"text": "plan", "extra_hypothesis": None},
                        step("victim_mobile", "I send a phone because the trap may be phone-only",
                             updates=[{"id": "H1", "status": "supported", "reason": "The robot got a news page",
                                       "evidence": ["robot/robot.json"]}])]
    inv.plan("s1", f"http://{KIT}/", scan_dir=scan)
    out = inv.next_step("s1", summaries(scan), scan_dir=scan)
    assert out["tool"] == "victim_mobile" and out["args"] == {"reason": out["reason"]}
    assert next(h for h in out["hypotheses"] if h["id"] == "H1")["status"] == "supported"
    assert ("hypothesis_update", {"id": "H1", "status": "supported", "reason": "The robot got a news page",
                                  "evidence": ["robot/robot.json"]}) in model["events"]
    user = model["prompts"][-1][1]["content"]
    assert "<untrusted_page>" in user and "victim/network.jsonl:2" in user


@pytest.mark.parametrize("bad,why", [
    (step("robot_followup", host="evil.example.com"), "host must be"),
    (step("victim_retry"), "needs a goal"),
    (step("conclude", action=None), "action block or none"),
    (step("victim_mobile", updates=[{"id": "H1", "status": "supported", "reason": "x", "evidence": ["made/up.txt"]}]),
     "does not exist"),
])
def test_validator_rejects(scan, bad, why):
    check = inv._validator(scan, {"H1", "H2", "H3", "H4"}, {"robot/robot.json"}, inv.TOOLS)
    with pytest.raises(ValueError, match=why):
        check(bad)


def test_robot_followup_on_known_host(scan, model):
    model["script"].append(step("robot_followup", "I check what cdn-metrics serves", host=COLLECTOR))
    assert inv.next_step("s1", summaries(scan), scan_dir=scan)["args"]["host"] == COLLECTOR


def test_out_of_budget_only_conclude(scan, model):
    model["script"] += [step("victim_mobile"), step("victim_mobile")]  # model ignores the rule twice
    out = inv.next_step("s1", summaries(scan), budget={"sandboxes": 0, "seconds": 30}, scan_dir=scan)
    assert "must conclude now" in model["prompts"][0][1]["content"]
    assert out["tool"] == "conclude" and out["args"]["untested"] == ["Planner unavailable, rules only"]


def test_model_down_falls_back_to_rules(scan, model):
    model["script"].append(llm.LLMError("down"))
    out = inv.next_step("s1", summaries(scan), scan_dir=scan)
    assert out["tool"] == "conclude" and out["args"]["action"] == "block"
    signals = {c["signal"] for c in out["args"]["claims"]}
    assert {"S1", "S2", "S4", "M4"} <= signals
    assert any(t == "error" and "rules only" in p["message"] for t, p in model["events"])


# ---------- loop ----------

def test_investigate_dispatches_then_concludes(scan, model):
    claim = {"hypothesis": "H2", "signal": "S1", "text": "The password went to cdn-metrics",
             "cite": ["victim/network.jsonl:2"]}
    model["script"] += [step("victim_mobile", "I try a phone"),
                        step("conclude", "I have enough", claims=[claim], action="block")]
    dispatched = []

    def dispatch(s):
        dispatched.append(s)
        return {"visit": "victim_mobile-3", "kind": "victim", "login_reached": False}

    result = inv.investigate("s1", summaries(scan), dispatch, scan_dir=scan, max_sandboxes=5)
    assert [d["tool"] for d in dispatched] == ["victim_mobile"]
    assert result == {"claims": [claim], "action": "block", "untested": []}
    assert "victim_mobile-3" in model["prompts"][1][1]["content"]
    tools = [i["tool"] for i in inv._history(scan) if i["type"] == "tool"]
    assert tools == ["victim_mobile", "conclude"]


def test_investigate_respects_sandbox_budget(scan, model):
    model["script"] += [step("conclude", claims=[], action="none")]
    result = inv.investigate("s1", summaries(scan), lambda s: pytest.fail("no budget left"),
                             scan_dir=scan, max_sandboxes=2)
    assert result["action"] == "none"
    assert "Budget left: 0 sandboxes" in model["prompts"][0][1]["content"]


def test_investigate_respects_time_budget(scan, model):
    model["script"] += [step("conclude", claims=[], action="none")]
    clock = iter([0, 500])
    inv.investigate("s1", summaries(scan), lambda s: pytest.fail("no time left"), scan_dir=scan,
                    max_seconds=240, now=lambda: next(clock))
    assert "must conclude now" in model["prompts"][0][1]["content"]


def test_existing_visit_cite_is_accepted(scan):
    check = inv._validator(scan, {"H1", "H2", "H3", "H4"}, set(), inv.TOOLS)
    check(step("victim_mobile", updates=[{"id": "H3", "status": "supported", "reason": "phone-only notice",
                                          "evidence": ["victim/agent.jsonl:2"]}]))


def test_victim_summary_has_page_text_and_cite(scan):
    victim = summaries(scan)[1]
    assert victim["cite"] == "victim/agent.jsonl:2" and "page" in victim


def test_robot_followup_host_is_normalized(scan):
    check = inv._validator(scan, {"H1"}, set(), inv.TOOLS)
    s = step("robot_followup", host=f"http://{COLLECTOR}:80/v1/collect")
    check(s)
    assert s["host"] == COLLECTOR


def test_unchanged_status_is_not_re_emitted(scan, model):
    same = {"id": "H1", "status": "open", "reason": "nothing new", "evidence": []}
    model["script"].append(step("victim_mobile", updates=[same]))
    inv.next_step("s1", summaries(scan), scan_dir=scan)
    assert not any(t == "hypothesis_update" for t, _ in model["events"])


def test_signal_id_as_evidence_maps_to_its_cite(scan):
    check = inv._validator(scan, {"H1", "H4"}, {"robot/robot.json"}, inv.TOOLS, {"S2": ["robot/robot.json"]})
    s = step("victim_mobile", updates=[{"id": "H1", "status": "supported", "reason": "x", "evidence": ["S2"]}])
    check(s)
    assert s["updates"][0]["evidence"] == ["robot/robot.json"]


def test_h4_and_unknown_updates_are_dropped(scan):
    check = inv._validator(scan, {"H1", "H4"}, set(), inv.TOOLS)
    s = step("victim_mobile", updates=[{"id": "H4", "status": "refuted", "reason": "x", "evidence": []},
                                       {"id": "H9", "status": "open", "reason": "x", "evidence": []}])
    check(s)
    assert s["updates"] == []


def test_signal_text_in_claim_maps_back_to_id(scan):
    text = "I sent the decoy password and it went to cdn-metrics"
    check = inv._validator(scan, {"H2"}, set(), inv.TOOLS, {}, {text: "S1"})
    s = step("conclude", action="block", claims=[{"hypothesis": "H2", "signal": text, "text": "x",
                                                   "cite": ["victim/network.jsonl:2"]}])
    check(s)
    assert s["claims"][0]["signal"] == "S1"


def test_claim_signal_is_an_enum():
    assert inv.STEP_SCHEMA["properties"]["claims"]["items"]["properties"]["signal"]["enum"][0] == "S1"
