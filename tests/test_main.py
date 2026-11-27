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
        assert approval["decision"] == "auto_approved"
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
        "url": "https://destination.example/account", "shown_text": "sender.example",
    }]
    assert [flag["name"] for flag in preview["flags"]] == ["link_text_mismatch"]
    assert client.app.state.scans == {}


def test_legitimate_submission_is_not_a_third_party_destination(client):
    scan = client.post("/api/scans", json={"url": PRESETS["legit"]}).json()
    events = read_events(client.get(f"/api/scans/{scan['scan_id']}/events"))
    assert any(event["type"] == "decoy_sent" for event in events)
    assert events[-1]["payload"]["password_sent_to"] == []
