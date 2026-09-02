/* E.V. HUD — reactive JARVIS-style front-end (vanilla JS, no deps) */
"use strict";

/* ------------------------------------------------------------------ */
/* global state + tiny pub-sub                                         */
/* ------------------------------------------------------------------ */
const EV = {
  state: "idle",
  level: 0.12,              // waveform energy 0..1
  tts: localStorage.ev_tts !== "off",
  setState(s) {
    this.state = s;
    document.body.dataset.state = s;
    const labels = { idle: "آماده", listening: "در حال شنیدن",
      thinking: "در حال فکر", speaking: "در حال صحبت",
      awaiting: "در انتظار تأیید", error: "خطا" };
    document.getElementById("stateBadge").textContent = labels[s] || s;
  },
  setLevel(v) { this.level = Math.max(0, Math.min(1, v)); },
};

const STATE_COLOR = {
  idle: "#19e3ff", listening: "#ffb020", thinking: "#7af0ff",
  speaking: "#8dff9b", awaiting: "#ffb020", error: "#ff5470",
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
    "HUD INTERFACE … ACTIVE",
  ];
  const box = document.getElementById("bootLines");
  let i = 0;
  const tick = () => {
    if (i < lines.length) {
      const d = document.createElement("div");
      d.textContent = "> " + lines[i++];
      box.appendChild(d);
      setTimeout(tick, 260);
    } else {
      setTimeout(() => document.getElementById("boot").classList.add("done"),
                 420);
    }
  };
  setTimeout(tick, 200);
})();

/* ------------------------------------------------------------------ */
/* starfield background                                                */
/* ------------------------------------------------------------------ */
(function starfield() {
  const cv = document.getElementById("stars");
  const cx = cv.getContext("2d");
  let W, H, stars = [];
  function resize() {
    W = cv.width = innerWidth;
    H = cv.height = innerHeight;
    stars = Array.from({ length: 140 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      z: Math.random() * 0.8 + 0.2, tw: Math.random() * Math.PI * 2,
    }));
  }
  addEventListener("resize", resize);
  resize();
  (function draw(t) {
    cx.clearRect(0, 0, W, H);
    for (const s of stars) {
      s.y += s.z * 0.12;
      if (s.y > H) { s.y = 0; s.x = Math.random() * W; }
      const a = 0.25 + 0.55 * Math.abs(Math.sin(t / 900 + s.tw));
      cx.fillStyle = `rgba(120,220,255,${(a * s.z).toFixed(3)})`;
      cx.fillRect(s.x, s.y, s.z * 1.7, s.z * 1.7);
    }
    requestAnimationFrame(draw);
  })(0);
})();

/* ------------------------------------------------------------------ */
/* central core — orbiting particles                                   */
/* ------------------------------------------------------------------ */
(function core() {
  const cv = document.getElementById("core");
  const cx = cv.getContext("2d");
  let W, H, parts = [];
  function resize() {
    W = cv.width = cv.clientWidth * devicePixelRatio;
    H = cv.height = cv.clientHeight * devicePixelRatio;
    parts = Array.from({ length: 90 }, () => ({
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
/* waveform strip under the core                                       */
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
    cx.lineWidth = 1.6 * devicePixelRatio;
    cx.shadowColor = col;
    cx.shadowBlur = 8 * devicePixelRatio;
    cx.stroke();
    cx.shadowBlur = 0;
    const target = { idle: 0.12, listening: EV.level, thinking: 0.35,
                     speaking: EV.level, awaiting: 0.5,
                     error: 0.2 }[EV.state] ?? 0.12;
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
function bubble(cls, text) {
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
        ? r.stderr.trim().split("\n").pop().slice(0, 80)
        : (typeof r.stdout === "string" ? r.stdout.trim().split("\n").pop().slice(0, 80) : "");
      return "exit=" + r.exit_code + (tail ? " " + tail : "");
    }
    if (Array.isArray(r.entries)) return r.entries.length + " مورد یافت شد";
    const s = JSON.stringify(r);
    return s ? s.slice(0, 110) : "";
  }
  return String(r).slice(0, 110);
}
function addStep(info) {
  const ul = document.getElementById("stepFeed");
  const li = document.createElement("li");
  const tool = info.tool || info.step || "tool";
  const args = typeof info.args === "object" && info.args
    ? JSON.stringify(info.args) : (info.args || "");
  if (info.phase === "start") {
    const msg = info.message || ("الان دارم «" + tool + "» را اجرا می‌کنم...");
    li.innerHTML = `⏳ <b>${escapeHtml(tool)}</b> ${escapeHtml(msg)}` +
      `<small>${escapeHtml(String(args)).slice(0, 90)}</small>`;
    ul.prepend(li);
    while (ul.children.length > 30) ul.lastChild.remove();
    // mirror into the main chat log so the progress is unmissable
    bubble("ev", "⚙️ " + msg);
    return;
  }
  if (info.phase === "progress") {
    li.innerHTML = `⏳ <b>${escapeHtml(tool)}</b> ${escapeHtml(info.message || "هنوز در حال انجام...")}`;
    ul.prepend(li);
    while (ul.children.length > 30) ul.lastChild.remove();
    return;
  }
  li.innerHTML = `✅ <b>${escapeHtml(tool)}</b> ${escapeHtml(String(args)).slice(0, 90)}` +
    `<small>${escapeHtml(briefResult(info.result))}</small>`;
  ul.prepend(li);
  while (ul.children.length > 30) ul.lastChild.remove();
}
function escapeHtml(s) {
  return s.replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
            '"': "&quot;", "'": "&#39;" }[c]));
}
/* server JSON-encodes SSE payloads; token/state carry plain strings —
   unwrap them so the chat shows the text, not `{"t": "..."}` quotes.  */
function unjson(s) {
  try {
    const v = JSON.parse(s);
    if (typeof v === "string") return v;
    if (v && typeof v.t === "string") return v.t;
  } catch { /* plain text */ }
  return s;
}

/* server asks for a Level-3/4 approval — render the card in the chat log */
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
    `<div class="perm-action">${escapeHtml(p.action || "")}</div>` +
    `<pre class="perm-args">${escapeHtml(args).slice(0, 400)}</pre>` +
    `<div class="perm-btns">
       <button class="ok">تأیید ✅</button>
       <button class="no">رد ❌</button>
       <span class="perm-timer"></span>
     </div>`;
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
      `<span>${allow ? "✅ تأیید شد — در حال اجرا…"
                     : expired ? "⌛ منقضی شد — رد گردید" : "❌ رد شد"}</span>`;
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
/* chat — POST /api/chat and consume the SSE stream                    */
/* ------------------------------------------------------------------ */
async function sendMessage(text) {
  if (!text || EV.state === "thinking") return;
  bubble("user", text);
  EV.setState("thinking");

  let evBubble = null, acc = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
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
    EV.setState("error");
    bubble("ev error", "خطای ارتباط با سرور: " + e.message);
    setTimeout(() => EV.setState("idle"), 2500);
    return;
  }
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
      EV.setState("idle");
      speak(answer);
    }
  }
}

document.getElementById("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const inp = document.getElementById("msg");
  const text = inp.value.trim();
  if (!text) return;
  inp.value = "";
  sendMessage(text);
});


/* ------------------------------------------------------------------ */
/* status polling + gauges                                             */
/* ------------------------------------------------------------------ */
function setMeter(barId, valId, pct, txt) {
  const bar = document.getElementById(barId);
  bar.style.width = (pct ?? 0) + "%";
  bar.classList.toggle("hot", (pct ?? 0) > 85);   // amber when nearly full
  document.getElementById(valId).textContent = txt;
}
async function pollStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    setMeter("mCpu", "vCpu", s.cpu, s.cpu != null ? s.cpu + "%" : "–");
    setMeter("mRam", "vRam", s.ram.percent, s.ram.percent + "%");
    if (s.gpu && s.gpu.available === false) {
      document.getElementById("gpuTemp").textContent = "GPU: در دسترس نیست";
    } else if (s.gpu && s.gpu.percent != null) {
      setMeter("mGpu", "vGpu", s.gpu.percent, s.gpu.percent + "%");
      const temp = s.gpu.temp != null ? "GPU: " + s.gpu.temp + "°C" : "GPU: فعال";
      document.getElementById("gpuTemp").textContent = temp;
      if (s.gpu.vram != null)
        setMeter("mVram", "vVram", s.gpu.vram.percent ?? 0,
                 (s.gpu.vram.percent ?? 0) + "%");
    }
    if (s.disk && s.disk.percent != null)
      setMeter("mDisk", "vDisk", s.disk.percent, s.disk.percent + "%");
    syncModelSelect(s.model);
  } catch { /* server briefly busy — retry next tick */ }
}

/* ------------------------------------------------------------------ */
/* model selector                                                      */
/* ------------------------------------------------------------------ */
const modelSel = document.getElementById("modelSel");
let modelSync = false;
function syncModelSelect(info) {
  if (!info || document.activeElement === modelSel || modelSync) return;
  modelSync = true;
  const opts = new Set(["auto", ...(info.pool || []), ...(info.available || [])]);
  const current = info.mode === "fixed" && info.current ? info.current : "auto";
  modelSel.innerHTML = "";
  for (const m of opts) {
    const o = document.createElement("option");
    o.value = m;
    o.textContent = m === "auto" ? "— auto —" : m;
    if (m === current) o.selected = true;
    modelSel.appendChild(o);
  }
  modelSync = false;
}
modelSel.addEventListener("change", async () => {
  const body = await (await fetch("/api/model", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: modelSel.value }),
  })).json();
  syncModelSelect(body);
});

/* ------------------------------------------------------------------ */
/* TTS — POST /api/tts and play the returned audio                     */
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
/* theme — dark (default) / light, persisted in localStorage           */
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
/* microphone — hold to record -> /api/stt -> auto-send                */
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
addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target === document.body &&
      !recorder && !starting) {
    e.preventDefault(); startRec();
  }
  // Ctrl+K (or "/") — jump to the composer, like every modern console
  if ((e.ctrlKey && e.key.toLowerCase() === "k") ||
      (e.key === "/" && e.target === document.body)) {
    e.preventDefault();
    document.getElementById("msg").focus();
  }
});
addEventListener("keyup", (e) => {
  if (e.code === "Space" && (recorder || starting)) {
    e.preventDefault(); stopRec();
  }
});

/* ------------------------------------------------------------------ */
/* clock, host info, boot                                              */
/* ------------------------------------------------------------------ */
setInterval(() => {
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString("fa-IR");
}, 1000);
fetch("/api/status").then(r => r.json()).then(s => {
  document.getElementById("hostInfo").textContent =
    "E.V. HUD — " + (s.model?.current || s.model?.mode || "auto");
}).catch(() => {});
pollStatus();
setInterval(pollStatus, 2000);
EV.setState("idle");
