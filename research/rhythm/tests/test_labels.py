"""Labels and splits for PTB-XL, PhysioNet 2017 and MIT-BIH, on small tables with known answers."""
import numpy as np
import pandas as pd

from research.rhythm import labels as lb


def test_ptbxl_codes_folds_and_rates():
    db = pd.DataFrame({
        "scp_codes": ["{'NORM': 100.0, 'SR': 0.0}", "{'PAC': 0.0, 'SR': 0.0}", "{'AFIB': 100.0}",
                      "{'SBRAD': 0.0, '1AVB': 100.0}"],
        "filename_hr": ["a", "b", "c", "d"], "strat_fold": [1, 9, 10, 3]},
        index=pd.Index([1, 2, 3, 4], name="ecg_id"))
    out = lb.ptbxl_labels(db)
    assert list(out["split"]) == ["train", "val", "test", "train"]
    assert out.loc[2, "extra_beats"] == 1 and out.loc[2, "af"] == 0   # a code counts at likelihood 0
    assert out.loc[3, "af"] == 1 and out.loc[4, "avb1"] == 1 and out.loc[4, "sbrad"] == 1
    assert out.loc[1, "norm"] == 1 and out.loc[1, list(lb.CONDITIONS)].sum() == 0


def test_cinc2017_sets_noisy_apart():
    ref = pd.DataFrame({"record": ["A1", "A2", "A3", "A4"], "label": ["A", "N", "O", "~"]})
    assert list(lb.cinc2017_labels(ref)["af"]) == [1, 0, 0, -1]


def test_mitbih_windows_label_extra_beats_and_leave_out_the_rest():
    fs, n = 100, 5000   # five 10 s windows of 1000 samples
    symbols = ["N", "N", "V", "N", "F", "N", "+", "N", "+"]
    samples = [100, 500, 1200, 1800, 2500, 2600, 3000, 3500, 4000]
    aux = ["", "", "", "", "", "", "(AFIB\x00", "", "(N\x00"]   # MIT-BIH notes end in a NUL byte
    w = lb.mitbih_windows(symbols, samples, aux, fs, n)
    assert list(w["extra_beats"]) == [0, 1, -1, -1, -1]   # normal, a PVC, an F beat, inside AF, no beat


def test_rr_windows_count_an_interval_only_where_both_its_beats_are():
    w = lb.rr_windows(np.array([1.0, 2.0, 3.0, 9.5, 10.5, 11.5]), 2)
    assert w.loc[0, "max_rr"] == 6.5 and w.loc[0, "n_rr"] == 3
    assert w.loc[1, "max_rr"] == 1.0 and round(w.loc[1, "bpm"]) == 60


def test_a_pause_across_a_window_edge_counts_in_neither_window():
    w = lb.rr_windows(np.array([7.0, 8.0, 9.0, 12.0, 13.0, 14.0]), 2)   # the 3 s pause crosses 10 s
    assert w.loc[0, "max_rr"] == 1.0 and w.loc[1, "max_rr"] == 1.0   # a detector inside one window never sees it
