"""ReviewStore: a whole recorded session, read through the same interface the tabs use on SignalStore.

The live SignalStore/Ring/StreamClock are untouched. Here every stream is held in read-only arrays
(signals float32, timestamps float64) and a time cursor ``view_end`` (seconds from the session start)
decides what counts as "the newest sample" for each stream, so tabs that read "the newest n samples"
show the window ending at the cursor.

Display time (``t_disp``) is computed once per sample with the live rule (core/timing.py): a linear fit
of raw timestamps against sample index over the preceding ``fit_sec`` seconds, evaluated per block of
BLOCK_SEC. Streams are split into segments where the raw timestamp jumps by more than
``max(GAP_MIN_SEC, GAP_PERIODS / fs)``; a fit never spans a gap, and ``time_axis`` puts NaN at the first
sample after a gap so curves are drawn broken there instead of bridging it.
"""
import copy

import numpy as np

from .. import config as C
from .filters import CausalFilter, remove_dc

STREAMS = ("eeg", "opt", "imu")
GAP_MIN_SEC = 0.25
GAP_PERIODS = 10
BLOCK_SEC = 1.0
FILTER_CHUNK_SEC = 60


def display_time(ts, fs, fit_sec=C.TIME_FIT_SEC):
    """(t_disp, gap_start mask) for raw timestamps ``ts`` — the live display rule applied at every block."""
    ts = np.asarray(ts, dtype=float)
    n = len(ts)
    out = np.empty(n); gap = np.zeros(n, dtype=bool)
    if n == 0: return out, gap
    gap[1:] = np.diff(ts) > max(GAP_MIN_SEC, GAP_PERIODS / fs)
    bounds = [0, *np.flatnonzero(gap).tolist(), n]
    B, fit_n = max(1, int(round(BLOCK_SEC * fs))), max(2, int(fit_sec * fs))
    for a, b in zip(bounds[:-1], bounds[1:]):
        for s in range(a, b, B):
            e = min(s + B, b)
            y = ts[max(a, e - fit_n):e]
            m = len(y)
            period, ref = 1.0 / fs, y[-1]
            if m >= 2:
                x = np.arange(m) - (m - 1) / 2
                p = float((x * (y - y.mean())).sum() / (x * x).sum())
                if np.isfinite(p) and p > 0: period, ref = p, float(y.mean() + p * (m - 1) / 2)
            out[s:e] = ref - period * ((e - 1) - np.arange(s, e))
    return np.maximum.accumulate(out), gap


def _readonly(a):
    a = np.asarray(a); a.flags.writeable = False; return a


class _View:
    """Ring-like read access to one stream: ``n`` = samples up to the cursor, ``get(n)`` = read-only view."""
    def __init__(self, x):
        self.x = _readonly(x); self.cap = x.shape[1]; self.end = 0

    @property
    def n(self):
        return self.end

    def get(self, n=None):
        n = self.end if n is None else max(0, min(int(n), self.end))
        return self.x[:, self.end - n:self.end]

    def clone(self):
        v = copy.copy(self); return v


class _Clock:
    """The parts of core.timing.StreamClock the tabs use, on the session time axis."""
    def __init__(self, store, key):
        self.store, self.key = store, key

    def _view(self):
        return self.store.views[self.key]

    def fit(self):
        st, v = self.store, self._view()
        t, end, fs = st.t_rel[self.key], v.end, st.fs[self.key]
        m = min(end, max(2, int(C.TIME_FIT_SEC * fs)))
        period = (t[end - 1] - t[end - m]) / (m - 1) if m >= 2 and t[end - 1] > t[end - m] else 1.0 / fs
        return period, (st.t0 + t[end - 1]) if end else None

    @property
    def ref(self):
        return self.fit()[1]

    @property
    def effective_fs(self):
        return 1.0 / self.fit()[0]

    def axis(self, n):
        return self.store.time_axis(self.key, n)

    def to_axis(self, idx, n):
        st, end = self.store, self._view().end
        t = st.t_rel[self.key]
        pos = end - n + np.asarray(idx, dtype=float)
        return np.interp(pos, np.arange(len(t)), t) if len(t) else np.zeros_like(pos)

    def health(self):
        return self.store.stream_health[self.key]


class ReviewStore:
    def __init__(self, spec, streams, events=(), fit_sec=C.TIME_FIT_SEC):
        """spec: DeviceSpec; streams: {"eeg"|"opt"|"imu": (raw ts (N,), x (n_ch, N))} — missing streams are empty;
        events: [(unix time, label)]."""
        self.spec = spec
        specs = {"eeg": spec.eeg, "opt": spec.optics, "imu": spec.imu}
        self.fs = {k: specs[k].fs for k in STREAMS}
        self.ts, self.t_rel, self.gap, self.views, self.stream_health = {}, {}, {}, {}, {}
        t_disp = {}
        for k in STREAMS:
            ts, x = streams.get(k, (np.empty(0), np.empty((max(1, specs[k].n), 0), dtype=np.float32)))
            self.ts[k] = _readonly(np.asarray(ts, dtype=float))
            t_disp[k], self.gap[k] = display_time(self.ts[k], self.fs[k], fit_sec)
            self.views[k] = _View(np.asarray(x, dtype=np.float32))
            span = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0
            self.stream_health[k] = dict(backsteps=int((np.diff(ts) < 0).sum()), seq_anomalies=0,
                                         effective_fs=(len(ts) - 1) / span if span > 0 else None, seq_deltas={})
        starts = [t_disp[k][0] for k in STREAMS if len(t_disp[k])]
        if not starts: raise ValueError("the session has no samples")
        self.t0 = min(starts)                                    # session origin (unix s, display clock)
        for k in STREAMS: self.t_rel[k] = _readonly(t_disp[k] - self.t0)
        self.duration = max(float(self.t_rel[k][-1]) for k in STREAMS if len(self.t_rel[k]))
        self.eeg, self.opt, self.imu = self.views["eeg"], self.views["opt"], self.views["imu"]
        self.filter = CausalFilter(spec.eeg.fs)
        self.eeg_f = None
        self._refilter()
        self.clock = {k: _Clock(self, k) for k in STREAMS}
        self.events = sorted((float(t), str(label)) for t, label in events)
        self.view_end = None
        self.last_ts = dict.fromkeys(STREAMS)
        self.latest = dict.fromkeys(STREAMS)
        self.total_opt = self.total_imu = 0
        self.set_view_end(0.0)

    # ---- filtering (whole session, chunk by chunk, same CausalFilter as live) --------------------------
    def _refilter(self):
        raw = self.eeg.x
        if not (self.filter.notch or self.filter.band) or raw.shape[1] == 0:
            out = raw
        else:
            self.filter.reset()
            out = np.empty_like(raw)
            step = max(1, FILTER_CHUNK_SEC * self.fs["eeg"])
            for s in range(0, raw.shape[1], step):
                out[:, s:s + step] = self.filter.process(raw[:, s:s + step].astype(np.float64))
        end = self.eeg_f.end if self.eeg_f is not None else 0
        self.eeg_f = _View(out); self.eeg_f.end = end

    def set_filter(self, notch, band):
        self.filter.configure(notch, band)
        self._refilter()

    def eeg_display(self, n):
        y = self.eeg_f.get(n)
        return y if self.filter.band else remove_dc(y)

    # ---- cursor -------------------------------------------------------------------------------------
    def set_view_end(self, t):
        """Move the cursor to ``t`` seconds after the session start (clamped to the session)."""
        t = float(min(max(t, 0.0), self.duration))
        self.view_end = t
        for k in STREAMS:
            end = int(np.searchsorted(self.t_rel[k], t, side="right"))
            self.views[k].end = end
            if k == "eeg": self.eeg_f.end = end
            self.last_ts[k] = float(self.ts[k][end - 1]) if end else None
        self.latest["eeg"] = self.eeg.x[:, self.eeg.end - 1].copy() if self.eeg.end else None
        self.latest["opt"] = self.opt.x[:4, self.opt.end - 1].copy() if self.opt.end else None
        self.latest["imu"] = self.imu.x[:6, self.imu.end - 1].copy() if self.imu.end else None
        self.total_opt, self.total_imu = self.opt.end, self.imu.end
        return t

    def fork(self):
        """A second cursor over the SAME arrays (no data copied) — used to replay the session to
        extensions while the window's own cursor follows the scrollbar."""
        other = copy.copy(self)
        other.views = {k: v.clone() for k, v in self.views.items()}
        other.eeg, other.opt, other.imu = other.views["eeg"], other.views["opt"], other.views["imu"]
        other.eeg_f = self.eeg_f.clone()
        other.clock = {k: _Clock(other, k) for k in STREAMS}
        other.last_ts, other.latest = dict(self.last_ts), dict(self.latest)
        return other

    # ---- timing (same names as SignalStore) -------------------------------------------------------------
    def time_axis(self, stream, n):
        """Session time (s from the start) of the n samples ending at the cursor; NaN marks a gap start."""
        end = self.views[stream].end
        n = max(0, min(int(n), end))
        t = np.array(self.t_rel[stream][end - n:end])
        t[self.gap[stream][end - n:end]] = np.nan
        return t

    def time_ref(self, stream):
        """Event markers sit at t_event − time_ref, i.e. on the session time axis."""
        return self.t0 if self.last_ts[stream] is not None else None

    def health(self):
        return {k: dict(v) for k, v in self.stream_health.items()}

    def events_in(self, lo, hi):
        """Events whose session time lies in [lo, hi]."""
        return [(t, label) for t, label in self.events if lo <= t - self.t0 <= hi]
