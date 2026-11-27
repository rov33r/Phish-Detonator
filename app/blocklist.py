"""Blocklist: the agent's block (or the analyst's override) has an effect beyond the scan page.

Built on the scans table, no new storage: a link's status is the latest decision recorded for it.
Blocked links show a banner when they are scanned again and are flagged in a pasted email.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from app import db


def normalize(url: str) -> str:
    """Same link, same key: lower-case scheme and host, no fragment, no trailing slash on the path."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _decided() -> list[dict]:
    """Scans with a decision, newest decision first."""
    rows = [s for s in db.all_scans() if s.get("decision") in ("block", "release") and s.get("url")]
    return sorted(rows, key=lambda s: s.get("decided_at") or "", reverse=True)


def _entry(scan: dict) -> dict:
    return {"url": scan["url"], "status": "blocked" if scan["decision"] == "block" else "released",
            "scan_id": scan["id"], "verdict": scan.get("verdict"), "decided_by": scan.get("decided_by"),
            "decided_at": scan.get("decided_at")}


def entries() -> list[dict]:
    """One row per link (its latest decision), newest first."""
    seen, out = set(), []
    for scan in _decided():
        key = normalize(scan["url"])
        if key not in seen:
            seen.add(key)
            out.append(_entry(scan))
    return out


def lookup(url: str, *, exclude: str | None = None) -> dict | None:
    """The latest decision for this link, or None if it was never decided."""
    key = normalize(url)
    return next((_entry(s) for s in _decided() if s["id"] != exclude and normalize(s["url"]) == key), None)
