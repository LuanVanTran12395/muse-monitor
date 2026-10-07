"""Experimental blink and sustained eye-closure avatar for Muse S Athena."""

import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from scipy.signal import butter, find_peaks, sosfilt, sosfilt_zi, welch

from musemonitor import config as app_config
from musemonitor.core.buffers import Ring
from musemonitor.plugins.api import BaseTab, Extension

HISTORY_SEC = app_config.MAX_WINDOW_SEC + 10      # detection history kept for the plots
ALPHA_EVERY_SEC = 0.45


def relative_alpha(channels, fs):
    """Mean 8–13 Hz / 4–30 Hz power for TP9 and TP10; returns None on bad input."""
    x = np.asarray(channels, dtype=float)
    if x.ndim != 2 or x.shape[0] < 1 or x.shape[1] < 2 * fs:
        return None
    x = x[:, -min(x.shape[1], int(4 * fs)):]
    if not np.all(np.isfinite(x)) or np.max(np.std(x, axis=1)) > 350:
        return None
    f, power = welch(x, fs=fs, nperseg=min(int(2 * fs), x.shape[1]), axis=1)
    integrate = getattr(np, "trapezoid", None) or np.trapz
    broad = integrate(power[:, (f >= 4) & (f < 30)], f[(f >= 4) & (f < 30)], axis=1)
    alpha = integrate(power[:, (f >= 8) & (f < 13)], f[(f >= 8) & (f < 13)], axis=1)
    valid = broad > 1e-8
    return float(np.mean(alpha[valid] / broad[valid])) if np.any(valid) else None


def _candidate_peaks(signal, fs, threshold):
    return find_peaks(signal, prominence=threshold,
                      height=threshold * 0.45,
                      width=(max(2, int(0.05 * fs)), int(0.55 * fs)),
                      distance=max(1, int(0.28 * fs)))


def _round_pen(color, width):
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    return pen


class EyeEstimator:
    """Keep EEG filtering and event detection independent of Qt rendering."""

    def __init__(self, fs, names):
        self.fs = int(fs)
        self.front = [names.index(name) for name in ("AF7", "AF8")]
        self.back = [names.index(name) for name in ("TP9", "TP10")]
        self.sos = butter(2, (0.8, 8), btype="bandpass", fs=fs, output="sos")
        self.reset()

    def reset(self):
        self.zi = None
        self.front_history = np.empty((2, 0))
        self.back_history = np.empty((2, 0))
        self.sample_count = 0
        self.last_peak_index = -10 * self.fs
        self.blink_sign = 0
        self.blink_threshold = None
        self.open_noise = None

    def feed(self, block, detect=True):
        x = np.asarray(block, dtype=float)
        if x.ndim != 2 or x.shape[1] == 0 or x.shape[0] <= max(self.front + self.back):
            return np.empty((2, 0)), False
        front = x[self.front]
        back = x[self.back]
        if not np.all(np.isfinite(front)) or not np.all(np.isfinite(back)):
            return np.empty((2, 0)), False
        if self.zi is None:
            self.zi = sosfilt_zi(self.sos)[:, None, :] * front[None, :, :1]
        filtered, self.zi = sosfilt(self.sos, front, axis=1, zi=self.zi)
        self.front_history = np.concatenate((self.front_history, filtered), axis=1)[:, -2*self.fs:]
        self.back_history = np.concatenate((self.back_history, back), axis=1)[:, -8*self.fs:]
        self.sample_count += x.shape[1]
        if not detect or self.blink_threshold is None:
            return filtered, False
        signal = self.blink_sign * self.front_history.mean(axis=0)
        peaks, _ = _candidate_peaks(signal, self.fs, self.blink_threshold)
        origin = self.sample_count - len(signal)
        for peak in peaks[::-1]:
            index = origin + int(peak)
            if (index <= self.last_peak_index or
                    index - self.last_peak_index < int(0.32 * self.fs) or
                    self.sample_count - index < int(0.035 * self.fs) or
                    self.sample_count - index > int(0.55 * self.fs)):
                continue
            # A blink usually reaches both frontal electrodes in the same direction.
            pair = self.blink_sign * self.front_history[:, peak]
            if np.min(pair) < self.blink_threshold * 0.12:
                continue
            self.last_peak_index = index
            return filtered, True
        return filtered, False

    def calibrate_open(self, filtered):
        x = np.asarray(filtered, dtype=float).mean(axis=0)
        self.open_noise = max(1.0, 1.4826 * np.median(np.abs(x - np.median(x))))

    def calibrate_blinks(self, filtered):
        if self.open_noise is None:
            return False
        x = np.asarray(filtered, dtype=float).mean(axis=0)
        candidates = []
        for sign in (1, -1):
            peaks, props = _candidate_peaks(sign * x, self.fs, max(5.0, 3*self.open_noise))
            strengths = sorted(props["prominences"], reverse=True)[:3]
            if len(peaks) >= 2:
                candidates.append((sum(strengths), sign, strengths))
        if not candidates:
            return False
        _, sign, strengths = max(candidates)
        typical = float(np.median(strengths[:2]))
        if typical < max(12.0, 4.0*self.open_noise):
            return False
        self.blink_sign = sign
        self.blink_threshold = max(5.0*self.open_noise, 0.42*typical)
        self.last_peak_index = self.sample_count
        return True


class GazeEstimator:
    """Horizontal glances (left / right) from the AF7 − AF8 difference — an experimental HEOG proxy.

    A horizontal eye movement shifts the corneo-retinal dipole, so the left and right forehead
    electrodes change in OPPOSITE directions; a blink moves both the same way. After a 0.3–6 Hz
    band-pass each gaze step becomes a transient whose sign gives the direction. Polarity differs
    between people and headset fits, so it is learned from one calibrated left and right glance.
    The band-pass cannot hold a sustained gaze, so the state returns to centre after RETURN_SEC
    without a returning transient."""

    RETURN_SEC = 6.0          # no return seen: show centre after this long (the gaze itself is unobservable)
    PENDING_RETURN_SEC = 30.0 # …but still expect that return: the next opposite swing = "back to centre"
    RETURN_GAP_SEC = 0.12     # quick look-and-back: the return may follow the glance this soon
    REPEAT_GAP_SEC = 0.35     # same direction again: avoid double events from one movement

    def __init__(self, fs, names):
        self.fs = int(fs)
        self.idx = [names.index("AF7"), names.index("AF8")]
        self.sos = butter(2, (0.3, 6.0), btype="bandpass", fs=fs, output="sos")
        self.reset()

    def reset(self):
        self.zi = None
        self.h_history = np.empty(0)          # AF7 − AF8 (filtered), last 2 s
        self.c_history = np.empty(0)          # common mode (AF7 + AF8) / 2, last 2 s
        self.sample_count = 0
        self.last_event_index = -10 * self.fs
        self.noise = None
        self.threshold = None
        self.left_sign = 0
        self.state = "center"
        self.state_since = 0
        self.armed = True                     # re-armed once |h| falls below half the threshold
        self.unreturned = None                # direction whose return was never seen (after timeout)

    def feed(self, block, detect=True):
        """Returns (filtered AF7 − AF8 for this block, event or None); event ∈ left / right / center."""
        x = np.asarray(block, dtype=float)
        if x.ndim != 2 or x.shape[1] == 0 or x.shape[0] <= max(self.idx):
            return np.empty(0), None
        front = x[self.idx]
        if not np.all(np.isfinite(front)):
            return np.empty(0), None
        if self.zi is None:
            self.zi = sosfilt_zi(self.sos)[:, None, :] * front[None, :, :1]
        f, self.zi = sosfilt(self.sos, front, axis=1, zi=self.zi)
        h, c = f[0] - f[1], (f[0] + f[1]) / 2
        keep = 2 * self.fs
        self.h_history = np.concatenate((self.h_history, h))[-keep:]
        self.c_history = np.concatenate((self.c_history, c))[-keep:]
        self.sample_count += x.shape[1]
        if not detect or self.threshold is None:
            return h, None
        if self.state != "center" and self.sample_count - self.state_since > self.RETURN_SEC * self.fs:
            self.unreturned = self.state                             # shown as centre, return still expected
            self.state = "center"
        if self.unreturned and self.sample_count - self.state_since > self.PENDING_RETURN_SEC * self.fs:
            self.unreturned = None
        # Trigger on the threshold CROSSING (rising edge), not the peak: the state changes ~50 ms
        # after the eye moves instead of ~300 ms later. Re-arm only after |h| falls below half the
        # threshold, so one eye movement gives one event.
        origin = self.sample_count - len(h)
        event = None
        for i in range(len(h)):
            a = abs(h[i])
            if not self.armed:
                if a < 0.5 * self.threshold: self.armed = True
                continue
            index = origin + i
            if a < self.threshold:
                continue
            direction = "left" if np.sign(h[i]) == self.left_sign else "right"
            late_return = self.state == "center" and self.unreturned not in (None, direction)
            returning = self.state not in ("center", direction) or late_return   # eyes coming back
            gap = self.RETURN_GAP_SEC if returning else self.REPEAT_GAP_SEC
            if index - self.last_event_index < int(gap * self.fs):
                continue
            # Same-direction change on both electrodes = blink. A return often comes with a blink,
            # so returns tolerate more common mode; a blink alone hardly moves AF7 − AF8 anyway.
            # A rejected sample does NOT disarm: later samples of the same swing (after the blink
            # has passed) can still be accepted.
            if abs(c[i]) > (1.5 if returning else 0.6) * a:
                continue
            self.armed = False
            self.last_event_index = index
            if late_return or self.state not in ("center", direction):
                self.state, event = "center", "center"
            else:
                self.state, event = direction, direction
            self.unreturned = None
            self.state_since = index
        return h, event

    def calibrate_noise(self, h):
        h = np.asarray(h, dtype=float)
        self.noise = max(1.0, 1.4826 * np.median(np.abs(h - np.median(h))))

    def _first_glance(self, h):
        """Sign and size of the FIRST large transient (going out), not the return."""
        a = np.abs(h)
        peaks, props = find_peaks(a, prominence=max(5.0, 3 * (self.noise or 1.0)),
                                  width=(int(0.04 * self.fs), int(1.0 * self.fs)))
        if not len(peaks): return 0, 0.0
        big = props["prominences"] >= 0.5 * props["prominences"].max()
        first = peaks[big][0]
        return int(np.sign(h[first])), float(a[first])

    def calibrate(self, h_left, h_right):
        """Learn polarity and threshold from one glance left (and back) and one glance right."""
        if self.noise is None:
            return False, "Complete step 1 (eyes open) first."
        sl, al = self._first_glance(np.asarray(h_left, dtype=float))
        sr, ar = self._first_glance(np.asarray(h_right, dtype=float))
        floor = max(10.0, 4 * self.noise)
        if min(al, ar) < floor:
            return False, "Glance was too small to detect. Look further to the side (eyes only) and repeat."
        if sl == sr:
            return False, "Left and right glances looked the same. Repeat both, keeping your head still."
        self.left_sign = sl
        self.threshold = max(4 * self.noise, 0.45 * min(al, ar))
        self.last_event_index = self.sample_count
        self.state = "center"
        self.armed = True
        self.unreturned = None
        return True, ""


class EyeCanvas(QtWidgets.QWidget):
    def __init__(self, ext):
        super().__init__()
        self.ext = ext
        self.theme = None
        self.openness = 1.0
        self.gaze = 0.0                   # −1 = screen left … +1 = screen right (mirror view)
        self.setMinimumSize(380, 300)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def advance(self):
        target = 0.0 if self.ext.closed else 1.0
        age = time.monotonic() - self.ext.blink_started
        if 0 <= age < 0.30 and not self.ext.closed:
            target = 1 - age/0.11 if age < 0.11 else min(1.0, (age-0.11)/0.19)
        self.openness += (max(0.0, min(1.0, target)) - self.openness) * 0.42
        # mirror view: when you look to YOUR left the avatar's pupils move to the screen's left
        goal = {"left": -1.0, "right": 1.0}.get(getattr(self.ext, "gaze_state", "center"), 0.0)
        self.gaze += (goal - self.gaze) * 0.7                    # ~0.1 s to follow the eyes
        self.update()

    def paintEvent(self, event):
        th = self.theme or {"base": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e"}
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(th["base"]))
        scale = min(self.width()/560, self.height()/440)
        painter.translate(self.width()/2, self.height()/2)
        painter.scale(scale, scale)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#c78e6a"))
        painter.drawEllipse(QtCore.QRectF(-190, -188, 380, 370))
        painter.setBrush(QtGui.QColor("#dbab83"))
        painter.drawEllipse(QtCore.QRectF(-172, -180, 344, 350))
        for side in (-1, 1):
            x = side*83
            opening = max(0.0, self.openness)
            painter.setPen(_round_pen("#4a3029", 5))
            painter.drawLine(QtCore.QPointF(x-51, -50), QtCore.QPointF(x+51, -50))
            if opening > 0.12:
                painter.setPen(QtGui.QPen(QtGui.QColor("#4a3029"), 4))
                painter.setBrush(QtGui.QColor("#f7eee6"))
                painter.drawEllipse(QtCore.QRectF(x-53, -27*opening, 106, 54*opening))
                painter.setPen(QtCore.Qt.NoPen)
                px = x + self.gaze * 30
                painter.setBrush(QtGui.QColor("#3d5b62"))
                painter.drawEllipse(QtCore.QRectF(px-15, -15*opening, 30, 30*opening))
                painter.setBrush(QtGui.QColor("#171c22"))
                painter.drawEllipse(QtCore.QRectF(px-7, -7*opening, 14, 14*opening))
            else:
                painter.setPen(_round_pen("#4a3029", 5))
                painter.drawLine(QtCore.QPointF(x-51, 0), QtCore.QPointF(x+51, 0))
        painter.setPen(_round_pen("#925f47", 5))
        painter.drawLine(QtCore.QPointF(0, 13), QtCore.QPointF(-8, 71))
        painter.drawLine(QtCore.QPointF(-8, 71), QtCore.QPointF(15, 75))
        painter.setPen(_round_pen("#6b4035", 4))
        painter.drawArc(QtCore.QRectF(-45, 91, 90, 37), 190*16, 160*16)
        painter.end()


class EyeTab(BaseTab):
    title = "Eyes · EEG/alpha"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        self.generation = 0
        self.info = None
        layout = QtWidgets.QVBoxLayout(self)
        self.status = QtWidgets.QLabel("Waiting for EEG…")
        layout.addWidget(self.status)
        self.canvas = EyeCanvas(ext)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self._build_plots(ctx))
        splitter.setSizes([320, 220])
        layout.addWidget(splitter, 1)
        row = QtWidgets.QHBoxLayout()
        for label, kind in (("1 · Eyes open", "open"), ("2 · Eyes closed", "closed"),
                            ("3 · Blink 3×", "blink"), ("4 · Glance left", "left"), ("5 · Glance right", "right")):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda _=False, k=kind: self.begin(k))
            row.addWidget(button)
        layout.addLayout(row)
        self.info = ctx.plots.muted_label(
            "Calibrate in order: look forward with eyes open, eyes closed, then blink three times. "
            "Optional 4–5: glance left / right with the eyes only and come back. "
            "Wait for GO before each step and keep your head still.")
        layout.addWidget(self.info)
        layout.addWidget(ctx.plots.muted_label(
            "Experimental visual feedback. Alpha may not distinguish open and closed eyes for everyone."))

    # ---- detection plots (time domain, shared time axis / time range / event markers) ---------
    def _build_plots(self, ctx):
        gfx = ctx.plots.widget(pg.GraphicsLayoutWidget())
        gfx.setMinimumHeight(240)
        self.eog_plot = ctx.plots.plot(gfx.addPlot(row=0, col=0), marker="eeg")
        self.eog_plot.setLabel("left", "Blink µV"); self.eog_plot.hideAxis("bottom")
        self.eog_plot.setClipToView(True); self.eog_plot.setDownsampling(auto=True, mode="peak")
        self.eog_curve = self.eog_plot.plot()
        self.blink_marks = pg.ScatterPlotItem(symbol="t", size=11)
        self.eog_plot.addItem(self.blink_marks)
        self.blink_thr = pg.InfiniteLine(angle=0, movable=False); self.blink_thr.hide()
        self.eog_plot.addItem(self.blink_thr)
        self.gaze_plot = ctx.plots.plot(gfx.addPlot(row=1, col=0), marker="eeg")
        self.gaze_plot.setLabel("left", "Gaze µV"); self.gaze_plot.hideAxis("bottom")
        self.gaze_plot.setXLink(self.eog_plot)
        self.gaze_plot.setClipToView(True); self.gaze_plot.setDownsampling(auto=True, mode="peak")
        self.gaze_curve = self.gaze_plot.plot()
        self.gaze_marks = pg.ScatterPlotItem(size=12)
        self.gaze_plot.addItem(self.gaze_marks)
        self.gaze_thr = [pg.InfiniteLine(angle=0, movable=False) for _ in range(2)]
        for line in self.gaze_thr: line.hide(); self.gaze_plot.addItem(line)
        self.alpha_plot = ctx.plots.plot(gfx.addPlot(row=2, col=0), marker="eeg")
        self.alpha_plot.setLabel("left", "Alpha"); self.alpha_plot.setLabel("bottom", "Time", units="s")
        self.alpha_plot.setXLink(self.eog_plot)
        for plot in (self.eog_plot, self.gaze_plot, self.alpha_plot):
            plot.getAxis("left").enableAutoSIPrefix(False)              # show 0.2…0.8, not "×0.001"
            plot.getAxis("left").setWidth(54)                            # aligned left edges
        self.alpha_curve = self.alpha_plot.plot(symbol="o", symbolSize=4)
        self.alpha_thr = pg.InfiniteLine(angle=0, movable=False); self.alpha_thr.hide()
        self.alpha_plot.addItem(self.alpha_thr)
        self.closed_regions, self.closed_lines = [], []
        return gfx

    def refresh_plots(self):
        ext, st = self.ext, self.ctx.store
        clock = st.clock["eeg"]
        ref = st.time_ref("eeg")
        n = min(ext.eog.n, st.eeg.n)
        if n >= 2 and ref is not None:
            sign = ext.estimator.blink_sign or 1
            self.eog_curve.setData(st.time_axis("eeg", n), sign * ext.eog.get(n)[0])
        thr = ext.estimator.blink_threshold
        if thr: self.blink_thr.setPos(thr); self.blink_thr.show()
        else: self.blink_thr.hide()
        g = ext.gaze
        ng = min(ext.heog.n, st.eeg.n)
        if ng >= 2 and ref is not None:
            sign = g.left_sign or 1                       # "left" glances drawn upward
            self.gaze_curve.setData(st.time_axis("eeg", ng), sign * ext.heog.get(ng)[0])
        for line, k in zip(self.gaze_thr, (1, -1)):
            if g.threshold: line.setPos(k * g.threshold); line.show()
            else: line.hide()
        if ref is None: return
        if ext.glances:
            sym = {"left": "t3", "right": "t2", "center": "o"}
            self.gaze_marks.setData([dict(pos=(t - ref, v), symbol=sym[kind], size=7 if kind == "center" else 12,
                                          brush=self._gaze_brush[kind]) for t, kind, v in ext.glances])
        else:
            self.gaze_marks.clear()
        if ext.blinks:
            bt = np.array([b[0] for b in ext.blinks]); bv = np.array([b[1] for b in ext.blinks])
            self.blink_marks.setData(bt - ref, bv)
        else:
            self.blink_marks.clear()
        if ext.alpha_series:
            a = np.array(ext.alpha_series)
            self.alpha_curve.setData(a[:, 0] - ref, a[:, 1])
        else:
            self.alpha_curve.clear()
        if ext.alpha_threshold is not None: self.alpha_thr.setPos(ext.alpha_threshold); self.alpha_thr.show()
        else: self.alpha_thr.hide()
        # closed intervals: shaded from recognition of closure to recognition of reopening
        while len(self.closed_regions) < len(ext.closed_periods):
            region = pg.LinearRegionItem(movable=False); region.setZValue(-10)
            for line in region.lines: line.setPen(pg.mkPen(None))
            line = pg.InfiniteLine(angle=90, movable=False, label="closed", labelOpts=dict(position=0.85))
            self.alpha_plot.addItem(region); self.alpha_plot.addItem(line)
            self.closed_regions.append(region); self.closed_lines.append(line)
            self._style_closed(region, line)
        last = st.last_ts["eeg"]
        for (t0, t1), region, line in zip(ext.closed_periods, self.closed_regions, self.closed_lines):
            region.setRegion((t0 - ref, (t1 if t1 is not None else last) - ref)); region.show()
            line.setPos(t0 - ref); line.show()
        for region, line in zip(self.closed_regions[len(ext.closed_periods):], self.closed_lines[len(ext.closed_periods):]):
            region.hide(); line.hide()

    def _style_closed(self, region, line):
        th = self.ctx.th
        c = QtGui.QColor(th["hbr"]); c.setAlpha(55)
        region.setBrush(pg.mkBrush(c))
        line.setPen(pg.mkPen(th["hbr"], width=1.5))
        line.label.setColor(th["hbr"])

    def begin(self, kind):
        if not self.ext.samples_seen:
            self.info.setText("Connect Athena and wait for EEG first.")
            return
        if kind != "open" and self.ext.open_alpha is None:
            self.info.setText("Complete step 1 first.")
            return
        if kind == "blink" and self.ext.closed_alpha is None:
            self.info.setText("Complete step 2 first.")
            return
        if kind == "right" and self.ext.left_capture is None:
            self.info.setText("Complete step 4 (glance left) first.")
            return
        self.generation += 1
        generation = self.generation
        self.ext.capture_kind = None
        what = {"left": "glance LEFT with your eyes only, hold ~1 s, then back to centre",
                "right": "glance RIGHT with your eyes only, hold ~1 s, then back to centre"}.get(kind, kind)
        self.info.setText(f"Get ready: {what}. GO in one second…")
        QtCore.QTimer.singleShot(1000, lambda: self._start(kind, generation))

    def _start(self, kind, generation):
        if generation != self.generation:
            return
        self.ext.capture_kind = kind
        self.ext.capture_raw = []
        self.ext.capture_filtered = []
        self.ext.capture_h = []
        self.info.setText(f"GO: {kind} · keep your head still until capture ends.")

    def on_frame(self):
        self.canvas.advance()
        self.refresh_plots()

    def update_texts(self):
        state = "closed (alpha)" if self.ext.closed else "open"
        if not self.ext.alpha_enabled:
            state = "closure uncalibrated" if self.ext.closed_alpha is None else "alpha inconclusive"
        blink = f" · blinks: {self.ext.blink_count}" if self.ext.estimator.blink_threshold else ""
        ratio = f" · alpha: {self.ext.last_alpha:.2f}" if self.ext.last_alpha is not None else ""
        gaze = ""
        g = self.ext.gaze
        if g.threshold:
            swing = float(np.max(np.abs(g.h_history))) if len(g.h_history) else 0.0
            gaze = (f" · gaze: {self.ext.gaze_state} (L {self.ext.glance_count['left']} / "
                    f"R {self.ext.glance_count['right']}) · swing {swing:.0f}/{g.threshold:.0f} µV")
        self.status.setText(f"Eyes: {state}{blink}{gaze}{ratio}")

    def on_analysis(self):
        self.ext.analyze_alpha()

    def apply_theme(self, th):
        self.canvas.set_theme(th)
        self.eog_curve.setPen(pg.mkPen(th["eeg"][1], width=1.2))
        self.blink_marks.setBrush(pg.mkBrush(th["event"])); self.blink_marks.setPen(pg.mkPen(th["bg"], width=1))
        self.alpha_curve.setPen(pg.mkPen(th["eeg"][0], width=1.6))
        self.alpha_curve.setSymbolBrush(pg.mkBrush(th["eeg"][0])); self.alpha_curve.setSymbolPen(None)
        self.gaze_curve.setPen(pg.mkPen(th["eeg"][2], width=1.2))
        self._gaze_brush = {"left": pg.mkBrush(th["hbo"]), "right": pg.mkBrush(th["hbr"]),
                            "center": pg.mkBrush(th["muted"])}
        self.gaze_marks.setPen(pg.mkPen(th["bg"], width=1))
        for item in (self.blink_thr, self.alpha_thr, *self.gaze_thr):
            item.setPen(pg.mkPen(th["muted"], width=1, style=QtCore.Qt.DashLine))
        for region, line in zip(self.closed_regions, self.closed_lines): self._style_closed(region, line)

    def clear(self):
        self.generation += 1
        self.ext.reset()
        self.canvas.openness = 1.0
        self.canvas.update()
        for c in (self.eog_curve, self.alpha_curve, self.blink_marks, self.gaze_curve, self.gaze_marks): c.clear()
        self.canvas.gaze = 0.0
        self.refresh_plots()


class EyeInteraction(Extension):
    id = "eye_interaction"
    name = "Eye Interaction"
    version = "0.1.0"
    description = ("Experimental blink and left/right glance detection from frontal EEG, and eye closure "
                   "from posterior alpha.")

    @classmethod
    def supports(cls, spec):
        return {"AF7", "AF8", "TP9", "TP10"} <= set(spec.eeg.names)

    def activate(self, app):
        self.estimator = EyeEstimator(app.spec.eeg.fs, app.spec.eeg.names)
        self.gaze = GazeEstimator(app.spec.eeg.fs, app.spec.eeg.names)
        self.eog = Ring(1, int(app.spec.eeg.fs * app_config.MAX_WINDOW_SEC))   # filtered AF7/AF8 mean
        self.heog = Ring(1, int(app.spec.eeg.fs * app_config.MAX_WINDOW_SEC))  # filtered AF7 − AF8
        self.reset()
        self.tab = app.add_tab(EyeTab(app.view, self))

    def reset(self):
        self.estimator.reset()
        self.gaze.reset()
        self.heog.clear()
        self.gaze_state = "center"
        self.glances = []           # [(t, "left" | "right" | "center", value)]
        self.glance_count = {"left": 0, "right": 0}
        self.left_capture = None
        self.capture_h = []
        self.samples_seen = 0
        self.capture_kind = None
        self.capture_raw = []
        self.capture_filtered = []
        self.open_alpha = self.closed_alpha = None
        self.alpha_threshold = None
        self.alpha_enabled = False
        self.closed = False
        self.closed_votes = self.open_votes = 0
        self.last_alpha = None
        self.blink_count = 0
        self.blink_started = -1e9
        self.motion_until = 0.0
        self.last_alpha_check = 0.0
        self.last_ts = None
        self.eog.clear()
        self.blinks = []            # [(t_peak, value)] counted blinks, timestamps on the EEG clock
        self.alpha_series = []      # [(t, alpha ratio)] — t = timestamp of the newest sample in the window
        self.closed_periods = []    # [[t_recognised_closed, t_recognised_open | None]]

    def on_imu(self, x, ts):
        imu = np.asarray(x, dtype=float)
        if imu.ndim != 2 or imu.shape[0] < 6 or imu.shape[1] == 0:
            return
        moving = (np.max(np.linalg.norm(imu[3:6], axis=0)) > 35 or
                  np.max(np.abs(np.linalg.norm(imu[:3], axis=0) - 1)) > 0.25)
        if moving:
            self.motion_until = time.monotonic() + 0.25

    def on_eeg(self, x, ts):
        self.samples_seen += x.shape[1]
        filtered, blink = self.estimator.feed(x, detect=self.capture_kind is None)
        h, glance = self.gaze.feed(x, detect=self.capture_kind is None)
        if filtered.shape[1]:
            self.eog.extend(filtered.mean(axis=0, keepdims=True))
        if len(h):
            self.heog.extend(h[None, :])
        self.last_ts = float(ts)
        if self.capture_kind is not None:
            self.capture_raw.append(np.asarray(x, dtype=float).copy())
            self.capture_filtered.append(filtered.copy())
            self.capture_h.append(h.copy())
            target = int(self.estimator.fs * (4 if self.capture_kind in ("blink", "left", "right") else 5))
            if sum(chunk.shape[1] for chunk in self.capture_raw) >= target:
                self._finish_capture()
            return
        if blink and time.monotonic() >= self.motion_until:
            self.blink_count += 1
            self.blink_started = time.monotonic()
            est = self.estimator
            lag = (est.sample_count - est.last_peak_index - 1) / est.fs          # peak → newest sample
            peak = est.front_history.shape[1] - (est.sample_count - est.last_peak_index)
            value = float(est.blink_sign * est.front_history[:, peak].mean()) if peak >= 0 else 0.0
            self.blinks.append((self.last_ts - lag, value))
        if self.gaze.state != self.gaze_state and glance is None:
            self.gaze_state = self.gaze.state                        # timed return to centre
        if glance and time.monotonic() >= self.motion_until:
            g = self.gaze
            lag = (g.sample_count - g.last_event_index - 1) / g.fs
            peak = len(g.h_history) - (g.sample_count - g.last_event_index)
            value = float((g.left_sign or 1) * g.h_history[peak]) if peak >= 0 else 0.0
            self.glances.append((self.last_ts - lag, glance, value))
            if glance in self.glance_count: self.glance_count[glance] += 1
            self.gaze_state = g.state
        elif glance:
            self.gaze.state = self.gaze_state                         # ignore during head motion
        self.analyze_alpha()
        self._prune()

    def _prune(self):
        cut = self.last_ts - HISTORY_SEC
        if self.blinks and self.blinks[0][0] < cut: self.blinks = [b for b in self.blinks if b[0] >= cut]
        if self.glances and self.glances[0][0] < cut: self.glances = [g for g in self.glances if g[0] >= cut]
        if self.alpha_series and self.alpha_series[0][0] < cut:
            self.alpha_series = [a for a in self.alpha_series if a[0] >= cut]
        self.closed_periods = [p for p in self.closed_periods if p[1] is None or p[1] >= cut]

    def _finish_capture(self):
        kind = self.capture_kind
        self.capture_kind = None
        raw = np.concatenate(self.capture_raw, axis=1)
        filtered = np.concatenate(self.capture_filtered, axis=1)
        h = np.concatenate(self.capture_h) if self.capture_h else np.empty(0)
        self.capture_raw = self.capture_filtered = []
        self.capture_h = []
        if kind == "left":
            self.left_capture = h
            self.tab.info.setText("Step 4 done. Click step 5 and glance RIGHT on GO, then back to centre.")
            return
        if kind == "right":
            ok, why = self.gaze.calibrate(self.left_capture, h)
            self.tab.info.setText("Glance calibration complete. Look left / right with your eyes only." if ok else why)
            if not ok: self.left_capture = None
            return
        if kind in ("open", "closed"):
            # Skip the first second, which may contain the opening/closing blink.
            back = raw[self.estimator.back, self.estimator.fs:]
            ratio = relative_alpha(back, self.estimator.fs)
            if ratio is None:
                self.tab.info.setText("Posterior EEG was too noisy or incomplete. Repeat this step.")
                return
            if kind == "open":
                self.open_alpha = ratio
                self.closed_alpha = None
                self.alpha_enabled = False
                self.estimator.calibrate_open(filtered[:, self.estimator.fs:])
                self.gaze.calibrate_noise(h[self.estimator.fs:])
                self.tab.info.setText("Step 1 done. Click step 2, then close your eyes on GO.")
            else:
                self.closed_alpha = ratio
                self.alpha_enabled = (ratio > self.open_alpha*1.25 and
                                      ratio - self.open_alpha > 0.025)
                self.alpha_threshold = (ratio + self.open_alpha)/2 if self.alpha_enabled else None
                msg = ("Step 2 done. Click step 3 and blink three times on GO." if self.alpha_enabled else
                       "Alpha did not separate open/closed states. Blink animation can still work; click step 3.")
                self.tab.info.setText(msg)
        else:
            if self.estimator.calibrate_blinks(filtered):
                self.tab.info.setText("Calibration complete. Blink naturally; keep your head still.")
            else:
                self.tab.info.setText("Could not identify two clear blinks. Keep still and repeat step 3.")

    def analyze_alpha(self):
        """Every ~0.45 s: alpha ratio for the plot (always) and the open/closed decision (only after
        calibration enabled it). Runs from the EEG hook so it works while the tab is hidden."""
        if self.capture_kind is not None:
            return
        now = time.monotonic()
        if now - self.last_alpha_check < ALPHA_EVERY_SEC or now < self.motion_until:
            return
        self.last_alpha_check = now
        ratio = relative_alpha(self.estimator.back_history, self.estimator.fs)
        self.last_alpha = ratio
        if ratio is not None and self.last_ts is not None:
            self.alpha_series.append((self.last_ts, ratio))
        if not self.alpha_enabled:
            return
        if ratio is None:
            self.closed_votes = self.open_votes = 0
            return
        was_closed = self.closed
        if ratio > self.alpha_threshold:
            self.closed_votes += 1
            self.open_votes = 0
            if self.closed_votes >= 2:
                self.closed = True
        else:
            self.open_votes += 1
            self.closed_votes = 0
            if self.open_votes >= 2:
                self.closed = False
        if self.closed and not was_closed:
            self.closed_periods.append([self.last_ts, None])          # moment closure was recognised
        elif was_closed and not self.closed and self.closed_periods:
            self.closed_periods[-1][1] = self.last_ts

    def on_disconnected(self):
        self.tab.clear()


EXTENSION = EyeInteraction
