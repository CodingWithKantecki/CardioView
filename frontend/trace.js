// ECG trace on a canvas. Samples are keyed by stream time; drawing follows t_display.
import { colors, alpha } from './theme.js';
const FS_DEFAULT = 130;
const KEEP_S = 40;   // the timeline reaches back 30 s, plus the 6 s window

export const WINDOW_S = 6;       // seconds from the left edge to the now line
export const NOW_INSET = 12;     // CSS px between the now line and the right edge: the graphs fill their box
export const GUTTER = 0;         // no left gutter; the lane letters sit inside their lanes
export const BASELINE_FRAC = 0.66;

// the shared time axis of the trace and the lanes, so beats line up between them
export function geometry(w, dpr) {
  const gutter = GUTTER * dpr, xNow = w - NOW_INSET * dpr;
  return { gutter, xNow, pxPerS: (xNow - gutter) / WINDOW_S };
}

export function fitCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
  const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return { w, h, dpr };
}

// quadratic curves through the midpoints between samples: smooth, no overshoot
function roundedPath(ctx, pts) {
  for (let i = 1; i < pts.length - 1; i++) {
    const xc = (pts[i][0] + pts[i + 1][0]) / 2;
    const yc = (pts[i][1] + pts[i + 1][1]) / 2;
    ctx.quadraticCurveTo(pts[i][0], pts[i][1], xc, yc);
  }
  const l = pts[pts.length - 1];
  ctx.lineTo(l[0], l[1]);
}

const PRE_S = 0.3;      // 3D: seconds shown before each R peak
const POST_S = 0.6;     // 3D: seconds shown after each R peak
const ROWS_3D = 8;      // 3D: beats stacked
const BEAT_GAP_S = 0.08; // 3D: a row stops this far short of the neighboring beats, so a fast rhythm never shows two R peaks in one row

export class Trace {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ts = [];
    this.ys = [];
    this.scale = 200;
    this.mode = '2d';
    this.fs = FS_DEFAULT;
    this.beats = [];      // shared with the chamber lanes, newest last
    this.amp3d = 0;
    this.resetFilter();
  }

  setMode(mode) { this.mode = mode === '3d' ? '3d' : '2d'; }

  resetFilter() {
    const rc = 1 / (2 * Math.PI * 0.5);     // 0.5 Hz one-pole high-pass
    this.a = rc / (rc + 1 / FS_DEFAULT);
    this.prevX = 0; this.prevY = 0; this.primed = false;
  }

  clear() { this.ts.length = 0; this.ys.length = 0; this.resetFilter(); this.scale = 200; }

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
    }
    const newest = this.ts[this.ts.length - 1];
    let drop = 0;
    while (drop < this.ts.length && this.ts[drop] < newest - KEEP_S) drop++;
    if (drop > 0) { this.ts.splice(0, drop); this.ys.splice(0, drop); }
  }

  // first sample index with time >= t
  indexAt(t) {
    let lo = 0, hi = this.ts.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.ts[mid] < t) lo = mid + 1; else hi = mid; }
    return lo;
  }

  // Beat waterfall: the newest beat in front, older ones receding up and back. Rows slide back
  // continuously, timed by the next beat's real time, so nothing jumps; the scale eases both
  // ways; the vertical budget keeps the up and down swings inside the panel.
  draw3d(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    this.drawRate(ctx, GUTTER * dpr, dpr);
    if (tDisplay === null || this.ts.length === 0) return;
    const T = colors();
    const all = this.beats.filter((b) => b.r - PRE_S >= this.ts[0]);
    const shown = all.filter((b) => b.r - PRE_S <= tDisplay);
    const rows = shown.slice(-ROWS_3D);
    if (rows.length === 0) return;
    const gutter = GUTTER * dpr;
    const n = rows.length;
    const newest = rows[n - 1];
    const next = all[all.indexOf(newest) + 1];                 // usually known already: beats arrive before they are displayed
    const span0 = next ? next.r - newest.r : (newest.rr || 0.8);
    const phase = Math.min(1, Math.max(0, (tDisplay - (newest.r - PRE_S)) / span0));
    const stepX = w * 0.012;
    const stepY = h * 0.08;
    const span = PRE_S + POST_S;
    const width0 = w * 0.86;
    const left0 = (w - width0) / 2;   // the front row sits centered in the box; rows behind drift right and shrink
    const base0 = h * 0.87;

    let up = 0, down = 0;
    for (const b of rows) {
      const i0 = this.indexAt(b.r - PRE_S), i1 = this.indexAt(Math.min(b.r + POST_S, tDisplay));
      for (let i = i0; i < i1; i++) { const v = this.ys[i]; if (v > up) up = v; if (-v > down) down = -v; }
    }
    const targetAmp = Math.min((h * 0.27) / Math.max(200, up), (h * 0.12) / Math.max(120, down));
    this.amp3d = this.amp3d ? this.amp3d + (targetAmp - this.amp3d) * 0.08 : targetAmp;
    const amp0 = this.amp3d;

    for (let k = 0; k < n; k++) {          // oldest first, so the front draws last
      const b = rows[k];
      const depth = (n - 1 - k) + phase;   // 0 = a beat that just started
      const sc = Math.pow(0.96, depth);
      const age = tDisplay - (b.r - PRE_S);                                   // seconds since this row began
      const rowAlpha = Math.max(0, 1 - depth / (ROWS_3D + 0.5)) * Math.min(1, age / 0.2);   // fade in, fade out at the back
      if (rowAlpha <= 0) continue;
      const x0 = left0 + depth * stepX;
      const base = base0 - depth * stepY;
      const pxPerS = (width0 * sc) / span;
      const amp = amp0 * sc;
      const idx = all.indexOf(b);
      const prev = all[idx - 1], nxt = all[idx + 1];
      const tStart = Math.max(b.r - PRE_S, prev ? prev.r + BEAT_GAP_S : -Infinity);
      const tEnd = Math.min(b.r + POST_S, nxt ? nxt.r - BEAT_GAP_S : Infinity, tDisplay);
      const i0 = this.indexAt(tStart), i1 = this.indexAt(tEnd);
      if (i1 - i0 < 3) continue;
      const pts = [];
      for (let i = i0; i < i1; i++) pts.push([x0 + (this.ts[i] - (b.r - PRE_S)) * pxPerS, base - this.ys[i] * amp]);
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(pts[0][0], base);
      ctx.lineTo(pts[0][0], pts[0][1]);
      roundedPath(ctx, pts);
      ctx.lineTo(pts[pts.length - 1][0], base);
      ctx.closePath();
      ctx.fillStyle = alpha(T.paper, 0.96 * Math.min(1, age / 0.2));
      ctx.fill();
      if (depth < 1) {
        const g = ctx.createLinearGradient(0, base - h * 0.2, 0, base);
        g.addColorStop(0, alpha(T.trace, 0.22 * (1 - depth) * Math.min(1, age / 0.2)));
        g.addColorStop(1, alpha(T.trace, 0));
        ctx.fillStyle = g;
        ctx.fill();
      }
      ctx.strokeStyle = alpha(T.rule, 0.12 * rowAlpha);
      ctx.lineWidth = 1 * dpr;
      ctx.beginPath(); ctx.moveTo(x0, base); ctx.lineTo(x0 + width0 * sc, base); ctx.stroke();
      ctx.strokeStyle = alpha(T.trace, rowAlpha);
      ctx.lineWidth = (1.2 + 0.8 * Math.max(0, 1 - depth)) * dpr;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      roundedPath(ctx, pts);
      ctx.stroke();
      ctx.restore();
    }
  }

  draw(tDisplay) {
    if (this.mode === '3d') { this.draw3d(tDisplay); return; }
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
    ctx.shadowColor = alpha(T.trace, 0.3);
    ctx.shadowBlur = 5 * dpr;
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
