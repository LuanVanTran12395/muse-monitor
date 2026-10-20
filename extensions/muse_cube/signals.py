"""The tab's live EOG / EMG panel: what the blink and jaw-clench detectors hear, with thresholds and filters by hand.

    EOG   the blink channel after the band-pass (TP9 / TP10 by default; blink polarity up), the blink threshold
          (a dashed line, draggable), single blinks ▲ and recognised double blinks ★
    EMG   the jaw-clench RMS in its band (30–45 Hz), its threshold (draggable) and recognised clenches ★

Under each plot: the threshold (µV), "calibrated value", and the filter band. Lower a threshold when a deliberate
blink / clench does not cross it; raise it when something else does. Change a band to make the wanted signal stand out
(e.g. EOG 0.5–5 Hz for slow, large blinks; EMG away from the 50 Hz mains). A threshold set by hand also works without
the calibration.
"""
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

WINDOW_S = 6.0


class SignalsBox(QtWidgets.QGroupBox):
    def __init__(self, ctx, ext):
        super().__init__("EOG / EMG — blink ×2 ↻ and jaw clench ↺ (live)")
        self.ext = ext
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(ctx.plots.muted_label(
            "What the detectors hear, last 6 s. Drag a dashed threshold line or type a value: lower it when a "
            "deliberate blink / clench stays under it, raise it when something else crosses it. Change a filter band to "
            "make the signal stand out (EOG 0.5–5 Hz for slow blinks; EMG avoiding 50 Hz). Re-calibrate after a band "
            "change, or adjust the threshold."))
        gfx = ctx.plots.widget(pg.GraphicsLayoutWidget())
        gfx.setMinimumHeight(280)
        gfx.setAccessibleName("Live EOG and EMG with thresholds")
        self.plots, self.curves, self.lines, self.marks = {}, {}, {}, {}
        for row, (kind, label) in enumerate((("eog", "EOG µV"), ("emg", "EMG RMS µV"))):
            pl = ctx.plots.plot(gfx.addPlot(row=row, col=0), timed=False)
            pl.setLabel("left", label); pl.setXRange(-WINDOW_S, 0, padding=0)
            pl.getAxis("left").enableAutoSIPrefix(False)
            if row == 1: pl.setLabel("bottom", "Time", units="s")
            else: pl.hideAxis("bottom")
            self.plots[kind] = pl
            self.curves[kind] = pl.plot(pen=pg.mkPen("#8fa3ff" if kind == "eog" else "#7dd3a0", width=1.5))
            line = pg.InfiniteLine(angle=0, movable=True, pen=pg.mkPen("#ffc45c", width=1.5, style=QtCore.Qt.DashLine),
                                   hoverPen=pg.mkPen("#ffdd99", width=2.5))
            line.hide(); pl.addItem(line)
            line.sigPositionChangeFinished.connect(lambda ln, k=kind: self._line_moved(k, ln))
            self.lines[kind] = line
            self.marks[kind] = pg.ScatterPlotItem(size=14, symbol="star", brush=pg.mkBrush("#ffc45c"), pen=None)
            pl.addItem(self.marks[kind])
        self.single = pg.ScatterPlotItem(size=9, symbol="t1", brush=pg.mkBrush("#8fa3ff"), pen=None)
        self.plots["eog"].addItem(self.single)
        self.plots["emg"].setXLink(self.plots["eog"])
        v.addWidget(gfx)
        self.thr, self.lo, self.hi, self.reset, self.state = {}, {}, {}, {}, {}
        rows = (("eog", "Blink threshold", (1, 3000, 5, 0), (0.1, 10, 0.1), (1, 40, 0.5)),
                ("emg", "Clench threshold", (0.1, 1000, 0.5, 1), (5, 110, 1), (10, 120, 1)))
        for kind, name, (tmin, tmax, tstep, dec), (lmin, lmax, lstep), (hmin, hmax, hstep) in rows:
            r = QtWidgets.QHBoxLayout()
            thr = QtWidgets.QDoubleSpinBox(); thr.setRange(tmin, tmax); thr.setSingleStep(tstep); thr.setDecimals(dec)
            thr.setSuffix(" µV"); thr.setKeyboardTracking(False)
            reset = QtWidgets.QPushButton("Calibrated value")
            lo = QtWidgets.QDoubleSpinBox(); lo.setRange(lmin, lmax); lo.setSingleStep(lstep); lo.setDecimals(1)
            hi = QtWidgets.QDoubleSpinBox(); hi.setRange(hmin, hmax); hi.setSingleStep(hstep); hi.setDecimals(1)
            for sp in (lo, hi): sp.setSuffix(" Hz"); sp.setKeyboardTracking(False)
            state = QtWidgets.QLabel("—")
            r.addWidget(QtWidgets.QLabel(name + ":")); r.addWidget(thr); r.addWidget(reset)
            r.addSpacing(16); r.addWidget(QtWidgets.QLabel("Filter:")); r.addWidget(lo); r.addWidget(QtWidgets.QLabel("–"))
            r.addWidget(hi); r.addSpacing(12); r.addWidget(state); r.addStretch()
            v.addLayout(r)
            self.thr[kind], self.lo[kind], self.hi[kind], self.reset[kind], self.state[kind] = thr, lo, hi, reset, state
            thr.valueChanged.connect(lambda val, k=kind: self._typed(k, val))
            reset.clicked.connect(lambda _=False, k=kind: (ext.controller.reset_threshold(k), self.sync(force=True)))
            lo.valueChanged.connect(lambda _v, k=kind: self._band(k))
            hi.valueChanged.connect(lambda _v, k=kind: self._band(k))
        self.timer = QtCore.QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.sync(force=True)

    # ---- edits ---------------------------------------------------------------------------------------------------
    def _typed(self, kind, value):
        self.ext.controller.set_threshold(kind, value)
        self.lines[kind].setValue(value)

    def _line_moved(self, kind, line):
        value = max(self.thr[kind].minimum(), float(line.value()))
        if self.ext.controller.set_threshold(kind, value):
            self.thr[kind].blockSignals(True); self.thr[kind].setValue(value); self.thr[kind].blockSignals(False)

    def _band(self, kind):
        lo, hi = self.lo[kind].value(), self.hi[kind].value()
        try:
            ok = lo < hi and self.ext.controller.set_band(kind, lo, hi)
        except ValueError:
            ok = False
        self.state[kind].setText(("band " if ok else "invalid band ") + f"{lo:g}–{hi:g} Hz" +
                                 (" — re-calibrate or adjust the threshold" if ok else ""))

    def sync(self, force=False):
        """Controls ← controller (after a calibration, or at start)."""
        c = self.ext.controller
        for kind in ("eog", "emg"):
            present = (c.eyes if kind == "eog" else c.jaw) is not None
            for wdg in (self.thr[kind], self.lo[kind], self.hi[kind], self.reset[kind]): wdg.setEnabled(present)
            if not present:
                self.state[kind].setText("unavailable (no EEG / estimator)"); continue
            thr, cal = c.threshold(kind), c.calibrated_threshold(kind)
            if thr is not None and (force or not self.thr[kind].hasFocus()):
                self.thr[kind].blockSignals(True); self.thr[kind].setValue(thr); self.thr[kind].blockSignals(False)
            self.reset[kind].setEnabled(cal is not None)
            if force:
                lo, hi = c.band(kind)
                for sp, val in ((self.lo[kind], lo), (self.hi[kind], hi)):
                    sp.blockSignals(True); sp.setValue(val); sp.blockSignals(False)
            self.state[kind].setText(("calibrated " + f"{cal:.1f} µV" if cal is not None else "not calibrated") +
                                     (f" · now {thr:.1f} µV" if thr is not None else " · set a threshold to use it"))

    # ---- live ----------------------------------------------------------------------------------------------------
    def refresh(self):
        if not self.isVisible(): return
        c = self.ext.controller
        for kind, view in (("eog", c.eog_view(WINDOW_S)), ("emg", c.emg_view(WINDOW_S))):
            line = self.lines[kind]
            if view is None:
                self.curves[kind].setData([], []); continue
            t, y, thr, *marks = view
            end = t[-1] if len(t) else 0.0
            self.curves[kind].setData(t - end, y)
            if thr is not None:
                line.show()
                if not line.moving: line.setValue(thr)
            if kind == "eog":
                singles, doubles = marks
                self._scatter(self.single, singles, end, y, t)
                self._scatter(self.marks["eog"], doubles, end, y, t)
            else:
                self._scatter(self.marks["emg"], marks[0], end, y, t)
        self.sync()

    @staticmethod
    def _scatter(item, times, end, y, t):
        pts = [(x - end, float(np.interp(x, t, y))) for x in times if end - WINDOW_S <= x <= end]
        item.setData([p[0] for p in pts], [p[1] for p in pts])
