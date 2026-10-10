// ECG trace on a canvas. Samples are keyed by stream time; drawing follows t_display.
const FS_DEFAULT = 130;
const KEEP_S = 14;

export const WINDOW_S = 6;
export const NOW_FRAC = 0.92;
export const GUTTER = 48;
export const BASELINE_FRAC = 0.64;

export function fitCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
  const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return { w, h, dpr };
}

const PRE_S = 0.3;      // 3D: seconds shown before each R peak
const POST_S = 0.6;     // 3D: seconds shown after each R peak
const ROWS_3D = 10;     // 3D: beats stacked

export class Trace {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ts = [];
    this.ys = [];
    this.scale = 200;
    this.mode = '2d';
    this.beats = [];      // shared with the chamber lanes, newest last
    this.resetFilter();
  }

  setMode(mode) { this.mode = mode === '3d' ? '3d' : '2d'; }

  resetFilter() {
    const rc = 1 / (2 * Math.PI * 0.5);     // 0.5 Hz one-pole high-pass
    this.a = rc / (rc + 1 / FS_DEFAULT);
    this.prevX = 0; this.prevY = 0; this.primed = false;
  }

  clear() { this.ts.length = 0; this.ys.length = 0; this.resetFilter(); this.scale = 200; }

  push(t0, uv, fs = FS_DEFAULT) {
    for (let i = 0; i < uv.length; i++) {
      const x = uv[i];
      if (!this.primed) { this.prevX = x; this.prevY = 0; this.primed = true; }
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

  // Beat waterfall: the newest beat in front, older ones receding up and back, front ridges hiding the back.
  draw3d(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    if (tDisplay === null || this.ts.length === 0) return;
    const rows = this.beats.filter((b) => b.r <= tDisplay && b.r - PRE_S >= this.ts[0]).slice(-ROWS_3D);
    if (rows.length === 0) return;
    const gutter = GUTTER * dpr;
    const n = rows.length;
    const stepX = (w - gutter) * 0.028;
    const stepY = h * 0.062;
    const span = PRE_S + POST_S;
    const width0 = (w - gutter) * 0.66;
    const base0 = h * 0.86;
    let peak = 0;
    for (const b of rows) {
      const i0 = this.indexAt(b.r - PRE_S), i1 = this.indexAt(Math.min(b.r + POST_S, tDisplay));
      for (let i = i0; i < i1; i++) { const v = Math.abs(this.ys[i]); if (v > peak) peak = v; }
    }
    const target = Math.max(200, peak);
    this.scale = target > this.scale ? target : this.scale + (target - this.scale) * 0.02;
    const amp0 = (h * 0.42) / this.scale;

    for (let k = 0; k < n; k++) {          // oldest first, so the front draws last
      const b = rows[k];
      const depth = n - 1 - k;             // 0 = newest
      const sc = Math.pow(0.965, depth);
      const alpha = Math.max(0.14, 1 - depth * 0.095);
      const x0 = gutter + depth * stepX;
      const base = base0 - depth * stepY;
      const pxPerS = (width0 * sc) / span;
      const amp = amp0 * sc;
      const tEnd = Math.min(b.r + POST_S, tDisplay);
      const i0 = this.indexAt(b.r - PRE_S), i1 = this.indexAt(tEnd);
      if (i1 - i0 < 2) continue;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x0, base);
      for (let i = i0; i < i1; i++) ctx.lineTo(x0 + (this.ts[i] - (b.r - PRE_S)) * pxPerS, base - this.ys[i] * amp);
      ctx.lineTo(x0 + (this.ts[i1 - 1] - (b.r - PRE_S)) * pxPerS, base);
      ctx.closePath();
      ctx.fillStyle = 'rgba(7,10,18,0.94)';
      ctx.fill();
      ctx.strokeStyle = `rgba(232,236,243,${(0.10 * alpha).toFixed(3)})`;
      ctx.lineWidth = 1 * dpr;
      ctx.beginPath(); ctx.moveTo(x0, base); ctx.lineTo(x0 + width0 * sc, base); ctx.stroke();
      ctx.strokeStyle = `rgba(67,224,160,${alpha.toFixed(3)})`;
      ctx.lineWidth = (depth === 0 ? 2.2 : 1.6) * dpr;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      if (depth === 0) { ctx.shadowColor = 'rgba(67,224,160,0.35)'; ctx.shadowBlur = 5 * dpr; }
      ctx.beginPath();
      for (let i = i0; i < i1; i++) {
        const x = x0 + (this.ts[i] - (b.r - PRE_S)) * pxPerS;
        const y = base - this.ys[i] * amp;
        if (i === i0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.restore();
    }
  }

  draw(tDisplay) {
    if (this.mode === '3d') { this.draw3d(tDisplay); return; }
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const gutter = GUTTER * dpr;
    const drawable = w - gutter;
    const xNow = gutter + drawable * NOW_FRAC;
    const tLeft = tDisplay === null ? 0 : tDisplay - WINDOW_S * NOW_FRAC;
    const pxPerS = drawable / WINDOW_S;
    const baseline = h * BASELINE_FRAC;

    // grid
    ctx.save();
    ctx.strokeStyle = 'rgba(140,151,171,0.07)';
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
    const amp = (h * 0.5) / this.scale;

    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter, 0, drawable, h);
    ctx.clip();
    ctx.strokeStyle = '#43E0A0';
    ctx.lineWidth = 2 * dpr;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowColor = 'rgba(67,224,160,0.35)';
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
