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
| `agent_step` | B | `{step, action, ref, reason, url, title, is_login_page, brand_seen}` (`reason` is first person, max 20 words) |
| `screenshot` | B | `{visit, step, path}` |
| `request_seen` | A | `{visit, method, host, url}` |
| `decoy_sent` | B | `{host, url, field: "email" or "password", encoding: "plain", "url" or "base64"}` |
| `probe_seen` | A | `{visit, name}` |
| `request_blocked` | A | `{visit, host, url, error}` (network lock stopped it; SPEC 5.7, 9.1 stage 5) |
| `sandbox_destroyed` | A | `{visit, container}` |
| `claim_rejected` | B | `{claim, reason}` (code did not find the cited evidence, SPEC 8.4) |
| `verdict` | B | `{verdict, reasons: [{signal, text, evidence}], password_sent_to, action_taken: "blocked" or "none", decided_by: "agent", untested: [text]}` |
| `decision` | C | `{decision: "block" or "release", decided_by: "agent" or "analyst"}` |
| `evidence_uploaded` | A | `{files: {<path>: <presigned URL>}}` |
| `error` | any | `{where, message}` |

Visit labels: `robot`, `victim`, then `<profile>-<n>` for follow-ups (for example `victim_mobile-3`). Cites use `<visit>/<file>:<line>` or `<visit>/step-NN.png`.
