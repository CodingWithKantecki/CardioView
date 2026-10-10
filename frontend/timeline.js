// The timeline in the header: the last HISTORY_S of ECG as a strip with a playhead, in one box with
// the transport tray. Drag the strip to scrub; the tray plays backward, pauses, plays forward or
// returns to live. It only steers the clock: the trace, the lanes, the heart and the number all
// follow displayTime(). Off live the strip's window is frozen (the clock's anchor).
import { fitCanvas, WINDOW_S } from './trace.js';
import { colors, alpha } from './theme.js';
import { HISTORY_S } from './clock.js';

export class Timeline {
  constructor(canvas, trace, lanes, clock) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.trace = trace;
    this.lanes = lanes;
    this.clock = clock;
    this.dragging = false;
    canvas.addEventListener('pointerdown', (e) => { canvas.setPointerCapture(e.pointerId); this.dragging = true; this.seekAt(e); });
    canvas.addEventListener('pointermove', (e) => { if (this.dragging) this.seekAt(e); });
    const up = () => { this.dragging = false; };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
  }

  seekAt(e) {
    const end = this.clock.windowEnd();
    if (end === null) return;
    const r = this.canvas.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    this.clock.seek(end - HISTORY_S + f * HISTORY_S);
  }

  draw(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const live = this.clock.liveTime();
    const end = this.clock.windowEnd();
    if (live === null || end === null || tDisplay === null) return;
    const T = colors();
    const t0 = end - HISTORY_S;
    const pxPerS = w / HISTORY_S;
    const xOf = (t) => (t - t0) * pxPerS;

    // the 6 s the instruments show
    ctx.fillStyle = alpha(T.now, 0.1);
    ctx.fillRect(xOf(tDisplay - WINDOW_S), 0, WINDOW_S * pxPerS, h);

    // a time grid: a line every second, stronger with a label every 5 s
    ctx.lineWidth = 1 * dpr;
    ctx.font = `600 ${10 * dpr}px "JetBrains Mono", monospace`;
    ctx.textBaseline = 'bottom';
    for (let k = 1; k < HISTORY_S; k++) {
      const x = Math.round(xOf(end - k)) + 0.5;
      ctx.strokeStyle = alpha(T.rule, k % 5 === 0 ? 0.32 : 0.1);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      if (k % 5 === 0) { ctx.fillStyle = alpha(T.dim, 0.9); ctx.fillText(`-${k} S`, x + 4 * dpr, h - 3 * dpr); }
    }

    // a flat line where there is no signal yet: before the first kept sample, and after the newest
    const ts = this.trace.ts, ys = this.trace.ys;
    const base = h * 0.52;
    const amp = (h * 0.4) / Math.max(200, this.trace.scale);
    const i0 = this.trace.indexAt(t0);
    const firstT = i0 < ts.length ? ts[i0] : null;
    const lastT = ts.length ? ts[ts.length - 1] : null;
    ctx.strokeStyle = alpha(T.trace, 0.45);
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath();
    if (firstT === null || firstT > end) { ctx.moveTo(0, base); ctx.lineTo(w, base); }
    else {
      if (firstT > t0) { ctx.moveTo(0, base); ctx.lineTo(xOf(firstT), base); }
      if (lastT < end) { ctx.moveTo(xOf(lastT), base); ctx.lineTo(w, base); }
    }
    ctx.stroke();

    // the ECG, scaled like the trace
    ctx.strokeStyle = alpha(T.trace, 0.8);
    ctx.lineWidth = 1 * dpr;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    let started = false;
    for (let i = i0; i < ts.length && ts[i] <= end; i++) {
      const x = xOf(ts[i]), y = base - ys[i] * amp;
      if (started) ctx.lineTo(x, y); else { ctx.moveTo(x, y); started = true; }
    }
    ctx.stroke();

    // the playhead, with how far behind live it sits
    const x = xOf(tDisplay);
    ctx.strokeStyle = T.now;
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    if (this.clock.mode !== 'live') {
      const label = `-${(live - tDisplay).toFixed(1)} S`;
      ctx.font = `600 ${11 * dpr}px "JetBrains Mono", monospace`;
      ctx.textBaseline = 'top';
      const tw = ctx.measureText(label).width;
      const lx = x + 6 * dpr + tw > w ? x - 6 * dpr - tw : x + 6 * dpr;
      ctx.fillStyle = T.now;
      ctx.fillText(label, lx, 3 * dpr);
    }
  }
}
