// Saved visitor sessions on the stage: the operator's keys, the step prompt and countdown,
// the breathing ring and the voice. The server owns the session; this only shows it.

const PROMPT = {
  get_ready: 'Hold still while the signal settles',
  rest: 'Sit still and breathe normally',
  squats: 'Squats, keep going',
  recover: 'Stand still and catch your breath',
};
const NOTE = {
  stopped: 'Session stopped and deleted',
  write_failed: 'Could not save the session, nothing was kept',
};
const ARM_MS = 5000;        // a second S or Esc must come within this
const FLASH_MS = 4000;
const BREATH_S = 10;        // 5 s in, 5 s out: 6 breaths a minute
const VOICE_KEY = 'cardioview.voice';
const MIN_DONE_MS = 2600;   // let "All done" finish before the summary opens

function readVoice() {
  try { return localStorage.getItem(VOICE_KEY) !== 'off'; } catch { return true; }
}

function writeVoice(on) {
  try { localStorage.setItem(VOICE_KEY, on ? 'on' : 'off'); } catch { /* private window */ }
}

export class SessionOverlay {
  constructor({ box, prompt, sub, ring }, { reducedMotion = false } = {}) {
    this.box = box;
    this.prompt = prompt;
    this.sub = sub;
    this.ring = ring;
    this.reducedMotion = reducedMotion;
    this.msg = { state: 'idle' };
    this.at = 0;              // performance.now() when msg arrived
    this.armedS = 0;
    this.armedEsc = 0;
    this.flashText = '';
    this.flashUntil = 0;
    this.voiceOn = readVoice();
    this.clips = {};
    this.lastIndex = -1;
    this.lastBreath = '';
    this.analyzingAt = 0;
  }

  // a session is recording or being measured: the source and rhythm switches wait until it stops
  busy() {
    return this.msg.state === 'running' || this.msg.state === 'analyzing';
  }

  handle(msg) {
    const prev = this.msg;
    this.msg = msg;
    this.at = performance.now();
    if (msg.state === 'running' && msg.index !== this.lastIndex) {
      this.lastIndex = msg.index;
      this.lastBreath = '';
      this.say(msg.step);
    }
    if (msg.state === 'analyzing' && prev.state !== 'analyzing') {
      this.analyzingAt = performance.now();
      this.say('done');
    }
    if (msg.state === 'idle') {
      this.lastIndex = -1;
      if (msg.note && prev.state !== 'idle') {
        this.flash(NOTE[msg.note] || 'Session ended');
        if (msg.note === 'stopped') this.say('stopped');
      }
    }
    if (msg.state === 'done') {
      const wait = this.analyzingAt ? Math.max(0, MIN_DONE_MS - (performance.now() - this.analyzingAt)) : 0;
      setTimeout(() => location.assign(`/s/${encodeURIComponent(msg.id)}?screen=1`), wait);
    }
  }

  // true when the key belonged to the session controls
  key(e) {
    const k = e.key;
    const now = performance.now();
    const busy = this.busy();
    if (k === 's' || k === 'S') {
      if (busy) { this.flash('A session is already running'); return true; }
      if (now - this.armedS < ARM_MS) {
        this.armedS = 0;
        this.post('/api/session/start');
      } else {
        this.armedS = now;
      }
      return true;
    }
    if (k === 'Escape') {
      if (this.armedS) { this.armedS = 0; return true; }
      if (!busy) return false;
      if (now - this.armedEsc < ARM_MS) {
        this.armedEsc = 0;
        this.post('/api/session/cancel');
      } else {
        this.armedEsc = now;
      }
      return true;
    }
    if (k === 'v' || k === 'V') {
      this.voiceOn = !this.voiceOn;
      writeVoice(this.voiceOn);
      this.flash(this.voiceOn ? 'Voice on' : 'Voice off');
      return true;
    }
    return false;
  }

  async post(path) {
    try {
      const res = await fetch(path, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        this.flash(body.reason || 'The server said no');
      }
    } catch {
      this.flash('Server offline');
    }
  }

  flash(text) {
    this.flashText = text;
    this.flashUntil = performance.now() + FLASH_MS;
  }

  say(key) {
    if (!this.voiceOn || !key) return;
    let clip = this.clips[key];
    if (!clip) {
      clip = new Audio(`assets/voice/${key}.wav`);
      this.clips[key] = clip;
    }
    clip.currentTime = 0;
    clip.play().catch(() => { /* no file yet, or no user gesture in this tab */ });
  }

  // the step clock between messages: it runs on while samples arrive and stops when paused
  elapsed(now) {
    const m = this.msg;
    if (m.state !== 'running') return 0;
    const extra = m.paused ? 0 : (now - this.at) / 1000;
    return Math.min(m.length_s, m.elapsed_s + extra);
  }

  frame(now) {
    const m = this.msg;
    let prompt = '';
    let sub = '';
    let ring = null;   // scale 0.7 to 1, or null to hide
    if (m.state === 'running') {
      const t = this.elapsed(now);
      if (m.step === 'breathe') {
        const phase = t % BREATH_S;
        const inhale = phase < BREATH_S / 2;
        const breath = inhale ? 'in' : 'out';
        if (breath !== this.lastBreath) {
          if (this.lastBreath) this.say(breath);
          this.lastBreath = breath;
        }
        const half = BREATH_S / 2;
        const p = inhale ? phase / half : 1 - (phase - half) / half;
        prompt = inhale ? 'Breathe in' : 'Breathe out';
        if (this.reducedMotion) {
          prompt += `, ${Math.ceil(half - (phase % half))}`;
        } else {
          ring = 0.7 + 0.3 * (0.5 - 0.5 * Math.cos(Math.PI * p));
        }
      } else {
        prompt = PROMPT[m.step] || '';
      }
      if (m.paused) sub = 'Paused, reconnecting to the strap';
      else if (m.step === 'get_ready') sub = 'Getting ready';
      else sub = `Step ${m.index} of ${m.count - 1}, ${Math.ceil(m.length_s - t)} s left`;
    } else if (m.state === 'analyzing') {
      prompt = 'Measuring your session';
      sub = 'A few seconds';
    }
    if (this.armedS && now - this.armedS < ARM_MS) {
      prompt = 'Visitor agreed to save this session?';
      sub = 'Press S again to start';
    } else if (this.armedEsc && now - this.armedEsc < ARM_MS) {
      sub = 'Press Esc again to stop and delete this session';
    }
    if (now < this.flashUntil) {
      if (prompt) sub = this.flashText;
      else prompt = this.flashText;
    }
    // write only what changed: most frames change nothing, and the box is an aria-live region
    if (this.prompt.textContent !== prompt) this.prompt.textContent = prompt;
    if (this.sub.textContent !== sub) this.sub.textContent = sub;
    const hide = !prompt && !sub;
    if (this.box.hidden !== hide) this.box.hidden = hide;
    if (this.ring.hidden !== (ring === null)) this.ring.hidden = ring === null;
    if (ring !== null) this.ring.style.transform = `translate(-50%, -50%) scale(${ring.toFixed(3)})`;
  }
}
