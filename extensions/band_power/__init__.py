"""Band Power — a complete example extension.

Shows: a realtime data hook (on_eeg), a new tab with plots following theme/time range/markers,
a companion file next to the recording (<rec>_bandpower.csv), a menu action and private settings.
"""
import csv
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from musemonitor.core.quality import band_rms
from musemonitor.plugins.api import BaseTab, Extension
from musemonitor.storage.recording import companion_path

BANDS = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30), "gamma": (30, 45)}
SEGMENT_SEC = 2.0          # EEG segment length per computation
HISTORY = 900              # points kept for the tab


def relative_band_power(x, fs):
    """x: (n_ch, n) → % power per band (mean over channels)."""
    p = np.array([band_rms(x, fs, lo, hi) ** 2 for lo, hi in BANDS.values()])   # (band, channel)
    rel = p / np.maximum(p.sum(axis=0, keepdims=True), 1e-12) * 100
    return rel.mean(axis=1)


class BandPowerTab(BaseTab):
    title = "Band power"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4)
        self.info = ctx.plots.muted_label("Waiting for EEG…", wrap=False)
        v.addWidget(self.info)
        pw = ctx.plots.widget(pg.PlotWidget())
        self.plot = ctx.plots.plot(pw.getPlotItem(), marker="eeg", marker_label=True)
        self.plot.setLabel("left", "Relative power (%)"); self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setYRange(0, 100); self.plot.enableAutoRange(axis="y", enable=False)
        ctx.plots.legend(pw.addLegend(offset=(5, 5)))
        self.curves = {b: self.plot.plot(name=b) for b in BANDS}
        v.addWidget(pw, 1)

    def on_analysis(self):
        hist, ref = self.ext.history, self.ctx.store.last_ts["eeg"]
        if not hist or ref is None: return
        t = np.array([h[0] for h in hist]) - ref
        vals = np.array([h[1] for h in hist])
        for i, c in enumerate(self.curves.values()): c.setData(t, vals[:, i])
        self.info.setText("  ·  ".join(f"{b} {v:.0f}%" for b, v in zip(BANDS, vals[-1])))

    def apply_theme(self, th):
        colors = th["eeg"] + [th["xyz"][0]]
        for c, col in zip(self.curves.values(), colors): c.setPen(pg.mkPen(col, width=2))

    def clear(self):
        for c in self.curves.values(): c.clear()


class BandPower(Extension):
    id = "band_power"
    name = "Band Power"
    version = "1.0.0"
    description = ("Relative EEG band power (delta…gamma) over time in a new tab; "
                   "while recording also writes <recording>_bandpower.csv.")
    author = "Muse Monitor"

    def activate(self, app):
        self.history = deque(maxlen=HISTORY)
        self.every = app.setting("update_sec", 1.0, type=float)    # computation period, adjustable via QSettings
        self.pending = 0; self.file = self.writer = None
        app.add_tab(BandPowerTab(app.view, self))
        app.add_action("Band power: clear history", self.history.clear)

    def on_eeg(self, x, ts):
        # Only count samples here (the hook is called ~50 times/s); compute every `every` seconds
        fs = self.app.spec.eeg.fs
        self.pending += x.shape[1]
        if self.pending < self.every * fs: return
        self.pending = 0
        n = int(SEGMENT_SEC * fs)
        if self.app.store.eeg_f.n < n: return
        rel = relative_band_power(self.app.store.eeg_display(n), fs)
        self.history.append((ts, rel))
        if self.writer: self.writer.writerow([f"{ts:.6f}"] + [f"{v:.3f}" for v in rel])

    def on_recording_started(self, path):
        self.file = open(companion_path(path, "bandpower"), "w", newline="")
        self.writer = csv.writer(self.file); self.writer.writerow(["timestamp"] + [f"{b}_pct" for b in BANDS])

    def on_recording_stopped(self):
        if self.file: self.file.close()
        self.file = self.writer = None

    def on_disconnected(self):
        self.history.clear()

    def deactivate(self):
        self.on_recording_stopped()


EXTENSION = BandPower
