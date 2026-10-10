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

export function drawNowLine(ctx, x, top, bottom, dpr, label) {
  ctx.save();
  ctx.setLineDash([3 * dpr, 5 * dpr]);
  ctx.strokeStyle = 'rgba(232,236,243,0.6)';
  ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
  ctx.restore();
  if (label) {
    ctx.save();
    ctx.font = `${18 * dpr}px "IBM Plex Mono", monospace`;
    ctx.fillStyle = '#8C97AB';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('NOW', x - 8 * dpr, top);
    ctx.restore();
  }
}

export class Trace {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ts = [];
    this.ys = [];
    this.scale = 200;
    this.resetFilter();
  }

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

  draw(tDisplay) {
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
    ctx.strokeStyle = 'rgba(140,151,171,0.14)';
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

    drawNowLine(ctx, xNow, 0, h, dpr, true);
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
    ctx.lineWidth = 2.5 * dpr;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowColor = 'rgba(67,224,160,0.35)';
    ctx.shadowBlur = 6 * dpr;
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
