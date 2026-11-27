from app import db


def test_emit_stores_and_notifies(tmp_path, monkeypatch):
    monkeypatch.setenv("PD_DB", str(tmp_path / "pd.db"))
    seen = []
    db.subscribe(seen.append)
    try:
        db.emit("s1", "plan", {"text": "a"})
        db.emit("s2", "plan", {"text": "other scan"})
        db.emit("s1", "verdict", {"verdict": "Phishing"})
    finally:
        db.unsubscribe(seen.append)
    rows = db.events("s1")
    assert [e["type"] for e in rows] == ["plan", "verdict"]
    assert rows[1]["payload"] == {"verdict": "Phishing"}
    assert [e["type"] for e in db.events("s1", after=rows[0]["id"])] == ["verdict"]
    assert [e["scan_id"] for e in seen] == ["s1", "s2", "s1"]


def test_broken_listener_does_not_stop_emit(tmp_path, monkeypatch):
    monkeypatch.setenv("PD_DB", str(tmp_path / "pd.db"))

    def boom(event):
        raise RuntimeError("ui down")

    db.subscribe(boom)
    try:
        db.emit("s1", "plan", {})
    finally:
        db.unsubscribe(boom)
    assert len(db.events("s1")) == 1


def test_update_scan_merges(tmp_path, monkeypatch):
    monkeypatch.setenv("PD_DB", str(tmp_path / "pd.db"))
    assert db.get_scan("s1") is None
    db.update_scan("s1", url="http://x/", status="running")
    db.update_scan("s1", status="finished", verdict="Phishing")
    assert db.get_scan("s1") == {"url": "http://x/", "status": "finished", "verdict": "Phishing"}
