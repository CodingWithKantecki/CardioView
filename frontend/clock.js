// Viewer clock: plays a fixed delay behind the newest sample so bursts never show, and can leave
// the live edge to pause, scrub, play, rewind or fast forward the last HISTORY_S (the timeline).
// Everything on screen draws from displayTime(), so steering it steers the whole screen. Off live,
// the timeline's window freezes where it was (`anchor`), so the history holds still to look at; a
// replay or a pan that leaves the window drags it along, back as far as the oldest kept sample
// (`oldest`, set by the viewer each frame), and reaching live goes live.
export const DELAY_S = 1.5;
export const HISTORY_S = 30;
export const RATES = { live: 1, paused: 0, play: 1, forward: 2, rewind: -2 };   // seconds per second in each mode

export class StreamClock {
  constructor() { this.offset = null; this.mode = 'live'; this.t = null; this.wall = 0; this.anchor = null; this.oldest = null; }

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
    this.t += (now - this.wall) * RATES[this.mode];
    this.wall = now;
    if (this.t >= live) { this.mode = 'live'; this.t = live; this.anchor = live; return live; }   // a replay caught up
    if (this.oldest !== null && this.t <= this.oldest) { this.t = this.oldest; if (this.mode === 'rewind') this.mode = 'paused'; }
    this._follow();
    return this.t;
  }

  // the window drags along when the playhead leaves it
  _follow() {
    if (this.t > this.anchor) this.anchor = this.t;
    if (this.t < this.anchor - HISTORY_S) this.anchor = this.t + HISTORY_S;
  }

  // move the window and the playhead together by ds seconds (dragging the clip, or the wheel)
  pan(ds) {
    const live = this.liveTime();
    if (live === null) return;
    this._leaveLive();
    const end = Math.max(this.anchor, this.t);
    const floorEnd = this.oldest === null ? -Infinity : this.oldest + HISTORY_S;
    const target = Math.min(live, Math.max(Math.min(floorEnd, end), end + ds));
    const shift = target - end;
    this.anchor = target;
    this.t = Math.min(live, Math.max(this.oldest === null ? -Infinity : this.oldest, this.t + shift));
    this.wall = performance.now() / 1000;
    if (this.mode === 'live') this.mode = 'paused';
  }

  // leaving live: the window freezes at this moment and the playhead starts here
  _leaveLive() {
    if (this.mode === 'live' || this.t === null) { this.t = this.liveTime(); this.anchor = this.t; }
  }

  // 'live', 'paused', 'play', 'forward' (2x) or 'rewind' (2x back)
  setMode(mode) {
    if (this.liveTime() === null || !(mode in RATES)) return;
    if (mode !== 'live') this._leaveLive();
    this.wall = performance.now() / 1000;
    this.mode = mode;
  }

  // hold at stream time t, clamped to the frozen window
  seek(t) {
    const live = this.liveTime();
    if (live === null) return;
    this._leaveLive();
    const floor = this.oldest === null ? this.anchor - HISTORY_S : Math.max(this.oldest, this.anchor - HISTORY_S);
    this.t = Math.min(this.anchor, Math.max(floor, t));
    this.wall = performance.now() / 1000;
    this.mode = this.t >= live ? 'live' : 'paused';
  }

  reset() { this.offset = null; this.mode = 'live'; this.t = null; this.anchor = null; this.oldest = null; }
}
