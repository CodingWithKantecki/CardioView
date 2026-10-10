// The small ECG strips in the rhythm tips: 4 s of each simulated rhythm, drawn from the same beat
// shapes and interval rules as the simulator (backend/sources/rhythm.py), clean, with no noise.
import { colors, alpha } from './theme.js';

const NORMAL = [[-0.18, 0.12, 0.022], [-0.03, -0.10, 0.009], [0, 1.0, 0.011], [0.025, -0.25, 0.010], [0.25, 0.30, 0.050]];
const NO_P = NORMAL.slice(1);
const WIDE = [[-0.01, 1.1, 0.035], [0.06, -0.7, 0.045], [0.30, -0.45, 0.075]];
// a heart attack beat with the ST segment fully lifted (the simulator's infarct(1))
const INFARCT = [[-0.18, 0.12, 0.022], [-0.03, -0.10, 0.009], [0, 1.0, 0.011], [0.025, -0.05, 0.010], [0.10, 0.40, 0.045], [0.23, 0.60, 0.065]];
const SECONDS = 4;

function rng(seed) {   // mulberry32, so every strip is the same each time
  return () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

function beats(pattern) {
  const r = rng(11);
  const out = [];
  let last = 0.2;
  for (let i = 0; last < SECONDS + 1; i++) {
    let rr = 0.83, tpl = NORMAL;
    if (pattern === 'brady') rr = 1.4;
    else if (pattern === 'afib') { rr = 0.35 + r() * 0.7; tpl = NO_P; }
    else if (pattern === 'vt') { rr = 0.40; tpl = WIDE; }
    else if (pattern === 'mi') { rr = 0.60; tpl = INFARCT; }
    else if (pattern === 'pvc') { const k = i % 4; if (k === 3) { rr = 0.52; tpl = WIDE; } else if (k === 0 && i > 0) rr = 1.15; }
    last += rr;
    out.push([last, tpl]);
  }
  return out;
}

function value(t, bs, pattern) {
  let v = 0;
  for (const [r, tpl] of bs) {
    const dt = t - r;
    if (dt <= -0.5 || dt >= 0.7) continue;
    for (const [c, a, w] of tpl) v += a * Math.exp(-((dt - c) ** 2) / (2 * w * w));
  }
  if (pattern === 'afib') v += 0.045 * Math.sin(2 * Math.PI * 6.3 * t) * (0.6 + 0.4 * Math.sin(2 * Math.PI * 0.37 * t));
  return v;
}

export function drawRhythmTips() {
  const T = colors();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  for (const canvas of document.querySelectorAll('canvas.tip-ecg')) {
    const w = Math.round(272 * dpr), h = Math.round(60 * dpr);   // the tips are hidden until hovered, so the size is fixed here
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, w, h);
    const pxPerS = w / SECONDS;
    ctx.strokeStyle = alpha(T.grid, 0.12);
    ctx.lineWidth = 1 * dpr;
    for (let x = 0; x <= w; x += pxPerS * 0.2) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
    const pattern = canvas.dataset.rhythm;
    const bs = beats(pattern);
    const base = h * 0.7, amp = h * 0.55;
    ctx.strokeStyle = T.trace;
    ctx.lineWidth = 1.5 * dpr;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    for (let x = 0; x <= w; x += Math.max(1, dpr * 0.5)) {
      const t = 0.3 + x / pxPerS;
      const y = base - value(t, bs, pattern) * amp;
      if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}
