/* ==================================================================
   E.V. 2.0 front-end — vanilla JS, no deps.
   Sections: state · boot · visuals (stars/core/wave) · chat helpers ·
   agent activity · permission · tasks · composer · SSE · status/model ·
   palette · voice · shortcuts.
   ================================================================== */
"use strict";

/* ------------------------------------------------------------------ */
/* global state + state pill / core labels                             */
/* ------------------------------------------------------------------ */
const EV = {
  state: "idle",
  level: 0.12,              // waveform energy 0..1
  tts: localStorage.ev_tts !== "off",
  setState(s) {
    this.state = s;
    document.body.dataset.state = s;
    const en = { idle: "READY", listening: "LISTENING",
      thinking: "THINKING", speaking: "SPEAKING",
      awaiting: "AWAITING APPROVAL", error: "ERROR" };
    const core = document.getElementById("coreState");
    if (core) core.textContent = en[s] || s.toUpperCase();
  },
  setLevel(v) { this.level = Math.max(0, Math.min(1, v)); },
};

const STATE_COLOR = {
  idle: "#2AC8DE", listening: "#f5b544", thinking: "#67e3f9",
  speaking: "#4ade80", awaiting: "#f5b544", error: "#f87171",
};

/* ------------------------------------------------------------------ */
/* boot sequence                                                       */
/* ------------------------------------------------------------------ */
(function boot() {
  const lines = [
    "E.V. CORE … ONLINE",
    "OS AGENT LAYER … LINKED",
    "TOOL ORCHESTRATOR … READY",
    "VOICE PIPELINE … STANDBY",
    "CONSOLE … ACTIVE",
  ];
  const box = document.getElementById("bootLines");
  let i = 0;
  const tick = () => {
    if (i < lines.length) {
      const d = document.createElement("div");
      d.textContent = "> " + lines[i++];
      box.appendChild(d);
      setTimeout(tick, 230);
    } else {
      setTimeout(() => document.getElementById("boot").classList.add("done"),
                 380);
      // hard fallback: the fade is cosmetic — never let the overlay linger
      setTimeout(() => {
        const b = document.getElementById("boot");
        if (b) b.style.display = "none";
      }, 1100);
    }
  };
  setTimeout(tick, 180);
})();

/* ------------------------------------------------------------------ */
/* starfield — subtle depth only (opacity handled in CSS)              */
/* ------------------------------------------------------------------ */
(function starfield() {
  const cv = document.getElementById("stars");
  const cx = cv.getContext("2d");
  let W, H, stars = [];
  function resize() {
    W = cv.width = innerWidth;
    H = cv.height = innerHeight;
    stars = Array.from({ length: 90 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      z: Math.random() * 0.8 + 0.2, tw: Math.random() * Math.PI * 2,
    }));
  }
  addEventListener("resize", resize);
  resize();
  (function draw(t) {
    cx.clearRect(0, 0, W, H);
    for (const s of stars) {
      s.y += s.z * 0.08;
      if (s.y > H) { s.y = 0; s.x = Math.random() * W; }
      const a = 0.2 + 0.5 * Math.abs(Math.sin(t / 900 + s.tw));
      cx.fillStyle = `rgba(120,220,255,${(a * s.z).toFixed(3)})`;
      cx.fillRect(s.x, s.y, s.z * 1.6, s.z * 1.6);
    }
    requestAnimationFrame(draw);
  })(0);
})();

/* ------------------------------------------------------------------ */
/* E.V. neural core — orbiting particles, state-reactive               */
/* ------------------------------------------------------------------ */
(function core() {
  const cv = document.getElementById("core");
  const cx = cv.getContext("2d");
  let W, H, parts = [];
  function resize() {
    W = cv.width = cv.clientWidth * devicePixelRatio;
    H = cv.height = cv.clientHeight * devicePixelRatio;
    parts = Array.from({ length: 70 }, () => ({
      r: 0.15 + Math.random() * 0.35,
      a: Math.random() * Math.PI * 2,
      sp: (0.2 + Math.random() * 0.9) * (Math.random() < 0.5 ? 1 : -1),
      sz: 0.6 + Math.random() * 1.8,
    }));
  }
  addEventListener("resize", resize);
  resize();
  (function draw(t) {
    const speed = { idle: 1, listening: 2.4, thinking: 3.2, awaiting: 1.8,
                    speaking: 2.0, error: 0.4 }[EV.state] || 1;
    cx.clearRect(0, 0, W, H);
    const R = Math.min(W, H) / 2;
    const col = STATE_COLOR[EV.state] || STATE_COLOR.idle;
    for (const p of parts) {
      p.a += 0.004 * p.sp * speed;
      const x = W / 2 + Math.cos(p.a) * p.r * R;
      const y = H / 2 + Math.sin(p.a) * p.r * R;
      cx.globalAlpha = 0.35 + 0.4 * Math.abs(Math.sin(t / 700 + p.a * 3));
      cx.fillStyle = col;
      cx.beginPath();
      cx.arc(x, y, p.sz * devicePixelRatio, 0, Math.PI * 2);
      cx.fill();
    }
    cx.globalAlpha = 0.10 + EV.level * 0.35;
    cx.fillStyle = col;
    cx.beginPath();
    cx.arc(W / 2, H / 2, R * (0.22 + EV.level * 0.16), 0, Math.PI * 2);
    cx.fill();
    cx.globalAlpha = 1;
    requestAnimationFrame(draw);
  })(0);
})();

/* ------------------------------------------------------------------ */
/* waveform strip in the CORE panel                                    */
/* ------------------------------------------------------------------ */
(function wave() {
  const cv = document.getElementById("wave");
  const cx = cv.getContext("2d");
  let W, H, phase = 0;
  function resize() {
    W = cv.width = cv.clientWidth * devicePixelRatio;
    H = cv.height = cv.clientHeight * devicePixelRatio;
  }
  addEventListener("resize", resize);
  resize();
  (function draw() {
    cx.clearRect(0, 0, W, H);
    const col = STATE_COLOR[EV.state] || STATE_COLOR.idle;
    const mid = H / 2;
    const amp = (H / 2 - 2 * devicePixelRatio) * EV.level;
    phase += 0.25;
    cx.beginPath();
    for (let x = 0; x <= W; x += 2) {
      const k = x / W;
      const env = Math.sin(Math.PI * k);
      const y = mid + Math.sin(k * 14 + phase) * amp * env
                   + Math.sin(k * 31 - phase * 1.7) * amp * 0.4 * env;
      x === 0 ? cx.moveTo(x, y) : cx.lineTo(x, y);
    }
    cx.strokeStyle = col;
    cx.lineWidth = 1.5 * devicePixelRatio;
    cx.shadowColor = col;
    cx.shadowBlur = 6 * devicePixelRatio;
    cx.stroke();
    cx.shadowBlur = 0;
    const target = { idle: 0.10, listening: EV.level, thinking: 0.32,
                     speaking: EV.level, awaiting: 0.45,
                     error: 0.18 }[EV.state] ?? 0.10;
    if (EV.state !== "listening") {
      EV.level += (target * (0.7 + 0.6 * Math.abs(Math.sin(phase / 40)))
                   - EV.level) * 0.08;
    }
    requestAnimationFrame(draw);
  })();
})();

/* ------------------------------------------------------------------ */
/* chat log helpers                                                    */
/* ------------------------------------------------------------------ */
const log = document.getElementById("log");
const chatEl = document.getElementById("chat");

function bubble(cls, text) {
  chatEl.classList.add("has-msgs");
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.dir = "auto";                       // mixed fa/en renders correctly
  const body = document.createElement("span");
  body.className = "body";
  if (text != null) body.textContent = text;
  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = new Date().toLocaleTimeString("en-US",
    { hour: "2-digit", minute: "2-digit" });
  d.append(body, ts);
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}
/* streaming updates must touch only the body — keeps the timestamp */
function msgBody(el) { return el.querySelector(".body") || el; }

function briefResult(r) {
  if (r == null) return "";
  if (typeof r === "string") return r;
  if (typeof r === "object") {
    if (r.blocked) return "Blocked: " + String(r.error || "");
    if (r.error) return "Error: " + String(r.error);
    if (r.description) return String(r.description);
    if (r.exit_code != null) {
      const tail = (typeof r.stderr === "string" && r.stderr.trim())
        ? r.stderr.trim().split("\n").pop().slice(0, 90)
        : (typeof r.stdout === "string"
           ? r.stdout.trim().split("\n").pop().slice(0, 90) : "");
      return "exit=" + r.exit_code + (tail ? " " + tail : "");
    }
    if (Array.isArray(r.entries)) return r.entries.length + " items found";
    const s = JSON.stringify(r);
    return s ? s.slice(0, 120) : "";
  }
  return String(r).slice(0, 120);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
            '"': "&quot;", "'": "&#39;" }[c]));
}
/* server JSON-encodes SSE payloads; token/state carry plain strings */
function unjson(s) {
  try {
    const v = JSON.parse(s);
    if (typeof v === "string") return v;
    if (v && typeof v.t === "string") return v.t;
  } catch { /* plain text */ }
  return s;
}

/* ------------------------------------------------------------------ */
/* agent activity — one card per run, expandable tool steps.
   Shows WHAT E.V. did (tool + args + result) — never chain-of-thought. */
/* ------------------------------------------------------------------ */
const TOOL_ICONS = [
  ["shell", "⌘"], ["command", "⌘"], ["fs", "📁"], ["file", "📁"],
  ["camera", "📷"], ["screen", "🖥"], ["gpu", "📊"], ["sys", "📊"],
  ["process", "📊"], ["web", "🌐"], ["browser", "🌐"], ["python", "🐍"],
  ["voice", "🎤"], ["memory", "🧠"], ["window", "🪟"], ["clip", "📋"],
  ["image", "🖼"], ["doc", "📄"], ["video", "🎬"],
];
function toolIcon(name) {
  const n = String(name).toLowerCase();
  for (const [k, ic] of TOOL_ICONS) if (n.includes(k)) return ic;
  return "🔧";
}

let activity = null;          // current run's activity card
function activeToolCount() {
  return activity
    ? activity.querySelectorAll(".act-step.run").length : 0;
}
function refreshToolsMeta() {
  const el = document.getElementById("coreTools");
  if (!el || !el.dataset.count) return;
  const act = activeToolCount();
  el.textContent = el.dataset.count + " available"
    + (act ? " · " + act + " active" : "");
}

function ensureActivity() {
  if (activity && activity.dataset.closed !== "1") return activity;
  chatEl.classList.add("has-msgs");
  activity = document.createElement("div");
  activity.className = "activity";
  activity.innerHTML =
    `<div class="act-head"><span class="act-pulse"></span>` +
    `<b>E.V. is working</b><span class="act-meta"></span></div>` +
    `<ul class="act-list"></ul>`;
  log.appendChild(activity);
  log.scrollTop = log.scrollHeight;
  refreshToolsMeta();
  return activity;
}

function closeActivity(ok) {
  if (!activity || activity.dataset.closed === "1") return;
  activity.dataset.closed = "1";
  activity.classList.add(ok === false ? "failed" : "closed");
  const n = activity.querySelectorAll(".act-step").length;
  activity.querySelector(".act-head b").textContent =
    ok === false ? "E.V. — Stopped" : "Completed";
  activity.querySelector(".act-meta").textContent =
    n ? n + " tool" + (n > 1 ? "s" : "") : "";
  refreshToolsMeta();
}

function toggleStep(li) {
  const det = li.querySelector(".act-detail");
  const row = li.querySelector(".act-row");
  det.hidden = !det.hidden;
  row.setAttribute("aria-expanded", det.hidden ? "false" : "true");
}

function makeStepLi(tool, args) {
  const li = document.createElement("li");
  const flat = String(args).replace(/\s+/g, " ").trim();
  li.innerHTML =
    `<button class="act-row" type="button" aria-expanded="false">` +
    `<span class="act-ico">${toolIcon(tool)}</span>` +
    `<span class="act-name" title="${escapeHtml(tool)}">${escapeHtml(tool)}</span>` +
    `<span class="act-mid">` +
    `<span class="act-sum"></span>` +
    `<span class="act-res" hidden></span></span>` +
    `<span class="act-st"></span></button>` +
    `<div class="act-detail" hidden>` +
    `<pre class="ltr args"></pre><pre class="ltr out" hidden></pre>` +
    `<span class="act-dur"></span></div>`;
  li.querySelector(".act-detail pre").textContent =
    String(args).slice(0, 2000) || "—";
  li.querySelector(".act-row").addEventListener("click", () => toggleStep(li));
  return li;
}

function addStep(info) {
  const card = ensureActivity();
  const ul = card.querySelector(".act-list");
  const tool = info.tool || info.step || "tool";
  const args = (typeof info.args === "object" && info.args)
    ? JSON.stringify(info.args, null, 1) : String(info.args ?? "");

  if (info.phase === "start") {
    const li = makeStepLi(tool, args);
    li.className = "act-step run";
    li.dataset.tool = tool;
    li.dataset.t0 = String(Date.now());
    // The live announcement includes the command, so keep it visible.
    li.querySelector(".act-sum").textContent =
      info.message || String(args).replace(/\s+/g, " ").slice(0, 140);
    ul.appendChild(li);
    trimSteps(ul);
    refreshToolsMeta();
    log.scrollTop = log.scrollHeight;
    return;
  }

  if (info.phase === "progress") {
    // heartbeat: refresh the running row for this tool
    const run = [...ul.querySelectorAll(".act-step.run")]
      .reverse().find(x => x.dataset.tool === tool);
    if (run) {
      const msg = info.message || "Still running…";
      run.querySelector(".act-sum").textContent = msg;
      const det = run.querySelector(".act-detail .out");
      det.hidden = false;
      det.textContent = msg;
    }
    return;
  }

  // done — KEEP the "what" (message) in the row and ADD the result under
  // it, so both stay visible without expanding anything
  let li = [...ul.querySelectorAll(".act-step.run")]
    .reverse().find(x => x.dataset.tool === tool);
  if (!li) { li = makeStepLi(tool, args); ul.appendChild(li); trimSteps(ul); }
  const res = info.result;
  const bad = res && typeof res === "object" && (res.error || res.blocked);
  li.className = "act-step " + (bad ? "err" : "done");
  const sum = briefResult(res);
  const resEl = li.querySelector(".act-res");
  resEl.hidden = false;
  resEl.textContent = sum || "—";
  const out = li.querySelector(".act-detail .out");
  out.hidden = false;
  out.textContent = sum || "—";
  const t0 = Number(li.dataset.t0 || 0);
  if (t0) li.querySelector(".act-dur").textContent =
    "duration: " + ((Date.now() - t0) / 1000).toFixed(1) + "s";
  refreshToolsMeta();
}

function trimSteps(ul) {
  while (ul.children.length > 40) ul.firstChild.remove();
}

/* ------------------------------------------------------------------ */
/* permission — server asks for a Level-3/4 approval                   */
/* ------------------------------------------------------------------ */
const LEVEL_LABELS = { 0: "Safe", 1: "Write", 2: "System",
  3: "Privileged (root)", 4: "Destructive" };
function showPermission(p) {
  EV.setState("awaiting");
  const card = bubble("perm", "");
  const args = (typeof p.args === "object" && p.args)
    ? JSON.stringify(p.args) : String(p.args ?? "");
    card.innerHTML =
      `<div class="perm-head">⚠️ Approval required — Level ${Number(p.level) || 0} (` +
      `${escapeHtml(p.level_name || LEVEL_LABELS[p.level] || "")})</div>` +
      `<div class="perm-action">E.V. wants to run:</div>` +
      `<pre class="perm-args">${escapeHtml(args).slice(0, 400)}</pre>` +
      `<div class="perm-btns">` +
      `<button class="no">Deny</button>` +
      `<button class="ok">Approve</button>` +
      `<span class="perm-timer"></span></div>`;
  const ok = card.querySelector(".ok"), no = card.querySelector(".no");
  const timer = card.querySelector(".perm-timer");
  let left = Math.max(30, Math.min(300, (p.timeout || 180) | 0));
  const iv = setInterval(() => {
    left -= 1;
    if (timer) timer.textContent = "Expires in " + left + "s";
    if (left <= 0) answer(false, true);
  }, 1000);
  async function answer(allow, expired) {
    clearInterval(iv);
    ok.disabled = no.disabled = true;
    card.classList.add(allow ? "granted" : "denied");
      card.querySelector(".perm-btns").innerHTML =
        `<span>${allow ? "✓ Approved — running…"
                       : expired ? "⌛ Expired — denied" : "✕ Denied"}</span>`;
    try {
      await fetch("/api/permission", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: p.id, allow: !!allow }) });
    } catch { /* server auto-denies on timeout anyway */ }
    if (EV.state === "awaiting") EV.setState("thinking");
  }
  ok.addEventListener("click", () => answer(true));
  no.addEventListener("click", () => answer(false));
  log.scrollTop = log.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* workspace task history — the user's REAL prompts, locally stored    */
/* ------------------------------------------------------------------ */
/* ------------------------------------------------------------------ */
/* chat sessions — every conversation is its own history page (like\n   ChatGPT): title from the first prompt, click to reopen, continue,\n   or start fresh with a new task. Persisted in localStorage.       */
/* ------------------------------------------------------------------ */
let SESS = { id: null, title: "", ts: 0, msgs: [] };

function loadSessions() {
  try { return JSON.parse(localStorage.ev_sessions || "[]"); }
  catch { return []; }
}
function saveSessions(list) {
  localStorage.ev_sessions = JSON.stringify(list.slice(0, 30));
  renderSessions();
}
function ensureSession(firstText) {
  if (!SESS.id) {
    SESS = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      title: String(firstText).slice(0, 60),
      ts: Date.now(),
      msgs: [],
    };
  }
}
function persistSession() {
  if (!SESS.id) return;
  const list = loadSessions();
  const rec = { id: SESS.id, title: SESS.title, ts: SESS.ts,
                msgs: SESS.msgs.slice(-40) };
  const i = list.findIndex(s => s.id === SESS.id);
  if (i >= 0) list[i] = rec; else list.unshift(rec);
  saveSessions(list);
}

/* history rows: real timestamps, two groups with divider headers */
function fmtTaskTime(ts) {
  const d = new Date(ts);
  const dayStart = new Date().setHours(0, 0, 0, 0);
  return ts >= dayStart
    ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-US", { month: "numeric", day: "numeric" });
}

function renderSessions() {
  const ul = document.getElementById("taskList");
  const sessions = loadSessions();
  ul.innerHTML = "";
  if (!sessions.length) {
    const li = document.createElement("li");
    li.className = "sb-empty";
    li.textContent = "No conversations yet. Each chat is saved as a session.";
    ul.appendChild(li);
    return;
  }
  const dayStart = new Date().setHours(0, 0, 0, 0);
  const groups = [
    ["Today", sessions.filter(s => s.ts >= dayStart)],
    ["Earlier", sessions.filter(s => s.ts < dayStart)],
  ];
  for (const [label, list] of groups) {
    if (!list.length) continue;
    const h = document.createElement("li");
    h.className = "tk-grp";
    h.textContent = label;
    ul.appendChild(h);
    for (const s of list.slice(0, 10)) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tk-item";
      b.title = s.title;
      const txt = document.createElement("span");
      txt.className = "tk-txt";
      txt.dir = "auto";
      txt.textContent = s.title;
      const time = document.createElement("small");
      time.className = "tk-time";
      time.textContent = fmtTaskTime(s.ts);
      b.append(txt, time);
      b.addEventListener("click", () => openSession(s.id));
      li.appendChild(b);
      ul.appendChild(li);
    }
  }
}

function openSession(id) {
  const s = loadSessions().find(x => x.id === id);
  if (!s) return;
  newTask(true); // clear the live view (keep session)
  SESS = { id: s.id, title: s.title, ts: s.ts, msgs: s.msgs.slice() };
  chatEl.classList.add("has-msgs");
  const chip = document.createElement("div");
  chip.className = "sess-chip";
  chip.innerHTML =
    `<span>🕘 Previous session — <b>${escapeHtml(s.title)}</b></span>` +
    `<button type="button" title="New task">Close</button>`;
  chip.querySelector("button").addEventListener("click", () => newTask());
  log.appendChild(chip);
  for (const m of s.msgs) bubble(m.role === "user" ? "user" : "ev", m.text);
  msgInput.focus();
}

/* migrate: old flat prompt-history becomes one session each */
function migrateTasks() {
  if (loadSessions().length) return;
  let tasks = [];
  try { tasks = JSON.parse(localStorage.ev_tasks || "[]"); } catch { tasks = []; }
  if (!tasks.length) return;
  const sessions = tasks.map(t => ({
    id: "m" + t.ts,
    title: t.text.slice(0, 60),
    ts: t.ts,
    msgs: [{ role: "user", text: t.text }],
  }));
  localStorage.ev_sessions = JSON.stringify(sessions.slice(0, 30));
  delete localStorage.ev_tasks;
  renderSessions();
}
document.getElementById("clearHistory").addEventListener("click", () => {
  const sessionIds = [...new Set(
    [...loadSessions().map(s => s.id), SESS.id].filter(Boolean))];
  for (const sessionId of sessionIds) {
    fetch("/api/session/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    }).catch(() => {});
  }
  SESS = { id: null, title: "", ts: 0, msgs: [] };
  localStorage.ev_sessions = "[]";
  renderSessions();
});

/* ------------------------------------------------------------------ */
/* chat — POST /api/chat + SSE stream (abortable with Esc)             */
/* ------------------------------------------------------------------ */
let currentAbort = null;

async function sendMessage(text) {
  text = String(text || "").trim();
  if (!text) return;
  if (EV.state === "thinking" || EV.state === "awaiting") return;
  bubble("user", text);
  ensureSession(text);
  SESS.msgs.push({ role: "user", text });
  EV.setState("thinking");
  activity = null;                       // fresh activity card per run

  const abort = new AbortController();
  currentAbort = abort;
  let evBubble = null, acc = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: SESS.id,
        history: (SESS.msgs.length > 1
          ? SESS.msgs.slice(0, -1).slice(-24)
              .map(m => ({ role: m.role === "user" ? "user" : "assistant",
                           content: m.text }))
          : null),
      }),
      signal: abort.signal,
    });
    if (!res.ok || !res.body) throw new Error("HTTP " + res.status);

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message", data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5);
        }
        if (!data) continue;
        handleEvent(event, data);
      }
    }
  } catch (e) {
    if (e && e.name === "AbortError") {
      closeActivity(false);
      bubble("ev", "⏹ Stopped.");
      persistSession();
      EV.setState("idle");
      currentAbort = null;
      return;
    }
    EV.setState("error");
    bubble("ev error", "Server connection error: " + (e.message || e));
    setTimeout(() => EV.setState("idle"), 2500);
    currentAbort = null;
    return;
  }
  currentAbort = null;
  // stream closed without "done" (server restart/crash) — never stick
  if (EV.state === "thinking") EV.setState("idle");

  function handleEvent(event, data) {
    if (event === "state") { EV.setState(unjson(data)); return; }
    if (event === "token") {
      if (!evBubble) { evBubble = bubble("ev", ""); acc = ""; }
      acc += unjson(data);
      msgBody(evBubble).textContent = acc;
      log.scrollTop = log.scrollHeight;
      return;
    }
    if (event === "step") {
      try { addStep(JSON.parse(data)); } catch { /* ignore */ }
      return;
    }
    if (event === "permission") {
      try { showPermission(JSON.parse(data)); } catch { /* ignore */ }
      return;
    }
    if (event === "done") {
      let payload = {};
      try { payload = JSON.parse(data); } catch { /* ignore */ }
      const answer = payload.answer ?? acc;
      if (!evBubble && answer) evBubble = bubble("ev", answer);
      else if (evBubble && answer && !acc) msgBody(evBubble).textContent = answer;
      closeActivity(true);
      EV.setState("idle");
      speak(answer);
      if (answer) SESS.msgs.push({ role: "ev", text: answer });
      persistSession();
    }
  }
}

function stopGeneration() {
  if (currentAbort) currentAbort.abort();
}

/* ------------------------------------------------------------------ */
/* composer — auto-growing textarea, Enter=send, Shift+Enter=newline   */
/* ------------------------------------------------------------------ */
const msgInput = document.getElementById("msg");
function autogrow() {
  msgInput.style.height = "auto";
  msgInput.style.height =
    Math.min(150, Math.max(40, msgInput.scrollHeight)) + "px";
}
msgInput.addEventListener("input", autogrow);
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    document.getElementById("composer").requestSubmit();
  }
});

document.getElementById("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = msgInput.value.trim();
  if (!text) return;
  msgInput.value = "";
  autogrow();
  sendMessage(text);
});

/* quick actions (sidebar + empty state) — all REAL agent tools */
document.querySelectorAll("[data-qa]").forEach((b) => {
  b.addEventListener("click", () => {
    if (EV.state === "thinking" || EV.state === "awaiting") {
      bubble("ev error", "E.V. is busy. Stop the current task with Esc first.");
      return;
    }
    sendMessage(b.dataset.qa);
  });
});

/* new task — clears the conversation (history is kept) */
function newTask(keepSession) {
  stopGeneration();
  log.innerHTML = "";
  if (!keepSession) {
    SESS = { id: null, title: "", ts: 0, msgs: [] };
    chatEl.classList.remove("has-msgs");
  }
  activity = null;
  if (EV.state !== "idle") EV.setState("idle");
  msgInput.focus();
}
document.getElementById("newTask").addEventListener("click", () => newTask());

/* sidebar collapse (Ctrl+B, persisted) */
function applySidebar() {
  document.body.classList.toggle("sb-collapsed",
    localStorage.ev_sidebar === "off");
}
function toggleSidebar() {
  localStorage.ev_sidebar =
    localStorage.ev_sidebar === "off" ? "on" : "off";
  applySidebar();
}
document.getElementById("sbToggle").addEventListener("click", toggleSidebar);
applySidebar();

/* ------------------------------------------------------------------ */
/* status polling + gauges + tools (all real /api/status fields)       */
/* ------------------------------------------------------------------ */
function setMeter(barId, valId, pct, txt) {
  const bar = document.getElementById(barId);
  if (!bar) return;
  bar.style.width = (pct ?? 0) + "%";
  bar.classList.toggle("hot", (pct ?? 0) > 85);
  document.getElementById(valId).textContent = txt;
}

function isCloud(name) { return /cloud/i.test(String(name)); }

async function pollStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    setMeter("mCpu", "vCpu", s.cpu, s.cpu != null ? s.cpu.toFixed(1) + "%" : "–");
    setMeter("mRam", "vRam", s.ram.percent, s.ram.percent + "%");
    if (s.gpu && s.gpu.available === false) {
      document.getElementById("gpuTemp").textContent = "GPU: unavailable";
    } else if (s.gpu && s.gpu.percent != null) {
      setMeter("mGpu", "vGpu", s.gpu.percent, s.gpu.percent + "%");
      document.getElementById("gpuTemp").textContent =
        s.gpu.temp != null ? "GPU: " + s.gpu.temp + "°C" : "GPU: active";
      if (s.gpu.vram != null)
        setMeter("mVram", "vVram", s.gpu.vram.percent ?? 0,
                 (s.gpu.vram.percent ?? 0) + "%");
    }
    if (s.disk && s.disk.percent != null)
      setMeter("mDisk", "vDisk", s.disk.percent, s.disk.percent + "%");
    if (s.tools && s.tools.count != null) {
      const el = document.getElementById("coreTools");
      el.dataset.count = s.tools.count;
      refreshToolsMeta();
    }
    renderModelDrop(s.model);
    renderCoreModel(s.model);
  } catch { /* server briefly busy — retry next tick */ }
}

async function pollBrief() {
  const summary = document.getElementById("briefSummary");
  const state = document.getElementById("briefState");
  const sources = document.getElementById("briefSources");
  const taskBox = document.getElementById("briefTasks");
  if (!summary || !state || !sources || !taskBox) return;
  try {
    const brief = await (await fetch("/api/brief")).json();
    if (!brief.ok) {
      state.textContent = "OFFLINE";
      summary.textContent = "No productivity services are configured.";
      sources.replaceChildren();
      taskBox.replaceChildren();
      return;
    }
    state.textContent = `${brief.sources.length} ACTIVE`;
    summary.textContent = brief.summary || "No summary available.";
    sources.replaceChildren(...brief.sources.map((name) => {
      const chip = document.createElement("span");
      chip.className = "brief-source active";
      chip.textContent = name;
      return chip;
    }));
    taskBox.replaceChildren(...(brief.tasks || []).slice(0, 4).map((task) => {
      const row = document.createElement("div");
      row.className = "brief-task " + task.priority;
      const dot = document.createElement("i");
      const text = document.createElement("div");
      text.textContent = task.title;
      const meta = document.createElement("small");
      meta.textContent = `${task.source} · ${task.priority}`;
      text.appendChild(meta);
      row.append(dot, text);
      return row;
    }));
  } catch {
    state.textContent = "ERROR";
    summary.textContent = "Daily brief is temporarily unavailable.";
    taskBox.replaceChildren();
  }
}

/* ------------------------------------------------------------------ */
/* model dropdown — premium custom control (Local / Cloud tagged)      */
/* ------------------------------------------------------------------ */
const modelBtn = document.getElementById("modelBtn");
const modelName = document.getElementById("modelName");
const modelMenu = document.getElementById("modelMenu");
const modelSel = document.getElementById("modelSel");   // hidden a11y fallback
let modelInfo = null, modelBusy = false;

function renderCoreModel(info) {
  const el = document.getElementById("coreModel");
  if (!el || !info) return;
  const cur = info.mode === "fixed" && info.current ? info.current : "auto";
  el.textContent = cur === "auto" ? "auto (router)" : cur;
}

function renderModelDrop(info) {
  if (!info || modelBusy || !modelMenu.hidden) return;
  modelInfo = info;
  const cur = info.mode === "fixed" && info.current ? info.current : "auto";
  modelName.textContent = cur === "auto" ? "— auto —" : cur;
  const dot = modelBtn.querySelector(".mdot");
  dot.classList.toggle("cloud", cur !== "auto" && isCloud(cur));
  dot.classList.toggle("auto", cur === "auto");

  const all = [...new Set([...(info.pool || []), ...(info.available || [])])]
    .filter(m => m !== "auto");
  const providerModels = all.filter(m => String(m).includes(":"));
  const locals = all.filter(m => !String(m).includes(":") && !isCloud(m));
  const clouds = all.filter(m => isCloud(m));

  modelMenu.innerHTML = "";
  const section = (label) => {
    const h = document.createElement("div");
    h.className = "mm-title";
    h.textContent = label;
    modelMenu.appendChild(h);
  };
  const item = (m, sub) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mm-item" + (m === cur ? " cur" : "");
    b.innerHTML =
      `<span class="mm-txt">` +
      `<span class="mm-name" title="${escapeHtml(m)}">${escapeHtml(m)}</span>` +
      `<span class="mm-sub">${escapeHtml(sub)}</span></span>` +
      `<span class="mm-check">✓</span>`;
    b.addEventListener("click", () => setModel(m));
    modelMenu.appendChild(b);
  };

  section("MODELS");
  item("auto", "router picks per task");
  if (locals.length) {
    section("LOCAL · " + locals.length);
    locals.forEach(m => item(m, "Local · ollama"));
  }
  if (providerModels.length) {
    section("API PROVIDERS · " + providerModels.length);
    providerModels.forEach(m => {
      const provider = String(m).split(":", 1)[0];
      item(m, "API · " + provider);
    });
  }
  if (clouds.length) {
    section("CLOUD · " + clouds.length);
    clouds.forEach(m => item(m, "Cloud · ollama.com"));
  }
  if (!all.length) {
    const d = document.createElement("div");
    d.className = "mm-empty";
    d.textContent = "No other models installed";
    modelMenu.appendChild(d);
  }

  // hidden native select stays in sync (keyboard fallback)
  modelSel.innerHTML = "";
  for (const m of ["auto", ...all]) {
    const o = document.createElement("option");
    o.value = m;
    o.textContent = m;
    if (m === cur) o.selected = true;
    modelSel.appendChild(o);
  }
}

async function setModel(m) {
  modelBusy = true;
  modelBtn.classList.add("busy");
  modelName.textContent = m === "auto" ? "— auto —" : m + " …";
  try {
    const body = await (await fetch("/api/model", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: m }),
    })).json();
    modelInfo = body;
    renderModelDrop.force = true;
  } catch { modelName.textContent = "Error"; }
  modelBtn.classList.remove("busy");
  modelBusy = false;
  closeModelMenu();
  pollStatus();
}
/* allow re-render even while menu closed after an explicit change */
Object.defineProperty(renderModelDrop, "force", {
  set(v) { if (v) { modelMenu.hidden = true; } },
});

function closeModelMenu() { modelMenu.hidden = true; modelBtn.setAttribute("aria-expanded", "false"); }
modelBtn.addEventListener("click", () => {
  modelMenu.hidden = !modelMenu.hidden;
  modelBtn.setAttribute("aria-expanded", modelMenu.hidden ? "false" : "true");
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("#modelDrop")) closeModelMenu();
});

/* ------------------------------------------------------------------ */
/* TTS toggle                                                          */
/* ------------------------------------------------------------------ */
const ttsBtn = document.getElementById("ttsToggle");
function renderTtsBtn() {
  ttsBtn.textContent = EV.tts ? "🔊" : "🔇";
  ttsBtn.title = EV.tts ? "Mute voice output" : "Enable voice output";
}
ttsBtn.addEventListener("click", () => {
  EV.tts = !EV.tts;
  localStorage.ev_tts = EV.tts ? "on" : "off";
  renderTtsBtn();
});
renderTtsBtn();

/* ------------------------------------------------------------------ */
/* theme — dark (default) / light, persisted                           */
/* ------------------------------------------------------------------ */
const themeBtn = document.getElementById("themeToggle");
function applyTheme(t) {
  if (t === "light") { document.body.dataset.theme = "light"; themeBtn.textContent = "🌙"; }
  else { delete document.body.dataset.theme; themeBtn.textContent = "☀️"; }
  themeBtn.title = t === "light" ? "Dark theme" : "Light theme";
}
themeBtn.addEventListener("click", () => {
  const next = document.body.dataset.theme === "light" ? "dark" : "light";
  localStorage.ev_theme = next;
  applyTheme(next);
});
applyTheme(localStorage.ev_theme === "light" ? "light" : "dark");

let audioEl = null;
async function speak(text) {
  if (!EV.tts || !text || text.startsWith("[Error]")) return;
  try {
    EV.setState("speaking");
    const res = await fetch("/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: String(text).slice(0, 600) }),
    });
    if (!res.ok) throw new Error("tts " + res.status);
    const blob = await res.blob();
    if (audioEl) { audioEl.pause(); audioEl = null; }
    audioEl = new Audio(URL.createObjectURL(blob));
    audioEl.onended = () => EV.setState("idle");
    audioEl.onerror = () => EV.setState("idle");
    await audioEl.play();
  } catch {
    EV.setState("idle");
  }
}

/* ------------------------------------------------------------------ */
/* command palette (Ctrl+K) — actions over REAL functionality          */
/* ------------------------------------------------------------------ */
const palette = document.getElementById("palette");
const palInput = document.getElementById("palInput");
const palList = document.getElementById("palList");
let palSel = 0;

function sendQuick(text) {
  closePalette();
  if (EV.state === "thinking" || EV.state === "awaiting") {
    bubble("ev error", "E.V. is busy. Stop the current task with Esc first.");
    return;
  }
  sendMessage(text);
}

const PALETTE_ACTIONS = [
    { t: "New task — clear conversation", k: "Ctrl+N", run: () => { closePalette(); newTask(); } },
    { t: "Screenshot current screen", k: "tool", run: () =>
      sendQuick("Take a screenshot of the current screen and show it to me") },
    { t: "Take a camera photo", k: "tool", run: () =>
      sendQuick("Take a photo with the camera and show it to me") },
    { t: "List current folder files", k: "tool", run: () =>
      sendQuick("List the files in the current folder") },
    { t: "System status (CPU/RAM/GPU)", k: "tool", run: () =>
      sendQuick("Check CPU, RAM, and GPU status and summarize it") },
    { t: "Change language model", k: "model", run: () => { closePalette(); modelBtn.click(); } },
    { t: "Toggle light/dark theme", k: "theme", run: () => { closePalette(); themeBtn.click(); } },
    { t: "Toggle voice output (TTS)", k: "tts", run: () => { closePalette(); ttsBtn.click(); } },
    { t: "Toggle sidebar", k: "Ctrl+B", run: () => { closePalette(); toggleSidebar(); } },
    { t: "Focus message input", k: "/", run: () => { closePalette(); msgInput.focus(); } },
];

function openPalette() {
  palette.hidden = false;
  palInput.value = "";
  renderPalette("");
  palInput.focus();
}
function closePalette() { palette.hidden = true; }
function renderPalette(q) {
  const needle = q.trim().toLowerCase();
  const items = PALETTE_ACTIONS.filter(a =>
    !needle || a.t.toLowerCase().includes(needle));
  palSel = 0;
  palList.innerHTML = "";
  items.forEach((a, i) => {
    const li = document.createElement("li");
    if (i === 0) li.className = "sel";
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<span>→ ${escapeHtml(a.t)}</span>` +
                  `<span class="pal-k">${escapeHtml(a.k || "")}</span>`;
    b.addEventListener("click", a.run);
    li.appendChild(b);
    palList.appendChild(li);
  });
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "sb-empty";
    li.style.padding = "10px 12px";
    li.textContent = "No results found";
    palList.appendChild(li);
  }
}
palInput.addEventListener("input", () => renderPalette(palInput.value));
palInput.addEventListener("keydown", (e) => {
  const items = [...palList.querySelectorAll("li")];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!items.length) return;
    items[palSel]?.classList.remove("sel");
    palSel = (palSel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[palSel]?.classList.add("sel");
    items[palSel]?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    e.preventDefault();
    items[palSel]?.querySelector("button")?.click();
  } else if (e.key === "Escape") {
    closePalette();
  }
});
palette.addEventListener("click", (e) => {
  if (e.target === palette) closePalette();
});
document.getElementById("paletteBtn").addEventListener("click", openPalette);

/* ------------------------------------------------------------------ */
/* microphone — hold to record -> /api/stt -> auto-send (unchanged)    */
/* ------------------------------------------------------------------ */
const micBtn = document.getElementById("micBtn");
let media = null, recorder = null, chunks = [], audioCtx = null,
    analyser = null, rafMic = 0, starting = false, wantStop = false;

function micLevelLoop() {
  if (!analyser) return;
  const buf = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  EV.setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
  rafMic = requestAnimationFrame(micLevelLoop);
}

function micHint(msg) {
  bubble("ev error", msg);
  EV.setState("idle");
}

async function startRec() {
  if (recorder || starting) return;
  wantStop = false;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        micHint("🎙 This browser or page cannot access the microphone. Open " +
          "http://127.0.0.1:8765 — microphone access is limited to localhost.");
    return;
  }
  starting = true;
  try {
    media = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    const src = audioCtx.createMediaStreamSource(media);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    EV.setState("listening");
    micLevelLoop();

    chunks = [];
    recorder = new MediaRecorder(media);
    recorder.ondataavailable =
      (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      cancelAnimationFrame(rafMic);
      const mime = recorder && recorder.mimeType;
      wantStop = false;
      media.getTracks().forEach((t) => t.stop());
      audioCtx.close();
      audioCtx = analyser = null;
      micBtn.classList.remove("rec");
      const blob = new Blob(chunks, { type: mime || "audio/webm" });
      recorder = null;
      if (!blob.size) { EV.setState("idle"); return; }
      EV.setState("thinking");
      try {
        const res = await fetch("/api/stt", {
          method: "POST",
          headers: { "Content-Type": blob.type || "audio/webm" },
          body: blob,
        });
        const out = await res.json();
        if (out.text) sendMessage(out.text);
        else if (out.error) micHint("🎙 Speech recognition error: " + out.error);
        else {
          bubble("ev error", "No speech detected. Try again.");
          EV.setState("idle");
        }
      } catch (e) {
        micHint("Speech recognition error: " + e.message);
      }
    };
    recorder.start();
    micBtn.classList.add("rec");
    if (wantStop) stopRec();   // released while the permission dialog was open
  } catch (e) {
    const hints = {
      NotAllowedError:
        "Microphone permission was denied. Click the 🔒/🎤 icon in the address bar, " +
        "allow access, and reload the page.",
      PermissionDeniedError:
        "Microphone permission was denied. Allow access in your browser's site settings.",
      NotFoundError:
        "No microphone found. Connect one or select it in your system sound settings.",
      NotReadableError: "The microphone is in use by another application.",
    };
    micHint("🎙 " + (hints[e.name] ||
      ("Could not access the microphone: " + (e.message || e.name))));
  } finally {
    starting = false;
  }
}

function stopRec() {
  if (recorder && recorder.state !== "inactive") recorder.stop();
  else wantStop = true;      // permission dialog still open — stop once up
}
micBtn.addEventListener("pointerdown", (e) => {
  try { micBtn.setPointerCapture(e.pointerId); } catch { /* ok */ }
  startRec();
});
micBtn.addEventListener("pointerup", stopRec);
micBtn.addEventListener("pointercancel", stopRec);

/* ------------------------------------------------------------------ */
/* keyboard shortcuts (existing ones preserved)                        */
/* ------------------------------------------------------------------ */
addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target === document.body &&
      !recorder && !starting && palette.hidden) {
    e.preventDefault(); startRec();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    palette.hidden ? openPalette() : closePalette();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
    e.preventDefault(); toggleSidebar();
  }
  if (e.key === "/" && e.target === document.body) {
    e.preventDefault(); msgInput.focus();
  }
  if (e.key === "Escape" && palette.hidden) {
    if (EV.state === "thinking") stopGeneration();
    else closeModelMenu();
  }
});
addEventListener("keyup", (e) => {
  if (e.code === "Space" && (recorder || starting)) {
    e.preventDefault(); stopRec();
  }
});

/* ------------------------------------------------------------------ */
/* shared application settings                                         */
/* ------------------------------------------------------------------ */
const settingsBtn = document.getElementById("settingsBtn");
const settingsDialog = document.getElementById("settingsDialog");
const settingsTabs = document.getElementById("settingsTabs");
const settingsContent = document.getElementById("settingsContent");
const settingsNotice = document.getElementById("settingsNotice");
const settingsSave = document.getElementById("settingsSave");
const SETTINGS_SECTIONS = [
  ["agent", "Agent"], ["ollama", "Model and Ollama"],
  ["model_selection", "Model selection"], ["providers", "Providers"],
  ["voice", "Voice"], ["web", "Web HUD"], ["memory", "Memory"],
  ["tools", "Tools and MCP"], ["security", "Security"],
  ["logging", "Logs"], ["integrations", "Platform integrations"],
];
const SETTINGS_LABELS = {
  name: "Name", user_name: "User name", language: "Response language",
  max_react_iterations: "Maximum agent steps", timeout: "Timeout",
  advisory_auto_approve: "Advisory auto-approval", data_dir: "Data directory",
  turbo_threshold: "Fast-response threshold", host: "Host address",
  cloud_timeout: "Cloud model timeout", fallback: "Fallback model",
  keep_alive: "Model keep-alive", think: "Model reasoning",
  max_tokens: "Maximum output tokens", min_tokens: "Minimum output tokens",
  num_ctx: "Context size", models: "Models", fast: "Fast",
  main: "Main", vision: "Vision", default: "Default", mode: "Mode",
  fixed: "Fixed model", include_cloud: "Use cloud models",
  enabled: "Enabled", wake_words: "Wake words", stt_backend: "STT backend",
  stt_model: "STT model", tts_backend: "TTS backend", tts_voice: "TTS voice",
  tts_piper_model: "Piper model", port: "Port", short_term_max_messages: "Short-term memory window",
  long_term_db: "Long-term memory database", semantic: "Semantic memory",
  embed_model: "Embedding model", skills_top_k: "Relevant skills count",
  native: "Native tools", mcp: "MCP tools", mcp_dir: "MCP directory",
  priority: "Priority", tools: "Tools", threshold: "Threshold",
  server: "Server", needs_approval: "Requires approval", providers: "Providers",
  instances: "Instances", type: "Type", base_url: "API URL",
  api_key_env: "API key environment variable", model: "Model", temperature: "Temperature",
  preferred: "Preferred models", security: "Security",
  auto_approve_until_level: "Auto-approve through level",
  require_confirm_for_unknown_host: "Confirm unknown hosts",
  sudo_via_pkexec: "Graphical sudo prompt", dir: "Log directory",
  audit_enabled: "Audit logging", ollama: "Ollama", ashna: "Ashna AI",
  shell: "Shell", filesystem: "Filesystem", process: "Processes",
  services: "Services", gpu: "GPU", game_control: "Game control",
  browser: "Browser", agent: "Agent", model_selection: "Model selection",
  web: "Web HUD", memory: "Memory", tools: "Tools", logging: "Logs",
};
let settingsSnapshot = null;
let settingsSection = "agent";

function settingLabel(key) { return SETTINGS_LABELS[key] || key; }

function settingField(path, key, value) {
  const row = document.createElement("label");
  row.className = "settings-field";
  const title = document.createElement("span");
  title.textContent = settingLabel(key);
  const control = document.createElement(
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? "textarea" : (Array.isArray(value) ? "textarea" : "input"));
  control.dataset.settingPath = path;
  if (typeof value === "boolean") {
    control.type = "checkbox";
    control.checked = value;
  } else if (Array.isArray(value)) {
    control.value = JSON.stringify(value);
    control.dataset.valueType = "array";
  } else if (value !== null && typeof value === "object") {
    control.value = JSON.stringify(value, null, 2);
    control.dataset.valueType = "object";
  } else {
    control.type = "text";
    control.value = value === null ? "" : String(value);
    control.dataset.valueType = value === null ? "null" : typeof value;
    control.dir = "ltr";
  }
  const caption = document.createElement("small");
  caption.className = "settings-path";
  caption.textContent = path;
  const text = document.createElement("span");
  text.append(title, caption);
  row.append(text, control);
  return row;
}

function renderConfigObject(container, value, prefix) {
  for (const [key, child] of Object.entries(value || {})) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child !== null && typeof child === "object" && !Array.isArray(child)) {
      const section = document.createElement("section");
      section.className = "settings-section";
      const heading = document.createElement("h3");
      heading.textContent = settingLabel(key);
      section.appendChild(heading);
      renderConfigObject(section, child, path);
      container.appendChild(section);
    } else {
      container.appendChild(settingField(path, key, child));
    }
  }
}

function renderSettingsTabs() {
  settingsTabs.replaceChildren();
  for (const [id, label] of SETTINGS_SECTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "settings-tab" + (id === settingsSection ? " active" : "");
    button.textContent = label;
    button.setAttribute("aria-pressed", String(id === settingsSection));
    button.addEventListener("click", () => {
      settingsSection = id;
      renderSettings();
    });
    settingsTabs.appendChild(button);
  }
}

function renderConnections() {
  for (const connection of settingsSnapshot.connections || []) {
    const section = document.createElement("section");
    section.className = "settings-connection";
    const head = document.createElement("div");
    head.className = "settings-connection-head";
    const title = document.createElement("h3");
    title.textContent = connection.label;
    const state = document.createElement("span");
    state.className = "settings-connection-state" +
      (connection.configured ? " ready" : "");
    state.textContent = connection.configured ? "Configured" : "Needs setup";
    head.append(title, state);
    section.appendChild(head);
    for (const field of connection.fields) {
      const row = document.createElement("label");
      row.className = "settings-field";
      const label = document.createElement("span");
      label.textContent = field.label;
      const control = document.createElement("input");
      control.type = field.secret ? "password" : "text";
      control.autocomplete = field.secret ? "new-password" : "off";
      control.placeholder = field.secret
        ? (field.configured ? "Saved; enter a new value to replace" : "Key or token")
        : "";
      control.value = field.secret ? "" : field.value;
      control.dataset.credentialName = field.name;
      control.dataset.credentialSecret = String(field.secret);
      control.dir = "ltr";
      if (field.secret) {
        const wrap = document.createElement("div");
        wrap.className = "settings-secret-row";
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "settings-clear";
        clear.textContent = "Clear";
        clear.addEventListener("click", () => {
          control.value = "";
          control.dataset.clearCredential = "true";
        });
        control.addEventListener("input", () => {
          delete control.dataset.clearCredential;
        });
        wrap.append(control, clear);
        row.append(label, wrap);
      } else {
        row.append(label, control);
      }
      section.appendChild(row);
    }
    settingsContent.appendChild(section);
  }
  const note = document.createElement("p");
  note.className = "settings-connection-state";
  note.textContent = "This only checks whether settings exist; API connectivity is checked separately.";
  settingsContent.appendChild(note);
}

function renderSecuritySettings(container) {
  const security = settingsSnapshot.config.security || {};
  const section = document.createElement("section");
  section.className = "settings-section";
  const heading = document.createElement("h3");
  heading.textContent = "Automatic approval limit";
  const row = document.createElement("label");
  row.className = "settings-field";
  const title = document.createElement("span");
  title.textContent = "Approve automatically through";
  const select = document.createElement("select");
  select.dataset.settingPath = "security.auto_approve_until_level";
  select.dataset.valueType = "number";
  const choices = [
    [0, "Level 0 · read-only"],
    [1, "Level 1 · workspace writes"],
    [2, "Level 2 · system actions"],
    [3, "Level 3 · still requires approval"],
    [4, "Level 4 · still requires approval"],
  ];
  for (const [value, label] of choices) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label;
    select.appendChild(option);
  }
  select.value = String(security.auto_approve_until_level ?? 2);
  const caption = document.createElement("small");
  caption.className = "settings-path";
  caption.textContent = "security.auto_approve_until_level";
  const labelWrap = document.createElement("span");
  labelWrap.append(title, caption);
  row.append(labelWrap, select);
  section.append(heading, row);
  const note = document.createElement("p");
  note.className = "settings-voice-help";
  note.textContent = "Levels 3 and 4 always require explicit approval. Commands using sudo separately request your system password: a graphical system prompt in the HUD, or a hidden prompt in the terminal.";
  section.appendChild(note);
  container.appendChild(section);

  const otherSettings = { ...security };
  delete otherSettings.auto_approve_until_level;
  if (Object.keys(otherSettings).length) {
    renderConfigObject(container, { security: otherSettings }, "");
  }
}

function voiceButton(label, action, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `settings-voice-button ${className}`.trim();
  button.textContent = label;
  button.addEventListener("click", action);
  return button;
}

async function voiceApi(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Voice request failed");
  return body;
}

function renderVoicePanel() {
  const diagnostics = document.createElement("section");
  diagnostics.className = "settings-section";
  const heading = document.createElement("h3");
  heading.textContent = "Voice diagnostics and components";
  const status = document.createElement("pre");
  status.className = "settings-voice-status";
  status.textContent = "Loading local audio devices and installed models…";
  const actions = document.createElement("div");
  actions.className = "settings-voice-actions";
  const refresh = voiceButton("Refresh diagnostics", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    await refreshVoiceDiagnostics();
    button.disabled = false;
  });
  actions.appendChild(refresh);
  diagnostics.append(heading, status, actions);
  settingsContent.appendChild(diagnostics);
  refreshVoiceDiagnostics();

  const installs = document.createElement("section");
  installs.className = "settings-section";
  const installHeading = document.createElement("h3");
  installHeading.textContent = "Optional voice components";
  const installHelp = document.createElement("p");
  installHelp.className = "settings-voice-help";
  installHelp.textContent = "Downloads and package installs require a separate confirmation.";
  const installActions = document.createElement("div");
  installActions.className = "settings-voice-actions";
  const components = [
    ["vosk_en_small", "Install English Vosk model"],
    ["faster_whisper", "Install multilingual Faster-Whisper"],
    ["piper", "Install Piper TTS"],
    ["gemini_live", "Install Gemini Live support"],
  ];
  for (const [component, label] of components) {
    installActions.appendChild(voiceButton(label, async event => {
      if (!window.confirm(`${label} may download software or a model. Continue?`)) return;
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const result = await voiceApi("/api/voice/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ component, confirmed: true }),
        });
        settingsNotice.textContent = `Installed ${component}: ${result.result.status}`;
        settingsNotice.classList.remove("error");
        await refreshVoiceDiagnostics();
      } catch (error) {
        settingsNotice.textContent = error.message;
        settingsNotice.classList.add("error");
      } finally {
        button.disabled = false;
      }
    }));
  }
  installs.append(installHeading, installHelp, installActions);
  settingsContent.appendChild(installs);

  const credentials = document.createElement("section");
  credentials.className = "settings-section";
  const credentialsHeading = document.createElement("h3");
  credentialsHeading.textContent = "Gemini Live credential";
  const credentialsHelp = document.createElement("p");
  credentialsHelp.className = "settings-voice-help";
  credentialsHelp.textContent =
    "The key is stored in the OS keyring or encrypted vault, never in settings or .env. Testing makes a metadata request only; it does not start a live audio session.";
  const keyLabel = document.createElement("label");
  keyLabel.className = "settings-voice-key";
  const keyCaption = document.createElement("span");
  keyCaption.textContent = "API key";
  const keyInput = document.createElement("input");
  keyInput.type = "password";
  keyInput.autocomplete = "new-password";
  keyInput.placeholder = "Enter key; saved key is never shown";
  keyInput.dir = "ltr";
  keyLabel.append(keyCaption, keyInput);
  const keyStatus = document.createElement("p");
  keyStatus.className = "settings-voice-help";
  const keyActions = document.createElement("div");
  keyActions.className = "settings-voice-actions";
  keyActions.append(
    voiceButton("Save key", async event => {
      if (!keyInput.value) {
        keyStatus.textContent = "Enter a key to save.";
        return;
      }
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await voiceApi("/api/voice/secret", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "GEMINI_API_KEY", value: keyInput.value }),
        });
        keyInput.value = "";
        keyStatus.textContent = "Key saved securely. Live remains disabled until explicitly configured.";
        keyStatus.classList.remove("error");
        await refreshVoiceDiagnostics();
      } catch (error) {
        keyStatus.textContent = error.message;
        keyStatus.classList.add("error");
      } finally {
        button.disabled = false;
      }
    }),
    voiceButton("Test key", async event => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const result = await voiceApi("/api/voice/secret/test", {
          method: "POST",
        });
        keyStatus.textContent = result.ok
          ? `Credential validated for ${result.model || "Gemini Live"}. No audio was sent.`
          : (result.error || "Credential validation failed.");
        keyStatus.classList.toggle("error", !result.ok);
        await refreshVoiceDiagnostics();
      } catch (error) {
        keyStatus.textContent = error.message;
        keyStatus.classList.add("error");
      } finally {
        button.disabled = false;
      }
    }),
    voiceButton("Remove key", async event => {
      if (!window.confirm("Remove the stored Gemini API key?")) return;
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await voiceApi("/api/voice/secret", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "GEMINI_API_KEY", action: "delete" }),
        });
        keyStatus.textContent = "Stored key removed.";
        keyStatus.classList.remove("error");
        await refreshVoiceDiagnostics();
      } catch (error) {
        keyStatus.textContent = error.message;
        keyStatus.classList.add("error");
      } finally {
        button.disabled = false;
      }
    }, "secondary"),
  );
  credentials.append(credentialsHeading, credentialsHelp, keyLabel, keyStatus, keyActions);
  settingsContent.appendChild(credentials);
}

async function refreshVoiceDiagnostics() {
  const status = settingsContent.querySelector(".settings-voice-status");
  if (!status) return;
  try {
    const report = await voiceApi("/api/voice/health");
    const audio = report.hardware.audio || {};
    const recommendation = report.recommendation || {};
    const installation = report.installation || {};
    status.textContent = [
      `Mode: ${report.operating_mode || "unknown"} / ${report.voice?.mode || "unknown"}`,
      `Capture: ${audio.capture_backend || "unavailable"}; playback: ${audio.playback_backend || "unavailable"}`,
      `Audio devices: ${(audio.alsa_cards || []).join(", ") || "none detected"}`,
      `GPU: ${(report.hardware.gpus || []).map(device => device.name || device.vendor).join(", ") || "not detected"}`,
      `ASR: ${recommendation.asr?.provider || "unknown"} (${recommendation.asr?.state || "unknown"})`,
      `TTS: ${recommendation.tts?.provider || "unknown"} (${recommendation.tts?.state || "unknown"})`,
      `Secure store: ${report.secret_store?.backend || "unavailable"}${report.secret_store?.available ? "" : " (not ready)"}`,
      `Live: ${report.live?.enabled ? "enabled" : "disabled"}; key ${report.live?.gemini_key_configured ? "configured" : "not configured"}`,
      `Packages: ${Object.entries(installation.packages || {}).map(([name, item]) => `${name} ${item.installed ? "installed" : "missing"}`).join("; ") || "unavailable"}`,
      `Models: ${Object.entries(installation.models || {}).map(([name, item]) => `${name} ${item.installed ? "installed" : "missing"}`).join("; ") || "unavailable"}`,
    ].join("\n");
  } catch (error) {
    status.textContent = error.message;
  }
}

function renderSettings() {
  if (!settingsSnapshot) return;
  renderSettingsTabs();
  settingsContent.replaceChildren();
  if (settingsSection === "integrations") {
    renderConnections();
  } else if (settingsSection === "security") {
    renderSecuritySettings(settingsContent);
  } else {
    renderConfigObject(settingsContent, {
      [settingsSection]: settingsSnapshot.config[settingsSection],
    }, "");
    if (settingsSection === "voice") renderVoicePanel();
  }
  settingsNotice.textContent = "";
  settingsNotice.classList.remove("error");
}

async function loadSettings() {
  settingsNotice.textContent = "Loading…";
  const response = await fetch("/api/settings");
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Could not load settings");
  settingsSnapshot = body;
  renderSettings();
}

function readSettingsForm() {
  if (settingsSection === "integrations") {
    const credentials = {};
    for (const input of settingsContent.querySelectorAll("[data-credential-name]")) {
      const isSecret = input.dataset.credentialSecret === "true";
      if (input.dataset.clearCredential === "true") {
        credentials[input.dataset.credentialName] = "";
      } else if (!isSecret || input.value) {
        credentials[input.dataset.credentialName] = input.value;
      }
    }
    return { credentials };
  }
  const config = {};
  for (const input of settingsContent.querySelectorAll("[data-setting-path]")) {
    const type = input.dataset.valueType;
    let value;
    if (input.type === "checkbox") value = input.checked;
    else if (type === "array" || type === "object") value = JSON.parse(input.value);
    else if (type === "number") value = Number(input.value);
    else if (type === "null") value = input.value === "" ? null : input.value;
    else value = input.value;
    config[input.dataset.settingPath] = value;
  }
  return { config };
}

settingsBtn.addEventListener("click", async () => {
  settingsDialog.showModal();
  try { await loadSettings(); }
  catch (error) {
    settingsNotice.textContent = error.message;
    settingsNotice.classList.add("error");
  }
});
document.getElementById("settingsClose").addEventListener("click", () => settingsDialog.close());
settingsDialog.addEventListener("click", event => {
  if (event.target === settingsDialog) settingsDialog.close();
});
settingsSave.addEventListener("click", async () => {
  settingsSave.disabled = true;
  settingsNotice.textContent = "Saving…";
  settingsNotice.classList.remove("error");
  try {
    const response = await fetch("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readSettingsForm()),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Could not save settings");
    settingsSnapshot = body;
    renderSettings();
    settingsNotice.textContent = body.restart_required
      ? "Saved. Restart E.V. to apply these settings."
      : "Saved and applied.";
  } catch (error) {
    settingsNotice.textContent = error.message;
    settingsNotice.classList.add("error");
  } finally {
    settingsSave.disabled = false;
  }
});

/* ------------------------------------------------------------------ */
/* clock, host info, init                                              */
/* ------------------------------------------------------------------ */
setInterval(() => {
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString("en-US");
}, 1000);
migrateTasks();
renderSessions();
pollStatus();
setInterval(pollStatus, 2000);
pollBrief();
setInterval(pollBrief, 60000);
EV.setState("idle");
