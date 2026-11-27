"""Event and scan store (SPEC 10). SQLite, one short connection per call so worker threads can emit.

Listeners registered with `subscribe` get every event right after it is stored; app/main.py uses one
to push events into the live SSE stream.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, fields TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_scan ON events (scan_id, id);
"""

_lock = threading.Lock()
_listeners: list[Callable[[dict], None]] = []
log = logging.getLogger(__name__)


def db_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PD_DB", "scans/pd.db"))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.executescript(SCHEMA)
    return con


def subscribe(listener: Callable[[dict], None]) -> None:
    _listeners.append(listener)


def unsubscribe(listener: Callable[[dict], None]) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def emit(scan_id: str, type: str, payload: dict) -> None:
    ts = datetime.now(UTC).isoformat()
    with _lock, closing(_connect()) as con, con:
        cur = con.execute("INSERT INTO events (scan_id, ts, type, payload) VALUES (?, ?, ?, ?)",
                          (scan_id, ts, type, json.dumps(payload)))
        event_id = cur.lastrowid
    event = {"id": event_id, "scan_id": scan_id, "ts": ts, "type": type, "payload": payload}
    for listener in list(_listeners):
        try:
            listener(event)
        except Exception:  # a broken UI listener must not stop a scan
            log.exception("event listener failed")


def update_scan(scan_id: str, **fields) -> None:
    with _lock, closing(_connect()) as con, con:
        row = con.execute("SELECT fields FROM scans WHERE id = ?", (scan_id,)).fetchone()
        merged = {**(json.loads(row[0]) if row else {}), **fields}
        con.execute("INSERT OR REPLACE INTO scans (id, fields) VALUES (?, ?)", (scan_id, json.dumps(merged)))


def get_scan(scan_id: str) -> dict | None:
    with closing(_connect()) as con:
        row = con.execute("SELECT fields FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return json.loads(row[0]) if row else None


def all_scans() -> list[dict]:
    """Every scan record with its id (the blocklist reads decisions from here)."""
    with closing(_connect()) as con:
        rows = con.execute("SELECT id, fields FROM scans").fetchall()
    return [{"id": i, **json.loads(f)} for i, f in rows]


def events(scan_id: str, after: int = 0) -> list[dict]:
    with closing(_connect()) as con:
        rows = con.execute("SELECT id, ts, type, payload FROM events WHERE scan_id = ? AND id > ? ORDER BY id",
                           (scan_id, after)).fetchall()
    return [{"id": i, "scan_id": scan_id, "ts": ts, "type": t, "payload": json.loads(p)} for i, ts, t, p in rows]
