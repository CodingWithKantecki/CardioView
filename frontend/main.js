import { StreamClock } from './clock.js';
import { Trace, NOW_INSET, WINDOW_S } from './trace.js';
import { Chambers } from './chambers.js';
import { Heart } from './heart.js';
import { Glitch } from './glitch.js';
import { Timeline } from './timeline.js';
import { Dock } from './dock.js';
import { drawRhythmTips } from './tips.js';
import { initChat } from './chat.js';
import { SessionOverlay } from './session.js';

const $ = (id) => document.getElementById(id);
const els = {
  device: $('conn'), bpm: $('bpm'), rr: $('rr'),
  trace: $('trace'), lanes: $('lanes'), column: $('column'), nowEcg: $('nowline-ecg'), nowLanes: $('nowline-lanes'),
  alert: $('alert'), alertTitle: $('alert-title'), alertHint: $('alert-hint'), strip: $('timeline-strip'),
};

// Debug: ?act=1 holds every chamber at full squeeze, ?act=0 relaxes them; ?signal=lost forces the lost state.
const params = new URLSearchParams(location.search);
const actParam = params.get('act');
const FORCED_ACT = actParam === null ? null : { ra: +actParam, la: +actParam, rv: +actParam, lv: +actParam };
const FORCED_LOST = params.get('signal') === 'lost';
const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches;   // lost state without the glitch pass

const RHYTHM_LABELS = {
  sinus: 'Normal rhythm', tachy: 'Tachycardia', brady: 'Bradycardia',
  afib: 'Atrial fibrillation', pvc: 'Extra beats', vt: 'Ventricular tachycardia', mi: 'Heart attack',
};

const clock = new StreamClock();
const trace = new Trace(els.trace);
const lanes = new Chambers(els.lanes);
trace.beats = lanes.beats;   // one shared list of recent beats
const timeline = new Timeline(els.strip, trace, lanes, clock);
const labels = {};
const sparks = {};
for (const el of document.querySelectorAll('.label')) {
  labels[el.dataset.chamber] = el;
  sparks[el.dataset.chamber] = el.querySelector('.spark');
}
const heart = new Heart($('heart-view'), { labels, leaders: $('leaders'), missing: $('heart-missing') });
if (new URLSearchParams(location.search).has('debug')) { window.heart = heart; window.clock = clock; window.trace = trace; }   // for headless checks
heart.load();
drawRhythmTips();
const glitch = new Glitch($('glitch'), heart.renderer.domElement);
const session = new SessionOverlay(
  { box: $('session'), prompt: $('session-prompt'), sub: $('session-sub'), ring: $('session-ring') },
  { reducedMotion: REDUCED_MOTION },
);

// The session report opens in an overlay over the live view (an iframe of the summary page in
// embed mode), so the app never reloads: Back or three idle minutes in the report close it.
const report = {
  el: $('report'), frame: $('report-frame'),
  open(id) {
    this.frame.src = `/s/${encodeURIComponent(id)}?screen=1&embed=1`;
    this.el.hidden = false;
    this.frame.focus();
  },
  close() {
    if (this.el.hidden) return;
    this.el.hidden = true;
    this.frame.src = 'about:blank';
  },
};
session.onDone = (id) => report.open(id);
window.addEventListener('message', (e) => {
  if (e.origin === location.origin && e.data?.type === 'cardioview-report' && e.data.action === 'back') report.close();
});

// Exercise needs the real strap, streaming, with a signal
function strapReady() {
  return !!status && status.source === 'live' && status.state === 'streaming' && signal.ok;
}

// The header tabs: Strap (the live view), Demo (the recording and the rhythms) and Exercise (the live
// view plus the session panel in the Heart rate box). A running session keeps the Exercise tab.
let exerciseMode = false;
const sourceCells = [...document.querySelectorAll('#source-mode button')];
const panel = { el: $('exercise'), note: $('exercise-note'), start: $('exercise-start'), stop: $('exercise-stop'), voice: $('exercise-voice') };
const setAttr = (el, name, value) => { if (el.getAttribute(name) !== String(value)) el.setAttribute(name, String(value)); };
function syncSourceCells() {
  const live = !!status && status.source === 'live';
  const busy = session.busy();
  if (busy) exerciseMode = true;
  const ex = exerciseMode && live;
  for (const b of sourceCells) {
    const s = b.dataset.source;
    setAttr(b, 'aria-pressed', s === 'live' ? (live && !ex) : s === 'demo' ? (!!status && !live) : ex);
  }
  panel.el.hidden = !ex;
  if (!ex) return;
  const ready = strapReady();
  const note = busy ? 'Session running' : ready ? 'Strap on. Start the two minute session' : 'Waiting for the strap';
  if (panel.note.textContent !== note) panel.note.textContent = note;
  panel.start.hidden = busy;
  panel.stop.hidden = !busy;
  setAttr(panel.start, 'aria-disabled', !ready);
  setAttr(panel.voice, 'aria-pressed', session.voiceOn);
}

let lastSampleT = null;
let lastSampleWall = null;
let shownBeat = null;
let status = null;                       // last status message
let signal = { ok: true, reason: '' };   // last signal message
let wsOpen = false;
let ws = null;
let userWireframe = false;
let appliedWireframe = false;
let flickerUntil = 0;

// It is either working or not connected: one message for every strap problem.
const NOT_CONNECTED = ['Not connected', 'Wet the pads and wear the strap snug on the chest'];

// Why the screen cannot follow a heart right now, or null when it can.
function lostState() {
  if (FORCED_LOST) return NOT_CONNECTED;
  if (!status) return null;
  if (!wsOpen) return ['Server offline', 'Retrying'];
  if (status.source === 'live' && status.state !== 'streaming') return NOT_CONNECTED;
  if (lastSampleWall !== null && performance.now() - lastSampleWall > 3000) return NOT_CONNECTED;
  if (!signal.ok) return NOT_CONNECTED;
  return null;
}

// The status line, in words: the strap id (as data, in mono) while it streams, otherwise whose recording
// or which simulated rhythm, or the link state. The backend's device strings stay as they are; this only
// renders them.
function setStatus(msg) {
  const device = msg.device || '';
  let text = device || msg.source, id = false;
  if (msg.source === 'live') {
    if (msg.state === 'streaming') { text = device; id = true; }
    else if (msg.state === 'reconnecting') text = 'Reconnecting to the strap';
    else text = 'Connecting to Polar H10';
  } else if (device.startsWith('Simulated: ')) {
    text = 'Simulated ' + device.slice(11).toLowerCase();
  } else if (device.startsWith('Recording ')) {
    // recordings are named h10_ecg_<name> by tools/h10_record.py
    const who = device.slice(10).replace(/^h10_(ecg_)?/, '').replace(/_/g, ' ');
    text = /^[a-z]+$/i.test(who) ? `${who[0].toUpperCase()}${who.slice(1)}'s recording` : `Recording ${who}`;
  }
  els.device.textContent = text;
  els.device.classList.toggle('id', id);
}

function handle(msg) {
  if (msg.type === 'status') {
    if (!status || status.source !== msg.source || status.device !== msg.device) {   // a new source
      signal = { ok: true, reason: '' };
      lastSampleWall = null;
      // the strap has no history: clear now. Other sources send their history in one message,
      // and the stream-time jump in it swaps the whole screen in a single frame.
      if (msg.source === 'live') { trace.clear(); lanes.clear(); clock.reset(); shownBeat = null; lastSampleT = null; }
    }
    status = msg;
    setStatus(msg);
    // simulated rhythms exist in demo only, never beside strap data
    const rhythms = document.getElementById('rhythms');
    rhythms.hidden = msg.source === 'live';
    for (const b of rhythms.querySelectorAll('button')) {
      const name = b.dataset.rhythm;
      const on = msg.device === 'Simulated: ' + RHYTHM_LABELS[name];
      b.setAttribute('aria-pressed', String(!!on));
    }
  } else if (msg.type === 'signal') {
    signal = { ok: !!msg.ok, reason: msg.reason || '' };
  } else if (msg.type === 'samples') {
    if (lastSampleT !== null && msg.t < lastSampleT - 1) {
      trace.clear(); lanes.clear(); clock.reset(); shownBeat = null;
    }
    lastSampleT = msg.t;
    lastSampleWall = performance.now();
    clock.update(msg.t + (msg.uv.length - 1) / msg.fs);
    trace.push(msg.t, msg.uv, msg.fs);
  } else if (msg.type === 'beat') {
    lanes.push(msg);
  } else if (msg.type === 'session') {
    session.handle(msg);
    if (msg.state === 'running' || msg.state === 'analyzing') report.close();
  }
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { wsOpen = true; };
  ws.onmessage = (ev) => handle(JSON.parse(ev.data));
  ws.onclose = () => {
    wsOpen = false;
    els.device.textContent = 'Server offline, retrying';
    setTimeout(connect, 1000);
  };
}
connect();

// one dotted "now" line across the trace and the lanes
function placeNowLine() {
  const col = els.column.getBoundingClientRect();
  const tr = els.trace.getBoundingClientRect();
  const ln = els.lanes.getBoundingClientRect();
  const x = tr.left - col.left + tr.width - NOW_INSET;
  for (const [el, r] of [[els.nowEcg, tr], [els.nowLanes, ln]]) {   // one line per band, never across the rule
    el.style.left = `${x.toFixed(1)}px`;
    el.style.top = `${(r.top - col.top).toFixed(1)}px`;
    el.style.height = `${r.height.toFixed(1)}px`;
  }
}

const relayout = new ResizeObserver(placeNowLine);
relayout.observe(els.column);
relayout.observe(els.trace);     // the trace moves when the rhythm tray appears or wraps
relayout.observe(els.lanes);
window.addEventListener('resize', placeNowLine);
placeNowLine();

function showBeat(b) {
  if (b === shownBeat) return;
  shownBeat = b;
  if (!b) { els.bpm.textContent = '--'; els.rr.textContent = '-- s between beats'; return; }
  // the first beat after a source switch carries no interval yet: keep the last numbers until one does
  if (b.bpm != null) els.bpm.textContent = String(b.bpm);
  if (b.rr != null) els.rr.textContent = `${b.rr.toFixed(2)} s between beats`;
}

function applyLost(lost) {
  document.body.classList.toggle('lost', !!lost);
  els.alert.hidden = !lost;
  if (lost) {
    if (els.alertTitle.textContent !== lost[0]) els.alertTitle.textContent = lost[0];
    if (els.alertHint.textContent !== lost[1]) els.alertHint.textContent = lost[1];
  }
  // wireframe flicker while lost, on top of whatever the W key set
  const now = performance.now();
  if (lost && !REDUCED_MOTION && now > flickerUntil && Math.random() < 0.04) flickerUntil = now + 50 + Math.random() * 120;
  const want = userWireframe || (!!lost && now < flickerUntil);
  if (want !== appliedWireframe) { heart.setWireframe(want); appliedWireframe = want; }
}

let heldFrom = null;   // off live, the buffers hold everything from here instead of rolling
function drawFrame() {
  clock.oldest = trace.ts.length ? trace.ts[0] : null;
  const t = clock.displayTime();
  heldFrom = clock.mode === 'live' ? null : Math.min(heldFrom ?? Infinity, clock.windowStart() - WINDOW_S);
  trace.holdFrom = heldFrom;
  lanes.holdFrom = heldFrom;
  const lost = lostState();
  trace.draw(t);
  lanes.draw(t);
  for (const c in sparks) if (!labels[c].hidden) lanes.drawSpark(sparks[c], c, t);
  if (lost) {
    heart.setActivation({ ra: 0, la: 0, rv: 0, lv: 0 });
    showBeat(null);
  } else if (t !== null) {
    heart.setActivation(FORCED_ACT === null ? lanes.activation(t) : FORCED_ACT);
    showBeat(lanes.latestBefore(t));
  }
  applyLost(lost);
  heart.render();
  if (lost && !REDUCED_MOTION) glitch.draw(performance.now());
  timeline.draw(t);
  syncTransport();
  dock.update();
  dock.setPressed('rotate', heart.state.rotate);
  dock.setPressed('wireframe', userWireframe);
  dock.setPressed('open', heart.state.cutaway);
  session.frame(performance.now());
  syncSourceCells();
}

// the transport tray shows the clock's mode; a replay that catches up flips back to live by itself
let shownMode = null;
function syncTransport() {
  if (clock.mode === shownMode) return;
  shownMode = clock.mode;
  for (const b of document.querySelectorAll('#transport button')) b.setAttribute('aria-pressed', String(b.dataset.mode === clock.mode));
}
for (const b of document.querySelectorAll('#transport button')) b.addEventListener('click', () => clock.setMode(b.dataset.mode));

// one error must never stop the screen: draw what we can and keep the loop alive
function frame() {
  try { drawFrame(); } catch (e) { console.error('frame failed', e); }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

for (const b of sourceCells) {
  b.addEventListener('click', () => {
    const s = b.dataset.source;
    if (session.busy() && s !== 'exercise') { session.flash('Stop the session first'); return; }
    exerciseMode = s === 'exercise';
    const want = s === 'demo' ? 'demo' : 'live';   // the Exercise tab is the strap too
    // Demo also brings a simulated rhythm back to the recording; Strap and Exercise only switch when not live
    const already = want === 'live' ? (!!status && status.source === 'live') : (!!status && status.source === 'recorded');
    if (!already && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'source', name: want }));
  });
}
panel.start.addEventListener('click', () => session.start(strapReady()));
panel.stop.addEventListener('click', () => session.stop());
panel.voice.addEventListener('click', () => session.setVoice(!session.voiceOn));

for (const b of document.querySelectorAll('#rhythms button')) {
  b.addEventListener('click', () => {
    if (session.busy()) { session.flash('Stop the session first'); return; }
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const name = b.dataset.rhythm;
    ws.send(JSON.stringify({ type: 'rhythm', name }));
  });
}

initChat();

const opacity = $('opacity');
opacity.addEventListener('input', () => heart.setOpacity(Number(opacity.value) / 100));

// The dock and the keys share these: R or Rotate spins, W or Wireframe, C or Open (the cutaway),
// 0 or Reset view. The dock reads its pressed state from the heart every frame.
const view = {
  rotate: () => heart.setRotate(!heart.state.rotate),
  wire: () => { userWireframe = !userWireframe; },
  cut: () => heart.setCutaway(!heart.state.cutaway),
  reset: () => heart.resetView(),
};
const dock = new Dock($('dock'), {
  rotate: view.rotate,
  wireframe: view.wire,
  open: view.cut,
  opacity: () => opacity.focus(),
  reset: view.reset,
});
if (REDUCED_MOTION) {   // auto-rotate is off under reduced motion; the dock's cell says so
  const b = $('dock').querySelector('[data-action="rotate"]');
  b.disabled = true;
  b.dataset.label = 'Auto-rotate is off under reduced motion';
}

