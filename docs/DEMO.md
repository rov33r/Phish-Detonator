# Demo Run Sheet

Deadline 19:00. Script and timings: SPEC section 17. Architecture: `docs/ARCHITECTURE.md`.

## What needs Vultr

| Item | Owner | Status |
|---|---|---|
| VM (Stockholm), firewall, gVisor, network lock | A | bootstrap and netlock merged |
| Sandbox image built on the VM | A | image merged; build on the VM |
| `db.py`, orchestrator, robot script (`bot.mjs`) | A | open |
| Mobile touch fix (issue #22) | A | open, needed for the mobile preset |
| Caddy, public URL, systemd | A | open |
| Inference key in the VM `.env` (`PD_MODEL=mimo-v2.6-pro`, `PD_MODEL_FALLBACK` and `PD_VISION_MODEL=qwen3.8-flash-next`) | A | key works |
| Object Storage bucket `phishdet-evidence` | A | open |
| UI on real events, presets, scoreboard page, email paste | C | PR #24 open |

## Presets (in this order)

| Preset | URL | Expected |
|---|---|---|
| Legit Vexalo | `http://vexalo.<IP>.sslip.io/` | No evidence found; H4 supported; probes shown as context |
| Phishing kit | `http://vexalo-docs.<IP>.nip.io/` | Scam, blocked; robot saw news; 3 blocked requests; password trail to cdn-metrics; H4 refuted |
| Mobile-only kit | `http://vexalo-docs.<IP>.nip.io/m/` | Investigator: "I send a phone"; Scam, blocked; H3 supported |
| Resource bomb | `http://vexalo-docs.<IP>.nip.io/bomb` | Memory bar hits 2 GB, visit killed, host flat; Suspicious with M5 |
| Scoreboard | `POST /api/scoreboard` | Robot `bot: true`, victim `bot: false` |

## Lines that land with judges

- Before the verdict, point at H4: "Before blocking, the agent tries to prove the page is a legitimate login. It checks where the password went: not the brand's site, not a login provider. Refuted." This answers false positives before anyone asks.
- Point at a rejected claim if one appears: "The agent made a claim the evidence did not support, and code threw it out."
- On the approval gate card: "The agent's one irreversible action, submitting a form, passes a gate. It only ever holds placeholders."

## Recording plan

1. As soon as a preset works on the VM, run it and pin the scan (`PD_DEMO_SCANS`) as the safety net.
2. Until then, laptop runs are the fallback: `scripts/dev_scan.py kit|mobile|legit` with evidence in `scans/<id>/`.
3. Record the video from the public URL with live runs; cut to pinned runs only if a live run misbehaves.
4. Video must show at least one containment moment: the three blocked requests and the resource bomb.

## Submission checklist (SPEC 18)

- [ ] Public GitHub repo with README (setup, architecture, limits) linking `docs/ARCHITECTURE.md`
- [ ] Backend on the Vultr VM, all model calls through Vultr Serverless Inference
- [ ] Public demo URL
- [ ] Demo video with the containment moments
- [ ] Architecture screenshot (the diagrams in `docs/ARCHITECTURE.md`)
- [ ] "How did you use Vultr?" answer (products table in `docs/ARCHITECTURE.md`)
- [ ] All three team members added; event: Vultr Agent Runtime Hackathon
