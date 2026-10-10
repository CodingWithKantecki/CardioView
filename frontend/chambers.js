// Chamber lanes and activation, both pure functions of t_display and the recent beats.
import { fitCanvas, WINDOW_S, NOW_INSET, geometry, keepCut } from './trace.js';
import { colors, alpha } from './theme.js';

export const ATRIA_S = 0.12;
const RISE_S = 0.1;
const RELEASE_S = 0.2;
export const ORDER = ['ra', 'la', 'rv', 'lv'];
const laneColor = (c) => colors()[c];   // one color per chamber, from the --c-ra/rv/la/lv tokens
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
    this.mode = '2d';
    this.holdFrom = null;   // set by the timeline while off live: keep beats from here
  }

  setMode(mode) { this.mode = mode === '3d' ? '3d' : '2d'; }

  clear() { this.beats.length = 0; }

  push(beat) {
    const last = this.beats[this.beats.length - 1];
    if (last && beat.r < last.r - 1) this.beats.length = 0;   // stream restarted
    this.beats.push(beat);
    const cut = keepCut(beat.r, this.holdFrom);
    let drop = 0;
    while (drop < this.beats.length && this.beats[drop].r < cut) drop++;
    if (drop > 0) this.beats.splice(0, drop);
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
    ctx.strokeStyle = alpha(colors().grid, 0.3);
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
      ctx.fillStyle = alpha(laneColor(c), 0.1);
      ctx.fill();
      ctx.beginPath();
      for (let x = 0; x < w; x++) {
        const t = tDisplay - ((w - 1 - x) / (w - 1)) * SPARK_S;
        const a = this.waveOf(c, t);
        const y = base - a * (base - top);
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = laneColor(c);
      ctx.lineWidth = 1.25 * dpr;
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
    ctx.restore();
  }

  // Lanes in perspective: the four chambers as ridges receding from LV in front to RA at the
  // back (the 2D order read bottom to top), each the same 6 s window with its now at the right
  // end, so the atria's lead over the ventricles shows as a step between ridges.
  draw3d(tDisplay) {
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const T = colors();
    const n = ORDER.length;
    const left = 46 * dpr;                   // room for the letter at the front ridge's start
    const right = w - NOW_INSET * dpr;
    const stepX = w * 0.045;                 // each ridge further back starts further right
    const stepY = h * 0.19;                  // and sits higher
    const base0 = h * 0.88;
    const amp0 = h * 0.21;                   // a ridge's peak just reaches the baseline behind it
    const step = Math.max(1, Math.round(dpr));
    const tLeft = tDisplay === null ? 0 : tDisplay - WINDOW_S;
    const letters = [];
    for (let i = 0; i < n; i++) {            // back to front: RA, LA, RV, LV
      const c = ORDER[i];
      const depth = n - 1 - i;
      const sc = 1 - 0.06 * depth;
      const x0 = left + depth * stepX;
      const xEnd = x0 + (right - left) * sc;
      const base = base0 - depth * stepY;
      const amp = amp0 * sc;
      const pxPerS = (xEnd - x0) / WINDOW_S;
      const col = laneColor(c);
      const pts = [];
      if (tDisplay !== null) {
        for (let x = x0; x <= xEnd; x += step) pts.push([x, base - this.activationOf(c, tLeft + (x - x0) / pxPerS) * amp]);
        pts.push([xEnd, base - this.activationOf(c, tDisplay) * amp]);
      }
      ctx.save();
      if (pts.length) {
        // the ridge knocks out what is behind it, then takes its color, brighter toward now
        ctx.beginPath();
        ctx.moveTo(x0, base);
        for (const [x, y] of pts) ctx.lineTo(x, y);
        ctx.lineTo(xEnd, base);
        ctx.closePath();
        ctx.fillStyle = alpha(T.paper, 0.96);
        ctx.fill();
        const fill = ctx.createLinearGradient(x0, 0, xEnd, 0);
        fill.addColorStop(0, alpha(col, 0.12));
        fill.addColorStop(1, alpha(col, 0.5));
        ctx.fillStyle = fill;
        ctx.fill();
      }
      ctx.strokeStyle = alpha(T.rule, 0.22);
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath(); ctx.moveTo(x0, base); ctx.lineTo(xEnd, base); ctx.stroke();
      if (pts.length) {
        const line = ctx.createLinearGradient(x0, 0, xEnd, 0);
        line.addColorStop(0, alpha(col, 0.3));
        line.addColorStop(1, col);
        ctx.beginPath();
        for (let k = 0; k < pts.length; k++) { if (k === 0) ctx.moveTo(pts[k][0], pts[k][1]); else ctx.lineTo(pts[k][0], pts[k][1]); }
        ctx.strokeStyle = line;
        ctx.lineWidth = 1.5 * dpr;
        ctx.lineJoin = 'round';
        ctx.stroke();
        const [lx, ly] = pts[pts.length - 1];   // pen dot at the leading edge
        ctx.fillStyle = col;
        ctx.shadowColor = col;
        ctx.shadowBlur = 8 * dpr;
        ctx.beginPath(); ctx.arc(lx, ly, 3 * dpr, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      }
      ctx.restore();
      letters.push([c, col, x0, base]);
    }
    // the chamber letters at each ridge's start, in their colors, on top of every ridge
    ctx.save();
    ctx.font = `700 ${14 * dpr}px "Helvetica Neue", Helvetica, Arial, sans-serif`;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'alphabetic';
    for (const [c, col, x0, base] of letters) {
      const label = c.toUpperCase();
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = alpha(T.paper, 0.85);
      ctx.fillRect(x0 - 12 * dpr - tw, base - 15 * dpr, tw + 8 * dpr, 18 * dpr);
      ctx.fillStyle = alpha(col, 0.95);
      ctx.fillText(label, x0 - 8 * dpr, base - 2 * dpr);
    }
    ctx.restore();
  }

  // Lanes: each chamber's activation curve over the 6 s window, brighter toward now, a faint
  // tick on every beat across all lanes, and a pen dot at the leading edge.
  draw(tDisplay) {
    if (this.mode === '3d') { this.draw3d(tDisplay); return; }
    const { w, h, dpr } = fitCanvas(this.canvas);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    const { gutter, xNow, pxPerS } = geometry(w, dpr);
    const tLeft = tDisplay === null ? 0 : tDisplay - WINDOW_S;
    const rows = ORDER.length;
    const rowH = h / rows;
    const pad = rowH * 0.12;
    const step = Math.max(1, Math.round(dpr));

    const T = colors();
    if (tDisplay !== null) {
      ctx.save();
      ctx.strokeStyle = alpha(T.rule, 0.1);
      ctx.lineWidth = 1 * dpr;
      for (const b of this.beats) {
        if (b.r < tLeft || b.r > tDisplay) continue;
        const x = gutter + (b.r - tLeft) * pxPerS;
        ctx.beginPath(); ctx.moveTo(x, pad); ctx.lineTo(x, h - pad); ctx.stroke();
      }
      ctx.restore();
    }

    for (let r = 0; r < rows; r++) {
      const c = ORDER[r];
      const base = rowH * (r + 1) - pad;
      const top = rowH * r + pad;
      const amp = base - top;
      ctx.save();
      ctx.strokeStyle = alpha(T.rule, 0.22);
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath(); ctx.moveTo(gutter, base); ctx.lineTo(w, base); ctx.stroke();
      ctx.restore();
      if (tDisplay === null) continue;

      const col = laneColor(c);
      const fill = ctx.createLinearGradient(gutter, 0, xNow, 0);
      fill.addColorStop(0, alpha(col, 0.12));
      fill.addColorStop(1, alpha(col, 0.55));
      const line = ctx.createLinearGradient(gutter, 0, xNow, 0);
      line.addColorStop(0, alpha(col, 0.3));
      line.addColorStop(1, col);

      ctx.save();
      ctx.beginPath(); ctx.rect(gutter, 0, xNow - gutter, h); ctx.clip();
      ctx.beginPath();
      ctx.moveTo(gutter, base);
      let last = 0;
      for (let x = gutter; x <= xNow; x += step) {
        last = this.activationOf(c, tLeft + (x - gutter) / pxPerS);
        ctx.lineTo(x, base - last * amp);
      }
      ctx.lineTo(xNow, base);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.beginPath();
      for (let x = gutter; x <= xNow; x += step) {
        const y = base - this.activationOf(c, tLeft + (x - gutter) / pxPerS) * amp;
        if (x === gutter) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = line;
      ctx.lineWidth = 1.5 * dpr;
      ctx.lineJoin = 'round';
      ctx.stroke();
      ctx.restore();

      // pen dot at the leading edge
      ctx.save();
      ctx.fillStyle = col;
      ctx.shadowColor = col;
      ctx.shadowBlur = 8 * dpr;
      ctx.beginPath();
      ctx.arc(xNow, base - last * amp, 3 * dpr, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // the chamber letters inside each lane's top-left corner, in the same bold Helvetica as the
    // labels on the heart, on a knock-out so the shapes pass under them
    ctx.save();
    ctx.font = `700 ${15 * dpr}px "Helvetica Neue", Helvetica, Arial, sans-serif`;
    ctx.textBaseline = 'top';
    for (let r = 0; r < rows; r++) {
      const label = ORDER[r].toUpperCase();
      const tw = ctx.measureText(label).width;
      const lx = 12 * dpr, ly = rowH * r + pad + 1 * dpr;
      ctx.fillStyle = alpha(T.paper, 0.85);
      ctx.fillRect(lx - 5 * dpr, ly - 3 * dpr, tw + 10 * dpr, 21 * dpr);
      ctx.fillStyle = alpha(T.ink, 0.85);
      ctx.fillText(label, lx, ly);
    }
    ctx.restore();
  }
}
