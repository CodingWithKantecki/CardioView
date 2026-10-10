# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, weighted equally:

- **The wearer.** A person wearing a Polar H10 chest strap at a hackathon booth. They watch a 3D heart on a big screen beat in time with their own heart, then do squats or breathe slowly and watch the rate and timing change.
- **Onlookers and judges.** People standing a few meters from the big screen (KnightHacks IX judges and passersby). They need to see at a glance that the heart is live, real and in sync, and judges want to see the depth of the signal pipeline behind it.

The demo crew (the team) runs the Mac, straps people in, and explains the 20 to 30 s settling period.

## Product Purpose

CardioView turns one live ECG lead into a four-chamber 3D heart that squeezes chamber by chamber on every real beat, next to the measured trace, the heart rate and the derived chamber timing.

Success is winning on technical depth: judges should come away convinced the signal is real, the beat detection is accurate, and the chamber timing is genuinely derived from the ECG (P wave, QRS, T wave), not a canned animation. The beating heart is the hook; the visible rigor is the win.

## Positioning

A real person's measured ECG drives a real anatomical model in real time, with honest labels separating what is measured (the ECG), what is derived (chamber timing), and what is modeled (anatomy, pressure-style waves). A neighboring "animated heart" demo cannot claim that chain from strap to shader.

## Operating Context

- One Python process on a Mac serves the viewer at http://localhost:8000 and over local Wi-Fi to the big screen and phones. Must run with no internet.
- Target screen: 1920 by 1080, viewed from about 3 m. Phones on the same Wi-Fi may open it, but they are a bonus, not a design target.
- Ritual: wet pads, strap on, wait 20 to 30 s for the contact to settle, heart appears, wearer exercises or breathes slowly, rate visibly changes. Must hold up under motion noise and rates from about 45 to 180 bpm.
- Sources: live strap (`h10`), recorded CSV, or simulated ECG. The strap can drop and reconnect mid-demo.

## Capabilities and Constraints

- Live ECG trace (2D sweep or a 3D beat waterfall of the last beats), heart rate, four chamber lanes sharing one now line with the trace, and a 3D heart (RA, LA, RV, LV) with orbit, zoom, an opacity slider, and a view tray (Rotate, Wire, Cut, Reset, also the R, W, C and 0 keys) for auto-rotate, wireframe, cutaway and reset view.
- A signal monitor on the server reports pads off, noise or no beats. The viewer then shows a lost state: the heart stops, the stage glitches red, and a plain-words alert says what is wrong and what to do. The first half minute on a live strap reads "Settling in".
- The header shows the strap id only for strap data; otherwise the recording name or "Simulated <bpm> bpm", or the link state.
- Plain ES modules and Three.js, no bundler, no framework, no build step, everything vendored.
- The heart is the Sketchfab "Realistic Human Heart" model by neshallads (CC-BY-4.0); chambers contract by vertex shader. Never a heart built from shapes in code.
- Planned extras, only on request: heartbeat sound, shock button, slow-mo replay of one beat, QR replay on a phone. Their space (the row under the chamber lanes) stays empty for now.
- Cut: finger or hand-held strap use, any printer.

## Brand Commitments

- Name: CardioView.
- Required provenance words on screen: "measured" on the ECG and "derived from the ECG" on the chambers. That the heart is a 3D model and the label waves are modeled is stated in the README.
- UI text is short, plain and sentence case. No em dashes anywhere.
- No diagnosis or rhythm names anywhere. This is a visualization, not a medical device.
- Model credit (author, link, license) stays in the README.

## Evidence on Hand

- `data/h10_ecg_thomas.csv`: an 84 s real Polar H10 recording from a team member, the main fixture.
- Simulated ECG at any rate via NeuroKit2.
- Pytest suite covering beat detection, latency, timing jumps, source pacing and the strap decoder.
- No visitor recordings may be committed or written to disk without asking. No testimonials, accuracy benchmarks against clinical equipment, or press exist; do not invent them.

## Product Principles

1. **Show the chain of evidence.** Every element says whether it is measured, derived or modeled, and the timing visibly lines up across trace, lanes and heart.
2. **Live first, honest always.** Never fake liveness: the header, the lost state and the provenance words tell the truth about the source, the link and the signal.
3. **Readable across the booth.** The heart, the rate and the beat-to-beat sync must land from 3 m in a few seconds.
4. **Survive the demo.** Motion noise, reconnects and wide rate swings are normal conditions, not edge cases.

## Accessibility & Inclusion

Key numbers, labels and status must be legible from about 3 m on a 1920 by 1080 screen. Phone use should not break, but is not optimized for.
