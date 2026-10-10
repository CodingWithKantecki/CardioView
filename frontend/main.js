import { StreamClock } from './clock.js';
import { Trace, GUTTER, NOW_FRAC } from './trace.js';
import { Chambers } from './chambers.js';
import { Heart } from './heart.js';
import { Glitch } from './glitch.js';
import { invalidate as invalidateTheme } from './theme.js';

const $ = (id) => document.getElementById(id);
const els = {
  device: $('conn'), bpm: $('bpm'), rr: $('rr'),
  trace: $('trace'), lanes: $('lanes'), column: $('column'), nowline: $('nowline'),
  alert: $('alert'), alertTitle: $('alert-title'), alertHint: $('alert-hint'),
};

// Debug: ?act=1 holds every chamber at full squeeze, ?act=0 relaxes them; ?signal=lost forces the lost state.
const params = new URLSearchParams(location.search);
const actParam = params.get('act');
const FORCED_ACT = actParam === null ? null : { ra: +actParam, la: +actParam, rv: +actParam, lv: +actParam };
const FORCED_LOST = params.get('signal') === 'lost';
// theme: navy by default; ?theme=light or the T key, remembered per browser
const savedTheme = (() => { try { return localStorage.getItem('cardioview-theme'); } catch { return null; } })();
if (params.get('theme') || savedTheme) document.documentElement.dataset.theme = params.get('theme') || savedTheme;
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'light' ? '' : 'light';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('cardioview-theme', next); } catch {}
  invalidateTheme();
  heart.applyTheme();
}
const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches;   // lost state without the glitch pass

const RHYTHM_LABELS = {
  sinus: 'Sinus rhythm', tachy: 'Tachycardia', brady: 'Bradycardia',
  afib: 'Atrial fibrillation', pvc: 'Extra beats', vt: 'Ventricular tachycardia',
};

const clock = new StreamClock();
const trace = new Trace(els.trace);
const lanes = new Chambers(els.lanes);
trace.beats = lanes.beats;   // one shared list of recent beats
const labels = {};
const sparks = {};
for (const el of document.querySelectorAll('.label')) {
  labels[el.dataset.chamber] = el;
  sparks[el.dataset.chamber] = el.querySelector('.spark');
}
const heart = new Heart($('heart-view'), { labels, leaders: $('leaders'), missing: $('heart-missing') });
heart.load();
const glitch = new Glitch($('glitch'), heart.renderer.domElement);

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

// One quiet line in the header: the strap id while it streams, otherwise the mode or the link state.
function setStatus(msg) {
  const device = msg.device || '';
  if (msg.source === 'live') {
    if (msg.state === 'streaming') els.device.textContent = device;
    else if (msg.state === 'reconnecting') els.device.textContent = 'Reconnecting to the strap';
    else els.device.textContent = 'Connecting to Polar H10';
  } else {
    els.device.textContent = device || msg.source;
  }
}

function handle(msg) {
  if (msg.type === 'status') {
    if (status && status.source !== msg.source) signal = { ok: true, reason: '' };   // sources continue on one stream clock
    status = msg;
    setStatus(msg);
    for (const b of document.querySelectorAll('#source-mode button')) {
      b.setAttribute('aria-pressed', String((b.dataset.source === 'live') === (msg.source === 'live')));
    }
    // simulated rhythms exist in demo only, never beside strap data
    const rhythms = document.getElementById('rhythms');
    rhythms.hidden = msg.source === 'live';
    for (const b of rhythms.querySelectorAll('button')) {
      const name = b.dataset.rhythm;
      const on = name === 'recording' ? msg.source === 'recorded' : msg.device === 'Simulated: ' + RHYTHM_LABELS[name];
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
  const x = tr.left - col.left + GUTTER + (tr.width - GUTTER) * NOW_FRAC;
  const top = trace.mode === '3d' ? ln.top - 14 : tr.top;   // the waterfall has no time axis
  els.nowline.style.left = `${x.toFixed(1)}px`;
  els.nowline.style.top = `${(top - col.top).toFixed(1)}px`;
  els.nowline.style.height = `${(ln.bottom - top).toFixed(1)}px`;
}

function setEcgMode(mode) {
  trace.setMode(mode);
  for (const b of document.querySelectorAll('#ecg-mode button')) b.setAttribute('aria-pressed', String(b.dataset.mode === trace.mode));
  placeNowLine();
}
for (const b of document.querySelectorAll('#ecg-mode button')) b.addEventListener('click', () => setEcgMode(b.dataset.mode));
if (new URLSearchParams(location.search).get('ecg') === '3d') setEcgMode('3d');
const relayout = new ResizeObserver(placeNowLine);
relayout.observe(els.column);
relayout.observe(els.trace);     // the trace moves when the rhythm tray appears or wraps
relayout.observe(els.lanes);
window.addEventListener('resize', placeNowLine);
placeNowLine();

function showBeat(b) {
  if (b === shownBeat) return;
  shownBeat = b;
  els.bpm.textContent = b && b.bpm != null ? String(b.bpm) : '--';
  els.rr.textContent = b && b.rr != null ? `${b.rr.toFixed(2)} s between beats` : '-- s between beats';
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

function frame() {
  const t = clock.displayTime();
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
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

for (const b of document.querySelectorAll('#source-mode button')) {
  b.addEventListener('click', () => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'source', name: b.dataset.source }));
  });
}

for (const b of document.querySelectorAll('#rhythms button')) {
  b.addEventListener('click', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const name = b.dataset.rhythm;
    ws.send(JSON.stringify(name === 'recording' ? { type: 'source', name: 'demo' } : { type: 'rhythm', name }));
  });
}

const opacity = $('opacity');
opacity.addEventListener('input', () => heart.setOpacity(Number(opacity.value) / 100));

// Keys keep the other views reachable without chrome: R spins, W wireframe, C cutaway.
window.addEventListener('keydown', (e) => {
  if (e.target instanceof HTMLInputElement) return;
  const k = e.key.toLowerCase();
  if (k === 't') toggleTheme();
  else if (k === 'r') heart.setRotate(!heart.state.rotate);
  else if (k === 'w') userWireframe = !userWireframe;
  else if (k === 'c') heart.setCutaway(!heart.state.cutaway);
});
