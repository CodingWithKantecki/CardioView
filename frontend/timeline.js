// The timeline in the header: the last HISTORY_S of ECG as a strip with a playhead. Drag the strip
// to scrub; the transport tray plays backward, pauses, plays forward or returns to live. It only
// steers the clock: the trace, the lanes, the heart and the number all follow displayTime().
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
    const live = this.clock.liveTime();
    if (live === null) return;
    const r = this.canvas.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    this.clock.seek(live - HISTORY_S + f * HISTORY_S);
  }

  draw(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const live = this.clock.liveTime();
    if (live === null || tDisplay === null) return;
    const T = colors();
    const t0 = live - HISTORY_S;
    const pxPerS = w / HISTORY_S;
    const xOf = (t) => (t - t0) * pxPerS;

    // the 6 s the instruments show
    ctx.fillStyle = alpha(T.now, 0.1);
    ctx.fillRect(xOf(tDisplay - WINDOW_S), 0, WINDOW_S * pxPerS, h);

    // beats as faint ticks along the bottom
    ctx.strokeStyle = alpha(T.rule, 0.2);
    ctx.lineWidth = 1 * dpr;
    for (const b of this.lanes.beats) {
      if (b.r < t0 || b.r > live) continue;
      const x = xOf(b.r);
      ctx.beginPath(); ctx.moveTo(x, h * 0.8); ctx.lineTo(x, h); ctx.stroke();
    }

    // the ECG, scaled like the trace
    const ts = this.trace.ts, ys = this.trace.ys;
    const base = h * 0.56;
    const amp = (h * 0.4) / Math.max(200, this.trace.scale);
    ctx.strokeStyle = alpha(T.trace, 0.8);
    ctx.lineWidth = 1 * dpr;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    let started = false;
    for (let i = this.trace.indexAt(t0); i < ts.length && ts[i] <= live; i++) {
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
