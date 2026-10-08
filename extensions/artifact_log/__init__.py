"""Artifact Log — marks noisy EEG with explicit, adjustable rules, next to the signal they were found in.

Analysis runs per 1-second epoch, consecutive and aligned to the EEG sample count. An epoch is analysed
when the NEXT one has arrived (1 s delay), so the zero-phase filters see data on both sides of it and no
filter edge falls inside the analysed second.

    kind       rule (threshold = a setting, see THRESHOLDS)                              marks
    blink      a peak in the frontal-pair mean, 0.5–6 Hz: prominence ≥ blink_uv, width    the blink itself
               blink_min_s…blink_max_s, both frontal channels deflected the same way      (frontal channels)
               (each ≥ blink_pair_frac × blink_uv); either polarity
    emg        RMS in 30–45 Hz (muscle, e.g. jaw clench) > emg_uv                        the epoch, each channel
    amplitude  peak-to-peak in 1–40 Hz > amplitude_uv (frontal channels skipped in an     the epoch, each channel
               epoch that holds a blink)
    flat       standard deviation of the raw signal < flat_uv                           the epoch, each channel
    motion     peak gyroscope magnitude > motion_dps                                     the epoch, "head" (IMU)

The tab draws the EEG of each channel with its artifacts behind it, and the blink detector's own signal
with its thresholds, so every mark can be checked against the data. While recording, every artifact is
written to ``<recording>_artifacts.csv``. Also runs in review windows. Thresholds are starting points,
not validated on many recordings — adjust them with the extension settings (keys below).
"""
import csv

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from scipy.signal import find_peaks, sosfiltfilt

from musemonitor.core.filters import bandpass_sos
from musemonitor.core.quality import band_rms
from musemonitor.plugins.api import BaseTab, Extension
from musemonitor.storage.recording import companion_path

EPOCH_SEC = 1.0
CONTEXT_SEC = 2.0                     # filter context before the analysed epoch (and 1 epoch after it)
BLINK_BAND = (0.5, 6.0)
THRESHOLDS = dict(blink_uv=100.0, blink_min_s=0.08, blink_max_s=0.5, blink_pair_frac=0.4,
                  emg_uv=8.0, amplitude_uv=250.0, flat_uv=1.0, motion_dps=30.0)
UNITS = dict(blink="µV", emg="µV rms", amplitude="µV p-p", flat="µV sd", motion="°/s")
KINDS = ("blink", "emg", "amplitude", "flat", "motion")
COLORS = dict(blink="#1f77b4", emg="#d62728", amplitude="#9467bd", flat="#7f7f7f", motion="#ff7f0e")
HEAD = "head"
ROW_UV = 200.0                        # ±ROW_UV fills a channel row (like the Signals tab's fixed ±200 µV)
TRACE_SPAN = (-0.45, 0.18)            # part of a row (row centre = 0, y grows downward) used by the trace
LANES = (0.22, 0.46)                  # part of a row used by the per-kind lanes
SHADE_ALPHA = 40


def frontal_pair(names):
    """Indices of a left/right frontal pair (AF7/AF8, AF3/AF4, Fp1/Fp2…), or None."""
    front = [i for i, n in enumerate(names) if n.upper().startswith(("AF", "FP"))]
    return (front[0], front[1]) if len(front) >= 2 else None


def blink_signals(raw, fs, pair):
    """(left, right, mean) of the frontal pair band-passed 0.5–6 Hz, zero-phase — what the blink rule uses."""
    x = np.asarray(raw, dtype=float)[list(pair)]
    y = sosfiltfilt(bandpass_sos(fs, *BLINK_BAND, order=2), x - x.mean(axis=1, keepdims=True), axis=1)
    return y[0], y[1], y.mean(axis=0)


def find_blinks(left, right, mean, fs, th):
    """Blink peaks in ``mean``: [(index, amplitude µV, left index, right index)], both polarities."""
    th = {**THRESHOLDS, **(th or {})}
    out = []
    lo, hi = max(1, int(th["blink_min_s"] * fs)), max(2, int(th["blink_max_s"] * fs))
    need = th["blink_pair_frac"] * th["blink_uv"]
    for sign in (1, -1):
        peaks, pr = find_peaks(sign * mean, prominence=th["blink_uv"], width=(lo, hi), rel_height=0.5,
                               distance=max(1, int(0.25 * fs)))
        for k, p in enumerate(peaks):
            if sign * left[p] < need or sign * right[p] < need: continue      # both sides, same direction
            out.append((int(p), float(pr["prominences"][k]), float(pr["left_ips"][k]), float(pr["right_ips"][k])))
    return sorted(out)


def detect_epoch(window, fs, names, start, gyro=None, th=None):
    """Artifacts in the epoch window[:, start:start+n] (n = 1 s). ``window`` carries filter context before and,
    ideally, after the epoch. gyro: (3, k) °/s for the epoch, or None.
    Returns [(channel, kind, value, threshold, offset_s, duration_s)] — offset from the epoch start."""
    th = {**THRESHOLDS, **(th or {})}
    raw = np.asarray(window, dtype=float)
    n = int(round(EPOCH_SEC * fs))
    if start < 0 or raw.shape[1] < start + n: return []
    ep = raw[:, start:start + n]
    centred = raw - raw.mean(axis=1, keepdims=True)
    broad = sosfiltfilt(bandpass_sos(fs, 1.0, 40.0, order=3), centred, axis=1)[:, start:start + n]
    out, blinked = [], False
    pair = frontal_pair(names)
    if pair:
        left, right, mean = blink_signals(raw, fs, pair)
        for p, amp, li, ri in find_blinks(left, right, mean, fs, th):
            if not start <= p < start + n: continue                   # each blink belongs to one epoch
            blinked = True
            half = (ri - li) * 0.75                                   # mark ~1.5× the half-height width
            a, b = max(0.0, p - half), min(raw.shape[1] - 1.0, p + half)
            for i in pair:
                out.append((names[i], "blink", amp, th["blink_uv"], (a - start) / fs, (b - a) / fs))
    emg = band_rms(ep, fs, 30, 45)
    sd = ep.std(axis=1)
    ptp = np.ptp(broad, axis=1)
    for i, name in enumerate(names):
        if sd[i] < th["flat_uv"]:
            out.append((name, "flat", float(sd[i]), th["flat_uv"], 0.0, EPOCH_SEC)); continue
        if emg[i] > th["emg_uv"]: out.append((name, "emg", float(emg[i]), th["emg_uv"], 0.0, EPOCH_SEC))
        if not (blinked and i in pair) and ptp[i] > th["amplitude_uv"]:
            out.append((name, "amplitude", float(ptp[i]), th["amplitude_uv"], 0.0, EPOCH_SEC))
    if gyro is not None and np.size(gyro):
        g = float(np.sqrt((np.asarray(gyro, dtype=float) ** 2).sum(axis=0)).max())
        if g > th["motion_dps"]: out.append((HEAD, "motion", g, th["motion_dps"], 0.0, EPOCH_SEC))
    return out


def _brush(color, alpha=255):
    c = pg.mkColor(color); c.setAlpha(alpha); return pg.mkBrush(c)


class ArtifactTab(BaseTab):
    title = "Artifacts"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4)
        self.info = ctx.plots.muted_label("Waiting for EEG…", wrap=True)
        v.addWidget(self.info)
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)

        # signal + artifacts, one row per channel
        pw = ctx.plots.widget(pg.PlotWidget())
        self.plot = ctx.plots.plot(pw.getPlotItem(), marker="eeg", marker_label=True)
        self.plot.setLabel("bottom", "Time", units="s")
        self.rows = list(ext.names) + ([HEAD] if ext.has_imu else [])
        self.plot.getAxis("left").setTicks([[(i, r) for i, r in enumerate(self.rows)]])
        self.plot.setYRange(-0.55, len(self.rows) - 0.45, padding=0)
        self.plot.setMouseEnabled(x=False, y=False); self.plot.getViewBox().invertY(True)
        self.lane_h = (LANES[1] - LANES[0]) / len(KINDS)
        self.shade = {k: pg.BarGraphItem(x0=[], y0=[], width=[], height=[], brush=_brush(COLORS[k], SHADE_ALPHA), pen=None)
                      for k in KINDS}
        self.lanes = {k: pg.BarGraphItem(x0=[], y0=[], width=[], height=[], brush=_brush(COLORS[k]), pen=None) for k in KINDS}
        for item in (*self.shade.values(), *self.lanes.values()): self.plot.addItem(item)
        self.traces = [self.plot.plot() for _ in self.rows]
        split.addWidget(pw)

        # the blink detector's own signal
        self.pair = frontal_pair(ext.names)
        bw = ctx.plots.widget(pg.PlotWidget())
        self.bplot = ctx.plots.plot(bw.getPlotItem(), marker="eeg")
        self.bplot.setLabel("left", "Blink detector (µV)"); self.bplot.setLabel("bottom", "Time", units="s")
        self.bcurve = self.bplot.plot()
        self.bthr = [pg.InfiniteLine(angle=0, movable=False) for _ in range(2)]
        for line in self.bthr: self.bplot.addItem(line)
        self.bmarks = pg.ScatterPlotItem(symbol="t", size=11)
        self.bplot.addItem(self.bmarks)
        split.addWidget(bw)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 1)
        v.addWidget(split, 1)
        if self.pair:
            a, b = (ext.names[i] for i in self.pair)
            cap = (f"Below: blink detector = mean of {a}/{b}, {BLINK_BAND[0]}–{BLINK_BAND[1]} Hz — the signal the blink "
                   "rule uses; dashed lines = ±blink_uv; ▼ = accepted blinks.")
        else:
            cap = "No frontal channel pair — the blink rule is off for this device."; bw.hide()
        legend = QtWidgets.QLabel("   ".join(f"<span style='color:{COLORS[k]}'>■</span> {k}" for k in KINDS)
                                  + "    — shading behind a trace = an artifact on that channel")
        v.addWidget(legend)
        v.addWidget(ctx.plots.muted_label(cap))

    @staticmethod
    def _trace_y(row, values, scale):
        lo, hi = TRACE_SPAN
        centre, half = row + (lo + hi) / 2, (hi - lo) / 2
        return centre - np.clip(values / scale, -1, 1) * half       # y grows downward

    def on_analysis(self):
        st, fs = self.ctx.store, self.ext.fs
        last, ref = st.last_ts["eeg"], st.time_ref("eeg")
        if last is None or ref is None: return
        T = self.ctx.window_sec
        n = min(st.eeg_f.n, int(T * fs))
        if n >= 2:
            t = st.time_axis("eeg", n)
            y = st.eeg_display(n)
            for i in range(len(self.ext.names)): self.traces[i].setData(t, self._trace_y(i, y[i], ROW_UV))
        if self.ext.has_imu and st.imu.n >= 2:
            m = min(st.imu.n, int(T * self.ctx.spec.imu.fs)); a = self.ctx.spec.n_acc
            g = np.sqrt((np.asarray(st.imu.get(m)[a:a + 3], dtype=float) ** 2).sum(axis=0))
            thr = self.ext.th["motion_dps"]
            self.traces[-1].setData(st.time_axis("imu", m), self._trace_y(len(self.rows) - 1, g - thr, thr))
        recs = self.ext.in_range(last - T - EPOCH_SEC, last)
        for k in KINDS:
            sel = [r for r in recs if r[3] == k and r[2] in self.rows]
            x0, w = [r[0] - ref for r in sel], [r[1] for r in sel]
            rows = [self.rows.index(r[2]) for r in sel]
            self.shade[k].setOpts(x0=x0, width=w, y0=[r - 0.5 for r in rows], height=[1.0] * len(sel))
            j = KINDS.index(k)
            self.lanes[k].setOpts(x0=x0, width=w, y0=[r + LANES[0] + j * self.lane_h for r in rows],
                                  height=[self.lane_h * 0.9] * len(sel))
        self._blink_plot(st, fs, T, ref, last)
        self.info.setText(self.ext.summary(last, T))

    def _blink_plot(self, st, fs, T, ref, last):
        if not self.pair or st.eeg.n < 32: return
        k = min(st.eeg.n, int(T * fs))
        n = min(st.eeg.n, k + int(CONTEXT_SEC * fs))
        _, _, mean = blink_signals(st.eeg.get(n), fs, self.pair)
        t = st.time_axis("eeg", k)
        self.bcurve.setData(t, mean[-k:])
        thr = self.ext.th["blink_uv"]
        self.bthr[0].setPos(thr); self.bthr[1].setPos(-thr)
        centres = sorted({round(r[0] + r[1] / 2, 4) for r in self.ext.in_range(last - T, last) if r[3] == "blink"})
        if centres:
            xs = np.array(centres) - ref
            idx = np.clip(np.searchsorted(np.nan_to_num(t, nan=-np.inf), xs), 0, k - 1)
            self.bmarks.setData(xs, mean[-k:][idx])
        else:
            self.bmarks.clear()

    def apply_theme(self, th):
        for i, c in enumerate(self.traces):
            c.setPen(pg.mkPen(th["eeg"][i % 4] if i < len(self.ext.names) else th["xyz"][0], width=1))
        self.bcurve.setPen(pg.mkPen(th["eeg"][1], width=1.5))
        for line in self.bthr: line.setPen(pg.mkPen(th["muted"], width=1, style=QtCore.Qt.DashLine))
        self.bmarks.setBrush(pg.mkBrush(COLORS["blink"])); self.bmarks.setPen(pg.mkPen(th["bg"], width=1))

    def clear(self):
        for item in (*self.shade.values(), *self.lanes.values()): item.setOpts(x0=[], y0=[], width=[], height=[])
        for c in (*self.traces, self.bcurve): c.clear()
        self.bmarks.clear()


class ArtifactLog(Extension):
    id = "artifact_log"
    name = "Artifact Log"
    version = "1.1.0"
    description = ("Marks noisy EEG (blink, EMG, large amplitude, flat signal, head motion) with explicit thresholds; "
                   "shows them behind each channel's signal, with the blink detector's own trace; writes "
                   "<recording>_artifacts.csv.")
    author = "Muse Monitor"
    category = "Data quality"    # panels go to Analysis ▸ Data quality
    supports_review = True

    @classmethod
    def supports(cls, spec):
        return spec.eeg.n > 0

    def activate(self, app):
        sp = app.spec
        self.fs, self.names = sp.eeg.fs, list(sp.eeg.names)
        self.has_imu = sp.imu.n >= 6
        self.th = {k: float(app.setting(k, v, type=float)) for k, v in THRESHOLDS.items()}
        self.records = []            # (t_start unix, duration, channel, kind, value, threshold)
        self.epochs = self.dirty_epochs = 0
        self.pending = 0
        self.prev_end = None         # end time of the last completed epoch, not yet analysed
        self.file = self.writer = None
        app.add_tab(ArtifactTab(app.view, self))
        app.add_action("Clear list", self.clear)

    def clear(self):
        self.records = []; self.epochs = self.dirty_epochs = 0

    # ---- data ----------------------------------------------------------------------------------------
    def on_eeg(self, x, ts):
        """Count samples; when an epoch completes, analyse the one before it (about once per second)."""
        n = int(round(EPOCH_SEC * self.fs))
        self.pending += x.shape[1]
        while self.pending >= n:
            back = self.pending - n                   # samples received after the end of this epoch
            self.pending -= n
            if self.prev_end is not None: self._analyse(back)
            self.prev_end = ts - back / self.fs

    def _analyse(self, back):
        """Analyse the previous epoch; the epoch that just completed is filter context after it."""
        st, n = self.app.store, int(round(EPOCH_SEC * self.fs))
        pre = int(round(CONTEXT_SEC * self.fs))
        raw = st.eeg.get(min(st.eeg.n, pre + 2 * n + back))
        if back: raw = raw[:, :-back]
        start = raw.shape[1] - 2 * n
        if start < 0: return
        gyro = None
        if self.has_imu and st.imu.n:
            k = int(round(EPOCH_SEC * self.app.spec.imu.fs)); a = self.app.spec.n_acc
            gyro = st.imu.get(2 * k)[a:a + 3, :k]            # roughly the analysed epoch (IMU timing is approximate)
        found = detect_epoch(raw, self.fs, self.names, start, gyro, self.th)
        self.epochs += 1
        if not found: return
        self.dirty_epochs += 1
        t_epoch = self.prev_end - EPOCH_SEC + 1.0 / self.fs
        for ch, kind, value, thr, off, dur in found:
            rec = (t_epoch + off, dur, ch, kind, value, thr)
            self.records.append(rec)
            if self.writer:
                self.writer.writerow([f"{rec[0]:.6f}", f"{dur:.3f}", ch, kind, f"{value:.3f}", f"{thr:g}", UNITS[kind]])

    # ---- queries for the tab ---------------------------------------------------------------------------
    def in_range(self, lo, hi):
        return [r for r in self.records if r[0] + r[1] >= lo and r[0] <= hi]

    def summary(self, last, T):
        recent = self.in_range(last - T, last)
        counts = {k: len({round(r[0], 2) for r in recent if r[3] == k}) for k in KINDS}
        part = "  ·  ".join(f"{k} {c}" for k, c in counts.items())
        clean = 100.0 * (1 - self.dirty_epochs / self.epochs) if self.epochs else 100.0
        where = "Whole recording" if self.app.is_review else "Since connect"
        return (f"In view ({T:.0f} s): {part}    •    {where}: {self.epochs} epochs analysed, {clean:.0f}% clean"
                "    •    marks appear ~1 s late (each second is analysed once the next has arrived)")

    # ---- recording -------------------------------------------------------------------------------------
    def on_recording_started(self, path):
        self.file = open(companion_path(path, "artifacts"), "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["timestamp_start", "duration_s", "channel", "kind", "value", "threshold", "unit"])

    def on_recording_stopped(self):
        if self.file: self.file.close()
        self.file = self.writer = None

    def on_disconnected(self):
        self.pending = 0; self.prev_end = None

    def deactivate(self):
        self.on_recording_stopped()


EXTENSION = ArtifactLog
