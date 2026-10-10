# CardioView

See your own heart beat, live in 3D. A Polar H10 chest strap streams ECG over Bluetooth, Python finds every beat, and a browser shows a heart model squeezing chamber by chamber in time with it, next to the live trace, the heart rate and the chamber timing.

Status: the core works. Simulated ECG, CSV replay and the live Polar H10 all drive the trace, heart rate, chamber activation lanes (their timing is derived from the ECG, not measured) and the 3D heart with its chamber labels and waves. Drag to orbit, scroll to zoom, and a dock at the bottom of the stage for rotate, wireframe, opening the heart, opacity and reset view (the R, W and C keys do the first three as well). The strip in the header is the last 30 s: drag it to scrub, and the Rewind, Play, Pause, Fast forward and Live buttons replay it or return to now; the heart, the trace and the lanes all follow. A signal monitor turns the stage into a red glitch with a plain-words alert when there is no signal at all. `data/h10_ecg_thomas.csv` is a real 84 s recording.

## Setup

You need Python 3.10 or newer and a Mac with Bluetooth for the live strap. Check with `python3 --version` (Windows: `py -3 --version`). The macOS built-in `python3` is 3.9 and will not do; install Python from python.org or Homebrew (`brew install python@3.14`).

macOS and Linux:

```
git clone https://github.com/CodingWithKantecki/CardioView.git
cd CardioView
python3 -m venv .venv            # macOS with Homebrew: /opt/homebrew/bin/python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Windows (PowerShell):

```
git clone https://github.com/CodingWithKantecki/CardioView.git
cd CardioView
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

The install takes about two minutes. Below, `python` means `.venv/bin/python` (macOS, Linux) or `.venv\Scripts\python` (Windows).

## Run

Then open http://localhost:8000 on the same machine, or http://<this machine's IP>:8000 from the big screen or a phone on the same Wi-Fi.

```
python -m backend --source sim                  # simulated ECG, no hardware
python -m backend --source data/<file>.csv      # replay a recording
python -m backend --source h10                  # live from the Polar H10
```

Options: `--bpm 72` sets the simulated rate, `--invert` flips a strap worn upside down, `--host` and `--port` change where it listens (default 0.0.0.0:8000). Whatever you start with, the Strap / Demo / Exercise toggle at the top right of the viewer switches between the live strap and demo data without a restart; `--demo data/<file>.csv` or `--demo sim` picks the demo source (default: the first recording in `data/`). In Demo, the Simulated rhythm tray beside the heart rate plays synthesized rhythms (normal, bradycardia, atrial fibrillation, extra beats, ventricular tachycardia, heart attack) for showing the screen without a strap; they are simulations and are never offered beside strap data. Hover the blue ! in a cell to read what that rhythm is. Press T to switch between the dark theme and the cream one. The 0 key resets the view, like the dock's Reset view.

### Chat (optional, the only part that needs internet)

The Ask button opens a Gemini guide grounded in CardioView's own measurements. It can answer questions, show the latest, fastest or slowest recent beat by pausing the shared replay clock, focus the ECG, chambers or heart, and open or reset the heart view. The saved-session page can compare rest, breathing, squats and recovery, show the exact derived evidence it used, and focus the relevant report section. Deterministic CardioView code selects and calculates the measurements; Gemini chooses tools and explains their results.

To turn it on, create a file named `.env` in the repo root (next to this README, on any OS) with one line:

```
GEMINI_API_KEY=your-key-here
```

Get a free key at https://aistudio.google.com/apikey. The server reads the file at startup, the key never leaves the server and `.env` is ignored by git. Without a key the guide says "Chat is not set up on this server"; without internet it says so too, and everything else keeps working. `GEMINI_MODEL=<name>` in the same file changes the model (default `gemini-3.5-flash`). The answers come from an AI and can be wrong. It never diagnoses and labels evidence as measured, derived, modeled or simulated. Saved-session questions send anonymous summary measurements to Gemini, never the raw ECG or chart arrays; the page says this beside the input.

## The strap

- Wet the pads and wear the H10 around the chest. It only switches on when the pads touch skin.
- Close Polar apps and any browser tab that uses the strap. It takes one Bluetooth connection at a time.
- The first 20 to 30 seconds after strapping in are junk while the contact settles. Wait before trusting the trace.
- macOS: the terminal app needs Bluetooth permission (System Settings > Privacy & Security > Bluetooth). macOS asks the first time.
- Record a fixture without the server: `python tools/h10_record.py --seconds 90 --out data/h10_ecg_<name>_raw.csv`, then trim the settling lead-in with `python tools/trim_csv.py data/h10_ecg_<name>_raw.csv data/h10_ecg_<name>.csv --start 30`.

If the pads lose contact or the strap drops, the screen says so and the heart glitches until signal is back. A noisy signal is shown as it is. Add `?signal=lost` to the URL to rehearse that state.

ECG is personal data. Only commit your own recording, never a visitor's.

## The heart model

The viewer uses the CGTrader pack "Human Heart with Cross section" by devden (purchased under its royalty-free license by Thomas Kantecki; the files are in `frontend/assets/heart-pro/` so the whole team runs the same heart): a whole heart (`exterior-2.glb`; `exterior-1.glb` is the other texture variation, switchable in `frontend/assets/heart-pro.json`) plus the same heart opened along the four-chamber plane (`inside.glb`), which the Open control in the dock swaps in; its valves open and close with the beat. If that folder is missing the viewer falls back to the free Sketchfab model credited below.

`frontend/assets/heart.json` (and `heart-pro.json` for the purchased set) holds, per chamber, the contraction center and radius plus a surface anchor and outward normal for the label, all in the normalized model space (model centered at the origin, 1.8 units tall), plus the camera. Labels keep fixed slots beside the heart, swap sides once when you look at it from behind, point at their anchors and dim when the anchor faces away. The small wave under each label is modeled from the beat timing (it is not a pressure measurement), which is why the heart card says WAVES: MODELED. Open the viewer with `?debug=1` to see the bounding box, axes and a marker per chamber while adjusting them; `?act=1` holds every chamber squeezed and `?act=0` relaxed.

## Saved sessions

A visitor can save a two minute session and take a summary of it home.

1. Strap them in and explain: their ECG is recorded for about two minutes, without their name, kept on this laptop until the end of the event, and they can delete it from their phone.
2. If they agree, press S, then S again. The stage walks them through it: hold still, rest, slow breathing with the ring, squats, recovery.
3. The big screen then shows their summary with a QR code. Esc goes back to the live view, and so does three minutes without a key.

The Exercise cell in the header starts a session with two clicks (the consent) and stops one with two clicks; it only works while the real strap is streaming, never on demo data. S twice and Esc twice do the same from the keyboard, and V turns the voice on or off. While a session runs, the Strap / Demo and rhythm buttons wait: stop the session first. The report opens over the live view and Back returns to it.

The summary shows effort and recovery, breathing, heart rate variability, their average heartbeat and their beat timing. A section says what it could not measure when the signal was not good enough. A session run on demo data says so at the top. It is a visualization, not a diagnosis.

Sessions live in `sessions/` on this machine and never go into git. After the event:

```
python tools/sessions.py wipe
```

`--keep-until 2026-10-11T18:00` on the server sets when sessions expire (default: 24 hours after it starts). `python tools/sessions.py list` shows what is saved.

### The public link (optional)

Without this, the QR opens the summary over the booth's Wi-Fi only. To make it open anywhere:

1. Create a free project at neon.com and copy its connection string (Connect, with connection pooling on).
2. `python tools/sessions.py cloud-init "<that connection string>"`, then put the two lines it prints where it says. Nothing uses the owner password after this, so you can reset it in Neon.
3. `npm i -g vercel` and `vercel login`, then in `cloud/`: `vercel project add cardioview`, `vercel link --yes --project cardioview` and `vercel env add NEON_PUBLIC_URL production --sensitive` (paste the public line). `cloud/vercel.json` already sets the FastAPI preset.
4. `python tools/sessions.py deploy`, and put `CARDIOVIEW_PUBLIC_URL=<the URL it prints>` in `.env`. Restart the server.

Only the anonymous summary goes to Neon. The raw ECG stays on this machine.

## Tests and checks

```
python -m pytest
```

Headless screenshot of the running viewer (needs Node and Google Chrome): `cd tools && npm install && node screenshot.mjs`. It writes `tools/out/screen.png`.

`python tools/fake_strap.py` runs a server on port 8002 whose strap is fake (the recording streamed like the H10), for checking the Strap / Demo switch without hardware.

## Credits

- Three.js 0.186.0, MIT license, vendored in `frontend/vendor/three/`.
- IBM Plex fonts 5.3.0 via Fontsource, SIL Open Font License 1.1, vendored in `frontend/vendor/fonts/`.
- JetBrains Mono 5.2.6 via Fontsource (weights 400, 600, 700), SIL Open Font License 1.1, vendored in `frontend/vendor/fonts/` with its license file.
- NeuroKit2 for ECG cleaning, peak detection and delineation, MIT license.
- bleak (MIT license) and bleakheart (Mozilla Public License 2.0) for the Polar H10 link.
- Voice: the session prompts were generated with Kokoro 82M (https://huggingface.co/hexgrad/Kokoro-82M), Apache 2.0.
- segno (BSD) for QR codes, psycopg (LGPL 3) for Neon.
- Heart model: "Human Heart with Cross section" by devden on CGTrader, royalty-free license, purchased by Thomas Kantecki.
- Fallback heart model: this work is based on "Realistic Human Heart" (https://sketchfab.com/3d-models/realistic-human-heart-3f8072336ce94d18b3d0d055a1ece089) by neshallads (https://sketchfab.com/neshallads) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/). Files in `frontend/assets/heart/` with the license text. The chambers are animated by a vertex shader; the model itself is unchanged.

This is a visualization, not a medical device. It shows no diagnosis.
