# CardioView

See your own heart beat, live in 3D. A Polar H10 chest strap streams ECG over Bluetooth, Python finds every beat, and a browser shows a heart model squeezing chamber by chamber in time with it, next to the live trace, the heart rate and the chamber timing.

Status: simulated ECG and CSV replay run end to end (trace, heart rate, chamber lanes). Live strap source and the heart model are next.

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

Options: `--bpm 72` sets the simulated rate, `--invert` flips a strap worn upside down, `--host` and `--port` change where it listens (default 0.0.0.0:8000).

## The strap

- Wet the pads and wear the H10 around the chest. It only switches on when the pads touch skin.
- Close Polar apps and any browser tab that uses the strap. It takes one Bluetooth connection at a time.
- The first 20 to 30 seconds after strapping in are junk while the contact settles. Wait before trusting the trace.
- macOS: the terminal app needs Bluetooth permission (System Settings > Privacy & Security > Bluetooth). macOS asks the first time.
- Record a fixture without the server: `python tools/h10_record.py --seconds 90 --out data/h10_ecg_<name>_raw.csv`, then trim the settling lead-in with `python tools/trim_csv.py data/h10_ecg_<name>_raw.csv data/h10_ecg_<name>.csv --start 30`.

ECG is personal data. Only commit your own recording, never a visitor's.

## Tests and checks

```
python -m pytest
```

Headless screenshot of the running viewer (needs Node and Google Chrome): `cd tools && npm install && node screenshot.mjs`. It writes `tools/out/screen.png`.

## Credits

- Three.js 0.186.0, MIT license, vendored in `frontend/vendor/three/`.
- IBM Plex fonts 5.3.0 via Fontsource, SIL Open Font License 1.1, vendored in `frontend/vendor/fonts/`.
- NeuroKit2 for ECG cleaning, peak detection and delineation, MIT license.
- bleak (MIT license) and bleakheart (Mozilla Public License 2.0) for the Polar H10 link.
- Heart model: to be added with its author, link and license once it is in the repo.

This is a visualization, not a medical device. It shows no diagnosis.
