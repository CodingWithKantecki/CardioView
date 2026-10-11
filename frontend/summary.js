// The report of a saved session or an export. A band of small boxes across the top (heart rate
// over time, the numbers, the average beat, the QR), then the ECG itself as rhythm strips on
// medical paper: 25 mm/s, 10 mm/mV, the 1 mm and 5 mm grid, a 1 mV calibration pulse at the
// start of every row. One page for the big screen (?screen=1, in the overlay over the live view),
// a phone on the booth Wi-Fi, the public link, and the printed PDF (?print=1 renders the page as
// the printed document, light, then prints it). It reads /api/s/<id> and /api/s/<id>/ecg.

const $ = (id) => document.getElementById(id);
const sid = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');
const params = new URLSearchParams(location.search);
const screenMode = params.has('screen');
const printMode = params.has('print');
const FONT = `600 ${new URLSearchParams(location.search).has('print') ? 14 : 12}px "JetBrains Mono", monospace`;   // chart readouts, in capitals like the 130 HZ corner on the live ECG; bigger on paper
const WAVE = '700 15px "Helvetica Neue", Helvetica, Arial, sans-serif';   // P, QRS, T, the voice of the chamber names
const STEP_NAME = { ready: 'GET READY', rest: 'REST', breathe: 'BREATHE', squats: 'SQUATS', recover: 'RECOVER' };   // an export has no steps to mark
const IDLE_MS = 180000;   // the big screen goes back to live after 3 minutes
const GONE = 'This session is no longer available.';

// ECG paper: a pink grid on near-white, the trace in black, as a clinical printout
const PAPER = { bg: '#FFF8F5', minor: '#F3C9C5', major: '#E29C96', ink: '#14171C', label: '#8A3434' };
const MM_PER_S = 25;      // the standard paper speed
const MM_PER_MV = 10;     // the standard gain
const ROW_MM = 26;        // a row is 26 mm tall: plus 1.6 mV above the baseline, minus 1 mV below
const BASE_FRAC = 0.62;   // the baseline sits below the middle: R peaks go up
const LEAD_S = 0.5;       // the lead-in at the left of every row holds the 1 mV calibration pulse
const HIGHPASS_HZ = 0.5;  // the live trace's one-pole high-pass, so the baseline sits still

// embedded: the booth shows this page in an overlay over the live view; leaving means closing it
const embedded = params.has('embed') && window.parent !== window;
function leave() {
  if (embedded) window.parent.postMessage({ type: 'cardioview-report', action: 'back' }, location.origin);
  else location.assign('/');
}

let summary = null;
let ecg = null;   // { fs, t0, uv } or null when this server has no recording (the cloud copy)
if (screenMode) document.body.classList.add('screen');
if (printMode) document.body.classList.add('print');

function alpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// chart colors come from the stylesheet, read when drawing, so the printed document gets its own
function palette() {
  const cs = getComputedStyle(document.body);   // body.print carries the printed document's colors
  const v = (k) => cs.getPropertyValue(k).trim();
  return { text: v('--c-ink'), dim: v('--c-dim'), hair: alpha(v('--c-rule'), 0.14), ecg: v('--c-trace') };
}

const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const day = (iso) => `${new Date(iso).toLocaleDateString([], { weekday: 'short' })} ${time(iso)}`;
const scale = (lo, hi, a, b) => (v) => a + ((v - lo) * (b - a)) / ((hi - lo) || 1);
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function canvas2d(el, dprWanted = null) {
  const r = el.getBoundingClientRect();
  const dpr = dprWanted || window.devicePixelRatio || 1;
  el.width = Math.max(1, Math.round(r.width * dpr));
  el.height = Math.max(1, Math.round(r.height * dpr));
  el.style.aspectRatio = `${Math.round(r.width)} / ${Math.round(r.height)}`;   // print scales the drawing as is, so it keeps its shape
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

// heart rate over the whole stretch, one value a second, the steps marked, the peak dotted
function rateChart(s, C) {
  const bpm = s.hr_chart?.bpm || [];
  const vals = bpm.filter((v) => v != null);
  const el = $('rate-chart');
  if (vals.length < 0.5 * bpm.length || vals.length < 2) { el.hidden = true; return; }   // mostly gaps: a chart would only show noise
  el.hidden = false;
  const { g, w, h } = canvas2d(el, printMode ? 3 : null);
  const lo = Math.floor(Math.min(...vals) / 10) * 10 - 5;
  const hi = Math.ceil(Math.max(...vals) / 10) * 10 + 5;
  const pad = { l: 30, r: 8, t: 18, b: 6 };
  const x = scale(0, bpm.length - 1, pad.l, w - pad.r);
  const y = scale(lo, hi, h - pad.b, pad.t);
  g.strokeStyle = C.hair;
  g.lineWidth = 1;
  g.fillStyle = C.dim;
  const every = hi - lo > 60 ? 40 : 20;
  for (let v = Math.ceil(lo / every) * every; v <= hi; v += every) { hline(g, pad.l, w - pad.r, y(v)); g.fillText(String(v), 0, y(v) + 4); }
  for (const st of s.steps || []) {
    if (!STEP_NAME[st.name] || st.start <= 0) continue;
    const xs = x(Math.min(st.start, bpm.length - 1));
    g.strokeStyle = C.hair;
    vline(g, xs, 2, h - pad.b);
    g.fillStyle = C.dim;
    g.fillText(STEP_NAME[st.name], xs + 5, 12);
  }
  trace(g, bpm, x, y, C.text, 1.8);
  if (s.effort?.ok) {
    const i = bpm.indexOf(Math.max(...vals));
    g.fillStyle = C.text;
    g.beginPath(); g.arc(x(i), y(bpm[i]), 3.5, 0, 2 * Math.PI); g.fill();
    g.fillText(`PEAK ${s.effort.peak_bpm}`, Math.min(x(i) + 8, w - 64), y(bpm[i]) + 4);
  }
}

// the average beat with its waves named
function beatChart(s, C) {
  const b = s.beat;
  const { g, w, h } = canvas2d($('beat-chart'), printMode ? 3 : null);
  const n = b.uv.length;
  const t = (i) => b.t0 + i / b.fs;
  const lo = Math.min(...b.uv);
  const hi = Math.max(...b.uv);
  const pad = { l: 6, r: 6, t: 22, b: 6 };
  const x = scale(t(0), t(n - 1), pad.l, w - pad.r);
  const y = scale(lo - 0.05 * (hi - lo), hi, h - pad.b, pad.t);
  g.strokeStyle = C.hair;
  hline(g, pad.l, w - pad.r, y(0));
  trace(g, b.uv, (i) => x(t(i)), y, C.ecg, 2);
  g.fillStyle = C.dim;
  g.fillText(`${b.fs} HZ`, pad.l, 12);
  g.font = WAVE;
  g.fillStyle = C.text;
  g.textAlign = 'center';
  for (const [name, at] of [['P', b.waves.p], ['QRS', b.waves.qrs], ['T', b.waves.t]]) {
    if (at == null) continue;
    const i = Math.round((at - b.t0) * b.fs);
    const near = b.uv.slice(Math.max(0, i - 5), i + 6);
    g.fillText(name, x(at), y(Math.max(...near)) - 8);
  }
  g.textAlign = 'start';
}

// the numbers: the rate over the stretch, the beats, the variability, the breathing
function stats(s) {
  const bpm = (s.hr_chart?.bpm || []).filter((v) => v != null);
  const mean = bpm.length ? Math.round(bpm.reduce((a, b) => a + b, 0) / bpm.length) : null;
  const items = [];
  if (mean != null) items.push([`${mean}<small>bpm</small>`, `average, ${Math.round(Math.min(...bpm))} to ${Math.round(Math.max(...bpm))}`]);
  else items.push(['--', 'heart rate']);
  const beats = s.beat?.ok ? s.beat.n : s.hrv?.ok ? s.hrv.n : null;
  const seconds = s.export ? s.seconds : Math.round(s.steps?.at(-1)?.end || 0);
  items.push([beats != null ? String(beats) : '--', `beats in ${clock(seconds)}`]);
  if (s.hrv?.ok) items.push([`${s.hrv.rmssd_ms}<small>ms</small>`, 'variability, rmssd']);
  else items.push(['--', 'variability']);
  const br = s.breathing;
  if (br?.ok && br.rest_per_min != null) items.push([`${br.rest_per_min}<small>a min</small>`, 'breathing at rest']);
  else if (br?.ok && br.paced_per_min != null) items.push([`${br.paced_per_min}<small>a min</small>`, 'breathing, paced']);
  else items.push(['--', 'breathing']);
  $('stats').innerHTML = items.map(([fig, label]) => `<div><b>${fig}</b><span>${label}</span></div>`).join('');
}

// the baseline held still, as the live trace does it
function highpass(uv, fs) {
  const rc = 1 / (2 * Math.PI * HIGHPASS_HZ);
  const a = rc / (rc + 1 / fs);
  const out = new Float32Array(uv.length);
  let px = uv[0] || 0, py = 0;
  for (let i = 0; i < uv.length; i++) {
    const y = a * (py + uv[i] - px);
    px = uv[i]; py = y;
    out[i] = y;
  }
  return out;
}

// seconds a row holds: the printed strip is 10 s at the true paper speed; the screen fits the
// stretch in rows of 20 s (30 s for long stretches), a phone takes 5 s
function rowSeconds(total) {
  if (printMode) return 10;
  if (document.body.clientWidth < 760) return 5;
  return total > 150 ? 30 : 20;
}

// the rhythm strips: one canvas a row, the grid, the calibration pulse, the trace, the time and
// the rate of that row, and the step that starts in it
function strips(s) {
  const host = $('strips');
  host.innerHTML = '';
  if (!ecg || !ecg.uv.length) { $('strips-note').hidden = false; $('strips-sub').textContent = ''; return; }
  $('strips-note').hidden = true;
  const fs = ecg.fs;
  const total = ecg.uv.length / fs;
  const y = highpass(ecg.uv, fs);
  const rowS = rowSeconds(total);
  const rows = Math.ceil(total / rowS);
  const bpm = s.hr_chart?.bpm || [];
  const steps = (s.steps || []).filter((st) => STEP_NAME[st.name]);
  $('strips-sub').textContent = `${clock(Math.round(total))} at ${MM_PER_S} mm/s, ${MM_PER_MV} mm/mV, ${fs} Hz`;
  const width = host.getBoundingClientRect().width;
  for (let r = 0; r < rows; r++) {
    const c = document.createElement('canvas');
    c.className = 'strip';
    if (!printMode) {   // on screen the row's height follows its width, so a millimetre is the same both ways
      const pxPerMm = width / (rowS + LEAD_S) / MM_PER_S;
      c.style.height = `${Math.round(ROW_MM * pxPerMm)}px`;
    }
    host.appendChild(c);
    stripRow(c, r, rowS, y, fs, bpm, steps, total);
  }
}

function stripRow(canvas, r, rowS, y, fs, bpm, steps, total) {
  const { g, w, h } = canvas2d(canvas, printMode ? 3 : null);
  const t0 = r * rowS;
  const pxPerS = w / (rowS + LEAD_S);
  const pxPerMm = pxPerS / MM_PER_S;
  const pxPerUv = (MM_PER_MV * pxPerMm) / 1000;
  const base = h * BASE_FRAC;
  const x = (t) => (LEAD_S + t - t0) * pxPerS;

  // the paper and its grid: a line a millimetre, a stronger one every five
  g.fillStyle = PAPER.bg;
  g.fillRect(0, 0, w, h);
  for (let i = 0; i * pxPerMm <= w; i++) {
    g.strokeStyle = i % 5 === 0 ? PAPER.major : PAPER.minor;
    g.lineWidth = i % 5 === 0 ? 1 : 0.6;
    vline(g, i * pxPerMm, 0, h);
  }
  for (let i = 0; base - i * pxPerMm >= 0 || base + i * pxPerMm <= h; i++) {
    g.strokeStyle = i % 5 === 0 ? PAPER.major : PAPER.minor;
    g.lineWidth = i % 5 === 0 ? 1 : 0.6;
    if (base - i * pxPerMm >= 0) hline(g, 0, w, base - i * pxPerMm);
    if (i > 0 && base + i * pxPerMm <= h) hline(g, 0, w, base + i * pxPerMm);
  }

  // the calibration pulse: 1 mV for 0.2 s, in the lead-in
  const mv = 1000 * pxPerUv;
  const c0 = 0.12 * pxPerS, c1 = c0 + 0.2 * pxPerS;
  g.strokeStyle = PAPER.ink;
  g.lineWidth = 1.4;
  g.lineJoin = 'miter';
  g.beginPath();
  g.moveTo(c0 - 0.06 * pxPerS, base); g.lineTo(c0, base); g.lineTo(c0, base - mv); g.lineTo(c1, base - mv); g.lineTo(c1, base); g.lineTo(c1 + 0.06 * pxPerS, base);
  g.stroke();

  // the trace, clipped to the row
  const i0 = Math.max(0, Math.floor(t0 * fs) - 1);
  const i1 = Math.min(y.length, Math.ceil((t0 + rowS) * fs) + 1);
  g.save();
  g.beginPath(); g.rect(LEAD_S * pxPerS, 0, w, h); g.clip();
  g.strokeStyle = PAPER.ink;
  g.lineWidth = 1.5;
  g.lineJoin = 'round';
  g.beginPath();
  for (let i = i0; i < i1; i++) {
    const px = x(i / fs), py = base - y[i] * pxPerUv;
    if (i === i0) g.moveTo(px, py); else g.lineTo(px, py);
  }
  g.stroke();
  g.restore();

  // the row's time and its rate, top left; the paper speed on the first row, top right
  g.font = FONT;
  g.fillStyle = PAPER.label;
  g.textBaseline = 'top';
  const secs = Math.min(rowS, total - t0);
  const here = bpm.slice(Math.floor(t0), Math.max(Math.floor(t0) + 1, Math.floor(t0 + secs))).filter((v) => v != null);
  const rate = here.length ? Math.round(here.reduce((a, b) => a + b, 0) / here.length) : null;
  g.fillText(`${clock(t0)}${rate != null ? `   ${rate} BPM` : ''}`, 6, 4);
  if (r === 0) { g.textAlign = 'right'; g.fillText(`${MM_PER_S} MM/S  ${MM_PER_MV} MM/MV`, w - 6, 4); g.textAlign = 'start'; }
  for (const st of steps) {
    if (st.start < t0 - 0.01 || st.start >= t0 + rowS) continue;
    const sx = x(Math.max(st.start, t0));
    g.strokeStyle = PAPER.label;
    g.lineWidth = 1.2;
    vline(g, sx, 2, h - 2);
    g.fillText(STEP_NAME[st.name], sx + 4, h - 16);
  }
  g.textBaseline = 'alphabetic';
}

// whose heart it was: the strap's wearer, or the booth's demo data (never presented as the visitor's)
function who(s) {
  if (s.export) return s.source === 'live' ? 'Exported ECG' : s.source === 'recorded' ? 'Exported recording' : 'Exported simulation';
  if (s.source === 'recorded') return 'Session on recorded data';
  if (s.source === 'simulated') return 'Session on simulated data';
  return 'Your session';
}

function render(s) {
  const minutes = Math.max(1, Math.round((s.steps?.at(-1)?.end || 60) / 60));
  const length = s.export ? `${s.seconds} s` : `${minutes} min`;
  $('meta').textContent = s.demo
    ? 'Demo session, synthetic data'
    : `${who(s)}, ${length}, ${time(s.created)}${s.ended_early ? ', ended early' : ''}`;
  $('until').textContent = s.demo ? '' : `Available until ${day(s.keep_until)}`;

  const e = s.effort;
  if (s.export) $('rate-text').textContent = '';
  else if (!e.ok) $('rate-text').textContent = e.reason;
  else if (e.peak_bpm - e.rest_bpm < 10) $('rate-text').textContent = `Resting ${e.rest_bpm} bpm. It stayed close to that during squats (peak ${e.peak_bpm} bpm).`;
  else $('rate-text').textContent = `Resting ${e.rest_bpm} bpm. Peak ${e.peak_bpm} bpm during squats. Down ${e.drop_bpm} bpm in the 30 s after.`;
  $('rate-text').hidden = !$('rate-text').textContent;

  stats(s);
  const b = s.beat;
  if (b.ok) $('beat-text').textContent = `Averaged from ${b.n} beats. P: the atria contract. QRS: the ventricles contract. T: they relax.`;
  else { $('beat').classList.add('refused'); $('beat-text').textContent = b.reason; }

  $('sheet').hidden = false;
  draw(s);
  if (!screenMode && !printMode && !s.demo) $('delete').hidden = false;
  if (printMode) {   // the Export menu's PDF: Save as PDF in the dialog; the booth's page drops this frame once the dialog closes
    window.addEventListener('afterprint', () => { if (embedded) window.parent.postMessage({ type: 'cardioview-report', action: 'printed' }, location.origin); }, { once: true });
    setTimeout(() => window.print(), 900);
  }
}

function draw(s) {
  const C = palette();
  rateChart(s, C);
  if (s.beat.ok) beatChart(s, C);
  strips(s);
}

function gone(text) {
  $('sheet').hidden = true;
  $('gone').textContent = text;
  $('gone').hidden = false;
}

async function load() {
  const id = encodeURIComponent(sid);
  let res = null;
  try { res = await fetch(`/api/s/${id}`, { cache: 'no-store' }); } catch { /* offline */ }
  if (!res || !res.ok) { gone(res ? GONE : 'Could not reach the booth. Try again on the same Wi-Fi.'); return; }
  summary = await res.json();
  try {
    const r = await fetch(`/api/s/${id}/ecg`, { cache: 'no-store' });
    ecg = r.ok ? await r.json() : null;
  } catch { ecg = null; }
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

let resizeTimer = null;
window.addEventListener('resize', () => {
  if (!summary || printMode) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => draw(summary), 150);
});

// the big screen and the demo page get a way back to the live view (Thomas: there was none)
if (screenMode || sid === 'demo') {
  $('back').hidden = false;
  $('back').addEventListener('click', leave);
}

if (screenMode || printMode) {
  $('take').hidden = false;
  $('qr').src = `/api/s/${encodeURIComponent(sid)}/qr.svg`;
}
if (screenMode && !printMode) setTimeout(leave, IDLE_MS);

load();
