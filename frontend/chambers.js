// Chamber lanes and activation, both pure functions of t_display and the recent beats.
import { fitCanvas, drawNowLine, WINDOW_S, NOW_FRAC, GUTTER } from './trace.js';

export const ATRIA_S = 0.12;
const RISE_S = 0.1;
const RELEASE_S = 0.2;
const ORDER = ['ra', 'la', 'rv', 'lv'];
const COLOR = { ra: '#5B9BFF', la: '#FF5C83', rv: '#5B9BFF', lv: '#FF5C83' };
const KEEP = 40;

export function intervals(beat) {
  const ra = beat.r + beat.ra_on;
  const la = beat.r + beat.la_on;
  const v = beat.r + beat.v_on;
  return {
    ra: [ra, ra + ATRIA_S],
    la: [la, la + ATRIA_S],
    rv: [v, beat.r + beat.v_off],
    lv: [v, beat.r + beat.v_off],
  };
}

function envelope(t, on, off) {
  if (t < on) return 0;
  if (t < on + RISE_S) return (t - on) / RISE_S;
  if (t <= off) return 1;
  if (t < off + RELEASE_S) return 1 - (t - off) / RELEASE_S;
  return 0;
}

export class Chambers {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.beats = [];
  }

  clear() { this.beats.length = 0; }

  push(beat) {
    const last = this.beats[this.beats.length - 1];
    if (last && beat.r < last.r - 1) this.beats.length = 0;   // stream restarted
    this.beats.push(beat);
    if (this.beats.length > KEEP) this.beats.splice(0, this.beats.length - KEEP);
  }

  latestBefore(t) {
    for (let i = this.beats.length - 1; i >= 0; i--) if (this.beats[i].r <= t) return this.beats[i];
    return null;
  }

  activation(t) {
    const out = { ra: 0, la: 0, rv: 0, lv: 0 };
    for (let i = this.beats.length - 1; i >= 0; i--) {
      const b = this.beats[i];
      if (b.r > t + 0.5) continue;
      if (b.r < t - 2) break;
      const iv = intervals(b);
      for (const c of ORDER) {
        const a = envelope(t, iv[c][0], iv[c][1]);
        if (a > out[c]) out[c] = a;
      }
    }
    return out;
  }

  draw(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const gutter = GUTTER * dpr;
    const drawable = w - gutter;
    const xNow = gutter + drawable * NOW_FRAC;
    const pxPerS = drawable / WINDOW_S;
    const tLeft = tDisplay === null ? 0 : tDisplay - WINDOW_S * NOW_FRAC;
    const rows = ORDER.length;
    const rowH = h / rows;
    const barH = Math.min(22 * dpr, rowH * 0.55);

    for (let r = 0; r < rows; r++) {
      const c = ORDER[r];
      const yMid = rowH * (r + 0.5);
      ctx.save();
      ctx.font = `${19 * dpr}px "IBM Plex Mono", monospace`;
      ctx.fillStyle = '#8C97AB';
      ctx.textBaseline = 'middle';
      ctx.fillText(c.toUpperCase(), 0, yMid);
      ctx.fillStyle = '#121B30';
      ctx.beginPath();
      ctx.roundRect(gutter, yMid - barH / 2, drawable, barH, 4 * dpr);
      ctx.fill();
      ctx.restore();
      if (tDisplay === null) continue;
      ctx.save();
      ctx.beginPath(); ctx.rect(gutter, 0, xNow - gutter, h); ctx.clip();
      ctx.fillStyle = COLOR[c];
      for (const b of this.beats) {
        const [on, off] = intervals(b)[c];
        if (off < tLeft || on > tDisplay) continue;
        const x0 = gutter + (on - tLeft) * pxPerS;
        const x1 = gutter + (Math.min(off, tDisplay) - tLeft) * pxPerS;
        ctx.beginPath();
        ctx.roundRect(x0, yMid - barH / 2, Math.max(x1 - x0, 3 * dpr), barH, 4 * dpr);
        ctx.fill();
      }
      ctx.restore();
    }
    drawNowLine(ctx, xNow, 0, h, dpr, false);
  }
}
