"""Deterministic synthetic signals (fixed seed) for tests — no headset or real recording needed."""
import numpy as np


def eeg(fs, sec, n_ch=4, seed=0):
    """EEG ~ 10 Hz alpha + small white noise (µV)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(fs * sec)) / fs
    return np.vstack([20 * np.sin(2 * np.pi * 10 * t + k) + 3 * rng.standard_normal(t.size) for k in range(n_ch)])


def beat_times(sec, bpm=75.0, jitter_s=0.03, seed=1):
    rng = np.random.default_rng(seed)
    out, t = [], 0.5
    while t < sec:
        out.append(t); t += 60.0 / bpm + jitter_s * rng.standard_normal()
    return np.array(out)


def optics(fs, sec, n_ch=16, bpm=75.0, seed=2):
    """Optical intensity: large DC; 'good' channels carry a pulse (intensity drops each beat), 'bad' ones only noise."""
    rng = np.random.default_rng(seed)
    n = int(fs * sec); t = np.arange(n) / fs
    pulse = np.zeros(n)
    for tb in beat_times(sec, bpm, seed=seed + 1):
        pulse += np.exp(-0.5 * ((t - tb) / 0.08) ** 2)
    x = np.empty((n_ch, n))
    for c in range(n_ch):
        good = c not in (2, 3, 4, 5, 6, 7)
        x[c] = 200000 + (1500 * (c + 1) / n_ch) * (-pulse if good else 0) + 30 * rng.standard_normal(n) \
            + 500 * np.sin(2 * np.pi * 0.1 * t + c)
    return x


def imu(fs, sec, seed=3):
    rng = np.random.default_rng(seed)
    n = int(fs * sec)
    acc = np.array([[-0.2], [0.1], [1.0]]) + 0.01 * rng.standard_normal((3, n))
    gyr = 0.5 * rng.standard_normal((3, n))
    return np.vstack([acc, gyr])
