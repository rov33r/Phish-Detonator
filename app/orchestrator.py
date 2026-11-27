"""Runs one scan end to end (SPEC 5, 6A, 10): plan, round 1, investigator loop, verdict, cleanup.

Every visit gets a fresh sandbox that is destroyed in `finally`. Global caps (PD_MAX_SCANS,
PD_MAX_SANDBOXES) bound what runs at once; further scans wait in FIFO order.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from app import agent, db, investigator, sandbox, verdict

ROBOT_TIMEOUT = 60
TIME_LIMIT_GRACE = 15
ROUND1_REASON = {
    "robot": "I always start with a robot visit to see what a crawler is shown.",
    "victim": "I always send a victim visit to see what a person is shown and where a password goes.",
}

peak_mem_mb: dict[str, int] = {}  # container -> peak memory, filled by stats.watch

_lock = threading.Lock()
_slots: dict[str, threading.Semaphore] = {}
_waiting: list[str] = []
_context: dict[str, dict] = {}


def _slot(name: str, env: str, default: str) -> threading.Semaphore:
    with _lock:
        if name not in _slots:
            _slots[name] = threading.BoundedSemaphore(int(os.environ.get(env, default)))
        return _slots[name]


def _scan_dir(scan_id: str) -> pathlib.Path:
    return pathlib.Path(os.environ.get("PD_SCANS_DIR", "scans")) / scan_id


def _error(scan_id: str, where: str, exc: BaseException) -> None:
    db.emit(scan_id, "error", {"where": where, "message": f"{type(exc).__name__}: {exc}"[:300]})


def _time_limit(scan_id: str, visit: str, container: str) -> None:
    limit_mb = int(str(sandbox.LIMITS["memory"]).rstrip("g")) * 1024
    peak = peak_mem_mb.get(container, 0)
    out = sandbox.out_dir(scan_id, visit)
    out.mkdir(parents=True, exist_ok=True)
    (out / "resource_limit.json").write_text(
        json.dumps({"kind": "time", "seconds": sandbox.LIMITS["seconds"]}))
    db.emit(scan_id, "resource_limit_hit", {"visit": visit, "kind": "time", "peak_mb": peak, "limit_mb": limit_mb})
    sandbox.stop_visit(container)


def _run_visit(scan_id: str, visit: str, profile: str, work: Callable[[str], None]) -> None:
    """One sandbox: create, run `work(container)`, always destroy. Errors become events, not crashes."""
    with _slot("sandboxes", "PD_MAX_SANDBOXES", "4"):
        started = time.monotonic()
        try:
            container = sandbox.start_visit(scan_id, visit, profile)
        except Exception as exc:
            _error(scan_id, f"start_visit:{visit}", exc)
            return
        # Grace past the agent's own 120 s cap: it checks its deadline between steps, so a slow but
        # normal visit must not be reported as a resource limit (signal M5).
        timer = threading.Timer(sandbox.LIMITS["seconds"] + TIME_LIMIT_GRACE, _time_limit, (scan_id, visit, container))
        timer.daemon = True
        timer.start()
        try:
            work(container)
        except Exception as exc:
            _error(scan_id, f"visit:{visit}", exc)
        finally:
            timer.cancel()
            sandbox.stop_visit(container)
            db.emit(scan_id, "sandbox_destroyed", {
                "visit": visit, "container": container, "lifetime_s": round(time.monotonic() - started, 1),
                "peak_mem_mb": peak_mem_mb.pop(container, 0)})


def _robot(scan_id: str, visit: str, url: str) -> Callable[[str], None]:
    def work(container: str) -> None:
        sandbox.exec_in(container, ["node", "bot.mjs", url], timeout=ROBOT_TIMEOUT)
        robot = verdict.read_json(sandbox.out_dir(scan_id, visit) / "robot.json") or {}
        db.emit(scan_id, "robot_done", {
            "final_url": robot.get("final_url"), "title": robot.get("title"),
            "screenshot": f"{visit}/final.png", "has_password_field": bool(robot.get("has_password_field"))})
    return work


def _victim(scan_id: str, visit: str, url: str, decoy: dict, goal: str | None) -> Callable[[str], None]:
    def work(container: str) -> None:
        agent.run_victim(scan_id, url, container, decoy, goal, visit=visit)
    return work


def _announce(scan_id: str, visit: str, profile: str, tool: str, reason: str) -> None:
    ctx = _context[scan_id]
    ctx["round"] += 1 if tool not in ROUND1_REASON else 0
    ctx["used"] += 1
    db.emit(scan_id, "dispatch", {
        "visit": visit, "profile": profile, "tool": tool, "reason": reason, "round": ctx["round"],
        "budget_left": {"sandboxes": ctx["max_sandboxes"] - ctx["used"],
                        "seconds": max(0, int(ctx["max_seconds"] - (time.monotonic() - ctx["started"])))}})


def dispatch(scan_id: str, tool: dict) -> dict:
    """Runs one investigator tool call in a fresh sandbox and returns the new visit summary."""
    ctx = _context[scan_id]
    name, args = tool["tool"], tool.get("args") or {}
    ctx["n"] += 1
    if name == "robot_followup":
        scheme = urlsplit(ctx["url"]).scheme or "http"
        visit, profile = f"robot-{ctx['n']}", "robot"
        _announce(scan_id, visit, profile, name, tool.get("reason", ""))
        _run_visit(scan_id, visit, profile, _robot(scan_id, visit, f"{scheme}://{args['host']}/"))
    elif name in ("victim_mobile", "victim_retry"):
        profile = "victim_mobile" if name == "victim_mobile" else "victim"
        visit = f"{profile}-{ctx['n']}"
        _announce(scan_id, visit, profile, name, tool.get("reason", ""))
        goal = args.get("goal") if name == "victim_retry" else None
        _run_visit(scan_id, visit, profile, _victim(scan_id, visit, ctx["url"], ctx["decoy"], goal))
    else:
        raise ValueError(f"unknown tool {name!r}")
    return investigator.visit_summary(_scan_dir(scan_id), visit, ctx["decoy"])


def _wait_for_slot(scan_id: str) -> threading.Semaphore:
    scans = _slot("scans", "PD_MAX_SCANS", "2")
    if scans.acquire(blocking=False):
        return scans
    with _lock:
        _waiting.append(scan_id)
        position = len(_waiting)
    db.emit(scan_id, "scan_queued", {"position": position})
    scans.acquire()
    with _lock:
        _waiting.remove(scan_id)
    return scans


CAPTURE_REASON = ("This link is not on the active-scan list, so I only send a robot in a sandbox to take a "
                  "screenshot. No decoy identity is submitted.")


def run_capture(scan_id: str, url: str) -> None:
    """Robot-only visit in a fresh sandbox for links outside the active-scan list. Never raises.

    Same containment as a full scan (gVisor, network lock, limits); no victim, no decoy, no verdict.
    """
    scans = _wait_for_slot(scan_id)
    try:
        _scan_dir(scan_id).mkdir(parents=True, exist_ok=True)
        db.update_scan(scan_id, url=url, mode="standard", status="running", capture_only=True)
        db.emit(scan_id, "scan_started", {"url": url, "mode": "standard", "decoy_email": None})
        db.emit(scan_id, "dispatch", {"visit": "robot", "profile": "robot", "tool": "robot", "reason": CAPTURE_REASON,
                                      "round": 1, "budget_left": {"sandboxes": 0, "seconds": 0}})
        _run_visit(scan_id, "robot", "robot", _robot(scan_id, "robot", url))
        captured = (sandbox.out_dir(scan_id, "robot") / "final.png").is_file()
        db.update_scan(scan_id, status="finished" if captured else "failed")
    except Exception as exc:
        _error(scan_id, "capture", exc)
        db.update_scan(scan_id, status="failed")
    finally:
        scans.release()


def run_scan(scan_id: str, url: str, mode: str = "standard") -> None:
    """Plan, round 1 (robot and victim in parallel), investigator loop, verdict. Never raises."""
    scans = _wait_for_slot(scan_id)
    scan_dir = _scan_dir(scan_id)
    try:
        scan_dir.mkdir(parents=True, exist_ok=True)
        decoy = agent.make_decoy()
        (scan_dir / "decoy.json").write_text(json.dumps(decoy))
        _context[scan_id] = {
            "url": url, "decoy": decoy, "n": 2, "round": 1, "used": 0, "started": time.monotonic(),
            "max_sandboxes": int(os.environ.get("PD_INVESTIGATOR_MAX_SANDBOXES", "5")),
            "max_seconds": int(os.environ.get("PD_INVESTIGATOR_MAX_SECONDS", "240"))}
        db.update_scan(scan_id, url=url, mode=mode, status="running")
        db.emit(scan_id, "scan_started", {"url": url, "mode": mode, "decoy_email": decoy["email"]})

        try:
            investigator.plan(scan_id, url)
        except Exception as exc:  # round 1 is fixed and does not need the plan
            _error(scan_id, "plan", exc)
        for visit in ("robot", "victim"):
            _announce(scan_id, visit, visit, visit, ROUND1_REASON[visit])
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(_run_visit, scan_id, "robot", "robot", _robot(scan_id, "robot", url)),
                    pool.submit(_run_visit, scan_id, "victim", "victim",
                                _victim(scan_id, "victim", url, decoy, None))]
            for job in jobs:
                job.result()
        round1 = [investigator.visit_summary(scan_dir, v, decoy) for v in ("robot", "victim")]

        try:
            concluded = investigator.investigate(scan_id, round1, lambda step: dispatch(scan_id, step))
        except Exception as exc:
            _error(scan_id, "investigator", exc)
            concluded = investigator.fallback_conclude(scan_id)["args"]
        result = verdict.decide(scan_id, concluded.get("claims"), action=concluded.get("action", "block"),
                                untested=concluded.get("untested"))
        db.update_scan(scan_id, status="finished", verdict=result.get("verdict"))
    except Exception as exc:
        _error(scan_id, "orchestrator", exc)
        db.update_scan(scan_id, status="failed")
    finally:
        _context.pop(scan_id, None)
        scans.release()


if __name__ == "__main__":  # python -m app.orchestrator <url>: one real scan without the web app
    import sys
    import uuid

    sid = f"cli-{uuid.uuid4().hex[:8]}"
    run_scan(sid, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "standard")
    for event in db.events(sid):
        print(event["type"], json.dumps(event["payload"])[:200])
