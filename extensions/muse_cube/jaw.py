"""Jaw clench → counter-clockwise turn. Qt-free; times are passed in.

The rule is artifact_log's EMG rule (RMS of the 30–45 Hz band — muscle, e.g. jaw clench; below the 50 Hz mains), made
fast enough to control: a causal filter and a 0.2 s RMS window instead of 1 s epochs analysed 1 s late. It reads
TP9 / TP10 (over the temporal muscles, where a clench is largest).

A clench counts when the RMS stays above the threshold for ``hold_s``; one clench = one turn (the RMS has to fall back
before the next), with a refractory time. Not while the head moves (neck muscles also make EMG).

Calibration: the RMS at rest (the still step) and while clenching (the clench step) set the threshold between them
(geometric middle); the clench has to be clearly above rest, or the control stays off.
Synthetic tests check the algorithm, not that it works on a person.
"""
from collections import deque

import numpy as np
from scipy.signal import sosfilt, sosfilt_zi

from musemonitor.core.filters import bandpass_sos

BAND = (30.0, 45.0)
DEFAULTS = dict(window_s=0.2, hold_s=0.25, release_ratio=0.6, refractory_s=0.8, min_ratio=2.5, still_s=0.5,
                gyro_dps=35.0)


class Jaw:
    def __init__(self, fs, names, cfg=None, channels=("TP9", "TP10")):
        self.cfg = dict(DEFAULTS, **(cfg or {}))
        self.fs = float(fs)
        self.idx = [names.index(c) for c in channels if c in names] or list(range(len(names)))
        self.band = BAND
        self.sos = bandpass_sos(self.fs, *BAND)
        self.threshold = self.calibrated = None              # calibrated: the value the calibration chose
        self.rest = self.clench = None
        self.hist = deque(maxlen=400)                        # (time, rms) per chunk, for the live plots
        self.reset()

    def set_band(self, lo, hi):
        """Another EMG band (e.g. if the 30–45 Hz one does not stand out for this person). The threshold was set in
        the old band: adjust it by hand or calibrate again."""
        lo, hi = float(lo), float(hi)
        if not 0 < lo < hi < self.fs / 2: raise ValueError(f"band {lo}–{hi} Hz outside 0–{self.fs / 2:g} Hz")
        self.band = (lo, hi)
        self.sos = bandpass_sos(self.fs, lo, hi)
        self.zi = None

    @property
    def ready(self):
        return self.threshold is not None

    def reset(self):
        self.zi = None
        self.win = deque(maxlen=max(2, int(self.cfg["window_s"] * self.fs)))
        self.rms = 0.0
        self.above_since = None
        self.fired = False
        self.quiet_until = -1e9
        self.moved_at = -1e9

    def note_motion(self, imu, now):
        x = np.asarray(imu, dtype=float)
        if x.ndim == 2 and x.shape[0] >= 6 and x.shape[1] and np.max(np.linalg.norm(x[3:6], axis=0)) > self.cfg["gyro_dps"]:
            self.moved_at = now

    def _filter(self, x):
        x = np.asarray(x, dtype=float)[self.idx]
        if self.zi is None:
            self.zi = np.stack([sosfilt_zi(self.sos) * x[i, 0] for i in range(len(self.idx))], axis=1)
        y, self.zi = sosfilt(self.sos, x, axis=1, zi=self.zi)
        return (y ** 2).mean(axis=0)                     # power per sample, averaged over the channels

    def rms_series(self, x):
        """RMS over the window for every sample of ``x`` (a fresh filter; for the calibration)."""
        self.zi = None
        win, out = deque(maxlen=self.win.maxlen), []
        for p in self._filter(x):
            win.append(p); out.append(float(np.sqrt(np.mean(win))))
        self.zi = None
        return np.array(out)

    def calibrate(self, rest, clench):
        """rest, clench: channels × samples (raw µV). Returns (ok, message)."""
        rest, clench = np.asarray(rest, float), np.asarray(clench, float)
        if rest.ndim != 2 or clench.ndim != 2 or rest.shape[1] < self.fs or clench.shape[1] < self.fs * 0.5:
            return False, "no_eeg"
        skip = int(0.3 * self.fs)                         # the filter settling
        r = self.rms_series(rest)[skip:]
        k = self.rms_series(clench)[skip:]
        rest_level, clench_level = float(np.percentile(r, 95)), float(np.percentile(k, 80))
        self.rest, self.clench = rest_level, clench_level
        if clench_level < self.cfg["min_ratio"] * rest_level:
            return False, "too_weak"
        self.threshold = self.calibrated = float(np.sqrt(rest_level * clench_level))
        self.reset()
        return True, ""

    def feed(self, x, now, detect=True):
        """EEG chunk → [("clench",)] (at most one per clench)."""
        c = self.cfg
        n = np.asarray(x).shape[1]
        ev = []
        for p in self._filter(x):
            self.win.append(p)
        self.rms = float(np.sqrt(np.mean(self.win))) if self.win else 0.0
        self.hist.append((now, self.rms))
        if not detect or self.threshold is None: return ev
        thr = self.threshold
        if self.fired:
            if self.rms < thr * c["release_ratio"]: self.fired, self.above_since = False, None
            return ev
        if self.rms >= thr and now >= self.quiet_until and now - self.moved_at >= c["still_s"]:
            self.above_since = self.above_since if self.above_since is not None else now - n / self.fs
            if now - self.above_since >= c["hold_s"]:
                ev.append(("clench",)); self.fired = True; self.quiet_until = now + c["refractory_s"]
        else:
            self.above_since = None
        return ev

    def level(self):
        """0..1+ of the threshold (for an on-screen meter)."""
        return 0.0 if not self.threshold else self.rms / self.threshold
