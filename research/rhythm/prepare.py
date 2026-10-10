"""Features for every stretch, native and strap, cached as CSV in data/cache/.

python -m research.rhythm.prepare [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io
import wfdb

from research.rhythm import detector as dt
from research.rhythm import labels as lb
from research.rhythm import signals as sg

HERE = Path(__file__).parent
DATA = HERE / "data"
CACHE = DATA / "cache"
REPO = HERE.parents[1]
CINC_FS, CINC_GAIN = 300, 1000.0   # PhysioNet 2017 headers: 300 Hz, 1000 units per mV
WINDOW_S = 10


def both(x_mv, fs) -> list[dict]:
    """The features of one stretch, native and strap."""
    x = np.nan_to_num(np.asarray(x_mv, dtype=float))
    return [{"version": "native", **dt.features(np.rint(x * 1000), fs)},
            {"version": "strap", **dt.features(sg.to_strap_uv(x, fs), sg.STRAP_FS)}]


def ptbxl_record(job):
    path, ecg_id = job
    sig, fields = wfdb.rdsamp(path, channel_names=["I"])
    return [{"ecg_id": ecg_id, **row} for row in both(sig[:, 0], fields["fs"])]


def cinc_record(path):
    x = scipy.io.loadmat(path + ".mat")["val"][0] / CINC_GAIN
    return [{"record": Path(path).name, **row} for row in both(x, CINC_FS)]


def mitbih_record(path):
    sig, fields = wfdb.rdsamp(path, channel_names=["MLII"])
    ann = wfdb.rdann(path, "atr")
    fs, x = fields["fs"], sig[:, 0]
    win = lb.mitbih_windows(ann.symbol, ann.sample, ann.aux_note, fs, len(x))
    truth = lb.rr_windows(lb.beat_times(ann.symbol, ann.sample, fs), len(win))
    strap, n_strap = sg.to_strap_uv(x, fs), WINDOW_S * sg.STRAP_FS
    rows = []
    for k in range(len(win)):
        a, b = int(k * WINDOW_S * fs), int((k + 1) * WINDOW_S * fs)
        meta = {"record": Path(path).name, "start_s": k * WINDOW_S, "extra_beats": int(win.loc[k, "extra_beats"]),
                "true_max_rr": truth.loc[k, "max_rr"], "true_n_rr": int(truth.loc[k, "n_rr"])}
        rows.append({**meta, "version": "native", **dt.features(np.rint(x[a:b] * 1000), fs)})
        rows.append({**meta, "version": "strap", **dt.features(strap[k * n_strap:(k + 1) * n_strap], sg.STRAP_FS)})
    return rows


def thomas() -> pd.DataFrame:
    rows, n = [], WINDOW_S * sg.STRAP_FS
    for path in sorted((REPO / "data").glob("h10_ecg_*.csv")):
        uv = pd.read_csv(path)["ecg_uv"].to_numpy(dtype=float)
        for k in range(len(uv) // n):
            rows.append({"record": path.stem, "start_s": k * WINDOW_S, "version": "strap",
                         **dt.features(uv[k * n:(k + 1) * n], sg.STRAP_FS)})
    return table(rows)


def table(rows) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    for c in dt.FEATURES:
        if c not in df:
            df[c] = np.nan
    return df


def save(name: str, df: pd.DataFrame) -> None:
    df.to_csv(CACHE / f"{name}.csv", index=False)
    print(f"{name}: {len(df)} rows, {int(df['bpm'].isna().sum())} with too few beats", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="smoke run: this many records per dataset")
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    root = next(DATA.glob("ptbxl/**/ptbxl_database.csv")).parent
    meta = lb.ptbxl_labels(pd.read_csv(root / "ptbxl_database.csv", index_col="ecg_id"))
    ref = lb.cinc2017_labels(pd.read_csv(DATA / "cinc2017_reference.csv", header=None, names=["record", "label"]))
    cinc_dir = next(DATA.glob("cinc2017/**/A00001.hea")).parent
    mit_dir = next(DATA.glob("mitdb/**/100.hea")).parent
    records = sorted(p.stem for p in mit_dir.glob("*.hea") if p.stem.isdigit() and p.stem not in lb.PACED)
    if args.limit:
        meta, ref, records = meta.iloc[:args.limit], ref.iloc[:args.limit], records[:2]
    with ProcessPoolExecutor() as pool:
        ptb = table(r for rows in pool.map(ptbxl_record, [(str(root / f), i) for i, f in meta["filename_hr"].items()],
                                           chunksize=64) for r in rows)
        cinc = table(r for rows in pool.map(cinc_record, [str(cinc_dir / r) for r in ref["record"]], chunksize=64)
                     for r in rows)
        mit = table(r for rows in pool.map(mitbih_record, [str(mit_dir / r) for r in records]) for r in rows)
    save("ptbxl", ptb.merge(meta.reset_index(), on="ecg_id"))
    save("cinc2017", cinc.merge(ref, on="record"))
    save("mitbih", mit)
    save("thomas", thomas())
    return 0


if __name__ == "__main__":
    sys.exit(main())
