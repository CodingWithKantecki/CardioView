import { isLight } from './theme.js';

// Lost-signal look for the stage: the WebGL frame copied through a red pass with bands torn
// sideways, TV static over everything, and the occasional flash. Drawn only while lost.
const RED = 'grayscale(1) sepia(1) saturate(6) hue-rotate(-64deg) contrast(1.35) brightness(0.66)';

function noiseTile(size) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  const img = ctx.createImageData(size, size);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const v = 90 + Math.random() * 165;
    d[i] = v; d[i + 1] = v * 0.55; d[i + 2] = v * 0.6; d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

export class Glitch {
  constructor(canvas, source) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.source = source;
    this.tile = noiseTile(256);
    this.bands = [];
    this.nextBands = 0;
    this.flashUntil = 0;
  }

  draw(now) {
    const src = this.source;
    const w = src.width, h = src.height;
    if (!w || !h) return;
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);

    // the heart, red
    ctx.filter = RED;
    ctx.drawImage(src, 0, 0);

    // bands torn sideways, re-rolled every 60 to 240 ms
    if (now > this.nextBands) {
      const n = 2 + Math.floor(Math.random() * 4);
      this.bands = [];
      for (let i = 0; i < n; i++) {
        this.bands.push({ y: Math.random() * h, hgt: (4 + Math.random() * 40) * (w / 1200), dx: (Math.random() - 0.5) * w * 0.06, bright: Math.random() < 0.4 });
      }
      this.nextBands = now + 60 + Math.random() * 180;
      // at most two flashes a second, under the three-per-second photosensitivity line
      if (Math.random() < 0.12 && now > this.flashUntil + 500) this.flashUntil = now + 40 + Math.random() * 60;
    }
    for (const b of this.bands) {
      ctx.filter = b.bright ? RED + ' brightness(1.9)' : RED;
      ctx.drawImage(src, 0, b.y, w, b.hgt, b.dx, b.y, w, b.hgt);
    }
    ctx.filter = 'none';

    // static over the whole stage
    const pattern = ctx.createPattern(this.tile, 'repeat');
    pattern.setTransform(new DOMMatrix().translate(Math.random() * 256, Math.random() * 256));
    const blend = isLight() ? 'multiply' : 'screen';   // static darkens a light theme, lightens a dark one
    ctx.save();
    ctx.globalCompositeOperation = blend;
    ctx.globalAlpha = now < this.flashUntil ? 0.5 : 0.2;
    ctx.fillStyle = pattern;
    ctx.fillRect(0, 0, w, h);
    ctx.restore();

    // red wash and a flash
    ctx.save();
    ctx.globalCompositeOperation = blend;
    ctx.fillStyle = now < this.flashUntil ? 'rgba(229,52,78,0.22)' : 'rgba(229,52,78,0.08)';
    ctx.fillRect(0, 0, w, h);
    ctx.restore();
  }
}
