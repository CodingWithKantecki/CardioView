"""The Hugging Face model card, and the upload. Publishing is public: it uploads only with --upload.

python -m research.rhythm.publish            writes models/README.md, the card, to read first
python -m research.rhythm.publish --upload   uploads models/ to <your account>/cardioview-rhythm-detector
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
MODELS = HERE / "models"
REPO_NAME = "cardioview-rhythm-detector"

BODY = """
# CardioView rhythm detector

Two tiny logistic models, `af.json` and `extra_beats.json`, that flag atrial fibrillation and extra beats from one chest-strap ECG lead sampled the way the Polar H10 samples it: 130 Hz, integer microvolts. They belong to CardioView, a KnightHacks IX project that shows a visitor's heart beating in 3D.

**This is not a medical device.** CardioView shows a visitor a condition only when it passes the bar below, and never as a diagnosis. Read the verdicts before using a model: one that fails the bar is published as a measured result, not as a working detector.

## How it works

NeuroKit2 cleans the stretch and finds R peaks without artifact correction (correction would move early beats back into line). From the beat-to-beat intervals and the beats come six features: `bpm`, `max_rr`, `nrmssd` (RMS of successive differences over the mean interval), `irregular` (share of successive differences over 15% of the median), `premature` (an interval under 85% of the median followed by one over 110%) and `odd_shape` (one minus the lowest correlation of a beat with the median beat). Each model is a logistic regression on standardized features: `score = sigmoid(sum(weights * (x - mean) / scale) + bias)`, flagged above `threshold`. The feature code is `research/rhythm/detector.py` in the CardioView repository.

## Results
{results}
## Data

- PTB-XL 1.0.3 (Wagner et al., PhysioNet), lead I: fitting, threshold and test folds. CC BY 4.0.
- PhysioNet/CinC Challenge 2017 training set: the outside test for atrial fibrillation. Open Data Commons Attribution 1.0.
- MIT-BIH Arrhythmia Database (Moody and Mark, PhysioNet): the outside test for extra beats and pauses. Open Data Commons Attribution 1.0.

Every stretch was also resampled to 130 Hz and rounded to integer microvolts, the strap version these models were fitted on.
"""


def card(results: str, license_id: str) -> str:
    body = results.split("\n", 1)[1] if results.startswith("# ") else results   # the card has its own title
    return (f"---\nlicense: {license_id}\ntags: [ecg, arrhythmia, atrial-fibrillation, wearable, polar-h10]\n---\n"
            + BODY.replace("{results}", body))


def upload() -> None:
    from huggingface_hub import HfApi

    from backend.env import load_dotenv
    load_dotenv()
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN (a write token) is not in .env")
    api = HfApi(token=token)
    repo = f"{api.whoami()['name']}/{REPO_NAME}"
    api.create_repo(repo, repo_type="model", exist_ok=True)
    api.upload_folder(folder_path=str(MODELS), repo_id=repo, repo_type="model")
    print(f"published: https://huggingface.co/{repo}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--license", default="mit")
    args = ap.parse_args(argv)
    MODELS.mkdir(exist_ok=True)
    (MODELS / "README.md").write_text(card((HERE / "RESULTS.md").read_text(encoding="utf-8"), args.license),
                                      encoding="utf-8")
    print(f"card: {MODELS / 'README.md'}")
    if args.upload:
        upload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
