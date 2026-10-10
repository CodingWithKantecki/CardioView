// The visitor's own Polar H10, through Web Bluetooth (Chrome and Edge on a computer or Android;
// not Safari). The page starts the strap's ECG stream, parses its frames and sends the samples to
// the server over the viewer's websocket, where that viewer's own pipeline finds the beats. With
// ?fake=1 a synthetic strap stands in (FakeStrap), for checks on machines with no radio.
const PMD_SERVICE = 'fb005c80-02e7-f387-1cad-8acd2d8df0c8';
const PMD_CONTROL = 'fb005c81-02e7-f387-1cad-8acd2d8df0c8';
const PMD_DATA = 'fb005c82-02e7-f387-1cad-8acd2d8df0c8';
const START_ECG = new Uint8Array([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0e, 0x00]);   // ECG, 130 Hz, 14 bit
const STOP_ECG = new Uint8Array([0x03, 0x00]);
const FS = 130;
const CONNECT_TIMEOUT_MS = 20000;   // a first connect that takes longer than this has picked a strap that is not there

export const supported = typeof navigator !== 'undefined' && !!navigator.bluetooth;

export class Strap {
  constructor(send, onChange) {
    this.send = send;           // (msg) => void: to the server, as the viewer's live source
    this.onChange = onChange;   // () => void: the panel reads state, name and reason
    this.state = 'off';         // off, choosing (the browser's list is open), connecting, streaming
    this.name = '';
    this.reason = '';           // why the last attempt gave up, for the panel; empty when none did
    this.device = null;
    this.control = null;
    this.data = null;
    this.samples = 0;
    this.wanted = false;
    this.attempt = 0;
  }

  // the user picked a strap: a gesture is needed for the chooser, so this runs from a click
  async connect() {
    if (!supported || this.state !== 'off') return;
    this.wanted = true;
    this.reason = '';
    this.set('choosing');
    try {
      this.device = await navigator.bluetooth.requestDevice({ filters: [{ namePrefix: 'Polar H10' }], optionalServices: [PMD_SERVICE] });
    } catch (e) {
      this.wanted = false;   // the chooser was closed, or Bluetooth is off
      if (e?.name !== 'NotFoundError') this.reason = `Bluetooth is not available: ${e?.message || e}`;
      this.set('off');
      return;
    }
    this.name = this.device.name || 'Polar H10';
    console.info(`strap: chose ${this.name}`);
    this.device.addEventListener('gattserverdisconnected', () => this.dropped());
    await this.open(true);
  }

  // Connect, find the PMD service and start the ECG stream. The first try after the chooser gives
  // up after CONNECT_TIMEOUT_MS (a device the browser listed from memory never answers); a
  // reconnect after a drop waits as long as it takes for the strap to come back.
  async open(first = false) {
    this.set('connecting');
    const attempt = ++this.attempt;
    const t0 = performance.now();
    const since = () => `${((performance.now() - t0) / 1000).toFixed(1)} s`;
    let timer = null;
    const timeout = first
      ? new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('timeout')), CONNECT_TIMEOUT_MS); })
      : new Promise(() => {});
    try {
      await Promise.race([this.start(since), timeout]);
      if (attempt !== this.attempt || !this.wanted) return;   // cancelled or restarted meanwhile
      this.samples = 0;
      this.set('streaming');
    } catch (e) {
      if (attempt !== this.attempt || !this.wanted) return;
      console.warn(`strap: ${e?.message || e} after ${since()}`);
      if (e?.message === 'timeout') {
        this.wanted = false;
        this.reason = 'The strap did not answer. Close other Polar apps, then pick the entry with the signal icon';
        try { this.device?.gatt.disconnect(); } catch { /* never connected */ }
        this.set('off');
        return;
      }
      this.dropped();
    } finally {
      clearTimeout(timer);
    }
  }

  async start(since) {
    const server = await this.device.gatt.connect();
    console.info(`strap: connected after ${since()}`);
    const service = await server.getPrimaryService(PMD_SERVICE);
    this.control = await service.getCharacteristic(PMD_CONTROL);
    this.data = await service.getCharacteristic(PMD_DATA);
    console.info(`strap: PMD service found after ${since()}`);
    await this.control.startNotifications();
    await this.data.startNotifications();
    this.data.addEventListener('characteristicvaluechanged', (e) => this.frame(e.target.value));
    await this.control.writeValue(START_ECG);
    console.info(`strap: ECG started after ${since()}`);
  }

  // one PMD notification: type, an 8 byte timestamp, a frame type, then 3 byte signed samples in uV
  frame(view) {
    if (this.state !== 'streaming' || view.byteLength < 10 || view.getUint8(0) !== 0x00) return;
    const uv = [];
    for (let i = 10; i + 2 < view.byteLength; i += 3) {
      let v = view.getUint8(i) | (view.getUint8(i + 1) << 8) | (view.getUint8(i + 2) << 16);
      if (v & 0x800000) v -= 0x1000000;
      uv.push(v);
    }
    if (!uv.length) return;
    this.send({ type: 'samples', t: this.samples / FS, uv });
    this.samples += uv.length;
  }

  // the strap went away (pads off, out of range): wait for it to come back
  dropped() {
    if (!this.wanted) return;
    this.set('connecting');
    setTimeout(() => { if (this.wanted && this.device && !this.device.gatt.connected) this.open(); }, 1500);
  }

  // Disconnect while streaming, or Cancel while connecting
  async disconnect() {
    this.wanted = false;
    this.attempt++;
    try { if (this.control && this.device?.gatt.connected) await this.control.writeValue(STOP_ECG); } catch { /* going away anyway */ }
    try { this.device?.gatt.disconnect(); } catch { /* already gone */ }
    this.device = null;
    this.control = null;
    this.data = null;
    this.set('off');
  }

  set(state) {
    this.state = state;
    this.send({ type: 'status', state: state === 'streaming' ? 'streaming' : 'connecting', device: state === 'off' ? '' : this.name });
    this.onChange();
  }
}

// A synthetic sinus ECG at 130 Hz played as if it were a strap, for checks on a machine with no
// radio (?fake=1): the same Gaussian beat model as the simulator, 72 bpm, a strap-like noise floor.
const BEAT = [[-0.18, 0.12, 0.022], [-0.03, -0.10, 0.009], [0, 1.0, 0.011], [0.025, -0.25, 0.010], [0.25, 0.30, 0.050]];
export class FakeStrap {
  constructor(send, onChange) {
    this.send = send; this.onChange = onChange;
    this.state = 'off'; this.name = 'Polar H10 (fake)'; this.timer = null; this.samples = 0; this.beats = [0.4];
  }

  value(t) {
    while (this.beats[this.beats.length - 1] < t + 1) this.beats.push(this.beats[this.beats.length - 1] + 0.83 + (Math.random() - 0.5) * 0.05);
    if (this.beats.length > 8) this.beats.splice(0, this.beats.length - 8);
    let v = 0;
    for (const r of this.beats) { const dt = t - r; if (dt > -0.5 && dt < 0.7) for (const [c, a, w] of BEAT) v += a * Math.exp(-((dt - c) ** 2) / (2 * w * w)); }
    return Math.round((v + (Math.random() - 0.5) * 0.08) * 600);
  }

  async connect() {
    this.state = 'streaming';
    this.send({ type: 'status', state: 'streaming', device: this.name });
    this.onChange();
    this.timer = setInterval(() => {
      const uv = [];
      for (let i = 0; i < 73; i++) uv.push(this.value((this.samples + i) / FS));
      this.send({ type: 'samples', t: this.samples / FS, uv });
      this.samples += 73;
    }, 73000 / FS);
  }

  async disconnect() {
    clearInterval(this.timer); this.timer = null; this.state = 'off';
    this.send({ type: 'status', state: 'connecting', device: '' });
    this.onChange();
  }
}
