import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ... import config as C
from ...core.spectral import stft_power
from .base import BaseTab


class PsdTab(BaseTab):
    """Spectrogram (PSD over time) per EEG channel; choose window / step / max freq."""
    title = "EEG PSD"

    def __init__(self, ctx):
        super().__init__(ctx)
        sp, reg, st = ctx.spec, ctx.plots, ctx.settings
        self.levels = None
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4)
        row = QtWidgets.QHBoxLayout()
        self.win = QtWidgets.QDoubleSpinBox(); self.win.setRange(0.25, 8); self.win.setSingleStep(0.25)
        self.win.setDecimals(2); self.win.setSuffix(" s"); self.win.setValue(float(st.value("psd_win", C.PSD_WIN_SEC)))
        self.step = QtWidgets.QDoubleSpinBox(); self.step.setRange(0.05, 4); self.step.setSingleStep(0.05)
        self.step.setDecimals(2); self.step.setSuffix(" s"); self.step.setValue(float(st.value("psd_step", C.PSD_STEP_SEC)))
        self.fmax = QtWidgets.QSpinBox(); self.fmax.setRange(5, sp.eeg.fs // 2); self.fmax.setSuffix(" Hz")
        self.fmax.setValue(int(st.value("psd_fmax", C.PSD_FMAX_HZ)))
        for lab, w in (("Window:", self.win), ("Step:", self.step), ("Max freq:", self.fmax)):
            row.addWidget(QtWidgets.QLabel(lab)); row.addWidget(w); row.addSpacing(10)
        self.info = reg.muted_label("", wrap=False)
        row.addWidget(self.info); row.addStretch()
        v.addLayout(row)

        self.gfx = reg.widget(pg.GraphicsLayoutWidget())
        self.plots, self.imgs = [], []
        for i, name in enumerate(sp.eeg.names):
            p = reg.plot(self.gfx.addPlot(row=i, col=0), marker="eeg", marker_label=(i == 0), on_image=True)
            p.showGrid(x=True, y=True, alpha=.15)
            img = pg.ImageItem(); p.addItem(img)
            p.setLabel("left", f"{name} (Hz)")
            p.enableAutoRange(axis="y", enable=False); p.setYRange(0, self.fmax.value(), padding=0)
            if i == sp.eeg.n - 1: p.setLabel("bottom", "Time", units="s")
            else: p.hideAxis("bottom")
            if i: p.setXLink(self.plots[0])
            self.plots.append(p); self.imgs.append(img)
        self.cbar = pg.ColorBarItem(values=(-10, 30), colorMap=pg.colormap.get("inferno"), interactive=False)
        self.cbar.setImageItem(self.imgs)
        self.gfx.addItem(self.cbar, row=0, col=1, rowspan=sp.eeg.n)
        v.addWidget(self.gfx, 1)
        for w in (self.win, self.step, self.fmax): w.valueChanged.connect(self._params_changed)
        self._params_changed()

    def _params_changed(self):
        for p in self.plots: p.setYRange(0, self.fmax.value(), padding=0)
        st = self.ctx.settings
        st.setValue("psd_win", self.win.value()); st.setValue("psd_step", self.step.value())
        st.setValue("psd_fmax", self.fmax.value())
        self.levels = None
        if self.isVisible(): self.on_analysis()

    def on_view_changed(self):
        self.levels = None

    def on_analysis(self):
        fs, st = self.ctx.spec.eeg.fs, self.ctx.store
        win = max(8, int(round(self.win.value() * fs)))
        step = max(1, int(round(self.step.value() * fs)))
        n = min(st.eeg_f.n, int(self.ctx.window_sec * fs))
        r = stft_power(st.eeg_display(n), fs, win, step, self.fmax.value())
        res = f"Δf = {fs / win:.2f} Hz"
        if r is None:
            self.info.setText(f"{res} · waiting for ≥ {win / fs:.2f} s of EEG…")
            for img in self.imgs: img.clear()
            return
        tc, f, P, step_used = r
        self.info.setText(res + (f" · step raised to {step_used / fs:.2f} s (CPU limit)" if step_used != step else ""))
        db = 10 * np.log10(P + 1e-12)
        lo, hi = np.percentile(db, [5, 99.5])
        if self.levels is None: self.levels = (lo, hi)
        else: self.levels = tuple(0.8 * a + 0.2 * b for a, b in zip(self.levels, (lo, hi)))   # avoid flicker
        df = f[1] - f[0] if len(f) > 1 else 1.0
        clock = st.clock["eeg"]
        x0 = float(clock.to_axis(tc[0] * fs + n, n))          # first segment centre → shared time axis
        dt = step_used * clock.fit()[0]
        rect = QtCore.QRectF(x0 - dt / 2, -df / 2, len(tc) * dt, len(f) * df)
        for c, img in enumerate(self.imgs):
            img.setImage(db[c], autoLevels=False); img.setRect(rect)
        self.cbar.setLevels(self.levels)

    def apply_theme(self, th):
        self.cbar.axis.setPen(th["fg"]); self.cbar.axis.setTextPen(th["fg"])
        self.cbar.axis.setLabel("Power (dB re 1 µV²/Hz)", color=th["fg"])
        self.cbar.setColorMap(pg.colormap.get(th["cmap"]))

    def clear(self):
        self.levels = None
        for img in self.imgs: img.clear()
