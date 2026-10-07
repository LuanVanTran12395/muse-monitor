"""SignalStore: buffers for every stream + the filtered EEG + per-stream timing.

The single "data source" the UI reads; fed by the worker through add_*().
``spec`` only needs .eeg/.optics/.imu with attributes fs and n (see device.spec).

Timing: raw timestamps are kept in ``clock[stream]`` (core.timing.StreamClock) and never
modified. Plots and event markers use ``time_axis()`` / ``time_ref()`` — one shared time-fit rule."""
from .. import config as C
from .buffers import Ring
from .filters import CausalFilter, remove_dc
from .timing import StreamClock, ts_vector

STREAMS = ("eeg", "opt", "imu")


class SignalStore:
    def __init__(self, spec, max_window_sec=C.MAX_WINDOW_SEC, opt_hist_sec=C.OPT_HIST_SEC):
        self.spec = spec
        self.eeg = Ring(spec.eeg.n, spec.eeg.fs * max_window_sec)       # raw
        self.eeg_f = Ring(spec.eeg.n, spec.eeg.fs * max_window_sec)     # causally filtered, continuous in time
        self.opt = Ring(max(1, spec.optics.n), spec.optics.fs * opt_hist_sec)
        self.imu = Ring(max(1, spec.imu.n), spec.imu.fs * max_window_sec)
        self.fs = {"eeg": spec.eeg.fs, "opt": spec.optics.fs, "imu": spec.imu.fs}
        self.clock = {k: StreamClock(self.fs[k], getattr(self, k).cap, C.TIME_FIT_SEC) for k in STREAMS}
        self.filter = CausalFilter(spec.eeg.fs)
        self.clear()

    def clear(self):
        for r in (self.eeg, self.eeg_f, self.opt, self.imu): r.clear()
        for c in self.clock.values(): c.clear()
        self.filter.reset()
        self.total_opt = self.total_imu = 0
        self.last_ts = dict.fromkeys(STREAMS)    # RAW timestamp of the last sample of each stream
        self.latest = dict.fromkeys(STREAMS)     # newest values for the text readouts

    # ---- data input ------------------------------------------------------------
    # ts: vector of raw per-sample timestamps (or a scalar = timestamp of the last sample, legacy)
    # seq: per-sample package_num or None
    def _clock(self, key, x, ts, seq):
        ts = ts_vector(ts, x.shape[1], self.fs[key])
        self.clock[key].add(ts, seq)
        self.last_ts[key] = float(ts[-1])

    def add_eeg(self, x, ts, seq=None):
        self.eeg.extend(x)
        self.eeg_f.extend(self.filter.process(x))
        self._clock("eeg", x, ts, seq); self.latest["eeg"] = x[:, -1].copy()

    def add_optics(self, x, ts, seq=None):
        self.opt.extend(x)
        self.total_opt += x.shape[1]
        self._clock("opt", x, ts, seq); self.latest["opt"] = x[:4, -1].copy()

    def add_imu(self, x, ts, seq=None):
        self.imu.extend(x)
        self.total_imu += x.shape[1]
        self._clock("imu", x, ts, seq); self.latest["imu"] = x[:6, -1].copy()

    # ---- timing ------------------------------------------------------------------
    def time_axis(self, stream, n):
        """x axis (s, last sample = 0) for the newest n samples of the stream."""
        return self.clock[stream].axis(n)

    def time_ref(self, stream):
        """Absolute time at x = 0 — event markers sit at t_event − time_ref."""
        return self.clock[stream].ref if self.last_ts[stream] is not None else None

    def health(self):
        return {k: c.health() for k, c in self.clock.items()}

    # ---- EEG filtering ------------------------------------------------------------------
    def set_filter(self, notch, band):
        """Filter settings changed → refilter the raw buffer with the new filter."""
        self.filter.configure(notch, band); self.eeg_f.clear()
        if self.eeg.n: self.eeg_f.extend(self.filter.process(self.eeg.get()))

    def eeg_display(self, n):
        """The newest n EEG samples for display; DC removed when the band-pass is off (raw / notch-only)."""
        y = self.eeg_f.get(n)
        return y if self.filter.band else remove_dc(y)
