# Event Contract

Draft. Lanes A and B emit these events with `db.emit(scan_id, type, payload)`. Lane C renders them from the SSE stream `GET /api/scans/{id}/events`. Change this file in its own PR before emitting a new or changed event.

Every SSE message is `{"id": <event id>, "ts": <ISO 8601>, "type": "<type>", "payload": {...}}`. Evidence paths are relative to the scan folder; the app serves them at `/api/scans/{id}/files/<path>`.

| Type | Emitted by | Payload |
|---|---|---|
| `scan_started` | A | `{url, mode, decoy_email}` |
| `scan_queued` | A | `{position}` (waiting for a free slot, SPEC 10) |
| `plan` | B | `{hypotheses: [{id, text, status: "open"}], text}` (`text`: one first-person sentence) |
| `hypothesis_update` | B | `{id, status: "open", "supported" or "refuted", reason, evidence: [cite]}` |
| `dispatch` | A | `{visit, profile, tool, reason, round, budget_left: {sandboxes, seconds}}` (`reason` from the investigator, first person) |
| `sandbox_created` | A | `{visit, profile, container, runtime, limits: {memory, cpus, pids, seconds}}` |
| `robot_done` | A | `{final_url, title, screenshot, has_password_field}` |
| `agent_step` | B | `{visit, step, action, ref, reason, url, title, is_login_page, brand_seen, model}` (`reason` is first person, max 20 words) |
| `approval` | B | `{visit, step, action, ref, typed: ["{{DECOY_EMAIL}}", "{{DECOY_PASSWORD}}"], checks: [{name, ok}], decision: "auto_approved" or "denied", reason}` (SPEC 6.6; never the decoy value itself) |
| `screenshot` | B | `{visit, step, path}` |
| `request_seen` | A | `{visit, method, host, url}` |
| `decoy_sent` | B | `{host, url, field: "email" or "password", encoding: "plain", "url" or "base64"}` |
| `probe_seen` | A | `{visit, name}` |
| `request_blocked` | A | `{visit, host, url, error}` (network lock stopped it; SPEC 5.7, 9.1 stage 5) |
| `live_available` | A | `{visit, url}` (MJPEG stream ready, SPEC 11A.1) |
| `sandbox_stats` | A | `{visit, mem_mb, mem_limit_mb, cpu_pct, pids}` (every 1 s, SPEC 11A.5) |
| `host_stats` | A | `{load_1m, mem_used_pct}` (every 2 s while a scan runs) |
| `resource_limit_hit` | A | `{visit, kind: "memory" or "time", peak_mb, limit_mb}` (SPEC 11A.4) |
| `sandbox_destroyed` | A | `{visit, container, lifetime_s, peak_mem_mb}` |
| `claim_rejected` | B | `{claim, reason}` (code did not find the cited evidence, SPEC 8.4) |
| `verdict` | B | `{verdict, reasons: [{signal, text, evidence}], password_sent_to, action_taken: "blocked" or "none", decided_by: "agent", untested: [text]}` |
| `decision` | C | `{decision: "block" or "release", decided_by: "agent" or "analyst"}` |
| `evidence_uploaded` | A | `{files: {<path>: <presigned URL>}}` |
| `report_ready` | C | `{report_url, manifest_sha256}` (signed report, SPEC 11A.3) |
| `error` | any | `{where, message}` |

Visit labels: `robot`, `victim`, then `<profile>-<n>` for follow-ups (for example `victim_mobile-3`). Cites use `<visit>/<file>:<line>` or `<visit>/step-NN.png`.
