// Closest demo pattern (experimental): the server reads the last 10 s every 5 s with a classifier
// trained only on the demo's simulated rhythms (backend/pattern.py). Each reading carries the stream
// time its window ends at, and the label shows the reading for the time on screen, so it follows
// the display clock like the trace (a replay shows what was read then). No readings, no label: the
// server has no classifier (the public copy) or it is still loading.

const KEEP = 240;      // readings kept, 20 minutes at one every 5 s: more than the replay history
const STALE_S = 12;    // a reading this much older than the screen is no longer about it

export class PatternLabel {
  constructor(el) {
    this.el = el;
    this.value = el.querySelector('.pattern-value');
    this.readings = [];
    this.shown = undefined;
  }

  push(msg) {
    if (typeof msg.t !== 'number') return;
    const r = this.readings;
    while (r.length && r[r.length - 1].t > msg.t) r.pop();   // the stream started over
    r.push(msg);
    if (r.length > KEEP) r.splice(0, r.length - KEEP);
  }

  text(t) {
    if (!this.readings.length) return null;
    let cur = null;
    if (t !== null) {
      for (let i = this.readings.length - 1; i >= 0; i--) {
        if (this.readings[i].t <= t) { cur = this.readings[i]; break; }
      }
    }
    if (!cur || cur.name == null || t - cur.t > STALE_S) return 'Reading';
    if (cur.name === 'unsure') return 'Unsure';
    if (cur.name === 'none') return cur.label || 'No match';
    return `${cur.label} ${Math.round(cur.p * 100)}%`;
  }

  draw(t) {
    const text = this.text(t);
    if (text === this.shown) return;
    this.shown = text;
    this.el.hidden = text === null;
    if (text !== null) {
      this.value.textContent = text;
      this.el.classList.toggle('waiting', text === 'Reading' || text === 'Unsure');
    }
  }
}
