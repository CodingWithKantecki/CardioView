import { StreamClock } from './clock.js';
import { Trace, GUTTER, NOW_FRAC } from './trace.js';
import { Chambers } from './chambers.js';
import { Heart } from './heart.js';

const $ = (id) => document.getElementById(id);
const els = {
  device: $('conn'), bpm: $('bpm'), rr: $('rr'),
  trace: $('trace'), lanes: $('lanes'), column: $('column'), nowline: $('nowline'), floor: $('floor'), ripple: $('ripple'),
};

// Debug: ?act=1 holds every chamber at full squeeze, ?act=0 relaxes them (screenshot checks).
const actParam = new URLSearchParams(location.search).get('act');
const FORCED_ACT = actParam === null ? null : { ra: +actParam, la: +actParam, rv: +actParam, lv: +actParam };
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const clock = new StreamClock();
const trace = new Trace(els.trace);
const lanes = new Chambers(els.lanes);
const labels = {};
const sparks = {};
for (const el of document.querySelectorAll('.label')) {
  labels[el.dataset.chamber] = el;
  sparks[el.dataset.chamber] = el.querySelector('.spark');
}
const heart = new Heart($('heart-view'), { labels, leaders: $('leaders'), missing: $('heart-missing') });
heart.load();

let lastSampleT = null;
let shownBeat = null;

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
    setStatus(msg);
  } else if (msg.type === 'samples') {
    if (lastSampleT !== null && msg.t < lastSampleT - 1) {
      trace.clear(); lanes.clear(); clock.reset(); shownBeat = null;
    }
    lastSampleT = msg.t;
    clock.update(msg.t + (msg.uv.length - 1) / msg.fs);
    trace.push(msg.t, msg.uv, msg.fs);
  } else if (msg.type === 'beat') {
    lanes.push(msg);
  }
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => handle(JSON.parse(ev.data));
  ws.onclose = () => {
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
  els.nowline.style.left = `${x.toFixed(1)}px`;
  els.nowline.style.top = `${(tr.top - col.top).toFixed(1)}px`;
  els.nowline.style.height = `${(ln.bottom - tr.top).toFixed(1)}px`;
}
new ResizeObserver(placeNowLine).observe(els.column);
window.addEventListener('resize', placeNowLine);
placeNowLine();

function ripple() {
  if (reducedMotion) return;
  els.ripple.animate(
    [{ transform: 'scale(0.55)', opacity: 0.7 }, { transform: 'scale(1.3)', opacity: 0 }],
    { duration: 650, easing: 'cubic-bezier(0.2, 0.7, 0.3, 1)' },
  );
}

function showBeat(b, t) {
  if (b === shownBeat) return;
  const fresh = shownBeat !== null && b && t - b.r < 0.3;
  shownBeat = b;
  els.bpm.textContent = b && b.bpm != null ? String(b.bpm) : '--';
  els.rr.textContent = b && b.rr != null ? `${b.rr.toFixed(2)} s between beats` : '-- s between beats';
  if (fresh) ripple();
}

function placeFloor() {
  const m = heart.metrics;
  if (!m) return;
  els.floor.style.top = `${m.floorY.toFixed(1)}px`;
  els.floor.style.left = `${m.centerX.toFixed(1)}px`;
  const wdt = Math.max(220, m.width * 1.15);
  els.floor.style.width = `${wdt.toFixed(0)}px`;
  els.floor.style.height = `${(wdt * 0.25).toFixed(0)}px`;
}

function frame() {
  const t = clock.displayTime();
  trace.draw(t);
  lanes.draw(t);
  for (const c in sparks) if (!labels[c].hidden) lanes.drawSpark(sparks[c], c, t);
  if (t !== null) {
    heart.setActivation(FORCED_ACT === null ? lanes.activation(t) : FORCED_ACT);
    showBeat(lanes.latestBefore(t), t);
  }
  heart.render();
  placeFloor();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

const opacity = $('opacity');
opacity.addEventListener('input', () => heart.setOpacity(Number(opacity.value) / 100));

// Keys keep the other views reachable without chrome: R spins, W wireframe, C cutaway.
window.addEventListener('keydown', (e) => {
  if (e.target instanceof HTMLInputElement) return;
  const k = e.key.toLowerCase();
  if (k === 'r') heart.setRotate(!heart.state.rotate);
  else if (k === 'w') heart.setWireframe(!heart.state.wireframe);
  else if (k === 'c') heart.setCutaway(!heart.state.cutaway);
});
