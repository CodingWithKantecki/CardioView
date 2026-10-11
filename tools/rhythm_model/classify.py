"""The closest demo pattern for each 10 s window of a strap CSV. Experimental, not a diagnosis.

    python -m tools.rhythm_model.classify data/h10_ecg_thomas.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from . import data as D

HEAD = Path(__file__).resolve().parent / "head.npz"


class Classifier:
    def __init__(self, head: Path = HEAD):
        from .encoder import Encoder

        z = np.load(head)
        if int(z["version"]) != D.VERSION:
            raise SystemExit(f"{head.name} is from generator version {int(z['version'])}; retrain with tools.rhythm_model.train")
        self.mean, self.scale, self.coef, self.intercept = z["mean"], z["scale"], z["coef"], z["intercept"]
        self.classes = [str(c) for c in z["classes"]]
        self.layers = tuple(int(k) for k in z["layers"])
        self.threshold = float(z["threshold"])
        self.encoder = Encoder(layers=self.layers)

    def probabilities(self, windows_uv) -> np.ndarray:
        x = np.stack([D.prepare(w) for w in windows_uv])
        f = self.encoder.features(x).mean(1).reshape(len(x), -1)
        logits = ((f - self.mean) / self.scale) @ self.coef.T + self.intercept
        e = np.exp(logits - logits.max(1, keepdims=True))
        return e / e.sum(1, keepdims=True)

    def closest(self, windows_uv) -> list[tuple[str, float]]:
        """(pattern, probability) per window; "unsure" when no pattern reaches the threshold."""
        out = []
        for p in self.probabilities(windows_uv):
            k = int(p.argmax())
            out.append((self.classes[k] if p[k] >= self.threshold else "unsure", float(p[k])))
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path, help="time_s,ecg_uv at 130 Hz, like tools/h10_record.py writes")
    ap.add_argument("--invert", action="store_true", help="flip the signal first (strap worn upside down)")
    args = ap.parse_args()
    uv = D.load_csv(args.csv) * (-1 if args.invert else 1)
    rec = D.Recording("unknown", 0, uv)
    win = int(D.WINDOW_S * D.FS)
    starts = [s for s, _ in D.windows(rec)]
    if not starts:
        raise SystemExit(f"{args.csv} is shorter than one {D.WINDOW_S:.0f} s window")
    for s, (name, p) in zip(starts, Classifier().closest([uv[s:s + win] for s in starts])):
        label = D.NAMES.get(name, "No close match")
        print(f"{s / D.FS:6.1f} s  {label:<24} {p:.2f}")
    print("Closest simulated demo pattern only. Experimental, not a diagnosis.")


if __name__ == "__main__":
    main()
