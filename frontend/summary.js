// One summary page for the big screen (?screen=1), a phone on the booth Wi-Fi, and the public link.
// It reads /api/s/<id> from whichever server sent it and draws every chart on canvas, in the viewer's colors.

const $ = (id) => document.getElementById(id);
const sid = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');
const params = new URLSearchParams(location.search);
const screenMode = params.has('screen');
const FONT = '600 12px "JetBrains Mono", monospace';   // chart readouts, in capitals like the 130 HZ corner on the live ECG
const WAVE = '700 15px "Helvetica Neue", Helvetica, Arial, sans-serif';   // P, QRS, T: the voice of the chamber letters
const STEP_NAME = { rest: 'REST', breathe: 'BREATHE', squats: 'SQUATS', recover: 'RECOVER' };
const IDLE_MS = 180000;   // the big screen goes back to live after 3 minutes
const GONE = 'This session is no longer available.';

// embedded: the booth shows this page in an overlay over the live view; leaving means closing it
const embedded = params.has('embed') && window.parent !== window;
function leave() {
  if (embedded) window.parent.postMessage({ type: 'cardioview-report', action: 'back' }, location.origin);
  else location.assign('/');
}

let summary = null;
if (screenMode) document.body.classList.add('screen');

function alpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// chart colors come from the stylesheet, so a theme is a stylesheet swap here too
function palette() {
  const cs = getComputedStyle(document.documentElement);
  const v = (k) => cs.getPropertyValue(k).trim();
  return { text: v('--c-ink'), dim: v('--c-dim'), hair: alpha(v('--c-rule'), 0.14), ecg: v('--c-trace') };
}
const C = palette();

const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const day = (iso) => `${new Date(iso).toLocaleDateString([], { weekday: 'short' })} ${time(iso)}`;
const scale = (lo, hi, a, b) => (v) => a + ((v - lo) * (b - a)) / ((hi - lo) || 1);

function canvas2d(el) {
  const r = el.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  el.width = Math.max(1, Math.round(r.width * dpr));
  el.height = Math.max(1, Math.round(r.height * dpr));
  const g = el.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.font = FONT;
  return { g, w: r.width, h: r.height };
}

function hline(g, x0, x1, y) { g.beginPath(); g.moveTo(x0, y); g.lineTo(x1, y); g.stroke(); }
function vline(g, x, y0, y1) { g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y1); g.stroke(); }

// a polyline that lifts the pen over missing values
function trace(g, values, x, y, color, width) {
  g.strokeStyle = color;
  g.lineWidth = width;
  g.lineJoin = 'round';
  g.beginPath();
  let pen = false;
  values.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    if (pen) g.lineTo(x(i), y(v)); else g.moveTo(x(i), y(v));
    pen = true;
  });
  g.stroke();
}

function bpmAxis(g, lo, hi, y, x0, x1) {
  g.strokeStyle = C.hair;
  g.lineWidth = 1;
  g.fillStyle = C.dim;
  for (let v = Math.ceil(lo / 20) * 20; v <= hi; v += 20) {
    hline(g, x0, x1, y(v));
    g.fillText(String(v), 0, y(v) + 4);
  }
}

function effortChart(s) {
  const bpm = s.hr_chart?.bpm || [];
  const vals = bpm.filter((v) => v != null);
  if (vals.length < 0.5 * bpm.length || vals.length < 2) {   // mostly gaps: a chart would only show noise
    $('effort-chart').hidden = true;
    return;
  }
  const { g, w, h } = canvas2d($('effort-chart'));
  const lo = Math.floor(Math.min(...vals) / 10) * 10 - 5;
  const hi = Math.ceil(Math.max(...vals) / 10) * 10 + 5;
  const pad = { l: 36, r: 10, t: 24, b: 6 };
  const x = scale(0, bpm.length - 1, pad.l, w - pad.r);
  const y = scale(lo, hi, h - pad.b, pad.t);
  bpmAxis(g, lo, hi, y, pad.l, w - pad.r);
  for (const st of s.steps || []) {
    if (!STEP_NAME[st.name]) continue;
    const xs = x(Math.min(st.start, bpm.length - 1));
    g.strokeStyle = C.hair;
    vline(g, xs, 4, h - pad.b);
    g.fillStyle = C.dim;
    g.fillText(STEP_NAME[st.name], xs + 6, 15);
  }
  trace(g, bpm, x, y, C.text, 2);
  if (s.effort?.ok) {
    const i = bpm.indexOf(Math.max(...vals));
    g.fillStyle = C.text;
    g.beginPath(); g.arc(x(i), y(bpm[i]), 4, 0, 2 * Math.PI); g.fill();
    g.fillText(`PEAK ${s.effort.peak_bpm}`, Math.min(x(i) + 8, w - 70), y(bpm[i]) + 4);
  }
}

function breathingChart(s) {
  const bpm = s.breathing?.chart?.bpm || [];
  const vals = bpm.filter((v) => v != null);
  if (vals.length < 2) return;
  const { g, w, h } = canvas2d($('breathing-chart'));
  const step = s.breathing.chart.step_s;
  const lo = Math.floor(Math.min(...vals) / 5) * 5 - 2;
  const hi = Math.ceil(Math.max(...vals) / 5) * 5 + 2;
  const pad = { l: 36, r: 6, t: 20, b: 6 };
  const x = scale(0, bpm.length - 1, pad.l, w - pad.r);
  const y = scale(lo, hi, h - pad.b, pad.t);
  bpmAxis(g, lo, hi, y, pad.l, w - pad.r);
  const perBreath = Math.round(10 / step);
  for (let i = 0; i < bpm.length; i += perBreath) {
    g.strokeStyle = C.hair;
    vline(g, x(i), 4, h - pad.b);
    g.fillStyle = C.dim;
    g.fillText('IN', x(i) + 4, 14);
    if (i + perBreath / 2 < bpm.length) g.fillText('OUT', x(i + perBreath / 2) + 4, 14);
  }
  trace(g, bpm, x, y, C.text, 2);
}

function beatChart(s) {
  const b = s.beat;
  const { g, w, h } = canvas2d($('beat-chart'));
  const n = b.uv.length;
  const t = (i) => b.t0 + i / b.fs;
  const lo = Math.min(...b.uv);
  const hi = Math.max(...b.uv);
  const pad = { l: 6, r: 6, t: 26, b: 8 };
  const x = scale(t(0), t(n - 1), pad.l, w - pad.r);
  const y = scale(lo - 0.05 * (hi - lo), hi, h - pad.b, pad.t);
  g.strokeStyle = C.hair;
  hline(g, pad.l, w - pad.r, y(0));
  const xi = (i) => x(t(i));
  trace(g, b.uv, xi, y, C.ecg, 2.2);
  g.fillStyle = C.dim;
  g.fillText(`${b.fs} HZ`, pad.l, 12);
  g.font = WAVE;
  g.fillStyle = C.text;
  g.textAlign = 'center';
  for (const [name, at] of [['P', b.waves.p], ['QRS', b.waves.qrs], ['T', b.waves.t]]) {
    if (at == null) continue;
    const i = Math.round((at - b.t0) * b.fs);
    const near = b.uv.slice(Math.max(0, i - 5), i + 6);
    g.fillText(name, x(at), y(Math.max(...near)) - 10);
  }
  g.textAlign = 'start';
}

function timingChart(s) {
  const rest = s.timing.rest || [];
  const breathe = s.timing.breathe || [];
  const all = rest.concat(breathe).flat();
  const { g, w, h } = canvas2d($('timing-chart'));
  const lo = Math.min(...all) - 0.05;
  const hi = Math.max(...all) + 0.05;
  const side = Math.min(w, h);
  const ox = (w - side) / 2;
  const x = scale(lo, hi, ox + 24, ox + side - 6);
  const y = scale(lo, hi, side - 22, 6);
  g.strokeStyle = C.hair;
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(x(lo), y(lo)); g.lineTo(x(hi), y(hi)); g.stroke();
  for (const [pts, color] of [[breathe, C.dim], [rest, C.text]]) {
    g.fillStyle = color;
    for (const [a, b] of pts) { g.beginPath(); g.arc(x(a), y(b), 3, 0, 2 * Math.PI); g.fill(); }
  }
  g.fillStyle = C.dim;
  g.fillText('GAP BEFORE', x(lo), side - 4);
  g.save(); g.translate(ox + 12, y(lo)); g.rotate(-Math.PI / 2); g.fillText('GAP AFTER', 0, 0); g.restore();
  g.fillStyle = C.text; g.fillText('REST', ox + 30, 16);   // top left stays empty: dots hug the diagonal
  g.fillStyle = C.dim; g.fillText('SLOW BREATHING', ox + 30, 32);
}

function refuse(block, reason) {
  $(block).classList.add('refused');
  $(`${block}-text`).textContent = reason;
}

// whose heart it was: the strap's wearer, or the booth's demo data (never presented as the visitor's)
function who(s) {
  if (s.source === 'recorded') return 'Session on recorded data';
  if (s.source === 'simulated') return 'Session on simulated data';
  return 'Your session';
}

function render(s) {
  const minutes = Math.max(1, Math.round((s.steps?.at(-1)?.end || 60) / 60));
  $('meta').textContent = s.demo
    ? 'Demo session, synthetic data'
    : `${who(s)}, ${minutes} min, ${time(s.created)}${s.ended_early ? ', ended early' : ''}`;
  $('until').textContent = s.demo ? '' : `Available until ${day(s.keep_until)}`;

  const e = s.effort;
  if (!e.ok) { $('effort-text').textContent = e.reason; $('effort-text').classList.add('dim'); }   // the chart decides on its own
  else if (e.peak_bpm - e.rest_bpm < 10) $('effort-text').textContent = `Resting ${e.rest_bpm} bpm. Your heart rate stayed close to that during squats (peak ${e.peak_bpm} bpm).`;
  else $('effort-text').textContent = `Resting ${e.rest_bpm} bpm. Peak ${e.peak_bpm} bpm during squats. Dropped ${e.drop_bpm} bpm in the 30 s after.`;

  const br = s.breathing;
  if (br.ok) {
    const parts = [];
    if (br.rest_per_min != null) parts.push(`At rest you breathed about ${br.rest_per_min} times a minute (estimated from the ECG).`);
    if (br.swing_bpm != null) parts.push(`Breathing slowly, your heart rate rose and fell by about ${br.swing_bpm} bpm with each breath.`);
    if (br.paced_per_min != null) parts.push(`Measured breathing pace ${br.paced_per_min} a minute; the ring paced 6.`);
    $('breathing-text').textContent = parts.join(' ');
  } else refuse('breathing', br.reason);

  const v = s.hrv;
  if (v.ok) {
    $('hrv-figure').textContent = `${v.rmssd_ms} ms`;
    $('hrv-text').textContent = `RMSSD over ${v.window_s} s at rest, with SDNN ${v.sdnn_ms} ms. Both describe how much the time between beats changes from beat to beat.`;
  } else refuse('hrv', v.reason);

  const b = s.beat;
  if (b.ok) $('beat-text').textContent = `Averaged from ${b.n} beats. P wave: the atria contract. QRS: the ventricles contract. T wave: the ventricles relax.`;
  else refuse('beat', b.reason);

  const tm = s.timing;
  if (tm.ok) $('timing-text').textContent = 'Each dot is one beat: the gap before it against the gap after it. Steady timing makes a tight cluster; slow breathing stretches it along the diagonal.';
  else refuse('timing', tm.reason);

  $('sheet').hidden = false;
  draw(s);
  if (!screenMode && !s.demo) $('delete').hidden = false;
}

function draw(s) {
  effortChart(s);
  if (s.breathing.ok) breathingChart(s);
  if (s.beat.ok) beatChart(s);
  if (s.timing.ok) timingChart(s);
}

function gone(text) {
  $('sheet').hidden = true;
  $('gone').textContent = text;
  $('gone').hidden = false;
}

async function load() {
  let res = null;
  try { res = await fetch(`/api/s/${encodeURIComponent(sid)}`, { cache: 'no-store' }); } catch { /* offline */ }
  if (!res || !res.ok) { gone(res ? GONE : 'Could not reach the booth. Try again on the same Wi-Fi.'); return; }
  summary = await res.json();
  try { await document.fonts.load(FONT); } catch { /* the readouts fall back to the system mono */ }
  render(summary);
}

let armed = false;
$('delete').addEventListener('click', async () => {
  const btn = $('delete');
  if (!armed) {
    armed = true;
    btn.textContent = 'Tap again to delete';
    setTimeout(() => { armed = false; btn.textContent = 'Delete my session'; }, 5000);
    return;
  }
  const res = await fetch(`/api/s/${encodeURIComponent(sid)}`, { method: 'DELETE' }).catch(() => null);
  if (res && res.ok) gone('Deleted. Nothing from this session is kept.');
  else btn.textContent = 'Could not delete, try again';
});

window.addEventListener('resize', () => { if (summary) draw(summary); });

// big screen: the QR, back to live on Esc or after a while, and follow the booth's session state
function backToLive() {
  fetch('/api/session/dismiss', { method: 'POST' }).catch(() => {}).finally(leave);
}

// the big screen and the demo page get a way back to the live view (Thomas: there was none)
if (screenMode || sid === 'demo') {
  $('back').hidden = false;
  $('back').addEventListener('click', backToLive);
}

if (screenMode) {
  $('take').hidden = false;
  $('qr').src = `/api/s/${encodeURIComponent(sid)}/qr.svg`;
  setTimeout(backToLive, IDLE_MS);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') backToLive(); });
  let ours = false;   // seen this session on the booth; leave once it is dismissed, deleted or replaced
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type !== 'session') return;
    if (msg.state === 'done' && msg.id === sid) {
      ours = true;
      $('qr').src = `/api/s/${encodeURIComponent(sid)}/qr.svg?v=${Date.now()}`;
      $('qr-text').textContent = msg.online ? 'Scan to keep this on your phone' : 'Scan on the booth Wi-Fi to keep this on your phone';
    } else if (msg.state === 'running' || (ours && msg.state === 'idle')) {
      leave();
    }
  };
}

load();
