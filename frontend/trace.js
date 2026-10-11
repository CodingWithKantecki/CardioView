// ECG trace on a canvas. Samples are keyed by stream time; drawing follows t_display.
import { colors, alpha } from './theme.js';
const FS_DEFAULT = 130;
export const KEEP_S = 120;      // history kept while live: the timeline's 30 s window can pan back through it
export const MAX_KEEP_S = 900;  // off live the history is held, but never more than this

export const WINDOW_S = 6;       // seconds from the left edge to the now line
export const NOW_INSET = 12;     // CSS px between the now line and the right edge: the graphs fill their box
export const GUTTER = 0;         // no left gutter; the lane letters sit inside their lanes
export const BASELINE_FRAC = 0.66;

// the shared time axis of the trace and the lanes, so beats line up between them
export function geometry(w, dpr) {
  const gutter = GUTTER * dpr, xNow = w - NOW_INSET * dpr;
  return { gutter, xNow, pxPerS: (xNow - gutter) / WINDOW_S };
}

// where a buffer may be trimmed to: KEEP_S behind the newest sample, or further back while the
// timeline holds history from `holdFrom` (null when live), within MAX_KEEP_S
export function keepCut(newest, holdFrom) {
  let cut = newest - KEEP_S;
  if (holdFrom !== null && holdFrom !== undefined) cut = Math.min(cut, holdFrom);
  return Math.max(cut, newest - MAX_KEEP_S);
}

export function fitCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
  const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return { w, h, dpr };
}

export class Trace {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ts = [];
    this.ys = [];
    this.raw = [];   // the microvolts as received, for Export; ys holds the filtered trace
    this.scale = 200;
    this.holdFrom = null;   // set by the timeline while off live: keep samples from here
    this.fs = FS_DEFAULT;
    this.beats = [];      // shared with the chamber lanes, newest last
    this.resetFilter();
  }

  resetFilter() {
    const rc = 1 / (2 * Math.PI * 0.5);     // 0.5 Hz one-pole high-pass
    this.a = rc / (rc + 1 / FS_DEFAULT);
    this.prevX = 0; this.prevY = 0; this.primed = false;
  }

  clear() { this.ts.length = 0; this.ys.length = 0; this.raw.length = 0; this.resetFilter(); this.scale = 200; }

  // the sample rate, small, in the graph's top-left corner
  drawRate(ctx, gutter, dpr) {
    ctx.save();
    ctx.font = `600 ${12 * dpr}px "JetBrains Mono", monospace`;
    ctx.fillStyle = colors().dim;
    ctx.textBaseline = 'top';
    ctx.fillText(`${this.fs} HZ`, gutter + 4 * dpr, 4 * dpr);
    ctx.restore();
  }

  push(t0, uv, fs = FS_DEFAULT) {
    this.fs = fs;
    for (let i = 0; i < uv.length; i++) {
      const x = uv[i];
      if (!this.primed) { this.prevX = x; this.prevY = 0; this.primed = true; }
      if (this.prevX === null) this.prevX = x;
      const y = this.a * (this.prevY + x - this.prevX);
      this.prevX = x; this.prevY = y;
      this.ts.push(t0 + i / fs);
      this.ys.push(y);
      this.raw.push(x);
    }
    const newest = this.ts[this.ts.length - 1];
    let drop = 0;
    const cut = keepCut(newest, this.holdFrom);
    while (drop < this.ts.length && this.ts[drop] < cut) drop++;
    if (drop > 0) { this.ts.splice(0, drop); this.ys.splice(0, drop); this.raw.splice(0, drop); }
  }

  // first sample index with time >= t
  indexAt(t) {
    let lo = 0, hi = this.ts.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.ts[mid] < t) lo = mid + 1; else hi = mid; }
    return lo;
  }

  draw(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const { gutter, xNow, pxPerS } = geometry(w, dpr);
    const drawable = w - gutter;
    const tLeft = tDisplay === null ? 0 : tDisplay - WINDOW_S;
    const baseline = h * BASELINE_FRAC;

    // grid
    ctx.save();
    const T = colors();
    ctx.strokeStyle = alpha(T.grid, 0.12);
    ctx.lineWidth = 1 * dpr;
    const stepPx = pxPerS * 0.2;
    const phase = tDisplay === null ? 0 : ((tLeft % 0.2) + 0.2) % 0.2;
    for (let x = gutter - phase * pxPerS; x <= w; x += stepPx) {
      if (x < gutter) continue;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = baseline; y >= 0; y -= stepPx) { ctx.beginPath(); ctx.moveTo(gutter, y); ctx.lineTo(w, y); ctx.stroke(); }
    for (let y = baseline + stepPx; y <= h; y += stepPx) { ctx.beginPath(); ctx.moveTo(gutter, y); ctx.lineTo(w, y); ctx.stroke(); }
    ctx.restore();

    this.drawRate(ctx, gutter, dpr);
    if (tDisplay === null || this.ts.length === 0) return;

    // scale follows the recent peak, floor 200 uV
    let peak = 0;
    let first = this.ts.length;
    for (let i = 0; i < this.ts.length; i++) {
      if (this.ts[i] < tLeft) continue;
      if (first === this.ts.length) first = i;
      if (this.ts[i] > tDisplay) break;
      const v = Math.abs(this.ys[i]);
      if (v > peak) peak = v;
    }
    const target = Math.max(200, peak);
    this.scale = target > this.scale ? target : this.scale + (target - this.scale) * 0.02;
    const amp = (h * 0.56) / this.scale;   // the recent peak reaches a tenth from the top

    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter, 0, drawable, h);
    ctx.clip();
    ctx.strokeStyle = T.trace;
    ctx.lineWidth = 2 * dpr;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    let pen = false;
    let prevT = null;
    for (let i = first; i < this.ts.length; i++) {
      const t = this.ts[i];
      if (t > tDisplay) break;
      const x = gutter + (t - tLeft) * pxPerS;
      const y = baseline - this.ys[i] * amp;
      if (!pen || (prevT !== null && t - prevT > 2.5 / FS_DEFAULT)) { ctx.moveTo(x, y); pen = true; }
      else ctx.lineTo(x, y);
      prevT = t;
    }
    ctx.stroke();
    ctx.restore();
  }
}

// Everything the page keeps, as the CSV the recordings use (time_s,ecg_uv, time from zero), so a
// file replays with --source. Beats are not written: the detector finds them again on replay.
export function exportCsv(trace) {
  const n = trace.ts.length;
  if (!n) return null;
  const t0 = trace.ts[0];
  const rows = new Array(n + 1);
  rows[0] = 'time_s,ecg_uv';
  for (let i = 0; i < n; i++) rows[i + 1] = `${(trace.ts[i] - t0).toFixed(4)},${trace.raw[i]}`;
  return { text: rows.join('\n') + '\n', seconds: trace.ts[n - 1] - t0 };
}
