"""Plot/widget registry so the theme and time range change everywhere at once.

Every tab/page creates plots through ``PlotRegistry`` → MainWindow need not know the details of each plot."""
from dataclasses import dataclass

from PySide6 import QtWidgets


@dataclass
class MarkerTarget:
    plot: object            # PlotItem
    stream: str             # "eeg" | "opt" | "imu" — which stream's time axis to use
    show_label: bool = False
    on_image: bool = False  # drawn over a colormap → uses its own contrasting colour


class PlotRegistry:
    def __init__(self, window_sec):
        self.window_sec = float(window_sec)
        self.widgets, self.plots, self.legends, self.muted = [], [], [], []
        self.time_plots = []             # plots with a time axis → follow the time range
        self.marker_targets = []
        self._x_locks = {}               # plot → function returning the mandatory (lo, hi) of the x axis

    def widget(self, w):
        self.widgets.append(w); return w

    def plot(self, p, timed=True, marker=None, marker_label=False, on_image=False):
        self.plots.append(p)
        p.showGrid(x=True, y=True, alpha=.25)
        if timed:
            self.time_plots.append(p)
            self.lock_x(p, lambda: (-self.window_sec, 0.0))
        if marker: self.marker_targets.append(MarkerTarget(p, marker, marker_label, on_image))
        return p

    def lock_x(self, p, x_range):
        """The x axis follows only the time range (number box), not the mouse: disable x drag/zoom, hide the
        "A" auto-range button, and restore the range if something else (the "View All" menu…) moves it.
        The y axis is still mouse-adjustable. ``x_range``: (lo, hi) or a function returning (lo, hi)."""
        get = x_range if callable(x_range) else (lambda: x_range)
        self._x_locks[p] = get
        p.setMouseEnabled(x=False, y=True)
        p.enableAutoRange(axis="x", enable=False)
        p.hideButtons()
        p.setXRange(*get(), padding=0)
        p.getViewBox().sigXRangeChanged.connect(lambda *_: self._enforce_x(p))

    def _enforce_x(self, p):
        lo, hi = self._x_locks[p]()
        cur = p.getViewBox().viewRange()[0]
        if abs(cur[0] - lo) > 1e-6 or abs(cur[1] - hi) > 1e-6:
            p.setXRange(lo, hi, padding=0)

    def forget_under(self, root):
        """Unregister every plot/widget inside ``root`` (a tab about to be removed). Returns the removed PlotItems."""
        def inside(w):
            return w is not None and (w is root or root.isAncestorOf(w))

        def view_of(item):
            try: return item.getViewWidget()
            except RuntimeError: return None
        gone = {p for p in self.plots if view_of(p) is None or inside(view_of(p))}
        self.plots = [p for p in self.plots if p not in gone]
        self.time_plots = [p for p in self.time_plots if p not in gone]
        self.marker_targets = [t for t in self.marker_targets if t.plot not in gone]
        for p in gone: self._x_locks.pop(p, None)
        self.widgets = [w for w in self.widgets if not inside(w)]
        self.legends = [lg for lg in self.legends if not (lg.scene() and any(inside(v) for v in lg.scene().views()))]
        self.muted = [lab for lab in self.muted if not inside(lab)]
        return gone

    def legend(self, lg):
        self.legends.append(lg); return lg

    def muted_label(self, text, wrap=True):
        lab = QtWidgets.QLabel(text); lab.setWordWrap(wrap); self.muted.append(lab); return lab

    def set_time_range(self, sec):
        self.window_sec = float(sec)
        for p in self.time_plots: p.setXRange(-self.window_sec, 0, padding=0)

    def apply_theme(self, th):
        for w in self.widgets: w.setBackground(th["bg"])
        for p in self.plots:
            for ax in ("left", "bottom", "right", "top"):
                a = p.getAxis(ax); a.setPen(th["fg"]); a.setTextPen(th["fg"])
        for lg in self.legends:
            lg.setLabelTextColor(th["fg"])
            for _, lab in lg.items: lab.setText(lab.text)
        for lab in self.muted: lab.setStyleSheet(f"color: {th['muted']}")
