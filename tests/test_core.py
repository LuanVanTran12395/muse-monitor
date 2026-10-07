import numpy as np
import pytest
from scipy.signal import sosfilt, sosfilt_zi

import synthetic as S
from musemonitor.core.buffers import Ring
from musemonitor.core.filters import CausalFilter, eeg_sos
from musemonitor.core.fnirs import EXT, mbll
from musemonitor.core.ppg import best_channel, clean_ibi, hrv_metrics, ppg_beats
from musemonitor.core.quality import contact_quality
from musemonitor.core.spectral import stft_power


# ---- Ring ---------------------------------------------------------------------
def test_ring_keeps_latest_in_order_across_wraparound():
    r = Ring(2, 10)
    data = np.vstack([np.arange(25), -np.arange(25)]).astype(float)
    for k in range(0, 25, 3): r.extend(data[:, k:k + 3])
    assert r.n == 10
    np.testing.assert_array_equal(r.get(), data[:, -10:])
    np.testing.assert_array_equal(r.get(4), data[:, -4:])


def test_ring_chunk_larger_than_capacity_and_clear():
    r = Ring(1, 5)
    r.extend(np.arange(12, dtype=float)[None])
    np.testing.assert_array_equal(r.get()[0], np.arange(7, 12))
    r.clear()
    assert r.n == 0 and r.get().shape == (1, 0)


# ---- CausalFilter -------------------------------------------------------------
def test_causal_filter_chunked_equals_one_shot():
    fs = 256
    x = S.eeg(fs, 4)
    f = CausalFilter(fs)
    chunked = np.hstack([f.process(x[:, k:k + 37]) for k in range(0, x.shape[1], 37)])
    sos = eeg_sos(fs)["both"]
    ref, _ = sosfilt(sos, x, axis=1, zi=sosfilt_zi(sos)[:, None, :] * x[None, :, :1])
    np.testing.assert_allclose(chunked, ref, atol=1e-9)


def test_causal_filter_off_is_passthrough():
    f = CausalFilter(256, notch=False, band=False)
    x = np.random.default_rng(0).standard_normal((4, 100))
    assert f.process(x) is x


# ---- Contact quality ------------------------------------------------------
def test_contact_quality_levels():
    fs = 256
    rng = np.random.default_rng(0)
    t = np.arange(2 * fs) / fs
    x = np.vstack([np.zeros(t.size),                                   # flat
                   10 * np.sin(2 * np.pi * 10 * t),                    # clean
                   80 * np.sin(2 * np.pi * 10 * t),                    # RMS ≈ 57 µV → Fair
                   200 * rng.standard_normal(t.size)])                 # noisy
    levels = [q for q, _, _ in contact_quality(x, fs)]
    assert levels == ["No signal", "Good", "Fair", "Bad"]


# ---- Spectrogram --------------------------------------------------------------
def test_stft_peak_at_signal_frequency():
    fs = 256
    t = np.arange(8 * fs) / fs
    x = np.sin(2 * np.pi * 12 * t)[None]
    tc, f, P, step = stft_power(x, fs, win=fs, step=fs // 4, fmax=45)
    assert f[np.argmax(P[0].mean(axis=0))] == pytest.approx(12)
    assert tc[-1] == pytest.approx(-0.5)            # last segment aligned to the newest sample
    assert stft_power(x[:, :100], fs, win=fs, step=10, fmax=45) is None


def test_stft_raises_step_when_too_many_cells():
    x = np.zeros((1, 10_000))
    *_, step = stft_power(x, 256, win=1000, step=1, fmax=45, max_cells=100_000)
    assert step > 1


# ---- PPG / HRV ----------------------------------------------------------------
def test_ppg_heart_rate_and_auto_channel():
    fs, sec = 64, 60
    o = S.optics(fs, sec, bpm=72)
    assert best_channel(o[:, -10 * fs:], fs) not in (2, 3, 4, 5, 6, 7)   # never picks a noise channel
    _, pk = ppg_beats(o[0], fs)
    _, ibi, ok = clean_ibi(pk / fs)
    assert 60 / np.median(ibi[ok]) == pytest.approx(72, abs=2)


def test_hrv_metrics_known_values():
    ibi = np.array([0.80, 0.85, 0.80, 0.90, 0.80])
    m = hrv_metrics(ibi, np.ones(5, bool))
    d = np.diff(ibi)
    assert m["rmssd"] == pytest.approx(np.sqrt(np.mean(d ** 2)) * 1000)
    assert m["sdnn"] == pytest.approx(ibi.std(ddof=1) * 1000)
    assert m["prr50"] == pytest.approx(50.0)             # |Δ| = 50,50,100,100 ms → 2/4 > 50 ms
    assert m["prr20"] == pytest.approx(100.0)
    assert m["n"] == 6
    assert hrv_metrics(ibi[:2], np.ones(2, bool)) is None


def test_clean_ibi_rejects_outliers():
    tb = np.cumsum([0.8] * 10 + [2.5] + [0.8] * 5)
    _, ibi, ok = clean_ibi(tb)
    assert not ok[ibi > 2.0].any() and ok.sum() == len(ibi) - 1


# ---- fNIRS --------------------------------------------------------------------
def test_mbll_recovers_concentration_change():
    fs, n = 64, 64 * 60
    t = np.arange(n) / fs
    hbo = 1e-6 * np.sin(2 * np.pi * 0.05 * t)            # ±1 µM, slower than the 0.5 Hz lowpass
    hbr = -0.5e-6 * np.sin(2 * np.pi * 0.05 * t)
    dpf, d = 6.0, 3.0
    od = (EXT * d * dpf) @ np.vstack([hbo, hbr])           # ΔOD theo Beer–Lambert
    i1, i2 = 1e5 * 10 ** (-od[0]), 1e5 * 10 ** (-od[1])
    out = mbll(i1, i2, fs, dpf, d)
    mid = slice(n // 4, 3 * n // 4)
    np.testing.assert_allclose(out[0][mid], (hbo - hbo.mean())[mid] * 1e6, atol=0.05)
    np.testing.assert_allclose(out[1][mid], (hbr - hbr.mean())[mid] * 1e6, atol=0.05)
