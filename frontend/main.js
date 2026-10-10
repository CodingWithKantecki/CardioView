import { StreamClock } from './clock.js';
import { Trace } from './trace.js';
import { Chambers } from './chambers.js';
import { Heart } from './heart.js';

const $ = (id) => document.getElementById(id);
const els = { pill: $('pill'), pillText: $('pill-text'), conn: $('conn'), bpm: $('bpm'), rr: $('rr') };

const clock = new StreamClock();
const trace = new Trace($('trace'));
const lanes = new Chambers($('lanes'));
const labels = {};
for (const el of document.querySelectorAll('.label')) labels[el.dataset.chamber] = el;
const heart = new Heart($('heart-view'), { labels, leaders: $('leaders'), missing: $('heart-missing') });
heart.load();

// Debug: ?act=1 holds every chamber at full squeeze, ?act=0 relaxes them (screenshot checks).
const actParam = new URLSearchParams(location.search).get('act');
const FORCED_ACT = actParam === null ? null : { ra: +actParam, la: +actParam, rv: +actParam, lv: +actParam };

const SOURCE_TEXT = { live: 'LIVE', recorded: 'RECORDED', simulated: 'SIMULATED' };
let lastSampleT = null;
let shownBeat = null;

function setStatus(msg) {
  els.pill.dataset.source = msg.source;
  els.pillText.textContent = SOURCE_TEXT[msg.source] || msg.source.toUpperCase();
  const device = msg.device || 'NO DEVICE';
  if (msg.state === 'streaming') els.conn.textContent = `${device} · CONNECTED · ${msg.fs} HZ`;
  else if (msg.state === 'reconnecting') els.conn.textContent = `${device} · RECONNECTING`;
  else els.conn.textContent = `${device} · CONNECTING`;
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
    els.conn.textContent = 'SERVER OFFLINE · RETRYING';
    setTimeout(connect, 1000);
  };
}
connect();

function showBeat(b) {
  if (b === shownBeat) return;
  shownBeat = b;
  els.bpm.textContent = b && b.bpm != null ? String(b.bpm) : '--';
  els.rr.textContent = b && b.rr != null ? `${b.rr.toFixed(2)} S BETWEEN BEATS` : '-- S BETWEEN BEATS';
}

function frame() {
  const t = clock.displayTime();
  trace.draw(t);
  lanes.draw(t);
  if (t !== null) {
    heart.setActivation(FORCED_ACT === null ? lanes.activation(t) : FORCED_ACT);
    showBeat(lanes.latestBefore(t));
  }
  heart.render();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

for (const btn of document.querySelectorAll('.controls button')) {
  btn.addEventListener('click', () => {
    const on = btn.getAttribute('aria-pressed') !== 'true';
    switch (btn.dataset.action) {
      case 'rotate': heart.setRotate(on); btn.setAttribute('aria-pressed', String(on)); break;
      case 'wireframe': heart.setWireframe(on); btn.setAttribute('aria-pressed', String(on)); break;
      case 'opacity': btn.setAttribute('aria-pressed', String(heart.cycleOpacity())); break;
      case 'cutaway': heart.setCutaway(on); btn.setAttribute('aria-pressed', String(on)); break;
    }
  });
}
