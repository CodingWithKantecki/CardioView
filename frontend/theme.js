// Canvas colors come from CSS variables on :root, so a theme is a stylesheet swap.
// Each --c-* value must be a six-digit hex; alpha() derives the translucent variants.
const KEYS = ['stage', 'paper', 'ink', 'trace', 'grid', 'rule', 'dim', 'ra', 'rv', 'la', 'lv', 'alert', 'now'];
let cache = null;

export function colors() {
  if (cache) return cache;
  const cs = getComputedStyle(document.documentElement);
  cache = {};
  for (const k of KEYS) cache[k] = (cs.getPropertyValue('--c-' + k) || '').trim() || '#ff00ff';
  return cache;
}

export function invalidate() { cache = null; }

export function alpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function isLight() {
  const n = parseInt(colors().paper.slice(1), 16);
  const lum = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
  return lum > 128;
}
