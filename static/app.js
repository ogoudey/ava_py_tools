"use strict";

// Every input is a discrete edge (press or release) and every edge gets exactly one
// row in the event tape with its outcome. Nothing is sent unless control is taken.

const $ = (sel, root = document) => root.querySelector(sel);
const MAX_EVENTS = 250;
const FEEDBACK_INTERVAL_MS = 100;
const CAMERA_MAX_FPS = 20;
const LIVE_WINDOW_MS = 1000;

const state = {
  config: null,
  index: {},              // key -> {modality, action}
  armed: false,
  held: new Set(),        // keys currently down
  chains: new Map(),      // key -> promise, keeps press/release ordered per key
  cells: new Map(),       // key -> key cell element
  events: [],
  cseq: 0,
  counts: { sent: 0, ack: 0, failed: 0 },
  controllerOk: null,
  lastFrameAt: 0,
  lastFeedbackAt: 0,
  lastFeedback: null,
};

async function getJSON(url, opts = {}) {
  const r = await fetch(url, { cache: "no-store", ...opts });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const pad = (n, w = 2) => String(n).padStart(w, "0");
const clock = (d) =>
  `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;

// ---------------- Keys ---------------- //

const ROWS = ["1234567890", "qwertyuiop", "asdfghjkl;", "zxcvbnm,./"];
const STAGGER = [0, 0.5, 0.75, 1.25];   // physical row offsets, in key widths

function buildKeys(mapping) {
  state.index = {};
  for (const [modality, table] of Object.entries(mapping)) {
    for (const [k, action] of Object.entries(table)) state.index[k.toLowerCase()] = { modality, action };
  }

  const placed = [], extra = [];
  for (const k of Object.keys(state.index)) {
    const r = ROWS.findIndex((row) => row.includes(k));
    if (r >= 0) placed.push({ k, r, x: ROWS[r].indexOf(k) + STAGGER[r] });
    else extra.push(k);
  }

  const box = $("#keys");
  box.innerHTML = "";
  // Quarter-key grid so staggered rows line up like a real keyboard
  if (placed.length) {
    const minX = Math.min(...placed.map((p) => p.x));
    const maxX = Math.max(...placed.map((p) => p.x));
    const minR = Math.min(...placed.map((p) => p.r));
    box.style.gridTemplateColumns = `repeat(${Math.round((maxX - minX + 1) * 4)}, 1fr)`;
    for (const p of placed) {
      const cell = keyCell(p.k);
      cell.style.gridColumn = `${Math.round((p.x - minX) * 4) + 1} / span 4`;
      cell.style.gridRow = `${p.r - minR + 1}`;
      box.append(cell);
    }
  }
  if (extra.length) {
    const row = document.createElement("div");
    row.className = "keys-extra";
    extra.forEach((k) => row.append(keyCell(k)));
    box.after(row);
  }
}

function keyCell(k) {
  const { action } = state.index[k];
  const cell = document.createElement("div");
  cell.className = "key";
  cell.dataset.held = "false";
  cell.innerHTML = `<kbd>${k === " " ? "Space" : k.toUpperCase()}</kbd><span class="action"></span><i class="result" aria-hidden="true"></i>`;
  cell.querySelector(".action").textContent = action;
  state.cells.set(k, cell);
  return cell;
}

function keyLabel(k) {
  return k === " " ? "Space" : k.length === 1 ? k.toUpperCase() : k;
}

// ---------------- Control ---------------- //

function setArmed(armed, reason) {
  if (!armed) releaseAll(reason);
  state.armed = armed;
  document.body.dataset.armed = String(armed);
  $("#arm .arm-label").textContent = armed ? "Release control" : "Take control";
  $("#arm kbd").textContent = armed ? "Esc" : "Enter";
  $("#key-hint").textContent = armed
    ? "Hold a key to move, let go to stop. Esc stops everything and releases control."
    : "Commands are not being sent. Press Enter or Take control to drive.";
}

function releaseAll(reason) {
  for (const k of [...state.held]) {
    state.held.delete(k);
    paintHeld(k);
    emit(k, "release", reason);
  }
}

function emit(key, edge, note) {
  const binding = state.index[key];
  const ev = {
    cseq: ++state.cseq, key, edge, note,
    action: binding ? binding.action : null,
    status: binding ? "pending" : "unmapped",
    wall: new Date(), t0: performance.now(),
  };
  addEvent(ev);
  if (!binding) return;
  state.counts.sent++;
  const prev = state.chains.get(key) || Promise.resolve();
  const next = prev.then(() => post(ev));
  state.chains.set(key, next.catch(() => {}));
}

async function post(ev) {
  try {
    const r = await getJSON("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: ev.key, edge: ev.edge, client_seq: ev.cseq }),
      keepalive: true,
    });
    Object.assign(ev, { seq: r.seq, status: r.status, detail: r.detail, ms: r.ms, attempts: r.attempts });
  } catch (e) {
    Object.assign(ev, { status: "unreachable", detail: "teleop server did not answer" });
  }
  if (ev.status === "ack") state.counts.ack++;
  else state.counts.failed++;
  if (ev.status === "ack") state.controllerOk = true;
  else if (ev.status === "unreachable") state.controllerOk = false;
  updateEvent(ev);
  const cell = state.cells.get(ev.key);
  if (cell) cell.dataset.result = ev.status;
}

function paintHeld(k) {
  const cell = state.cells.get(k);
  if (cell) cell.dataset.held = String(state.held.has(k));
}

function isTypingTarget(el) {
  return el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

window.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;

  if (e.key === "Escape") {
    e.preventDefault();
    if (state.armed) setArmed(false, "Esc");
    return;
  }
  if (!state.armed) {
    if (e.key === "Enter") { e.preventDefault(); setArmed(true); }
    return;
  }

  const k = e.key.toLowerCase();
  if (state.index[k]) e.preventDefault();
  if (e.repeat || state.held.has(k)) return;   // one press = one event; ignore OS auto-repeat
  if (!state.index[k]) { emit(k, "press"); return; }   // logged as unmapped, nothing sent
  state.held.add(k);
  paintHeld(k);
  emit(k, "press");
});

window.addEventListener("keyup", (e) => {
  const k = e.key.toLowerCase();
  if (!state.held.has(k)) return;
  state.held.delete(k);
  paintHeld(k);
  emit(k, "release");
});

// Keys released while the page lacks focus never produce keyup, so stop them now
window.addEventListener("blur", () => state.armed && setArmed(false, "window lost focus"));
document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.armed) setArmed(false, "tab hidden");
});

$("#arm").addEventListener("click", (e) => {
  setArmed(!state.armed, "released from button");
  e.currentTarget.blur();   // so Enter/Space don't re-trigger the button
});

// ---------------- Event tape ---------------- //

const RESULT_TEXT = {
  pending: "sending",
  ack: "acknowledged",
  rejected: "rejected",
  timeout: "timed out",
  unreachable: "unreachable",
  unmapped: "not bound",
};

function addEvent(ev) {
  const tr = document.createElement("tr");
  ev.row = tr;
  state.events.unshift(ev);
  $("#tape").prepend(tr);
  if (state.events.length > MAX_EVENTS) state.events.pop().row.remove();
  $("#tape-empty").hidden = true;
  updateEvent(ev);
}

function updateEvent(ev) {
  const tr = ev.row;
  tr.dataset.status = ev.status;
  tr.dataset.edge = ev.edge;
  const result = RESULT_TEXT[ev.status] || ev.status;
  const detail = [ev.detail, ev.note, ev.attempts > 1 ? `${ev.attempts} attempts` : null].filter(Boolean).join("; ");
  tr.innerHTML = `
    <td class="num">${ev.seq ?? "–"}</td>
    <td class="mono">${clock(ev.wall)}</td>
    <td><kbd>${keyLabel(ev.key)}</kbd></td>
    <td>${ev.edge}</td>
    <td class="mono"></td>
    <td class="result-cell"><i aria-hidden="true"></i></td>
    <td class="num">${ev.ms != null ? ev.ms.toFixed(1) : ""}</td>`;
  tr.children[4].textContent = ev.action ?? "";
  tr.children[5].append(document.createTextNode(result));
  if (detail) tr.children[5].title = detail;
  const c = state.counts;
  $("#tape-meta").textContent = `${c.sent} sent, ${c.ack} acknowledged, ${c.failed} failed`;
}

// ---------------- Bindings ---------------- //

const SYNC_TEXT = {
  match: "matches",
  mismatch: "differs",
  missing_input: "not on server",
  missing_modality: "modality missing",
};

async function runSync() {
  const table = $("#sync"), summary = $("#sync-summary");
  summary.textContent = "checking";
  let report;
  try { report = await getJSON("/api/sync"); }
  catch { report = { reachable: false, error: "Teleop server did not answer.", bindings: [] }; }

  state.controllerOk = report.reachable;
  table.innerHTML = "";
  for (const cell of state.cells.values()) delete cell.dataset.sync;

  if (!report.reachable) {
    summary.textContent = "controller unreachable";
    table.innerHTML = `<tbody><tr><td class="error"></td></tr></tbody>`;
    table.querySelector(".error").textContent = report.error;
    return;
  }

  const ok = report.bindings.filter((b) => b.status === "match").length;
  summary.textContent = `${ok} of ${report.bindings.length} match`;
  table.innerHTML = `<thead><tr><th>Key</th><th>Sends</th><th>Server has</th><th>Status</th></tr></thead><tbody></tbody>`;
  const body = table.querySelector("tbody");
  for (const b of report.bindings) {
    const tr = document.createElement("tr");
    tr.dataset.status = b.status;
    tr.innerHTML = `<td><kbd></kbd></td><td class="mono"></td><td class="mono"></td><td class="result-cell"><i aria-hidden="true"></i></td>`;
    tr.querySelector("kbd").textContent = keyLabel(b.input);
    tr.children[1].textContent = b.expected;
    tr.children[2].textContent = b.actual ?? "–";
    tr.children[3].append(document.createTextNode(SYNC_TEXT[b.status] || b.status));
    body.append(tr);
    const cell = state.cells.get(b.input.toLowerCase());
    if (cell && b.status !== "match") cell.dataset.sync = b.status;
  }
}

$("#resync").addEventListener("click", runSync);

// ---------------- Camera ---------------- //

// ---- Zoom (shared by all cameras) ----
const ZOOM_LEVELS = [1, 1.5, 2, 3, 4];
const zoomListeners = [];
state.zoomIdx = 0;
try { state.zoomIdx = Math.min(ZOOM_LEVELS.length - 1, Math.max(0, Number(localStorage.getItem("ava.zoomIdx")) || 0)); } catch {}

function setZoom(idx) {
  idx = Math.min(ZOOM_LEVELS.length - 1, Math.max(0, idx));
  if (idx === state.zoomIdx) return;
  state.zoomIdx = idx;
  try { localStorage.setItem("ava.zoomIdx", String(idx)); } catch {}
  zoomListeners.forEach((fn) => fn());
}

// + / - zoom whether or not control is taken; handled before the drive keys so they
// never show up in the event log as unbound presses
window.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
  const step = { "+": 1, "=": 1, "-": -1, "_": -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (!e.repeat) setZoom(state.zoomIdx + step);
}, true);

async function startCamera(cam) {
  const fig = document.createElement("figure");
  fig.className = "cam";
  fig.innerHTML = `
    <div class="frame"><p class="cam-wait">Waiting for the first frame</p></div>
    <figcaption><span class="cam-name"></span><span class="cam-frame"></span><span class="cam-rate"></span><span class="cam-lat"></span><span class="cam-skip"></span>
      <span class="zoom"><button type="button" class="small" data-z="-1" aria-label="Zoom out">−</button><output class="zoom-level"></output><button type="button" class="small" data-z="1" aria-label="Zoom in">+</button></span></figcaption>`;
  fig.querySelector(".cam-name").textContent = cam;
  $("#cams").append(fig);
  const wait = fig.querySelector(".cam-wait");
  const set = (cls, text) => (fig.querySelector(cls).textContent = text);

  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", `${cam} camera`);
  fig.querySelector(".frame").append(canvas);
  const ctx = canvas.getContext("2d");

  // Zoom crops the center of the frame; the canvas is then scaled up to fill the panel
  let last = null;   // last ImageBitmap, kept so a zoom change redraws immediately
  const draw = () => {
    if (!last) return;
    const z = ZOOM_LEVELS[state.zoomIdx];
    const sw = last.width / z, sh = last.height / z;
    const w = Math.round(sw), h = Math.round(sh);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    ctx.drawImage(last, (last.width - sw) / 2, (last.height - sh) / 2, sw, sh, 0, 0, w, h);
  };
  const showZoom = () => (fig.querySelector(".zoom-level").textContent = `${ZOOM_LEVELS[state.zoomIdx]}×`);
  zoomListeners.push(() => { showZoom(); draw(); });
  showZoom();
  fig.querySelectorAll(".zoom button").forEach((b) =>
    b.addEventListener("click", (e) => { setZoom(state.zoomIdx + Number(b.dataset.z)); e.currentTarget.blur(); }));
  fig.querySelector(".frame").addEventListener("wheel", (e) => {
    e.preventDefault();
    setZoom(state.zoomIdx + (e.deltaY < 0 ? 1 : -1));
  }, { passive: false });

  // Frame numbers come from the feedback service. Ask only for frames newer than the
  // one on screen; frames that arrived there and were never shown here count as skipped.
  let shown = 0, skipped = 0;
  const arrivals = [];
  const minGap = 1000 / CAMERA_MAX_FPS;

  const pull = async () => {
    if (document.hidden) { setTimeout(pull, 250); return; }
    const t0 = performance.now();
    try {
      const r = await fetch(`/api/camera/${encodeURIComponent(cam)}/latest?after=${shown}`, { cache: "no-store" });
      if (r.status === 200) {
        const seq = Number(r.headers.get("X-Frame-Seq"));
        const age = Number(r.headers.get("X-Frame-Age-Ms"));
        const bmp = await createImageBitmap(await r.blob());
        if (last) last.close();
        last = bmp;
        draw();
        if (shown === 0) wait.remove();
        else if (seq > shown + 1) skipped += seq - shown - 1;
        shown = seq;
        const now = performance.now();
        state.lastFrameAt = now;
        arrivals.push(now);
        while (arrivals.length && now - arrivals[0] > 1000) arrivals.shift();
        set(".cam-frame", `frame ${seq}`);
        set(".cam-rate", `${arrivals.length} fps`);
        set(".cam-lat", `${Math.round(age + (now - t0))} ms old`);
        set(".cam-skip", skipped ? `${skipped} skipped` : "");
      } else if (r.status !== 204) {
        set(".cam-lat", `HTTP ${r.status}`);
        if (shown === 0) wait.textContent = `No frames from ${cam}: the feedback service answered HTTP ${r.status}.`;
        setTimeout(pull, 500);
        return;
      }
    } catch {
      if (shown === 0) wait.textContent = `No frames from ${cam} yet. Retrying.`;
      setTimeout(pull, 500);
      return;
    }
    setTimeout(pull, Math.max(0, minGap - (performance.now() - t0)));
  };
  pull();
}

// ---------------- Feedback ---------------- //

function flatten(obj, prefix = "", out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

function fmt(v) {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

async function pollFeedback() {
  if (!document.hidden) {
    try {
      const r = await getJSON("/api/feedback");
      if (r.status === "ok") {
        state.lastFeedbackAt = performance.now();
        renderFeedback(r);
      } else {
        $("#fb-meta").textContent = `sample ${r.seq}: ${r.detail || r.status}`;
      }
    } catch {
      $("#fb-meta").textContent = "teleop server did not answer";
    }
  }
  setTimeout(pollFeedback, FEEDBACK_INTERVAL_MS);
}

function renderFeedback(r) {
  const data = r.data && typeof r.data === "object" && !Array.isArray(r.data) ? flatten(r.data) : { value: r.data };
  const prev = state.lastFeedback || {};
  const dl = $("#fb");
  dl.innerHTML = "";
  for (const [k, v] of Object.entries(data)) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = k;
    dd.textContent = fmt(v);
    // Mark values that differ from the previous sample
    if (k in prev && fmt(prev[k]) !== fmt(v)) dd.dataset.changed = "true";
    dl.append(dt, dd);
  }
  state.lastFeedback = data;
  $("#fb-meta").textContent = `sample ${r.seq}, ${r.ms.toFixed(1)} ms`;
}

// ---------------- Connection lights ---------------- //

function paintLinks() {
  const now = performance.now();
  const set = (id, ok) => ($(id).dataset.ok = ok === null ? "unknown" : String(ok));
  set("#link-controller", state.controllerOk);
  set("#link-camera", now - state.lastFrameAt < LIVE_WINDOW_MS);
  set("#link-feedback", now - state.lastFeedbackAt < LIVE_WINDOW_MS);
}

// ---------------- Boot ---------------- //

async function boot() {
  setArmed(false);
  try {
    state.config = await getJSON("/api/config");
  } catch {
    $("#key-hint").textContent = "Could not load configuration from the teleop server. Is teleop_web.py running?";
    return;
  }
  buildKeys(state.config.action_mapping);
  runSync();
  state.config.cameras.forEach(startCamera);
  pollFeedback();
  setInterval(paintLinks, 250);
}

boot();
