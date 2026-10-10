// The timeline in the header: the last HISTORY_S of ECG as a strip with a playhead, in one box with
// the transport tray. Drag the strip to scrub; the tray rewinds, plays, pauses, fast forwards or
// returns to live. It only steers the clock: the trace, the lanes, the heart and the number all
// follow displayTime(). Off live the strip's window is frozen (the clock's anchor).
import { fitCanvas, WINDOW_S } from './trace.js';
import { colors, alpha } from './theme.js';
import { HISTORY_S } from './clock.js';

const EDGE = 0.06;        // the strip's edge zone where a held drag scrolls the window
const PAN_RATE_S = 10;    // seconds of history per second while scrolling at an edge

export class Timeline {
  constructor(canvas, trace, lanes, clock) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.trace = trace;
    this.lanes = lanes;
    this.clock = clock;
    this.dragging = false;
    this.pointerF = 0;        // where the pointer is across the strip, 0 to 1 (beyond while dragging outside)
    this.lastFrame = 0;
    const at = (e) => { const r = canvas.getBoundingClientRect(); this.pointerF = (e.clientX - r.left) / r.width; };
    canvas.addEventListener('pointerdown', (e) => { canvas.setPointerCapture(e.pointerId); this.dragging = true; at(e); this.seekAt(); });
    canvas.addEventListener('pointermove', (e) => { if (this.dragging) { at(e); this.seekAt(); } });
    const up = () => { this.dragging = false; };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    // the wheel (a trackpad's two-finger scroll) pans the window and the playhead together
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = canvas.getBoundingClientRect();
      const px = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      this.clock.pan(px * (HISTORY_S / r.width));
    }, { passive: false });
  }

  // the playhead goes where the pointer is in the window
  seekAt() {
    const end = this.clock.windowEnd();
    if (end === null) return;
    const f = Math.min(1, Math.max(0, this.pointerF));
    this.clock.seek(end - HISTORY_S + f * HISTORY_S);
  }

  // a drag held at an edge (or beyond it) scrolls the window through the history
  scrollAtEdge() {
    const now = performance.now() / 1000;
    const dt = Math.min(0.1, now - this.lastFrame);
    this.lastFrame = now;
    if (!this.dragging) return;
    const f = this.pointerF;
    let pull = 0;
    if (f < EDGE) pull = -Math.min(1, (EDGE - f) / EDGE);
    else if (f > 1 - EDGE) pull = Math.min(1, (f - (1 - EDGE)) / EDGE);
    if (pull === 0) return;
    this.clock.pan(pull * PAN_RATE_S * dt);
    this.seekAt();
  }

  draw(tDisplay) {
    this.scrollAtEdge();
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
