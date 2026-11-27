import json

import pytest
from fastapi.testclient import TestClient

from app.main import PRESETS, app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PD_FEATURE_FAKE_SCAN", "1")
    with TestClient(app) as client:
        app.state.delay = 0
        yield client


def read_events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_dashboard_and_disabled_scan(monkeypatch):
    monkeypatch.delenv("PD_FEATURE_FAKE_SCAN", raising=False)
    with TestClient(app) as client:
        assert "Browser comparison" in client.get("/").text
        assert client.get("/api/health").json()["demo"] is False
        assert client.post("/api/scans", json={"url": PRESETS["kit"]}).status_code == 503


@pytest.mark.parametrize(("preset", "expected"), [
    ("legit", "No evidence found"), ("kit", "Phishing"), ("mobile", "Phishing"), ("bomb", "Suspicious"),
])
def test_simulation_outcomes(client, preset, expected):
    response = client.post("/api/scans", json={"url": PRESETS[preset]})
    assert response.status_code == 202
    path = f"/api/scans/{response.json()['scan_id']}"
    events = read_events(client.get(f"{path}/events"))
    assert [event["id"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "scan_started"
    assert events[-1]["payload"]["verdict"] == expected
    assert client.get(path).json()["status"] == "finished"
    if preset == "mobile":
        assert any(event["payload"].get("visit") == "victim_mobile-3" for event in events)
    if preset == "bomb":
        assert any(event["type"] == "resource_limit_hit" for event in events)
    if preset == "kit":
        verdict = events[-1]["payload"]
        assert "S1" in {reason["signal"] for reason in verdict["reasons"]}
        assert verdict["password_sent_to"] == ["cdn-metrics.example"]
        approval = next(event["payload"] for event in events if event["type"] == "approval")
        assert approval["decision"] == "timed_out"
        types = [event["type"] for event in events]
        request = next(event["payload"] for event in events if event["type"] == "approval_requested")
        assert types.index("approval_requested") < types.index("approval")
        assert request["visit"] == approval["visit"]
        assert request["host"] == "vexalo-docs.example"
        assert request["fields"] == ["email", "password"]
        assert request["timeout_s"] > 0
        assert approval["typed"] == ["{{DECOY_EMAIL}}", "{{DECOY_PASSWORD}}"]
        assert all(
            {"visit", "model"} <= event["payload"].keys()
            for event in events if event["type"] == "agent_step"
        )
        assert sum(event["type"] == "request_blocked" for event in events) == 3


def test_reconnect_evidence_and_override(client):
    scan = client.post("/api/scans", json={"url": PRESETS["kit"]}).json()
    path = f"/api/scans/{scan['scan_id']}"
    events = read_events(client.get(f"{path}/events"))
    replay = read_events(client.get(f"{path}/events", headers={"Last-Event-ID": "2"}))
    assert replay == events[2:]
    assert client.get(f"{path}/files/robot/final.png").headers["content-type"] == "image/png"
    assert "cdn-metrics.example" in client.get(f"{path}/files/victim/network.txt").text
    assert client.get(f"{path}/files/robot/login.png").status_code == 404
    h4 = next(event["payload"] for event in events
              if event["type"] == "hypothesis_update" and event["payload"]["id"] == "H4")
    assert h4["status"] == "refuted"
    assert client.get(f"{path}/files/checks/destinations.jsonl").json()["brand_owned"] is False
    assert client.get(path).json()["decided_by"] == "agent"
    decision = client.post(f"{path}/decision", json={"decision": "release"}).json()
    assert decision == {"decision": "release", "decided_by": "analyst"}
    override = read_events(client.get(f"{path}/events", params={"after": events[-1]["id"]}))
    assert [event["payload"] for event in override] == [decision]


def test_invalid_scan_and_unknown_id(client):
    assert client.post("/api/scans", json={"url": "file:///tmp/example"}).status_code == 422
    assert client.get("/api/scans/missing/events").status_code == 404


def test_email_preview_extracts_without_starting_a_scan(client):
    response = client.post("/api/email-preview", json={
        "email_text": '<a href="https://destination.example/account">sender.example</a>',
    })
    assert response.status_code == 200
    preview = response.json()
    assert preview["links"] == [{
        "url": "https://destination.example/account", "shown_text": "sender.example", "blocklist": None,
    }]
    assert [flag["name"] for flag in preview["flags"]] == ["link_text_mismatch"]
    assert client.app.state.scans == {}


def test_legitimate_submission_is_not_a_third_party_destination(client):
    scan = client.post("/api/scans", json={"url": PRESETS["legit"]}).json()
    events = read_events(client.get(f"/api/scans/{scan['scan_id']}/events"))
    assert any(event["type"] == "decoy_sent" for event in events)
    assert events[-1]["payload"]["password_sent_to"] == []


def test_stored_scan_stream_and_public_record(client):
    from app import db

    db.update_scan("scan-db", url="https://test.example/", status="finished",
                   client_ip="127.0.0.1", decoy_password="do-not-publish")
    db.emit("scan-db", "plan", {"text": "First event"})
    db.emit("scan-db", "verdict", {"verdict": "Phishing"})
    path = "/api/scans/scan-db"
    assert client.get(path).json() == {
        "id": "scan-db", "url": "https://test.example/", "status": "finished",
    }
    events = read_events(client.get(f"{path}/events"))
    assert [event["type"] for event in events] == ["plan", "verdict"]
    replay = client.get(f"{path}/events", headers={"Last-Event-ID": str(events[0]["id"])})
    assert read_events(replay) == events[1:]


@pytest.mark.parametrize(("scan_id", "verdict"), [
    ("dev-kit-161e89", "Phishing"), ("dev-mobile-80d800", "Phishing"),
    ("dev-inject-e9ec6b", "Phishing"), ("dev-legit-f1af13", "No evidence found"),
])
def test_recorded_runs_and_evidence(client, monkeypatch, scan_id, verdict):
    monkeypatch.setenv("PD_SCANS_DIR", "fixtures/recordings")
    path = f"/api/scans/{scan_id}"
    assert client.get(f"/replay/{scan_id}").status_code == 200
    assert client.get(path).json()["verdict"] == verdict
    events = read_events(client.get(f"{path}/events"))
    assert events[0]["type"] == "scan_started"
    assert events[-1]["payload"]["verdict"] == verdict
    evidence = client.get(f"{path}/files/robot/final.png")
    assert evidence.content.startswith(b"\x89PNG")
    assert client.get(f"{path}/files/decoy.json").status_code == 404
    assert client.get(f"{path}/files/robot/%2e%2e/decoy.json").status_code == 404


def test_saved_scoreboard(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PD_SCANS_DIR", str(tmp_path))
    assert client.get("/api/scoreboard").json() is None
    (tmp_path / "scoreboard.json").write_text('{"robot":{"bot":true},"victim":{"bot":false}}')
    assert client.get("/api/scoreboard").json() == {
        "robot": {"bot": True}, "victim": {"bot": False},
    }


def test_persisted_stream_receives_live_event_and_unsubscribes(monkeypatch):
    import asyncio
    from threading import Event

    from app import db
    from app.main import stream_persisted

    subscribed = Event()
    real_subscribe = db.subscribe
    real_unsubscribe = db.unsubscribe
    listeners = set()

    def subscribe(listener):
        real_subscribe(listener)
        listeners.add(listener)
        subscribed.set()

    def unsubscribe(listener):
        real_unsubscribe(listener)
        listeners.remove(listener)

    monkeypatch.setattr(db, "subscribe", subscribe)
    monkeypatch.setattr(db, "unsubscribe", unsubscribe)
    db.update_scan("live-db", status="running")

    async def verify():
        stream = stream_persisted("live-db", 0)
        try:
            next_event = asyncio.create_task(anext(stream))
            assert await asyncio.to_thread(subscribed.wait, 2)
            await asyncio.to_thread(db.emit, "live-db", "plan", {"text": "Live event"})
            assert "Live event" in await asyncio.wait_for(next_event, timeout=2)
        finally:
            await stream.aclose()

    asyncio.run(verify())
    assert not listeners


@pytest.fixture
def live(monkeypatch):
    from app import orchestrator
    started = []
    monkeypatch.setenv("PD_FEATURE_ORCHESTRATOR", "1")
    monkeypatch.setenv("PD_PUBLIC_IP_DASHED", "203-0-113-5")
    monkeypatch.setenv("PD_ACTIVE_SCAN_HOSTS", "")
    monkeypatch.setattr(orchestrator, "run_scan", lambda *a: started.append(("scan", a)))
    monkeypatch.setattr(orchestrator, "run_capture", lambda *a: started.append(("capture", a)))
    return started


def _wait(started, n=1):
    import time
    for _ in range(50):
        if len(started) >= n:
            return
        time.sleep(0.02)


def test_live_presets_are_real_fixture_urls(client, live):
    presets = client.get("/api/health").json()["live_presets"]
    assert presets["kit"] == "http://vexalo-docs.203-0-113-5.nip.io/"
    assert presets["inject"].endswith("/x/") and presets["legit"] == "http://vexalo.203-0-113-5.sslip.io/"


def test_fixture_host_runs_full_investigation(client, live):
    response = client.post("/api/scans", json={"url": "http://vexalo-docs.203-0-113-5.nip.io/m/"})
    assert response.status_code == 202 and response.json()["capture_only"] is False
    _wait(live)
    assert live[0][0] == "scan"


def test_other_link_gets_sandboxed_capture_not_host_browser(client, live):
    response = client.post("/api/scans", json={"url": "https://public.example/story"})
    assert response.json()["capture_only"] is True
    _wait(live)
    assert live[0] == ("capture", (response.json()["scan_id"], "https://public.example/story"))


def test_wildcard_allows_full_investigation_of_any_link(client, live, monkeypatch):
    monkeypatch.setenv("PD_ACTIVE_SCAN_HOSTS", "*")
    assert client.post("/api/scans", json={"url": "https://public.example/"}).json()["capture_only"] is False


def test_live_scans_off_by_default(client, monkeypatch):
    monkeypatch.delenv("PD_FEATURE_ORCHESTRATOR", raising=False)
    assert client.post("/api/scans", json={"url": "https://public.example/"}).status_code == 503


def test_no_browser_runs_in_the_app_process():
    import pathlib as pl
    source = (pl.Path(__file__).resolve().parent.parent / "app" / "main.py").read_text()
    assert "sync_playwright" not in source and "chromium" not in source.lower()


def test_rate_limit_per_ip_behind_proxy(client, live, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_recent", {})
    monkeypatch.setenv("PD_RATE_LIMIT_PER_IP", "2")
    # the test client is not the proxy; stand in for Caddy's forwarded address (client_ip has its own test)
    monkeypatch.setattr(main, "client_ip", lambda request: request.headers["x-forwarded-for"])
    url = {"url": "http://vexalo-docs.203-0-113-5.nip.io/"}
    a = {"X-Forwarded-For": "198.51.100.7"}
    assert [client.post("/api/scans", json=url, headers=a).status_code for _ in range(3)] == [202, 202, 429]
    # another visitor behind the same proxy is not affected
    assert client.post("/api/scans", json=url, headers={"X-Forwarded-For": "198.51.100.8"}).status_code == 202


def test_client_ip_ignores_forwarded_header_from_non_proxy():
    from types import SimpleNamespace
    from app import main
    req = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"), headers={"x-forwarded-for": "1.2.3.4"})
    assert main.client_ip(req) == "203.0.113.9"
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"x-forwarded-for": "1.2.3.4, 198.51.100.7"})
    assert main.client_ip(req) == "198.51.100.7"


def test_analyst_can_override_a_real_scan(client, monkeypatch):
    from app import db
    events = []
    store = {"real1": {"verdict": "Phishing", "decision": "block", "decided_by": "agent"}, "cap1": {"capture_only": True}}
    monkeypatch.setattr(db, "get_scan", lambda sid: store.get(sid))
    monkeypatch.setattr(db, "update_scan", lambda sid, **f: store[sid].update(f))
    monkeypatch.setattr(db, "emit", lambda sid, t, p: events.append((t, p)))
    r = client.post("/api/scans/real1/decision", json={"decision": "release"})
    assert r.status_code == 200 and store["real1"]["decision"] == "release" and store["real1"]["decided_by"] == "analyst"
    assert events == [("decision", {"decision": "release", "decided_by": "analyst"})]
    assert client.post("/api/scans/cap1/decision", json={"decision": "block"}).status_code == 404


def test_analyst_approves_a_waiting_submit(client, monkeypatch):
    from app import agent, db
    store = {"real1": {"verdict": None}, "cap1": {"capture_only": True}}
    monkeypatch.setattr(db, "get_scan", lambda sid: store.get(sid))
    answers = []
    monkeypatch.setattr(agent, "answer", lambda sid, visit, d: answers.append((sid, visit, d)) or visit == "victim")
    r = client.post("/api/scans/real1/approve", json={"visit": "victim", "decision": "approve"})
    assert r.status_code == 200 and r.json() == {"visit": "victim", "decision": "approve"}
    assert answers == [("real1", "victim", "approve")]
    assert client.post("/api/scans/real1/approve", json={"visit": "robot", "decision": "deny"}).status_code == 409
    assert client.post("/api/scans/nope/approve", json={"visit": "victim", "decision": "deny"}).status_code == 404
    assert client.post("/api/scans/cap1/approve", json={"visit": "victim", "decision": "deny"}).status_code == 404
    assert client.post("/api/scans/real1/approve", json={"visit": "victim", "decision": "maybe"}).status_code == 422


def test_approve_endpoint_reaches_the_waiting_agent(client, monkeypatch):
    """End to end in one process: the endpoint wakes the agent thread that is waiting."""
    import threading
    from app import agent, db
    monkeypatch.setattr(db, "get_scan", lambda sid: {"verdict": None})
    monkeypatch.setattr(agent, "_emit", lambda *a: None)
    result = {}
    t = threading.Thread(target=lambda: result.update(d=agent.ask_analyst("live1", "victim", 5, "http://x.test/login",
                                                                          [agent.EMAIL, agent.PASSWORD])))
    t.start()
    for _ in range(200):
        if agent.pending("live1"):
            break
        threading.Event().wait(0.01)
    assert client.post("/api/scans/live1/approve", json={"visit": "victim", "decision": "deny"}).status_code == 200
    t.join(2)
    assert result["d"] == "denied_by_analyst" and agent.pending("live1") == []


def test_rescan_of_a_blocked_link_announces_it_and_still_runs(client, monkeypatch):
    from app import blocklist, db, main, orchestrator
    monkeypatch.setenv("PD_FEATURE_ORCHESTRATOR", "1")
    monkeypatch.setattr(main, "orchestrator_enabled", lambda url: True)
    monkeypatch.setattr(main, "over_rate_limit", lambda ip: False)
    monkeypatch.setattr(db, "update_scan", lambda sid, **f: None)
    events, runs = [], []
    monkeypatch.setattr(db, "emit", lambda sid, t, p: events.append((t, p)))
    monkeypatch.setattr(orchestrator, "run_scan", lambda *a: runs.append(a))
    hit = {"url": "http://kit.test/", "status": "blocked", "scan_id": "old", "verdict": "Phishing",
           "decided_by": "agent", "decided_at": "2026-11-27T15:40:00+00:00"}
    monkeypatch.setattr(blocklist, "lookup", lambda url, exclude=None: hit)
    r = client.post("/api/scans", json={"url": "http://kit.test/"})
    assert r.status_code == 202 and events == [("blocklist_hit", hit)]
    import time
    for _ in range(50):
        if runs:
            break
        time.sleep(0.01)
    assert runs  # a blocked link is still investigated fresh


def test_blocklist_endpoint_and_email_flags(client, monkeypatch):
    from app import blocklist
    hit = {"url": "http://kit.test/", "status": "blocked", "scan_id": "old", "verdict": "Phishing",
           "decided_by": "agent", "decided_at": "t"}
    monkeypatch.setattr(blocklist, "entries", lambda: [hit])
    monkeypatch.setattr(blocklist, "lookup", lambda url, exclude=None: hit if "kit.test" in url else None)
    assert client.get("/api/blocklist").json() == {"entries": [hit]}
    r = client.post("/api/email-preview", json={"email_text": "See http://kit.test/ and http://ok.test/"})
    assert [link["blocklist"] for link in r.json()["links"]] == [hit, None]
