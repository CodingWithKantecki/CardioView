"""Train and evaluate the demo-pattern classifier: frozen HuBERT-ECG features, a logistic regression head.

    python -m tools.rhythm_model.train            # embeds (cached), fits, writes docs/rhythm-model/

Splits are by seed, so every test recording is one the head never saw. A second test runs the demo's
own RhythmSource streams, and the strap recordings in data/ get the closest pattern per window
(no labels: that is real ECG, and nothing here is a diagnosis).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from . import data as D
from .encoder import LAYERS

LAYER_SETS = [(8,), (4, 8), (2, 4, 6, 8)]
ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / "cache"
HEAD = Path(__file__).resolve().parent / "head.npz"
DOCS = ROOT / "docs" / "rhythm-model"
SIZES = {"train": 100, "val": 25, "test": 50, "demo": 6}   # recordings per class (demo: per pattern)
THRESHOLD = 0.6   # below this the closest pattern is "no close match"
SHORT = {"sinus": "Normal", "brady": "Brady", "afib": "AFib", "pvc": "Extra beats", "vt": "V-tach",
         "mi": "Heart attack", "none": "No match"}


def recordings(split: str, n: int):
    if split == "demo":
        return [D.demo_recording(p, s) for p in D.DEMO for s in D.split_seeds("demo", n)]
    return [D.recording(c, s) for c in D.CLASSES for s in D.split_seeds(split, n)]


def window_set(recs):
    win = int(D.WINDOW_S * D.FS)
    x, y, rec = [], [], []
    for i, r in enumerate(recs):
        for s, label in D.windows(r):
            x.append(D.prepare(r.uv[s:s + win]))
            y.append(D.CLASSES.index(label) if label in D.CLASSES else -1)
            rec.append(i)
    return np.stack(x), np.array(y), np.array(rec)


def embedded(name: str, recs, encoder):
    """Features for a set of recordings, cached by generator version, encoder layers and size."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"v{D.VERSION}_L{''.join(map(str, LAYERS))}_{name}_{len(recs)}.npz"
    if path.exists():
        z = np.load(path)
        return z["f"].astype(np.float32), z["y"], z["rec"]
    x, y, rec = window_set(recs)
    t = time.time()
    f = encoder().features(x)
    print(f"{name}: {len(x)} windows embedded in {time.time() - t:.0f} s", flush=True)
    np.savez_compressed(path, f=f.astype(np.float16), y=y, rec=rec)
    return f, y, rec


def pool(f, layers):
    """Head input: the chosen layers' features, averaged over the window's two halves."""
    return f[:, :, [LAYERS.index(k) for k in layers]].mean(1).reshape(len(f), -1)


def strap_recordings():
    out = []
    for p in sorted((ROOT / "data").glob("h10_ecg_*.csv")):
        uv = D.load_csv(p)
        out.append(D.Recording("unknown", 0, uv, meta={"file": p.name}))
    return out


def fit(train, val):
    """The layers and regularization with the best validation accuracy."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    best = None
    for layers in LAYER_SETS:
        xt, xv = pool(train[0], layers), pool(val[0], layers)
        for c in (0.001, 0.003, 0.01, 0.03, 0.1):
            model = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=3000))
            model.fit(xt, train[1])
            acc = float((model.predict(xv) == val[1]).mean())
            print(f"layers {layers}, C={c}: val accuracy {acc:.4f}", flush=True)
            if best is None or acc > best[0]:
                best = (acc, layers, c, model)
    return best


def report(model, f, y, names):
    from sklearn.metrics import classification_report, confusion_matrix

    p = model.predict_proba(f)
    pred = p.argmax(1)
    labels = sorted(set(y.tolist()) | set(pred.tolist()))
    sure = p.max(1) >= THRESHOLD
    return {
        "windows": int(len(y)),
        "accuracy": float((pred == y).mean()),
        "answered": float(sure.mean()),
        "accuracy_answered": float((pred[sure] == y[sure]).mean()) if sure.any() else None,
        "labels": [D.CLASSES[i] for i in labels],
        "confusion": confusion_matrix(y, pred, labels=labels).tolist(),
        "per_class": {k: v for k, v in classification_report(
            y, pred, labels=labels, target_names=[names[D.CLASSES[i]] for i in labels],
            output_dict=True, zero_division=0).items() if k not in ("accuracy",)},
    }


def plot(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    bg, fg, dim, accent = "#0A1115", "#E8F1F2", "#7F969B", "#2BD4BD"
    cmap = LinearSegmentedColormap.from_list("cv", [bg, "#12403C", accent])
    panels = [("test", "Held-out seeds"), ("demo", "Demo rhythm source")]
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.4), facecolor=bg,
                             gridspec_kw={"width_ratios": [7, 6]})
    for ax, (key, title) in zip(axes, panels):
        r = results[key]
        cm = np.array(r["confusion"], dtype=float)
        rows = r["labels"]
        norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
        ax.imshow(norm, cmap=cmap, vmin=0, vmax=1)
        names = [SHORT[c] for c in rows]
        ax.set_xticks(range(len(rows)), names, rotation=35, ha="right", color=fg, fontsize=10)
        ax.set_yticks(range(len(rows)), names, color=fg, fontsize=10)
        for i in range(len(rows)):
            for j in range(len(rows)):
                if cm[i, j]:
                    ax.text(j, i, f"{norm[i, j] * 100:.0f}%\n{int(cm[i, j])}", ha="center", va="center",
                            fontsize=8.5, color=bg if norm[i, j] > 0.55 else fg)
        ax.set_xlabel("Predicted", color=dim)
        ax.set_ylabel("True", color=dim)
        ax.set_title(f"{title}: {r['accuracy'] * 100:.1f}% of {r['windows']} windows", color=fg, fontsize=12, pad=10)
        ax.tick_params(colors=dim)
        for s in ax.spines.values():
            s.set_color(dim)
        ax.set_facecolor(bg)
    fig.tight_layout()
    fig.savefig(path, dpi=110, facecolor=bg)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--small", action="store_true", help="a few recordings per class, to try the pipeline")
    args = ap.parse_args()
    sizes = {k: (3 if args.small else v) for k, v in SIZES.items()}

    enc = None

    def encoder():
        nonlocal enc
        if enc is None:
            from .encoder import Encoder
            enc = Encoder()
        return enc

    sets = {k: embedded(k, recordings(k, n), encoder) for k, n in sizes.items()}
    strap = strap_recordings()
    strap_set = embedded("strap", strap, encoder) if strap else None

    val_acc, layers, c, model = fit(sets["train"][:2], sets["val"][:2])
    results = {
        "version": D.VERSION, "encoder": "Edoardo-Coppola/hubert-ecg-small (frozen)",
        "head": f"logistic regression on layers {list(layers)}, C={c}",
        "threshold": THRESHOLD, "window_s": D.WINDOW_S, "hop_s": D.HOP_S,
        "recordings": {k: (n * (len(D.DEMO) if k == "demo" else len(D.CLASSES))) for k, n in sizes.items()},
        "windows": {k: int(len(v[1])) for k, v in sets.items()},
        "val_accuracy": val_acc,
    }
    for key in ("test", "demo"):
        results[key] = report(model, pool(sets[key][0], layers), sets[key][1], SHORT)
        print(f"{key}: accuracy {results[key]['accuracy']:.4f}", flush=True)
    if strap_set is not None:
        p = model.predict_proba(pool(strap_set[0], layers))
        results["strap"] = {}
        for i, r in enumerate(strap):
            mine = p[strap_set[2] == i]
            closest = [D.CLASSES[k] if q.max() >= THRESHOLD else "unsure" for k, q in zip(mine.argmax(1), mine)]
            results["strap"][r.meta["file"]] = {c: closest.count(c) for c in sorted(set(closest))}
        print("strap:", results["strap"], flush=True)

    if not args.small:
        DOCS.mkdir(parents=True, exist_ok=True)
        plot(results, DOCS / "confusion.png")
        (DOCS / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        scaler, head = model[0], model[1]
        np.savez(HEAD, mean=scaler.mean_, scale=scaler.scale_, coef=head.coef_, intercept=head.intercept_,
                 classes=np.array(D.CLASSES), layers=np.array(layers), threshold=THRESHOLD, version=D.VERSION)
        print(f"wrote {DOCS / 'confusion.png'}, {DOCS / 'results.json'} and {HEAD}")


if __name__ == "__main__":
    main()
