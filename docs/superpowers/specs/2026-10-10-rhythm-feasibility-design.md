# Rhythm feasibility test: which conditions survive one strap lead at 130 Hz

Date 2026-10-10. Branch `gabe_backend_evaluation`, local commits only (not pushed). Handoff item 10; it gates item 11 (condition flags for visitors).

## Purpose

CardioView's summary shows measurements only. Before any condition name may reach a visitor, this test answers, per condition: can a model fine-tuned on one lead, sampled the way the Polar H10 samples it (130 Hz, integer microvolts), detect it reliably? A condition can be shown later only if it passes here. The test is also the Hugging Face (ECGFounder) and Databricks (MLflow) sponsor-track entry.

Decided with the user on 2026-10-10: fine-tune at 130 Hz (not zero-shot, not hand-built features), one fixed split (2 training runs), the pass bar below, Databricks Free Edition for MLflow and the verdict notebook, the code in `research/rhythm/` with its own environment.

## Conditions and data

| Condition | Judged by | Trained and tested on | Outside test |
|---|---|---|---|
| Atrial fibrillation | model | PTB-XL `AFIB` | PhysioNet 2017 (A against N and O) |
| Atrial flutter | model | PTB-XL `AFLT` | none |
| Extra beats | model | PTB-XL `PVC`, `PAC`, `BIGU` or `TRIGU` | MIT-BIH (windows with an SVEB or VEB beat) |
| First-degree AV block | model | PTB-XL `1AVB` | none |
| Long QT | model | PTB-XL `LNGQT` | none |
| WPW | model | PTB-XL `WPW` | none |
| Slow rate, fast rate | beat detector | PTB-XL `SBRAD` (under 60 bpm), `STACH` (over 100 bpm), fold 10 | MIT-BIH annotated beats (bpm error) |
| Pauses | beat detector | MIT-BIH annotated RR over 2.0 s and over 3.0 s | none |

- PTB-XL 1.0.3: lead I, 10 s at 500 Hz (`records500`), labels from `scp_codes` (a code counts at any likelihood, as in the PTB-XL benchmark). Folds by `strat_fold`: 1 to 8 train, 9 validation, 10 test. A patient never spans two folds.
- PhysioNet/CinC 2017 training set: one lead, 300 Hz, 9 to 61 s. Every full 10 s window of a recording is scored (recordings under 10 s are skipped and counted); a recording's score is its highest window score. Positives `A`, negatives `N` and `O`; noisy `~` recordings are reported apart.
- MIT-BIH Arrhythmia: lead MLII, 360 Hz, 48 records, 10 s windows. The paced records (102, 104, 107, 217) are left out. Positive: at least one SVEB (`A`, `a`, `J`, `S`) or VEB (`V`, `E`) beat. Negative: only AAMI N beats (`N`, `L`, `R`, `e`, `j`). Windows with an `F` or `Q` beat, and windows inside an AF or flutter episode, are left out.
- Thomas's recordings `data/h10_ecg_*.csv` (130 Hz, the real strap): no labels; every flag raised on them counts as a false alarm on a healthy wearer.
- Downloads go to `research/rhythm/data/` (git-ignored). Nothing downloaded is committed.

## The two versions of every window

- Full: resampled to 500 Hz with `scipy.signal.resample_poly`, in mV.
- Strap: resampled to 130 Hz with the same function (its FIR filter is the anti-alias filter), rounded to integer microvolts, then resampled back to 500 Hz for the model. The model sees only what a 130 Hz strap can carry. The H10's own filtering, noise and electrode placement are not modelled; the real-strap check covers part of that.
- Both: 10 s windows (5,000 samples at 500 Hz), z-scored per window as in ECGFounder's `dataset.py`.

## Model and training

- ECGFounder (PKUDigitalHealth, MIT license): the single-lead checkpoint `1_lead_ECGFounder.pth` from Hugging Face, its model code vendored with the license.
- Gate before any training counts: the stock single-lead model, zero-shot on PTB-XL fold 9 at full quality (fold 10 stays untouched), must score AF with an AUROC of at least 0.90. A lower score means our preprocessing does not match the model's; stop and fix that first.
- A new output layer with 6 outputs (AF, flutter, extra beats, first-degree AV block, long QT, WPW), multi-label.
- Two runs, identical except for the version of the input: `full` and `strap`. Starting recipe: AdamW, learning rate 1e-4 for the backbone and 1e-3 for the new layer, binary cross-entropy weighted per label against imbalance, batch 32, mixed precision, at most 15 epochs, keep the epoch with the best mean validation AUROC (fold 9), stop after 3 epochs without improvement, fixed seed. If 6 GB of GPU memory is not enough, lower the batch and accumulate gradients.

## Scoring and the pass bar (fixed before any run)

- Each condition's threshold is set on fold 9 so that its specificity there is 0.98.
- At that threshold, on fold 10 and on the outside set where there is one, with 95% bootstrap intervals (2,000 resamples):
  - Pass: the lower bound of specificity is at least 0.97 and sensitivity is at least 0.80, on fold 10, and on the outside set where there is one.
  - Not enough data: fewer than 50 positive cases in fold 10 (for the detector conditions, in their test set). Expected for flutter, WPW and long QT with this split.
  - Fail: everything else.
- The detector conditions use the same bar with fixed cutoffs instead of a fitted threshold: a window is slow under 60 bpm and fast over 100 bpm (the median of the detector's bpm in the window), judged on fold 10 against `SBRAD` and `STACH`; a MIT-BIH window has a pause when an RR interval in it is over 2.0 s (and, reported apart, over 3.0 s), judged against the annotated beats. Also reported: the detector's beat sensitivity and positive predictive value (a beat matches within 150 ms) and its median absolute bpm error.
- Every verdict is shown next to the full version's numbers: a condition that fails on both is limited by the single lead or the model, not by 130 Hz.
- Also reported: specificity on PTB-XL `NORM` records alone, and the flags raised on Thomas's recordings.

## Databricks and MLflow

- An MLflow experiment `/Users/<the user's Databricks login>/cardioview-rhythm` in the user's Databricks Free Edition workspace. Runs: `gate`, `full`, `strap`, `detector`, `verdict`; each logs its settings, its metrics per condition and dataset, and its prediction tables.
- `MLFLOW_TRACKING_URI=databricks` with `DATABRICKS_HOST` and `DATABRICKS_TOKEN` in the repo-root `.env` (git-ignored, read with `backend/env.py`). Without them the runs go to a local `research/rhythm/mlruns/` (git-ignored) and the same code works.
- `research/rhythm/databricks/verdict.py`: a Databricks notebook in source format that reads the experiment's runs and shows the pass/fail table. It is imported into the workspace by hand or with the Databricks CLI.
- Checkpoints stay local in `research/rhythm/runs/` (git-ignored). No model registry.

## Code and environment

```
research/rhythm/
  README.md            set up, download, run, read the verdict
  requirements.txt     torch (CUDA 12), wfdb, mlflow, huggingface_hub, scikit-learn, scipy, numpy, pandas
  signals.py           resampling, the strap version, windows, z-score (numpy and scipy only)
  labels.py            labels and splits for PTB-XL, PhysioNet 2017 and MIT-BIH (no torch)
  scoring.py           thresholds, bootstrap intervals, verdicts (no torch)
  download.py          the three datasets from PhysioNet into data/
  ecgfounder/          vendored model code (MIT) and a loader for the Hugging Face checkpoint
  train.py             the gate and the two fine-tuning runs
  detector.py          slow rate, fast rate and pauses through backend.pipeline.BeatDetector at 130 Hz
  verdict.py           writes RESULTS.md and logs the verdict run
  databricks/verdict.py
  tests/               known-answer tests for signals, labels and scoring
  RESULTS.md           the committed outcome
```

- `.venv-research` (Python 3.12, its own, like `.venv-voice`): torch never enters the booth's `requirements.txt`.
- `signals.py`, `labels.py` and `scoring.py` import no torch, so their tests run with the main suite in `.venv` (`pytest.ini` gains the path).
- `detector.py` runs the booth's own `BeatDetector`, fed in 73-sample packets like the strap.
- CLAUDE.md gains a short section and stays under 200 lines; the README points to `research/rhythm/README.md`.

## Testing

- `signals.py`: a 10 Hz sine survives the strap round trip and a 100 Hz sine does not; before upsampling, the strap version is integer microvolts at 130 Hz; window counts and lengths.
- `labels.py`: the mapping on small synthetic tables (a PTB-XL row with `PAC` is extra beats; fold 9 is validation; a MIT-BIH window with one `V` beat is positive, one with an `F` beat is left out).
- `scoring.py`: thresholds and verdicts on synthetic scores with known answers (a perfect separator passes; 49 positives give not enough data; a specificity lower bound under 0.97 fails).
- The whole pipeline on a tiny subset on the CPU (a few records, one epoch) before the real runs.
- The gate above before any fine-tuning result counts.

## Out of scope

- Showing anything to visitors (item 11). This test only produces verdicts.
- Five-fold cross-validation, a chest-lead variant and a model registry: offered, declined for now.
- Real strap recordings with known conditions: none exist.

## Risks

- Databricks Free Edition limits (tokens, MLflow from outside the workspace): a run that cannot log there logs locally and is imported later. The verdict does not depend on Databricks.
- ECGFounder's exact preprocessing: guarded by the gate.
- PTB-XL lead I is not the strap's lead, whose electrodes sit lower on the chest. The real-strap check measures only false alarms, so a pass here is necessary, not sufficient, for showing a flag.
