"""app/verdict.py: signals, verdict rules, H4 and claim checks (SPEC 8.2 to 8.5, A5, A6, A13, A21)."""
import base64
import json
from urllib.parse import quote_plus

import pytest

from app import verdict as vd

IP = "203-0-113-5"
KIT = f"vexalo-docs.{IP}.nip.io"
LEGIT = f"vexalo.{IP}.sslip.io"
COLLECTOR = f"cdn-metrics.{IP}.sslip.io"
DECOY = {"email": "nora.berg.4c1d2e@fjord-mail.com", "password": "Kq8!vT2mZr5pLx9w"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PD_PUBLIC_IP_DASHED", IP)
    events, updates = [], []
    monkeypatch.setattr(vd, "_emit", lambda scan_id, type, payload: events.append((type, payload)))
    monkeypatch.setattr(vd, "_update", lambda scan_id, **f: updates.append(f))
    return events, updates


def write_scan(root, robot=None, agent=(), network=(), navigations=(), probes=(), blocked=(), extra=None):
    root.mkdir(exist_ok=True)
    (root / "decoy.json").write_text(json.dumps(DECOY))
    if robot is not None:
        (root / "robot").mkdir()
        (root / "robot" / "robot.json").write_text(json.dumps(robot))
    v = root / "victim"
    v.mkdir()
    for name, rows in (("agent", agent), ("network", network), ("navigations", navigations),
                       ("probes", probes), ("blocked", blocked)):
        (v / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for path, content in (extra or {}).items():
        (root / path).write_text(content)
    return root


def step(n, url, reason, login=False, brand=None):
    return {"step": n, "action": "click", "url": url, "reason": reason, "title": "",
            "password_field": login, "brand_seen": brand}


def run(tmp_path, **kw):
    return vd.decide("scan1", scan_dir=write_scan(tmp_path / "scan1", **kw), run_brand_check=False)


def kit_scan(post_host=COLLECTOR, brand="Vexalo", robot_page=None, after=f"http://{LEGIT}/login"):
    body = json.dumps(DECOY)
    return dict(
        robot=robot_page or {"final_url": f"http://{KIT}/news", "title": "Stockholm news",
                             "text": "Stockholm today. Nothing to see here.", "status": 200,
                             "has_password_field": False},
        agent=[step(1, f"http://{KIT}/", "I click Review document to open the shared file"),
               step(2, f"http://{KIT}/gate", "I tick the not a robot checkbox and continue"),
               step(3, f"http://{KIT}/login", "Login form, I fill the decoy email", True, brand),
               step(4, f"http://{KIT}/login", "I submit the form", True, brand)],
        network=[{"ts": 1, "method": "GET", "url": f"http://{KIT}/", "host": KIT},
                 {"ts": 10, "method": "POST", "url": f"http://{post_host}/v1/collect", "host": post_host,
                  "postData": body}],
        navigations=[{"ts": 1, "url": f"http://{KIT}/"}, {"ts": 3, "url": f"http://{KIT}/login"},
                     {"ts": 11, "url": after}],
        probes=[{"ts": 2, "name": "webdriver"}],
        blocked=[{"ts": 4, "url": "http://169.254.169.254/latest/meta-data/", "host": "169.254.169.254",
                  "error": "net::ERR_CONNECTION_REFUSED"}],
    )


# ---------- helpers ----------

def test_site():
    assert vd.site("login.acme.com") == "acme.com"
    assert vd.site("www.bbc.co.uk") == "bbc.co.uk"
    assert vd.site(COLLECTOR) == COLLECTOR  # wildcard DNS: every name is its own site
    assert vd.site("10.0.0.1") == "10.0.0.1"


def test_brands_json_has_vexalo_and_providers():
    b = vd.load_brands()
    assert b["brands"]["Vexalo"] == [LEGIT]
    assert vd.is_provider("acme.okta.com", b) and vd.is_provider("accounts.google.com", b)
    assert not vd.is_provider("docs.google.com", b) and not vd.is_provider("forms.office.com", b)


@pytest.mark.parametrize("wrap", [
    lambda p: p,
    lambda p: quote_plus(p),
    lambda p: base64.b64encode(json.dumps({"u": "x", "p": p}).encode()).decode(),
    lambda p: base64.urlsafe_b64encode(("ab" + p).encode()).decode(),
])
def test_decoy_found_in_any_encoding(wrap):
    assert vd.find_decoy("payload=" + wrap(DECOY["password"]), DECOY["password"])


def test_decoy_not_found():
    assert vd.find_decoy("nothing here", DECOY["password"]) is None


# ---------- A6: the kit ----------

def test_kit_is_scam_with_strong_combination(tmp_path, env):
    r = run(tmp_path, **kit_scan())
    signals = {x["signal"] for x in r["reasons"]}
    assert r["verdict"] == "Scam"
    assert {"S1", "S2", "S4", "M4", "M1", "M3", "M5", "S3"} <= signals
    assert r["password_sent_to"] == [COLLECTOR]
    assert r["action_taken"] == "blocked" and r["h4"]["status"] == "refuted"
    events, updates = env
    h4 = next(p for t, p in events if t == "hypothesis_update")
    assert h4["id"] == "H4" and h4["status"] == "refuted" and "Refuted" in h4["reason"]
    assert h4["evidence"] == ["checks/destinations.jsonl:1"]
    assert updates[-1] == {"verdict": "Scam", "decision": "block", "decided_by": "agent"}
    assert next(p for t, p in events if t == "verdict")["decided_by"] == "agent"


def test_kit_writes_evidence_files(tmp_path):
    run(tmp_path, **kit_scan())
    dest = json.loads((tmp_path / "scan1" / "checks" / "destinations.jsonl").read_text())
    assert dest["host"] == COLLECTOR and dest["third_party"] and not dest["login_provider"]
    saved = json.loads((tmp_path / "scan1" / "verdict.json").read_text())
    assert saved["decoy"]["password_masked"].startswith("Kq") and DECOY["password"] not in json.dumps(saved)


def test_investigator_can_decline_to_block(tmp_path):
    r = vd.decide("s", scan_dir=write_scan(tmp_path / "s", **kit_scan()), action="none", run_brand_check=False)
    assert r["verdict"] == "Scam" and r["action_taken"] == "none"


# ---------- A5 and A21: false positives ----------

def test_legit_site_with_bot_protection_is_no_evidence(tmp_path, env):
    form = f"email={quote_plus(DECOY['email'])}&password={quote_plus(DECOY['password'])}"
    r = run(tmp_path,
            robot={"final_url": f"http://{LEGIT}/", "title": "Sign in - Vexalo", "text": "Sign in",
                   "status": 200, "has_password_field": True},
            agent=[step(1, f"http://{LEGIT}/", "Login form", True, "Vexalo")],
            network=[{"ts": 5, "method": "POST", "url": f"http://{LEGIT}/login", "host": LEGIT, "postData": form}],
            probes=[{"ts": 1, "name": "webdriver"}])
    assert r["verdict"] == "No evidence found"
    assert r["h4"]["status"] == "supported" and r["action_taken"] == "none"
    assert {x["signal"] for x in r["reasons"]} == {"S3", "M3"}  # context only


def test_same_site_api_is_not_s1(tmp_path):
    r = run(tmp_path, robot={"final_url": "https://login.acme.com/", "has_password_field": True, "status": 200},
            agent=[step(1, "https://login.acme.com/", "Login form", True, "Acme")],
            network=[{"ts": 5, "method": "POST", "url": "https://api.acme.com/session", "host": "api.acme.com",
                      "postData": json.dumps(DECOY)}])
    assert r["verdict"] == "No evidence found" and r["password_sent_to"] == []


def test_login_provider_is_not_s1_even_with_content_swap(tmp_path):
    r = run(tmp_path, robot={"final_url": "https://acme.com/", "title": "Acme", "text": "Welcome",
                             "has_password_field": False, "status": 200},
            agent=[step(1, "https://acme.okta.com/login", "Okta sign in", True, "Acme")],
            network=[{"ts": 5, "method": "POST", "url": "https://acme.okta.com/api/v1/authn",
                      "host": "acme.okta.com", "postData": json.dumps(DECOY)}])
    assert r["verdict"] != "Scam" and "S1" not in {x["signal"] for x in r["reasons"]}
    assert r["h4"]["status"] == "supported"


def test_challenge_page_is_not_content_swap(tmp_path):
    challenge = {"final_url": f"http://{KIT}/", "title": "Just a moment...",
                 "text": "Checking your browser before accessing", "status": 403, "has_password_field": False}
    r = run(tmp_path, **kit_scan(robot_page=challenge))
    assert "S2" not in {x["signal"] for x in r["reasons"]}


def test_email_only_leak_is_a_fact_not_a_signal(tmp_path):
    r = run(tmp_path, robot={"final_url": "https://shop.example.com/", "has_password_field": True, "status": 200},
            agent=[step(1, "https://shop.example.com/login", "Login form", True)],
            network=[{"ts": 3, "method": "POST", "url": "https://analytics.example.net/collect",
                      "host": "analytics.example.net", "postData": json.dumps({"email": DECOY["email"]})},
                     {"ts": 5, "method": "POST", "url": "https://shop.example.com/login",
                      "host": "shop.example.com", "postData": json.dumps(DECOY)}])
    assert r["verdict"] == "No evidence found"
    assert r["email_shared_with"] == ["analytics.example.net"]


def test_third_party_password_alone_is_suspicious_not_scam(tmp_path):
    r = run(tmp_path, robot={"final_url": "https://shop.example.com/", "has_password_field": True, "status": 200},
            agent=[step(1, "https://shop.example.com/login", "Login form", True)],
            network=[{"ts": 5, "method": "POST", "url": "https://forms-vendor.com/submit",
                      "host": "forms-vendor.com", "postData": json.dumps(DECOY)}])
    assert r["verdict"] == "Suspicious" and r["action_taken"] == "none"
    assert r["h4"]["status"] == "refuted"


def test_google_forms_is_not_whitelisted(tmp_path):
    r = run(tmp_path, **kit_scan(post_host="docs.google.com"))
    assert r["password_sent_to"] == ["docs.google.com"] and r["verdict"] == "Scam"


def test_no_password_sent_leaves_h4_open(tmp_path):
    scan = kit_scan()
    scan["network"] = scan["network"][:1]
    r = run(tmp_path, **scan)
    assert r["h4"]["status"] == "open" and r["verdict"] != "Scam"


# ---------- A13: claim checks ----------

def claim(signal, *cites):
    return {"hypothesis": "H2", "signal": signal, "text": "x", "cite": list(cites)}


@pytest.mark.parametrize("bad,why", [
    (claim("S1", "victim/network.jsonl:1"), "decoy"),
    (claim("M2", "victim/navigations.jsonl:1"), "did not find M2"),
    (claim("S1", "../../etc/passwd"), "bad cite"),
    (claim("S1", "victim/network.jsonl:99"), "past the end"),
    (claim("S1", "victim/nothere.jsonl:1"), "does not exist"),
    (claim("S2", "victim/agent.jsonl:3"), "robot/robot.json"),
    (claim("S1"), "no evidence"),
])
def test_bad_claims_rejected(tmp_path, env, bad, why):
    scan = write_scan(tmp_path / "s", **kit_scan())
    r = vd.decide("s", [bad], scan_dir=scan, run_brand_check=False)
    assert why in r["rejected_claims"][0]["reason"]
    assert any(t == "claim_rejected" for t, _ in env[0])


def test_good_claims_accepted(tmp_path):
    scan = write_scan(tmp_path / "s", **kit_scan())
    good = [claim("S1", "victim/network.jsonl:2"), claim("S2", "robot/robot.json", "victim/agent.jsonl:3"),
            claim("M5", "victim/blocked.jsonl:1")]
    assert vd.decide("s", good, scan_dir=scan, run_brand_check=False)["rejected_claims"] == []


# ---------- brand check (8.3) ----------

def test_brand_check_result_drives_s4(tmp_path, monkeypatch):
    from app import llm
    calls = []

    def fake_vision(prompt, png, schema, *, name, validate=None):
        calls.append(prompt)
        return llm.Reply({"brand": "Vexalo", "confidence": 0.95}, "eye-model")
    monkeypatch.setattr(llm, "vision_json", fake_vision)
    scan = write_scan(tmp_path / "s", **kit_scan(brand=None), extra={"victim/step-03.png": "png"})
    r = vd.decide("s", scan_dir=scan)
    assert "<untrusted_page>" in calls[0]
    assert json.loads((scan / "victim" / "brand.json").read_text())["model"] == "eye-model"
    assert r["brand_shown"] == "Vexalo" and r["verdict"] == "Scam"


def test_brand_check_failure_falls_back(tmp_path, monkeypatch):
    from app import llm

    def down(*a, **k):
        raise llm.LLMError("down")
    monkeypatch.setattr(llm, "vision_json", down)
    scan = write_scan(tmp_path / "s", **kit_scan(), extra={"victim/step-03.png": "png"})
    assert vd.decide("s", scan_dir=scan)["brand_shown"] == "Vexalo"  # from agent brand_seen


def test_s4_claim_citing_agent_step_survives_vision_check(tmp_path, monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "vision_json", lambda *a, **k: llm.Reply({"brand": "Vexalo", "confidence": 0.9}, "eye"))
    scan = write_scan(tmp_path / "s", **kit_scan(), extra={"victim/step-03.png": "png"})
    r = vd.decide("s", [claim("S4", "victim/agent.jsonl:3")], scan_dir=scan)
    assert r["rejected_claims"] == []
