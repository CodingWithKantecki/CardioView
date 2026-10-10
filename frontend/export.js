// Export: what the page holds (the last minutes of ECG), in three shapes. CSV is the recordings'
// file. FHIR is an R4 Bundle: the waveform as SampledData on an EKG Observation plus a heart rate
// Observation. The PDF report is a saved summary on the server (Gabe's session store and page),
// opened in the report overlay and printed; its QR opens the same page on a phone later.
import { exportCsv } from './trace.js';

export function stamp() {
  const d = new Date();
  const pad = (v) => String(v).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
}

export function sourceName(status) {
  if (!status) return 'ecg';
  return status.source === 'live' ? 'strap' : status.source === 'recorded' ? 'recording' : 'simulated';
}

export function download(name, text, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

export function csv(trace, status) {
  const out = exportCsv(trace);
  if (!out) return false;
  download(`cardioview_${stamp()}_${sourceName(status)}.csv`, out.text, 'text/csv');
  return true;
}

// FHIR R4. The ECG is one lead from a chest strap, so one component carries the whole waveform in
// microvolts with factor 0.001 to millivolts. Simulated and recorded data say so in a note and
// carry no subject, so nothing here reads as a person's record unless it came from the strap.
export function fhirBundle(trace, status, beat) {
  const n = trace.ts.length;
  if (!n) return null;
  const end = new Date();
  const start = new Date(end.getTime() - (trace.ts[n - 1] - trace.ts[0]) * 1000);
  const live = !!status && status.source === 'live';
  const deviceName = live ? (status.device || 'Polar H10') : status?.source === 'recorded' ? 'CardioView recording replay' : 'CardioView rhythm simulator';
  const note = live ? null
    : status?.source === 'recorded' ? 'Replay of a stored recording shown in the CardioView demo, not a live measurement.'
      : `Simulated ECG from the CardioView demo (${(status?.device || 'simulated').replace(/^Simulated: /, '')}), not a measurement of a person.`;
  const device = { resourceType: 'Device', id: 'device', deviceName: [{ name: deviceName, type: 'user-friendly-name' }], manufacturer: live ? 'Polar' : 'CardioView' };
  const ecg = {
    resourceType: 'Observation', id: 'ecg', status: 'final',
    category: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'procedure', display: 'Procedure' }] }],
    code: { coding: [{ system: 'http://loinc.org', code: '11524-6', display: 'EKG study' }], text: 'Single lead ECG from a chest strap' },
    effectivePeriod: { start: start.toISOString(), end: end.toISOString() },
    device: { reference: 'Device/device', display: deviceName },
    component: [{
      code: { coding: [{ system: 'urn:oid:2.16.840.1.113883.6.24', code: '131328', display: 'MDC_ECG_ELEC_POTL' }], text: 'Chest strap lead' },
      valueSampledData: {
        origin: { value: 0, unit: 'mV', system: 'http://unitsofmeasure.org', code: 'mV' },
        period: +(1000 / (trace.fs || 130)).toFixed(4), factor: 0.001, lowerLimit: -19.93, upperLimit: 19.93, dimensions: 1,
        data: trace.raw.join(' '),
      },
    }],
  };
  if (note) ecg.note = [{ text: note }];
  const entries = [{ fullUrl: 'urn:uuid:cardioview-device', resource: device }, { fullUrl: 'urn:uuid:cardioview-ecg', resource: ecg }];
  if (beat && beat.bpm != null) {
    const hr = {
      resourceType: 'Observation', id: 'heart-rate', status: 'final',
      category: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'vital-signs', display: 'Vital Signs' }] }],
      code: { coding: [{ system: 'http://loinc.org', code: '8867-4', display: 'Heart rate' }] },
      effectiveDateTime: end.toISOString(),
      valueQuantity: { value: beat.bpm, unit: 'beats/minute', system: 'http://unitsofmeasure.org', code: '/min' },
      device: { reference: 'Device/device' },
      derivedFrom: [{ reference: 'Observation/ecg' }],
    };
    if (note) hr.note = [{ text: note }];
    entries.push({ fullUrl: 'urn:uuid:cardioview-heart-rate', resource: hr });
  }
  return { resourceType: 'Bundle', type: 'collection', timestamp: end.toISOString(), entry: entries };
}

export function fhir(trace, status, beat) {
  const bundle = fhirBundle(trace, status, beat);
  if (!bundle) return false;
  download(`cardioview_${stamp()}_${sourceName(status)}.fhir.json`, JSON.stringify(bundle, null, 1), 'application/fhir+json');
  return true;
}

// the report: the server stores the buffer and measures it; the caller opens /s/<id>
export async function report(trace, status) {
  const n = trace.ts.length;
  if (!n) return null;
  const body = { fs: trace.fs || 130, t0: trace.ts[0], uv: trace.raw.slice(), source: status?.source || 'unknown', device: status?.device || '' };
  const r = await fetch('/api/export/report', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.reason || 'The server could not make the report');
  return data.id;
}
