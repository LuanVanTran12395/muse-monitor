"""Timing of one stream: keep RAW timestamps, count anomalies, compute the display axis.

Rules (see debate/claude-round-2.md):
- Raw timestamps are never modified: the CSV and ``raw_ts()`` return exactly what was received.
- ``backsteps``: number of times ts[i] < ts[i-1] (including across chunk boundaries).
- ``seq_anomalies``: number of package_num steps with Δ ∉ {0, 1}. This is NOT a count of lost packets — the
  package_num rule (increment, wrap-around, samples per packet) of each preset still has to be verified on
  a raw fixture. ``seq_deltas`` keeps a histogram of Δ for analysis.
- Display axis: linear regression of raw ts against sample index over the last ``fit_sec`` seconds →
  sample period ``period`` and time ``ref`` of the newest sample. Signal curves (x = period·(i − last))
  and event markers (x = t_event − ref) use the SAME time frame, so they never drift apart.
  Until there is enough data: period = 1/nominal fs, ref = last raw ts.
"""
from collections import Counter

import numpy as np

from .buffers import Ring

MAX_DELTA_KINDS = 32


def ts_vector(ts, k, fs):
    """Accept a scalar ts (timestamp of the last sample — legacy) or a vector of k values."""
    ts = np.asarray(ts, dtype=float)
    if ts.ndim == 0: return float(ts) - (k - 1 - np.arange(k)) / fs
    return ts


class StreamClock:
    def __init__(self, fs, cap, fit_sec):
        self.fs = fs
        self.ts = Ring(1, cap)
        self.fit_n = max(2, int(fit_sec * fs))
        self.clear()

    def clear(self):
        self.ts.clear()
        self.total = 0
        self.backsteps = self.seq_anomalies = 0
        self.seq_deltas = Counter()
        self.last_ts = self.last_seq = None
        self._fit_key = None; self._fit = None

    def add(self, ts, seq=None):
        ts = np.asarray(ts, dtype=float)
        prev = [] if self.last_ts is None else [self.last_ts]
        self.backsteps += int((np.diff(np.concatenate([prev, ts])) < 0).sum())
        if seq is not None and len(seq):
            seq = np.asarray(seq, dtype=float)
            prev_s = [] if self.last_seq is None else [self.last_seq]
            d = np.diff(np.concatenate([prev_s, seq]))
            self.seq_anomalies += int(((d != 0) & (d != 1)).sum())
            for v, c in zip(*np.unique(d, return_counts=True)):
                if v in self.seq_deltas or len(self.seq_deltas) < MAX_DELTA_KINDS: self.seq_deltas[float(v)] += int(c)
            self.last_seq = float(seq[-1])
        self.ts.extend(ts[None, :])
        self.total += len(ts)
        self.last_ts = float(ts[-1])

    def raw_ts(self, n=None):
        return self.ts.get(n)[0]

    def fit(self):
        """(period, ref): estimated sample period and time (on the fitted axis) of the newest sample."""
        key = self.total
        if key == self._fit_key: return self._fit
        m = min(self.ts.n, self.fit_n)
        period, ref = 1.0 / self.fs, self.last_ts
        if m >= 2:
            y = self.raw_ts(m)
            x = np.arange(m) - (m - 1) / 2
            p = float((x * (y - y.mean())).sum() / (x * x).sum())
            if np.isfinite(p) and p > 0:
                period, ref = p, float(y.mean() + p * (m - 1) / 2)
        self._fit_key, self._fit = key, (period, ref)
        return self._fit

    def axis(self, n):
        """Relative time (s) of the newest n samples; last sample = 0."""
        period, _ = self.fit()
        return period * (np.arange(n) - (n - 1))

    def to_axis(self, idx, n):
        """Convert (possibly fractional) sample indices within the newest n samples to relative time."""
        return self.fit()[0] * (np.asarray(idx, dtype=float) - (n - 1))

    @property
    def ref(self):
        return self.fit()[1]

    @property
    def effective_fs(self):
        return 1.0 / self.fit()[0]

    def health(self):
        return dict(backsteps=self.backsteps, seq_anomalies=self.seq_anomalies,
                    effective_fs=self.effective_fs if self.ts.n >= 2 else None,
                    seq_deltas=dict(self.seq_deltas.most_common(8)))
