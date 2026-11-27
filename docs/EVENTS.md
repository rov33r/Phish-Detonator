# Event Contract

Draft. Lanes A and B emit these events with `db.emit(scan_id, type, payload)`. Lane C renders them from the SSE stream `GET /api/scans/{id}/events`. Change this file in its own PR before emitting a new or changed event.

Every SSE message is `{"id": <event id>, "ts": <ISO 8601>, "type": "<type>", "payload": {...}}`. Evidence paths are relative to the scan folder; the app serves them at `/api/scans/{id}/files/<path>`.

| Type | Emitted by | Payload |
|---|---|---|
| `scan_started` | A | `{url, mode, decoy_email}` |
| `plan` | A | `{steps: ["robot visit", "victim visit", "verdict"]}` |
| `sandbox_created` | A | `{visit: "robot" or "victim", container, runtime}` |
| `robot_done` | A | `{final_url, title, screenshot, has_password_field}` |
| `agent_step` | B | `{step, action, ref, reason, url, title, is_login_page, brand_seen}` (`reason` is first person, max 20 words) |
| `screenshot` | B | `{visit, step, path}` |
| `request_seen` | A | `{visit, method, host, url}` |
| `decoy_sent` | B | `{host, url, field: "email" or "password", encoding: "plain", "url" or "base64"}` |
| `probe_seen` | A | `{name}` |
| `sandbox_destroyed` | A | `{visit, container}` |
| `verdict` | B | `{verdict, reasons: [{signal, text, evidence}], password_sent_to, action_taken: "blocked" or "none"}` |
| `evidence_uploaded` | A | `{files: {<path>: <presigned URL>}}` |
| `error` | any | `{where, message}` |

`plan` and `action_taken` are additions to SPEC 10 for the judging focus (visible workflow, agent owns its decision).
