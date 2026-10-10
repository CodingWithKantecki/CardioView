"""The strap version: 130 Hz and integer microvolts, raised back to the model's 500 Hz."""
import numpy as np

from research.rhythm import signals as sg


def sine(f, fs=500, seconds=10, mv=1.0):
    t = np.arange(int(fs * seconds)) / fs
    return mv * np.sin(2 * np.pi * f * t)


def test_the_strap_keeps_a_slow_wave_and_loses_a_fast_one():
    mid = slice(500, -500)   # away from the filter's edges
    slow = sg.strap_version(sine(10), 500)
    fast = sg.strap_version(sine(100), 500)
    assert np.sqrt(np.mean((slow - sine(10))[mid] ** 2)) < 0.02
    assert np.sqrt(np.mean(fast[mid] ** 2)) < 0.05


def test_the_strap_sends_integer_microvolts_at_130_hz():
    uv = sg.to_strap_uv(sine(5, mv=1.5), 500)
    assert uv.dtype == np.int32 and len(uv) == 1300
    assert 1450 <= np.abs(uv).max() <= 1510


def test_every_rate_gives_the_same_windows_in_both_versions():
    for fs in (300, 360, 500):
        x = sine(7, fs=fs, seconds=30)
        full, strap = sg.full_version(x, fs), sg.strap_version(x, fs)
        assert sg.windows(full).shape == sg.windows(strap).shape == (3, sg.WINDOW_N)


def test_windows_keep_only_full_windows():
    assert sg.windows(np.zeros(12000)).shape == (2, 5000)
    assert sg.windows(np.zeros(4999)).shape == (0, 5000)   # a 9 s recording gives no window


def test_zscore_is_per_window_and_a_flat_line_stays_zero():
    z = sg.zscore(np.array([[1.0, 2.0, 3.0], [5.0, 5.0, 5.0]]))
    assert np.isclose(z[0].mean(), 0) and np.isclose(z[0].std(), 1, atol=1e-4)
    assert np.all(z[1] == 0) and not np.isnan(z).any()
