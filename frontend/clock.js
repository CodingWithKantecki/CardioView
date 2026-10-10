// Viewer clock: plays a fixed delay behind the newest sample so bursts never show, and can leave
// the live edge to pause, scrub, or replay the last HISTORY_S forward or backward (the timeline).
// Everything on screen draws from displayTime(), so steering it steers the whole screen. Off live,
// the timeline's window freezes where it was (`anchor`), so the history holds still to look at;
// playing forward through newer data drags the window along, and reaching live goes live.
export const DELAY_S = 1.5;
export const HISTORY_S = 30;

export class StreamClock {
  constructor() { this.offset = null; this.mode = 'live'; this.t = null; this.wall = 0; this.anchor = null; }

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

  // the right edge of the timeline's window: live, or where it froze when the screen left live
  windowEnd() {
    const live = this.liveTime();
    if (live === null) return null;
    return this.mode === 'live' ? live : Math.max(this.anchor, this.t);
  }

  windowStart() {
    const end = this.windowEnd();
    return end === null ? null : end - HISTORY_S;
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
    if (this.t >= live) { this.mode = 'live'; this.t = live; this.anchor = live; return live; }   // a replay caught up
    if (this.t > this.anchor) this.anchor = this.t;
    const oldest = this.anchor - HISTORY_S;
    if (this.t <= oldest) { this.t = oldest; if (this.mode === 'backward') this.mode = 'paused'; }
    return this.t;
  }

  // leaving live: the window freezes at this moment and the playhead starts here
  _leaveLive() {
    if (this.mode === 'live' || this.t === null) { this.t = this.liveTime(); this.anchor = this.t; }
  }

  // 'live', 'paused', 'forward' or 'backward'
  setMode(mode) {
    if (this.liveTime() === null) return;
    if (mode !== 'live') this._leaveLive();
    this.wall = performance.now() / 1000;
    this.mode = mode;
  }

  // hold at stream time t, clamped to the frozen window
  seek(t) {
    const live = this.liveTime();
    if (live === null) return;
    this._leaveLive();
    this.t = Math.min(this.anchor, Math.max(this.anchor - HISTORY_S, t));
    this.wall = performance.now() / 1000;
    this.mode = this.t >= live ? 'live' : 'paused';
  }

  reset() { this.offset = null; this.mode = 'live'; this.t = null; this.anchor = null; }
}
