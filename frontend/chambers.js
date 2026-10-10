// Chamber lanes and activation, both pure functions of t_display and the recent beats.
import { fitCanvas, WINDOW_S, NOW_FRAC, GUTTER } from './trace.js';

export const ATRIA_S = 0.12;
const RISE_S = 0.1;
const RELEASE_S = 0.2;
export const ORDER = ['ra', 'la', 'rv', 'lv'];
const COLOR = { ra: '#5B9BFF', la: '#FF5C83', rv: '#5B9BFF', lv: '#FF5C83' };
const KEEP = 40;
const SPARK_S = 3;

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

// raised-cosine bump centered on `center`, zero beyond `half` seconds either side
function bump(t, center, half) {
  const x = (t - center) / half;
  return x > -1 && x < 1 ? 0.5 + 0.5 * Math.cos(Math.PI * x) : 0;
}

function smooth(a, b, t) {
  const x = Math.min(1, Math.max(0, (t - a) / (b - a)));
  return x * x * (3 - 2 * x);
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

  // activation of one chamber at time t, 0 to 1
  activationOf(c, t) {
    let out = 0;
    for (let i = this.beats.length - 1; i >= 0; i--) {
      const b = this.beats[i];
      if (b.r > t + 0.5) continue;
      if (b.r < t - 2) break;
      const [on, off] = intervals(b)[c];
      const a = envelope(t, on, off);
      if (a > out) out = a;
    }
    return out;
  }

  activation(t) {
    return { ra: this.activationOf('ra', t), la: this.activationOf('la', t), rv: this.activationOf('rv', t), lv: this.activationOf('lv', t) };
  }

  // Modeled pressure-style wave for one chamber, from the beat timing alone (not a measurement).
  // Atria: a bump at atrial contraction, then a slow rise while the ventricles squeeze and the atria fill.
  // Ventricles: a dome from ventricles on to off, the left one tall, the right one low, plus a small
  // end-diastolic bump from the atrial kick.
  waveOf(c, t) {
    let out = 0;
    for (let i = this.beats.length - 1; i >= 0; i--) {
      const b = this.beats[i];
      if (b.r > t + 0.5) continue;
      if (b.r < t - 2) break;
      const aOn = b.r + (c === 'la' || c === 'lv' ? b.la_on : b.ra_on);
      const vOn = b.r + b.v_on;
      const vOff = b.r + b.v_off;
      let v;
      if (c === 'ra' || c === 'la') {
        v = bump(t, aOn + 0.07, 0.09) + 0.55 * bump(t, vOff + 0.02, 0.24);
      } else {
        const up = smooth(vOn, vOn + 0.1, t);
        const down = 1 - smooth(vOff - 0.05, vOff + 0.08, t);
        v = (c === 'lv' ? 1.0 : 0.5) * up * down + 0.12 * bump(t, aOn + 0.08, 0.08);
      }
      if (v > out) out = v;
    }
    return Math.min(1, out);
  }

  // small wave of one chamber over the last SPARK_S seconds, newest at the right edge
  drawSpark(canvas, c, tDisplay) {
    const { w, h, dpr } = fitCanvas(canvas);
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, w, h);
    const base = h - 1.5 * dpr;
    const top = 2 * dpr;
    ctx.save();
    ctx.strokeStyle = 'rgba(140,151,171,0.25)';
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath(); ctx.moveTo(0, base); ctx.lineTo(w, base); ctx.stroke();
    if (tDisplay !== null) {
      ctx.beginPath();
      ctx.moveTo(0, base);
      for (let x = 0; x < w; x++) {
        const t = tDisplay - ((w - 1 - x) / (w - 1)) * SPARK_S;
        const a = this.waveOf(c, t);
        ctx.lineTo(x, base - a * (base - top));
      }
      ctx.lineTo(w - 1, base);
      ctx.closePath();
      ctx.fillStyle = COLOR[c] + '1A';
      ctx.fill();
      ctx.beginPath();
      for (let x = 0; x < w; x++) {
        const t = tDisplay - ((w - 1 - x) / (w - 1)) * SPARK_S;
        const a = this.waveOf(c, t);
        const y = base - a * (base - top);
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = COLOR[c];
      ctx.lineWidth = 1.25 * dpr;
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
    ctx.restore();
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
    const barH = Math.min(12 * dpr, rowH * 0.5);

    for (let r = 0; r < rows; r++) {
      const c = ORDER[r];
      const yMid = rowH * (r + 0.5);
      ctx.save();
      ctx.font = `${14 * dpr}px "IBM Plex Sans", sans-serif`;
      ctx.fillStyle = '#7F8AA0';
      ctx.textBaseline = 'middle';
      ctx.fillText(c.toUpperCase(), 0, yMid);
      ctx.fillStyle = 'rgba(232,236,243,0.06)';
      ctx.beginPath();
      ctx.roundRect(gutter, yMid - barH / 2, drawable, barH, barH / 2);
      ctx.fill();
      ctx.restore();
      if (tDisplay === null) continue;
      ctx.save();
      ctx.beginPath(); ctx.rect(gutter, 0, xNow - gutter, h); ctx.clip();
      ctx.fillStyle = COLOR[c] + 'D9';
      for (const b of this.beats) {
        const [on, off] = intervals(b)[c];
        if (off < tLeft || on > tDisplay) continue;
        const x0 = gutter + (on - tLeft) * pxPerS;
        const x1 = gutter + (Math.min(off, tDisplay) - tLeft) * pxPerS;
        ctx.beginPath();
        ctx.roundRect(x0, yMid - barH / 2, Math.max(x1 - x0, 3 * dpr), barH, barH / 2);
        ctx.fill();
      }
      ctx.restore();
    }
  }
}
