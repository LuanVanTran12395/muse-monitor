import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ... import config as C
from ..theme import text_on
from ..widgets.head_map import HeadWidget
from ..widgets.indicators import fill_quality_labels, quality_summary


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
        self.graphics.setAccessibleName(f"Fit-test traces, {sp.eeg.n} channels")
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
        self.accept_btn.clicked.connect(self._on_accept)
        self.last_qs = None
        self.accepted = None            # contact quality when Accept was pressed (→ session.json "fit_test")
        bottom.addWidget(self.disc_btn); bottom.addSpacing(16); bottom.addWidget(self.summary, 1); bottom.addWidget(self.accept_btn)
        v.addLayout(bottom)

    def set_device(self, name):
        """A new stream started: new fit-test, the previous Accept no longer applies."""
        self.title.setText(f"<h2>Fit-test · {name}</h2>")
        self.accepted = None

    def set_battery_html(self, html):
        self.batt.setText(html)

    def set_disconnect_enabled(self, on):
        self.disc_btn.setEnabled(on)

    # ---- Accept ---------------------------------------------------------------
    WEAK = ("Bad", "No signal", "—")        # Fair is allowed without asking; it is still shown and recorded

    def weak_channels(self):
        """[(name, level)] of channels whose contact is Bad / No signal / not measured yet."""
        names = self.ctx.spec.eeg.names
        if not self.last_qs: return [(n, "—") for n in names]
        return [(n, q[0]) for n, q in zip(names, self.last_qs) if q[0] in self.WEAK]

    def confirm_weak_contact(self, weak):
        """Ask before recording with poor contact; True = continue anyway."""
        listing = ", ".join(f"{n} {lvl if lvl != '—' else 'not measured'}" for n, lvl in weak)
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Poor electrode contact",
                                    f"{listing}.", parent=self)
        box.setInformativeText("Data from these channels will probably be unusable. Adjust the headset, "
                               "or continue if you only need the other channels.")
        go = box.addButton("Continue anyway", QtWidgets.QMessageBox.AcceptRole)
        keep = box.addButton("Keep adjusting", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(keep); box.setEscapeButton(keep)
        box.exec()
        return box.clickedButton() is go

    def _on_accept(self):
        weak = self.weak_channels()
        if weak and not self.confirm_weak_contact(weak): return
        self.accepted = self.quality_record(accepted=True)
        self.accept_clicked.emit()

    def fit_test_for_recording(self):
        """session.json "fit_test": the snapshot taken at Accept, or — when recording starts without Accept
        on this connection (⌘R from the fit-test page) — the quality right now, marked accepted=False."""
        return self.accepted or self.quality_record(accepted=False)

    def quality_record(self, accepted):
        """JSON-ready snapshot of the current contact quality (see docs/EXTENSIONS.md ▸ session.json)."""
        def num(v):
            v = float(v)
            return round(v, 2) if math.isfinite(v) else None      # NaN/inf are not valid JSON
        names = self.ctx.spec.eeg.names
        qs = self.last_qs or [None] * len(names)
        chans = {n: (dict(level=q[0], signal_rms_uv=num(q[1]), mains_rms_uv=num(q[2])) if q else dict(level="—"))
                 for n, q in zip(names, qs)}
        return dict(accepted=accepted, measured_unix=time.time(),
                    all_good=bool(chans) and all(c["level"] == "Good" for c in chans.values()), channels=chans)

    def set_quality(self, qs):
        self.last_qs = qs
        sp = self.ctx.spec
        self.head.set_quality({n: (qs[i][0] if qs else "—") for i, n in enumerate(sp.eeg.names)})
        n_good = sum(q[0] == "Good" for q in qs) if qs else 0
        ready = n_good == sp.eeg.n
        self.summary.setText(f"<b>{n_good}/{sp.eeg.n}</b> channels Good" + ("  ✓ Ready to record" if ready else ""))
        good = self.ctx.th["q"]["Good"]
        self.accept_btn.setStyleSheet(f"background:{good};color:{text_on(good)};font-weight:bold" if ready else "")
        fill_quality_labels(self.q_labels, sp.eeg.names, qs, self.ctx.th)
        self.graphics.setAccessibleDescription(quality_summary(sp.eeg.names, qs))
        self.accept_btn.setAccessibleDescription(self.summary.text().replace("<b>", "").replace("</b>", ""))

    def clear(self):
        for c in self.curves: c.clear()
        self.accepted = None

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
