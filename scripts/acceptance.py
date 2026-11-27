"""Acceptance runner: start real scans on a deployed instance and check SPEC 16 tests from the events.

Usage (from a laptop or the VM; standard library only):
  python3 scripts/acceptance.py --base https://app.203-0-113-5.sslip.io --ip 203-0-113-5
  python3 scripts/acceptance.py --base ... --ip ... --presets kit,mobile --runs 3 --scoreboard --docker
Prints one row per check and exits 1 if any check fails. `--docker` also checks `docker ps -a`
for leftover sandboxes (only meaningful on the VM). Checks are pure functions over the event list,
so tests/test_acceptance.py runs them against the recorded investigations.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

PRESETS = {
    "kit": "http://vexalo-docs.{ip}.nip.io/",
    "mobile": "http://vexalo-docs.{ip}.nip.io/m/",
    "legit": "http://vexalo.{ip}.sslip.io/",
    "inject": "http://vexalo-docs.{ip}.nip.io/x/",
    "bomb": "http://vexalo-docs.{ip}.nip.io/bomb",
}
SCAN_TIMEOUT_S = 420


# ---------- checks (pure) ----------

def _of(events: list[dict], type: str) -> list[dict]:
    return [e["payload"] for e in events if e.get("type") == type]


def _index(events: list[dict], pred) -> int:
    return next((i for i, e in enumerate(events) if pred(e)), -1)


def _verdict(events: list[dict]) -> dict:
    v = _of(events, "verdict")
    return v[-1] if v else {}


def _h(events: list[dict], hid: str) -> str | None:
    updates = [u for u in _of(events, "hypothesis_update") if u.get("id") == hid]
    return updates[-1]["status"] if updates else None


def _signals(events: list[dict]) -> set[str]:
    return {r.get("signal") for r in _verdict(events).get("reasons", [])}


def check(preset: str, events: list[dict]) -> list[tuple[str, bool, str]]:
    """[(test id, ok, detail)] for one finished scan."""
    out: list[tuple[str, bool, str]] = []
    v, sig = _verdict(events), _signals(events)
    out.append(("verdict", bool(v), v.get("verdict", "no verdict event")))

    created, destroyed = _of(events, "sandbox_created"), _of(events, "sandbox_destroyed")
    if created:
        out.append(("A7", len(destroyed) >= len(created), f"{len(created)} created, {len(destroyed)} destroyed"))

    if preset in ("kit", "inject"):
        victim = [s for s in _of(events, "agent_step") if s.get("visit", "victim") == "victim"]
        sent = [d for d in _of(events, "decoy_sent") if d.get("field") == "password"]
        approved = [a for a in _of(events, "approval") if a.get("decision") == "auto_approved"]
        out.append(("A2", 0 < len(victim) <= 15 and bool(sent) and bool(approved),
                    f"{len(victim)} victim steps, password sent: {bool(sent)}, approved: {bool(approved)}"))
        hosts = sorted({d["host"] for d in sent})
        out.append(("A3", any(h.startswith("cdn-metrics.") for h in hosts), f"password to {hosts}"))
        out.append(("A6", v.get("verdict") == "Phishing" and "S1" in sig and bool(sig & {"S2", "S4", "M4"})
                    and _h(events, "H4") == "refuted",
                    f"{v.get('verdict')} {sorted(s for s in sig if s)}; H4 {_h(events, 'H4')}"))
        blocked = _of(events, "request_blocked")
        m5 = next((r for r in v.get("reasons", []) if r.get("signal") == "M5"), {})
        n_blocked = len(blocked) or len([c for c in m5.get("evidence", []) if "blocked.jsonl" in c])
        out.append(("A12", n_blocked >= 1 and "M5" in sig, f"{n_blocked} blocked requests shown, M5: {'M5' in sig}"))
        gate = _index(events, lambda e: e.get("type") == "approval")
        leak = _index(events, lambda e: e.get("type") == "decoy_sent" and e["payload"].get("field") == "password")
        out.append(("A20", 0 <= gate < leak, f"approval at event {gate}, password leaves at {leak}"))
        if preset == "inject":
            first = victim[0] if victim else {}
            out.append(("INJ", v.get("verdict") == "Phishing" and first.get("action") != "done",
                        f"first step {first.get('action')}: {first.get('reason', '')[:60]}"))
    elif preset == "mobile":
        tools = [d.get("tool") for d in _of(events, "dispatch")]
        out.append(("A11", "victim_mobile" in tools and v.get("verdict") == "Phishing" and _h(events, "H3") == "supported",
                    f"dispatched {tools}; {v.get('verdict')}; H3 {_h(events, 'H3')}"))
    elif preset == "legit":
        out.append(("A5", v.get("verdict") == "No evidence found" and _h(events, "H4") != "refuted",
                    f"{v.get('verdict')}; H4 {_h(events, 'H4')}; signals {sorted(s for s in sig if s)}"))
    elif preset == "bomb":
        hit = _of(events, "resource_limit_hit")
        out.append(("A18", bool(hit) and v.get("verdict") == "Suspicious" and "M5" in sig,
                    f"limit hit: {bool(hit)}; {v.get('verdict')} {sorted(s for s in sig if s)}"))
    return out


# ---------- talking to the app ----------

def _request(method: str, url: str, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def stream_events(base: str, scan_id: str, timeout_s: int = SCAN_TIMEOUT_S) -> list[dict]:
    """Read the SSE stream until the verdict arrives (plus a short grace for cleanup events)."""
    events, end, verdict_at = [], time.time() + timeout_s, None
    with _request("GET", f"{base}/api/scans/{scan_id}/events", timeout=timeout_s) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    continue
                if events[-1].get("type") == "verdict":
                    verdict_at = verdict_at or time.time()
            if time.time() > end or (verdict_at and time.time() - verdict_at > 10):
                break
    return events


def run_preset(base: str, ip: str, preset: str) -> tuple[str, list[dict]]:
    with _request("POST", f"{base}/api/scans", {"url": PRESETS[preset].format(ip=ip), "mode": "standard"}) as r:
        scan_id = json.loads(r.read())["scan_id"]
    return scan_id, stream_events(base, scan_id)


def health(base: str) -> tuple[str, bool, str]:
    try:
        with _request("GET", f"{base}/api/health") as r:
            h = json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return "A10", False, f"health failed: {e}"
    model = h.get("model") or ""
    return "A10", bool(model) and model != "ci-dummy", f"model {model!r}, runtime {h.get('runtime')}"


def scoreboard(base: str) -> tuple[str, bool, str]:
    try:
        with _request("POST", f"{base}/api/scoreboard", {}, timeout=240) as r:
            s = json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return "A9", False, f"scoreboard failed: {e}"
    if "robot" not in s:  # the route may answer at once and run in the background
        for _ in range(40):
            time.sleep(5)
            with _request("GET", f"{base}/api/scoreboard") as r:
                s = json.loads(r.read()) or {}
            if "robot" in s:
                break
    robot, victim = s.get("robot", {}), s.get("victim", {})
    return "A9", robot.get("bot") is True and victim.get("bot") is False, \
        f"robot bot={robot.get('bot')} ({robot.get('botKind')}), victim bot={victim.get('bot')}"


def leftover_containers() -> tuple[str, bool, str]:
    time.sleep(10)
    out = subprocess.run(["docker", "ps", "-a", "--filter", "name=pd-", "--format", "{{.Names}}"],
                         capture_output=True, text=True, check=False).stdout.split()
    return "A7-docker", not out, f"leftover: {out or 'none'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="app URL, for example https://app.203-0-113-5.sslip.io")
    ap.add_argument("--ip", required=True, help="VM IP dashed, for example 203-0-113-5")
    ap.add_argument("--presets", default="kit,mobile,legit,inject")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--scoreboard", action="store_true")
    ap.add_argument("--docker", action="store_true")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    rows = [("-", *health(base))]
    for preset in args.presets.split(","):
        for n in range(args.runs):
            label = f"{preset}#{n + 1}"
            print(f"running {label} ...", flush=True)
            try:
                scan_id, events = run_preset(base, args.ip, preset)
            except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError) as e:
                rows.append((label, "start", False, str(e)[:120]))
                continue
            rows += [(f"{label} {scan_id}", *c) for c in check(preset, events)]
    if args.scoreboard:
        rows.append(("-", *scoreboard(base)))
    if args.docker:
        rows.append(("-", *leftover_containers()))

    width = max(len(r[0]) for r in rows)
    for scan, test, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {test:<9} {scan:<{width}}  {detail}")
    failed = sum(1 for r in rows if not r[2])
    print(f"\n{len(rows) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
