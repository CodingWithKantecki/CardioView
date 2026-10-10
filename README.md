# CardioView

See your own heart beat, live in 3D. A Polar H10 chest strap streams ECG over Bluetooth, Python finds every beat, and a browser shows a heart model squeezing chamber by chamber in time with it, next to the live trace, the heart rate and the chamber timing.

Status: the core works. Simulated ECG, CSV replay and the live Polar H10 all drive the trace (2D or a 3D beat waterfall), heart rate, chamber activation lanes (their timing is derived from the ECG, not measured) and the 3D heart with its chamber labels and waves. Drag to orbit, scroll to zoom, an opacity slider, and the R, W and C keys for auto-rotate, wireframe and cutaway. The strip in the header is the last 30 s: drag it to scrub, and the Rewind, Play, Pause, Fast forward and Live buttons replay it or return to now; the heart, the trace and the lanes all follow. A signal monitor turns the stage into a red glitch with a plain-words alert when there is no signal at all. `data/h10_ecg_thomas.csv` is a real 84 s recording.

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

Options: `--bpm 72` sets the simulated rate, `--invert` flips a strap worn upside down, `--host` and `--port` change where it listens (default 0.0.0.0:8000). Whatever you start with, the Strap / Demo toggle at the top right of the viewer switches between the live strap and demo data without a restart; `--demo data/<file>.csv` or `--demo sim` picks the demo source (default: the first recording in `data/`). In Demo, the Simulated rhythm tray beside the heart rate plays synthesized rhythms (normal, bradycardia, atrial fibrillation, extra beats, ventricular tachycardia) for showing the screen without a strap; they are simulations and are never offered beside strap data. Hover the blue ! in a cell to read what that rhythm is. Press T to switch between the dark theme and the cream one.

## The strap

- Wet the pads and wear the H10 around the chest. It only switches on when the pads touch skin.
- Close Polar apps and any browser tab that uses the strap. It takes one Bluetooth connection at a time.
- The first 20 to 30 seconds after strapping in are junk while the contact settles. Wait before trusting the trace.
- macOS: the terminal app needs Bluetooth permission (System Settings > Privacy & Security > Bluetooth). macOS asks the first time.
- Record a fixture without the server: `python tools/h10_record.py --seconds 90 --out data/h10_ecg_<name>_raw.csv`, then trim the settling lead-in with `python tools/trim_csv.py data/h10_ecg_<name>_raw.csv data/h10_ecg_<name>.csv --start 30`.

If the pads lose contact or the strap drops, the screen says so and the heart glitches until signal is back. A noisy signal is shown as it is. Add `?signal=lost` to the URL to rehearse that state.

ECG is personal data. Only commit your own recording, never a visitor's.

## The heart model

The repo ships the free Sketchfab model credited below. A better set is optional: the CGTrader pack "Human Heart with Cross section" by devden, a whole heart plus the same heart opened along the four-chamber plane. Its license does not allow redistribution, so it is not in the repo: put its GLB files in `frontend/assets/heart-pro/` as `exterior-2.glb` (or `exterior-1.glb`, the other texture variation, and point `frontend/assets/heart-pro.json` at it) and `inside.glb`, and the viewer picks them up, with the C key swapping in the opened heart. Without that folder it falls back to the bundled model.

`frontend/assets/heart.json` (and `heart-pro.json` for the purchased set) holds, per chamber, the contraction center and radius plus a surface anchor and outward normal for the label, all in the normalized model space (model centered at the origin, 1.8 units tall), plus the camera. Labels keep fixed slots beside the heart, swap sides once when you look at it from behind, point at their anchors and dim when the anchor faces away. The small wave under each label is modeled from the beat timing (it is not a pressure measurement), which is why the heart card says WAVES: MODELED. Open the viewer with `?debug=1` to see the bounding box, axes and a marker per chamber while adjusting them; `?act=1` holds every chamber squeezed and `?act=0` relaxed.

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
- Heart model: this work is based on "Realistic Human Heart" (https://sketchfab.com/3d-models/realistic-human-heart-3f8072336ce94d18b3d0d055a1ece089) by neshallads (https://sketchfab.com/neshallads) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/). Files in `frontend/assets/heart/` with the license text. The chambers are animated by a vertex shader; the model itself is unchanged.

This is a visualization, not a medical device. It shows no diagnosis.
