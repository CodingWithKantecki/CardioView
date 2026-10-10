// Viewer clock: plays a fixed delay behind the newest sample so bursts never show.
export const DELAY_S = 1.5;

export class StreamClock {
  constructor() { this.offset = null; }

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

  displayTime() {
    if (this.offset === null) return null;
    return performance.now() / 1000 + this.offset - DELAY_S;
  }

  reset() { this.offset = null; }
}
