# Rhythm feasibility test: which conditions survive one strap lead at 130 Hz

Date 2026-10-10, revised twice the same day: a lightweight detector replaces the fine-tuned neural network of the first version, and the Hugging Face Hub replaces Databricks. Branch `gabe_rhythm_feasibility` (off main), local commits only (not pushed). Handoff item 10; it gates item 11 (condition flags for visitors).

## Purpose

CardioView's summary shows measurements only. Before any condition name may reach a visitor, this test answers, per condition: can a lightweight detector, small enough to run inside the backend on Render, detect it reliably from one lead sampled the way the Polar H10 samples it (130 Hz, integer microvolts)? A condition can be shown later only if it passes here. Its two fitted models and their results are published on the Hugging Face Hub, beside the Kokoro voice coach in the Hugging Face sponsor track.

Decided with the user on 2026-10-10:
- A lightweight detector: beat timing, a few rhythm features and at most two tiny logistic models stored as JSON. No neural network: the backend is hosted on Render, where torch and a 370 MB model would be slow and large. Fine-tuning ECGFounder was the first design and is dropped.
- Flutter, first-degree AV block, long QT and WPW are not attempted.
- One fixed split for the two models, the pass bar below, the code in `research/rhythm/` with its own environment (no torch).
- No Databricks: the results go to `RESULTS.md`, and the two models with their results are published on the Hugging Face Hub.

## The detector (what item 11 would run)

- Input: a stretch of the recording in integer microvolts, at its sampling rate (130 Hz for the strap).
- Beats: `nk.ecg_clean`, then `nk.ecg_peaks` without artifact correction. `backend/analysis.find_beats` corrects artifacts, which moves early beats back into line: that would hide extra beats and smooth AF, so the detector keeps the uncorrected peaks.
- Features from the RR intervals (seconds) and the beats:
  - `bpm`: 60 over the median RR.
  - `max_rr`: the longest RR.
  - `nrmssd`: the RMS of successive RR differences over the mean RR.
  - `irregular`: the share of successive RR differences larger than 15% of the median RR.
  - `premature`: how many beats have an RR under 85% of the median RR followed by an RR over 110% of it (an early beat and its compensating pause).
  - `odd_shape`: one minus the lowest correlation of a beat (from 100 ms before to 100 ms after its R peak) with the median beat.
- A stretch with fewer than 4 beats gets no features: it is flagged for nothing and counted.
- AF: logistic regression on `nrmssd`, `irregular` and `premature`.
- Extra beats: logistic regression on `premature`, `odd_shape` and `nrmssd`.
- Slow rate: `bpm` under 60. Fast rate: `bpm` over 100. Pauses: `max_rr` over 2.0 s (over 3.0 s reported apart). No model.
- The models are fitted with numpy (L2-regularized logistic regression on standardized features) and saved as JSON: feature names, means, scales, weights, bias and threshold. Running them needs numpy only.

## Conditions and data

| Condition | Judged by | Tested on | Outside test |
|---|---|---|---|
| Atrial fibrillation | model | PTB-XL `AFIB`: folds 1 to 8 fit, 9 sets the threshold, 10 tests | PhysioNet 2017 (A against N and O) |
| Extra beats | model | PTB-XL `PVC`, `PAC`, `BIGU` or `TRIGU`: the same folds | MIT-BIH (windows with an SVEB or VEB beat) |
| Slow rate | `bpm` under 60 | all of PTB-XL against `SBRAD` | none |
| Fast rate | `bpm` over 100 | all of PTB-XL against `STACH` | none |
| Pauses | `max_rr` over 2.0 s | all of MIT-BIH against its annotated beats | none |

Not attempted: flutter, first-degree AV block, long QT and WPW. They depend on wave timing or shape (flutter waves, the PR and QT intervals, a delta wave) that 130 Hz blurs and no simple rule reads reliably; they stay off item 11.

- PTB-XL 1.0.3: lead I, 10 s at 500 Hz (`records500`), labels from `scp_codes` (a code counts at any likelihood, as in the PTB-XL benchmark). Folds by `strat_fold`; a patient never spans two folds. Fixed cutoffs need no fitting, so their conditions are judged on every record.
- PhysioNet/CinC 2017 training set: one lead, 300 Hz, 9 to 61 s. A recording is one stretch. Positives `A`, negatives `N` and `O`; noisy `~` recordings are reported apart.
- MIT-BIH Arrhythmia: lead MLII, 360 Hz, 48 records, 10 s windows. The paced records (102, 104, 107, 217) are left out.
  - Extra beats: positive with at least one SVEB (`A`, `a`, `J`, `S`) or VEB (`V`, `E`) beat, negative with only AAMI N beats (`N`, `L`, `R`, `e`, `j`); windows with an `F` or `Q` beat, or inside an AF or flutter episode, are left out.
  - Pauses: a window has one when an annotated RR ending in it is over 2.0 s.
- Thomas's recordings `data/h10_ecg_*.csv` (130 Hz, the real strap), in 10 s windows: no labels; every flag raised on them counts as a false alarm on a healthy wearer.
- Downloads go to `research/rhythm/data/` (git-ignored). Nothing downloaded is committed.

## The two versions of every stretch

- Native: the dataset's own rate (500, 300 or 360 Hz), in microvolts.
- Strap: resampled to 130 Hz with `scipy.signal.resample_poly` (its FIR filter is the anti-alias filter) and rounded to integer microvolts, as the strap delivers it.
- Both versions go through the same detector code, and the two models are fitted per version. The H10's own filtering, noise and electrode placement are not modelled; the real-strap check covers part of that.

## Scoring and the pass bar (fixed before any run)

- Model conditions: each threshold is set on PTB-XL fold 9 so that its specificity there is 0.98, then applied to fold 10 and to the outside set.
- Fixed-cutoff conditions have no threshold to fit.
- With 95% bootstrap intervals (2,000 resamples):
  - Pass: the lower bound of specificity is at least 0.97 and sensitivity is at least 0.80, on the test set and on the outside set where there is one.
  - Not enough data: fewer than 50 positive cases in the test set.
  - Fail: everything else.
- Every verdict is shown next to the native version's numbers: a condition that fails on both is limited by the single lead or the detector, not by 130 Hz.
- Also reported: specificity on PTB-XL `NORM` records alone, the flags raised on Thomas's recordings, and how many stretches had too few beats.

## Hugging Face Hub

- A public model repo under the user's Hugging Face account, `cardioview-rhythm-detector`, holding `af.json` and `extra_beats.json` (both fitted on the strap version) and a model card (`README.md`) generated from the results.
- The card carries the pass/fail table, the pass bar, how the features are computed, the data and their licenses (PTB-XL: CC BY 4.0; PhysioNet/CinC 2017 and MIT-BIH: Open Data Commons Attribution 1.0) and two plain statements: this is not a medical device, and CardioView shows a visitor only the conditions that pass.
- `publish.py` uploads with `huggingface_hub` and a write token `HF_TOKEN` in the repo-root `.env` (git-ignored, read with `backend/env.py`). Publishing is public, so it runs only when the user says so.

## Code and environment

```
research/rhythm/
  README.md            set up, download, run, read the verdict
  requirements.txt     wfdb and huggingface_hub, plus the booth's neurokit2, numpy, scipy, pandas (no torch)
  signals.py           resampling, the strap version, windows
  labels.py            labels and splits for PTB-XL, PhysioNet 2017 and MIT-BIH
  scoring.py           AUROC, thresholds, bootstrap intervals, verdicts
  detector.py          uncorrected beats, the six features, logistic fit and predict, JSON save and load
  download.py          the three datasets from PhysioNet into data/
  prepare.py           features for every stretch in both versions, cached as CSV
  evaluate.py          fits the two models per version, applies the pass bar, writes RESULTS.md and the model files
  publish.py           the model card and the upload to the Hugging Face Hub
  models/              af.json and extra_beats.json, fitted on the strap version (item 11 loads them)
  tests/               known-answer tests for signals, labels, scoring and the detector
  RESULTS.md           the committed outcome
```

- `.venv-research` (Python 3.12) holds wfdb and huggingface_hub, so the booth's `requirements.txt` gains nothing.
- `signals.py`, `labels.py`, `scoring.py` and `detector.py` import only what the booth already has (numpy, scipy, pandas, neurokit2), so their tests run with the main suite in `.venv` (`pytest.ini` gains the path) and item 11 can call the detector from the backend.
- CLAUDE.md gains a short section and stays under 200 lines; the README points to `research/rhythm/README.md`.

## Testing

- `signals.py`, `labels.py`, `scoring.py`: known-answer tests (the strap keeps a 10 Hz wave and loses a 100 Hz one; a PTB-XL row with `PAC` is extra beats; a MIT-BIH window with an `F` beat is left out; a perfect separator passes; 49 positives give not enough data).
- `detector.py`: features on RR series with known answers (a steady rhythm has no premature beat and an `nrmssd` near 0; one early beat with its pause counts once; a random rhythm is irregular); beats found on `nk.ecg_simulate` at 130 Hz; one odd-shaped beat raises `odd_shape`; fewer than 4 beats give no features; a fitted model separates separable data, and its JSON copy predicts the same.
- The pipeline end to end on a few records before the full run.

## Out of scope

- Showing anything to visitors (item 11). This test only produces verdicts and the two model files.
- Neural networks, including the ECGFounder fine-tuning of the first design.
- Flutter, first-degree AV block, long QT and WPW.
- Real strap recordings with known conditions: none exist.

## Risks

- Publishing is public: the card must carry the verdicts and the not-a-medical-device line, and nothing is uploaded without the user's go-ahead.
- PTB-XL lead I is not the strap's lead, whose electrodes sit lower on the chest. The real-strap check measures only false alarms, so a pass here is necessary, not sufficient, for showing a flag.
- A 10 s stretch holds about 8 to 20 beats, which limits AF and extra-beat detection. A visitor session has 30 s of rest, so these numbers are conservative.
