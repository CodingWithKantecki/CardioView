// The visitor's own Polar H10, through Web Bluetooth (Chrome and Edge on a computer or Android;
// not Safari). The page starts the strap's ECG stream, parses its frames and sends the samples to
// the server over the viewer's websocket, where that viewer's own pipeline finds the beats. With
// ?debug=1 a recording can stand in for a strap (fakeStrap), for checks on machines with no radio.
const PMD_SERVICE = 'fb005c80-02e7-f387-1cad-8acd2d8df0c8';
const PMD_CONTROL = 'fb005c81-02e7-f387-1cad-8acd2d8df0c8';
const PMD_DATA = 'fb005c82-02e7-f387-1cad-8acd2d8df0c8';
const START_ECG = new Uint8Array([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0e, 0x00]);   // ECG, 130 Hz, 14 bit
const STOP_ECG = new Uint8Array([0x03, 0x00]);
const FS = 130;

export const supported = typeof navigator !== 'undefined' && !!navigator.bluetooth;

export class Strap {
  constructor(send, onChange) {
    this.send = send;           // (msg) => void: to the server, as the viewer's live source
    this.onChange = onChange;   // () => void: the panel reads state and name
    this.state = 'off';         // off, connecting, streaming
    this.name = '';
    this.device = null;
    this.control = null;
    this.data = null;
    this.samples = 0;
    this.wanted = false;
  }

  // the user picked a strap: a gesture is needed for the chooser, so this runs from a click
  async connect() {
    if (!supported) return;
    this.wanted = true;
    try {
      this.device = await navigator.bluetooth.requestDevice({ filters: [{ namePrefix: 'Polar H10' }], optionalServices: [PMD_SERVICE] });
    } catch (e) {
      this.wanted = false;   // the chooser was closed
      return;
    }
    this.name = this.device.name || 'Polar H10';
    this.device.addEventListener('gattserverdisconnected', () => this.dropped());
    await this.open();
  }

  async open() {
    this.set('connecting');
    try {
      const server = await this.device.gatt.connect();
      const service = await server.getPrimaryService(PMD_SERVICE);
      this.control = await service.getCharacteristic(PMD_CONTROL);
      this.data = await service.getCharacteristic(PMD_DATA);
      await this.control.startNotifications();
      await this.data.startNotifications();
      this.data.addEventListener('characteristicvaluechanged', (e) => this.frame(e.target.value));
      await this.control.writeValue(START_ECG);
      this.samples = 0;
      this.set('streaming');
    } catch (e) {
      console.warn('strap:', e?.message || e);
      this.dropped();
    }
  }

  // one PMD notification: type, an 8 byte timestamp, a frame type, then 3 byte signed samples in uV
  frame(view) {
    if (view.byteLength < 10 || view.getUint8(0) !== 0x00) return;
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

  dropped() {
    if (!this.wanted) return;
    this.set('connecting');
    setTimeout(() => { if (this.wanted && this.device && !this.device.gatt.connected) this.open(); }, 1500);
  }

  async disconnect() {
    this.wanted = false;
    try { if (this.control && this.device?.gatt.connected) await this.control.writeValue(STOP_ECG); } catch { /* going away anyway */ }
    try { this.device?.gatt.disconnect(); } catch { /* already gone */ }
    this.device = null;
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
