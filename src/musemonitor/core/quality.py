"""Electrode contact quality estimated from the signal (thresholds in config)."""
import numpy as np

from .. import config as C

LEVELS = ("Good", "Fair", "Bad", "No signal")


def band_rms(x, fs, lo, hi):
    """Band-limited RMS (Parseval) per channel. x: (n_ch, n)."""
    n = x.shape[1]
    w = np.hanning(n)
    X = np.fft.rfft((x - x.mean(axis=1, keepdims=True)) * w, axis=1)
    f = np.fft.rfftfreq(n, 1 / fs)
    p = (np.abs(X) ** 2) / (fs * (w ** 2).sum())          # one-sided PSD (µV²/Hz)
    p[:, 1:-1] *= 2
    m = (f >= lo) & (f <= hi)
    return np.sqrt(p[:, m].sum(axis=1) * (f[1] - f[0]))


def contact_quality(x, fs):
    """Returns [(level, RMS 1–40 Hz, RMS 45–55 Hz)] per channel."""
    band = band_rms(x, fs, 1, 40); line = band_rms(x, fs, 45, 55)
    out = []
    for b, l, raw in zip(band, line, x):
        if raw.std() < C.Q_FLAT_UV: q = "No signal"
        elif b <= C.Q_GOOD["band"] and l <= C.Q_GOOD["line"]: q = "Good"
        elif b <= C.Q_FAIR["band"] and l <= C.Q_FAIR["line"]: q = "Fair"
        else: q = "Bad"
        out.append((q, b, l))
    return out
