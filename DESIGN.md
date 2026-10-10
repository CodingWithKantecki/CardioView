---
name: CardioView
description: A live ECG drives a 3D heart, beat by beat, on one dark surface.
colors:
  trace-green: "#43E0A0"
  venous-blue: "#5B9BFF"
  arterial-rose: "#FF5C83"
  alert-red: "#E5344E"
  alert-text: "#FF6B8B"
  ink: "#070A12"
  hairline: "rgba(232, 236, 243, 0.10)"
  readout-white: "#E8ECF3"
  instrument-gray: "#7F8AA0"
  caption-gray: "#6F7A94"
typography:
  display:
    fontFamily: "IBM Plex Sans Condensed, IBM Plex Sans, system-ui, sans-serif"
    fontSize: "clamp(88px, 13.5vh, 150px)"
    fontWeight: 700
    lineHeight: 0.9
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "IBM Plex Sans Condensed, IBM Plex Sans, system-ui, sans-serif"
    fontSize: "clamp(28px, 3.4vh, 36px)"
    fontWeight: 700
    lineHeight: 1.05
  title:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    letterSpacing: "-0.01em"
  alert:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.3
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
spacing:
  xs: "8px"
  sm: "12px"
  md: "24px"
  gutter: "40px"
  header: "64px"
components:
  header-device:
    textColor: "{colors.caption-gray}"
    typography: "{typography.mono}"
  instrument-title:
    textColor: "{colors.instrument-gray}"
    typography: "{typography.body}"
  instrument-subtitle:
    textColor: "{colors.caption-gray}"
    typography: "{typography.label}"
  text-toggle:
    textColor: "{colors.caption-gray}"
    typography: "{typography.label}"
    padding: "0 0 2px"
  text-toggle-active:
    textColor: "{colors.readout-white}"
    typography: "{typography.label}"
    padding: "0 0 2px"
  rate-readout:
    textColor: "{colors.readout-white}"
    typography: "{typography.display}"
  chamber-label:
    textColor: "{colors.readout-white}"
    typography: "{typography.headline}"
  lost-alert:
    textColor: "{colors.alert-text}"
    typography: "{typography.alert}"
    padding: "36px 72px"
---

# Design System: CardioView

## Overview

**Creative North Star: "The Telemetry Console"**

CardioView is a mission-control instrument panel for one human heart, stripped to the panel itself. There are no cards, pills, chips or buttons: one ink-black surface, a hairline under the header and a hairline between the stage and the instrument column, and hairlines between the instruments. Captions are sentence case, small and gray. Nothing in the chrome moves or glows. All the energy comes from the signal: the green ECG sweeping to the dotted now line, the blue and rose activation curves rising under it, the pen dots at their leading edge, the heart squeezing with a faint colored glow and a soft rose halo behind it.

The mood is precise, calm and live. It is built for a 1920 by 1080 screen read from a few meters, so the things that must carry the room are huge: the heart, the condensed heart-rate numeral (up to 150 px) and the condensed chamber letters. Everything else is written for the person standing at the screen at 13 to 15 px. The console still shows its work: "measured at 130 Hz" sits beside ECG, "timing derived from the ECG" beside Chambers, and one dotted now line runs through both so the timing chain is visible as well as stated.

The console has one loud state. When the signal is lost, the stage turns red, the heart glitches with torn bands and static, and a centered alert says in plain words what is wrong and what to do. That is the only time the chrome raises its voice, and it says so because a heart stopped being readable.

**Key Characteristics:**
- One ink surface, hairlines only; no fills, borders, radii or shadows.
- Three signal hues with fixed meaning: green for the measured ECG, blue for the right heart, rose for the left heart.
- Sentence-case captions in two grays; condensed numerals for what must read from across the room.
- One dotted now line shared by the trace and the chamber lanes.
- Glow belongs only to the signal; red belongs only to a lost signal.

## Colors

Near-black ink and two grays carry the chrome; three hues carry the physiology; one red carries the lost state.

### Primary
- **Trace Green** (`trace-green`): The measured ECG only. The 2D sweep with its soft glow, the 3D waterfall ridges, nothing else.

### Secondary
- **Venous Blue** (`venous-blue`): The right heart (RA, RV): activation curves, pen dots, label sparks, shader glow and the blue rim light on the model.

### Tertiary
- **Arterial Rose** (`arterial-rose`): The left heart (LA, LV): the same roles on the left side, plus the faint radial halo behind the heart at 7 percent.
- **Alert Red** (`alert-red`): The lost state only: the inset stage wash, the glitch tint and the static. **Alert Text** (`alert-text`) is the brighter red the alert title uses so it stays legible over the wash.

### Neutral
- **Ink** (`ink`): The single surface behind everything, including the waterfall fills that hide older beats.
- **Hairline** (`hairline`): White at 10 percent. Every divider: under the header, between stage and column, between instruments, and the lane baselines.
- **Readout White** (`readout-white`): The wordmark, the numeral, the chamber letters, the active toggle, leaders at 40 percent and the now line at 45 percent.
- **Instrument Gray** (`instrument-gray`): Instrument titles, the bpm unit, seconds between beats, chamber full names, lane names and the slider label.
- **Caption Gray** (`caption-gray`): The smallest text: the device line, instrument subtitles and the inactive toggle. It is the floor, 4.6:1 on ink; never go dimmer.

### Named Rules
**The Signal Owns Color Rule.** Hue is only for physiology. Green is the measured ECG, blue is the right heart and rose is the left heart. No caption, control or divider gets a signal hue.

**The Right Blue, Left Rose Rule.** RA and RV are always blue and LA and LV are always rose, everywhere: lanes, sparks, shader glow and anything added later.

**The Red Means Lost Rule.** Red appears only while the signal is lost, and then over the whole stage. It never marks a button, a number or a normal state.

## Typography

**Display Font:** IBM Plex Sans Condensed (with IBM Plex Sans, system-ui)
**Body Font:** IBM Plex Sans (with system-ui)
**Mono Font:** IBM Plex Mono (with ui-monospace, Menlo), only for the device id

**Character:** Plex is engineered, not friendly. The condensed cut packs a numeral that reads from across a booth into a narrow column; the regular cut in sentence case keeps every caption quiet. Mono is reserved for the one string that is literally an identifier.

### Hierarchy
- **Display** (Condensed 700, clamp 88 to 150 px by viewport height, 0.9): The heart-rate numeral only. Tabular numerals so it does not jitter.
- **Headline** (Condensed 700, clamp 28 to 36 px, 1.05): The chamber letters RA, LA, RV, LV on the stage.
- **Alert** (Sans 600, 28 px): The lost-state title.
- **Title** (Sans 600, 22 px): The CardioView wordmark.
- **Body** (Sans 400, 15 px, 1.3): Instrument titles, chamber full names, seconds between beats, lane names.
- **Label** (Sans 400, 13 px): Instrument subtitles, the 2D / 3D toggle, the "now" tag, the slider label at 14 px.
- **Mono** (Mono 400, 13 px): The strap id in the header.

### Named Rules
**The Sentence Case Rule.** Every caption is sentence case with no tracking and no uppercase stencils. Emphasis comes from size and the two grays, never from case.

**The Two Sizes From Three Metres Rule.** From across the booth only the numeral, the chamber letters and the traces need to read. Captions are written for someone at the screen, so they stay small and never crowd the numeral.

## Layout

A fixed full-viewport console for 1920 by 1080 with no page scroll. A 64 px header holds the wordmark and one dim line, with a hairline under it. Below, a two-column grid splits 3fr to 2fr: the stage on the left (the heart on bare ink with a soft rose halo, labels in fixed slots beside it, the opacity slider bottom-left) and the instrument column on the right, separated by a vertical hairline. The column uses a 40 px gutter and stacks Heart rate (auto), ECG (1.15fr), Chambers (1fr) and a reserved empty 110 px row, each instrument padded 24 px above and 22 px below with a hairline between.

The trace and the lanes share geometry exactly: a 48 px left gutter for lane names, a 6 s window, and now at 92 percent of the drawable width. One dotted now line is positioned in the column over both canvases from those numbers (in 3D mode it spans only the lanes, since the waterfall has no time axis). The trace baseline sits at 64 percent of its canvas height.

Under 1500 px wide the gutter drops to 28 px and the label sparks shrink. Under 760 px wide (phones on the same Wi-Fi, a bonus, not a target) the page becomes one scrolling column: the stage at 72 percent of the viewport height with a hairline under it, then the three instruments at fixed heights; the camera widens so the heart leaves room for its labels.

## Elevation & Depth

The system is flat and tonal. There is one surface, and structure comes from 10 percent hairlines alone. No element has a fill, a border radius or a box shadow, and nothing lifts on hover. The only luminous effects belong to the signal: a 5 px soft glow on the ECG line, an 8 px glow on each lane's pen dot, the additive per-chamber glow in the heart shader, the blue rim light on the model, and the 7 percent rose halo behind the heart. The lost state adds one inset red wash across the stage and a red glitch pass over the heart.

### Named Rules
**The Glow Is Signal Rule.** Glow is only for live physiological signal. Captions, controls and dividers never glow, cast shadows or lift. If something glows, it is because a heart did something; if something is red, it is because the heart could not be read.

## Shapes

There are almost no shapes. Dividers are 1 px hairlines. The now line is a 2 px dotted rule. Leaders are 1.5 px lines ending in a 3 px dot; a chamber facing away gets a 3 on 6 off dash. The slider is a 1.5 px track with a 12 px round thumb ringed in ink. The toggle's active state is a 1.5 px underline. Activation curves and the ECG are rounded strokes with a filled area beneath. The only radius anywhere is the circle of a dot or a thumb; rectangles never get corners.

## Components

**Intent: nearly invisible, precise.** Controls recede into captions and hairlines; the heart and the readings lead. Anything that must be found by touch or sight is a thin, exact mark, not a button.

### Header
- **Wordmark:** "CardioView" at 22 px semibold.
- **Device line:** one Caption Gray mono string: the strap id while streaming, otherwise the recording or simulation name or the link state ("Connecting to Polar H10", "Reconnecting to the strap", "Server offline, retrying"). Empty when there is nothing to say.

### Instrument
- **Structure:** a section with a 15 px Instrument Gray title, an optional 13 px Caption Gray subtitle beside it, and a canvas or readout below. Hairline between instruments, none after the last.
- **Heart rate:** the condensed numeral with "bpm" at 22 px Instrument Gray on its baseline, then "0.86 s between beats" at 15 px.

### Text Toggle (2D / 3D)
- **Style:** two 13 px words at the right end of the ECG title, Caption Gray, no box.
- **Hover:** Readout White. **Active:** Readout White with a 1.5 px underline. **Focus:** a 1 px Instrument Gray outline at 4 px offset.

### Opacity Slider
- **Style:** "Opacity" at 14 px Instrument Gray, then a 160 px range input with a 1.5 px track at 22 percent white and a 12 px Readout White thumb with a 4 px ink ring.
- **Focus:** a 1 px Instrument Gray outline at 6 px offset. The other views are a tray at the bottom right of the stage: Rotate, Wire, Cut and Reset as mono pills with the accent fill when on, mirroring the R, W, C and 0 keys. All off by default.

### ECG Trace (signature)
A 2 px Trace Green rounded line with a 5 px glow over a 7 percent grid, sweeping right to the now line. In 3D the last eight beats stack as a waterfall: the newest in front, older ones receding up and back, each ridge filled with ink so it hides what is behind it, the front ridge lit green beneath.

### Chamber Lanes (signature)
Four rows, RA, LA, RV, LV, each a hairline baseline with the chamber's activation curve drawn above it: a gradient fill that brightens toward now, a 1.5 px stroke, and a glowing pen dot at the leading edge. A faint tick on every beat crosses all four lanes.

### Chamber Labels (signature)
A condensed letter over a 15 px gray full name over a 150 by 26 px spark that plays the modeled wave in the chamber's color. A 1.5 px leader at 40 percent runs to a surface dot. Labels ease 0.35 s between fixed slots beside the heart; one facing away fades to 40 percent with a dashed leader. Easing is off under reduced motion.

### Lost Alert (signature)
Centered on the stage over a radial ink fade: a 28 px Alert Text title ("No signal from the strap") and a 15 px Instrument Gray hint ("Wet the pads and wear it snug on the chest"). Around it the stage gets a 160 px inset red wash, the labels and leaders fade to 30 percent, the numeral to 35 percent, the trace to 50 percent, and the heart is redrawn through the glitch pass with torn bands, static and a flash at most twice a second. Under reduced motion the heart stays put, tinted red, with the wash and the alert only.

## Do's and Don'ts

### Do:
- **Do** keep hue reserved for signal: Trace Green for measured ECG, Venous Blue for RA and RV, Arterial Rose for LA and LV.
- **Do** separate everything with 10 percent hairlines and nothing else.
- **Do** write captions in sentence case at 13 to 15 px in the two grays, with Caption Gray as the dimmest text allowed.
- **Do** keep "measured" beside the ECG and "derived from the ECG" beside the chambers.
- **Do** share the 48 px gutter, the 6 s window and now at 92 percent across every time-based canvas, and draw one now line for all of them.
- **Do** make a control a thin, exact mark: an underline, a hairline track, a word.

### Don't:
- **Don't** add panels, cards, pills, chips, borders, radii or shadows. The surface is one piece of ink.
- **Don't** use uppercase, tracking or mono for captions. Mono is for the device id only.
- **Don't** use red for anything but the lost state, and never for a number.
- **Don't** swap the side colors. Right is blue and left is rose, everywhere.
- **Don't** put rhythm names, diagnoses or alarm language anywhere on screen. The lost alert says what to do, not what is wrong with the heart.
- **Don't** fill the reserved empty row under the chamber lanes until an extra is requested.
