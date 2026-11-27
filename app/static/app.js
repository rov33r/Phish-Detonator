const byId = (id) => document.getElementById(id);
const form = byId("scan-form");
const urlInput = byId("url");
const startButton = byId("scan-button");
const presets = [...document.querySelectorAll("[data-url]")];
const workspace = document.querySelector(".workspace");
const initialWorkspace = workspace.cloneNode(true);
const counterIds = ["created", "destroyed", "requests", "blocked-count", "limits", "probes"];
const hypothesisRows = new Map();
const sandboxRows = new Map();
const stepReasons = new Map();
const passwordHosts = new Set();
let scanId;
let source;
let lastEvent = 0;
let startTime;

function status(text, state) {
  byId("status").textContent = text;
  byId("status").dataset.state = state;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function appendRow(listId, ...children) {
  const list = byId(listId);
  const row = element("li", "");
  row.append(...children);
  list.append(row);
  list.hidden = false;
  return row;
}

function increment(id) {
  const count = byId(id);
  count.textContent = Number(count.textContent) + 1;
}

function evidenceUrl(cite) {
  const path = cite.replace(/:\d+$/, "");
  return `/api/scans/${scanId}/files/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function citeLinks(cites) {
  return cites.map((cite) => {
    const link = element("a", cite);
    link.href = evidenceUrl(cite);
    link.target = "_blank";
    link.rel = "noopener";
    return link;
  });
}

function capture(id, path, description) {
  const image = element("img", "");
  image.alt = description;
  image.src = evidenceUrl(path);
  image.addEventListener("error", () => {
    if (image.isConnected) image.replaceWith(element("span", "Capture unavailable"));
  });
  byId(id).replaceChildren(image);
}

function activity(event, title, detail = "") {
  const seconds = Math.max(0, Math.round((Date.parse(event.ts) - startTime) / 1000));
  const time = element("time", `+${seconds}s`);
  time.dateTime = event.ts;
  byId("timeline-empty").hidden = true;
  const row = appendRow("timeline", time, element("strong", title));
  if (detail) row.append(element("p", detail, "subtle"));
}

function recordDecision({ decision, decided_by }) {
  const text = decision === "block" ? "Blocked" : "Released";
  byId("decision").textContent = `${text} by ${decided_by === "agent" ? "agent" : "analyst"}`;
  for (const button of byId("decisions").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.decision === decision));
  }
}

function sandboxRow(visit) {
  if (!sandboxRows.has(visit)) sandboxRows.set(visit, appendRow("meters"));
  return sandboxRows.get(visit);
}

const render = {
  scan_started(event, p) {
    byId("email").textContent = p.decoy_email;
    byId("password").textContent = "••••••••••••••••";
    activity(event, "Scan started", p.url);
  },
  scan_queued(event, p) {
    status(`Queued · position ${p.position}`, "running");
    activity(event, "Scan queued");
  },
  plan(event, p) {
    byId("plan").textContent = p.text;
    for (const item of p.hypotheses) {
      const title = element("div", "", "row-title");
      const state = element("span", "Open", "subtle");
      const detail = element("p", "", "subtle");
      title.append(element("strong", `${item.id} · ${item.text}`), state);
      const row = appendRow("hypotheses", title, detail);
      hypothesisRows.set(item.id, { row, state, detail });
    }
  },
  hypothesis_update(event, p) {
    const entry = hypothesisRows.get(p.id);
    if (!entry) return;
    entry.state.textContent = p.status[0].toUpperCase() + p.status.slice(1);
    entry.detail.textContent = p.reason;
    entry.row.querySelectorAll("a").forEach((link) => link.remove());
    entry.row.append(...citeLinks(p.evidence));
  },
  dispatch(event, p) {
    activity(event, `Round ${p.round} · Dispatch ${p.visit}`, p.reason);
  },
  sandbox_created(event, p) {
    increment("created");
    activity(event, `Sandbox created · ${p.visit}`, `${p.runtime} · ${p.limits.memory} MB memory cap`);
  },
  robot_done(event, p) {
    capture("robot-capture", p.screenshot, `Scanner capture showing ${p.title}`);
    byId("robot-url").textContent = p.final_url;
    activity(event, "Scanner capture received", p.title);
  },
  agent_step(event, p) {
    stepReasons.set(`${p.visit}:${p.step}`, p.reason);
    byId("agent-step").textContent = p.reason;
    activity(event, `${p.visit} · Step ${p.step} · ${p.action}`, `${p.reason} · ${p.model}`);
  },
  approval(event, p) {
    const outcome = p.decision === "auto_approved" ? "Auto-approved" : "Denied";
    activity(event, `${p.visit} · Step ${p.step} · ${outcome}`, p.reason);
  },
  screenshot(event, p) {
    const frames = byId("frames");
    const label = `${p.visit} · Step ${p.step}`;
    const caption = stepReasons.get(`${p.visit}:${p.step}`) ?? "Screenshot received.";
    const show = () => {
      for (const button of frames.children) button.setAttribute("aria-pressed", "false");
      frame.setAttribute("aria-pressed", "true");
      byId("agent-step").textContent = caption;
      capture("victim-capture", p.path, `Victim capture from ${label}`);
    };
    const frame = element("button", label);
    frame.type = "button";
    frame.addEventListener("click", show);
    frames.append(frame);
    frames.hidden = false;
    show();
  },
  request_seen() { increment("requests"); },
  probe_seen() { increment("probes"); },
  decoy_sent(event, p) {
    if (p.field !== "password" || passwordHosts.has(p.host)) return;
    passwordHosts.add(p.host);
    byId("trail-empty").hidden = true;
    appendRow("trail", element("strong", p.host));
    activity(event, "Decoy password observed", p.host);
  },
  request_blocked(event, p) {
    increment("blocked-count");
    byId("blocked-empty").hidden = true;
    const title = element("div", "", "row-title");
    const state = element("strong", "Blocked");
    state.dataset.tone = "risk";
    title.append(element("strong", p.host), state);
    appendRow("blocked", title, element("p", p.error, "subtle"));
  },
  sandbox_stats(event, p) {
    const meter = element("meter", "");
    meter.max = p.mem_limit_mb;
    meter.value = p.mem_mb;
    meter.setAttribute("aria-label", `${p.visit} memory used`);
    sandboxRow(p.visit).replaceChildren(
      element("strong", p.visit),
      meter,
      element("p", `${p.mem_mb} / ${p.mem_limit_mb} MB · ${p.cpu_pct}% CPU · ${p.pids} PIDs`, "subtle"),
    );
  },
  host_stats(event, p) {
    byId("host").hidden = false;
    byId("host").textContent = `Host load ${p.load_1m} · ${p.mem_used_pct}% memory`;
  },
  resource_limit_hit(event, p) {
    increment("limits");
    byId("blocked-empty").hidden = true;
    appendRow("blocked", element("strong", `${p.visit} · ${p.kind} limit reached`));
    activity(event, "Resource limit reached", `${p.peak_mb} / ${p.limit_mb} MB`);
  },
  sandbox_destroyed(event, p) {
    increment("destroyed");
    sandboxRow(p.visit).replaceChildren(
      element("strong", `${p.visit} · Destroyed`),
      element("p", `${p.lifetime_s}s lifetime · ${p.peak_mem_mb} MB peak`, "subtle"),
    );
    activity(event, `Sandbox destroyed · ${p.visit}`);
  },
  claim_rejected(event, p) {
    appendRow("rejected", element("s", p.claim), element("p", p.reason, "subtle"));
  },
  verdict(event, p) {
    const stamp = byId("verdict");
    stamp.textContent = p.verdict;
    stamp.dataset.tone = { Scam: "risk", Suspicious: "warn", "No evidence found": "good" }[p.verdict];
    for (const reason of p.reasons) {
      appendRow("reasons", element("strong", `${reason.signal} · ${reason.text}`), ...citeLinks(reason.evidence));
    }
    if (p.untested.length) {
      byId("untested").hidden = false;
      byId("untested").textContent = `Untested · ${p.untested.join(", ")}`;
    }
    byId("decisions").hidden = false;
    if (p.action_taken === "blocked") recordDecision({ decision: "block", decided_by: p.decided_by });
    else byId("decision").textContent = "No automatic action taken.";
    activity(event, "Verdict reached", p.verdict);
    stop("Investigation complete", "complete");
  },
  decision(event, p) { recordDecision(p); },
  error(event, p) { stop(`${p.where}: ${p.message}`, "error"); },
};

function stop(message, state) {
  source?.close();
  status(message, state);
  startButton.disabled = false;
  startButton.textContent = "Start scan";
}

function reset() {
  source?.close();
  document.querySelector(".workspace").replaceWith(initialWorkspace.cloneNode(true));
  for (const id of counterIds) byId(id).textContent = "0";
  for (const cache of [hypothesisRows, sandboxRows, stepReasons, passwordHosts]) cache.clear();
  lastEvent = 0;
  scanId = undefined;
  byId("case-id").textContent = "";
}

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check the request and try again.");
  return data;
}

function selectPreset() {
  for (const button of presets) {
    button.setAttribute("aria-pressed", String(button.dataset.url === urlInput.value));
  }
}
for (const button of presets) {
  button.addEventListener("click", () => {
    urlInput.value = button.dataset.url;
    selectPreset();
    urlInput.focus();
  });
}
urlInput.addEventListener("input", selectPreset);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (startButton.disabled) return;
  reset();
  startButton.disabled = true;
  startButton.textContent = "Scanning…";
  status("Starting simulated investigation", "running");
  try {
    const result = await post("/api/scans", Object.fromEntries(new FormData(form)));
    scanId = result.scan_id;
    byId("case-id").textContent = `Scan ${scanId.slice(0, 8)}`;
    const stream = new EventSource(`/api/scans/${scanId}/events`);
    source = stream;
    let failures = 0;
    stream.onopen = () => status("Investigation running", "running");
    stream.onmessage = ({ data }) => {
      failures = 0;
      const entry = JSON.parse(data);
      if (entry.id <= lastEvent) return;
      if (!lastEvent) startTime = Date.parse(entry.ts);
      lastEvent = entry.id;
      render[entry.type]?.(entry, entry.payload);
    };
    stream.onerror = () => {
      failures += 1;
      if (stream.readyState === EventSource.CLOSED || failures >= 3) {
        stop("The event stream ended early. Start the scan again to retry.", "error");
      } else {
        status("Reconnecting to the investigation…", "running");
      }
    };
  } catch (error) {
    stop(error.message, "error");
  }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-decision]");
  if (!button || !scanId) return;
  const activeScan = scanId;
  const buttons = [...byId("decisions").querySelectorAll("button")];
  for (const control of buttons) control.disabled = true;
  try {
    const decision = await post(`/api/scans/${activeScan}/decision`, { decision: button.dataset.decision });
    if (activeScan === scanId) recordDecision(decision);
  } catch (error) {
    if (activeScan === scanId) byId("decision").textContent = error.message;
  } finally {
    for (const control of buttons) control.disabled = false;
  }
});

fetch("/api/health")
  .then((response) => response.json())
  .then(({ demo }) => {
    if (!demo && !scanId && !startButton.disabled) status("Simulated scans are disabled", "error");
  })
  .catch(() => status("Could not check service status", "error"));
