const byId = (id) => document.getElementById(id);
const themeToggle = byId("theme-toggle");
const themeRoot = document.documentElement;

function syncThemeControl() {
  themeToggle.textContent = themeRoot.dataset.theme === "dark" ? "Light mode" : "Dark mode";
}

themeToggle.addEventListener("click", () => {
  const theme = themeRoot.dataset.theme === "dark" ? "light" : "dark";
  themeRoot.dataset.theme = theme;
  syncThemeControl();
  try {
    localStorage.setItem("phishdet-theme", theme);
  } catch {
    // The theme still works when browser storage is disabled.
  }
});
syncThemeControl();

const form = byId("scan-form");
const urlInput = byId("url");
const startButton = byId("scan-button");
const presets = [...document.querySelectorAll("[data-url]")];
const workspace = document.querySelector(".workspace");
const initialWorkspace = workspace.cloneNode(true);
const counterIds = ["created", "destroyed", "blocked-count", "limits", "probes"];
const hypothesisRows = new Map();
const blockedRows = new Map();
const roundCards = new Map();
const visitedStages = new Set();
const hypothesisChips = {
  open: "Checking", supported: "Confirmed", refuted: "Ruled out", untested: "Not tested",
};
const sandboxRows = new Map();
const stepReasons = new Map();
const observedHosts = new Map();
const thirdPartyHosts = new Set();
const latestShots = new Map();
const autoAnswered = new Set();
const approvalOutcomes = {
  auto_approved: "Auto-approved by the code policy",
  denied: "Denied by the code policy",
  approved_by_analyst: "Approved by analyst",
  denied_by_analyst: "Denied by analyst",
  timed_out: "No answer in time; the code policy approved",
};
let scanId;
let source;
let lastEvent = 0;
let startTime;
let activeResult;
let playback = false;
let captureOnly = false;
let liveService = false;
let limitHit = false;
let approveRest = false;
let pendingApproval;

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

const captureVisits = ["robot", "victim"];
const stages = [...document.querySelectorAll("[data-phase]")];

function stageNote(phase, text) {
  const stage = stages.find((item) => item.dataset.phase === phase);
  if (stage) stage.querySelector(".stage-note").textContent = text;
}

// Stages can repeat (a follow-up after an approval), so completion tracks visits, not position.
function setPhase(phase) {
  const current = stages.find((stage) => stage.dataset.phase === phase);
  const previous = stages.find((stage) => stage.hasAttribute("aria-current"));
  if (current) visitedStages.add(phase);
  const end = phase === "complete" || phase === "verdict";
  const reached = current ? stages.indexOf(current) : end ? stages.length : -1;
  stages.forEach((stage, index) => {
    const visited = visitedStages.has(stage.dataset.phase);
    stage.dataset.complete = String(visited && stage !== current);
    stage.dataset.skipped = String(!visited && index < reached);
    if (stage === current) stage.setAttribute("aria-current", "step");
    else stage.removeAttribute("aria-current");
  });
  if (!current || current === previous) return;
  const target = byId(current.dataset.target);
  if (target && !target.hidden) {
    const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
  }
}

function showCapturePlaceholder(visit, message, loading) {
  const placeholder = byId(`pending-${visit}`);
  placeholder.hidden = false;
  placeholder.querySelector(".capture-skeleton").hidden = !loading;
  byId(`pending-${visit}-message`).textContent = message;
  byId(`compare-${visit}`).hidden = true;
}

function updateComparisonState() {
  const pending = captureVisits.some((visit) => ["true", "image"].includes(byId(`pending-${visit}`).dataset.loading));
  const available = captureVisits.filter((visit) => !byId(`compare-${visit}`).hidden).length;
  byId("compare-stage").setAttribute("aria-busy", String(pending));
  byId("comparison-state").textContent = pending ? "Gathering captures" :
    available === 2 ? "Scan captures" : available === 1 ? "One capture available" : "No captures available";
}

function capture(visit, path, description) {
  const image = byId(`compare-${visit}`);
  const placeholder = byId(`pending-${visit}`);
  placeholder.dataset.loading = "image";
  showCapturePlaceholder(visit, "Loading capture", true);
  updateComparisonState();
  image.alt = description;
  image.onload = () => {
    if (!image.isConnected) return;
    placeholder.dataset.loading = "false";
    placeholder.hidden = true;
    image.hidden = false;
    updateComparisonState();
  };
  image.onerror = () => {
    if (!image.isConnected) return;
    placeholder.dataset.loading = "false";
    showCapturePlaceholder(visit, "Capture unavailable", false);
    updateComparisonState();
  };
  const url = evidenceUrl(path);
  if (image.getAttribute("src") === url && image.complete && image.naturalWidth > 0) {
    image.onload();
  } else {
    image.src = url;
  }
}

function setTextLoading(section, loading) {
  byId(`${section}-skeleton`).hidden = !loading;
  byId(section).hidden = loading;
  byId(section).parentElement.setAttribute("aria-busy", String(loading));
}

function startLoading() {
  setPhase("plan");
  setTextLoading("plan", true);
  setTextLoading("verdict", true);
  for (const visit of captureVisits) {
    byId(`pending-${visit}`).dataset.loading = "true";
    showCapturePlaceholder(visit, visit === "robot" ? "Waiting for scanner capture" : "Waiting for victim capture", true);
  }
  updateComparisonState();
}

function finishLoading(state) {
  setPhase(state === "complete" ? "complete" : "");
  setTextLoading("plan", false);
  setTextLoading("verdict", false);
  for (const visit of captureVisits) {
    const placeholder = byId(`pending-${visit}`);
    const loading = placeholder.dataset.loading;
    if (loading === "false" || (loading === "image" && state === "complete")) continue;
    if (loading === "image") {
      const image = byId(`compare-${visit}`);
      image.onload = null;
      image.onerror = null;
    }
    showCapturePlaceholder(visit, state === "complete" ? "No capture recorded" : "Scan stopped", false);
    placeholder.dataset.loading = "false";
  }
  updateComparisonState();
}

document.addEventListener("click", (event) => {
  const control = event.target.closest("[data-view][type=button]");
  if (!control) return;
  byId("compare-stage").dataset.view = control.dataset.view;
  for (const button of control.parentElement.querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button === control));
  }
});

function activity(event, title, detail = "") {
  const seconds = Math.max(0, Math.round((Date.parse(event.ts) - startTime) / 1000));
  const time = element("time", `+${seconds}s`);
  time.dateTime = event.ts;
  byId("timeline-empty").hidden = true;
  const row = appendRow("timeline", time, element("strong", title));
  if (detail) row.append(element("p", detail, "subtle"));
  return row;
}

function recordDecision({ decision, decided_by }) {
  const text = decision === "block" ? "Blocked" : "Released";
  byId("decision").textContent = `${text} by ${decided_by === "agent" ? "agent" : "analyst"}`;
  for (const button of byId("decisions").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.decision === decision));
  }
  refreshBlocklist();
}

function clock(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function scanLink(id, text) {
  const link = element("a", text);
  link.href = `/replay/${encodeURIComponent(id)}`;
  return link;
}

// Blocked links are rendered as text, never as links to the suspicious page.
function refreshBlocklist() {
  fetch("/api/blocklist")
    .then((response) => response.ok ? response.json() : Promise.reject(new Error("unavailable")))
    .then(({ entries }) => {
      const blocked = (entries ?? []).filter((entry) => entry.status === "blocked");
      byId("blocklist").replaceChildren();
      for (const entry of blocked) {
        const who = entry.decided_by === "agent" ? "agent" : "analyst";
        const detail = [`Blocked by ${who}`, entry.verdict, clock(entry.decided_at)].filter(Boolean).join(" · ");
        const meta = element("p", `${detail} · `, "subtle");
        meta.append(scanLink(entry.scan_id, "view scan"));
        appendRow("blocklist", element("code", entry.url), meta);
      }
      byId("blocklist-count").textContent = `(${blocked.length})`;
      byId("blocklist-empty").hidden = blocked.length > 0;
      byId("blocklist").hidden = blocked.length === 0;
      byId("blocklist-panel").hidden = false;
    })
    .catch(() => { byId("blocklist-panel").hidden = true; });
}

function sandboxRow(visit) {
  if (!sandboxRows.has(visit)) sandboxRows.set(visit, appendRow("meters"));
  return sandboxRows.get(visit);
}

function setVisitState(visit, text, state) {
  const family = visit?.startsWith("robot") ? "scanner" : visit?.startsWith("victim") ? "victim" : null;
  if (!family) return;
  const badge = byId(`${family}-state`);
  if (state === "finished" && badge.dataset.visit && badge.dataset.visit !== visit) return;
  badge.dataset.visit = visit;
  badge.dataset.state = state;
  badge.textContent = text;
}

function setCheck(name, text, state) {
  const check = byId(`check-${name}`);
  if (check.dataset.state === state && check.querySelector("span").textContent === text) return;
  check.dataset.state = state;
  check.querySelector("span").textContent = text;
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    check.animate([{ opacity: .6, transform: "translateY(2px)" }, { opacity: 1, transform: "translateY(0)" }],
                  { duration: 230, easing: "ease-out" });
  }
}

function summarizeChecks(payload) {
  const mismatch = payload.reasons.some((reason) => reason.signal === "S2");
  setCheck("cloak", mismatch ? "Scanner and victim saw different pages" : "No page mismatch cited",
           mismatch ? "flagged" : "finished");
  const destinations = payload.password_sent_to;
  if (destinations?.length && payload.reasons.some((reason) => reason.signal === "S1")) {
    setCheck("password", `Third-party destination: ${destinations.join(", ")}`, "flagged");
  } else if ([...observedHosts.values()].some((fields) => fields.has("password"))) {
    setCheck("password", "Password observed. No third-party destination cited.", "finished");
  } else {
    setCheck("password", "No password submission observed", "finished");
  }
  if (byId("check-containment").dataset.state === "waiting") {
    setCheck("containment", "No blocked activity observed", "finished");
  }
}

function renderTrail() {
  const list = byId("trail");
  list.replaceChildren();
  for (const host of thirdPartyHosts) {
    if (!observedHosts.has(host)) observedHosts.set(host, new Set(["password"]));
  }
  for (const [host, fields] of observedHosts) {
    const label = element("strong", host);
    if (thirdPartyHosts.has(host)) label.dataset.tone = "risk";
    const detail = thirdPartyHosts.has(host) ? "Third-party password destination" :
      fields.has("password") ? "Password observed" : "Email observed";
    appendRow("trail", label, element("p", detail, "subtle"));
  }
  byId("trail-empty").hidden = observedHosts.size > 0;
  list.hidden = observedHosts.size === 0;
}

function renderEmailTriage({ links, flags }) {
  const section = byId("email-triage");
  section.hidden = false;
  for (const id of ["email-links", "email-flags"]) byId(id).replaceChildren();
  byId("email-triage-summary").textContent = links.length
    ? `${links.length} ${links.length === 1 ? "link" : "links"} found`
    : "No web links found.";
  for (const link of links) {
    const title = element("strong", link.url);
    if (link.blocklist?.status === "blocked") title.append(element("span", "Blocked", "blocked-tag"));
    const row = appendRow("email-links", title);
    if (link.shown_text && link.shown_text !== link.url) row.append(element("p", link.shown_text, "subtle"));
    if (link.picked) row.append(element("p", link.reason || "Selected for investigation", "subtle"));
  }
  for (const flag of flags) appendRow("email-flags", element("p", flag.detail, "subtle"));
  byId("email-links").hidden = links.length === 0;
  byId("email-flags").hidden = flags.length === 0;
}

const render = {
  scan_started(event, p) {
    if (playback && p.url) byId("submitted-url").textContent = p.url;
    if (captureOnly) {
      status("Capturing public page", "running");
      return;
    }
    byId("email").textContent = p.decoy_email;
    byId("password").textContent = "••••••••••••••••";
    activity(event, "Scan started", p.url);
  },
  email_triage(event, p) { renderEmailTriage(p); },
  scan_queued(event, p) {
    status(`Queued · position ${p.position}`, "running");
    activity(event, "Scan queued");
  },
  plan(event, p) {
    setTextLoading("plan", false);
    byId("plan").textContent = p.text;
    for (const item of p.hypotheses) {
      const title = element("div", "", "row-title");
      const state = element("span", "", "chip");
      const detail = element("p", "", "subtle");
      title.append(element("strong", item.text), state);
      const row = appendRow("hypotheses", title, detail);
      hypothesisRows.set(item.id, { row, state, detail });
      setHypothesisChip(item.id, "open");
    }
    stageNote("plan", `${p.hypotheses.length} ${p.hypotheses.length === 1 ? "question" : "questions"}`);
    setPhase("captures");
  },
  hypothesis_update(event, p) {
    if (p.id === "H1" && p.status === "supported") {
      setCheck("cloak", "Page mismatch reported. Checking the evidence.", "observed");
    }
    const entry = hypothesisRows.get(p.id);
    if (!entry) return;
    setHypothesisChip(p.id, p.status);
    entry.detail.textContent = p.reason;
    entry.row.querySelectorAll("a").forEach((link) => link.remove());
    entry.row.append(...citeLinks(p.evidence));
    if (p.id === "H4" && p.status === "refuted") {
      entry.row.dataset.hypothesis = "refuted-legitimate";
      byId("legitimate-check").hidden = false;
      activity(event, "Legitimate login ruled out", p.reason);
    }
  },
  dispatch(event, p) {
    setVisitState(p.visit, "Dispatched", "running");
    const round = p.round ? `Round ${p.round} · ` : "";
    activity(event, `${round}Dispatch ${p.visit}`, p.reason);
    roundCard(p);
    if (p.round > 1) {
      stageNote("followups", `Round ${p.round} · ${browserLabel(p.visit).toLowerCase()}`);
      setPhase("followups");
    } else {
      stageNote("captures", "Scanner and desktop browser");
    }
  },
  sandbox_created(event, p) {
    setPhase("captures");
    increment("created");
    setVisitState(p.visit, "Browser started", "running");
    activity(event, `Sandbox created · ${p.visit}`, `${p.runtime} · ${p.limits.memory} MB memory cap`);
  },
  robot_done(event, p) {
    setVisitState(p.visit ?? "robot", "Captured", captureOnly ? "finished" : "running");
    capture("robot", p.screenshot, `${captureOnly ? "Public-page screenshot" : "Scanner capture"} showing ${p.title}`);
    byId("robot-url").textContent = p.final_url;
    activity(event, "Scanner capture received", p.title);
    if (captureOnly) {
      byId("verdict").textContent = "Screenshot captured";
      byId("decision").textContent = "Captured the public HTML with scripts and external assets disabled. No phishing verdict was made.";
      activeResult = "Screenshot captured";
      stop("Capture complete", "complete");
      const currentId = scanId;
      fetch(`/api/scans/${currentId}`)
        .then((response) => response.ok ? response.json() : null)
        .then((record) => {
          if (currentId !== scanId || !record) return;
          if (record.access_gate === "cloudflare") {
            byId("verdict").textContent = "Sign-in required";
            activeResult = "Sign-in required";
            byId("decision").textContent = "The public link redirected to Cloudflare Access. This screenshot shows the sign-in page. The page behind it was not inspected.";
            return;
          }
          if (!(record.http_status >= 400)) return;
          const status = record.http_status;
          const label = status === 403 ? "Access denied" : `Site returned HTTP ${status}`;
          byId("verdict").textContent = label;
          activeResult = label;
          byId("decision").textContent = `The site returned HTTP ${status}. The screenshot shows the server’s response. No phishing verdict was made.`;
        })
        .catch(() => {});
    }
  },
  agent_step(event, p) {
    setVisitState(p.visit, `Step ${p.step}`, "running");
    stepReasons.set(`${p.visit}:${p.step}`, p.reason);
    byId("agent-step").textContent = p.reason;
    activity(event, `${p.visit} · Step ${p.step} · ${p.action}`, `${p.reason} · ${p.model}`);
  },
  approval_requested(event, p) {
    byId("approval-stage").hidden = false;
    stageNote("approval", `Waiting · ${p.host}`);
    setPhase("approval");
    if (approveRest && !playback) {
      autoAnswered.add(p.visit);
      stageNote("approval", "Auto-approved by you");
      answerApproval(p.visit, "approve");
    } else {
      openApprovalBanner(p);
    }
    activity(event, `${p.visit} · Step ${p.step} · Approval requested`, `Submit on ${p.host || "this page"}`);
  },
  approval(event, p) {
    closeApproval(p.visit);
    const outcome = autoAnswered.has(p.visit) && p.decision === "approved_by_analyst"
      ? "Auto-approved by you" : approvalOutcomes[p.decision] ?? p.decision;
    byId("approval-stage").hidden = false;
    appendRow("approval-outcomes", element("strong", `${browserLabel(p.visit)} · ${outcome}`), element("span", p.reason ?? "", "subtle"));
    const denied = p.decision === "denied" || p.decision === "denied_by_analyst";
    setVisitState(p.visit, denied ? "Submit denied" : "Submit approved", "running");
    stageNote("approval", outcome);
    // An auto-approval has no request, so record the stage as passed without moving focus to it.
    visitedStages.add("approval");
    setPhase(stages.find((stage) => stage.hasAttribute("aria-current"))?.dataset.phase ?? "approval");
    activity(event, `${p.visit} · Step ${p.step} · ${outcome}`, p.reason);
  },
  screenshot(event, p) {
    latestShots.set(p.visit, p.path);
    if (pendingApproval === p.visit) showApprovalShot(p.visit);
    const frames = byId("frames");
    const label = `${p.visit} · Step ${p.step}`;
    const caption = stepReasons.get(`${p.visit}:${p.step}`) ?? "Screenshot received.";
    const show = () => {
      for (const button of frames.children) button.setAttribute("aria-pressed", "false");
      frame.setAttribute("aria-pressed", "true");
      byId("agent-step").textContent = caption;
      capture("victim", p.path, `Victim capture from ${label}`);
    };
    const frame = element("button", label);
    frame.type = "button";
    frame.addEventListener("click", show);
    frames.append(frame);
    frames.hidden = false;
    show();
  },
  probe_seen() { increment("probes"); },
  decoy_sent(event, p) {
    if (!observedHosts.has(p.host)) observedHosts.set(p.host, new Set());
    const fields = observedHosts.get(p.host);
    if (fields.has(p.field)) return;
    fields.add(p.field);
    if (p.field === "password") setCheck("password", `Decoy password observed at ${p.host}`, "observed");
    renderTrail();
    activity(event, `Decoy ${p.field} observed`, p.host);
  },
  request_blocked(event, p) {
    increment("blocked-count");
    const total = Number(byId("blocked-count").textContent);
    setCheck("containment", `${total} blocked ${total === 1 ? "request" : "requests"}`, "flagged");
    byId("blocked-empty").hidden = true;
    const existing = blockedRows.get(p.host);
    if (existing) {
      existing.count += 1;
      existing.state.textContent = `Blocked ×${existing.count}`;
      return;
    }
    const title = element("div", "", "row-title");
    const state = element("strong", "Blocked");
    state.dataset.tone = "risk";
    title.append(element("strong", p.host), state);
    appendRow("blocked", title, element("p", p.error, "subtle"));
    blockedRows.set(p.host, { state, count: 1 });
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
    limitHit = true;
    for (const row of byId("timeline").querySelectorAll("[data-container-error]")) row.remove();
    setRoundState(p.visit, `${p.kind[0].toUpperCase()}${p.kind.slice(1)} limit reached`, "risk");
    setCheck("containment", `Sandbox hit its ${p.kind} limit`, "flagged");
    byId("blocked-empty").hidden = true;
    appendRow("blocked", element("strong", `${p.visit} · ${p.kind} limit reached`));
    activity(event, "Resource limit reached", `${p.peak_mb} / ${p.limit_mb} MB`);
  },
  sandbox_destroyed(event, p) {
    increment("destroyed");
    setVisitState(p.visit, "Sandbox closed", "finished");
    setRoundState(p.visit, "Sandbox closed", "done");
    // A zero peak means the stats watcher never sampled, not that the browser used no memory.
    const peak = p.peak_mem_mb > 0 ? ` · ${p.peak_mem_mb} MB peak` : "";
    sandboxRow(p.visit).replaceChildren(
      element("strong", `${p.visit} · Destroyed`),
      element("p", `${p.lifetime_s}s lifetime${peak}`, "subtle"),
    );
    activity(event, `Sandbox destroyed · ${p.visit}`);
  },
  claim_rejected(event, p) {
    appendRow("rejected", element("s", p.claim), element("p", p.reason, "subtle"));
  },
  verdict(event, p) {
    summarizeChecks(p);
    thirdPartyHosts.clear();
    for (const host of p.password_sent_to) thirdPartyHosts.add(host);
    renderTrail();
    if (thirdPartyHosts.size && p.reasons.some((reason) => reason.signal === "S1")) {
      const finding = byId("credential-finding");
      finding.hidden = false;
      finding.textContent = `Credential theft confirmed · Decoy password sent to ${[...thirdPartyHosts].join(", ")}.`;
    }
    const stamp = byId("verdict");
    const label = p.verdict;
    stamp.textContent = label;
    activeResult = label;
    stamp.dataset.tone = { Phishing: "risk", Suspicious: "warn", Inconclusive: "neutral", "No evidence found": "good" }[label];
    stageNote("verdict", label);
    setPhase("verdict");
    for (const reason of p.reasons) {
      appendRow("reasons", element("strong", `${reason.signal === "S3" ? "Context · " : ""}${reason.text}`), ...citeLinks(reason.evidence));
    }
    for (const [id, entry] of hypothesisRows) if (entry.status === "open") setHypothesisChip(id, "untested");
    if (p.untested.length) {
      byId("untested").hidden = false;
      byId("untested").textContent = `Untested · ${p.untested.join(", ")}`;
    }
    const blocked = p.action_taken === "blocked";
    byId("recommendation").hidden = false;
    byId("recommendation").dataset.action = blocked ? "blocked" : "none";
    byId("recommendation-action").textContent = blocked ? "Agent recommends: Block" : "Agent recommends: no block, review";
    byId("recommendation-reason").textContent = p.reasons[0]?.text ?? "";
    byId("decision-label").hidden = byId("decisions").hidden = playback;
    byId("decision").textContent = "";
    refreshBlocklist();
    activity(event, "Verdict reached", label);
    stop("Investigation complete", "complete");
  },
  decision(event, p) { recordDecision(p); },
  blocklist_hit(event, p) {
    const banner = byId("blocklist-hit");
    const who = p.decided_by === "agent" ? "the agent" : "the analyst";
    const at = clock(p.decided_at);
    const lead = p.status === "blocked" ? "⛔ Already blocked" : "Released earlier";
    const head = [`${lead} by ${who}${at ? ` at ${at}` : ""}`, p.verdict].filter(Boolean).join(" · ");
    banner.replaceChildren(`${head} · `, scanLink(p.scan_id, "view previous scan"), " · investigating again");
    banner.dataset.status = p.status;
    banner.hidden = false;
  },
  error(event, p) {
    if (captureOnly && p.where === "capture") {
      byId("verdict").textContent = "Screenshot unavailable";
      byId("decision").textContent = "The page could not be captured. No phishing verdict was made.";
      stop(p.message, "error");
      return;
    }
    if (p.where === "investigator" && p.message.includes("Planner unavailable, rules only")) {
      byId("planner-fallback").hidden = false;
      activity(event, "Planner unavailable, rules only");
      return;
    }
    // A sandbox killed by its own limit reports "not running"; the verdict still follows.
    if (/not running/i.test(p.message)) {
      if (!limitHit) activity(event, "Sandbox stopped early", p.where).dataset.containerError = "";
      return;
    }
    stop(`${p.where}: ${p.message}`, "error");
  },
};

function browserLabel(visit) {
  const name = String(visit ?? "");
  if (name.startsWith("victim_mobile")) return "Phone browser";
  if (name.startsWith("victim")) return "Desktop browser";
  if (name.startsWith("robot")) return "Scanner browser";
  return name;
}

function setHypothesisChip(id, status) {
  const entry = hypothesisRows.get(id);
  if (!entry) return;
  entry.status = status;
  entry.state.textContent = hypothesisChips[status] ?? status;
  entry.state.dataset.status = status;
}

function roundCard(p) {
  if (!(p.round > 1)) return;
  byId("rounds-stage").hidden = false;
  const card = element("article", "", "round-card");
  const state = element("span", "Running", "round-state");
  state.dataset.state = "running";
  card.append(element("strong", `Round ${p.round} · ${browserLabel(p.visit)}`), state);
  if (p.reason) card.append(element("p", p.reason, "subtle"));
  appendRow("rounds", card);
  roundCards.set(p.visit, state);
}

function setRoundState(visit, text, state) {
  const badge = roundCards.get(visit);
  if (!badge || (badge.dataset.state === "risk" && state === "done")) return;
  badge.textContent = text;
  badge.dataset.state = state;
}

function approvalStage() {
  return stages.find((stage) => stage.dataset.phase === "approval");
}

function showApprovalShot(visit) {
  const image = byId("approval-shot");
  const path = latestShots.get(visit);
  image.hidden = !path;
  if (path) {
    image.src = evidenceUrl(path);
    image.alt = `${browserLabel(visit)} with the filled sign-in form`;
  }
}

function openApprovalBanner(p) {
  pendingApproval = p.visit;
  byId("approval-banner-title").replaceChildren(
    "The agent wants to submit the decoy login on ", element("strong", p.host || "this page"));
  showApprovalShot(p.visit);
  const seconds = Number(p.timeout_s) || 60;
  byId("approval-timer-label").textContent = `Policy approves automatically in ${seconds} s if you don't answer`;
  byId("approval-banner").hidden = false;
  const bar = byId("approval-bar");
  bar.style.transition = "none";
  bar.style.transform = "scaleX(1)";
  bar.getBoundingClientRect();
  bar.style.transition = `transform ${seconds}s linear`;
  bar.style.transform = "scaleX(0)";
  byId("approval-result").textContent = playback ? "Recorded run: the answer was given at the time." : "";
  for (const button of byId("approval-banner").querySelectorAll("[data-approval]")) button.disabled = playback;
  approvalStage().dataset.waiting = "true";
}

async function answerApproval(visit, decision) {
  const id = scanId;
  const result = byId("approval-result");
  for (const button of byId("approval-banner").querySelectorAll("[data-approval]")) button.disabled = true;
  result.textContent = "Sending…";
  try {
    const response = await fetch(`/api/scans/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visit, decision }),
    });
    if (id !== scanId) return;
    result.textContent = response.ok
      ? `${decision === "approve" ? "Approval" : "Denial"} sent. Waiting for the agent.`
      : "This visit is no longer waiting.";
  } catch {
    if (id === scanId) result.textContent = "Could not reach the server. The policy decides on timeout.";
  }
}

function closeApproval(visit) {
  if (visit !== undefined && visit !== pendingApproval) return;
  pendingApproval = undefined;
  byId("approval-banner").hidden = true;
  delete approvalStage().dataset.waiting;
}

function clearApprovals() {
  closeApproval();
}

function stop(message, state) {
  source?.close();
  clearApprovals();
  status(message, state);
  finishLoading(state);
  for (const family of ["scanner", "victim"]) {
    const badge = byId(`${family}-state`);
    if (badge.dataset.state === "running" || badge.dataset.state === "waiting") {
      badge.dataset.state = "finished";
      badge.textContent = state === "complete" ? "Visit ended" : "Scan stopped";
    }
  }
  startButton.disabled = false;
  startButton.textContent = "Start scan";
}

function reset() {
  source?.close();
  if (activeResult) {
    const previous = element("article", "", "previous-exchange");
    const prompt = element("div", "", "prompt-message");
    prompt.append(element("span", "You"), element("p", byId("submitted-url").textContent));
    previous.append(prompt, element("p", activeResult, "previous-verdict"));
    byId("conversation-history").append(previous);
  }
  activeResult = undefined;
  clearApprovals();
  approveRest = false;
  byId("blocklist-hit").hidden = true;
  document.querySelector(".workspace").replaceWith(initialWorkspace.cloneNode(true));
  for (const id of counterIds) byId(id).textContent = "0";
  for (const cache of [hypothesisRows, sandboxRows, stepReasons, observedHosts, thirdPartyHosts, blockedRows, roundCards, visitedStages, latestShots, autoAnswered]) cache.clear();
  limitHit = false;
  for (const stage of stages) {
    stage.removeAttribute("aria-current");
    delete stage.dataset.complete;
    delete stage.dataset.skipped;
    stage.querySelector(".stage-note").textContent = "";
  }
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

function configureCaptureView(enabled) {
  captureOnly = enabled;
  byId("active-exchange").dataset.captureOnly = String(enabled);
  byId("environment").textContent = enabled ? "Passive capture" : playback ? "Recorded investigation" : liveService ? "Live investigation" : "Simulation workspace";
  byId("comparison-heading").textContent = enabled ? "Public-page screenshot" : "Browser comparison";
  byId("scanner-label").textContent = enabled ? "Public page" : "Scanner bot";
  byId("scanner-profile").textContent = enabled ? "Passive capture" : "Headless browser";
  byId("scanner-heading").textContent = enabled ? "Final URL" : "Scanner saw";
  byId("scanner-pane-profile").hidden = enabled;
  if (enabled) byId("compare-stage").dataset.view = "scanner";
}

function openExchange(submitted, recording = false, capture = false) {
  reset();
  playback = recording;
  configureCaptureView(capture);
  byId("welcome").hidden = true;
  byId("active-exchange").hidden = false;
  byId("submitted-url").textContent = submitted;
  byId("active-exchange").scrollIntoView({ block: "start" });
  startLoading();
  startButton.disabled = true;
  startButton.textContent = recording ? "Replaying…" : "Scanning…";
  status(recording ? "Opening recording" : "Starting investigation", "running");
}

function connectScan(id) {
  scanId = id;
  byId("case-id").textContent = `Scan ${scanId.slice(0, 8)}`;
  const stream = new EventSource(`/api/scans/${scanId}/events`);
  source = stream;
  let failures = 0;
  stream.onopen = () => status(playback ? "Playing recorded investigation" : "Investigation running", "running");
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
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (startButton.disabled) return;
  openExchange(urlInput.value, false, !presets.some((button) => button.dataset.url === urlInput.value));
  try {
    const result = await post("/api/scans", Object.fromEntries(new FormData(form)));
    configureCaptureView(result.capture_only === true);
    connectScan(result.scan_id);
  } catch (error) {
    stop(error.message, "error");
  }
});

const replayRoute = location.pathname.match(/^\/replay\/([a-zA-Z0-9_-]{1,80})$/);
if (replayRoute) {
  openExchange("Recorded investigation", true);
  connectScan(replayRoute[1]);
  const replayId = scanId;
  fetch(evidenceUrl("robot/robot.json"))
    .then((response) => response.ok ? response.json() : null)
    .then((record) => {
      if (!record || scanId !== replayId) return;
      byId("robot-url").textContent = record.final_url ?? "Scanner capture";
      capture("robot", "robot/final.png", `Scanner capture showing ${record.title ?? "the page"}`);
    })
    .catch(() => {});
}

byId("approval-banner").addEventListener("click", (event) => {
  const button = event.target.closest("[data-approval]");
  if (!button || !pendingApproval || playback) return;
  if (button.dataset.approval === "approve-rest") approveRest = true;
  answerApproval(pendingApproval, button.dataset.approval === "deny" ? "deny" : "approve");
});

refreshBlocklist();

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
  .then(({ demo, recordings, scoreboard_enabled, live_presets }) => {
    const group = byId("recorded-runs");
    const names = { kit: "Phishing kit", mobile: "Mobile-only kit", legit: "Legit Vexalo", inject: "Prompt injection" };
    for (const [key, id] of Object.entries(recordings ?? {})) {
      const link = element("a", names[key] ?? key);
      link.href = `/replay/${encodeURIComponent(id)}`;
      group.append(link);
    }
    group.hidden = !group.querySelector("a");
    byId("scoreboard-run").hidden = !scoreboard_enabled;
    if (!demo && !scanId) byId("environment").textContent = "Public link capture";
    const live = live_presets && Object.keys(live_presets).length > 0;
    liveService = Boolean(live);
    if (live) {  // presets start real sandboxed investigations on this VM's fixture hosts
      for (const button of presets) {
        const url = live_presets[button.dataset.preset];
        if (url) { button.dataset.url = url; button.hidden = false; } else button.hidden = true;
      }
      if (!scanId) byId("environment").textContent = "Live investigation";
    }
    byId("simulated-presets").hidden = !(demo || live);
  })
  .catch(() => status("Could not check service status", "error"));

byId("scoreboard").addEventListener("toggle", async (event) => {
  if (!event.currentTarget.open) return;
  const summary = byId("scoreboard-result");
  summary.textContent = "Loading saved result…";
  try {
    const response = await fetch("/api/scoreboard");
    if (!response.ok) throw new Error();
    const result = await response.json();
    const bot = (profile) => profile?.bot === true ? "true" : profile?.bot === false ? "false" : "unavailable";
    summary.textContent = result
      ? `Scanner bot: ${bot(result.robot)} · Victim bot: ${bot(result.victim)}`
      : "No saved scoreboard result.";
  } catch {
    summary.textContent = "Could not load the saved scoreboard.";
  }
});

byId("scoreboard-run").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const summary = byId("scoreboard-result");
  button.disabled = true;
  summary.textContent = "Running scanner and victim browsers against the BotD fixture…";
  try {
    const response = await fetch("/api/scoreboard", { method: "POST" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? "The browser check could not start.");
    }
    const result = await response.json();
    const bot = (profile) => profile?.bot === true ? "true" : profile?.bot === false ? "false" : "unavailable";
    summary.textContent = `Scanner bot: ${bot(result.robot)} · Victim bot: ${bot(result.victim)}${result.pass ? " · Check passed" : " · Check did not pass"}`;
  } catch (error) {
    summary.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

byId("email-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = byId("email-preview-button");
  const message = byId("email-preview-status");
  button.disabled = true;
  message.textContent = "Checking email…";
  try {
    const result = await post("/api/email-preview", { email_text: byId("email-text").value });
    renderEmailTriage(result);
    byId("email-form").closest("details").open = false;
    byId("email-triage").scrollIntoView({ block: "nearest" });
    message.textContent = "Email preview ready. No links were opened.";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
