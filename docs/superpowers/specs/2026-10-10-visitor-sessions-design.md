# Visitor sessions and summary: design

Date: 2026-10-10. Status: approved in conversation, waiting for review of this written spec.

Scope: saved sessions and the visitor summary, plus two sponsor integrations (Neon for the summary store, a Hugging Face voice coach). The rhythm feasibility test (Databricks, Hugging Face rhythm model) and any condition flags get their own specs later.

## Goal

A booth visitor wears the strap, agrees to a saved session, follows a two minute guided script on the big screen, and then sees a summary of what their heart did: on the big screen with a QR code, and on their own phone. Every number on it is a measurement that states its window and method. Nothing on it is a diagnosis.

## Decisions

- Guided session of about two minutes: get ready, rest 30 s, breathe 40 s, squats 20 s, recover 30 s.
- Five summary sections: effort and recovery, breathing, heart rate variability, average heartbeat, beat timing.
- The big screen shows the summary with a QR code; the QR opens the same page on the visitor's phone.
- Opt-in per visitor. The full recording stays on the laptop during the event, a visitor can delete theirs, and one command wipes everything after the event.
- Anonymous: a random ID, no names.
- Neon stores the anonymous summary, never the raw ECG. A small Vercel function serves it, so the QR works on any network.
- A voice coach reads the steps. The clips are made once with an open text-to-speech model from Hugging Face and shipped as audio files.
- Measurements only, in plain words: no verdicts ("good", "normal", "healthy"), no condition or rhythm names, no reference ranges.
- The booth runs with no internet. The cloud parts are optional and fall back to a LAN link.
- New code goes in new files. Edits to files Thomas is changing (`main.js`, `index.html`, `style.css`, `app.py`) stay small.

## Session flow

The visitor puts the wet strap on while the operator explains the session and asks for consent, so the strap's 20 to 30 s of settling junk passes during the talk.

Operator keys, with no on-screen chrome (like R, W and C):

- S arms a session: the stage shows "Visitor agreed to save this session? Press S again to start." A second S within 5 s starts it. The double press is the record of consent.
- Esc backs out of the confirm. During a session, the first Esc shows "Press Esc again to stop and delete this session" and a second Esc within 5 s deletes it. On the summary, Esc returns to the live view.
- V turns the voice on or off.

| Step | Length | Prompt on the stage | Measures |
|---|---|---|---|
| Get ready | until clean for 5 s, at most 30 s | Hold still while the signal settles | nothing |
| Rest | 30 s | Sit still and breathe normally | resting rate, variability, beat timing, breathing at rest |
| Breathe | 40 s | Breathe in, breathe out, with a guide ring | heart rate swing with each breath |
| Squats | 20 s | Squats, keep going | peak rate |
| Recover | 30 s | Stand still and catch your breath | drop over 30 s |
| Summary | until dismissed, 3 min at most | the summary page | |

The average heartbeat uses rest and breathe together.

Rules:

- Step clocks count received samples, not wall time, so a step pauses while the strap is away. With no samples for 15 s the session ends early and the summary covers the steps that finished.
- Clean means no sample at the clip level (absolute value 19000 uV or more) and at least 3 beats from the live detector with RR between 0.3 and 2.0 s in the last 5 s. If get ready reaches 30 s without that, the session goes on and the quality rules below decide what can be measured.
- One session at a time. Start is refused when no samples arrived in the last 2 s; the stage shows "No signal yet".
- The breathe step paces 6 breaths a minute: 5 s in, 5 s out, starting with in. Under prefers-reduced-motion the ring stays still and the prompt alternates "Breathe in" and "Breathe out" with a seconds count.
- The live view keeps running under the overlay, so the visitor watches their heart change. The extras row under the chamber lanes stays empty.

Overlay layout: the prompt sits at the top center of the stage in Plex Sans 600, with one dim line under it for the step number and seconds left. The guide ring is a hairline circle centered on the heart that grows over 5 s and shrinks over 5 s.

## Architecture

```
strap / sim / replay -> pump() -> Hub -> live view (unchanged)
                          |
                          +-> SessionManager: steps, timing, recording
                                   | session ends
                                   v
                              analysis: NeuroKit2 -> summary
                     +-------------+------------------------+
                     v             v                        v
          big screen summary   sessions/<id>/ on laptop   Neon: anonymous summary only
          and QR code          (full recording, wiped)          ^ read and delete by link
                                                   Vercel function <- visitor's phone
```

New files:

- `backend/session.py`: the session manager. Step machine, sample-count timing, the 15 s drop limit, cancel, the recording on disk, and the `session` messages.
- `backend/analysis.py`: pure functions from a recording and its step windows to a summary. Each section is either values or "couldn't measure" with a reason.
- `backend/synth.py`: builds a synthetic session with known answers, for tests and for the `/s/demo` page.
- `backend/cloud.py`: Neon sync, enabled only when `NEON_DATABASE_URL` is set.
- `frontend/session.js`, `frontend/session.css`: the overlay (prompt, countdown, guide ring, voice, keys).
- `frontend/summary.html`, `frontend/summary.js`, `frontend/summary.css`: the summary page.
- `frontend/assets/voice/*.wav`: the voice clips.
- `cloud/`: the Vercel project (one Python function and the static summary page).
- `tools/sessions.py`: `list`, `delete <id>`, `wipe`, `cloud-init`, `deploy`.
- `tools/make_voice.py`, `tools/requirements-voice.txt`: renders the voice clips.

Small edits:

- `backend/app.py`: call the session manager from `pump()`, add the routes below, put the session state in the backlog.
- `frontend/main.js`: hand `session` messages and keys to `session.js`.
- `frontend/index.html`: one overlay container and one stylesheet link.
- `requirements.txt`: `segno==1.6.6` (QR codes), `psycopg[binary]==3.3.6` (Neon).
- `.gitignore`: `sessions/`, `.env`, `cloud/public/`, `cloud/.vercel/`.
- `README.md` and `CLAUDE.md`: sessions, keys, the cloud setup, the wipe command, the new message.

## Messages and routes

New WebSocket message, server to viewer, sent on every change and once per packet while running. A late viewer gets the current one in the backlog.

```json
{"type": "session", "state": "running", "id": "x7Qk...", "step": "breathe", "index": 2, "count": 5, "elapsed_s": 12.3, "length_s": 40, "paused": false}
{"type": "session", "state": "analyzing", "id": "x7Qk..."}
{"type": "session", "state": "done", "id": "x7Qk...", "link": "https://cardioview.vercel.app/s/x7Qk...", "online": true}
{"type": "session", "state": "idle"}
```

`index` counts from 0 over get ready, rest, breathe, squats and recover. The overlay animates the ring and countdown from `elapsed_s` with its own clock between messages.

HTTP routes on the booth server:

- `POST /api/session/start`: 200 with the id, or 409 with a reason (already running, no signal).
- `POST /api/session/cancel`: stops and deletes the running session.
- `POST /api/session/dismiss`: back to idle.
- `GET /api/s/{id}`: the summary JSON; 404 when missing, deleted or past keep-until.
- `DELETE /api/s/{id}`: deletes the local folder and the Neon row.
- `GET /api/s/{id}/qr.svg`: a QR code for the best link.
- `GET /s/{id}`: the summary page. `GET /s/demo` serves the synthetic session.

## Storage and retention

Local folder `sessions/<id>/`, ignored by git:

- `session.json`: id, created, keep-until, source, device, state (`recording`, `analyzing` or `done`), each step's start and end stream time and seconds done, and consent (`{"by": "operator", "how": "pressed S twice", "at": <time>}`).
- `ecg.csv`: `time_s,ecg_uv`, the same format as `data/`, so `--source sessions/<id>/ecg.csv` replays it.
- `beats.csv`: `r,rr,bpm` from the live detector.
- `summary.json`: the analysis.

The id is `secrets.token_urlsafe(16)`, 128 random bits. At startup, folders whose state is not `done` are deleted, so an interrupted session leaves nothing behind.

Neon, one table:

```sql
create table session_summary (
  id text primary key,
  created_at timestamptz not null default now(),
  keep_until timestamptz not null,
  summary jsonb,
  deleted_at timestamptz
);
```

Two roles: `cardioview_booth` (select, insert, update, delete) for the laptop, and `cardioview_public` (select, plus update of `summary` and `deleted_at`) for the Vercel function. A delete from a phone sets `deleted_at` and clears `summary`. The laptop's sync loop deletes the local folder for every such row, then removes the row. `tools/sessions.py cloud-init` creates the table and both roles from an owner connection string and prints the two connection strings once.

Retention:

- keep-until defaults to 24 hours after the server starts; `--keep-until` sets it.
- Reads refuse rows that are deleted or past keep-until, on the laptop and in the function.
- `tools/sessions.py wipe` deletes every local session and every Neon row, and asks first unless given `--yes`.

## Analysis

`backend/analysis.py`, run once when the session ends, in a thread. It takes a few seconds and never blocks the live view.

Preparation:

- Split the recording at stream time gaps. For each contiguous piece of at least 5 s, run `nk.ecg_clean` and `nk.ecg_peaks` with artifact correction, at the native 130 Hz.
- A beat is usable when its RR is between 0.3 and 2.0 s and no sample within 0.5 s of it is at the clip level.
- The heart rate series is 60 / RR at each usable beat, interpolated to 4 Hz. The chart uses 1 Hz.

Each section is values or "couldn't measure" with a plain reason ("not enough steady signal during rest").

1. Effort and recovery
   - Resting rate: median heart rate over rest. Needs 20 s of usable beats in rest.
   - Peak rate: the highest 5-beat median heart rate from the start of squats to 10 s into recover.
   - Drop: peak rate minus the median heart rate from 27 to 30 s after squats end. Needs recover to have run its full 30 s.
   - Chart: heart rate over the whole session with the steps marked.
   - Text: "Resting 68 bpm. Peak 141 bpm during squats. Dropped 31 bpm in the 30 s after."
2. Breathing
   - Breathing rate at rest, estimated from the ECG with NeuroKit2's ECG-derived respiration over the rest step. Needs at least 3 breaths and a rate between 6 and 30 a minute.
   - The same estimate over the breathe step, shown next to the pace of 6 a minute as a check.
   - Swing: for each full 10 s breath in the breathe step, the highest minus the lowest heart rate; the median over breaths. Needs 3 full breaths with usable beats.
   - Text: "At rest you breathed about 14 times a minute (estimated from the ECG). Breathing slowly, your heart rate rose and fell by about 11 bpm with each breath."
3. Heart rate variability
   - RMSSD and SDNN of the beat-to-beat intervals in rest (`nk.hrv_time` on the corrected peaks). Needs 20 intervals with at most 10 percent corrected.
   - Text: "RMSSD 42 ms and SDNN 51 ms, over 30 s at rest. Both describe how much the time between beats changes."
4. Average heartbeat
   - The median of usable beats from rest and breathe, from 0.25 s before to 0.5 s after the R peak. Needs 30 beats whose correlation with the median beat is at least 0.8.
   - Durations from `nk.ecg_delineate` (DWT) over the same beats, the median of each landmark: P to QRS (P onset to QRS onset), QRS (onset to offset), QT (QRS onset to T offset). Rounded to 10 ms and marked approximate at 130 Hz. Each needs its landmark on at least 20 beats. No QTc.
   - Text: "Averaged from 78 beats. P to QRS about 150 ms, QRS about 90 ms, QT about 380 ms (approximate at 130 Hz)."
5. Beat timing
   - Each beat's RR against the next one, for rest and for breathe in two shades. No numbers, no verdict.
   - Text: "Each dot is one beat: the gap before it against the gap after it. Steady timing makes a tight cluster; slow breathing stretches it along the diagonal."

The page footer: "A visualization, not a medical device. It does not diagnose anything."

## Summary page

One page (`summary.html`, `summary.js`, `summary.css`) for three hosts: the big screen (`/s/<id>?screen=1`), a phone on the LAN (`/s/<id>`), and Vercel (`/s/<id>`). It fetches `/api/s/<id>` from its own origin and draws its charts on canvas with no chart library.

It follows the viewer's language: ink background, hairlines, Plex Sans in sentence case, no panels, pills or chips. ECG green appears only on the measured average beat. Blue and red keep their right and left heart meaning, so the other charts use the text and dim colors.

- Big screen, 1920 by 1080: a header with the wordmark and "Your session, 2 min, 14:03"; the effort chart across the top; breathing, variability, average beat and beat timing in four columns below; on the right the QR code with "Scan to keep this on your phone" and "Available until Sun 14:03". Esc goes back to live, and so does 3 minutes without a key.
- Phone, portrait: the same sections stacked, no QR, and "Delete my session" at the bottom (tap once, then "Tap again to delete", then "Deleted").
- A deleted or expired link shows "This session is no longer available."

## Voice coach

`tools/make_voice.py` renders each prompt line with Kokoro 82M (`hexgrad/Kokoro-82M` on Hugging Face, Apache 2.0) to `frontend/assets/voice/<key>.wav`, 24 kHz mono. It runs once on a dev machine (the `kokoro` package needs Python 3.10 to 3.12, pinned in `tools/requirements-voice.txt`). The WAV files are committed, so the booth needs neither the model nor the internet.

Lines: get ready ("Hold still while we get a clean signal."), rest ("Sit still and breathe normally."), breathe ("Now breathe with the ring."), in ("In."), out ("Out."), squats ("Squats. Keep going."), recover ("Stop. Stand still and catch your breath."), done ("All done. Here is your heart."), stopped ("Session stopped and deleted.").

`session.js` plays the line at each step change and in and out on each breath. The S key press unlocks audio in the browser. The README credits the model and its license.

## Cloud: Neon and Vercel

- `backend/cloud.py` is enabled only when `NEON_DATABASE_URL` is set, read from the environment or a local `.env` that is never committed. After analysis it upserts the id, keep-until and summary with a 4 s timeout.
- If the upsert fails, the QR uses the LAN link. A background loop retries every 30 s until keep-until, and when it succeeds the big screen gets a new `done` message and the QR switches to the public link. The same loop applies deletes made from phones.
- The QR link is `CARDIOVIEW_PUBLIC_URL/s/<id>` once the upsert succeeded, otherwise `http://<LAN address>:<port>/s/<id>`. The LAN address is the outbound interface's; `--public-host` overrides it.
- `cloud/` holds a Vercel project: a Python FastAPI function for `GET` and `DELETE /api/s/{id}` using the `cardioview_public` role, and the summary page with the fonts it needs. `tools/sessions.py deploy` copies those files from `frontend/` into `cloud/public/` (ignored by git, so `frontend/` stays the one source) and runs `vercel deploy --prod`.
- With no environment variables and no internet, the booth behaves exactly as today plus local sessions.

## Error handling

- Start with no signal: refused, "No signal yet".
- Strap drops: the step pauses and the stage says "Paused, reconnecting to the strap". After 15 s without samples the session ends early.
- Analysis raises: logged, every section shows "couldn't measure", the server keeps running.
- A disk write fails: the session is cancelled and its folder removed.
- The server restarts mid-session: the unfinished folder is deleted at startup.
- Neon is unreachable: the LAN link, with retries as above. Vercel is down: the LAN link still works at the booth.

## Testing

- `backend/synth.py` builds a session from a designed RR series: rest near 70 bpm with natural variation, breathe with a 0.1 Hz swing of plus or minus 6 bpm, squats ramping to about 140, recover decaying. It places a NeuroKit2-simulated beat at each R peak at 130 Hz, so the expected values follow from the design.
- `test_analysis.py`: each section within tolerance of the designed values (rest within 2 bpm, peak within 3, drop within 4, swing within 3, RMSSD within 15 percent of the designed series, durations within 30 ms of the same beat template delineated at 1000 Hz); "couldn't measure" for noise, short steps and clipping; Thomas's recording analysed as a rest step without errors.
- `test_session.py`: step order and lengths by sample count, pause and early end on a gap, cancel deletes the folder, start refused without signal, consent written, unfinished folders removed at startup.
- `test_app_sessions.py`: the routes, the session message in the backlog, the QR SVG.
- `test_cloud.py`: sync with a fake database adapter, disabled without the variable, phone deletes remove the local folder.
- `cloud/tests/`: the function with a fake adapter; deleted and expired rows give 404; DELETE writes the tombstone.
- Screens: `tools/screenshot.mjs` on the overlay during rest and breathe, the big-screen summary, and a phone-size summary, all from `/s/demo` (synthetic, nobody's ECG).
- On hardware, on Thomas's Mac: one real session with the strap, and the QR opened on a phone both over the public link and over a hotspot.

## Out of scope

- The rhythm feasibility test and condition flags: separate specs.
- Replays on the phone. Thomas's planned QR replay extra can build on these sessions later.
- Accounts, names and history across visits.

## Risks

- The voice tool pulls in torch on the dev machine, about 200 MB. Only the WAV files ship.
- Breathing estimated from 30 s of ECG is approximate. It will sometimes say "couldn't measure", which is the intended behavior.
- Thomas is changing `main.js`, `index.html` and `style.css` often. Our edits there stay small and get merged last, after a fresh pull.
