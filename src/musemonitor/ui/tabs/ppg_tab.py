import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from ... import config as C
from ...core.fnirs import mbll
from ...core.ppg import best_channel, clean_ibi, hrv_metrics, ppg_beats
from .base import BaseTab

# (key in hrv_metrics, title, unit, tooltip, format)
TILES = (
    ("hr", "Mean HR", "bpm", "Mean heart rate over the HRV window", "{:.0f}"),
    ("rmssd", "RMSSD", "ms", "Root mean square of successive IBI differences", "{:.0f}"),
    ("sdnn", "SDNN", "ms", "Standard deviation of inter-beat intervals", "{:.0f}"),
    ("sdhr", "SDHR", "bpm", "Standard deviation of instantaneous heart rate", "{:.1f}"),
    ("prr50", "pRR50", "%", "% of successive IBI differences > 50 ms", "{:.0f}"),
    ("prr20", "pRR20", "%", "% of successive IBI differences > 20 ms", "{:.0f}"),
    ("n", "Beats", "", "Valid beats in the HRV window", "{:d}"),
)


def _fmt(val, fmt):
    if val is None or (isinstance(val, float) and not np.isfinite(val)): return "—"
    return fmt.format(val)


class PpgTab(BaseTab):
    """PPG + heart rate over time → HRV metrics → ΔHbO/ΔHbR (fNIRS)."""
    title = "PPG · HRV · fNIRS"

    def __init__(self, ctx):
        super().__init__(ctx)
        sp, reg, st = ctx.spec, ctx.plots, ctx.settings
        self.auto_ch = None; self.auto_t = 0.0; self.tiles_t = 0.0
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4)

        row = QtWidgets.QHBoxLayout()
        self.ch = QtWidgets.QComboBox(); self.ch.addItems(["Auto (clearest pulse)"] + sp.optics.names)
        self.hrv_win = QtWidgets.QSpinBox(); self.hrv_win.setRange(10, 300); self.hrv_win.setSuffix(" s")
        self.hrv_win.setValue(int(st.value("hrv_win", C.HRV_WIN_SEC)))
        self.hrv_win.valueChanged.connect(lambda val: st.setValue("hrv_win", val))
        row.addWidget(QtWidgets.QLabel("PPG channel:")); row.addWidget(self.ch); row.addSpacing(10)
        row.addWidget(QtWidgets.QLabel("HRV window:")); row.addWidget(self.hrv_win); row.addSpacing(10)
        self.info = reg.muted_label("", wrap=False)
        row.addWidget(self.info); row.addStretch()
        v.addLayout(row)

        self.gfx = reg.widget(pg.GraphicsLayoutWidget())
        self.ppg_plot = reg.plot(self.gfx.addPlot(row=0, col=0), marker="opt", marker_label=True)
        self.ppg_plot.setLabel("left", "PPG (band-passed)"); self.ppg_plot.hideAxis("bottom")
        self.ppg_curve = self.ppg_plot.plot()
        self.beat_scatter = pg.ScatterPlotItem(size=7, pen=None); self.ppg_plot.addItem(self.beat_scatter)
        self.hr_plot = reg.plot(self.gfx.addPlot(row=1, col=0), marker="opt")
        self.hr_plot.setLabel("left", "Heart rate (bpm)"); self.hr_plot.setLabel("bottom", "Time", units="s")
        self.hr_plot.setXLink(self.ppg_plot)
        self.hr_curve = self.hr_plot.plot(symbol="o", symbolSize=4)
        v.addWidget(self.gfx, 3)

        tiles = QtWidgets.QHBoxLayout(); self.tiles = {}; self.tile_frames = []
        for key, title, unit, tip, _ in TILES:
            fr = QtWidgets.QFrame(); fr.setObjectName("tile"); fr.setToolTip(tip)
            fv = QtWidgets.QVBoxLayout(fr); fv.setContentsMargins(10, 6, 10, 6); fv.setSpacing(0)
            t = reg.muted_label(title + (f" ({unit})" if unit else ""), wrap=False)
            val = QtWidgets.QLabel("—"); val.setStyleSheet("font-size: 20pt; font-weight: 600")
            fv.addWidget(t); fv.addWidget(val)
            tiles.addWidget(fr); self.tiles[key] = val; self.tile_frames.append(fr)
        v.addLayout(tiles)

        frow = QtWidgets.QHBoxLayout()
        # device (profile) defaults if any: wavelength pair, labels and extinction coefficients
        fn = getattr(ctx.profile, "fnirs", None) or {}
        self.fn_ext = fn.get("ext")
        pair = fn.get("pair", C.FNIRS_CH)
        labels = fn.get("labels", ("fNIRS  λ 730 nm:", "λ 850 nm:"))
        self.fn_ch1, self.fn_ch2 = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        for cb, d in ((self.fn_ch1, pair[0]), (self.fn_ch2, pair[1])):
            cb.addItems(sp.optics.names); cb.setCurrentIndex(min(d, max(0, sp.optics.n - 1)))
        self.fn_dpf = QtWidgets.QDoubleSpinBox(); self.fn_dpf.setRange(1, 15); self.fn_dpf.setValue(fn.get("dpf", C.FNIRS_DPF))
        self.fn_dpf.setSingleStep(0.5)
        self.fn_dist = QtWidgets.QDoubleSpinBox(); self.fn_dist.setRange(0.5, 6); self.fn_dist.setValue(fn.get("dist", C.FNIRS_DIST_CM))
        self.fn_dist.setSingleStep(0.1); self.fn_dist.setSuffix(" cm")
        for lab, w in ((labels[0], self.fn_ch1), (labels[1], self.fn_ch2), ("DPF:", self.fn_dpf), ("Distance:", self.fn_dist)):
            frow.addWidget(QtWidgets.QLabel(lab)); frow.addWidget(w); frow.addSpacing(8)
        frow.addWidget(reg.muted_label("Modified Beer–Lambert, baseline = mean of shown window, low-pass 0.5 Hz."))
        frow.addStretch()
        v.addLayout(frow)
        self.fn_plot = reg.widget(pg.PlotWidget())
        self.fn_plot.setLabel("left", "Δ concentration (µM)"); self.fn_plot.setLabel("bottom", "Time", units="s")
        reg.plot(self.fn_plot.getPlotItem(), marker="opt")
        reg.legend(self.fn_plot.addLegend(offset=(5, 5)))
        self.hbo_curve = self.fn_plot.plot(name="HbO"); self.hbr_curve = self.fn_plot.plot(name="HbR")
        v.addWidget(self.fn_plot, 2)

    def _channel(self, o, fs):
        if self.ch.currentIndex() > 0: return self.ch.currentIndex() - 1
        now = time.monotonic()
        if self.auto_ch is None or now - self.auto_t > C.PPG_AUTO_EVERY_SEC:
            self.auto_ch = best_channel(o[:, -C.PPG_AUTO_SPAN_SEC * fs:], fs); self.auto_t = now
        return self.auto_ch

    def on_analysis(self):
        sp, st = self.ctx.spec, self.ctx.store
        fs = sp.optics.fs
        T, W = self.ctx.window_sec, self.hrv_win.value()
        n = min(st.opt.n, int((max(T, W) + 3) * fs))     # +3 s padding keeps the filter edge outside the view
        if not sp.optics.n or n < 4 * fs:
            self.info.setText("Waiting for ≥ 4 s of optical data…"); return
        o = st.opt.get(n)
        ch = self._channel(o, fs)

        # PPG + heart rate. HRV uses time from SAMPLE COUNT / nominal fs (the device sampling clock is
        # steadier than host timestamps); the plot uses time_axis so it matches the event markers.
        y, pk = ppg_beats(o[ch], fs)
        t = st.time_axis("opt", n)
        tb = (pk - n) / fs
        xb = st.clock["opt"].to_axis(pk, n)
        nT = min(n, int(T * fs))
        self.ppg_curve.setData(t[-nT:], y[-nT:])
        vis = tb >= -T
        self.beat_scatter.setData(xb[vis], y[np.round(pk[vis]).astype(int)])
        tib, ibi, ok = clean_ibi(tb)
        shown = ok & (tib >= -T)
        self.hr_curve.setData(xb[1:][shown], 60.0 / ibi[shown])

        # HRV — text readouts: twice per second
        inw = tib >= -W
        m = hrv_metrics(ibi[inw], ok[inw])
        now = time.monotonic()
        if now - self.tiles_t >= C.TEXT_MS / 1000:
            self.tiles_t = now
            self.info.setText(f"Using {sp.optics.names[ch]} · {vis.sum()} beats in view")
            for key, *_, fmt in TILES:
                self.tiles[key].setText(_fmt(None if m is None else m[key], fmt))

        # fNIRS
        mT = min(n, int((T + 3) * fs))
        c1, c2 = self.fn_ch1.currentIndex(), self.fn_ch2.currentIndex()
        hb = mbll(o[c1, -mT:], o[c2, -mT:], fs, self.fn_dpf.value(), self.fn_dist.value(), ext=self.fn_ext)[:, -nT:]
        self.hbo_curve.setData(t[-nT:], hb[0]); self.hbr_curve.setData(t[-nT:], hb[1])

    def apply_theme(self, th):
        self.ppg_curve.setPen(pg.mkPen(th["ppg"], width=1.5))
        self.beat_scatter.setBrush(pg.mkBrush(th["beat"]))
        self.hr_curve.setPen(pg.mkPen(th["hr"], width=2))
        self.hr_curve.setSymbolBrush(pg.mkBrush(th["hr"])); self.hr_curve.setSymbolPen(None)
        self.hbo_curve.setPen(pg.mkPen(th["hbo"], width=2)); self.hbr_curve.setPen(pg.mkPen(th["hbr"], width=2))
        for fr in self.tile_frames:
            fr.setStyleSheet(f"QFrame#tile {{ border: 1px solid {th['border']}; border-radius: 6px; background: {th['base']}; }}")

    def clear(self):
        self.auto_ch = None
        for c in (self.ppg_curve, self.hr_curve, self.hbo_curve, self.hbr_curve): c.clear()
        self.beat_scatter.clear()
        for lab in self.tiles.values(): lab.setText("—")
