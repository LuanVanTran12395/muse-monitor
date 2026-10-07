import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ... import config as C
from ..widgets.indicators import fill_quality_labels
from .base import BaseTab


class SignalsTab(BaseTab):
    """4-channel EEG (with quality) / raw optics / IMU — draggable vertical splitter."""
    title = "Signals"

    def __init__(self, ctx):
        super().__init__(ctx)
        sp, reg = ctx.spec, ctx.plots
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(4, 4, 4, 4)
        self.opt_label = QtWidgets.QLabel()
        outer.addWidget(self.opt_label)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        outer.addWidget(self.splitter, 1)

        self.graphics = reg.widget(pg.GraphicsLayoutWidget()); self.splitter.addWidget(self.graphics)
        self.plots, self.curves, self.q_labels = [], [], []
        for i, name in enumerate(sp.eeg.names):
            lab = self.graphics.addLabel(row=i, col=0)   # quality readout at the start of each channel
            lab.setFixedWidth(110)
            self.q_labels.append(lab)
            p = reg.plot(self.graphics.addPlot(row=i, col=1), marker="eeg", marker_label=(i == 0))
            p.setLabel("left", f"{name} (µV)")
            p.getAxis("left").enableAutoSIPrefix(False)
            p.setClipToView(True); p.setDownsampling(auto=True, mode="peak")
            if i == sp.eeg.n - 1: p.setLabel("bottom", "Time", units="s")
            else: p.hideAxis("bottom")
            if i: p.setXLink(self.plots[0])
            self.plots.append(p); self.curves.append(p.plot())
        self.apply_scale(True)

        self.opt_plot = reg.widget(pg.PlotWidget())
        self.opt_plot.setMinimumHeight(120)
        self.opt_plot.setLabel("left", "Optical (mean-removed)")
        self.opt_plot.setLabel("bottom", "Time", units="s")
        reg.plot(self.opt_plot.getPlotItem(), marker="opt")
        self.opt_plot.setDownsampling(auto=True, mode="peak"); self.opt_plot.setClipToView(True)
        self.opt_curves = [self.opt_plot.plot() for _ in range(sp.optics.n)]
        self.splitter.addWidget(self.opt_plot)

        # IMU: accel + gyro side by side
        self.imu_label = QtWidgets.QLabel()
        imu_box = QtWidgets.QWidget(); imu_v = QtWidgets.QVBoxLayout(imu_box); imu_v.setContentsMargins(0, 0, 0, 0)
        imu_v.addWidget(self.imu_label)
        imu_row = QtWidgets.QHBoxLayout()
        self.acc_plot, self.gyr_plot = reg.widget(pg.PlotWidget()), reg.widget(pg.PlotWidget())
        for pw, lab in ((self.acc_plot, "Accel (g)"), (self.gyr_plot, "Gyro (°/s)")):
            pw.setMinimumHeight(110); pw.setLabel("left", lab); pw.setLabel("bottom", "Time", units="s")
            reg.plot(pw.getPlotItem(), marker="imu")
            reg.legend(pw.addLegend(offset=(5, 5)))
            imu_row.addWidget(pw)
        self.acc_curves = [self.acc_plot.plot(name="xyz"[i]) for i in range(sp.n_acc)]
        self.gyr_curves = [self.gyr_plot.plot(name="xyz"[i]) for i in range(sp.imu.n - sp.n_acc)]
        imu_v.addLayout(imu_row)
        self.splitter.addWidget(imu_box)
        imu_box.setVisible(sp.imu.n > 0)                  # device without an IMU → hidden
        self.splitter.setStretchFactor(0, 5); self.splitter.setStretchFactor(1, 2); self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([560, 200, 200])
        self.clear()

    def apply_scale(self, fixed):
        for p in self.plots:
            p.enableAutoRange(axis="y", enable=not fixed)
            if fixed: p.setYRange(-C.EEG_FIXED_UV, C.EEG_FIXED_UV, padding=0)

    def set_quality(self, qs):
        fill_quality_labels(self.q_labels, self.ctx.spec.eeg.names, qs, self.ctx.th)

    def on_frame(self):
        st, sp, T = self.ctx.store, self.ctx.spec, self.ctx.window_sec
        n = min(st.eeg_f.n, int(T * sp.eeg.fs))
        if n >= 2:
            t = st.time_axis("eeg", n)
            y = st.eeg_display(n)
            for i, c in enumerate(self.curves): c.setData(t, y[i])
        no = min(st.opt.n, int(T * sp.optics.fs))
        if sp.optics.n and no >= 2:
            o = st.opt.get(no)
            to = st.time_axis("opt", no)
            o = o - o.mean(axis=1, keepdims=True)
            for i, c in enumerate(self.opt_curves): c.setData(to, o[i])
        nm = min(st.imu.n, int(T * sp.imu.fs))
        if sp.imu.n and nm >= 2:
            m = st.imu.get(nm)
            tm = st.time_axis("imu", nm)
            for i, c in enumerate(self.acc_curves): c.setData(tm, m[i])
            for i, c in enumerate(self.gyr_curves): c.setData(tm, m[sp.n_acc + i])

    def update_texts(self):
        st, sp = self.ctx.store, self.ctx.spec
        o, m = st.latest["opt"], st.latest["imu"]
        if o is not None:
            preview = "  ".join(f"{n} {v:.0f}" for n, v in zip(sp.optics.names, o))
            self.opt_label.setText(f"Optics/PPG: {st.total_opt:,} samples • {sp.optics.fs} Hz • {sp.optics.n} ch • {preview}")
        if m is not None:
            a, g = m[:3], m[3:6]
            self.imu_label.setText(f"IMU: {st.total_imu:,} samples • {sp.imu.fs} Hz • "
                                   f"acc [{a[0]:+.2f} {a[1]:+.2f} {a[2]:+.2f}] g • "
                                   f"gyro [{g[0]:+.1f} {g[1]:+.1f} {g[2]:+.1f}] °/s")

    def apply_theme(self, th):
        for i, c in enumerate(self.curves): c.setPen(pg.mkPen(th["eeg"][i % 4], width=1))
        n_opt = max(1, self.ctx.spec.optics.n)
        for i, c in enumerate(self.opt_curves):
            c.setPen(pg.intColor(i, n_opt, maxValue=th["opt_value"], minValue=th["opt_value"]))
        for i, c in enumerate(self.acc_curves + self.gyr_curves): c.setPen(pg.mkPen(th["xyz"][i % 3], width=1))

    def clear(self):
        sp = self.ctx.spec
        self.imu_label.setText(f"IMU: — (target {sp.imu.fs} Hz)")
        self.opt_label.setText(f"Optics/PPG: — (target {sp.optics.fs} Hz, {sp.optics.n} ch)")
        for c in self.curves + self.opt_curves + self.acc_curves + self.gyr_curves: c.clear()
