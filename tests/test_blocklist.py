from app import blocklist, db


def store(monkeypatch, rows):
    monkeypatch.setattr(db, "all_scans", lambda: rows)


def test_normalize_treats_the_same_link_the_same():
    assert blocklist.normalize("HTTP://Vexalo-Docs.Example/login/#x") == "http://vexalo-docs.example/login"
    assert blocklist.normalize("http://a.test") == blocklist.normalize("http://a.test/")
    assert blocklist.normalize("http://a.test/p?t=1") != blocklist.normalize("http://a.test/p?t=2")


def test_latest_decision_wins(monkeypatch):
    store(monkeypatch, [
        {"id": "s1", "url": "http://kit.test/", "verdict": "Phishing", "decision": "block", "decided_by": "agent",
         "decided_at": "2026-11-27T15:40:00+00:00"},
        {"id": "s2", "url": "http://kit.test", "verdict": "Phishing", "decision": "release", "decided_by": "analyst",
         "decided_at": "2026-11-27T15:50:00+00:00"},
        {"id": "s3", "url": "http://legit.test/", "verdict": "No evidence found"},
    ])
    hit = blocklist.lookup("http://KIT.test/")
    assert hit["status"] == "released" and hit["decided_by"] == "analyst" and hit["scan_id"] == "s2"
    assert blocklist.lookup("http://legit.test/") is None
    assert [e["scan_id"] for e in blocklist.entries()] == ["s2"]


def test_lookup_skips_the_scan_itself(monkeypatch):
    store(monkeypatch, [{"id": "s1", "url": "http://kit.test/", "decision": "block", "decided_at": "t"}])
    assert blocklist.lookup("http://kit.test/", exclude="s1") is None
    assert blocklist.lookup("http://kit.test/")["status"] == "blocked"


def test_all_scans_reads_the_real_table(monkeypatch, tmp_path):
    monkeypatch.setenv("PD_DB", str(tmp_path / "pd.db"))
    db.update_scan("a1", url="http://kit.test/", decision="block", decided_at="t")
    assert db.all_scans() == [{"id": "a1", "url": "http://kit.test/", "decision": "block", "decided_at": "t"}]
