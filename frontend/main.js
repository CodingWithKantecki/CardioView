import { StreamClock } from './clock.js';
import { Trace, NOW_INSET, WINDOW_S } from './trace.js';
import { csv as exportCsv, fhir as exportFhir, report as exportReport } from './export.js';
import { Chambers } from './chambers.js';
import { Heart } from './heart.js';
import { Glitch } from './glitch.js';
import { Timeline } from './timeline.js';
import { Dock } from './dock.js';
import { Strap, FakeStrap, supported as strapSupported } from './strap.js';
import { initChat } from './chat.js';
import { SessionOverlay } from './session.js';

const $ = (id) => document.getElementById(id);
const els = {
  device: $('conn'), bpm: $('bpm'),
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
const glitch = new Glitch($('glitch'), heart.renderer.domElement);
const session = new SessionOverlay(
  { box: $('session'), prompt: $('session-prompt'), sub: $('session-sub'), ring: $('session-ring') },
  { reducedMotion: REDUCED_MOTION },
);
// a message down this viewer's socket; true when it went
function sendWs(msg) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(msg));
  return true;
}
session.send = sendWs;
// what the page last asked of the server (its source, a rhythm), re-sent when the socket comes back:
// the server starts every connection on the demo, and a deploy or a proxy hiccup drops the socket
let lastChoice = null;
function choose(msg) { lastChoice = msg; return sendWs(msg); }
// the strap's state as a status message, re-sent after a reconnect so the server never runs a
// strap that is marked connecting while its samples flow (Thomas, 2026-10-10 evening: Not connected
// with a signal on screen)
function strapStatus() {
  return { type: 'status', state: strap.state === 'streaming' ? 'streaming' : 'connecting', device: strap.state === 'off' ? '' : strap.name };
}
let cid = null;   // this viewer's id from the server's hello; the chat sends it with a question

// The visitor's own Polar H10, through Web Bluetooth, sent down this socket as the live source.
// ?fake=1 plays the recording as if it were a strap, for checks on a machine without a radio.
const strap = new (params.has('fake') ? FakeStrap : Strap)(sendWs, () => syncSourceCells());
const strapPanel = { el: $('strap-panel'), note: $('strap-note'), tray: $('strap-tray'), connect: $('strap-connect'), disconnect: $('strap-disconnect') };

// The session report opens in an overlay over the live view (an iframe of the summary page in
// embed mode), so the app never reloads: Back or three idle minutes in the report close it.
const report = {
  el: $('report'), frame: $('report-frame'),
  open(id, print = false) {
    this.frame.src = `/s/${encodeURIComponent(id)}?screen=1&embed=1${print ? '&print=1' : ''}`;
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
  if (e.origin === location.origin && e.data?.type === 'cardioview-report' && e.data.action === 'back') { report.close(); sendWs({ type: 'session', action: 'dismiss' }); }
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
  // the strap panel: on the Strap tab always, on the Exercise tab until the strap streams
  const streaming = live && status.state === 'streaming';
  const showStrap = live && (!exerciseMode || !streaming);
  strapPanel.el.hidden = !showStrap;
  if (showStrap) {
    let note;
    if (!strapSupported && !params.has('fake')) note = 'Connecting a strap needs Chrome or Edge on a computer or an Android phone';
    else if (strap.state === 'streaming') note = `${strap.name} connected`;
    else if (strap.state === 'choosing') note = 'Give the list a second, then pick the strap with the signal icon';
    else if (strap.state === 'connecting') note = 'Connecting to the strap';
    else note = strap.reason || 'Wet the pads, wear the strap snug, then connect it';
    if (strapPanel.note.textContent !== note) strapPanel.note.textContent = note;
    strapPanel.connect.hidden = strap.state !== 'off' || (!strapSupported && !params.has('fake'));
    strapPanel.disconnect.hidden = strap.state === 'off' || strap.state === 'choosing';   // Cancel while connecting, Disconnect while streaming
    const stop = strap.state === 'streaming' ? 'Disconnect' : 'Cancel';
    if (strapPanel.disconnect.textContent !== stop) strapPanel.disconnect.textContent = stop;
    strapPanel.tray.hidden = strapPanel.connect.hidden && strapPanel.disconnect.hidden;
  }
  panel.el.hidden = !(ex && streaming);
  if (!(ex && streaming)) return;
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

// Why the screen cannot follow a heart right now, or null when it can. `lostWhy` names the rule
// that fired, for the console: the alert itself says the same thing for every strap problem.
let lostWhy = '';
let loggedWhy = '';
function lostState() {
  const why = (reason, state) => { lostWhy = reason; return state; };
  if (FORCED_LOST) return why('forced by ?signal=lost', NOT_CONNECTED);
  if (!status) return why('', null);
  if (!wsOpen) return why('server offline', ['Server offline', 'Retrying']);
  if (status.source === 'live' && status.state !== 'streaming') return why(`strap ${status.state}`, NOT_CONNECTED);
  const gap = lastSampleWall === null ? 0 : (performance.now() - lastSampleWall) / 1000;
  if (gap > 3) return why(`no samples for ${gap.toFixed(1)} s`, NOT_CONNECTED);
  if (!signal.ok) return why(`signal ${signal.reason}`, NOT_CONNECTED);
  return why('', null);
}

// one console line per change of cause, not per frame
function logLost() {
  const key = lostWhy.replace(/[\d.]+ s$/, '');
  if (key === loggedWhy) return;
  loggedWhy = key;
  console.info(lostWhy ? `lost: ${lostWhy}` : 'signal back');
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
    const device = typeof msg.device === 'string' ? msg.device : '';
    const cells = [...rhythms.querySelectorAll('.rhythm-tray button')];
    // a Gemini heart: any simulated rhythm that is not one of the cells' own (Gemini may well name one "Atrial fibrillation")
    const described = device.startsWith('Simulated: ') && !cells.some((b) => device === 'Simulated: ' + RHYTHM_LABELS[b.dataset.rhythm]);
    for (const b of cells) {
      const name = b.dataset.rhythm;
      const on = name === 'gemini' ? described : device === 'Simulated: ' + RHYTHM_LABELS[name];
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
  } else if (msg.type === 'hello') {
    cid = msg.cid;
    window.cardioview = { cid };
  } else if (msg.type === 'session_result') {
    session.result(msg);
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
  ws.onopen = () => {
    wsOpen = true;
    if (lastChoice) sendWs(lastChoice);
    if (strap.state !== 'off') sendWs(strapStatus());
  };
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
  if (!b) { els.bpm.textContent = '--'; return; }
  // the first beat after a source switch carries no rate yet: keep the last number until one does
  if (b.bpm != null) els.bpm.textContent = String(b.bpm);
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
  logLost();
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
    if (!already) choose({ type: 'source', name: want });
    else if (want === 'live') lastChoice = { type: 'source', name: 'live' };
    if (want === 'live') describeUi.close();   // a Gemini heart belongs to the demo
  });
}
// the logo toggles full screen (Thomas, 2026-10-10 evening): a click fills the display, another brings the browser's tabs back
$('brand').addEventListener('click', () => {
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  else document.documentElement.requestFullscreen?.().catch(() => {});
});
panel.start.addEventListener('click', () => session.start(strapReady()));
strapPanel.connect.addEventListener('click', () => { if (strap.state === 'off') strap.connect(); });
strapPanel.disconnect.addEventListener('click', () => strap.disconnect());
panel.stop.addEventListener('click', () => session.stop());
panel.voice.addEventListener('click', () => session.setVoice(!session.voiceOn));

for (const b of document.querySelectorAll('.rhythm-tray button')) {
  b.addEventListener('click', () => {
    if (session.busy()) { session.flash('Stop the session first'); return; }
    if (b.dataset.rhythm === 'gemini') { describeUi.open(); return; }   // the Gemini panel; the rhythm comes from what is typed
    describeUi.close();
    choose({ type: 'rhythm', name: b.dataset.rhythm });
  });
}

// Gemini heart: a patient, a situation or a rhythm in words. The server asks Gemini for the
// simulator's recipe and switches this viewer's demo to it; the recipe is kept as the last choice,
// so a reconnect brings the same heart back without asking again.
const describeUi = {
  el: $('describe'), panel: $('gemini'), tray: $('rhythm-tray'), rate: document.querySelector('.instrument.rate'), text: $('describe-text'), go: $('describe-go'), note: $('describe-note'),
  open() { this.tray.hidden = true; this.panel.hidden = false; this.rate.classList.add('gemini-open'); this.text.focus(); },   // the panel takes the tray's place; the status line above goes quiet
  close() { this.panel.hidden = true; this.tray.hidden = false; this.rate.classList.remove('gemini-open'); this.say(''); this.panel.classList.remove('busy'); },
  busy(on) { this.panel.classList.toggle('busy', on); setAttr(this.go, 'aria-disabled', on); },
  // the note under the box: the sparkle, the simulated heart's name in Gemini's gradient, then the words
  say(text, name = '') {
    const n = this.note;
    n.textContent = '';
    n.hidden = !text;
    if (!text) return;
    const mark = document.createElement('span');
    mark.className = 'note-mark';
    mark.innerHTML = SPARKLE;
    n.appendChild(mark);
    if (name) {
      const b = document.createElement('b');
      b.className = 'note-name';
      b.textContent = `Simulated ${name}`;
      n.appendChild(b);
    }
    const t = document.createElement('span');
    t.className = 'note-text';
    t.textContent = text;
    n.appendChild(t);
  },
};
const SPARKLE = '<img src="assets/gemini-mark.svg" alt="">';   // the Gemini mark (frontend/assets/gemini-mark.svg)
$('gemini-back').addEventListener('click', () => { describeUi.panel.hidden = true; describeUi.tray.hidden = false; describeUi.rate.classList.remove('gemini-open'); });   // the rhythm playing stays
describeUi.el.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (session.busy()) { session.flash('Stop the session first'); return; }
  const text = describeUi.text.value.trim();
  if (!text || describeUi.go.getAttribute('aria-disabled') === 'true') return;
  describeUi.busy(true);
  describeUi.say('Gemini is setting up the heart');
  try {
    const res = await fetch('/api/rhythm/describe', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ cid, text }) });
    const data = await res.json().catch(() => ({}));
    if (data.ok) {
      lastChoice = { type: 'rhythm', name: 'custom', recipe: data.recipe };
      describeUi.say(data.summary, data.name.toLowerCase());
    } else describeUi.say(data.reply || 'Gemini did not answer, try again');
  } catch { describeUi.say('Gemini heart needs an internet connection'); }
  describeUi.busy(false);
});

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

// Export asks for the shape: CSV and FHIR are made in the page; the PDF report is stored by the
// server and opened in the report overlay, which prints it (Save as PDF), QR included.
const exportMenu = { button: $('export'), menu: $('export-menu') };
function showExportMenu(on) { exportMenu.menu.hidden = !on; exportMenu.button.setAttribute('aria-expanded', String(on)); }
exportMenu.button.addEventListener('click', () => showExportMenu(exportMenu.menu.hidden));
document.addEventListener('click', (e) => { if (!exportMenu.menu.hidden && !e.target.closest('.export-item')) showExportMenu(false); });
for (const b of exportMenu.menu.querySelectorAll('button')) {
  b.addEventListener('click', async () => {
    showExportMenu(false);
    if (!trace.ts.length) { session.flash('Nothing to export yet'); return; }
    const format = b.dataset.format;
    if (format === 'csv') exportCsv(trace, status);
    else if (format === 'fhir') exportFhir(trace, status, shownBeat);
    else if (format === 'pdf') {
      session.flash('Making the report');
      try { report.open(await exportReport(trace, status), true); }
      catch (err) { session.flash(err.message); }
    }
  });
}
