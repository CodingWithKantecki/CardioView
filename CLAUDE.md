# CardioView

A 3D heart on a big screen that beats in time with a real person's heart. They wear a Polar H10 chest strap, we read their ECG live, and the heart model squeezes chamber by chamber on every beat. Hackathon project (KnightHacks IX). Thomas owns the strap (Polar H10 223FD838), the Mac and the decisions.

The demo: someone straps in, their heart appears, they do squats or breathe slowly and watch it change. So it has to survive motion noise and rates from about 45 to 180 bpm.

## How to work here

- Time is the constraint. Get the simplest version working end to end, then improve it. Build the core in one pass in milestone order; no waiting between milestones, but each piece works before the next starts.
- In a cloud session you have no Bluetooth and cannot reach the strap or the Mac. Thomas runs anything live. So:
  - Build and test against simulated and recorded ECG.
  - Never report the live path as working. Say it is untested on hardware, give the exact command to run on the Mac and the output to expect, then ask for the result.
  - Thomas cannot see your machine. Before calling viewer work done, open it in a headless browser, take a screenshot and look at it. If no browser is available, say the viewer is unverified.
  - The network is an allowlist: package registries, GitHub and similar. PhysioNet, Zenodo, Sketchfab and JS CDNs are not on it. If a download fails, do not work around it. Ask Thomas to commit the file or to allow the domain.
- In a session on the Mac itself you can run the strap commands directly. Ask Thomas to put the strap on first.
- Commit small and push often so Thomas can pull and run on the Mac.

## Scope

Core, built in this order:
1. Recorded ECG playback through the full pipeline
2. Live ECG from the H10
3. Beat detection and chamber timing
4. 3D heart, four chambers, beating in sync
5. ECG trace, heart rate, chamber bars
6. Rotate, zoom, wireframe, opacity, cutaway

Cut: any finger or hand-held use of the strap (it is always worn on the chest), any printer.

Later, only when the core works and Thomas asks, in this order: heartbeat sound, shock button (a recorded bad rhythm takes over, shock returns to live), slow-mo replay of one beat, QR code that opens a replay on a phone. Leave their space (the row under the chamber lanes) empty for now.

## Decisions

Change these only if Thomas says so.

- One Python process on the Mac. FastAPI serves the viewer and one WebSocket. The page at `/` gets a `<base href="/a/<version>/">` and the frontend is mounted there too (`asset_version()`: a hash of every viewer file's size and mtime, fixed at server start), plus `Cache-Control: no-cache` on everything: Chrome's plain reload revalidates only the page, and a cached old theme.js next to a new chambers.js once broke the whole page. Run with `python -m backend --source sim`, `--source data/<file>.csv` or `--source h10`, then open http://localhost:8000. Listen on 0.0.0.0 so the big screen and phones on the same Wi-Fi can open it. The server keeps two sources ready, the strap (`live`) and a demo (`--demo`, default the first recording in `data/`, else sim), and runs one at a time; the Strap / Demo toggle in the header switches them with a viewer-to-server `{"type": "source", "name": "live" | "demo"}` message; `{"type": "rhythm", "name": "sinus" | "tachy" | "brady" | "afib" | "pvc" | "vt"}` switches the third source, the rhythm simulator, to that pattern (a takeover, below). To or from the strap a switch is a full reset: the runner starts the new source at stream time 0 with a fresh detector and monitor, the hub drops its backlog, and the viewer clears when the source is the strap. Between demo sources (recording and simulated rhythms) it is a takeover (Thomas, 2026-10-10, after a hard cut and then a handover that replaced the last 1.1 s both looked glitchy and sudden): nothing already sent is touched. The new source continues the stream time and the schedule (`PacedSource.takeover` and `anchor`); a fresh detector is primed on the hub's 8 s backlog so it knows the old stream's last beats (a beat the old pump never got to send goes out then); the new source's first sample meets the old stream's last value and that step decays over 80 ms; and the next beat lands where the old rhythm would have put it: a rhythm source replays the tail of the old beat's template from the detector's last R and eases its intervals over three beats from the old RR to its own, a recording starts at the point in its file whose next R peak is one interval after the old last beat (`peaks_of`, found once). So the trace never redraws, the lanes never lose a beat, and the rate glides. There is no handover message. Simulated and recorded sources start with `PREROLL_S` (10 s) of history: the runner gathers those packets, sends them as one samples message, runs the detector over them in one pass (`BeatDetector.prime`) and sends the beats after the samples, so the viewer swaps to the new source in a single frame; it keeps the old screen until that message arrives and clears on the stream-time jump (the strap has no history and clears at once). Never let the page play through a preroll packet by packet: that looks like fast-forward.
- The viewer is plain ES modules and Three.js. No bundler, no framework, no build step.
- It must run with no internet. Vendor Three.js and the fonts into the repo, no CDN links. For Three.js 0.186 copy `build/three.module.js` and `build/three.core.js` (the first imports the second) plus the `examples/jsm` files you use, and map `three` and `three/addons/` with an import map.
- Python 3.10 or newer, because bleakheart needs it. The Mac's built-in `python3` is 3.9; use `/opt/homebrew/bin/python3.14 -m venv .venv`. The README says how to check.
- The heart is a real model: Sketchfab "Realistic Human Heart" by neshallads, https://sketchfab.com/3d-models/realistic-human-heart-3f8072336ce94d18b3d0d055a1ece089 (22.6k triangles, free download, login needed, pick the glTF "Autoconverted" format). Thomas downloads it. Check the license file in the zip and credit author, link and license in the README. It is one textured surface, not four chamber meshes, so chambers contract by vertex displacement in a shader (see Viewer). Never build a heart out of shapes in code.

## Layout

```
backend/    app.py (FastAPI, /ws, static files), pipeline.py, sources/ (base.py, sim.py, replay.py, h10.py), tests/
frontend/   index.html, main.js, clock.js, chambers.js, heart.js, trace.js, style.css, vendor/, assets/ (heart model + heart.json)
tools/      h10_record.py (strap to CSV, no server), trim_csv.py, screenshot.mjs (headless check)
data/       ECG fixtures: CSV with header time_s,ecg_uv at 130 Hz, in microvolts
```

## The strap

Polar H10, checked facts:
- ECG over Bluetooth LE: one lead, 130 Hz, signed integer microvolts.
- It arrives in bursts: 73 samples per packet, a packet about every 0.56 s. The packet timestamp (ns) belongs to its last sample.
- It only switches on when the wet pads touch skin, and it takes one Bluetooth connection at a time. Polar apps and browser tabs using it must be closed.
- On macOS the terminal app needs Bluetooth permission (System Settings > Privacy & Security > Bluetooth). On Thomas's Mac this is already granted. Device addresses are per-Mac UUIDs, so find the strap by name ("Polar H10 ...") and never hardcode an address.
- The first 20 to 30 s after the pads touch skin are junk: samples pinned at the clip level (about plus or minus 19930 uV) and swings of several mV while the contact settles. Wait that long before trusting the trace or the beats, and tell the demo crew.
- Worn upside down, the signal is inverted. Add an `--invert` flag that flips it before the pipeline. Thomas's strap reads upright, no flag needed.
- Expect R peaks of roughly 500 uV after cleaning and a raw signal of 1.5 to 2 mV peak to peak.

Read it with `bleakheart` 0.2.0 on `bleak` 3.0.2 (these versions work together). Usage, checked against the library source:

```python
device = await BleakScanner.find_device_by_filter(
    lambda d, adv: "polar h10" in (adv.local_name or d.name or "").lower(), timeout=15)
async with BleakClient(device, disconnected_callback=on_drop) as client:
    battery = await BatteryLevel(client).read()               # percent
    pmd = PolarMeasurementData(client, ecg_queue=queue)        # an asyncio.Queue
    err, msg, _ = await pmd.start_streaming("ECG")             # err == 0 means it started
    # queue items: ("ECG", t_ns_of_last_sample, [microvolts, ...])
    await stop.wait()
    await pmd.stop_streaming("ECG")
```

- Run uvicorn with `loop="asyncio"`. bleak is built on the standard loop.
- When the strap drops, reconnect without a restart: scan again with a 1 s backoff, keep scanning forever in the server. The recorder gives up after a few scans. When streaming resumes, advance stream time by the wall-clock gap so the viewer clock stays aligned.
- Test `sources/h10.py` without a radio by swapping in a fake `BleakClient`, so bleakheart's real decoder runs. bleakheart subscribes to the control characteristic `FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8` and the data characteristic `FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8`, then writes `02 00 00 01 82 00 01 01 0E 00` to control and waits up to 10 s for a control response starting with `F0`. Answer with `F0 02 00 00 00` (the fourth byte is the error code); stop is `03 00`, answer `F0 03 00 00 00`. ECG frames on data are `00`, an 8 byte little-endian timestamp, `00`, then 3 byte signed little-endian samples. Handlers are async `(characteristic, data)`.

## Timing

This is the part that is easy to get wrong.

- Stream time is seconds since the first sample: sample index / 130. Every message uses it. Samples never get wall-clock times.
- The detector takes each packet's stream time and stamps beats in it. If stream time jumps (strap reconnect, source restart), it empties its window and warms up again. A detector that counts its own samples instead stamps every beat tens of seconds in the past after one reconnect, and the viewer shows no rate, no bars and a still heart. Test this with a jump.
- Samples arrive in bursts, so never draw or animate on arrival. The viewer buffers and plays out on a clock that runs a fixed delay behind the newest sample. Start with `DELAY_S = 1.5`, one constant.
- Viewer clock: each samples message gives `candidate = t_newest - performance.now() / 1000`. The first one sets `offset`. Later ones: snap if the difference is over 1 s (restart), otherwise move up quickly when the candidate is higher and drift down at about 5 percent when it is lower. The nudging absorbs the strap not running at exactly 130 Hz.
- Each frame, `t_display = performance.now() / 1000 + offset - DELAY_S`. The trace, the chamber lanes and the heart all draw from `t_display`, so they line up.
- Chamber activation is a pure function of `t_display` and the recent beats. A beat that arrives late then joins mid-squeeze instead of being dropped.
- Budget: a beat is known at most about 0.85 s after its R peak (0.25 s confirm wait plus one packet), and its first event is up to 0.3 s before the R peak. At 1.5 s delay that leaves about 0.3 s spare. If the heart stutters or the trace runs dry on real hardware, raise `DELAY_S`. Do not shorten the confirm wait.
- The sim and replay sources deliver exactly like the strap: 73 samples every 73/130 s, in real time, a packet when its last sample is due. Replay loops at the end of the file and stream time keeps counting.
- A viewer that connects late gets the last 8 s of samples and the last dozen beats first.

## Beats and chambers

One ECG lead times all four chambers. P wave: atria squeeze. QRS: ventricles squeeze. T wave: ventricles relax.

Targets for this recipe: on simulated ECG at 60, 90 and 140 bpm every beat is found once and none extra, worst latency under 0.9 s; on a real strap recording it matches a full-signal reference beat for beat and finds the P wave on most beats. Each packet costs about 13 to 23 ms on the Mac.

- Keep the last 8 s. On every packet run `nk.ecg_clean` then `nk.ecg_peaks` (NeuroKit2 defaults, native 130 Hz, no resampling).
- Emit a beat for each R peak that is at least 0.25 s older than the newest sample and more than 0.25 s after the last emitted beat. Start after 3 s of data and emit only beats from the last second. Older ones just seed the RR history.
- bpm is 60 / the median of the last 5 RR intervals. `rr` in the message is the interval to the previous peak.
- Chamber events are offsets in seconds from the R peak. Defaults: RA on -0.20, LA on -0.17, ventricles on -0.04, ventricles off `0.40 * sqrt(RR) - 0.04` clamped to 0.20 to 0.42. Atria squeeze for about 0.12 s. At fast rates, do not let the atria start before the previous beat's ventricles are off (push RA on later, never later than -0.10).
- Better atrial timing: `nk.ecg_delineate(clean, rpeaks, sampling_rate=130, method="dwt")`, only on packets that emit a beat. If the P onset is 0.08 to 0.32 s before the R peak, use it as RA on (LA 0.03 s later) and set `p_found` true. Otherwise keep the defaults. About 80 ms per call. It raises on flat or very short signals, so wrap it and require 4 peaks.
- Simulated source: `nk.ecg_simulate(sampling_rate=130, heart_rate=bpm, heart_rate_std=2, noise=0.02)` times 1000, rounded to integer microvolts, 120 s generated once and looped.

## Messages

One WebSocket at `/ws`, JSON, server to viewer:

```json
{"type": "status", "source": "live", "state": "streaming", "device": "Polar H10 223FD838", "fs": 130}
{"type": "samples", "source": "live", "t": 12.480, "fs": 130, "uv": [12, -8, 31]}
{"type": "beat", "source": "live", "r": 12.911, "rr": 0.83, "bpm": 72, "ra_on": -0.20, "la_on": -0.17, "v_on": -0.04, "v_off": 0.32, "p_found": true}
{"type": "signal", "source": "live", "ok": false, "reason": "pads"}
```

`t` is the stream time of the first sample in `uv`. `source` is `live`, `recorded` or `simulated`. `state` is `connecting`, `streaming` or `reconnecting`. `signal` is sent on change (and first thing to a late viewer): the only reason is `pads`, meaning no signal at all: samples pinned near 19930 uV (the pads left the skin) or a flat line, over the last 2 s. Noisy or odd signal is still signal and is never flagged (Thomas's call). Lost after 0.5 s, ok again after 1 s of signal (`SignalMonitor` in pipeline.py; `CARDIOVIEW_DEBUG=1` logs the numbers per packet). Send raw microvolts. The viewer removes baseline drift (one-pole 0.5 Hz high-pass) and scales for display (follow the recent peak, floor 200 uV).

## Viewer

- The target screen is 1920 by 1080, one dark surface with no panels: a 60 px header with a 2 px rule under it, then a stage on the left (3fr) and an instrument column on the right (2fr) split by a vertical rule. Header: the wordmark at the left and the Strap / Demo toggle at the right, nothing else. The status line (one white mono line in uppercase, written in words, centered over the tray) sits in the Heart rate box above the rhythm tray: the strap id while it streams (Polar H10 223FD838), otherwise whose recording (Thomas's recording, from the h10_ecg_<name> file name) or which simulation (Simulated bradycardia, Simulated 72 bpm) or the link state (Connecting to Polar H10, Reconnecting to the strap, Server offline, retrying). No live badge. Stage: the heart floating in a closed grid room (a floor grid under it and four wall grids whose lines meet the floor's edges, GridHelpers recolored to the theme's rule color, fading into scene fog of the stage color; the orbit is limited to inside the room and above the floor, so the camera never clips through), labels in fixed slots, and one control: an opacity slider at the bottom left. Drag orbits, scroll zooms; the R, W and C keys toggle auto-rotate, wireframe and cutaway without any on-screen chrome (plain keys only, nothing with Cmd, Ctrl or Alt held and nothing while typing in a field: Cmd+C to copy text used to cut the heart open). No footnotes on the stage. The layout fits any screen with no leftover space: the column's three instruments share the height (no reserved extras row), paddings, the numeral and the label waves scale with the viewport, and heart.js refits the camera distance on every resize so the model fills about 74 percent of the stage height and at most 60 percent of its width. Column: three ruled bands whose rules run edge to edge (the column has no side padding; each band carries the gutter): Heart rate (numeral, bpm and seconds between beats at the left; in demo the rhythm tray fills the space to the right of the numeral exactly, same height and flush right, the status line on the title row above it; a 3 by 2 grid of six equal cells separated by rules: Recording, Normal, Bradycardia, Atrial fibrillation, Extra beats, V-tach (names wrap to two lines in a cell on small screens); each rhythm cell but Recording has a small round blue ! badge inside its top-right corner, and hovering the badge opens a box under the cell with the rhythm's full name and a plain two-sentence definition, so visitors need not look it up (hover only, not focus: Chrome marks a clicked cell :focus-visible once a hotkey is pressed, which would pin the box open; screen readers get it through aria-describedby); the tachy pattern exists in the backend but has no button, Thomas wanted an even grid), ECG (title just "ECG"; the sample rate, "130 HZ", sits small in the graph's top-left corner) with a 2D / 3D tray (3D is a beat waterfall: the last 8 beats as receding ridges, newest in front, sliding back continuously timed by the next beat, scale eased both ways, new rows fading in; `?ecg=3d` opens in it), Chambers (title only, Thomas dropped "timing derived from the ECG" on 2026-10-10) with its own 2D / 3D tray (3D: the four lanes as ridges in perspective, LV in front and RA at the back, each the same 6 s window with its now at the right end, so the atria's lead shows as a step between ridges; a per-beat overlay was tried first and collapsed into two blobs because both ventricles, and both atria, move together; `?lanes=3d`). The ECG waterfall's front row sits centered in its box (Thomas, 2026-10-10: left-anchored it was badly placed). The ECG and Chambers titles with their trays sit in their own band with a rule under it, and the graph fills the rest of the box (Thomas, 2026-10-10). A dotted now line in each band with no label, aligned but never crossing the rule between them (each hides in 3D). Grid room lines at 0.60 (floor) and 0.36 (walls) opacity after Thomas asked twice for more. Numbers that match: both canvases run edge to edge of their box (no side or bottom padding below the title; Thomas, 2026-10-10: the graphs fill the box), a 6 s window from the left edge to the now line 12 px in from the right edge (`geometry()` in trace.js, shared so beats line up between the trace and the lanes), the lane letters inside each lane's top-left corner on a knock-out, trace baseline at 66 percent of its canvas height with the recent peak a tenth from the top.
- Look: Statura's Swiss structure on a medical dark palette (Thomas, 2026-10-10). Type (Thomas, 2026-10-10, two rounds: 12 px tracked mono on everything read as a terminal theme, then plain Helvetica in sentence case looked too simple): JetBrains Mono 700 (vendored from `@fontsource/jetbrains-mono` 5.2.6, weights 400, 600, 700) in uppercase with 0.08 to 0.1em tracking for the instrument titles (15 to 19 px, white), the status line (13 to 16 px), the controls (14 px; tray cells 11 to 14 px with 0.04em, wrapping to two lines when a name needs it), the names under the chamber letters (12 to 14 px) and the readouts (seconds between beats, 130 HZ, in 600). Helvetica Neue (system) for the wordmark, the numeral, the chamber letters on the heart and in the lanes, and the alert. Nothing under 11 px. Square corners, no shadows, 2 px rules between regions, segmented controls as equal cells separated by 2 px rules (the tray background shows through the gaps) with the accent fill when active, all trays right-aligned. Colors: stage #0A1115, column #0F1A1F, header #0E1A1F, text #E8F1F2, dim #7F969B, rules white at 14 to 45 percent, accent teal #2BD4BD, trace green #37E07E, one color per chamber, plainly different (Thomas, 2026-10-10: two side colors, then four related tints, were both too alike; he asked for red, green, blue and one more): RA blue #4D8BFF, RV green #7FE24B (a lime, so it never reads as the mint trace), LA red #FF4F4F, LV yellow #FFC93C, used alike by the lanes, the label sparks, the waterfall legend and the heart's glow; alert #FF5252; info blue #3B82F6 (#2563EB in cream) for the rhythm tray's ! badges only. The canvases read their colors from the `--c-*` CSS variables (theme.js), so a theme is a stylesheet swap; T switches to Statura's cream theme. Motion: the label easing only, off under prefers-reduced-motion.
- Under 760 px wide (phones, a bonus) the page becomes one scrolling column, stage first, and the camera keeps at least 34 degrees of horizontal view so the labels fit beside the heart. Under prefers-reduced-motion the lost state skips the glitch pass and tints the heart red with CSS; the glitch flashes at most twice a second.
- `heart.js` exposes `setActivation({ra, la, rv, lv})` with values from 0 to 1, plus wireframe, opacity and cutaway. Squeeze in about 0.1 s, release over about 0.2 s, with no glow or tint on the surface (Thomas, 2026-10-10: the colored glow per chamber looked bad).
- The model is one surface, so contraction is a vertex shader on the model's material (`onBeforeCompile`): uniforms for four chamber centers, radii and activations; each vertex gets a smooth weight per chamber from its distance to that center and moves toward the center by about 12 percent (ventricles) or 8 percent (atria) times the activation; a varying still carries the weights to the fragment shader, which adds nothing (the glow was removed). Chamber centers and radii live in `frontend/assets/heart.json` in the normalized model space (centered, 1.8 units tall), picked by eye with the `?debug=1` overlay (bounding box, axes, one marker per chamber) and checked with `?act=1` against `?act=0`; each chamber also has a surface `anchor` and outward `normal`. Labels sit in fixed slots that hug the heart's projected outline (RA and RV on one side, LA and LV on the other), swap sides once when the camera goes behind the heart (hysteresis at 80 to 100 degrees), ease into place with CSS, and never overlap. Leaders run from the label's real position to the anchor; a label whose normal faces away dims with a dashed leader. Under each label a small canvas draws a modeled pressure-style wave from the beat timing (atria: contraction bump then a filling rise during ventricular systole; ventricles: a dome from on to off, LV tall, RV half height), tagged WAVES: MODELED. The weight is 1 inside the radius and fades to 0 at 1.6 radii, so the chamber surface moves the full amount. Keep the model's own textures and materials, just extend them. Cutaway is a clipping plane with double-sided materials. Load with GLTFLoader (vendor it with `utils/BufferGeometryUtils.js` and `utils/SkeletonUtils.js`, which it imports).
- Lost signal: when the signal message says not ok, the strap is not streaming, the server is gone, or no samples arrive for 3 s, the body gets class `lost`: the heart stops squeezing, the WebGL frame is hidden and redrawn by `glitch.js` through a red pass with bands torn sideways, TV static and flashes over the whole stage (needs `preserveDrawingBuffer`), the stage gets a red wash, labels and the numeral dim, and a centered alert says Not connected (with the one-line fix: wet the pads, wear the strap snug) for every strap problem, or Server offline when the server is gone. There is no in-between state (Thomas): while the strap is chosen and not streaming, the page is Not connected. It is either working or not connected; there is no settling or noise message (Thomas's call). `?signal=lost` forces it for rehearsal.
- These words are part of the product: the Strap / Demo state and the Simulated label carry the honesty (Thomas dropped "measured" from the ECG title and "timing derived from the ECG" from the Chambers title on 2026-10-10; the README says the lanes are derived from the ECG). That the heart is a 3D model and the label waves are modeled is stated in the README. The status line shows the strap id only for strap data, otherwise whose recording or which simulation. No diagnosis of a live signal anywhere; rhythm names appear only on the demo's simulated rhythms (`sources/rhythm.py`: normal (sinus), tachycardia, bradycardia, atrial fibrillation, extra beats, ventricular tachycardia), in the tray beside the heart rate, hidden whenever the source is the strap; the status line then reads "Simulated <name>". This is a visualization, not a medical device.

## Milestones

- M0. `tools/h10_record.py`: connect, print battery and sample counts, save a CSV. Give it to Thomas first. His recording proves the strap path and becomes the main fixture. Record at least 90 s and trim the settling lead-in.
- M1. `--source sim` and CSV replay through the pipeline to the viewer: trace, bpm, chamber lanes, heart beating in sync, orbit controls. Tests pass.
- M2. `--source h10` with reconnect and status. Thomas tests on the Mac, including pulling the strap off and on.
- M3. Real model with the shader contraction, wireframe, opacity, cutaway, match the target screen.
- M4. Extras, on request.

## Tests

`pytest` covers: bpm within 2 of a simulated rate, every beat emitted once, every beat emitted within 0.9 s of stream time after its R peak, a stream time jump restamps beats, sources paced like the strap, `sources/h10.py` against the fake client (decode, battery, invert, reconnect), and every `data/h10_ecg_*.csv` replayed without gaps over 2 s.

## Conventions

- No em dashes anywhere: code, comments, UI text, docs, commit messages.
- UI text is short and plain.
- Keep this file current in the same commit as the change it describes, and under 200 lines.
- No code from before the hackathon exists; do not go looking for any.
- ECG is personal data. Fixtures in `data/` are team members' own recordings. Never commit a visitor's ECG, and do not write it to disk without asking. If the repo is public, ask before committing any recording.
- The README always has working setup steps and the three run commands, written for teammates on Mac, Windows and Linux.
