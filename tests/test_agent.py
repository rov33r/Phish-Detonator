"""app/agent.py with a fake browser (kit state machine) and a scripted model. No Docker, no network."""
import json

import pytest

from app import agent, llm

DECOY = {"email": "nora.berg.4c1d2e@fjord-mail.com", "password": "Kq8!vT2mZr5pLx9w"}
KIT = "http://vexalo-docs.203-0-113-5.nip.io"
PAGES = {
    "/": ('- heading "Anna shared a file" [level=1, ref=e1]\n- link "Review document" [ref=e2]', False),
    "/gate": ('- checkbox "I am not a robot" [ref=e1]\n- button "Continue" [ref=e2]', False),
    "/login": ('- textbox "Email" [ref=e1]\n- textbox "Password" [ref=e2]\n- button "Sign in" [ref=e3]', True),
    "/done": ('- heading "Wrong password" [ref=e1]', False),
}
NEXT = {("/", "@e2"): "/gate", ("/gate", "@e2"): "/login", ("/login", "@e3"): "/done"}


class FakeBrowser:
    def __init__(self):
        self.path, self.calls = "/", []

    def __call__(self, container, args, timeout=30):
        assert args[:4] == ["agent-browser", "--cdp", "9222", "--pin-tab"]
        cmd = args[4:]
        self.calls.append(cmd)
        if cmd[0] == "snapshot":
            return 0, PAGES[self.path][0]
        if cmd[:2] == ["get", "url"]:
            return 0, KIT + self.path
        if cmd[:2] == ["get", "title"]:
            return 0, "Vexalo"
        if cmd[0] == "eval":
            return 0, "true" if PAGES[self.path][1] else "false"
        if cmd[0] == "click":
            self.path = NEXT.get((self.path, cmd[1]), self.path)
        if cmd[0] == "press" and self.path == "/login":
            self.path = "/done"
        return 0, ""


def act(action, ref=None, text=None, key=None, reason="I do the next step", login=False):
    return {"action": action, "ref": ref, "text": text, "key": key, "reason": reason,
            "brand_seen": "Vexalo" if login else None, "is_login_page": login}


KIT_SCRIPT = [
    act("click", "@e2", reason="I open the shared document"),
    act("click", "@e1", reason="I tick the not a robot checkbox"),
    act("click", "@e2", reason="I continue to the document"),
    act("fill", "@e1", agent.EMAIL, login=True),
    act("fill", "@e2", agent.PASSWORD, login=True),
    act("click", "@e3", reason="I submit the login form", login=True),
    act("done", reason="I submitted the form once"),
]


@pytest.fixture
def rig(monkeypatch, tmp_path):
    browser, events, prompts = FakeBrowser(), [], []
    script = []

    def fake_chat(messages, schema, *, name, validate=None, **kw):
        prompts.append(messages)
        data = dict(script.pop(0))
        if validate:
            validate(data)
        return llm.Reply(data, "main-model")

    monkeypatch.setattr(agent, "_exec", browser)
    monkeypatch.setattr(agent, "_emit", lambda s, t, p: events.append((t, p)))
    monkeypatch.setattr(agent, "_out_dir", lambda s, v: tmp_path / v)
    monkeypatch.setattr(agent, "_sleep", lambda s: None)
    monkeypatch.setattr(agent.llm, "chat_json", fake_chat)
    return {"browser": browser, "events": events, "prompts": prompts, "script": script, "out": tmp_path}


def run(rig, script, **kw):
    rig["script"][:] = script
    return agent.run_victim("s1", KIT + "/", "pd-s1-victim", DECOY, **kw)


def test_walks_the_kit(rig):
    summary = run(rig, KIT_SCRIPT)
    assert summary["stop_reason"] == "done" and summary["login_reached"]
    assert summary["visit"] == "victim"
    types = [c for c in rig["browser"].calls if c[0] == "type"]
    assert types == [["type", "@e1", DECOY["email"]], ["type", "@e2", DECOY["password"]]]
    clicks = [c for c in rig["browser"].calls if c[0] in ("hover", "click")]
    assert clicks[:2] == [["hover", "@e2"], ["click", "@e2"]]  # hover before every click


def test_real_decoy_never_reaches_model_events_or_log(rig):
    run(rig, KIT_SCRIPT)
    assert DECOY["password"] not in json.dumps(rig["prompts"])
    assert DECOY["password"] not in json.dumps(rig["events"])
    assert DECOY["password"] not in (rig["out"] / "victim" / "agent.jsonl").read_text()


def test_snapshot_is_wrapped_as_untrusted(rig):
    run(rig, KIT_SCRIPT)
    assert "<untrusted_page>" in rig["prompts"][0][1]["content"]


def test_approval_gate_before_submit(rig):
    run(rig, KIT_SCRIPT)
    types = [t for t, _ in rig["events"]]
    gate = next(p for t, p in rig["events"] if t == "approval")
    assert gate["decision"] == "auto_approved" and gate["typed"] == [agent.EMAIL, agent.PASSWORD]
    assert all(c["ok"] for c in gate["checks"])
    assert types.index("approval") < len(types) - types[::-1].index("agent_step") - 1


def test_agent_log_has_password_field_from_code(rig):
    run(rig, KIT_SCRIPT)
    lines = [json.loads(x) for x in (rig["out"] / "victim" / "agent.jsonl").read_text().splitlines()]
    assert [x["password_field"] for x in lines[:4]] == [False, False, False, True]
    assert lines[0]["model"] == "main-model" and lines[0]["visit"] == "victim"


def test_second_password_submit_is_denied():
    decision, checks = agent.approval([agent.PASSWORD], KIT + "/login", password_submitted=True)
    assert decision == "denied"
    assert not next(c for c in checks if c["name"].startswith("first submit"))["ok"]


def test_submit_to_private_address_is_denied():
    assert agent.approval([agent.EMAIL], "http://10.0.0.5/login", False)[0] == "denied"


def test_validator_rejects_bad_actions():
    check = agent.validator({"@e1", "@e2"})
    for bad in (act("click", "@e9"), act("fill", "@e1", "hunter2"), act("press", key="Delete"), act("fly")):
        with pytest.raises(ValueError):
            check(bad)
    ok = act("click", "e1")
    check(ok)
    assert ok["ref"] == "@e1"


def test_reason_is_capped_at_20_words():
    a = act("done", reason=" ".join(["word"] * 40))
    agent.validator(set())(a)
    assert len(a["reason"].split()) == 20


def test_model_failure_gives_up_with_error(rig, monkeypatch):
    def down(*a, **k):
        raise llm.LLMError("all models down")
    monkeypatch.setattr(agent.llm, "chat_json", down)
    summary = agent.run_victim("s1", KIT + "/", "pd-s1-victim", DECOY)
    assert summary["stop_reason"] == "give_up"
    assert any(t == "error" for t, _ in rig["events"])


def test_time_limit(rig, monkeypatch):
    clock = iter([0, 0, 200, 200])
    monkeypatch.setattr(agent, "_now", lambda: next(clock))
    assert run(rig, KIT_SCRIPT)["stop_reason"] == "time_limit"


def test_step_limit(rig):
    summary = run(rig, [act("wait")] * 3, max_steps=3)
    assert summary["stop_reason"] == "step_limit" and summary["steps"] == 3


def test_extra_goal_in_prompt(rig):
    run(rig, KIT_SCRIPT, goal="enter the decoy code 000000 on a one-time code screen")
    assert "Extra goal: enter the decoy code 000000" in rig["prompts"][0][0]["content"]


def test_decoy_sent_from_network_log(rig):
    out = rig["out"] / "victim"
    out.mkdir()
    (out / "network.jsonl").write_text(json.dumps({
        "ts": 1, "method": "POST", "url": "http://cdn-metrics.203-0-113-5.sslip.io/v1/collect",
        "host": "cdn-metrics.203-0-113-5.sslip.io", "postData": json.dumps(DECOY)}) + "\n")
    summary = run(rig, KIT_SCRIPT)
    assert summary["decoy_sent_to"] == ["cdn-metrics.203-0-113-5.sslip.io"]
    sent = [p for t, p in rig["events"] if t == "decoy_sent"]
    assert {s["field"] for s in sent} == {"email", "password"}


def test_browser_error_ends_visit(rig, monkeypatch):
    monkeypatch.setattr(agent, "_exec", lambda c, a, t=30: (1, "cannot attach to CDP"))
    summary = agent.run_victim("s1", KIT + "/", "pd-s1-victim", DECOY)
    assert summary["stop_reason"] == "browser_error"


def test_make_decoy_is_unique_and_well_formed():
    import re
    a, b = agent.make_decoy(), agent.make_decoy()
    assert a != b
    assert re.fullmatch(r"[a-z]+\.[a-z]+\.[0-9a-f]{6}@[a-z]+-mail\.com", a["email"])
    pw = a["password"]
    assert len(pw) == 16 and sum(c in "!#%*" for c in pw) == 1


def test_failed_screenshot_does_not_end_visit(rig, monkeypatch):
    real = rig["browser"]

    def flaky(container, args, timeout=30):
        if args[4] == "screenshot" and args[5].endswith("step-06.png"):
            return 1, "Not attached to an active page"
        return real(container, args, timeout)
    monkeypatch.setattr(agent, "_exec", flaky)
    summary = run(rig, KIT_SCRIPT)
    assert summary["stop_reason"] == "done" and summary["steps"] == 7


def test_click_with_text_on_textbox_becomes_fill():
    roles = agent.roles_in('- textbox "Email" [ref=e9]\n- checkbox "I am not a robot" [ref=e4]\n- button "Go" [ref=e7]')
    assert roles == {"@e9": "textbox", "@e4": "checkbox", "@e7": "button"}
    check = agent.validator(roles)
    a = act("click", "@e9", agent.EMAIL)
    check(a)
    assert a["action"] == "fill" and a["text"] == agent.EMAIL
    b = act("click", "@e4", agent.EMAIL)  # never type into a checkbox
    check(b)
    assert b["action"] == "click" and b["text"] is None
    with pytest.raises(ValueError, match="not a text field"):
        check(act("fill", "@e7", agent.PASSWORD))


def test_resnapshot_when_form_not_rendered(rig, monkeypatch):
    real, seen = rig["browser"], {"n": 0}

    def slow(container, args, timeout=30):
        if args[4] == "snapshot" and real.path == "/login" and seen["n"] == 0:
            seen["n"] += 1
            return 0, '- heading "Sign in" [ref=e1]'
        return real(container, args, timeout)
    monkeypatch.setattr(agent, "_exec", slow)
    run(rig, KIT_SCRIPT)
    assert seen["n"] == 1 and any(c[0] == "type" for c in rig["browser"].calls)


def test_hanging_submit_does_not_end_visit(rig, monkeypatch):
    real = rig["browser"]

    def hang(container, args, timeout=30):
        if args[4] == "click" and args[5] == "@e3":
            real(container, args, timeout)  # the form is submitted and the page moves on
            raise TimeoutError("agent-browser click timed out")
        return real(container, args, timeout)
    monkeypatch.setattr(agent, "_exec", hang)
    assert run(rig, KIT_SCRIPT)["stop_reason"] == "done"


def test_runner_exception_becomes_browser_error(rig, monkeypatch):
    def boom(container, args, timeout=30):
        raise OSError("docker went away")
    monkeypatch.setattr(agent, "_exec", boom)
    assert agent.run_victim("s1", KIT + "/", "pd-s1-victim", DECOY)["stop_reason"] == "browser_error"


def test_containment_events_emitted_live_once(rig):
    out = rig["out"] / "victim"
    out.mkdir()
    (out / "blocked.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"ts": 1, "url": "http://169.254.169.254/latest/meta-data/", "host": "169.254.169.254",
         "error": "net::ERR_CONNECTION_REFUSED"},
        {"ts": 2, "url": "http://172.30.0.1:8000/api/health", "host": "172.30.0.1", "error": "net::ERR_CONNECTION_REFUSED"}]))
    (out / "probes.jsonl").write_text(json.dumps({"ts": 1, "name": "navigator.webdriver"}) + "\n")
    run(rig, KIT_SCRIPT)
    blocked = [p for t, p in rig["events"] if t == "request_blocked"]
    assert [b["host"] for b in blocked] == ["169.254.169.254", "172.30.0.1"]  # each line once, not per step
    assert blocked[0]["visit"] == "victim" and "REFUSED" in blocked[0]["error"]
    assert [p for t, p in rig["events"] if t == "probe_seen"] == [{"visit": "victim", "name": "navigator.webdriver"}]
