// Viewer clock: plays a fixed delay behind the newest sample so bursts never show, and can leave
// the live edge to pause, scrub, or replay the last HISTORY_S forward or backward (the timeline).
// Everything on screen draws from displayTime(), so steering it steers the whole screen.
export const DELAY_S = 1.5;
export const HISTORY_S = 30;

export class StreamClock {
  constructor() { this.offset = null; this.mode = 'live'; this.t = null; this.wall = 0; }

  // tNewest: stream time of the newest sample just received.
  update(tNewest) {
    const candidate = tNewest - performance.now() / 1000;
    if (this.offset === null || Math.abs(candidate - this.offset) > 1) {
      this.offset = candidate;              // first message, or a restart
    } else if (candidate > this.offset) {
      this.offset = candidate;              // move up at once
    } else {
      this.offset += (candidate - this.offset) * 0.05;   // drift down slowly
    }
  }

  // the stream time the live edge shows
  liveTime() {
    if (this.offset === null) return null;
    return performance.now() / 1000 + this.offset - DELAY_S;
  }

  // the stream time the screen shows this frame; call it once per frame, a replay advances in it
  displayTime() {
    const live = this.liveTime();
    if (live === null) return null;
    if (this.mode === 'live') return live;
    const now = performance.now() / 1000;
    if (this.mode === 'forward') this.t += now - this.wall;
    else if (this.mode === 'backward') this.t -= now - this.wall;
    this.wall = now;
    if (this.t >= live) { this.mode = 'live'; this.t = live; return live; }   // a replay caught up
    const oldest = live - HISTORY_S;
    if (this.t <= oldest) { this.t = oldest; if (this.mode === 'backward') this.mode = 'paused'; }
    return this.t;
  }

  // 'live', 'paused', 'forward' or 'backward'; leaving live starts from the moment on screen
  setMode(mode) {
    const live = this.liveTime();
    if (live === null) return;
    if (this.t === null || this.mode === 'live') this.t = live;
    this.wall = performance.now() / 1000;
    this.mode = mode;
  }

  // hold at stream time t, clamped to what is kept
  seek(t) {
    const live = this.liveTime();
    if (live === null) return;
    this.t = Math.min(live, Math.max(live - HISTORY_S, t));
    this.wall = performance.now() / 1000;
    this.mode = this.t >= live ? 'live' : 'paused';
  }

  reset() { this.offset = null; this.mode = 'live'; this.t = null; }
}
