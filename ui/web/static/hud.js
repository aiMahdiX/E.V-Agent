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
  ts.textContent = new Date().toLocaleTimeString("fa-IR",
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
    if (r.blocked) return "مسدود شد: " + String(r.error || "");
    if (r.error) return "خطا: " + String(r.error);
    if (r.description) return String(r.description);
    if (r.exit_code != null) {
      const tail = (typeof r.stderr === "string" && r.stderr.trim())
        ? r.stderr.trim().split("\n").pop().slice(0, 90)
        : (typeof r.stdout === "string"
           ? r.stdout.trim().split("\n").pop().slice(0, 90) : "");
      return "exit=" + r.exit_code + (tail ? " " + tail : "");
    }
    if (Array.isArray(r.entries)) return r.entries.length + " مورد یافت شد";
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
    `<b>E.V. در حال کار</b><span class="act-meta"></span></div>` +
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
    ok === false ? "E.V. — متوقف شد" : "انجام شد";
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
    // the Persian announcement IS the key live detail (it embeds the
    // command) — surface it directly, don't hide it behind the expander
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
      const msg = info.message || "هنوز در حال اجرا…";
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
const LEVEL_FA = { 0: "بی‌خطر", 1: "نوشتن", 2: "سیستمی",
  3: "دسترسی ویژه (root)", 4: "مخرب" };
function showPermission(p) {
  EV.setState("awaiting");
  const card = bubble("perm", "");
  const args = (typeof p.args === "object" && p.args)
    ? JSON.stringify(p.args) : String(p.args ?? "");
  card.innerHTML =
    `<div class="perm-head">⚠️ مجوز لازم است — سطح ${Number(p.level) || 0} (${
      escapeHtml(p.level_name || LEVEL_FA[p.level] || "")})</div>` +
    `<div class="perm-action">E.V. می‌خواهد اجرا کند:</div>` +
    `<pre class="perm-args">${escapeHtml(args).slice(0, 400)}</pre>` +
    `<div class="perm-btns">` +
    `<button class="no">رد</button>` +
    `<button class="ok">اجازه</button>` +
    `<span class="perm-timer"></span></div>`;
  const ok = card.querySelector(".ok"), no = card.querySelector(".no");
  const timer = card.querySelector(".perm-timer");
  let left = Math.max(30, Math.min(300, (p.timeout || 180) | 0));
  const iv = setInterval(() => {
    left -= 1;
    if (timer) timer.textContent = "انقضا: " + left + " ثانیه";
    if (left <= 0) answer(false, true);
  }, 1000);
  async function answer(allow, expired) {
    clearInterval(iv);
    ok.disabled = no.disabled = true;
    card.classList.add(allow ? "granted" : "denied");
    card.querySelector(".perm-btns").innerHTML =
      `<span>${allow ? "✓ تأیید شد — در حال اجرا…"
                     : expired ? "⌛ منقضی شد — رد گردید" : "✕ رد شد"}</span>`;
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
function loadTasks() {
  try { return JSON.parse(localStorage.ev_tasks || "[]"); }
  catch { return []; }
}
function addTask(text) {
  const t = loadTasks();
  if (t[0] && t[0].text === text) return;
  t.unshift({ text: text.slice(0, 90), ts: Date.now() });
  localStorage.ev_tasks = JSON.stringify(t.slice(0, 25));
  renderTasks();
}
function renderTasks() {
  const ul = document.getElementById("taskList");
  const tasks = loadTasks();
  ul.innerHTML = "";
  if (!tasks.length) {
    const li = document.createElement("li");
    li.className = "sb-empty";
    li.textContent = "هنوز تسکی ثبت نشده";
    ul.appendChild(li);
    return;
  }
  const dayStart = new Date().setHours(0, 0, 0, 0);
  const today = tasks.filter(t => t.ts >= dayStart);
  const older = tasks.filter(t => t.ts < dayStart);
  const add = (list, label) => {
    if (!list.length) return;
    const h = document.createElement("li");
    h.className = "sb-empty";
    h.textContent = label;
    ul.appendChild(h);
    for (const t of list.slice(0, 7)) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.title = t.text;
      const s = document.createElement("span");
      s.textContent = "● " + t.text;
      b.appendChild(s);
      b.addEventListener("click", () => {
        const inp = document.getElementById("msg");
        inp.value = t.text;
        inp.focus();
        autogrow();
      });
      li.appendChild(b);
      ul.appendChild(li);
    }
  };
  add(today, "امروز");
  add(older, "قبلاً");
}

/* ------------------------------------------------------------------ */
/* chat — POST /api/chat + SSE stream (abortable with Esc)             */
/* ------------------------------------------------------------------ */
let currentAbort = null;

async function sendMessage(text) {
  text = String(text || "").trim();
  if (!text) return;
  if (EV.state === "thinking" || EV.state === "awaiting") return;
  bubble("user", text);
  addTask(text);
  EV.setState("thinking");
  activity = null;                       // fresh activity card per run

  const abort = new AbortController();
  currentAbort = abort;
  let evBubble = null, acc = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
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
      bubble("ev", "⏹ متوقف شد.");
      EV.setState("idle");
      currentAbort = null;
      return;
    }
    EV.setState("error");
    bubble("ev error", "خطای ارتباط با سرور: " + (e.message || e));
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
      bubble("ev error", "E.V. مشغول است — ابتدا با Esc متوقف کن.");
      return;
    }
    sendMessage(b.dataset.qa);
  });
});

/* new task — clears the conversation (history is kept) */
function newTask() {
  stopGeneration();
  log.innerHTML = "";
  activity = null;
  chatEl.classList.remove("has-msgs");
  if (EV.state !== "idle") EV.setState("idle");
  msgInput.focus();
}
document.getElementById("newTask").addEventListener("click", newTask);

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
  const locals = all.filter(m => !isCloud(m));
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
  if (clouds.length) {
    section("CLOUD · " + clouds.length);
    clouds.forEach(m => item(m, "Cloud · ollama.com"));
  }
  if (!all.length) {
    const d = document.createElement("div");
    d.className = "mm-empty";
    d.textContent = "مدل دیگری نصب نیست";
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
  } catch { modelName.textContent = "خطا"; }
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
  ttsBtn.title = EV.tts ? "خاموش کردن صدا" : "روشن کردن صدا";
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
  themeBtn.title = t === "light" ? "تم تاریک" : "تم روشن";
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
    bubble("ev error", "E.V. مشغول است — ابتدا با Esc متوقف کن.");
    return;
  }
  sendMessage(text);
}

const PALETTE_ACTIONS = [
  { t: "تسک جدید — پاک‌کردن گفتگو", k: "Ctrl+N", run: () => { closePalette(); newTask(); } },
  { t: "اسکرین‌شات از صفحهٔ فعلی", k: "tool", run: () =>
      sendQuick("یک اسکرین‌شات از صفحهٔ فعلی بگیر و نشانم بده") },
  { t: "عکس از دوربین", k: "tool", run: () =>
      sendQuick("از دوربین عکس بگیر و نشانم بده") },
  { t: "لیست فایل‌های پوشهٔ فعلی", k: "tool", run: () =>
      sendQuick("فایل‌های پوشهٔ فعلی را لیست کن") },
  { t: "وضعیت سیستم (CPU/RAM/GPU)", k: "tool", run: () =>
      sendQuick("وضعیت CPU، RAM و GPU را بررسی کن و خلاصه بگو") },
  { t: "تغییر مدل زبان", k: "model", run: () => { closePalette(); modelBtn.click(); } },
  { t: "تم روشن / تاریک", k: "theme", run: () => { closePalette(); themeBtn.click(); } },
  { t: "صدا روشن / خاموش (TTS)", k: "tts", run: () => { closePalette(); ttsBtn.click(); } },
  { t: "نمایش / پنهان‌سازی نوار کنار", k: "Ctrl+B", run: () => { closePalette(); toggleSidebar(); } },
  { t: "فوکوس به ورودی پیام", k: "/", run: () => { closePalette(); msgInput.focus(); } },
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
    li.textContent = "چیزی پیدا نشد";
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
    micHint("🎙 این مرورگر/آدرس اجازهٔ میکروفن نمی‌دهد. صفحه را با " +
            "http://127.0.0.1:8765 باز کن — میکروفن فقط روی localhost کار می‌کند.");
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
        else if (out.error) micHint("🎙 خطای STT: " + out.error);
        else {
          bubble("ev error", "صدا شنیده نشد — دوباره تلاش کن.");
          EV.setState("idle");
        }
      } catch (e) {
        micHint("خطای STT: " + e.message);
      }
    };
    recorder.start();
    micBtn.classList.add("rec");
    if (wantStop) stopRec();   // released while the permission dialog was open
  } catch (e) {
    const hints = {
      NotAllowedError:
        "مجوز میکروفن رد شده — روی آیکون 🔒/🎤 در نوار آدرس کلیک کن، " +
        "اجازه را روی Allow بگذار و صفحه را رفرش کن.",
      PermissionDeniedError:
        "مجوز میکروفن رد شده — از تنظیمات سایت مرورگر Allow کن.",
      NotFoundError:
        "هیچ میکروفنی پیدا نشد — میکروفن را وصل کن یا از تنظیمات صدا سیستم انتخابش کن.",
      NotReadableError: "میکروفن توسط برنامهٔ دیگری اشغال است.",
    };
    micHint("🎙 " + (hints[e.name] ||
      ("دسترسی به میکروفن ممکن نشد: " + (e.message || e.name))));
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
/* clock, host info, init                                              */
/* ------------------------------------------------------------------ */
setInterval(() => {
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString("fa-IR");
}, 1000);
renderTasks();
pollStatus();
setInterval(pollStatus, 2000);
EV.setState("idle");
