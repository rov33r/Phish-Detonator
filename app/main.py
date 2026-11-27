"""Lane C dashboard and local simulated investigation transport."""

import asyncio
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app import agent, blocklist, db, orchestrator, scoreboard
from app.email_intake import extract_links, flags

ROOT = Path(__file__).resolve().parent
PRESETS = {
    "legit": "https://vexalo.example/login",
    "kit": "https://vexalo-docs.example/share",
    "mobile": "https://vexalo-docs.example/m/",
    "bomb": "https://vexalo-docs.example/bomb",
}
DECOY = "analyst.demo@decoy.example"
LIMITS = {"memory": 2048, "cpus": 2, "pids": 512, "seconds": 120}
DEMO_FILES = {
    "robot/final.png": "news.png",
    "robot/login.png": "login.png",
    "victim/step-01.png": "document.png",
    "victim/login.png": "login.png",
    "victim_mobile-3/login.png": "login.png",
    "checks/destinations.jsonl": "destinations.jsonl",
    "victim/network.txt": "network.txt",
    "victim_mobile-3/network.txt": "network.txt",
}


def timestamp():
    return datetime.now(UTC).isoformat()


@dataclass
class Scan:
    url: str
    mode: str
    status: str = "running"
    capture_only: bool = False
    screenshot: bytes | None = None
    http_status: int | None = None
    access_gate: str | None = None
    verdict: dict | None = None
    decision: str | None = None
    decided_by: str | None = None
    events: list[dict] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def emit(self, event_type, payload):
        async with self.changed:
            self.events.append({
                "id": len(self.events) + 1, "ts": timestamp(),
                "type": event_type, "payload": payload,
            })
            self.changed.notify_all()


DEMO_APPROVAL_TIMEOUT_S = 8


def demo_events(url, mode):
    preset = next((key for key, value in PRESETS.items() if value == url), "kit")
    legit = preset == "legit"
    bomb = preset == "bomb"
    mobile = preset == "mobile"
    phishing = not (legit or bomb)
    yield "scan_started", {"url": url, "mode": mode, "decoy_email": DECOY}
    hypotheses = [
        {"id": "H1", "text": "Do the scanner and the victim see different pages?", "status": "open"},
        {"id": "H2", "text": "Does the password go to an unrelated host?", "status": "open"},
        {"id": "H3", "text": "Does the sign-in form appear only for some visitors?", "status": "open"},
        {"id": "H4", "text": "Is the destination a legitimate login provider?", "status": "open"},
    ]
    yield "plan", {
        "text": "I’ll compare two browser views and trace the decoy form submission.",
        "hypotheses": hypotheses,
    }
    for index, visit in enumerate(("robot", "victim"), start=1):
        reason = (
            "I’ll capture what a scanner can see." if visit == "robot"
            else "I’ll compare that view with the victim session."
        )
        yield "dispatch", {
            "visit": visit, "profile": visit, "tool": visit, "round": 1,
            "reason": reason, "budget_left": {"sandboxes": 5 - index, "seconds": 240},
        }
        yield "sandbox_created", {
            "visit": visit, "profile": visit, "container": f"demo-{visit}",
            "runtime": "simulated", "limits": LIMITS,
        }
    yield "robot_done", {
        "final_url": PRESETS["legit"] if legit else "https://vexalo-docs.example/news",
        "title": "Vexalo sign in" if legit else "Vexalo News",
        "screenshot": "robot/login.png" if legit else "robot/final.png",
        "has_password_field": legit,
    }
    if not legit:
        yield "agent_step", {
            "visit": "victim", "step": 1, "model": "simulated", "action": "wait", "ref": None, "url": url, "title": "Vexalo Documents",
            "reason": "I’m checking what the shared document page shows.",
            "is_login_page": False, "brand_seen": "Vexalo",
        }
        yield "screenshot", {"visit": "victim", "step": 1, "path": "victim/step-01.png"}
    yield "sandbox_destroyed", {
        "visit": "robot", "container": "demo-robot", "lifetime_s": 4, "peak_mem_mb": 184,
    }
    victim = "victim"
    if mobile:
        yield "sandbox_destroyed", {
            "visit": "victim", "container": "demo-victim", "lifetime_s": 7, "peak_mem_mb": 310,
        }
        victim = "victim_mobile-3"
        yield "dispatch", {
            "visit": victim, "profile": "victim_mobile", "tool": "victim_mobile", "round": 2,
            "reason": "I’ll compare a mobile visit because the desktop view stopped at the document.",
            "budget_left": {"sandboxes": 2, "seconds": 220},
        }
        yield "sandbox_created", {
            "visit": victim, "profile": "victim_mobile", "container": f"demo-{victim}",
            "runtime": "simulated", "limits": LIMITS,
        }
    peak = 2048 if bomb else 428
    yield "sandbox_stats", {
        "visit": victim, "mem_mb": peak, "mem_limit_mb": 2048, "cpu_pct": 24, "pids": 32,
    }
    yield "host_stats", {"load_1m": 0.42, "mem_used_pct": 28}
    reasons = []
    trail = []
    if bomb:
        yield "resource_limit_hit", {
            "visit": victim, "kind": "memory", "peak_mb": peak, "limit_mb": 2048,
        }
        reasons.append({"signal": "M5", "text": "Victim session reached its memory cap.", "evidence": []})
    else:
        yield "agent_step", {
            "visit": victim, "step": 2, "model": "simulated", "action": "done", "ref": None, "url": url, "title": "Vexalo sign in",
            "reason": "I found a sign-in form in the victim view.",
            "is_login_page": True, "brand_seen": "Vexalo",
        }
        login = f"{victim}/login.png"
        yield "screenshot", {"visit": victim, "step": 2, "path": login}
        host = "cdn-metrics.example" if phishing else "vexalo.example"
        yield "approval_requested", {
            "visit": victim, "step": 2, "host": urlsplit(url).hostname or "",
            "fields": ["email", "password"], "timeout_s": DEMO_APPROVAL_TIMEOUT_S,
        }
        yield "approval", {
            "visit": victim, "step": 2, "action": "submit", "ref": None,
            "typed": ["{{DECOY_EMAIL}}", "{{DECOY_PASSWORD}}"],
            "checks": [{"name": "Synthetic values only", "ok": True}],
            "decision": "timed_out",
            "reason": "No analyst answer in the simulation; the code policy approved a decoy-only submit.",
        }
        if phishing:
            trail.append(host)
        receipt = f"{victim}/network.txt"
        yield "request_seen", {"visit": victim, "method": "POST", "host": host, "url": f"https://{host}/submit"}
        yield "decoy_sent", {"host": host, "url": f"https://{host}/submit", "field": "password", "encoding": "plain"}
        if phishing:
            yield "probe_seen", {"visit": victim, "name": "webdriver"}
            for blocked in ("Cloud metadata", "Host gateway", "Application"):
                yield "request_blocked", {
                    "visit": victim, "host": blocked, "url": "https://blocked.example/",
                    "error": "Simulated network policy rejection",
                }
            yield "claim_rejected", {
                "claim": "The decoy was sent to a second collector.",
                "reason": "The recorded request shows one destination.",
            }
            reasons.extend([
                {"signal": "S1", "text": "The decoy password reached an unrelated host.", "evidence": [f"{receipt}:1"]},
                {"signal": "S2", "text": "The scanner saw news while the victim saw a sign-in form.",
                 "evidence": ["robot/final.png", login]},
            ])
        for key, evidence in (("H1", [login]), ("H2", [f"{receipt}:1"] if phishing else [])):
            yield "hypothesis_update", {
                "id": key, "status": "supported" if phishing else "refuted",
                "reason": "Comparison complete.", "evidence": evidence,
            }
        yield "hypothesis_update", {
            "id": "H4", "status": "refuted" if phishing else "supported",
            "reason": (
                "The destination is unrelated to Vexalo and is not a known login provider."
                if phishing else "Vexalo received the decoy on its own domain."
            ),
            "evidence": ["checks/destinations.jsonl:1"],
        }
        if mobile:
            yield "hypothesis_update", {
                "id": "H3", "status": "supported",
                "reason": "The mobile capture shows the sign-in form.", "evidence": [login],
            }
    yield "sandbox_destroyed", {
        "visit": victim, "container": f"demo-{victim}", "lifetime_s": 12, "peak_mem_mb": peak,
    }
    yield "verdict", {
        "verdict": "Phishing" if phishing else "Suspicious" if bomb else "No evidence found",
        "reasons": reasons, "password_sent_to": trail,
        "action_taken": "blocked" if phishing else "none", "decided_by": "agent",
        "untested": ["Password destination"] if bomb else [],
    }


async def play_demo(scan, delay):
    try:
        for event_type, payload in demo_events(scan.url, scan.mode):
            await asyncio.sleep(delay)
            if event_type == "verdict":
                scan.verdict = payload
                if payload["action_taken"] == "blocked":
                    scan.decision = "block"
                    scan.decided_by = "agent"
            await scan.emit(event_type, payload)
            if event_type == "approval_requested" and delay:
                # Hold so the approval card stays on screen for its countdown.
                await asyncio.sleep(payload["timeout_s"])
    finally:
        async with scan.changed:
            scan.status = "finished" if scan.verdict else "failed"
            scan.changed.notify_all()


@asynccontextmanager
async def lifespan(application):
    application.state.scans = {}
    application.state.tasks = set()
    application.state.demo = os.getenv("PD_FEATURE_FAKE_SCAN") == "1"
    application.state.delay = 0.38
    yield
    tasks = list(application.state.tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class ScanInput(BaseModel):
    url: HttpUrl
    mode: Literal["standard", "high_risk"] = "standard"


class EmailPreviewInput(BaseModel):
    email_text: str = Field(min_length=1, max_length=50_000)


@app.post("/api/email-preview")
async def email_preview(body: EmailPreviewInput):
    try:
        links = extract_links(body.email_text)
        for link in links:
            link["blocklist"] = await asyncio.to_thread(blocklist.lookup, link["url"])
        return {"links": links, "flags": flags(body.email_text, links)}
    except ValueError as error:
        raise HTTPException(422, "The email could not be parsed") from error


class DecisionInput(BaseModel):
    decision: Literal["block", "release"]


class ApprovalInput(BaseModel):
    visit: str = Field(min_length=1, max_length=64)
    decision: Literal["approve", "deny"]


def demo_scan(request, scan_id):
    return getattr(request.app.state, "scans", {}).get(scan_id)


def scan_directory(scan_id):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", scan_id):
        raise HTTPException(404, "Scan not found")
    root = Path(os.getenv("PD_SCANS_DIR", "scans")).resolve()
    directory = (root / scan_id).resolve()
    if directory.parent != root:
        raise HTTPException(404, "Scan not found")
    return directory


def recorded_events(scan_id):
    path = scan_directory(scan_id) / "events.jsonl"
    if not path.is_file() or path.is_symlink():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        raise HTTPException(404, "Recording unavailable") from error


def public_record(scan_id, record):
    allowed = ("url", "mode", "status", "verdict", "decision", "decided_by", "capture_only", "http_status", "access_gate")
    return {"id": scan_id, **{key: record[key] for key in allowed if key in record}}


def configured_recordings():
    pairs = (part.partition("=") for part in os.getenv("PD_DEMO_SCANS", "").split(","))
    return {label.strip(): identifier.strip() for label, sep, identifier in pairs
            if sep and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identifier.strip())}


def live_presets() -> dict[str, str]:
    """The owned fixture URLs on this VM; empty unless live investigations are on."""
    ip = os.getenv("PD_PUBLIC_IP_DASHED", "")
    if os.getenv("PD_FEATURE_ORCHESTRATOR") != "1" or not ip:
        return {}
    kit = f"http://vexalo-docs.{ip}.nip.io"
    return {"legit": f"http://vexalo.{ip}.sslip.io/", "kit": f"{kit}/", "mobile": f"{kit}/m/",
            "bomb": f"{kit}/bomb", "inject": f"{kit}/x/"}


def orchestrator_enabled(url: str) -> bool:
    """Full investigation (victim browser, decoy identity) only for owned fixture hosts and hosts in
    PD_ACTIVE_SCAN_HOSTS; `*` allows every link. Everything else gets a sandboxed robot capture."""
    if os.getenv("PD_FEATURE_ORCHESTRATOR") != "1":
        return False
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    allowed = {item.strip().lower().rstrip(".") for item in os.getenv("PD_ACTIVE_SCAN_HOSTS", "").split(",")
               if item.strip()}
    allowed |= {(urlsplit(preset).hostname or "") for preset in live_presets().values()}
    return bool(host) and ("*" in allowed or host in allowed)


@app.get("/")
async def index():
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/api/health")
async def health(request: Request):
    return {"ok": True, "model": os.getenv("PD_MODEL"), "runtime": os.getenv("PD_RUNTIME", "runsc"),
            "demo": getattr(request.app.state, "demo", False), "recordings": configured_recordings(),
            "scoreboard_enabled": os.getenv("PD_FEATURE_ORCHESTRATOR") == "1"
            and bool(os.getenv("PD_PUBLIC_IP_DASHED")), "live_presets": live_presets()}


RATE_WINDOW_S = 600
_rate_lock = threading.Lock()
_recent: dict[str, list[float]] = {}


def client_ip(request: Request) -> str | None:
    """The visitor's IP. Behind Caddy every request comes from 127.0.0.1, so then the address Caddy
    saw (the last X-Forwarded-For entry) counts; a client cannot spoof it past the proxy."""
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for", "")
    if peer in ("127.0.0.1", "::1") and forwarded:
        return forwarded.split(",")[-1].strip() or peer
    return peer


def over_rate_limit(ip: str | None) -> bool:
    """Public URL abuse (SPEC 10, A14): PD_RATE_LIMIT_PER_IP live scans per IP per 10 minutes; 0 disables."""
    limit = int(os.getenv("PD_RATE_LIMIT_PER_IP", "20"))
    if not limit or not ip:
        return False
    now = time.monotonic()
    with _rate_lock:
        recent = [t for t in _recent.get(ip, []) if now - t < RATE_WINDOW_S]
        if len(recent) >= limit:
            _recent[ip] = recent
            return True
        _recent[ip] = recent + [now]
        return False


@app.post("/api/scans", status_code=202)
async def start_scan(body: ScanInput, request: Request):
    state = request.app.state
    url = str(body.url)
    demo = url in PRESETS.values()
    if demo and not state.demo:
        raise HTTPException(503, "Simulated scans are disabled")
    scan_id = uuid4().hex
    if not demo:
        if os.getenv("PD_FEATURE_ORCHESTRATOR") != "1":
            raise HTTPException(503, "Live scans are not enabled on this server")
        active = orchestrator_enabled(url)
        if not active and body.mode != "standard":
            raise HTTPException(422, "Links outside the active-scan list use Standard mode.")
        ip = client_ip(request)
        if over_rate_limit(ip):
            raise HTTPException(429, "Too many scans from this address. Try again in a few minutes.")
        await asyncio.to_thread(db.update_scan, scan_id, url=url, mode=body.mode, status="queued",
                                client_ip=ip, capture_only=not active)
        known = await asyncio.to_thread(blocklist.lookup, url, exclude=scan_id)
        if known:  # the link was decided before: say so first, then investigate it fresh
            await asyncio.to_thread(db.emit, scan_id, "blocklist_hit", known)
        # Both paths run in sandboxes: a full investigation, or a robot-only capture without a decoy.
        target, args = (orchestrator.run_scan, (scan_id, url, body.mode)) if active else (orchestrator.run_capture, (scan_id, url))
        threading.Thread(target=target, args=args, daemon=True).start()
        return {"scan_id": scan_id, "queued_position": None, "capture_only": not active}
    scan = Scan(url, body.mode)
    state.scans[scan_id] = scan
    task = asyncio.create_task(play_demo(scan, state.delay))
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return {"scan_id": scan_id, "queued_position": None, "capture_only": False}


@app.get("/api/scoreboard")
def saved_scoreboard():
    return scoreboard.latest()


@app.post("/api/scoreboard")
async def run_scoreboard(request: Request):
    if os.getenv("PD_FEATURE_ORCHESTRATOR") != "1" or not os.getenv("PD_PUBLIC_IP_DASHED"):
        raise HTTPException(503, "The owned fixture scoreboard is not configured")
    return await asyncio.to_thread(scoreboard.run)


@app.get("/replay/{scan_id}")
def replay_page(scan_id: str):
    if not recorded_events(scan_id):
        raise HTTPException(404, "Recording not found")
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/api/scans/{scan_id}")
async def scan_record(scan_id: str, request: Request):
    scan = demo_scan(request, scan_id)
    if scan is not None:
        return public_record(scan_id, vars(scan))
    scan_directory(scan_id)
    record = await asyncio.to_thread(db.get_scan, scan_id)
    if record is not None:
        return public_record(scan_id, record)
    history = await asyncio.to_thread(recorded_events, scan_id)
    if not history:
        raise HTTPException(404, "Scan not found")
    started = next((event["payload"] for event in history if event["type"] == "scan_started"), {})
    outcome = next((event["payload"] for event in reversed(history) if event["type"] == "verdict"), {})
    return public_record(scan_id, {
        **started, "status": "finished" if outcome else "incomplete", "verdict": outcome.get("verdict"),
    })


def sse_event(event):
    return f"id: {event['id']}\ndata: {json.dumps(event)}\n\n"


async def replay_recording(history, cursor):
    for event in history:
        if event["id"] > cursor:
            yield sse_event(event)


async def stream_persisted(scan_id, cursor):
    loop = asyncio.get_running_loop()
    changed = asyncio.Event()

    def listener(event):
        if event["scan_id"] == scan_id:
            loop.call_soon_threadsafe(changed.set)

    db.subscribe(listener)
    try:
        while True:
            changed.clear()
            batch = await asyncio.to_thread(db.events, scan_id, cursor)
            for event in batch:
                cursor = event["id"]
                yield sse_event(event)
            status = (await asyncio.to_thread(db.get_scan, scan_id) or {}).get("status")
            if status in {"finished", "failed", "error"}:
                # A final event can land between the first event query and the status query.
                for event in await asyncio.to_thread(db.events, scan_id, cursor):
                    yield sse_event(event)
                break
            try:
                await asyncio.wait_for(changed.wait(), timeout=10)
            except TimeoutError:
                yield ": keepalive\n\n"
    finally:
        db.unsubscribe(listener)


@app.get("/api/scans/{scan_id}/events")
async def scan_events(scan_id: str, request: Request, after: int = 0):
    scan = demo_scan(request, scan_id)
    last_id = request.headers.get("Last-Event-ID", "")
    cursor = max(0, int(last_id) if last_id.isascii() and last_id.isdecimal() and len(last_id) < 15 else after)

    async def stream():
        nonlocal cursor
        while True:
            heartbeat = False
            async with scan.changed:
                try:
                    await asyncio.wait_for(
                        scan.changed.wait_for(lambda current=cursor: current < len(scan.events) or scan.status != "running"),
                        timeout=12,
                    )
                except TimeoutError:
                    heartbeat = True
                batch = scan.events[cursor:]
                finished = scan.status != "running"
            if heartbeat:
                yield ": keepalive\n\n"
            for event in batch:
                cursor = event["id"]
                yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
            if finished:
                break

    if scan is not None:
        events = stream()
    else:
        scan_directory(scan_id)
        record = await asyncio.to_thread(db.get_scan, scan_id)
        if record is not None:
            events = stream_persisted(scan_id, cursor)
        else:
            history = await asyncio.to_thread(recorded_events, scan_id)
            if not history:
                raise HTTPException(404, "Scan not found")
            events = replay_recording(history, cursor)
    return StreamingResponse(events, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/blocklist")
async def get_blocklist():
    """Links the agent or an analyst decided, latest decision per link, newest first."""
    return {"entries": await asyncio.to_thread(blocklist.entries)}


@app.post("/api/scans/{scan_id}/approve")
async def approve(scan_id: str, body: ApprovalInput):
    """The analyst answers an approval_requested before the agent's submit (SPEC 6.6 manual mode)."""
    record = await asyncio.to_thread(db.get_scan, scan_id)
    if record is None or record.get("capture_only"):
        raise HTTPException(404, "Scan not found")
    if not agent.answer(scan_id, body.visit, body.decision):
        raise HTTPException(409, "Nothing is waiting for approval in this visit")
    return {"visit": body.visit, "decision": body.decision}


@app.post("/api/scans/{scan_id}/decision")
async def decide(scan_id: str, body: DecisionInput, request: Request):
    scan = demo_scan(request, scan_id)
    if scan is None:  # a real scan: the analyst can override the agent's decision (SPEC 8.4 step 4)
        record = await asyncio.to_thread(db.get_scan, scan_id)
        if record is None or record.get("capture_only"):
            raise HTTPException(404, "Editable scan not found")
        if not record.get("verdict"):
            raise HTTPException(409, "Wait for the verdict before making a decision")
        payload = {"decision": body.decision, "decided_by": "analyst"}
        await asyncio.to_thread(db.update_scan, scan_id, **payload, decided_at=datetime.now(UTC).isoformat())
        await asyncio.to_thread(db.emit, scan_id, "decision", payload)
        return payload
    if scan.capture_only:
        raise HTTPException(404, "Editable scan not found")
    if scan.verdict is None:
        raise HTTPException(409, "Wait for the verdict before making a decision")
    scan.decision = body.decision
    scan.decided_by = "analyst"
    payload = {"decision": scan.decision, "decided_by": scan.decided_by}
    await scan.emit("decision", payload)
    return payload


@app.get("/api/scans/{scan_id}/files/{path:path}")
async def evidence(scan_id: str, path: str, request: Request):
    scan = demo_scan(request, scan_id)
    if scan is None:
        directory = scan_directory(scan_id)
        relative = PurePosixPath(path)
        media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".json": "text/plain", ".jsonl": "text/plain", ".txt": "text/plain"}
        if (relative.is_absolute() or ".." in relative.parts or "\\" in path
                or relative.name == "decoy.json" or relative.suffix not in media):
            raise HTTPException(404, "Evidence not found")
        candidate = (directory / relative).resolve()
        if not candidate.is_relative_to(directory) or not candidate.is_file():
            raise HTTPException(404, "Evidence not found")
        record = await asyncio.to_thread(db.get_scan, scan_id)
        if record is None and not await asyncio.to_thread(recorded_events, scan_id):
            raise HTTPException(404, "Evidence not found")
        return FileResponse(candidate, media_type=media[relative.suffix],
                            headers={"X-Content-Type-Options": "nosniff"})
    if scan.capture_only:
        if path != "robot/final.png" or scan.screenshot is None:
            raise HTTPException(404, "Evidence not found")
        return Response(scan.screenshot, media_type="image/png", headers={"Cache-Control": "no-store"})
    disclosed = any(
        path in (event["payload"].get("path"), event["payload"].get("screenshot"))
        or any(cite.split(":")[0] == path for cite in event["payload"].get("evidence", []))
        or any(cite.split(":")[0] == path for reason in event["payload"].get("reasons", [])
               for cite in reason["evidence"])
        for event in scan.events
    )
    if not disclosed or path not in DEMO_FILES:
        raise HTTPException(404, "Evidence not found")
    fixture = ROOT / "static" / "demo" / DEMO_FILES[path]
    if path == "checks/destinations.jsonl":
        host = next(event["payload"]["host"] for event in scan.events if event["type"] == "decoy_sent")
        brand_owned = host == "vexalo.example"
        return PlainTextResponse(json.dumps({
            "host": host, "field": "password", "same_site": brand_owned,
            "brand_owned": brand_owned, "login_provider": False, "followup": None,
        }) + "\n")
    if fixture.suffix == ".txt":
        host = next(event["payload"]["host"] for event in scan.events if event["type"] == "decoy_sent")
        return PlainTextResponse(f"Simulated POST to {host}. Synthetic password marker observed.\n")
    return FileResponse(fixture)
