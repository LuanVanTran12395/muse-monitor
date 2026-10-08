import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ... import config as C
from ..widgets.head_map import HeadWidget
from ..widgets.indicators import fill_quality_labels


class FitPage(QtWidgets.QWidget):
    """Screen 2: check electrode contact before recording."""
    accept_clicked = QtCore.Signal()
    disconnect_clicked = QtCore.Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        sp, reg = ctx.spec, ctx.plots
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(30, 20, 30, 20)
        top = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("<h2>Fit-test</h2>")
        self.batt = QtWidgets.QLabel("🔋 —")
        top.addWidget(self.title); top.addStretch(); top.addWidget(self.batt)
        v.addLayout(top)
        v.addWidget(reg.muted_label("Adjust the headset so it sits snugly on the skin (wipe the forehead, move hair away "
                                    f"behind the ears) until all {sp.eeg.n} electrodes turn green. Sit still and relax your jaw."))
        mid = QtWidgets.QHBoxLayout()
        positions = getattr(ctx.profile, "electrode_positions", None)
        self.head = HeadWidget(sp.eeg.names, positions); mid.addWidget(self.head, 2)
        self.graphics = reg.widget(pg.GraphicsLayoutWidget())
        self.curves, self.q_labels = [], []
        for i in range(sp.eeg.n):
            lab = self.graphics.addLabel(row=i, col=0); lab.setFixedWidth(120); self.q_labels.append(lab)
            p = reg.plot(self.graphics.addPlot(row=i, col=1), timed=False)
            p.setYRange(-C.FIT_RANGE_UV, C.FIT_RANGE_UV, padding=0)
            reg.lock_x(p, (-C.FIT_SEC, 0.0))          # fixed fit-test window, no x drag/zoom
            p.enableAutoRange(enable=False); p.hideAxis("bottom"); p.getAxis("left").setWidth(40)
            p.showGrid(x=False, y=True, alpha=.15)
            self.curves.append(p.plot())
        mid.addWidget(self.graphics, 3)
        v.addLayout(mid, 1)
        bottom = QtWidgets.QHBoxLayout()
        self.disc_btn = QtWidgets.QPushButton("Disconnect"); self.disc_btn.clicked.connect(self.disconnect_clicked)
        self.summary = QtWidgets.QLabel("")
        self.accept_btn = QtWidgets.QPushButton("Accept  →"); self.accept_btn.setMinimumHeight(44); self.accept_btn.setMinimumWidth(180)
        self.accept_btn.clicked.connect(self.accept_clicked)
        bottom.addWidget(self.disc_btn); bottom.addSpacing(16); bottom.addWidget(self.summary, 1); bottom.addWidget(self.accept_btn)
        v.addLayout(bottom)

    def set_device(self, name):
        self.title.setText(f"<h2>Fit-test · {name}</h2>")

    def set_battery_html(self, html):
        self.batt.setText(html)

    def set_disconnect_enabled(self, on):
        self.disc_btn.setEnabled(on)

    def set_quality(self, qs):
        sp = self.ctx.spec
        self.head.set_quality({n: (qs[i][0] if qs else "—") for i, n in enumerate(sp.eeg.names)})
        n_good = sum(q[0] == "Good" for q in qs) if qs else 0
        ready = n_good == sp.eeg.n
        self.summary.setText(f"<b>{n_good}/{sp.eeg.n}</b> channels Good" + ("  ✓ Ready to record" if ready else ""))
        self.accept_btn.setStyleSheet("background:#2ea043;color:white;font-weight:bold" if ready else "")
        fill_quality_labels(self.q_labels, sp.eeg.names, qs, self.ctx.th)

    def clear(self):
        for c in self.curves: c.clear()

    def on_frame(self):
        st, fs = self.ctx.store, self.ctx.spec.eeg.fs
        nf = min(st.eeg_f.n, C.FIT_SEC * fs)
        if nf >= 2:
            y = st.eeg_f.get(nf)
            y = y - y.mean(axis=1, keepdims=True)
            t = (np.arange(nf) - nf) / fs
            for i, c in enumerate(self.curves): c.setData(t, y[i])

    def apply_theme(self, th):
        for i, c in enumerate(self.curves): c.setPen(pg.mkPen(th["eeg"][i % 4], width=1))
        self.head.set_colors(th["q"])
