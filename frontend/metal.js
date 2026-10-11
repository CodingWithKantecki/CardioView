// Liquid metal between the cells (Thomas, 2026-10-10 evening, from 21st.dev's Liquid Metal Button):
// every tray's rules and frame are a Paper Shaders liquid-metal surface under its cells, one WebGL
// mount per tray, so the chrome shows only through the gaps. It idles slowly, runs on hover and
// flashes on a click; under prefers-reduced-motion it holds still. Without WebGL2 the trays keep
// their plain rules. The Gemini frames keep their own gradient.
import { ShaderMount } from './vendor/paper-shaders/shader-mount.js';
import { liquidMetalFragmentShader, LiquidMetalShapes } from './vendor/paper-shaders/shaders/liquid-metal.js';

const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const IDLE = 0.5;
const HOVER = 1.1;
const CLICK = 2.4;
// the Liquid Metal Button's own settings, the whole surface instead of a pill (shape none)
const UNIFORMS = {
  u_scale: 8, u_offsetX: 0.1, u_offsetY: -0.1,
  u_repetition: 4, u_softness: 0.5, u_shiftRed: 0.3, u_shiftBlue: 0.3,
  u_distortion: 0, u_contour: 0, u_angle: 45, u_shape: LiquidMetalShapes.none,
};
const TRAYS = ['#transport', '#source-mode', '#rhythm-tray', '#strap-tray', '#exercise .exercise-tray', '#export-menu', '#dock'];

export function initMetal() {
  const probe = document.createElement('canvas');
  if (!probe.getContext('webgl2')) return [];
  const mounts = [];
  for (const sel of TRAYS) {
    const el = document.querySelector(sel);
    if (!el) continue;
    let mount;
    try {
      mount = new ShaderMount(el, liquidMetalFragmentShader, UNIFORMS, undefined, REDUCED ? 0 : IDLE);
    } catch (e) {
      console.warn('metal:', e?.message || e);
      continue;
    }
    el.classList.add('metal');
    mounts.push(mount);
    if (REDUCED) continue;
    let back = null;
    el.addEventListener('mouseenter', () => mount.setSpeed(HOVER));
    el.addEventListener('mouseleave', () => mount.setSpeed(IDLE));
    el.addEventListener('click', () => {
      mount.setSpeed(CLICK);
      clearTimeout(back);
      back = setTimeout(() => mount.setSpeed(el.matches(':hover') ? HOVER : IDLE), 300);
    });
  }
  return mounts;
}
