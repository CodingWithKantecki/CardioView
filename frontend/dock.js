// A dock at the bottom of the stage for the heart's view controls, in the manner of a macOS dock:
// cells grow toward the pointer with a spring, a label shows above the hovered one, and toggles
// show their state as pressed cells. Plain DOM; the R, W and C keys still work and stay in sync.
const BASE = 48;      // CSS px, a resting cell
const MAG = 78;       // the cell under the pointer
const REACH = 150;    // px of pointer distance over which the growth fades

export class Dock {
  constructor(el, actions) {
    this.el = el;
    this.items = [...el.querySelectorAll('button[data-action]')];
    this.size = this.items.map(() => BASE);
    this.vel = this.items.map(() => 0);
    this.shown = this.items.map(() => 0);
    this.pointerX = null;
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.addEventListener('pointermove', (e) => { if (e.pointerType === 'mouse') this.pointerX = e.clientX; });
    el.addEventListener('pointerleave', () => { this.pointerX = null; });
    for (const b of this.items) b.addEventListener('click', () => actions[b.dataset.action]?.());
  }

  // every frame: ease each cell toward its size for the pointer's position
  update() {
    for (let i = 0; i < this.items.length; i++) {
      const b = this.items[i];
      let target = BASE;
      if (this.pointerX !== null) {
        const r = b.getBoundingClientRect();
        const d = Math.abs(this.pointerX - (r.left + r.width / 2));
        target = BASE + (MAG - BASE) * Math.max(0, 1 - d / REACH);
      }
      if (this.reduced) this.size[i] = target;
      else {
        this.vel[i] = (this.vel[i] + (target - this.size[i]) * 0.28) * 0.58;
        this.size[i] += this.vel[i];
      }
      const s = Math.round(this.size[i] * 10) / 10;
      if (s !== this.shown[i]) { b.style.width = `${s}px`; b.style.height = `${s}px`; this.shown[i] = s; }
    }
  }

  setPressed(action, on) {
    const b = this.items.find((x) => x.dataset.action === action);
    if (b && b.getAttribute('aria-pressed') !== String(!!on)) b.setAttribute('aria-pressed', String(!!on));
  }
}
