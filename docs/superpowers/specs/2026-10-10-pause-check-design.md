# Pause check on the visitor's report

Date 2026-10-10. Branch `gabe_rhythm_feasibility` (PR #5). Handoff item 11. A proposal: nothing is built until Thomas says yes.

## Purpose

The rhythm feasibility test (`research/rhythm/RESULTS.md`) found one condition that one strap lead at 130 Hz detects reliably: pauses over 2 s between beats. On MIT-BIH, resampled to the strap's 130 Hz integer microvolts, it caught 88.6% of the 88 stretches that hold a pause and left 99.4% of the other 10 s stretches unflagged. AF, extra beats and the rate cutoffs failed. This spec puts that one result on the session report, so the judges see the research feed the product: the report always shows the check and what it found.

Decided with the user on 2026-10-10:
- It is mainly for the judges (Hugging Face track): the report always shows the check and its result, even when nothing is found.
- Two figures in the numbers box and a mark on the strip for each pause. Not a separate "rhythm check" box, which would put condition names on a visitor's report, and not strip marks alone, which the cloud copy cannot show.
- The demo report shows one simulated pause, so the mark can be seen without waiting for a real one.
- No condition names anywhere, and nothing on the live view or in the chat.

## Why this needs Thomas

CLAUDE.md today says the analysis has "no verdicts, no reference ranges", there is "no diagnosis of a live signal anywhere", and the report's footer says it "does not diagnose anything". A count of gaps over a fixed 2 s cutoff would be the first rhythm finding a visitor sees. It is a measurement against a threshold, not a diagnosis, but it changes rules Thomas set, so it waits for his yes. If he says yes, CLAUDE.md's "Saved sessions" section changes in the same commit as the code.

## The rule, exactly as scored

- Stretches: full 10 s windows from the start of each of rest (30 s), breathe (40 s) and recover (30 s), so 10 for a full session and fewer for one that ended early. A partial window at a step's end is left out. Get ready (the pads still settling) and squats (motion) are not checked.
- In each stretch: `research.rhythm.detector.find_peaks` (NeuroKit2 clean and peaks, no artifact correction) on that stretch's microvolts at 130 Hz, then `rr_features`. A stretch with fewer than 4 beats gets no features and counts as not checked, as in the test.
- A stretch has a pause when its `max_rr` is over 2.0 s. An RR counts only when both of its beats are inside the stretch (`labels.rr_windows`), so a pause across a stretch edge is not counted, as in the test.
- Not the summary's own beats: `analysis.find_beats` corrects artifacts, which can put a beat into a gap, and it marks every RR over 2.0 s unusable. The check leaves the other sections alone.
- Strap guard. This is not part of the scored rule, and it only removes stretches: a stretch with a clipped sample (19000 uV or more, `CLIP_UV`) or a stream gap (`GAP_S`) counts as not checked. A lifted pad or a dropped packet makes a fake pause, and the test's clinical recordings had neither.

## Output

A new `pauses` section in the summary:

```json
"pauses": {"ok": true, "threshold_s": 2.0, "stretches": 10, "checked": 9, "longest_s": 1.31,
           "found": [{"t": 47.32, "s": 2.41}]}
```

- `stretches`: the windows in the checked steps. `checked`: those with features and no clipping or gap.
- `longest_s`: the longest RR counted in any checked stretch (both beats inside it).
- `found`: one entry per counted RR over 2.0 s, with `t` its first beat and `s` its length, in seconds from the session start like the step markers.
- When `checked` is 0: `{"ok": false, "reason": "No 10 s stretch of rest, breathing or recovery was clean enough to check."}`.
- Summaries saved before this change have no `pauses`, and the page shows `--` for them. An export (the live buffer saved as a report) has no steps to check, so its page keeps today's four figures.

## The report

In Thomas's `frontend/summary.js`. The look stays his.

- Numbers box: `stats()` goes from 4 figures to 6, in a 3 by 2 grid: "pauses over 2 s" (the count, usually 0) and "longest gap" (seconds, one decimal). Both show `--` when the section is missing or not ok. The band may need a few more pixels; a screenshot decides.
- Strips: `stripRow()` marks each found pause the way it marks a step: a bracket from the pause's first beat to its second, with the length above it ("2.4 S"), in the label color.
- Footer, after "A visualization, not a medical device. It does not diagnose anything." and not on an export: "Pauses are checked with the one rhythm rule that passed CardioView's 130 Hz test: on MIT-BIH it caught 88.6% of pauses over 2 s and left 99.4% of other stretches clear." It links to the Hugging Face card once that is published, and to `research/rhythm/RESULTS.md` on GitHub until then.
- Only when a pause is found, one more footer line: "A gap like this can also come from the strap shifting. If you have felt faint or dizzy, show this report to a doctor." Thomas approves the wording.
- The cloud copy has no strips, so it shows the figures and the footer. It picks up the new page with the next `python tools/sessions.py deploy`.

## The demo

`/s/demo` and its ECG both come from `synth_session(seed=1)`. A new parameter, `pause_at` (seconds into the session, off by default), makes the gap after the first beat past that time 2.4 s long. The demo passes 110 s: 15 s into recovery, in the middle of its second stretch and away from an edge. So the demo report shows one pause and a marked strip, still labelled simulated data. Tests that use the default keep their known answers.

## Code

- `backend/analysis.py`: `pauses(t, uv, steps)` beside the other sections, calling `research.rhythm.detector` directly, so the report runs the very function the test scored. This needs PR #5 merged first. If Thomas would rather keep `research/` out of the booth, `find_peaks` and `rr_features` move to `backend/` and the research imports them from there.
- `backend/synth.py`: `pause_at`; `backend/app.py`: the demo passes it in both places it builds the demo session.
- `frontend/summary.js` and `summary.css`: the two figures, the grid's third row, the marks and the footer lines.
- CLAUDE.md: the `research/` Layout line says `detector.py` also runs the report's pause check, and "Saved sessions" names the new figures and marks.

## Testing

- Synthetic sessions with known answers: no pause gives 0 found and 10 checked; a 2.4 s pause in rest is found once, at the right time and length; the same pause in squats is not counted; a clipped stretch is not checked; a session that ended during breathing has only rest's 3 stretches (the analysis gets finished steps only).
- Parity: on the same samples, the section's decision for each stretch equals `detector.features(...)["max_rr"] > 2.0`.
- The demo summary has exactly one pause, in recovery.
- The real strap: run the check over every `data/h10_ecg_*.csv` in 10 s stretches and report how many were checked. These are healthy wearers, so any pause found there is a false alarm, and it blocks showing the check until the bar is raised (see Risks).
- Screenshots of `/s/demo` at 1920 by 1080 (`?screen=1&embed=1`), at phone width and in print (`print=1`), looked at before calling it done.

## Out of scope

The live view, the chat, AF, extra beats, the rate cutoffs, pauses over 3 s as their own figure, and any change to the other sections.

## Risks

- False pauses on healthy visitors. The test left 99.4% of stretches unflagged (95% range 99.2% to 99.6%). If a visitor's 10 stretches failed independently at that rate, about 6% of sessions (4% to 8%), roughly 1 in 17, would show a pause that is not there. The test's other stretches came from MIT-BIH, ambulatory recordings of patients, so healthy visitors at rest may do better, and a strap moving may do worse. The only strap check so far is 0 flags in 8 stretches of Thomas's recordings, too few to say. If the recordings check under Testing or the first real sessions show false pauses, raise the bar before showing it (for example, a pause only when the gap holds no beat a lower threshold would find).
- Pauses missed at an edge. A pause counts only inside one stretch, as in the test. A 2.4 s pause straddles a 10 s edge about a quarter of the time (2.4 in 10), so the report would catch roughly two thirds of real single pauses, not 88.6%. Overlapping stretches would fix that, but they double the stretches and with them the false pauses above, and they are not what was scored.
- The test never saw the strap's own lead or a visitor moving. The strap guard and skipping squats lower that risk, and the found-pause footer line says a gap can come from the strap.
